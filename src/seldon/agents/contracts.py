"""Typed contracts for Phase E context-gathering agents."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ContextGatheringInput(BaseModel):
    scenario_id: str
    question: str
    timeframe: str = ""
    depth: Literal["light", "standard", "deep"] = "standard"
    source_policy: Literal["kb_first", "kb_only"] = "kb_first"
    max_subqueries: int = Field(default=8, ge=1, le=20)


class Subquery(BaseModel):
    query: str
    topic: str | None = None
    rationale: str = ""


class QueryPlan(BaseModel):
    primary_topic: str
    temporal_scope: str = ""
    subqueries: list[Subquery]
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


class RetrievedSource(BaseModel):
    source_type: str = "kb_entry"
    source_id: str | None = None
    url: str | None = None
    name: str = "Seldon KB"
    content: str
    original_snippet: str | None = None
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    valid_from: datetime | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class RetrievalResult(BaseModel):
    query: str
    sources: list[RetrievedSource] = Field(default_factory=list)


class Observation(BaseModel):
    content: str
    original_snippet: str | None = None
    source_type: str = "context_gathering"
    source_url: str | None = None
    source_name: str = "Context Gathering"
    valid_from: datetime | None = None
    topics: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    perspective_tags: dict[str, Any] = Field(default_factory=dict)
    source_reference: str | None = None


class Delta(BaseModel):
    observation_index: int
    status: Literal["new", "duplicate", "superseding"]
    matched_kb_entry_id: str | None = None
    reason: str = ""


class KBWriteResult(BaseModel):
    created_entry_ids: list[str] = Field(default_factory=list)
    linked_entry_ids: list[str] = Field(default_factory=list)
    skipped_observation_indexes: list[int] = Field(default_factory=list)


class AgentExecution(BaseModel):
    run_id: str
    output: dict[str, Any]


class ContextGatheringOutput(BaseModel):
    run_plan: QueryPlan
    child_run_ids: list[str]
    retrievals: list[RetrievalResult]
    observations: list[Observation]
    deltas: list[Delta]
    kb_entry_ids: list[str]
