"""Repository interfaces for Phase C persistence and auditability."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Generic, TypeVar

from sqlalchemy import select, text
from sqlalchemy.orm import Session
import networkx as nx

from seldon.kb.vector import EmbeddingProvider, LocalHashEmbeddingProvider, cosine_similarity, pgvector_literal

from .models import (
    AgentMessage,
    AgentRun,
    AuditLog,
    ERGEdge,
    ERGNode,
    FeedbackEntry,
    GraphSnapshot,
    KBEntry,
    KBEntryContradiction,
    KBEntryVersion,
    ModelInvocation,
    Scenario,
    Source,
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
    data: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.key)
        # Source maps DB column "metadata" to Python attribute "metadata_" to
        # avoid colliding with SQLAlchemy's Base.metadata descriptor.
        if column.name == "metadata" and not isinstance(value, dict) and hasattr(row, "metadata_"):
            value = getattr(row, "metadata_")
        data[column.name] = _jsonable(value)
    return data


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


class SourceRepository(BaseRepository[Source]):
    model = Source
    audit_entity_type = "source"


class KBRepository(BaseRepository[KBEntry]):
    model = KBEntry
    audit_entity_type = "kb_entry"

    def __init__(self, session: Session, audit: AuditRepository | None = None, *, embedding_provider: EmbeddingProvider | None = None):
        super().__init__(session, audit=audit)
        self.embedding_provider = embedding_provider or LocalHashEmbeddingProvider()

    def _embed_values(self, values: dict[str, Any]) -> None:
        if values.get("content") and not values.get("content_embedding"):
            embedding = self.embedding_provider.embed(str(values["content"]))
            values["content_embedding"] = embedding.vector
            values["embedding_metadata"] = {**(values.get("embedding_metadata") or {}), **embedding.metadata}
            values.setdefault("vector_index_pointer", f"kb:{values.get('source_url') or values['content'][:32]}")

    def _sync_pgvector_column(self, row: KBEntry) -> None:
        if self.session.bind is None or self.session.bind.dialect.name != "postgresql" or not row.content_embedding:
            return
        self.session.execute(
            text("UPDATE kb_entries SET content_embedding_vector = CAST(:embedding AS vector) WHERE id = :id"),
            {"embedding": pgvector_literal(row.content_embedding), "id": row.id},
        )

    def create_entry(self, *, actor: str = "system", reason: str | None = None, **values: Any) -> KBEntry:
        self._embed_values(values)
        row = self.create(actor=actor, reason=reason, **values)
        self._sync_pgvector_column(row)
        self._version(row, actor=actor, reason=reason or "initial create")
        return row

    def update_entry(self, id: str, *, actor: str = "system", reason: str | None = None, **values: Any) -> KBEntry:
        self._embed_values(values)
        row = self.update(id, actor=actor, reason=reason, **values)
        self._sync_pgvector_column(row)
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

    def search(
        self,
        query: str | None = None,
        *,
        topic: str | None = None,
        entity: str | None = None,
        scenario_id: str | None = None,
        updated_since: datetime | None = None,
        valid_at: datetime | None = None,
        current_only: bool = False,
        min_sentiment: float | None = None,
        max_sentiment: float | None = None,
        min_confidence: float | None = None,
    ) -> list[KBEntry]:
        stmt = select(KBEntry)
        if query:
            stmt = stmt.where(KBEntry.content.ilike(f"%{query}%"))
        if updated_since:
            stmt = stmt.where(KBEntry.updated_at >= updated_since)
        if current_only:
            stmt = stmt.where(KBEntry.superseded_by.is_(None))
        results = list(self.session.scalars(stmt))
        if topic:
            results = [r for r in results if topic in (r.topics or [])]
        if entity:
            results = [r for r in results if entity in (r.entities or [])]
        if scenario_id:
            results = [r for r in results if scenario_id in (r.scenario_ids or [])]
        if valid_at:
            results = [r for r in results if (r.valid_from is None or r.valid_from <= valid_at) and (r.valid_until is None or r.valid_until >= valid_at)]
        if min_sentiment is not None:
            results = [r for r in results if (r.perspective_tags or {}).get("sentiment", 0) >= min_sentiment]
        if max_sentiment is not None:
            results = [r for r in results if (r.perspective_tags or {}).get("sentiment", 0) <= max_sentiment]
        if min_confidence is not None:
            results = [r for r in results if (r.perspective_tags or {}).get("confidence", 0) >= min_confidence]
        return results

    def semantic_search(self, query: str, *, limit: int = 10) -> list[KBEntry]:
        query_embedding = self.embedding_provider.embed(query).vector
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            rows = self._semantic_search_pgvector(query_embedding, limit=limit)
            if rows:
                return rows
        rows = list(self.session.scalars(select(KBEntry)))
        ranked = sorted(rows, key=lambda entry: (cosine_similarity(query_embedding, entry.content_embedding), query.lower() in entry.content.lower()), reverse=True)
        return ranked[:limit]

    def _semantic_search_pgvector(self, query_embedding: list[float], *, limit: int) -> list[KBEntry]:
        try:
            result = self.session.execute(
                text(
                    "SELECT id FROM kb_entries "
                    "WHERE content_embedding_vector IS NOT NULL "
                    "ORDER BY content_embedding_vector <=> CAST(:embedding AS vector) "
                    "LIMIT :limit"
                ),
                {"embedding": pgvector_literal(query_embedding), "limit": limit},
            )
            ids = [row[0] for row in result]
        except Exception:
            return []
        by_id = {entry.id: entry for entry in self.session.scalars(select(KBEntry).where(KBEntry.id.in_(ids)))} if ids else {}
        return [by_id[id] for id in ids if id in by_id]

    def decay_scores(self, entries: list[KBEntry], *, as_of: datetime | None = None, half_life_days: float = 30.0) -> dict[str, float]:
        as_of = as_of or datetime.now(timezone.utc)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        scores: dict[str, float] = {}
        for entry in entries:
            updated_at = entry.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age_days = max(0.0, (as_of - updated_at).total_seconds() / 86400)
            scores[entry.id] = 0.5 ** (age_days / half_life_days)
        return scores

    def confidence_summary(self, entries: list[KBEntry]) -> dict[str, float]:
        values = [(e.perspective_tags or {}).get("confidence") for e in entries]
        nums = [float(v) for v in values if v is not None]
        return {"count": len(nums), "average": sum(nums) / len(nums) if nums else 0.0}

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

    def list_nodes(self, *, scenario_id: str | None = None) -> list[ERGNode]:
        nodes = list(self.session.scalars(select(ERGNode)))
        if scenario_id is not None:
            nodes = [node for node in nodes if scenario_id in (node.scenario_ids or [])]
        return nodes

    def update_node(self, id: str, **values: Any) -> ERGNode:
        node = self.get_node(id)
        if node is None:
            raise KeyError(f"erg_node not found: {id}")
        before = row_to_dict(node)
        for key, value in values.items():
            setattr(node, key, value)
        self.session.flush()
        self.audit.emit("erg_node", id, "update", before=before, after=row_to_dict(node))
        return node

    def create_edge(self, **values: Any) -> ERGEdge:
        edge = ERGEdge(**values)
        self.session.add(edge)
        self.session.flush()
        self.audit.emit("erg_edge", edge.id, "create", after=row_to_dict(edge))
        return edge

    def update_edge(self, id: str, **values: Any) -> ERGEdge:
        edge = self.session.get(ERGEdge, id)
        if edge is None:
            raise KeyError(f"erg_edge not found: {id}")
        before = row_to_dict(edge)
        for key, value in values.items():
            setattr(edge, key, value)
        self.session.flush()
        self.audit.emit("erg_edge", id, "update", before=before, after=row_to_dict(edge))
        return edge

    def list_edges(self, node_id: str | None = None, *, scenario_id: str | None = None) -> list[ERGEdge]:
        stmt = select(ERGEdge)
        if node_id:
            stmt = stmt.where((ERGEdge.source_node_id == node_id) | (ERGEdge.target_node_id == node_id))
        edges = list(self.session.scalars(stmt))
        if scenario_id is not None:
            edges = [edge for edge in edges if scenario_id in (edge.scenario_ids or [])]
        return edges

    def to_networkx(self, *, scenario_id: str | None = None) -> nx.DiGraph:
        """Return a directed NetworkX view of persisted ERG rows.

        The DB remains the source of truth; this method builds an in-memory graph
        for algorithms. Multiple persisted relationship rows between the same
        ordered node pair are folded into one directed edge with the strongest
        confidence-weighted relationship as ``weight`` while retaining all
        source ``edge_ids`` and relationship metadata for auditability.
        """
        graph = nx.DiGraph(scenario_id=scenario_id)
        nodes = self.list_nodes(scenario_id=scenario_id)
        node_ids = {node.id for node in nodes}
        for node in nodes:
            graph.add_node(node.id, **row_to_dict(node))
        for edge in self.list_edges(scenario_id=scenario_id):
            if edge.source_node_id not in node_ids or edge.target_node_id not in node_ids:
                continue
            weight = max(0.01, edge.strength * edge.confidence)
            if graph.has_edge(edge.source_node_id, edge.target_node_id):
                attrs = graph[edge.source_node_id][edge.target_node_id]
                attrs["weight"] = max(attrs["weight"], weight)
                attrs["edge_ids"].append(edge.id)
                attrs["relationships"].append(row_to_dict(edge))
                attrs["evidence_kb_ids"] = sorted({*attrs.get("evidence_kb_ids", []), *(edge.evidence_kb_ids or [])})
            else:
                graph.add_edge(
                    edge.source_node_id,
                    edge.target_node_id,
                    weight=weight,
                    edge_ids=[edge.id],
                    relationships=[row_to_dict(edge)],
                    relationship_type=edge.relationship_type,
                    direction=edge.direction,
                    evidence_kb_ids=list(edge.evidence_kb_ids or []),
                )
        return graph

    def centrality_scores(self, *, scenario_id: str | None = None) -> dict[str, dict[str, float]]:
        """Compute reusable graph-algorithm scores for persisted ERG nodes."""
        graph = self.to_networkx(scenario_id=scenario_id)
        if not graph.nodes:
            return {}
        undirected = graph.to_undirected()
        degree = nx.degree_centrality(undirected)
        pagerank = self._pagerank_no_numpy(graph) if graph.number_of_edges() else {node: 1 / graph.number_of_nodes() for node in graph.nodes}
        betweenness = nx.betweenness_centrality(graph, weight="weight", normalized=True) if graph.number_of_edges() else {node: 0.0 for node in graph.nodes}
        closeness = nx.closeness_centrality(graph) if graph.number_of_edges() else {node: 0.0 for node in graph.nodes}
        max_reach = max(1, graph.number_of_nodes() - 1)
        return {
            node: {
                "degree": float(degree.get(node, 0.0)),
                "pagerank": float(pagerank.get(node, 0.0)),
                "betweenness": float(betweenness.get(node, 0.0)),
                "closeness": float(closeness.get(node, 0.0)),
                "dependency_reach": len(nx.descendants(graph, node)) / max_reach,
            }
            for node in graph.nodes
        }

    @staticmethod
    def _pagerank_no_numpy(graph: nx.DiGraph, *, alpha: float = 0.85, max_iter: int = 100, tol: float = 1.0e-6) -> dict[str, float]:
        """Small PageRank implementation that avoids optional numpy/scipy deps."""
        nodes = list(graph.nodes)
        if not nodes:
            return {}
        n = len(nodes)
        ranks = {node: 1.0 / n for node in nodes}
        teleport = (1.0 - alpha) / n
        outgoing_weight = {
            node: sum(max(0.0, graph[node][target].get("weight", 1.0)) for target in graph.successors(node))
            for node in nodes
        }
        for _ in range(max_iter):
            new_ranks = {node: teleport for node in nodes}
            dangling_rank = alpha * sum(ranks[node] for node in nodes if outgoing_weight[node] == 0.0) / n
            for node in nodes:
                new_ranks[node] += dangling_rank
            for source in nodes:
                total = outgoing_weight[source]
                if total == 0.0:
                    continue
                for target in graph.successors(source):
                    weight = max(0.0, graph[source][target].get("weight", 1.0))
                    new_ranks[target] += alpha * ranks[source] * weight / total
            if sum(abs(new_ranks[node] - ranks[node]) for node in nodes) < n * tol:
                return new_ranks
            ranks = new_ranks
        return ranks

    def export_graph_json(self) -> dict[str, Any]:
        return {"nodes": [row_to_dict(n) for n in self.list_nodes()], "edges": [row_to_dict(e) for e in self.list_edges()]}

    def create_snapshot(self, *, scenario_id: str | None = None, reason: str | None = None, agent_id: str | None = None) -> GraphSnapshot:
        snapshot = GraphSnapshot(scenario_id=scenario_id, snapshot=self.export_graph_json(), reason=reason, agent_id=agent_id)
        self.session.add(snapshot)
        self.session.flush()
        self.audit.emit("graph_snapshot", snapshot.id, "create", after=row_to_dict(snapshot), actor=agent_id or "system", reason=reason)
        return snapshot

    def reuse_candidates(self, scenario_id: str, *, query: str | None = None) -> dict[str, list[Any]]:
        nodes = self.list_nodes()
        edges = self.list_edges()
        if query:
            q = query.lower()
            nodes = [n for n in nodes if q in n.name.lower() or q in (n.description or "").lower()]
        nodes = [n for n in nodes if scenario_id not in (n.scenario_ids or [])]
        node_ids = {n.id for n in nodes}
        edges = [e for e in edges if e.source_node_id in node_ids or e.target_node_id in node_ids]
        return {"nodes": nodes, "edges": edges}

    def diff_snapshots(self, older: GraphSnapshot, newer: GraphSnapshot) -> dict[str, list[str]]:
        old_nodes = {n["id"] for n in older.snapshot.get("nodes", [])}
        new_nodes = {n["id"] for n in newer.snapshot.get("nodes", [])}
        old_edges = {e["id"] for e in older.snapshot.get("edges", [])}
        new_edges = {e["id"] for e in newer.snapshot.get("edges", [])}
        return {
            "added_nodes": sorted(new_nodes - old_nodes),
            "removed_nodes": sorted(old_nodes - new_nodes),
            "added_edges": sorted(new_edges - old_edges),
            "removed_edges": sorted(old_edges - new_edges),
        }


class ScenarioRepository(BaseRepository[ScenarioPrediction]):
    model = ScenarioPrediction
    audit_entity_type = "scenario_prediction"

    def create_scenario(self, *, actor: str = "system", reason: str | None = None, **values: Any) -> Scenario:
        row = Scenario(**values)
        self.session.add(row)
        self.session.flush()
        self.audit.emit("scenario", row.id, "create", actor=actor, reason=reason, after=row_to_dict(row))
        return row

    def record_feedback(self, *, actor: str = "system", reason: str | None = None, **values: Any) -> FeedbackEntry:
        row = FeedbackEntry(**values)
        self.session.add(row)
        self.session.flush()
        self.audit.emit("feedback_entry", row.id, "create", actor=actor, reason=reason, after=row_to_dict(row))
        return row

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
        self.session.flush()
        return v


class DatabaseModelInvocationRecorder:
    """Recorder compatible with OpenRouterClient that writes to model_invocations."""

    def __init__(self, session: Session, *, agent_run_id: str | None = None, auto_commit: bool = False):
        self.session = session
        self.agent_run_id = agent_run_id
        self.auto_commit = auto_commit

    def record(self, row: dict[str, Any]) -> None:
        invocation = ModelInvocation(
            agent_run_id=row.get("agent_run_id") or self.agent_run_id,
            agent=row.get("agent"),
            model=row.get("model") or "unknown",
            provider=row.get("provider"),
            latency_ms=int(row["latency_ms"]) if row.get("latency_ms") is not None else None,
            usage=row.get("usage") or {},
            estimated_cost=row.get("cost") or row.get("estimated_cost"),
            ok=bool(row.get("ok", True)),
            error=row.get("error"),
            raw_metadata=row,
        )
        self.session.add(invocation)
        if self.auto_commit:
            self.session.commit()


class AgentRunRepository(BaseRepository[AgentRun]):
    model = AgentRun
    audit_entity_type = "agent_run"

    def add_message(self, run_id: str, role: str, content: str, payload: dict[str, Any] | None = None) -> AgentMessage:
        row = AgentMessage(agent_run_id=run_id, role=role, content=content, payload=payload or {})
        self.session.add(row)
        self.session.flush()
        self.audit.emit("agent_message", row.id, "create", after=row_to_dict(row))
        return row

    def publish(self, run_id: str, event_type: str, *, content: str | None = None, payload: dict[str, Any] | None = None) -> AgentMessage:
        """Publish a structured inter-agent message on the run timeline."""
        envelope = {"event_type": event_type, **(payload or {})}
        return self.add_message(run_id, "event", content or event_type, payload=envelope)

    def timeline(self, run_id: str) -> list[AgentMessage]:
        return list(self.session.scalars(select(AgentMessage).where(AgentMessage.agent_run_id == run_id).order_by(AgentMessage.created_at)))

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
