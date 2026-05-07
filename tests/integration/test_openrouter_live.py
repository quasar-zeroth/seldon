from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from seldon.config import OpenRouterConfig
from seldon.graph.entity_extractor import EntityExtractor
from seldon.graph.knowledge_graph import KnowledgeGraph
from seldon.llm import OpenRouterClient

pytestmark = pytest.mark.live_openrouter


def _api_key() -> str | None:
    value = os.getenv("OPENROUTER_API_KEY")
    if not value or value.startswith("sk-or-…"):
        return None
    return value


requires_openrouter = pytest.mark.skipif(_api_key() is None, reason="OPENROUTER_API_KEY is not set")


class SmokeResponse(BaseModel):
    ok: bool
    label: str


class JsonCompatOpenRouterClient:
    """Delegate to the live client while avoiding provider-specific JSON-mode issues."""

    def __init__(self, client: OpenRouterClient):
        self.client = client

    def complete_json(self, messages: list[dict], system: str | None = None, **kwargs):
        kwargs.setdefault("response_format", None)
        kwargs.setdefault("temperature", 0)
        kwargs.setdefault("max_tokens", 700)
        kwargs.setdefault("max_retries", 1)
        return self.client.complete_json(messages, system=system, **kwargs)


@requires_openrouter
def test_live_openrouter_complete_json_uses_default_and_fallback_models():
    client = OpenRouterClient(OpenRouterConfig(timeout_seconds=90), api_key=_api_key())

    result = client.complete_json(
        [
            {
                "role": "user",
                "content": 'Return only JSON matching this exact shape: {"ok": true, "label": "openrouter-live"}',
            }
        ],
        schema=SmokeResponse,
        response_format=None,
        temperature=0,
        max_tokens=120,
        max_retries=1,
    )

    assert result["ok"] is True
    assert result["label"] == "openrouter-live"
    assert client.config.default_model == "tencent/hy3-preview:free"
    assert client.config.fallback_models == [
        "openrouter/owl-alpha",
        "minimax/minimax-m2.5:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
    ]


@requires_openrouter
def test_live_entity_extractor_agent_calls_openrouter_and_populates_graph(tmp_path):
    client = JsonCompatOpenRouterClient(OpenRouterClient(OpenRouterConfig(timeout_seconds=90), api_key=_api_key()))
    graph = KnowledgeGraph(tmp_path / "live-graph.json")
    extractor = EntityExtractor(llm_client=client)

    result = extractor.extract_from_article(
        {
            "id": "nvidia-blackwell-supply",
            "title": "Nvidia Blackwell demand pressures advanced packaging supply",
            "source": "Live OpenRouter smoke fixture",
            "tickers": ["NVDA"],
            "topics": ["AI chips"],
            "content": (
                "Nvidia said demand for Blackwell AI accelerators remains strong. "
                "TSMC advanced packaging capacity and cloud capex from Microsoft, Amazon, and Meta "
                "are key constraints for shipments over the next two quarters."
            ),
        },
        graph,
    )

    # The article/source/ticker/topic are deterministic; any additional node comes
    # from the live LLM-backed extraction path.
    assert result["entities_added"] >= 4
    assert graph.graph.number_of_nodes() >= 4
    assert any("NVDA" in node for node in graph.graph.nodes)
