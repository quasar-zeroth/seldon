from __future__ import annotations

import os

import pytest

from seldon.config import load_env_file

# Pytest does not load .env by default; reuse the production loader so live
# provider tests pick up keys while preserving real-environment precedence.
load_env_file()

# Tests run against the real schema and a real (or stub) LLM client. The default
# production behavior is to raise when the LLM fails so misconfigurations surface
# visibly. For unit tests that exercise heuristic paths without a usable LLM, keep
# the deterministic dev-mode fallback on and skip the boot-time model healthcheck
# so the test suite doesn't burn OpenRouter rate limits.
os.environ.setdefault("SELDON_ALLOW_DEV_FALLBACK", "1")
os.environ.setdefault("SELDON_SKIP_LLM_HEALTHCHECK", "1")


@pytest.fixture()
def tmp_data_dir(tmp_path):
    return tmp_path


class FakeLLM(dict):
    def __init__(self):
        super().__init__()
        self["_call_count"] = {"n": 0}

    def complete_json(self, messages, system=None, **kwargs):
        self["_call_count"]["n"] += 1
        content = ""
        if messages:
            content = messages[-1].get("content", "")
        system_str = system or ""
        for key, response in self.items():
            if key in ("_default", "_call_count"):
                continue
            if key in content or key in system_str:
                return response
        return self.get("_default", {})


@pytest.fixture()
def mock_llm():
    return FakeLLM()
