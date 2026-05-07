from __future__ import annotations

import os
from pathlib import Path

import pytest


def _load_project_dotenv() -> None:
    """Load simple KEY=VALUE pairs from the project .env for local tests.

    Pytest does not load .env files by default. This keeps live OpenRouter tests
    convenient while preserving normal environment precedence and avoiding any
    dependency on python-dotenv.
    """
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.getenv(key):
            os.environ[key] = value


_load_project_dotenv()


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
