"""Transactional research exchange over Seldon's existing durable repositories.

No model clients or retrieval providers are constructed here. Semantic judgments
come from the calling agent; structural and provenance gates are enforced here.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import networkx as nx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from seldon.data.models import (
    AgentRun,
    ERGEdge,
    ERGNode,
    KBEntry,
    Scenario,
    ScenarioPrediction,
)
from seldon.data.repositories import (
    AgentRunRepository,
    AuditRepository,
    GraphRepository,
    KBRepository,
    ScenarioRepository,
    row_to_dict,
)
from seldon.workspace.schemas import StartRequest, WorkspaceApply
from seldon.workspace.knowledge import (
    freeze_graph,
    knowledge_revision,
    saved_scope,
    scoped_graph,
)


class WorkspaceConflict(ValueError):
    """The caller must export current state before making another change."""


def record_id(scenario_id: str, kind: str, key: str) -> str:
    try:
        return str(UUID(key))
    except ValueError:
        return str(uuid5(NAMESPACE_URL, f"seldon:{scenario_id}:{kind}:{key}"))


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def _row(row) -> dict:
    result = row_to_dict(row)
    # SQLite drops timezone annotations; interpret stored timestamps as UTC so
    # revisions survive commits, process restarts, and different DB backends.
    for column in row.__table__.columns:
        value = getattr(row, column.key)
        if isinstance(value, datetime):
            result[column.name] = (
                value.replace(tzinfo=value.tzinfo or timezone.utc)
                .astimezone(timezone.utc)
                .isoformat()
            )
    return result


class WorkspaceService:
    def __init__(self, db: Session):
        self.db = db
        self.graph = GraphRepository(db)

    def start(self, question: str, horizon: str, *, name: str | None = None) -> dict:
        request = StartRequest(question=question, horizon=horizon, name=name)
        question, horizon, name = request.question, request.horizon, request.name
        scenario = ScenarioRepository(self.db).create_scenario(
            name=name or question[:120],
            target_question=question,
            original_prompt=question,
            time_horizon=horizon,
            actor="external_agent",
            description="Agent-led research; see workspace runs for evidence, DAG reasoning, and forecasts.",
        )
        return self.export(scenario.id)

    def export(self, scenario_id: str) -> dict:
        scenario = self.db.get(Scenario, scenario_id)
        if scenario is None:
            raise KeyError(f"Scenario not found: {scenario_id}")
        view = scoped_graph(self.db, scenario_id)
        evidence = [_row(e) for e in view["evidence"]]
        for item in evidence:
            item.pop("content_embedding", None)
        runs = [
            _row(r)
            for r in self.db.scalars(select(AgentRun))
            if r.phase == "external_workspace"
            and r.input.get("scenario_id") == scenario_id
        ]
        data = {
            "schema_version": 1,
            **({"perspectives": view["perspectives"]} if view.get("perspectives", {}).get("claims") else {}),
            **({"cycles": view["cycles"]} if view.get("cycles") else {}),
            "scenario": _row(scenario),
            "evidence": sorted(evidence, key=lambda x: x["id"]),
            "nodes": sorted(
                [_row(n) for n in view["nodes"]],
                key=lambda x: x["id"],
            ),
            "edges": sorted(
                [_row(e) for e in view["edges"]],
                key=lambda x: x["id"],
            ),
            "predictions": [
                _row(p)
                for p in self.db.scalars(
                    select(ScenarioPrediction)
                    .where(ScenarioPrediction.scenario_id == scenario_id)
                    .order_by(ScenarioPrediction.created_at, ScenarioPrediction.id)
                )
            ],
            "runs": sorted(runs, key=lambda x: (x["created_at"], x["id"])),
            "graph_scope": view["scope"].model_dump(),
        }
        data["revision"] = _digest(
            {
                "visible": data,
                "members": {
                    "nodes": sorted(
                        [
                            _row(n)
                            for n in self.graph.list_nodes(scenario_id=scenario_id)
                        ],
                        key=lambda n: n["id"],
                    ),
                    "edges": sorted(
                        [
                            _row(e)
                            for e in self.graph.list_edges(scenario_id=scenario_id)
                        ],
                        key=lambda e: e["id"],
                    ),
                    "evidence": sorted(
                        [
                            _row(e)
                            for e in self.db.scalars(select(KBEntry))
                            if scenario_id in (e.scenario_ids or [])
                        ],
                        key=lambda e: e["id"],
                    ),
                },
            }
        )
        data["knowledge_revision"] = knowledge_revision(view)
        data["scope_details"] = {
            "direction": "upstream",
            "distances": view["distances"],
            "excluded_member_ids": view["excluded_member_ids"],
            "library_node_count": view["library_node_count"],
        }
        graph = view["graph"]
        data["dag"] = {
            "acyclic": nx.is_directed_acyclic_graph(graph),
            "edge_orientation": "upstream driver -> downstream effect",
        }
        if data["dag"]["acyclic"]:
            data["dag"]["topological_order"] = list(
                nx.lexicographical_topological_sort(graph)
            )
        from seldon.workspace.reruns import list_requests, prediction_history

        data["prediction_history"] = prediction_history(self.db, scenario_id)
        data["prediction_requests"] = list_requests(self.db, scenario_id)
        # Derived handoff stays outside the revision: host paths are not knowledge.
        repository = Path(__file__).resolve().parents[3]
        url = self.db.get_bind().url
        if url.get_backend_name() == "sqlite" and url.database not in {None, ":memory:"}:
            database = shlex.quote(str(Path(url.database).resolve()))
            access = f"From {repository}, use uv run seldon research --db {database}"
        else:
            access = "Use this server's authenticated /workspace HTTP interface"
        from .cases import CASE_GENERATION_GUIDANCE
        from .cycles.catalog import CYCLE_GUIDANCE
        from .transcripts.catalog import TRANSCRIPT_GUIDANCE

        data["research_handoff"] = (
            f"Read {repository / 'AGENTS.md'} and {repository / 'docs/agent-workflow.md'}. "
            f"Continue existing research scenario {scenario_id}; do not create another scenario. "
            f"Question: {scenario.target_question}\nHorizon / as-of scope: {scenario.time_horizon}\n"
            f"{access}. Export this scenario first and use its fresh revision. "
            "Search the shared library before adding entities; reuse relevant UUIDs and verify dated evidence. "
            "Assign evidence-grounded tags on every entity creation/update (data-center for physical campuses, plus country/region and roles where established). Search library with --tag data-center and paginate until total is covered. When reports are requested, generate and store summary and detailed versions with research reports generate. Define a question target and upstream dependency depth, gather sources with your current agent's "
            "search tools, and persist material rounds with research apply. Distinguish observations, "
            "assumptions, and unknowns. Inspect perspectives export for conflicting claims, source affiliations, and dated trust/leaning assessments. Use perspectives catalog and perspectives connections to navigate entity/topic/claim/source paths, preserving explicit identities and relationship direction. Use perspectives apply to add sourced judgments; never treat repeated coverage as independent confirmation or an observation as a verified fact. Reconcile disputed or superseded claims explicitly in forecasts. Investigate counterevidence and record coverage and remaining gaps. "
            + CYCLE_GUIDANCE + " Procedure: skills/seldon-cycles/SKILL.md. "
            + TRANSCRIPT_GUIDANCE + " "
            "For a current-state investigation, save a research summary without inventing a forecast. "
            "If a prediction is requested, define a future resolution date and measurable criteria, "
            "assess all scoped nodes, and save reviewed forecast branches. "
            + CASE_GENERATION_GUIDANCE + " Export Markdown and JSON. "
            "Use your existing agent session; do not invoke provider-backed run endpoints or place trades."
        )
        return data

    def apply(self, payload: WorkspaceApply, *, media: list[dict] | None = None) -> dict:
        """`media` is transcript provenance supplied by transcripts.ingest, not by callers' JSON."""
        # Savepoint makes Python/API callers safe even if they catch a validation
        # error and subsequently commit their outer transaction.
        connection = self.db.connection()
        if (
            connection.dialect.name == "sqlite"
            and not connection.connection.driver_connection.in_transaction
        ):
            # sqlite3 legacy transaction control does not BEGIN for SAVEPOINT;
            # ensure releasing it cannot commit ahead of the caller's transaction.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        with self.db.begin_nested():
            return self._apply(payload, media)

    def _apply(self, p: WorkspaceApply, media: list[dict] | None = None) -> dict:
        # Serialize scenario mutations on SQLite and PostgreSQL before reading the
        # revision, without changing the scenario's timestamp on a no-op/replay.
        self.db.execute(
            update(Scenario)
            .where(Scenario.id == p.scenario_id)
            .values(updated_at=Scenario.updated_at)
        )
        before = self.export(p.scenario_id)
        request = p.model_dump(mode="json")
        # Preserve request fingerprints for exact replays authored before reuse/scope support.
        for key in (
            "graph_scope",
            "reuse_node_ids",
            "reuse_edge_ids",
            "reuse_evidence_ids",
            "allow_shared_updates",
            "prediction_request_id",
        ):
            if not request[key]:
                request.pop(key)
        for item in request["nodes"]:
            if item.get("tags") is None:
                item.pop("tags", None)
        if request.get("forecast") and request["forecast"].get("case_bounds") is None:
            request["forecast"].pop("case_bounds", None)
        if media:
            request["media"] = media
        fingerprint = _digest(request)
        for run in before["runs"]:
            if run["input"].get("request_id") == p.request_id:
                if run["input"].get("request_hash") != fingerprint:
                    raise WorkspaceConflict(
                        "request_id already used for different input"
                    )
                return {
                    **run["output"],
                    "replayed": True,
                    "revision": before["revision"],
                }
        if p.base_revision != before["revision"]:
            raise WorkspaceConflict(
                "Stale base_revision; export the scenario and reconcile your changes"
            )
        if (
            p.research_round
            and p.research_round.stop_reason == "exhausted"
            and (
                p.evidence
                or p.nodes
                or p.edges
                or p.detach_nodes
                or p.detach_edges
                or p.reuse_node_ids
                or p.reuse_edge_ids
                or p.reuse_evidence_ids
                or p.graph_scope
            )
        ):
            raise ValueError(
                "An exhausted research round must not also change evidence or graph; save findings first"
            )
        ids: dict[str, dict[str, str]] = {}
        for kind, rows in (
            ("evidence", p.evidence),
            ("node", p.nodes),
            ("edge", p.edges),
        ):
            values = [record_id(p.scenario_id, kind, r.id) for r in rows]
            if len(set(values)) != len(values):
                raise ValueError(f"Duplicate {kind} IDs")
            ids[kind] = {r.id: value for r, value in zip(rows, values)}

        def ref(kind: str, key: str) -> str:
            return record_id(p.scenario_id, kind, key)

        readable = {
            row["id"] for kind in ("nodes", "edges", "evidence") for row in before[kind]
        }

        def reuse(model, id):
            row = self.db.get(model, str(UUID(id)))
            if row is None:
                raise ValueError(f"Shared record not found: {id}")
            if p.scenario_id not in (row.scenario_ids or []):
                row.scenario_ids = [*(row.scenario_ids or []), p.scenario_id]
                AuditRepository(self.db).emit(
                    model.__tablename__,
                    row.id,
                    "reuse",
                    actor=p.agent,
                    reason=p.reason,
                    after={"scenario_id": p.scenario_id},
                )
            readable.add(row.id)
            if isinstance(row, ERGNode):
                for evidence_id in row.kb_entry_ids or []:
                    reuse(KBEntry, evidence_id)
            if isinstance(row, ERGEdge):
                reuse(ERGNode, row.source_node_id)
                reuse(ERGNode, row.target_node_id)
                for evidence_id in row.evidence_kb_ids or []:
                    reuse(KBEntry, evidence_id)

        for model, values in (
            (ERGNode, p.reuse_node_ids),
            (ERGEdge, p.reuse_edge_ids),
            (KBEntry, p.reuse_evidence_ids),
        ):
            for id in values:
                reuse(model, id)

        def scoped(model, id: str, *, required: bool = True):
            row = self.db.get(model, id)
            if row is None and required:
                raise ValueError(f"Missing reference: {id}")
            if (
                row is not None
                and p.scenario_id not in (row.scenario_ids or [])
                and id not in readable
            ):
                raise ValueError(f"Reference belongs to another scenario: {id}")
            return row

        def writable(model, id: str):
            row = scoped(model, id, required=False)
            if (
                row
                and (len(row.scenario_ids) > 1 or p.scenario_id not in row.scenario_ids)
                and not p.allow_shared_updates
            ):
                raise ValueError(
                    "Shared records require explicit cross-scenario review; set allow_shared_updates after reviewing other uses"
                )
            return row

        def evidence_refs(keys: list[str]) -> list[str]:
            result = [ref("evidence", key) for key in keys]
            for id in result:
                row = scoped(KBEntry, id)
                if row.superseded_by:
                    raise ValueError(f"Evidence is superseded: {id}")
            return result

        detached = {"nodes": [], "edges": []}
        for kind, keys, model in (
            ("edge", p.detach_edges, ERGEdge),
            ("node", p.detach_nodes, ERGNode),
        ):
            values = [ref(kind, key) for key in keys]
            if len(set(values)) != len(values) or set(values) & set(ids[kind].values()):
                raise ValueError(
                    "A record may be detached only once and cannot also be updated in the same request"
                )
            for id in values:
                row = scoped(model, id)
                memberships = [s for s in row.scenario_ids if s != p.scenario_id]
                if kind == "edge":
                    self.graph.update_edge(id, scenario_ids=memberships)
                else:
                    self.graph.update_node(id, scenario_ids=memberships)
                detached[kind + "s"].append(id)

        kb = KBRepository(self.db)
        now = datetime.now(timezone.utc)
        for e in p.evidence:
            id = ref("evidence", e.id)
            existing = writable(KBEntry, id)
            values = dict(
                content=e.content,
                source_type=e.kind,
                source_name=e.source_name,
                source_url=e.source_url,
                valid_from=e.published_at.astimezone(timezone.utc)
                if e.published_at
                else None,
                scenario_ids=existing.scenario_ids if existing else [p.scenario_id],
                perspective_tags={
                    "confidence": e.confidence,
                    "kind": e.kind,
                    "retrieved_at": e.retrieved_at.isoformat(),
                },
            )
            if existing:
                kb.update_entry(id, actor=p.agent, reason=p.reason, **values)
            else:
                kb.create_entry(id=id, actor=p.agent, reason=p.reason, **values)
        for n in p.nodes:
            id = ref("node", n.id)
            existing = writable(ERGNode, id)
            values = dict(
                name=n.name,
                type=n.type,
                tags=n.tags,
                description=n.description,
                current_state=n.current_state,
                state_updated_at=now,
                kb_entry_ids=evidence_refs(n.evidence_ids),
                scenario_ids=existing.scenario_ids if existing else [p.scenario_id],
            )
            if existing:
                self.graph.update_node(id, **values)
            else:
                self.graph.create_node(id=id, **values)
        for e in p.edges:
            id = ref("edge", e.id)
            existing = writable(ERGEdge, id)
            source, target = ref("node", e.source), ref("node", e.target)
            scoped(ERGNode, source)
            scoped(ERGNode, target)
            # A new scenario relationship also adopts its already-visible endpoints.
            reuse(ERGNode, source)
            reuse(ERGNode, target)
            values = dict(
                source_node_id=source,
                target_node_id=target,
                relationship_type=e.relationship,
                description=e.description,
                direction=e.direction,
                strength=e.strength,
                confidence=e.confidence,
                lag=e.lag,
                evidence_kb_ids=evidence_refs(e.evidence_ids),
                scenario_ids=existing.scenario_ids if existing else [p.scenario_id],
            )
            if existing:
                self.graph.update_edge(id, **values)
            else:
                duplicate = self.db.scalar(
                    select(ERGEdge).where(
                        ERGEdge.source_node_id == source,
                        ERGEdge.target_node_id == target,
                        ERGEdge.relationship_type == e.relationship,
                    )
                )
                if duplicate:
                    raise ValueError(
                        f"Relationship already exists: {duplicate.id}; reuse it through reuse_edge_ids"
                    )
                self.graph.create_edge(id=id, **values)

        nodes = self.graph.list_nodes(scenario_id=p.scenario_id)
        edges = self.graph.list_edges(scenario_id=p.scenario_id)
        node_ids = {n.id for n in nodes}
        for edge in edges:
            if (
                edge.source_node_id not in node_ids
                or edge.target_node_id not in node_ids
            ):
                raise ValueError(
                    "Scenario contains an edge with missing or out-of-scenario endpoints"
                )
        graph = self.graph.to_networkx(scenario_id=p.scenario_id)
        if not nx.is_directed_acyclic_graph(graph):
            raise ValueError(
                f"Scenario must be a DAG; cycle: {nx.find_cycle(graph)}. Time-index feedback instead."
            )
        scope = p.graph_scope or saved_scope(self.db, p.scenario_id)
        if scope.target_node_id:
            scope = scope.model_copy(
                update={"target_node_id": ref("node", scope.target_node_id)}
            )
        elif p.forecast:
            scope = scope.model_copy(
                update={"target_node_id": ref("node", p.forecast.target_node_id)}
            )
        scope = scope.model_copy(
            update={
                "excluded_node_ids": sorted(
                    (
                        {ref("node", id) for id in scope.excluded_node_ids}
                        | {ref("node", id) for id in p.detach_nodes}
                    )
                    - set(p.reuse_node_ids)
                ),
                "excluded_edge_ids": sorted(
                    (
                        {ref("edge", id) for id in scope.excluded_edge_ids}
                        | {ref("edge", id) for id in p.detach_edges}
                    )
                    - set(p.reuse_edge_ids)
                ),
            }
        )
        from .perspectives import index_scenario
        index_scenario(self.db, p.scenario_id, agent=p.agent, scope=scope)
        view = scoped_graph(self.db, p.scenario_id, scope)
        nodes, edges, graph = view["nodes"], view["edges"], view["graph"]
        node_ids = {n.id for n in nodes}
        readable.update(n.id for n in nodes)
        readable.update(e.id for e in view["evidence"])
        if not nx.is_directed_acyclic_graph(graph):
            raise ValueError(
                "Relevant shared dependencies contain a cycle; time-index or exclude the disputed relationship"
            )
        research = (
            p.research_round.model_dump(mode="json") if p.research_round else None
        )
        if research:
            research["checked_node_ids"] = [
                ref("node", key) for key in research["checked_node_ids"]
            ]
            if not set(research["checked_node_ids"]) <= node_ids:
                raise ValueError("Research round refers to unknown nodes")
        prediction_id = None
        forecast = None
        if p.forecast:
            if not research or research["stop_reason"] == "continue":
                raise ValueError(
                    "Forecast requires an explicit completed research round (exhausted or budget)"
                )
            if set(research["checked_node_ids"]) != node_ids:
                raise ValueError("Final research review must cover every scenario node")
            f = p.forecast
            target = ref("node", f.target_node_id)
            if target != view["scope"].target_node_id:
                raise ValueError(
                    "Forecast target differs from the configured graph scope"
                )
            if target not in graph or len(graph) < 2 or not edges:
                raise ValueError(
                    "Forecast requires a target and a connected dependency DAG"
                )
            if any(
                id != target and not nx.has_path(graph, id, target) for id in node_ids
            ):
                raise ValueError(
                    "Every scenario node must influence the forecast target through a directed path"
                )
            for n in nodes:
                if not n.kb_entry_ids:
                    raise ValueError(
                        f"Node lacks evidence or an explicit assumption: {n.name}"
                    )
                evidence_refs(n.kb_entry_ids)
            for e in edges:
                if e.relationship_type in {"depends_on", "correlates_with"}:
                    raise ValueError(
                        "Forecast DAG must contain upstream influence edges; review dependency/correlation orientation"
                    )
                if not e.evidence_kb_ids:
                    raise ValueError(
                        f"Edge lacks evidence or an explicit assumption: {e.id}"
                    )
                evidence_refs(e.evidence_kb_ids)
            assessments = [ref("node", a.node_id) for a in f.node_assessments]
            if set(assessments) != node_ids or len(assessments) != len(node_ids):
                raise ValueError("Provide exactly one forecast assessment per node")
            evidence_ids = set()
            if f.case_bounds:
                for bound in (f.case_bounds.lower, f.case_bounds.upper):
                    bound_refs = evidence_refs(bound.evidence_ids)
                    if not set(bound_refs) <= {entry.id for entry in view["evidence"]}:
                        raise ValueError("Hot-take bounds cite evidence outside the configured dependency scope")
                    evidence_ids.update(bound_refs)
            for a in f.node_assessments:
                refs = evidence_refs(a.evidence_ids)
                node = scoped(ERGNode, ref("node", a.node_id))
                if not set(refs) <= set(node.kb_entry_ids):
                    raise ValueError(
                        "Node assessments must cite evidence attached to that node"
                    )
                evidence_ids.update(refs)
            evidence_ids.update(id for n in nodes for id in n.kb_entry_ids)
            evidence_ids.update(id for e in edges for id in e.evidence_kb_ids)
            observations = []
            for id in evidence_ids:
                entry = scoped(KBEntry, id)
                if entry.source_type == "observation":
                    observations.append(entry)
                    published = entry.valid_from
                    if (
                        published
                        and published.replace(tzinfo=published.tzinfo or timezone.utc)
                        > f.as_of
                    ):
                        raise ValueError(
                            "Forecast cannot use evidence published after as_of"
                        )
            if not observations:
                raise ValueError(
                    "Forecast requires observed source evidence, not assumptions alone"
                )
            forecast = f.model_dump(mode="json")
            if f.case_bounds:
                for bound in forecast["case_bounds"].values():
                    bound["evidence_ids"] = evidence_refs(bound["evidence_ids"])
            forecast["target_node_id"] = target
            for assessment in forecast["node_assessments"]:
                assessment["node_id"] = ref("node", assessment["node_id"])
                assessment["evidence_ids"] = evidence_refs(assessment["evidence_ids"])
            snapshot = freeze_graph(
                self.db, p.scenario_id, view, reason=p.reason, agent=p.agent
            )
            scenario = self.db.get(Scenario, p.scenario_id)
            scenario.erg_snapshot_id = snapshot.id
            scenario.kb_snapshot_at = now
            repo = ScenarioRepository(self.db)
            prediction = repo.create_prediction(
                scenario_id=p.scenario_id,
                statement=f.statement,
                scope=f.units,
                timeframe=f.resolution_date.isoformat(),
                resolution_criteria=f.resolution_criteria,
                scenarios=[b.model_dump(mode="json") for b in f.branches],
                probabilities={b.key: b.probability for b in f.branches},
                confidence=f.confidence,
                key_drivers=[id for id in nx.topological_sort(graph) if id != target],
                evidence_links=sorted(evidence_ids),
                assumptions=f.assumptions,
                status="active",
                actor=p.agent,
                reason=p.reason,
                probability_history=[
                    {
                        "as_of": f.as_of.isoformat(),
                        "probabilities": {b.key: b.probability for b in f.branches},
                    }
                ],
                calibration_result={
                    "method": "external_agent_judgment",
                    "calibrated": False,
                    "graph_snapshot_id": snapshot.id,
                    "knowledge_revision": knowledge_revision(view),
                    "graph_scope": view["scope"].model_dump(),
                    "forecast": forecast,
                    "research_round": research,
                },
            )
            prediction_id = prediction.id
            if p.prediction_request_id:
                from seldon.workspace.reruns import complete_request

                complete_request(
                    self.db,
                    p.prediction_request_id,
                    p.scenario_id,
                    prediction_id,
                    p.agent,
                )
        elif p.prediction_request_id:
            raise ValueError("Completing a prediction request requires a forecast")

        output = {
            "scenario_id": p.scenario_id,
            "ids": ids,
            "detached": detached,
            "prediction_id": prediction_id,
            "research_round": research,
            "forecast": forecast,
            "graph_scope": view["scope"].model_dump(),
            "topological_order": list(nx.lexicographical_topological_sort(graph)),
        }
        from seldon.workspace.pipeline import workspace_steps

        output["pipeline_steps"] = workspace_steps(request, output)
        run = AgentRunRepository(self.db).create(
            agent_id=p.agent,
            phase="external_workspace",
            status="completed",
            input={**request, "request_hash": fingerprint},
            output=output,
            source_references=[e.source_url for e in p.evidence if e.source_url],
            elapsed_ms=None,
            actor=p.agent,
            reason=p.reason,
        )
        output = {**output, "run_id": run.id}
        run.output = output
        AuditRepository(self.db).emit(
            "scenario",
            p.scenario_id,
            "external_workspace_apply",
            actor=p.agent,
            reason=p.reason,
            after=output,
        )
        self.db.flush()
        return {
            **output,
            "revision": self.export(p.scenario_id)["revision"],
            "replayed": False,
        }


