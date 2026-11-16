"""Pydantic schemas mirroring Phase C/C.1 storage contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PerspectiveTags(BaseModel):
    sentiment: float | None = Field(default=None, ge=-1.0, le=1.0)
    political_lean: float | None = Field(default=None, ge=-1.0, le=1.0)
    geopolitical_lens: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class SourceCreate(BaseModel):
    source_type: str
    url: str | None = None
    name: str = "Unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    content_embedding: list[float] | None = None
    embedding_metadata: dict[str, Any] = Field(default_factory=dict)
    vector_index_pointer: str | None = None


class KBEntryRead(KBEntryCreate):
    id: str
    version: int
    superseded_by: str | None = None
    created_at: datetime
    updated_at: datetime


class KBEntryVersionRead(BaseModel):
    id: str
    kb_entry_id: str
    version: int
    snapshot: dict[str, Any]
    created_at: datetime
    reason: str | None = None
    agent_id: str | None = None


class KBEntryContradictionCreate(BaseModel):
    kb_entry_id: str
    contradicts_kb_entry_id: str
    description: str
    status: str = "open"


class ERGNodeCreate(BaseModel):
    tags: list[str] = Field(default_factory=list)
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


class GraphSnapshotRead(BaseModel):
    id: str
    scenario_id: str | None = None
    snapshot: dict[str, Any]
    created_at: datetime
    reason: str | None = None
    agent_id: str | None = None


class ScenarioDraftRequest(BaseModel):
    prompt: str = Field(min_length=8, max_length=4000)
    default_time_horizon: str | None = Field(default=None, max_length=255)


class ScenarioDraftResponse(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_question: str = Field(min_length=1, max_length=600)
    time_horizon: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=1600)
    source_prompt: str = Field(default="", max_length=4000)


class ScenarioCreate(BaseModel):
    name: str
    description: str = ""
    original_prompt: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "paused", "archived", "completed"] = "active"
    target_question: str
    time_horizon: str = ""
    erg_snapshot_id: str | None = None
    kb_snapshot_at: datetime | None = None


class ScenarioPredictionCreate(BaseModel):
    scenario_id: str | None = None
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


class ScenarioVersionRead(BaseModel):
    id: str
    scenario_prediction_id: str
    version: int
    snapshot: dict[str, Any]
    created_at: datetime
    reason: str | None = None
    agent_id: str | None = None


class ScenarioEvidenceLinkCreate(BaseModel):
    scenario_prediction_id: str
    kb_entry_id: str
    relationship: str = "supports"


class FeedbackEntryCreate(BaseModel):
    scenario_id: str | None = None
    prediction_id: str | None = None
    actual_outcome: str
    comparison: str = ""
    missed_factors: list[str] = Field(default_factory=list)
    graph_corrections: list[dict[str, Any]] = Field(default_factory=list)
    lessons_learned: str = ""


class AgentRunCreate(BaseModel):
    agent_id: str
    phase: str | None = None
    status: str = "pending"
    input: dict[str, Any] = Field(default_factory=dict)
    source_references: list[str] = Field(default_factory=list)


class AgentMessageCreate(BaseModel):
    agent_run_id: str
    role: str
    content: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ModelInvocationCreate(BaseModel):
    agent_run_id: str | None = None
    agent: str | None = None
    model: str
    provider: str | None = None
    latency_ms: int | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    estimated_cost: float | None = None
    ok: bool = True
    error: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class AuditLogRead(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    action: str
    actor: str
    reason: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    created_at: datetime

class SourceRead(SourceCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class SourceUpdate(BaseModel):
    source_type: str | None = None
    url: str | None = None
    name: str | None = None
    metadata: dict[str, Any] | None = None


class KBEntryUpdate(BaseModel):
    content: str | None = None
    original_snippet: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    topics: list[str] | None = None
    entities: list[str] | None = None
    scenario_ids: list[str] | None = None
    perspective_tags: dict[str, Any] | None = None
    content_embedding: list[float] | None = None
    embedding_metadata: dict[str, Any] | None = None
    vector_index_pointer: str | None = None
    superseded_by: str | None = None


class KBEntryContradictionRead(KBEntryContradictionCreate):
    id: str
    created_at: datetime
    resolved_at: datetime | None = None


class KBEntryContradictionUpdate(BaseModel):
    description: str | None = None
    status: str | None = None
    resolved_at: datetime | None = None


class ERGNodeRead(ERGNodeCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class ERGNodeUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    description: str | None = None
    current_state: str | None = None
    state_updated_at: datetime | None = None
    kb_entry_ids: list[str] | None = None
    scenario_ids: list[str] | None = None
    stability_score: float | None = Field(default=None, ge=0.0, le=1.0)
    importance_score: float | None = Field(default=None, ge=0.0, le=1.0)


class ERGEdgeRead(ERGEdgeCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class ERGEdgeUpdate(BaseModel):
    relationship_type: str | None = None
    description: str | None = None
    strength: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    lag: str | None = None
    direction: str | None = None
    evidence_kb_ids: list[str] | None = None
    scenario_ids: list[str] | None = None


class ScenarioRead(ScenarioCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class ScenarioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    original_prompt: str | None = Field(default=None, max_length=4000)
    status: str | None = None
    target_question: str | None = None
    time_horizon: str | None = None
    erg_snapshot_id: str | None = None
    kb_snapshot_at: datetime | None = None


class ScenarioPredictionRead(ScenarioPredictionCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class ScenarioPredictionUpdate(BaseModel):
    statement: str | None = None
    scope: str | None = None
    timeframe: str | None = None
    resolution_criteria: str | None = None
    scenarios: list[dict[str, Any]] | None = None
    probabilities: dict[str, Any] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    key_drivers: list[str] | None = None
    evidence_links: list[str] | None = None
    assumptions: list[str] | None = None
    probability_history: list[dict[str, Any]] | None = None
    status: str | None = None
    outcome: dict[str, Any] | None = None
    calibration_result: dict[str, Any] | None = None


class ScenarioEvidenceLinkRead(ScenarioEvidenceLinkCreate):
    id: str
    created_at: datetime


class FeedbackEntryRead(FeedbackEntryCreate):
    id: str
    recorded_at: datetime


class OutcomeCheckRead(BaseModel):
    id: str
    prediction_id: str
    scenario_id: str | None = None
    actual_outcome: str
    resolved_outcome_key: str
    probability_assigned: float
    resolution_confidence: float
    source_references: list[str] = Field(default_factory=list)
    notes: str = ""
    checked_at: datetime


class FeedbackEntryUpdate(BaseModel):
    actual_outcome: str | None = None
    comparison: str | None = None
    missed_factors: list[str] | None = None
    graph_corrections: list[dict[str, Any]] | None = None
    lessons_learned: str | None = None


class AgentRunRead(AgentRunCreate):
    id: str
    output: dict[str, Any] | None = None
    error: str | None = None
    elapsed_ms: int | None = None
    created_at: datetime
    updated_at: datetime


class AgentRunUpdate(BaseModel):
    status: str | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    elapsed_ms: int | None = None


class AgentMessageRead(AgentMessageCreate):
    id: str
    created_at: datetime


class ModelInvocationRead(ModelInvocationCreate):
    id: str
    created_at: datetime


class ModelInvocationUpdate(BaseModel):
    ok: bool | None = None
    error: str | None = None
    raw_metadata: dict[str, Any] | None = None
