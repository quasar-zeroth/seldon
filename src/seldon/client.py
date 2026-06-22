"""Small facade for prediction and knowledge graph operations."""
from __future__ import annotations

from pathlib import Path

from .config import SeldonConfig
from .llm import LLMClientProtocol, ModelInvocationRecorder, build_llm_client
from .predictions.engine import PredictionEngine
from .graph.knowledge_graph import KnowledgeGraph
from .graph.entity_extractor import EntityExtractor


class GraphFacade:
    def __init__(self, config: SeldonConfig, llm_client: LLMClientProtocol | None = None):
        self.config = config
        self.llm_client = llm_client

    @property
    def graph_path(self) -> Path:
        return self.config.data_dir / "knowledge_graph.json"

    def open(self) -> KnowledgeGraph:
        return KnowledgeGraph(path=self.graph_path)

    def extractor(self) -> EntityExtractor:
        return EntityExtractor(
            entity_extraction_model=self.config.knowledge_graph.entity_extraction_model,
            entity_extraction_model_profile=self.config.knowledge_graph.entity_extraction_model_profile,
            llm_client=self.llm_client,
        )

    def search(self, query: str) -> list[dict]:
        return self.open().search(query)

    def show(self, entity_id: str) -> dict | None:
        kg = self.open()
        node = kg.get_node(entity_id)
        if node is None:
            results = kg.search(entity_id)
            return results[0] if results else None
        return node

    def export(self) -> dict:
        return self.open().export()


class SeldonClient:
    """Facade for The Seldon Project prediction and graph operations."""

    def __init__(self, config: SeldonConfig | None = None, llm_client: LLMClientProtocol | None = None):
        self.config = config or SeldonConfig()
        self.llm_client = llm_client or build_llm_client(
            self.config,
            recorder=ModelInvocationRecorder(self.config.data_dir / "model_invocations.jsonl"),
        )
        self.predictions = PredictionEngine(
            data_dir=self.config.data_dir,
            pred_cfg=self.config.predictions,
            llm_client=llm_client,
        )
        self.graph = GraphFacade(config=self.config, llm_client=llm_client)
