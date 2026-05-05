"""Repository interfaces for Phase C persistence and auditability."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AgentMessage,
    AgentRun,
    AuditLog,
    ERGEdge,
    ERGNode,
    KBEntry,
    KBEntryContradiction,
    KBEntryVersion,
    ModelInvocation,
    ScenarioEvidenceLink,
    ScenarioPrediction,
    ScenarioVersion,
)

ModelT = TypeVar("ModelT")


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def row_to_dict(row: Any) -> dict[str, Any]:
    return {c.name: _jsonable(getattr(row, c.name)) for c in row.__table__.columns}


class AuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def emit(self, entity_type: str, entity_id: str, action: str, *, actor: str = "system", reason: str | None = None, before: dict[str, Any] | None = None, after: dict[str, Any] | None = None) -> AuditLog:
        row = AuditLog(entity_type=entity_type, entity_id=entity_id, action=action, actor=actor, reason=reason, before=before, after=after)
        self.session.add(row)
        return row

    def list(self, *, entity_type: str | None = None, entity_id: str | None = None) -> list[AuditLog]:
        stmt = select(AuditLog).order_by(AuditLog.created_at)
        if entity_type:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        return list(self.session.scalars(stmt))


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]
    audit_entity_type: str

    def __init__(self, session: Session, audit: AuditRepository | None = None):
        self.session = session
        self.audit = audit or AuditRepository(session)

    def get(self, id: str) -> ModelT | None:
        return self.session.get(self.model, id)

    def list(self, limit: int = 100, offset: int = 0) -> list[ModelT]:
        return list(self.session.scalars(select(self.model).offset(offset).limit(limit)))

    def create(self, *, actor: str = "system", reason: str | None = None, **values: Any) -> ModelT:
        row = self.model(**values)
        self.session.add(row)
        self.session.flush()
        self.audit.emit(self.audit_entity_type, row.id, "create", actor=actor, reason=reason, after=row_to_dict(row))
        return row

    def update(self, id: str, *, actor: str = "system", reason: str | None = None, **values: Any) -> ModelT:
        row = self.get(id)
        if row is None:
            raise KeyError(f"{self.audit_entity_type} not found: {id}")
        before = row_to_dict(row)
        for key, value in values.items():
            setattr(row, key, value)
        self.session.flush()
        self.audit.emit(self.audit_entity_type, id, "update", actor=actor, reason=reason, before=before, after=row_to_dict(row))
        return row


class KBRepository(BaseRepository[KBEntry]):
    model = KBEntry
    audit_entity_type = "kb_entry"

    def create_entry(self, *, actor: str = "system", reason: str | None = None, **values: Any) -> KBEntry:
        row = self.create(actor=actor, reason=reason, **values)
        self._version(row, actor=actor, reason=reason or "initial create")
        return row

    def update_entry(self, id: str, *, actor: str = "system", reason: str | None = None, **values: Any) -> KBEntry:
        row = self.update(id, actor=actor, reason=reason, **values)
        row.version += 1
        self.session.flush()
        self._version(row, actor=actor, reason=reason or "update")
        return row

    def supersede(self, old_id: str, new_id: str, *, actor: str = "system", reason: str | None = None) -> KBEntry:
        row = self.update_entry(old_id, actor=actor, reason=reason or f"superseded by {new_id}", superseded_by=new_id)
        self.audit.emit("kb_entry", old_id, "supersede", actor=actor, reason=reason, after={"superseded_by": new_id})
        return row

    def add_contradiction(self, entry_id: str, contradicts_id: str, description: str) -> KBEntryContradiction:
        row = KBEntryContradiction(kb_entry_id=entry_id, contradicts_kb_entry_id=contradicts_id, description=description)
        self.session.add(row)
        self.session.flush()
        self.audit.emit("kb_entry_contradiction", row.id, "create", after=row_to_dict(row))
        return row

    def search(self, query: str | None = None, *, topic: str | None = None, entity: str | None = None) -> list[KBEntry]:
        stmt = select(KBEntry)
        if query:
            stmt = stmt.where(KBEntry.content.ilike(f"%{query}%"))
        results = list(self.session.scalars(stmt))
        if topic:
            results = [r for r in results if topic in (r.topics or [])]
        if entity:
            results = [r for r in results if entity in (r.entities or [])]
        return results

    def _version(self, row: KBEntry, *, actor: str, reason: str) -> KBEntryVersion:
        version = KBEntryVersion(kb_entry_id=row.id, version=row.version, snapshot=row_to_dict(row), reason=reason, agent_id=actor)
        self.session.add(version)
        return version


class GraphRepository:
    def __init__(self, session: Session, audit: AuditRepository | None = None):
        self.session = session
        self.audit = audit or AuditRepository(session)

    def create_node(self, **values: Any) -> ERGNode:
        node = ERGNode(**values)
        self.session.add(node)
        self.session.flush()
        self.audit.emit("erg_node", node.id, "create", after=row_to_dict(node))
        return node

    def get_node(self, id: str) -> ERGNode | None:
        return self.session.get(ERGNode, id)

    def list_nodes(self) -> list[ERGNode]:
        return list(self.session.scalars(select(ERGNode)))

    def create_edge(self, **values: Any) -> ERGEdge:
        edge = ERGEdge(**values)
        self.session.add(edge)
        self.session.flush()
        self.audit.emit("erg_edge", edge.id, "create", after=row_to_dict(edge))
        return edge

    def list_edges(self, node_id: str | None = None) -> list[ERGEdge]:
        stmt = select(ERGEdge)
        if node_id:
            stmt = stmt.where((ERGEdge.source_node_id == node_id) | (ERGEdge.target_node_id == node_id))
        return list(self.session.scalars(stmt))

    def export_graph_json(self) -> dict[str, Any]:
        return {"nodes": [row_to_dict(n) for n in self.list_nodes()], "edges": [row_to_dict(e) for e in self.list_edges()]}


class ScenarioRepository(BaseRepository[ScenarioPrediction]):
    model = ScenarioPrediction
    audit_entity_type = "scenario_prediction"

    def create_prediction(self, *, actor: str = "system", reason: str | None = None, **values: Any) -> ScenarioPrediction:
        row = self.create(actor=actor, reason=reason, **values)
        self._version(row, actor=actor, reason=reason or "initial create")
        for kb_id in row.evidence_links or []:
            self.session.add(ScenarioEvidenceLink(scenario_prediction_id=row.id, kb_entry_id=kb_id))
        return row

    def update_prediction(self, id: str, *, actor: str = "system", reason: str | None = None, **values: Any) -> ScenarioPrediction:
        row = self.update(id, actor=actor, reason=reason, **values)
        latest = self.session.scalar(select(ScenarioVersion.version).where(ScenarioVersion.scenario_prediction_id == id).order_by(ScenarioVersion.version.desc())) or 0
        self._version(row, actor=actor, reason=reason or "update", version=latest + 1)
        return row

    def _version(self, row: ScenarioPrediction, *, actor: str, reason: str, version: int = 1) -> ScenarioVersion:
        v = ScenarioVersion(scenario_prediction_id=row.id, version=version, snapshot=row_to_dict(row), reason=reason, agent_id=actor)
        self.session.add(v)
        return v


class AgentRunRepository(BaseRepository[AgentRun]):
    model = AgentRun
    audit_entity_type = "agent_run"

    def add_message(self, run_id: str, role: str, content: str, payload: dict[str, Any] | None = None) -> AgentMessage:
        row = AgentMessage(agent_run_id=run_id, role=role, content=content, payload=payload or {})
        self.session.add(row)
        self.session.flush()
        self.audit.emit("agent_message", row.id, "create", after=row_to_dict(row))
        return row

    def record_invocation(self, **values: Any) -> ModelInvocation:
        row = ModelInvocation(**values)
        self.session.add(row)
        self.session.flush()
        self.audit.emit("model_invocation", row.id, "create", after=row_to_dict(row))
        return row


@dataclass
class MarkdownExporter:
    """Human-readable snapshot exporter; DB remains source of truth."""
    output_dir: Path

    def export_kb_entry(self, entry: KBEntry) -> Path:
        path = self.output_dir / "kb" / f"{entry.id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# KB Entry {entry.id}\n\n{entry.content}\n\n- Source: {entry.source_name} ({entry.source_type})\n- Topics: {', '.join(entry.topics or [])}\n- Entities: {', '.join(entry.entities or [])}\n- Version: {entry.version}\n", encoding="utf-8")
        return path

    def export_scenario(self, scenario: ScenarioPrediction) -> Path:
        path = self.output_dir / "scenarios" / f"{scenario.id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        assumptions = "\n".join(f"- {a}" for a in (scenario.assumptions or []))
        path.write_text(f"# {scenario.statement}\n\n**Status:** {scenario.status}  \n**Timeframe:** {scenario.timeframe}  \n**Confidence:** {scenario.confidence:.0%}\n\n## Resolution Criteria\n{scenario.resolution_criteria}\n\n## Assumptions\n{assumptions}\n", encoding="utf-8")
        return path
