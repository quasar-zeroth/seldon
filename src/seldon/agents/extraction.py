"""Phase F extraction coordinator and specialist agents.

The Phase F workflow converts scenario-linked KB evidence into persisted ERG
nodes. It is deliberately conservative: specialists propose schema-valid nodes,
the deduplicator emits merge proposals, and only non-destructive writes happen.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from seldon.data.models import KBEntry, Scenario
from seldon.data.repositories import AuditRepository, GraphRepository, KBRepository

from .base import AgentBase, compact_terms

NodeType = Literal["entity", "event", "topic", "metric", "policy", "actor"]


class ExtractionInput(BaseModel):
    scenario_id: str
    question: str
    timeframe: str = ""
    max_kb_entries: int = Field(default=50, ge=1, le=500)
    max_nodes: int = Field(default=50, ge=1, le=200)


class NodeCandidate(BaseModel):
    name: str
    type: NodeType
    description: str = ""
    current_state: str | None = None
    kb_entry_ids: list[str] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    aliases: list[str] = Field(default_factory=list)


class MergeProposal(BaseModel):
    canonical_name: str
    type: NodeType
    existing_node_id: str | None = None
    candidate_names: list[str] = Field(default_factory=list)
    alias_node_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ExtractionOutput(BaseModel):
    child_run_ids: list[str]
    entity_candidates: list[NodeCandidate]
    event_candidates: list[NodeCandidate]
    topic_candidates: list[NodeCandidate]
    merge_proposals: list[MergeProposal]
    created_node_ids: list[str]
    updated_node_ids: list[str]


def _canonical(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.replace("_", " ").replace("-", " ").split())
    return cleaned[:80]


def _sentence(text: str) -> str:
    return " ".join(text.strip().split())[:300]


def _classify_term(term: str) -> NodeType:
    lower = term.lower()
    if any(word in lower for word in ("rate", "price", "inflation", "demand", "supply", "flow", "yield", "gdp", "revenue", "cost")):
        return "metric"
    if any(word in lower for word in ("policy", "regulation", "tariff", "sanction", "fed", "central bank")):
        return "policy"
    if any(word in lower for word in ("bank", "company", "government", "fed", "china", "india", "opec")):
        return "actor"
    return "entity"


class EntityExtractor(AgentBase[dict, BaseModel]):  # type: ignore[type-var]
    """Schema-validated replacement for the legacy graph EntityExtractor."""

    agent_id = "entity_extractor"
    phase = "extraction"
    model_profile = "fast"

    def run_entries(self, entries: list[KBEntry], *, scenario_id: str, parent_run_id: str | None = None) -> tuple[str, list[NodeCandidate]]:
        return self.run({"scenario_id": scenario_id, "entries": entries}, parent_run_id=parent_run_id)  # type: ignore[return-value]

    def run(self, payload: dict, *, parent_run_id: str | None = None):  # type: ignore[override]
        from pydantic import TypeAdapter
        import time

        started = time.perf_counter()
        entries = payload["entries"]
        json_payload = {"scenario_id": payload["scenario_id"], "entry_ids": [entry.id for entry in entries], "parent_run_id": parent_run_id}
        run = self.runs.create(agent_id=self.agent_id, phase=self.phase, status="running", input=json_payload)
        try:
            output = self._extract(payload["scenario_id"], entries)
            data = TypeAdapter(list[NodeCandidate]).dump_python(output, mode="json")
            self.runs.update(run.id, status="completed", output={"candidates": data}, elapsed_ms=int((time.perf_counter() - started) * 1000))
            return run.id, output
        except Exception as exc:
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
            raise

    def _run(self, payload, *, run_id: str, parent_run_id: str | None):  # pragma: no cover
        raise NotImplementedError

    def _extract(self, scenario_id: str, entries: list[KBEntry]) -> list[NodeCandidate]:
        candidates: dict[tuple[str, NodeType], NodeCandidate] = {}
        for entry in entries:
            names = [*entry.entities]
            for term in compact_terms(" ".join([entry.content, *entry.topics]), limit=8):
                names.append(_clean_name(term))
            for name in names:
                if not name:
                    continue
                ntype = _classify_term(name)
                key = (_canonical(name), ntype)
                existing = candidates.get(key)
                if existing:
                    existing.kb_entry_ids = sorted({*existing.kb_entry_ids, entry.id})
                    continue
                candidates[key] = NodeCandidate(
                    name=_clean_name(name),
                    type=ntype,
                    description=f"Extracted from KB evidence: {_sentence(entry.content)}",
                    current_state=_sentence(entry.content),
                    kb_entry_ids=[entry.id],
                    scenario_ids=[scenario_id],
                    confidence=float((entry.perspective_tags or {}).get("confidence", 0.6)),
                )
        return list(candidates.values())


class EventExtractor(AgentBase[dict, BaseModel]):  # type: ignore[type-var]
    agent_id = "event_extractor"
    phase = "extraction"
    model_profile = "fast"

    EVENT_HINTS = ("announced", "reported", "launched", "raised", "cut", "fell", "rose", "election", "meeting", "war", "shock", "crisis", "default")

    def run_entries(self, entries: list[KBEntry], *, scenario_id: str, parent_run_id: str | None = None) -> tuple[str, list[NodeCandidate]]:
        return self.run({"scenario_id": scenario_id, "entries": entries}, parent_run_id=parent_run_id)  # type: ignore[return-value]

    def run(self, payload: dict, *, parent_run_id: str | None = None):  # type: ignore[override]
        from pydantic import TypeAdapter
        import time

        started = time.perf_counter()
        run = self.runs.create(agent_id=self.agent_id, phase=self.phase, status="running", input={"scenario_id": payload["scenario_id"], "entry_ids": [e.id for e in payload["entries"]], "parent_run_id": parent_run_id})
        try:
            output = self._extract(payload["scenario_id"], payload["entries"])
            self.runs.update(run.id, status="completed", output={"candidates": TypeAdapter(list[NodeCandidate]).dump_python(output, mode="json")}, elapsed_ms=int((time.perf_counter() - started) * 1000))
            return run.id, output
        except Exception as exc:
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
            raise

    def _run(self, payload, *, run_id: str, parent_run_id: str | None):  # pragma: no cover
        raise NotImplementedError

    def _extract(self, scenario_id: str, entries: list[KBEntry]) -> list[NodeCandidate]:
        candidates: list[NodeCandidate] = []
        for entry in entries:
            content = _sentence(entry.content)
            if any(hint in entry.content.lower() for hint in self.EVENT_HINTS):
                candidates.append(NodeCandidate(name=content[:70], type="event", description=f"Event-like observation from {entry.source_name}: {content}", current_state=content, kb_entry_ids=[entry.id], scenario_ids=[scenario_id], confidence=float((entry.perspective_tags or {}).get("confidence", 0.55))))
        return candidates


class TopicThemeExtractor(AgentBase[dict, BaseModel]):  # type: ignore[type-var]
    agent_id = "topic_theme_extractor"
    phase = "extraction"
    model_profile = "fast"

    def run_entries(self, entries: list[KBEntry], *, scenario_id: str, question: str, parent_run_id: str | None = None) -> tuple[str, list[NodeCandidate]]:
        return self.run({"scenario_id": scenario_id, "question": question, "entries": entries}, parent_run_id=parent_run_id)  # type: ignore[return-value]

    def run(self, payload: dict, *, parent_run_id: str | None = None):  # type: ignore[override]
        from pydantic import TypeAdapter
        import time

        started = time.perf_counter()
        run = self.runs.create(agent_id=self.agent_id, phase=self.phase, status="running", input={"scenario_id": payload["scenario_id"], "entry_ids": [e.id for e in payload["entries"]], "parent_run_id": parent_run_id})
        try:
            output = self._extract(payload["scenario_id"], payload["question"], payload["entries"])
            self.runs.update(run.id, status="completed", output={"candidates": TypeAdapter(list[NodeCandidate]).dump_python(output, mode="json")}, elapsed_ms=int((time.perf_counter() - started) * 1000))
            return run.id, output
        except Exception as exc:
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
            raise

    def _run(self, payload, *, run_id: str, parent_run_id: str | None):  # pragma: no cover
        raise NotImplementedError

    def _extract(self, scenario_id: str, question: str, entries: list[KBEntry]) -> list[NodeCandidate]:
        topics: dict[str, list[str]] = {}
        for entry in entries:
            for topic in [*entry.topics, *compact_terms(question, limit=5)]:
                if topic:
                    topics.setdefault(_clean_name(topic), []).append(entry.id)
        return [NodeCandidate(name=name, type="topic", description=f"Scenario theme/topic: {name}", kb_entry_ids=sorted(set(ids)), scenario_ids=[scenario_id], confidence=0.65) for name, ids in topics.items()]


class NodeDeduplicatorMerger(AgentBase[dict, BaseModel]):  # type: ignore[type-var]
    agent_id = "node_deduplicator_merger"
    phase = "extraction"
    model_profile = "fast"

    def run_candidates(self, candidates: list[NodeCandidate], *, parent_run_id: str | None = None) -> tuple[str, list[MergeProposal]]:
        return self.run({"candidates": candidates}, parent_run_id=parent_run_id)  # type: ignore[return-value]

    def run(self, payload: dict, *, parent_run_id: str | None = None):  # type: ignore[override]
        from pydantic import TypeAdapter
        import time

        started = time.perf_counter()
        candidates = payload["candidates"]
        run = self.runs.create(agent_id=self.agent_id, phase=self.phase, status="running", input={"candidates": [c.model_dump(mode="json") for c in candidates], "parent_run_id": parent_run_id})
        try:
            output = self._propose(candidates)
            self.runs.update(run.id, status="completed", output={"merge_proposals": TypeAdapter(list[MergeProposal]).dump_python(output, mode="json")}, elapsed_ms=int((time.perf_counter() - started) * 1000))
            return run.id, output
        except Exception as exc:
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
            raise

    def _run(self, payload, *, run_id: str, parent_run_id: str | None):  # pragma: no cover
        raise NotImplementedError

    def _propose(self, candidates: list[NodeCandidate]) -> list[MergeProposal]:
        graph = GraphRepository(self.db)
        existing = graph.list_nodes()
        proposals: list[MergeProposal] = []
        grouped: dict[tuple[str, NodeType], list[NodeCandidate]] = {}
        for candidate in candidates:
            grouped.setdefault((_canonical(candidate.name), candidate.type), []).append(candidate)
        for (canon, ntype), group in grouped.items():
            match = next((node for node in existing if _canonical(node.name) == canon and node.type == ntype), None)
            if match or len(group) > 1:
                proposals.append(MergeProposal(canonical_name=group[0].name, type=ntype, existing_node_id=match.id if match else None, candidate_names=[c.name for c in group], alias_node_ids=[match.id] if match else [], reason="Exact canonical name/type match; safe merge candidate, not auto-destructive", confidence=0.9 if match else 0.75))
        return proposals


class ExtractionCoordinator(AgentBase[ExtractionInput, ExtractionOutput]):
    agent_id = "extraction_coordinator"
    phase = "extraction"
    model_profile = "balanced"

    @classmethod
    def input_from_scenario(cls, scenario: Scenario, *, max_kb_entries: int = 50, max_nodes: int = 50) -> ExtractionInput:
        return ExtractionInput(scenario_id=scenario.id, question=scenario.target_question, timeframe=scenario.time_horizon, max_kb_entries=max_kb_entries, max_nodes=max_nodes)

    def _run(self, payload: ExtractionInput, *, run_id: str, parent_run_id: str | None) -> ExtractionOutput:
        kb_entries = KBRepository(self.db).search(scenario_id=payload.scenario_id)[: payload.max_kb_entries]
        child_run_ids: list[str] = []

        e_run, entities = EntityExtractor(self.db, config=self.config, llm_client=self.llm_client).run_entries(kb_entries, scenario_id=payload.scenario_id, parent_run_id=run_id)
        child_run_ids.append(e_run)
        ev_run, events = EventExtractor(self.db, config=self.config, llm_client=self.llm_client).run_entries(kb_entries, scenario_id=payload.scenario_id, parent_run_id=run_id)
        child_run_ids.append(ev_run)
        t_run, topics = TopicThemeExtractor(self.db, config=self.config, llm_client=self.llm_client).run_entries(kb_entries, scenario_id=payload.scenario_id, question=payload.question, parent_run_id=run_id)
        child_run_ids.append(t_run)

        all_candidates = (entities + events + topics)[: payload.max_nodes]
        m_run, proposals = NodeDeduplicatorMerger(self.db, config=self.config, llm_client=self.llm_client).run_candidates(all_candidates, parent_run_id=run_id)
        child_run_ids.append(m_run)

        graph = GraphRepository(self.db)
        created: list[str] = []
        updated: list[str] = []
        by_key = {(_canonical(node.name), node.type): node for node in graph.list_nodes()}
        now = datetime.now(timezone.utc)
        for candidate in all_candidates:
            key = (_canonical(candidate.name), candidate.type)
            existing = by_key.get(key)
            if existing:
                kb_ids = sorted({*(existing.kb_entry_ids or []), *candidate.kb_entry_ids})
                scenario_ids = sorted({*(existing.scenario_ids or []), *candidate.scenario_ids})
                node = graph.update_node(existing.id, kb_entry_ids=kb_ids, scenario_ids=scenario_ids, current_state=candidate.current_state or existing.current_state, state_updated_at=now)
                updated.append(node.id)
                continue
            node = graph.create_node(name=candidate.name, type=candidate.type, description=candidate.description, current_state=candidate.current_state, state_updated_at=now, kb_entry_ids=candidate.kb_entry_ids, scenario_ids=candidate.scenario_ids, stability_score=0.5, importance_score=0.0)
            by_key[key] = node
            created.append(node.id)

        AuditRepository(self.db).emit("scenario", payload.scenario_id, "extraction_graph_write", actor=self.agent_id, reason="Phase F extraction wrote ERG nodes", after={"created_node_ids": created, "updated_node_ids": updated, "merge_proposals": [p.model_dump(mode="json") for p in proposals]})
        return ExtractionOutput(child_run_ids=child_run_ids, entity_candidates=entities, event_candidates=events, topic_candidates=topics, merge_proposals=proposals, created_node_ids=created, updated_node_ids=updated)
