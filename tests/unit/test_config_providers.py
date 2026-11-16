"""Tests for multi-provider LLM config: presets, selection, env overrides, .env loading."""
from __future__ import annotations

from seldon.config import (
    LLMProviderConfig,
    OpenRouterConfig,
    config_from_env,
    load_env_file,
    provider_preset,
    select_llm_provider,
)


def test_openrouter_config_is_alias_of_llm_provider_config():
    assert OpenRouterConfig is LLMProviderConfig


def test_nvidia_preset_has_expected_models_and_nim_endpoint():
    preset = provider_preset("nvidia")
    assert preset.provider == "nvidia"
    assert preset.base_url == "https://integrate.api.nvidia.com/v1"
    assert preset.api_key_env == "NVIDIA_API_KEY"
    assert preset.model_for_profile("balanced") == "deepseek-ai/deepseek-v4-pro"
    assert preset.model_for_profile("reasoning") == "deepseek-ai/deepseek-v4-pro"
    assert preset.model_for_profile("fast") == "qwen/qwen3.5-122b-a10b"
    assert preset.fallback_models == [
        "z-ai/glm-5.1",
        "minimaxai/minimax-m3",
        "nvidia/nemotron-3-ultra-550b-a55b",
    ]
    # NIM does not use OpenRouter attribution headers.
    assert preset.app_name is None


def test_openrouter_preset_drops_nonexistent_fast_model():
    preset = provider_preset("openrouter")
    assert preset.provider == "openrouter"
    assert preset.base_url == "https://openrouter.ai/api/v1"
    assert preset.fast_model == "qwen/qwen3.8-27b:free"
    # The non-existent deepseek free id must not survive anywhere.
    all_ids = [preset.default_model, preset.fast_model, preset.reasoning_model, *preset.fallback_models]
    assert not any("deepseek-v4-flash:free" in m for m in all_ids)


def test_unknown_provider_degrades_to_openrouter():
    preset = provider_preset("does-not-exist")
    assert preset.provider == "openrouter"


def test_select_provider_prefers_nvidia_then_openrouter(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    assert select_llm_provider() == "nvidia"  # nvidia preferred when both present

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert select_llm_provider() == "openrouter"  # falls back to openrouter

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert select_llm_provider() == "openrouter"  # default when neither set


def test_select_provider_explicit_env_wins(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setenv("SELDON_LLM_PROVIDER", "openrouter")
    assert select_llm_provider() == "openrouter"


def test_config_from_env_honors_explicit_provider(monkeypatch):
    monkeypatch.setenv("SELDON_LLM_PROVIDER", "nvidia")
    cfg = config_from_env()
    assert cfg.llm.provider == "nvidia"
    assert cfg.llm.default_model == "deepseek-ai/deepseek-v4-pro"
    assert cfg.llm.api_key_env == "NVIDIA_API_KEY"

    monkeypatch.setenv("SELDON_LLM_PROVIDER", "openrouter")
    cfg = config_from_env()
    assert cfg.llm.provider == "openrouter"
    assert cfg.llm.base_url == "https://openrouter.ai/api/v1"


def test_config_from_env_applies_model_overrides(monkeypatch):
    monkeypatch.setenv("SELDON_LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("SELDON_FAST_MODEL", "qwen/custom-fast")
    monkeypatch.setenv("SELDON_REASONING_MODEL", "qwen/custom-reasoning")
    monkeypatch.setenv("SELDON_LLM_BASE_URL", "https://example.test/v1")
    cfg = config_from_env()
    assert cfg.llm.fast_model == "qwen/custom-fast"
    assert cfg.llm.reasoning_model == "qwen/custom-reasoning"
    assert cfg.llm.base_url == "https://example.test/v1"


def test_load_env_file_does_not_override_existing(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ALREADY_SET=from_file\nNEW_VAR=loaded\n# comment\n")
    monkeypatch.setenv("ALREADY_SET", "from_env")
    monkeypatch.delenv("NEW_VAR", raising=False)

    load_env_file(env_file)

    import os

    assert os.environ["ALREADY_SET"] == "from_env"  # real env wins
    assert os.environ["NEW_VAR"] == "loaded"  # missing var gets loaded
