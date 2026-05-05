"""Pydantic schemas mirroring Phase C storage contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PerspectiveTags(BaseModel):
    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)
    political_lean: float | None = Field(default=None, ge=-1.0, le=1.0)
    geopolitical_lens: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class KBEntryCreate(BaseModel):
    content: str
    original_snippet: str | None = None
    source_type: str = "user_input"
    source_url: str | None = None
    source_name: str = "Unknown"
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)
    perspective_tags: dict[str, Any] = Field(default_factory=dict)
    embedding_metadata: dict[str, Any] = Field(default_factory=dict)
    vector_index_pointer: str | None = None


class ERGNodeCreate(BaseModel):
    name: str
    type: Literal["entity", "event", "topic", "metric", "policy", "actor"]
    description: str = ""
    current_state: str | None = None
    state_updated_at: datetime | None = None
    kb_entry_ids: list[str] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)
    stability_score: float = Field(default=0.5, ge=0.0, le=1.0)
    importance_score: float = Field(default=0.0, ge=0.0, le=1.0)


class ERGEdgeCreate(BaseModel):
    source_node_id: str
    target_node_id: str
    relationship_type: Literal["causes", "correlates_with", "depends_on", "constrains", "enables", "opposes", "amplifies", "dampens"]
    description: str = ""
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    lag: str | None = None
    direction: Literal["positive", "negative", "complex"] = "complex"
    evidence_kb_ids: list[str] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)


class ScenarioPredictionCreate(BaseModel):
    statement: str
    scope: str = ""
    timeframe: str = ""
    resolution_criteria: str = ""
    scenarios: list[dict[str, Any]] = Field(default_factory=list)
    probabilities: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    key_drivers: list[str] = Field(default_factory=list)
    evidence_links: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    probability_history: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["draft", "active", "monitoring", "resolved", "archived"] = "draft"
