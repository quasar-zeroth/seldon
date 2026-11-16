"""Shared knowledge library and the question-specific, bounded upstream view."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from seldon.data.models import (
    AgentRun,
    ERGEdge,
    ERGNode,
    GraphSnapshot,
    KBEntry,
    ScenarioPrediction,
)
from seldon.data.repositories import row_to_dict
from .schemas import GraphScope

CAUSAL_RELATIONS = {
    "causes",
    "constrains",
    "enables",
    "opposes",
    "amplifies",
    "dampens",
}


def saved_scope(db: Session, scenario_id: str) -> GraphScope:
    for run in db.scalars(
        select(AgentRun)
        .where(AgentRun.phase == "external_workspace")
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
    ):
        if run.input.get("scenario_id") == scenario_id and (run.output or {}).get(
            "graph_scope"
        ):
            return GraphScope.model_validate(run.output["graph_scope"])
    return GraphScope()


def scoped_graph(
    db: Session, scenario_id: str, scope: GraphScope | None = None, *, include_perspectives: bool = True
) -> dict:
    scope = scope or saved_scope(db, scenario_id)
    nodes = list(db.scalars(select(ERGNode)))
    edges = list(db.scalars(select(ERGEdge)))
    members = {n.id for n in nodes if scenario_id in (n.scenario_ids or [])}
    member_edges = [e for e in edges if scenario_id in (e.scenario_ids or [])]
    target = scope.target_node_id
    if not target:
        latest = db.scalar(
            select(ScenarioPrediction)
            .where(ScenarioPrediction.scenario_id == scenario_id)
            .order_by(
                ScenarioPrediction.created_at.desc(), ScenarioPrediction.id.desc()
            )
        )
        target = (
            ((latest.calibration_result or {}).get("forecast") or {}).get(
                "target_node_id"
            )
            if latest
            else None
        )
    if not target:
        sinks = members - {e.source_node_id for e in member_edges}
        target = next(iter(sinks)) if len(sinks) == 1 else None
    if target and target not in members:
        raise ValueError(
            "The forecast target must belong to this question; reuse or create it first"
        )
    if target in scope.excluded_node_ids:
        raise ValueError("The forecast target cannot be excluded")
    resolved = scope.model_copy(update={"target_node_id": target})
    graph = nx.DiGraph()
    available = {
        n.id for n in nodes if n.scenario_ids and n.id not in scope.excluded_node_ids
    }
    graph.add_nodes_from(available)
    eligible = [
        e
        for e in edges
        if e.scenario_ids
        and e.relationship_type in CAUSAL_RELATIONS
        and e.id not in scope.excluded_edge_ids
        and e.source_node_id in available
        and e.target_node_id in available
    ]
    graph.add_edges_from((e.source_node_id, e.target_node_id) for e in eligible)
    if target:
        distances = dict(
            nx.single_source_shortest_path_length(
                graph.reverse(copy=False), target, cutoff=scope.max_depth
            )
        )
        selected = set(distances)
        selected_edges = [
            e
            for e in eligible
            if e.source_node_id in selected and e.target_node_id in selected
        ]
    else:
        # Drafts with multiple disconnected candidates need an explicit target before forecasting.
        selected = members - set(scope.excluded_node_ids)
        distances = {}
        selected_edges = [
            e
            for e in member_edges
            if e.source_node_id in selected
            and e.target_node_id in selected
            and e.id not in scope.excluded_edge_ids
        ]
    selected_nodes = [n for n in nodes if n.id in selected]
    view = nx.DiGraph()
    view.add_nodes_from(selected)
    view.add_edges_from((e.source_node_id, e.target_node_id) for e in selected_edges)
    evidence_ids = {id for n in selected_nodes for id in n.kb_entry_ids or []} | {
        id for e in selected_edges for id in e.evidence_kb_ids or []
    }
    evidence = [
        e
        for e in db.scalars(select(KBEntry))
        if e.id in evidence_ids
        or (not target and scenario_id in (e.scenario_ids or []))
    ]
    from .perspectives import research_context
    perspectives = research_context(db, selected_nodes, evidence) if include_perspectives else {}
    return {
        "perspectives": perspectives,
        "scope": resolved,
        "nodes": selected_nodes,
        "edges": selected_edges,
        "evidence": evidence,
        "graph": view,
        "distances": distances,
        "excluded_member_ids": sorted(members - selected),
        "library_node_count": len(nodes),
    }


def snapshot_data(view: dict) -> dict:
    def dump(row):
        result = row_to_dict(row)
        for column in row.__table__.columns:
            value = getattr(row, column.key)
            if isinstance(value, datetime):
                result[column.name] = (
                    value.replace(tzinfo=value.tzinfo or timezone.utc)
                    .astimezone(timezone.utc)
                    .isoformat()
                )
        return result

    evidence = [dump(e) for e in view["evidence"]]
    for row in evidence:
        row.pop("content_embedding", None)
    return {
        **({"perspectives": view["perspectives"]} if view.get("perspectives", {}).get("claims") else {}),
        "nodes": sorted([dump(n) for n in view["nodes"]], key=lambda x: x["id"]),
        "edges": sorted([dump(e) for e in view["edges"]], key=lambda x: x["id"]),
        "evidence": sorted(evidence, key=lambda x: x["id"]),
        "scope": view["scope"].model_dump(),
    }


def knowledge_revision(view: dict) -> str:
    data = snapshot_data(view)
    # Membership/DB timestamp changes in another question aren't changes to the facts.
    for kind in ("nodes", "edges", "evidence"):
        for row in data[kind]:
            for key in ("scenario_ids", "created_at", "updated_at", "state_updated_at"):
                row.pop(key, None)
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()


def freeze_graph(
    db: Session, scenario_id: str, view: dict, *, agent: str, reason: str
) -> GraphSnapshot:
    row = GraphSnapshot(
        scenario_id=scenario_id,
        snapshot=snapshot_data(view),
        agent_id=agent,
        reason=reason,
    )
    db.add(row)
    db.flush()
    return row


def search_library(db: Session, query: str = "", limit: int = 30, *, tag: str | None = None, offset: int = 0, entity_id: str | None = None) -> dict:
    from seldon.data.tags import normalize_tag
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Library limit must be 1–100 and offset must be nonnegative")
    terms = query.casefold().split()
    matches = []
    for node in db.scalars(select(ERGNode).order_by(ERGNode.name, ERGNode.id)):
        if entity_id and node.id != entity_id:
            continue
        if tag and normalize_tag(tag) not in (node.tags or []):
            continue
        text = f"{node.name} {node.description} {node.current_state or ''} {' '.join(node.tags or [])}".casefold()
        if terms and not all(term in text for term in terms):
            continue
        evidence = [db.get(KBEntry, id) for id in node.kb_entry_ids or []]
        matches.append(
            {
                **row_to_dict(node),
                "evidence": [
                    {
                        k: v
                        for k, v in row_to_dict(e).items()
                        if k != "content_embedding"
                    }
                    for e in evidence
                    if e
                ],
            }
        )
    return {"nodes": matches[offset:offset + limit], "total": len(matches), "offset": offset, "limit": limit}
