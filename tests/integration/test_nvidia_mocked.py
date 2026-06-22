"""NVIDIA NIM client path (mocked transport).

NIM is OpenAI-compatible, so the same client serves it. These tests assert the
request targets the NIM endpoint with Bearer auth and without OpenRouter-only
attribution headers, and that build_llm_client routes provider config correctly.
"""
from __future__ import annotations

import json

import httpx

from seldon.config import LLMProviderConfig, SeldonConfig, provider_preset
from seldon.llm import build_llm_client


def _nim_config(**overrides) -> LLMProviderConfig:
    base = dict(
        provider="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_API_KEY",
        app_name=None,
        default_model="qwen/qwen3.5-397b-a17b",
        fast_model="qwen/qwen3.5-122b-a10b",
        fallback_models=[],
    )
    base.update(overrides)
    return LLMProviderConfig(**base)


def test_nvidia_client_posts_to_nim_with_bearer_and_no_attribution_headers():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["x_title"] = request.headers.get("X-Title")
        body = json.loads(request.content)
        seen["model"] = body["model"]
        return httpx.Response(200, json={"model": body["model"], "choices": [{"message": {"content": "{\"ok\": true}"}}]})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = build_llm_client(_nim_config(), api_key="nvapi-test", http_client=http_client)

    result = client.complete_json([{"role": "user", "content": "return json"}], model_profile="fast")

    assert result == {"ok": True}
    assert seen["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert seen["auth"] == "Bearer nvapi-test"
    assert seen["x_title"] is None  # app_name=None → no OpenRouter attribution header
    assert seen["model"] == "qwen/qwen3.5-122b-a10b"


def test_build_llm_client_accepts_seldon_config():
    cfg = SeldonConfig()
    cfg.llm = provider_preset("nvidia")
    client = build_llm_client(cfg, api_key="nvapi-test")
    assert client.config.provider == "nvidia"
    assert client.config.base_url == "https://integrate.api.nvidia.com/v1"
