"""Configuration models for the seldon package."""
from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field


class PredictionContextConfig(BaseModel):
    daily_summaries: int = 3
    weekly_summaries: int = 4
    monthly_summaries: int = 2


class OpenRouterConfig(BaseModel):
    base_url: str = "https://openrouter.ai/api/v1"
    api_key_env: str = "OPENROUTER_API_KEY"
    app_name: str = "The Seldon Project"
    site_url: str | None = None
    timeout_seconds: float = 90
    default_model: str = "anthropic/claude-sonnet-4.5"
    fast_model: str = "anthropic/claude-haiku-4.5"
    reasoning_model: str = "openai/gpt-5.1"
    embedding_model: str = "text-embedding-3-small"
    fallback_models: list[str] = Field(default_factory=list)

    def model_for_profile(self, profile: str) -> str:
        if profile == "fast":
            return self.fast_model
        if profile == "reasoning":
            return self.reasoning_model
        if profile == "embedding":
            return self.embedding_model
        return self.default_model


class AgentModelConfig(BaseModel):
    model_profile: str = "balanced"
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class AgentsConfig(BaseModel):
    context_gathering_coordinator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    query_decomposer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    information_retriever: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.0)
    )
    information_summarizer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    deduplication_delta_detector: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.0)
    )
    kb_writer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.0)
    )
    prediction_engine: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.2)
    )
    extraction_coordinator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    entity_extractor: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    event_extractor: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    topic_theme_extractor: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    node_deduplicator_merger: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.0)
    )
    graph_construction_coordinator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    pairwise_relationship_detector: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    graph_consistency_checker: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.0)
    )
    importance_scorer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.0)
    )
    convergence_loop_coordinator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    prediction_coordinator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="reasoning", temperature=0.2)
    )
    node_state_predictor: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="fast", temperature=0.1)
    )
    graph_traversal_simulator: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="balanced", temperature=0.1)
    )
    instability_analyzer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="reasoning", temperature=0.1)
    )
    scenario_synthesizer: AgentModelConfig = Field(
        default_factory=lambda: AgentModelConfig(model_profile="reasoning", temperature=0.2)
    )


class PredictionConfig(BaseModel):
    model_profile: str = "balanced"
    model: str | None = None
    max_active_predictions: int = 30
    min_confidence_to_create: float = 0.40
    deactivate_after_days: int = 90
    context: PredictionContextConfig = Field(default_factory=PredictionContextConfig)
    update_frequency: str = "daily"


class KnowledgeGraphConfig(BaseModel):
    backend: str = "networkx"
    entity_extraction_model_profile: str = "fast"
    entity_extraction_model: str | None = None
    auto_extract_entities: bool = True


class DatabaseConfig(BaseModel):
    url: str | None = None
    sqlite_path: Path = Path("./data/seldon.db")
    echo: bool = False


class OpsConfig(BaseModel):
    structured_logs: bool = True
    log_level: str = "INFO"
    api_key_env: str = "SELDON_API_KEY"
    require_api_key: bool = False
    allow_localhost_without_api_key: bool = True
    backup_dir: Path = Path("./data/backups")
    vector_index_path: Path = Path("./data/vector-index")


class SeldonConfig(BaseModel):
    data_dir: Path = Path("./data")
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    llm: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    predictions: PredictionConfig = Field(default_factory=PredictionConfig)
    knowledge_graph: KnowledgeGraphConfig = Field(default_factory=KnowledgeGraphConfig)
    ops: OpsConfig = Field(default_factory=OpsConfig)

    model_config = {"arbitrary_types_allowed": True}
