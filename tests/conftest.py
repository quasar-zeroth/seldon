from __future__ import annotations

import pytest


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
