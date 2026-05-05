"""Configuration models for the seldon package."""
from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field


class PredictionContextConfig(BaseModel):
    daily_summaries: int = 3
    weekly_summaries: int = 4
    monthly_summaries: int = 2


class PredictionConfig(BaseModel):
    model: str = "anthropic/claude-sonnet-4-20250514"
    max_active_predictions: int = 30
    min_confidence_to_create: float = 0.40
    deactivate_after_days: int = 90
    context: PredictionContextConfig = Field(default_factory=PredictionContextConfig)
    update_frequency: str = "daily"


class KnowledgeGraphConfig(BaseModel):
    backend: str = "networkx"
    entity_extraction_model: str = "google/gemini-2.5-flash-preview"
    auto_extract_entities: bool = True


class SeldonConfig(BaseModel):
    data_dir: Path = Path("./data")
    predictions: PredictionConfig = Field(default_factory=PredictionConfig)
    knowledge_graph: KnowledgeGraphConfig = Field(default_factory=KnowledgeGraphConfig)

    model_config = {"arbitrary_types_allowed": True}