def render_markdown(data: dict) -> str:
    """Lossless text handoff: overview plus JSON for every persisted section."""
    scenario = data["scenario"]
    lines = [
        f"# {scenario['name']}",
        "",
        scenario["target_question"],
        "",
        f"Horizon: {scenario['time_horizon']}",
        f"Revision: {data['revision']}",
        "",
    ]
    latest_research = next(
        (
            research
            for run in reversed(data.get("runs", []))
            if (
                research := (run.get("output") or {}).get("research_round")
                or (run.get("input") or {}).get("research_round")
            )
        ),
        None,
    )
    if latest_research:
        lines.extend(
            [
                "## Latest research findings",
                "",
                latest_research.get("summary", ""),
                "",
                f"Research stop reason: {latest_research.get('stop_reason', 'Not recorded')}",
                "",
            ]
        )
        if latest_research.get("remaining_gaps"):
            lines.extend(["### Remaining gaps", ""])
            lines.extend(f"- {gap}" for gap in latest_research["remaining_gaps"])
            lines.append("")
    if data["predictions"]:
        prediction = data["predictions"][-1]
        details = (prediction.get("calibration_result") or {}).get("forecast", {})
        from .cases import case_bounds_markdown

        bounds = details.get("case_bounds") or (prediction.get("calibration_result") or {}).get("case_bounds")
        lines.extend(
            [
                "## Latest forecast",
                "",
                "Forecast probabilities are agent judgments, not a calibrated statistical model.",
                "",
                prediction["statement"],
                "",
                f"Units: {prediction['scope']}; resolution: {prediction['timeframe']}",
                f"As of: {details.get('as_of', 'See prediction history')}",
                "",
                *case_bounds_markdown(bounds),
                "| Branch | Probability | Outcome |",
                "| --- | ---: | --- |",
            ]
        )
        for branch in prediction["scenarios"]:
            if isinstance(branch.get("probability"), (float, int)):
                outcome = (
                    str(branch.get("outcome", ""))
                    .replace("|", "\\|")
                    .replace("\n", " ")
                )
                lines.append(
                    f"| {branch.get('key', 'scenario')} | {branch['probability']:.0%} | {outcome} |"
                )
        lines.extend(
            [
                "",
                prediction["resolution_criteria"],
                "",
                details.get("synthesis", ""),
                "",
                "### Assumptions and uncertainties",
                "",
            ]
        )
        for item in [
            *details.get("assumptions", []),
            *details.get("uncertainties", []),
            *details.get("red_team", []),
        ]:
            lines.append(f"- {item}")
        lines.extend(["", f"Base rate: {details.get('base_rate', 'Not recorded')}", ""])
    lines.extend(cycles_markdown(data.get("cycles")))
    if data["nodes"]:
        lines.extend(["## Knowledge and evidence by node", ""])
        for node in data["nodes"]:
            lines.extend(
                [
                    f"### {node['name']}",
                    "",
                    node.get("current_state") or "No current assessment recorded.",
                    "",
                ]
            )
    lines.extend(["## Dependency map", "", "```mermaid", "flowchart LR"])
    labels = {node["id"]: f"n{i}" for i, node in enumerate(data["nodes"])}
    for node in data["nodes"]:
        name = node["name"].replace('"', "&quot;").replace("\n", " ")
        lines.append(f'  {labels[node["id"]]}["{name}"]')
    for edge in data["edges"]:
        if edge["source_node_id"] in labels and edge["target_node_id"] in labels:
            lines.append(
                f"  {labels[edge['source_node_id']]} --> {labels[edge['target_node_id']]}"
            )
    lines.extend(["```", "", "## Source index", ""])
    for entry in data["evidence"]:
        label = entry["source_name"].replace("[", "").replace("]", "")
        url = entry.get("source_url")
        source = (
            f"[{label}]({url})"
            if url and url.startswith(("https://", "http://"))
            else label
        )
        lines.append(f"- {source}: {entry['content']}")
    lines.append("")
    for label in ("dag", "evidence", "nodes", "edges", "predictions", "runs", "perspectives", *(("cycles",) if data.get("cycles") else ())):
        lines.extend(
            [
                f"## {label.replace('_', ' ').title()}",
                "",
                "```json",
                json.dumps(data.get(label, {}), indent=2, ensure_ascii=False),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def cycles_markdown(context: dict | None) -> list[str]:
    """Readable summary of linked cycle priors; empty when none are linked."""
    if not context:
        return []
    lines = [
        "## Cycle priors",
        "",
        "Model-derived structural priors from historical curve fits, not observations. Only 'supported' verdicts beat red-noise and holdout checks.",
        "",
        f"Evaluated at: {context.get('at') or 'last observation (no horizon date found)'}",
        "",
        "| Factor | Verdict | Period (years) | Phase | Projection | Next turning point |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for factor in context.get("factors", []):
        fit = factor.get("fit") or {}
        cycles = fit.get("cycles") or ([fit["dynamics"]] if fit.get("dynamics") else [])
        period = ", ".join(f"{c['period_years']:.3g}" for c in cycles if c.get("period_years")) or "—"
        at = factor.get("at") or {}
        phase = ", ".join(p["label"] for p in at.get("phases", [])) or "—"
        projection = f"{at['mean']:.4g} [{at['lower']:.4g}, {at['upper']:.4g}] {factor['units']}" if at.get("mean") is not None and at.get("lower") is not None else at.get("relation", "—")
        upcoming = at.get("next_turning_points") or fit.get("upcoming_turning_points") or []
        turning = f"{upcoming[0]['label']} {upcoming[0]['date']}" if upcoming else "—"
        name = f"{factor['name']} ({factor['region']})".replace("|", "\\|")
        lines.append(f"| {name} | {fit.get('verdict', factor.get('fit_status'))} | {period} | {phase} | {projection} | {turning} |")
    for composite in context.get("composites", []):
        at = composite.get("at") or {}
        if at.get("value") is not None:
            lines.append(f"| Composite: {composite['name']} | — | — | alignment {at.get('alignment')} ({at.get('shared_phase') or '—'}) | {at['value']:.3g} z | — |")
    lines.append("")
    return lines
