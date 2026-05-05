from __future__ import annotations

import json

import httpx
from pydantic import BaseModel

from seldon.config import AgentModelConfig, OpenRouterConfig
from seldon.llm import ModelInvocationRecorder, OpenRouterClient, extract_json_object


class AnswerSchema(BaseModel):
    answer: str


def test_request_payload_construction_uses_profile_and_json_mode():
    client = OpenRouterClient(
        OpenRouterConfig(default_model="balanced-model", fast_model="fast-model"),
        api_key="test-key",
    )

    payload = client.build_payload(
        [{"role": "user", "content": "hello"}],
        system="system prompt",
        model_profile="fast",
        temperature=0.1,
        max_tokens=123,
    )

    assert payload["model"] == "fast-model"
    assert payload["messages"][0] == {"role": "system", "content": "system prompt"}
    assert payload["messages"][1] == {"role": "user", "content": "hello"}
    assert payload["temperature"] == 0.1
    assert payload["max_tokens"] == 123
    assert payload["response_format"] == {"type": "json_object"}


def test_agent_config_overrides_profile_defaults():
    client = OpenRouterClient(OpenRouterConfig(default_model="balanced", reasoning_model="reasoning"))
    payload = client.build_payload(
        [{"role": "user", "content": "think"}],
        agent_config=AgentModelConfig(model_profile="reasoning", temperature=0.2, max_tokens=50),
    )
    assert payload["model"] == "reasoning"
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 50


def test_fallback_model_selection_deduplicates_primary():
    client = OpenRouterClient(OpenRouterConfig(default_model="a", fallback_models=["a", "b", "c"]))
    assert client.candidate_models(model_profile="balanced") == ["a", "b", "c"]
    assert client.candidate_models(model="x") == ["x", "a", "b", "c"]


def test_malformed_json_recovery_from_markdown_and_prose():
    assert extract_json_object('```json\n{"ok": true}\n```') == {"ok": True}
    assert extract_json_object('Here is the answer: {"ok": true, "n": 1}') == {"ok": True, "n": 1}


def test_complete_json_validates_schema_and_records_metadata(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "balanced"
        return httpx.Response(
            200,
            json={
                "model": "balanced",
                "provider": "mock",
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "cost": 0.01},
                "choices": [{"message": {"content": "noise {\"answer\": \"yes\"}"}}],
            },
        )

    recorder_path = tmp_path / "model_invocations.jsonl"
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenRouterClient(
        OpenRouterConfig(default_model="balanced", base_url="https://openrouter.test/api/v1"),
        api_key="test-key",
        http_client=http_client,
        recorder=ModelInvocationRecorder(recorder_path),
    )

    result = client.complete_json(
        [{"role": "user", "content": "question"}],
        schema=AnswerSchema,
        agent="unit-test-agent",
    )

    assert result == {"answer": "yes"}
    records = recorder_path.read_text().splitlines()
    assert len(records) == 1
    row = json.loads(records[0])
    assert row["model"] == "balanced"
    assert row["provider"] == "mock"
    assert row["usage"]["total_tokens"] == 3
    assert row["agent"] == "unit-test-agent"
    assert row["ok"] is True
