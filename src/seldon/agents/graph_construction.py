"""Phase G relationship graph construction agents.

This phase turns persisted scenario nodes into auditable ERG edges. The first
implementation is deliberately bounded and deterministic: it generates a small
set of evidence-backed candidate pairs, writes only supported relationships,
checks graph consistency, computes node importance, and exposes a convergence
loop over Phases E–G.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from math import sqrt
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from seldon.data.models import ERGEdge, ERGNode, KBEntry, Scenario
from seldon.data.repositories import AuditRepository, GraphRepository, KBRepository

from .base import AgentBase
from .context_gathering import ContextGatheringCoordinator
from .extraction import ExtractionCoordinator

RelationshipType = Literal["causes", "correlates_with", "depends_on", "constrains", "enables", "opposes", "amplifies", "dampens"]
Direction = Literal["positive", "negative", "complex"]


class GraphConstructionInput(BaseModel):
    scenario_id: str
    question: str
    timeframe: str = ""
    max_candidate_pairs: int = Field(default=40, ge=1, le=500)
    min_evidence_overlap: int = Field(default=1, ge=0, le=20)
    min_confidence_to_write: float = Field(default=0.35, ge=0.0, le=1.0)


class NodePairCandidate(BaseModel):
    source_node_id: str
    target_node_id: str
    evidence_kb_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class RelationshipCandidate(BaseModel):
    source_node_id: str
    target_node_id: str
    relationship_type: RelationshipType
    description: str
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    lag: str | None = None
    direction: Direction = "complex"
    evidence_kb_ids: list[str] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)


class ConsistencyIssue(BaseModel):
    issue_type: Literal["circular_contradiction", "unsupported_high_confidence_edge", "stale_relationship", "duplicate_edge"]
    edge_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = "medium"
    message: str
    suggested_action: str = "review"


class ImportanceUpdate(BaseModel):
    node_id: str
    importance_score: float = Field(ge=0.0, le=1.0)
    components: dict[str, float] = Field(default_factory=dict)


class ConvergenceDecision(BaseModel):
    should_continue: bool
    reason: str
    iteration: int
    new_kb_entries: int = 0
    new_nodes: int = 0
    new_edges: int = 0
    marginal_new_info: float = 0.0


class GraphConstructionOutput(BaseModel):
    child_run_ids: list[str]
    candidate_pairs: list[NodePairCandidate]
    relationship_candidates: list[RelationshipCandidate]
    created_edge_ids: list[str]
    updated_edge_ids: list[str]
    consistency_issues: list[ConsistencyIssue]
    importance_updates: list[ImportanceUpdate]
    snapshot_id: str | None = None
    convergence: ConvergenceDecision | None = None


class ConvergenceLoopInput(BaseModel):
    scenario_id: str
    max_iterations: int = Field(default=3, ge=1, le=10)
    min_new_info_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    coverage_target: float = Field(default=0.65, ge=0.0, le=1.0)
    max_candidate_pairs: int = Field(default=40, ge=1, le=500)


class ConvergenceLoopOutput(BaseModel):
    child_run_ids: list[str]
    iterations: list[ConvergenceDecision]
    final_graph: GraphConstructionOutput | None = None


def _overlap(left: list[str] | None, right: list[str] | None) -> list[str]:
    return sorted(set(left or []) & set(right or []))


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _entry_text(entries: list[KBEntry]) -> str:
    return " ".join(entry.content.lower() for entry in entries)


RELATIONSHIP_DETECTOR_SYSTEM = """You are The Seldon Project's Pairwise Relationship Detector.
Given two ERG nodes and shared evidence, return one evidence-reasoned relationship candidate.
Explain the mechanism, lag, direction, strength, confidence, and evidence sufficiency.
Use only allowed relationship_type and direction values. Return only JSON matching the RelationshipCandidate schema."""


class PairwiseRelationshipDetector(AgentBase[NodePairCandidate, RelationshipCandidate]):
    agent_id = "pairwise_relationship_detector"
    phase = "graph_construction"
    model_profile = "balanced"

    def _run(self, payload: NodePairCandidate, *, run_id: str, parent_run_id: str | None) -> RelationshipCandidate:
        graph = GraphRepository(self.db)
        source = graph.get_node(payload.source_node_id)
        target = graph.get_node(payload.target_node_id)
        if source is None or target is None:
            raise KeyError("candidate pair references missing node")
        entries = [entry for entry in (self.db.get(KBEntry, id) for id in payload.evidence_kb_ids) if entry is not None]
        scenario_ids = sorted(set(source.scenario_ids or []) & set(target.scenario_ids or []))
        if self.llm_client is not None:
            try:
                result = self.llm_complete_json(
                    [
                        {
                            "role": "user",
                            "content": (
                                "Detect the best supported relationship for this node pair.\n"
                                f"Candidate: {payload.model_dump(mode='json')}\n"
                                f"Source node: {source.name} ({source.type}) - {source.description}\n"
                                f"Target node: {target.name} ({target.type}) - {target.description}\n"
                                f"Shared scenario_ids: {scenario_ids}\n"
                                "Evidence entries:\n"
                                + "\n".join(f"- {entry.id}: {entry.content[:1000]}" for entry in entries)
                            ),
                        }
                    ],
                    run_id=run_id,
                    system=RELATIONSHIP_DETECTOR_SYSTEM,
                    schema=RelationshipCandidate,
                    repair_retries=1,
                    min_confidence=0.4,
                    escalation_profiles=("reasoning",),
                )
                candidate = RelationshipCandidate.model_validate(result)
                return candidate.model_copy(
                    update={
                        "source_node_id": source.id,
                        "target_node_id": target.id,
                        "evidence_kb_ids": candidate.evidence_kb_ids or payload.evidence_kb_ids,
                        "scenario_ids": sorted({*candidate.scenario_ids, *scenario_ids}),
                    }
                )
            except Exception as exc:
                self.runs.add_message(run_id, "system", "PairwiseRelationshipDetector LLM path failed; using deterministic fallback.", payload={"error": str(exc)})

        text = _entry_text(entries)
        rel_type: RelationshipType = "correlates_with"
        direction: Direction = "complex"
        lag: str | None = None
        if any(word in text for word in ("cut", "lower", "fall", "fell", "drop", "decline", "easing")):
            rel_type = "dampens" if target.type in {"metric", "topic"} else "correlates_with"
            direction = "negative"
        if any(word in text for word in ("raise", "rise", "rose", "increase", "stronger", "amplify", "boost")):
            rel_type = "amplifies"
            direction = "positive"
        if any(word in text for word in ("cause", "drive", "lead", "trigger", "because")):
            rel_type = "causes"
        if any(word in text for word in ("depend", "requires", "hinges")):
            rel_type = "depends_on"
        if any(word in text for word in ("constraint", "limit", "cap", "restrict")):
            rel_type = "constrains"
        if any(word in text for word in ("oppose", "offset", "counter", "headwind")):
            rel_type = "opposes"
            direction = "negative"
        if any(word in text for word in ("week", "month", "quarter", "year")):
            lag = "evidence mentions temporal lag"
        evidence_count = len(payload.evidence_kb_ids)
        confidence = _clamp(0.35 + 0.15 * evidence_count + 0.25 * payload.score)
        strength = _clamp(0.4 + 0.2 * payload.score + 0.05 * evidence_count)
        description = (
            f"{source.name} and {target.name} are linked by {evidence_count} shared scenario evidence item(s). "
            f"Mechanism inferred from evidence: {payload.reason}."
        )
        return RelationshipCandidate(
            source_node_id=source.id,
            target_node_id=target.id,
            relationship_type=rel_type,
            description=description,
            strength=strength,
            confidence=confidence,
            lag=lag,
            direction=direction,
            evidence_kb_ids=payload.evidence_kb_ids,
            scenario_ids=scenario_ids,
        )


class GraphConsistencyChecker(AgentBase[dict[str, Any], BaseModel]):  # type: ignore[type-var]
    agent_id = "graph_consistency_checker"
    phase = "graph_construction"
    model_profile = "balanced"

    def run_checks(self, *, scenario_id: str, parent_run_id: str | None = None) -> tuple[str, list[ConsistencyIssue]]:
        return self.run({"scenario_id": scenario_id}, parent_run_id=parent_run_id)  # type: ignore[return-value]

    def run(self, payload: dict[str, Any], *, parent_run_id: str | None = None):  # type: ignore[override]
        from pydantic import TypeAdapter
        import time

        started = time.perf_counter()
        run = self.runs.create(agent_id=self.agent_id, phase=self.phase, status="running", input={**payload, "parent_run_id": parent_run_id})
        try:
            output = self._check(payload["scenario_id"])
            self.runs.update(run.id, status="completed", output={"issues": TypeAdapter(list[ConsistencyIssue]).dump_python(output, mode="json")}, elapsed_ms=int((time.perf_counter() - started) * 1000))
            return run.id, output
        except Exception as exc:
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
            raise

    def _run(self, payload, *, run_id: str, parent_run_id: str | None):  # pragma: no cover
        raise NotImplementedError

    def _check(self, scenario_id: str) -> list[ConsistencyIssue]:
        edges = [edge for edge in GraphRepository(self.db).list_edges() if scenario_id in (edge.scenario_ids or [])]
        issues: list[ConsistencyIssue] = []
        seen: dict[tuple[str, str, str], str] = {}
        by_pair: dict[tuple[str, str], list[ERGEdge]] = defaultdict(list)
        for edge in edges:
            key = (edge.source_node_id, edge.target_node_id, edge.relationship_type)
            if key in seen:
                issues.append(ConsistencyIssue(issue_type="duplicate_edge", edge_ids=[seen[key], edge.id], severity="medium", message="Duplicate relationship edge detected", suggested_action="merge duplicate edge evidence"))
            seen[key] = edge.id
            by_pair[(edge.source_node_id, edge.target_node_id)].append(edge)
            if edge.confidence >= 0.75 and not edge.evidence_kb_ids:
                issues.append(ConsistencyIssue(issue_type="unsupported_high_confidence_edge", edge_ids=[edge.id], severity="high", message="High-confidence edge has no KB evidence", suggested_action="lower confidence or attach evidence"))
            if edge.lag and "stale" in edge.lag.lower():
                issues.append(ConsistencyIssue(issue_type="stale_relationship", edge_ids=[edge.id], severity="medium", message="Relationship lag/staleness marker requires review", suggested_action="refresh evidence"))
        opposite = {"causes": "opposes", "amplifies": "dampens", "dampens": "amplifies", "enables": "constrains", "constrains": "enables"}
        for edge in edges:
            for reverse in by_pair.get((edge.target_node_id, edge.source_node_id), []):
                if opposite.get(edge.relationship_type) == reverse.relationship_type:
                    issues.append(ConsistencyIssue(issue_type="circular_contradiction", edge_ids=[edge.id, reverse.id], node_ids=[edge.source_node_id, edge.target_node_id], severity="high", message="Opposing relationship types exist in both directions", suggested_action="review causal direction and evidence"))
        return issues


class ImportanceScorer(AgentBase[dict[str, Any], BaseModel]):  # type: ignore[type-var]
    agent_id = "importance_scorer"
    phase = "graph_construction"
    model_profile = "fast"

    def run_scores(self, *, scenario_id: str, parent_run_id: str | None = None) -> tuple[str, list[ImportanceUpdate]]:
        return self.run({"scenario_id": scenario_id}, parent_run_id=parent_run_id)  # type: ignore[return-value]

    def run(self, payload: dict[str, Any], *, parent_run_id: str | None = None):  # type: ignore[override]
        from pydantic import TypeAdapter
        import time

        started = time.perf_counter()
        run = self.runs.create(agent_id=self.agent_id, phase=self.phase, status="running", input={**payload, "parent_run_id": parent_run_id})
        try:
            output = self._score(payload["scenario_id"])
            self.runs.update(run.id, status="completed", output={"importance_updates": TypeAdapter(list[ImportanceUpdate]).dump_python(output, mode="json")}, elapsed_ms=int((time.perf_counter() - started) * 1000))
            return run.id, output
        except Exception as exc:
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
            raise

    def _run(self, payload, *, run_id: str, parent_run_id: str | None):  # pragma: no cover
        raise NotImplementedError

    def _score(self, scenario_id: str) -> list[ImportanceUpdate]:
        graph = GraphRepository(self.db)
        nodes = [node for node in graph.list_nodes() if scenario_id in (node.scenario_ids or [])]
        edges = [edge for edge in graph.list_edges() if scenario_id in (edge.scenario_ids or [])]
        if not nodes:
            return []
        degree: dict[str, float] = {node.id: 0.0 for node in nodes}
        edge_conf: dict[str, float] = {node.id: 0.0 for node in nodes}
        for edge in edges:
            weight = max(0.1, (edge.strength + edge.confidence) / 2)
            if edge.source_node_id in degree:
                degree[edge.source_node_id] += weight
                edge_conf[edge.source_node_id] += edge.confidence
            if edge.target_node_id in degree:
                degree[edge.target_node_id] += weight
                edge_conf[edge.target_node_id] += edge.confidence
        max_degree = max(degree.values()) or 1.0
        max_evidence = max((len(node.kb_entry_ids or []) for node in nodes), default=1) or 1
        max_usage = max((len(node.scenario_ids or []) for node in nodes), default=1) or 1
        updates: list[ImportanceUpdate] = []
        for node in nodes:
            degree_score = degree[node.id] / max_degree
            evidence_score = len(node.kb_entry_ids or []) / max_evidence
            usage_score = len(node.scenario_ids or []) / max_usage
            confidence_score = min(1.0, edge_conf[node.id] / max(1, degree[node.id])) if degree[node.id] else 0.0
            score = _clamp(0.45 * degree_score + 0.25 * evidence_score + 0.20 * usage_score + 0.10 * confidence_score)
            graph.update_node(node.id, importance_score=score)
            updates.append(ImportanceUpdate(node_id=node.id, importance_score=score, components={"degree": degree_score, "evidence": evidence_score, "scenario_usage": usage_score, "edge_confidence": confidence_score}))
        return updates


class GraphConstructionCoordinator(AgentBase[GraphConstructionInput, GraphConstructionOutput]):
    agent_id = "graph_construction_coordinator"
    phase = "graph_construction"
    model_profile = "balanced"

    @classmethod
    def input_from_scenario(cls, scenario: Scenario, *, max_candidate_pairs: int = 40, min_confidence_to_write: float = 0.35) -> GraphConstructionInput:
        return GraphConstructionInput(scenario_id=scenario.id, question=scenario.target_question, timeframe=scenario.time_horizon, max_candidate_pairs=max_candidate_pairs, min_confidence_to_write=min_confidence_to_write)

    def _run(self, payload: GraphConstructionInput, *, run_id: str, parent_run_id: str | None) -> GraphConstructionOutput:
        child_run_ids: list[str] = []
        pairs = self._candidate_pairs(payload)
        candidates: list[RelationshipCandidate] = []
        for pair in pairs:
            d_run, relationship = PairwiseRelationshipDetector(self.db, config=self.config, llm_client=self.llm_client).run(pair, parent_run_id=run_id)
            child_run_ids.append(d_run)
            candidates.append(relationship)

        graph = GraphRepository(self.db)
        created: list[str] = []
        updated: list[str] = []
        for candidate in candidates:
            if candidate.confidence < payload.min_confidence_to_write:
                continue
            existing = self._find_existing_edge(candidate)
            values = candidate.model_dump(mode="json")
            if existing:
                evidence = sorted({*(existing.evidence_kb_ids or []), *candidate.evidence_kb_ids})
                scenario_ids = sorted({*(existing.scenario_ids or []), *candidate.scenario_ids, payload.scenario_id})
                edge = graph.update_edge(existing.id, description=candidate.description, strength=max(existing.strength, candidate.strength), confidence=max(existing.confidence, candidate.confidence), lag=candidate.lag or existing.lag, direction=candidate.direction, evidence_kb_ids=evidence, scenario_ids=scenario_ids)
                updated.append(edge.id)
            else:
                values["scenario_ids"] = sorted({*candidate.scenario_ids, payload.scenario_id})
                edge = graph.create_edge(**values)
                created.append(edge.id)

        c_run, issues = GraphConsistencyChecker(self.db, config=self.config, llm_client=self.llm_client).run_checks(scenario_id=payload.scenario_id, parent_run_id=run_id)
        child_run_ids.append(c_run)
        i_run, importance = ImportanceScorer(self.db, config=self.config, llm_client=self.llm_client).run_scores(scenario_id=payload.scenario_id, parent_run_id=run_id)
        child_run_ids.append(i_run)
        snapshot = graph.create_snapshot(scenario_id=payload.scenario_id, reason="Phase G graph construction snapshot", agent_id=self.agent_id)
        scenario = self.db.get(Scenario, payload.scenario_id)
        if scenario is not None:
            scenario.erg_snapshot_id = snapshot.id
        AuditRepository(self.db).emit("scenario", payload.scenario_id, "graph_construction_write", actor=self.agent_id, reason="Phase G wrote ERG edges and importance scores", after={"created_edge_ids": created, "updated_edge_ids": updated, "snapshot_id": snapshot.id})
        convergence = ConvergenceDecision(should_continue=False, reason="single graph construction run completed", iteration=1, new_edges=len(created), marginal_new_info=len(created) / max(1, len(candidates)))
        return GraphConstructionOutput(child_run_ids=child_run_ids, candidate_pairs=pairs, relationship_candidates=candidates, created_edge_ids=created, updated_edge_ids=updated, consistency_issues=issues, importance_updates=importance, snapshot_id=snapshot.id, convergence=convergence)

    def _candidate_pairs(self, payload: GraphConstructionInput) -> list[NodePairCandidate]:
        nodes = [node for node in GraphRepository(self.db).list_nodes() if payload.scenario_id in (node.scenario_ids or [])]
        entries_by_id = {entry.id: entry for entry in KBRepository(self.db).search(scenario_id=payload.scenario_id)}
        candidates: list[NodePairCandidate] = []
        for left, right in combinations(nodes, 2):
            evidence = _overlap(left.kb_entry_ids, right.kb_entry_ids)
            if len(evidence) < payload.min_evidence_overlap:
                evidence = self._cooccurring_evidence(left, right, entries_by_id)
            if len(evidence) < payload.min_evidence_overlap:
                continue
            evidence_score = min(1.0, len(evidence) / max(1, sqrt(max(1, len(left.kb_entry_ids or [])) * max(1, len(right.kb_entry_ids or [])))))
            type_bonus = 0.15 if {left.type, right.type} & {"metric", "policy", "event"} else 0.0
            candidates.append(NodePairCandidate(source_node_id=left.id, target_node_id=right.id, evidence_kb_ids=evidence, reason=f"shared/co-occurring evidence for {left.name} and {right.name}", score=_clamp(evidence_score + type_bonus)))
        candidates.sort(key=lambda c: (c.score, len(c.evidence_kb_ids)), reverse=True)
        return candidates[: payload.max_candidate_pairs]

    def _cooccurring_evidence(self, left: ERGNode, right: ERGNode, entries_by_id: dict[str, KBEntry]) -> list[str]:
        names = (_norm(left.name), _norm(right.name))
        ids = set(left.kb_entry_ids or []) | set(right.kb_entry_ids or [])
        matches: list[str] = []
        for id, entry in entries_by_id.items():
            haystack = _norm(" ".join([entry.content, *entry.topics, *entry.entities]))
            if (id in ids and (names[0] in haystack or names[1] in haystack)) or (names[0] in haystack and names[1] in haystack):
                matches.append(id)
        return sorted(matches)

    def _find_existing_edge(self, candidate: RelationshipCandidate) -> ERGEdge | None:
        return self.db.scalar(
            select(ERGEdge).where(
                ERGEdge.source_node_id == candidate.source_node_id,
                ERGEdge.target_node_id == candidate.target_node_id,
                ERGEdge.relationship_type == candidate.relationship_type,
            )
        )


class ConvergenceLoopCoordinator(AgentBase[ConvergenceLoopInput, ConvergenceLoopOutput]):
    agent_id = "convergence_loop_coordinator"
    phase = "convergence"
    model_profile = "balanced"

    def _run(self, payload: ConvergenceLoopInput, *, run_id: str, parent_run_id: str | None) -> ConvergenceLoopOutput:
        scenario = self.db.get(Scenario, payload.scenario_id)
        if scenario is None:
            raise KeyError(f"scenario not found: {payload.scenario_id}")
        child_run_ids: list[str] = []
        decisions: list[ConvergenceDecision] = []
        final_graph: GraphConstructionOutput | None = None
        previous_total = 0
        for iteration in range(1, payload.max_iterations + 1):
            c_run, context = ContextGatheringCoordinator(self.db, config=self.config, llm_client=self.llm_client).run(ContextGatheringCoordinator.input_from_scenario(scenario), parent_run_id=run_id)
            child_run_ids.append(c_run)
            e_run, extraction = ExtractionCoordinator(self.db, config=self.config, llm_client=self.llm_client).run(ExtractionCoordinator.input_from_scenario(scenario), parent_run_id=run_id)
            child_run_ids.append(e_run)
            g_run, graph_output = GraphConstructionCoordinator(self.db, config=self.config, llm_client=self.llm_client).run(GraphConstructionCoordinator.input_from_scenario(scenario, max_candidate_pairs=payload.max_candidate_pairs), parent_run_id=run_id)
            child_run_ids.append(g_run)
            final_graph = graph_output
            new_info = len(context.kb_entry_ids) + len(extraction.created_node_ids) + len(graph_output.created_edge_ids)
            marginal = new_info / max(1, previous_total + new_info)
            should_continue = iteration < payload.max_iterations and marginal >= payload.min_new_info_threshold
            reason = "marginal new info above threshold" if should_continue else "max iterations reached or marginal new info below threshold"
            decision = ConvergenceDecision(should_continue=should_continue, reason=reason, iteration=iteration, new_kb_entries=len(context.kb_entry_ids), new_nodes=len(extraction.created_node_ids), new_edges=len(graph_output.created_edge_ids), marginal_new_info=marginal)
            decisions.append(decision)
            previous_total += new_info
            if not should_continue:
                break
        return ConvergenceLoopOutput(child_run_ids=child_run_ids, iterations=decisions, final_graph=final_graph)
