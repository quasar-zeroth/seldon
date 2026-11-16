"""Public JSON contracts. Generate the complete schema with research schema."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cases import CaseBounds


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, str_strip_whitespace=True
    )


class StartRequest(Contract):
    question: str = Field(min_length=1)
    horizon: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=255)


class EvidenceWrite(Contract):
    id: str = Field(
        min_length=1, description="Existing UUID or a stable local key for a new record"
    )
    content: str = Field(min_length=1)
    kind: Literal["observation", "assumption"] = "observation"
    source_name: str = Field(min_length=1)
    source_url: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def provenance(self):
        if self.kind == "observation" and not (self.source_url or "").startswith(
            ("https://", "http://")
        ):
            raise ValueError(
                "Observed evidence requires a source URL; label unsupported premises as assumptions"
            )
        if self.retrieved_at.tzinfo is None or (
            self.published_at and self.published_at.tzinfo is None
        ):
            raise ValueError("Evidence timestamps must include a timezone")
        return self


class NodeWrite(Contract):
    tags: list[str] | None = Field(default=None, description="Evidence-grounded category/geography/role tags; omitted tags are preserved. Use data-center for physical campuses.")
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: Literal["entity", "event", "topic", "metric", "policy", "actor"]
    description: str = ""
    current_state: str = "Unknown; research required"
    evidence_ids: list[str] = Field(default_factory=list)


class EdgeWrite(Contract):
    id: str = Field(min_length=1)
    source: str
    target: str
    relationship: Literal[
        "causes", "constrains", "enables", "opposes", "amplifies", "dampens"
    ] = "causes"
    description: str = Field(min_length=1)
    direction: Literal["positive", "negative", "complex"] = "complex"
    strength: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.5, ge=0, le=1)
    lag: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ResearchRound(Contract):
    queries: list[str] = Field(min_length=1)
    checked_node_ids: list[str] = Field(min_length=1)
    sources_consulted: list[str] = Field(default_factory=list)
    new_information: bool
    stop_reason: Literal["continue", "exhausted", "budget"]
    summary: str = Field(min_length=1)
    remaining_gaps: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def stopping(self):
        if self.stop_reason == "exhausted" and self.new_information:
            raise ValueError(
                "Research cannot be exhausted while reporting new information"
            )
        if self.stop_reason == "budget" and not self.remaining_gaps:
            raise ValueError("A budget stop must record remaining gaps")
        return self


class NodeAssessment(Contract):
    node_id: str
    forecast: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class Branch(Contract):
    key: str = Field(min_length=1)
    probability: float = Field(ge=0, le=1)
    outcome: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    value_low: float | None = None
    value_high: float | None = None

    @model_validator(mode="after")
    def interval(self):
        if (self.value_low is None) != (self.value_high is None):
            raise ValueError("Provide both interval endpoints or neither")
        if self.value_low is not None and self.value_low > self.value_high:
            raise ValueError("Interval endpoints are reversed")
        return self


class ForecastWrite(Contract):
    target_node_id: str
    as_of: datetime
    resolution_date: date
    units: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    resolution_criteria: str = Field(min_length=1)
    case_bounds: CaseBounds | None = Field(
        default=None,
        description="Generate lower/upper hot takes before central cases; optional only for legacy clients and replay compatibility",
    )
    branches: list[Branch] = Field(min_length=2)
    confidence: float = Field(ge=0, le=1)
    node_assessments: list[NodeAssessment] = Field(min_length=1)
    synthesis: str = Field(min_length=1)
    base_rate: str = Field(
        min_length=1,
        description="Empirical anchor, or explicitly state that none was established",
    )
    assumptions: list[str] = Field(min_length=1)
    red_team: list[str] = Field(min_length=1)
    uncertainties: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def distribution(self):
        keys = [b.key for b in self.branches]
        if len(set(keys)) != len(keys):
            raise ValueError("Forecast branch keys must be unique")
        if not math.isclose(
            sum(b.probability for b in self.branches), 1.0, abs_tol=1e-6
        ):
            raise ValueError("Forecast probabilities must sum to one")
        if self.as_of.tzinfo is None or self.resolution_date <= self.as_of.date():
            raise ValueError(
                "Forecast needs a timezone-aware as_of and later resolution date"
            )
        return self


class GraphScope(Contract):
    target_node_id: str | None = None
    max_depth: int = Field(default=4, ge=1, le=12)
    excluded_node_ids: list[str] = Field(default_factory=list)
    excluded_edge_ids: list[str] = Field(default_factory=list)


class WorkspaceApply(Contract):
    schema_version: Literal[1] = 1
    scenario_id: str
    base_revision: str
    request_id: str = Field(min_length=1, max_length=128)
    agent: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1)
    graph_scope: GraphScope | None = None
    reuse_node_ids: list[str] = Field(default_factory=list)
    reuse_edge_ids: list[str] = Field(default_factory=list)
    reuse_evidence_ids: list[str] = Field(default_factory=list)
    allow_shared_updates: bool = False
    prediction_request_id: str | None = None
    evidence: list[EvidenceWrite] = Field(default_factory=list)
    nodes: list[NodeWrite] = Field(default_factory=list)
    edges: list[EdgeWrite] = Field(default_factory=list)
    detach_edges: list[str] = Field(
        default_factory=list,
        description="Remove these edges from this scenario; preserve rows/history and other scenarios",
    )
    detach_nodes: list[str] = Field(
        default_factory=list,
        description="Remove these nodes from this scenario; also detach their incident scenario edges explicitly",
    )
    research_round: ResearchRound | None = None
    forecast: ForecastWrite | None = None
