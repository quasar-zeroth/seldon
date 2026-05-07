"""SQLAlchemy persistence models for Phase C."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Source(Base, TimestampMixin):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Unknown")
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)


class KBEntry(Base, TimestampMixin):
    __tablename__ = "kb_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    original_snippet: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(64), default="user_input", nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(String(255), default="Unknown", nullable=False)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    topics: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    entities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    scenario_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    perspective_tags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    superseded_by: Mapped[str | None] = mapped_column(ForeignKey("kb_entries.id"))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content_embedding: Mapped[list[float] | None] = mapped_column(JSON)
    embedding_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    vector_index_pointer: Mapped[str | None] = mapped_column(String(255))
    versions: Mapped[list["KBEntryVersion"]] = relationship(back_populates="entry", cascade="all, delete-orphan")


class KBEntryVersion(Base):
    __tablename__ = "kb_entry_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kb_entry_id: Mapped[str] = mapped_column(ForeignKey("kb_entries.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    agent_id: Mapped[str | None] = mapped_column(String(128))
    entry: Mapped[KBEntry] = relationship(back_populates="versions")


class KBEntryContradiction(Base):
    __tablename__ = "kb_entry_contradictions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    kb_entry_id: Mapped[str] = mapped_column(ForeignKey("kb_entries.id"), nullable=False)
    contradicts_kb_entry_id: Mapped[str] = mapped_column(ForeignKey("kb_entries.id"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Scenario(Base, TimestampMixin):
    __tablename__ = "scenarios"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    target_question: Mapped[str] = mapped_column(Text, nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    erg_snapshot_id: Mapped[str | None] = mapped_column(String(36))
    kb_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ERGNode(Base, TimestampMixin):
    __tablename__ = "erg_nodes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    current_state: Mapped[str | None] = mapped_column(Text)
    state_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kb_entry_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    scenario_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    stability_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class ERGEdge(Base, TimestampMixin):
    __tablename__ = "erg_edges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_node_id: Mapped[str] = mapped_column(ForeignKey("erg_nodes.id"), nullable=False)
    target_node_id: Mapped[str] = mapped_column(ForeignKey("erg_nodes.id"), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    lag: Mapped[str | None] = mapped_column(String(128))
    direction: Mapped[str] = mapped_column(String(32), default="complex", nullable=False)
    evidence_kb_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    scenario_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    __table_args__ = (UniqueConstraint("source_node_id", "target_node_id", "relationship_type", name="uq_erg_edge_relation"),)


class GraphSnapshot(Base):
    __tablename__ = "graph_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    agent_id: Mapped[str | None] = mapped_column(String(128))


class ScenarioPrediction(Base, TimestampMixin):
    __tablename__ = "scenario_predictions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"))
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, default="", nullable=False)
    timeframe: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    resolution_criteria: Mapped[str] = mapped_column(Text, default="", nullable=False)
    scenarios: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    probabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    key_drivers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_links: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    probability_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    calibration_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class ScenarioVersion(Base):
    __tablename__ = "scenario_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scenario_prediction_id: Mapped[str] = mapped_column(ForeignKey("scenario_predictions.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    agent_id: Mapped[str | None] = mapped_column(String(128))


class ScenarioEvidenceLink(Base):
    __tablename__ = "scenario_evidence_links"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scenario_prediction_id: Mapped[str] = mapped_column(ForeignKey("scenario_predictions.id"), nullable=False)
    kb_entry_id: Mapped[str] = mapped_column(ForeignKey("kb_entries.id"), nullable=False)
    relationship: Mapped[str] = mapped_column(String(64), default="supports", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class FeedbackEntry(Base):
    __tablename__ = "feedback_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"))
    prediction_id: Mapped[str | None] = mapped_column(ForeignKey("scenario_predictions.id"))
    actual_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    comparison: Mapped[str] = mapped_column(Text, default="", nullable=False)
    missed_factors: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    graph_corrections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    lessons_learned: Mapped[str] = mapped_column(Text, default="", nullable=False)


class OutcomeCheck(Base):
    __tablename__ = "outcome_checks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prediction_id: Mapped[str] = mapped_column(ForeignKey("scenario_predictions.id"), nullable=False)
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"))
    actual_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_outcome_key: Mapped[str] = mapped_column(String(128), nullable=False)
    probability_assigned: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    resolution_confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source_references: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class HistoricalAnalogy(Base):
    __tablename__ = "historical_analogies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prediction_id: Mapped[str | None] = mapped_column(ForeignKey("scenario_predictions.id"))
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    historical_outcome: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_kb_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BaseRateEvidence(Base):
    __tablename__ = "base_rate_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prediction_id: Mapped[str | None] = mapped_column(ForeignKey("scenario_predictions.id"))
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"))
    metric: Mapped[str] = mapped_column(String(255), nullable=False)
    population: Mapped[str] = mapped_column(Text, default="", nullable=False)
    observed_frequency: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    sample_size: Mapped[int | None] = mapped_column(Integer)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_kb_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SentimentDrift(Base):
    __tablename__ = "sentiment_drift"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"))
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    sentiment: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    previous_sentiment: Mapped[float | None] = mapped_column(Float)
    velocity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    evidence_kb_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AssumptionRecord(Base, TimestampMixin):
    __tablename__ = "assumptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prediction_id: Mapped[str | None] = mapped_column(ForeignKey("scenario_predictions.id"))
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"))
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    used_in_scenarios: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    still_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="valid", nullable=False)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_by: Mapped[str | None] = mapped_column(ForeignKey("kb_entries.id"))


class AdvancedAnalysis(Base):
    __tablename__ = "advanced_analyses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prediction_id: Mapped[str] = mapped_column(ForeignKey("scenario_predictions.id"), nullable=False)
    scenario_id: Mapped[str | None] = mapped_column(ForeignKey("scenarios.id"))
    red_team: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    expert_perspectives: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    uncertainty: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    information_value: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    cascade_risks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    scenario_diff: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    phase: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source_references: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ModelInvocation(Base):
    __tablename__ = "model_invocations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"))
    agent: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(128))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    ok: Mapped[bool] = mapped_column(default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
