from __future__ import annotations

import json

import httpx

from seldon.config import OpenRouterConfig
from seldon.llm import OpenRouterClient


def test_openrouter_client_retries_with_fallback_model_after_bad_json():
    seen_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_models.append(body["model"])
        if body["model"] == "primary-model":
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        return httpx.Response(200, json={"model": "fallback-model", "choices": [{"message": {"content": "{\"ok\": true}"}}]})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenRouterClient(
        OpenRouterConfig(default_model="primary-model", fallback_models=["fallback-model"]),
        api_key="test-key",
        http_client=http_client,
    )

    assert client.complete_json([{"role": "user", "content": "return json"}]) == {"ok": True}
    assert seen_models == ["primary-model", "fallback-model"]
