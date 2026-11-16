"""Phase F extraction coordinator and specialist agents.

The Phase F workflow converts scenario-linked KB evidence into persisted ERG
nodes. It is deliberately conservative: specialists propose schema-valid nodes,
the deduplicator emits merge proposals, and only non-destructive writes happen.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from seldon.data.models import KBEntry, Scenario
from seldon.data.repositories import AuditRepository, GraphRepository, KBRepository
from seldon.kb.vector import cosine_similarity, embed_text
from seldon.llm.openrouter import LLMAuthenticationError

from .base import AgentBase, compact_terms

# Cosine threshold (on local name embeddings) above which two same-type nodes are
# treated as the same entity. Deliberately high: false merges corrupt the graph
# worse than a few duplicates, and the alias + LLM-resolver paths catch the
# semantic cases (abbreviations, synonyms) that short-name embeddings miss.
_EMBED_MERGE_THRESHOLD = 0.86

NodeType = Literal["entity", "event", "topic", "metric", "policy", "actor"]


class ExtractionInput(BaseModel):
    scenario_id: str
    question: str
    timeframe: str = ""
    max_kb_entries: int = Field(default=50, ge=1, le=500)
    max_nodes: int = Field(default=50, ge=1, le=200)


class NodeCandidate(BaseModel):
    tags: list[str] = Field(default_factory=list)
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


def _name_keys(name: str, aliases: list[str] | None = None) -> set[str]:
    """Canonical lookup keys for a node/candidate: its name plus any aliases.

    Lets "Fed" resolve to "Federal Reserve" when the extractor lists it as an
    alias, without requiring an aliases column on the persisted node.
    """
    keys = {_canonical(name)}
    for alias in aliases or []:
        keys.add(_canonical(alias))
    keys.discard("")
    return keys


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.replace("_", " ").replace("-", " ").split())
    return cleaned[:80]


def _sentence(text: str) -> str:
    return " ".join(text.strip().split())[:300]


# Single-word generic stopwords/structural words that frequently leak in when
# extraction falls back to keyword heuristics. These should never be graph nodes.
_NODE_NAME_BLOCKLIST: set[str] = {
    "question", "scope", "temporal", "outcome", "outcomes", "likely", "want",
    "know", "would", "look", "like", "scenario", "answer", "topic", "context",
    "evidence", "factor", "factors", "driver", "drivers", "data", "information",
    "general", "various", "multiple", "things", "stuff", "thing",
}


def validate_node_candidate(
    candidate: "NodeCandidate",
    *,
    scenario_question: str | None = None,
    is_subject: bool = False,
) -> bool:
    """Return True if the candidate is plausibly a real graph node.

    Rejects:
      - empty/whitespace names
      - single-word generic stopwords (the most common source of garbage)
      - names that are just the scenario question itself
      - candidates with no supporting KB entries
      - candidates with confidence < 0.4 unless explicitly the scenario subject
    """
    name = (candidate.name or "").strip()
    if not name:
        return False
    canonical = _canonical(name)
    if not canonical:
        return False
    tokens = canonical.split()
    if len(tokens) == 1 and tokens[0] in _NODE_NAME_BLOCKLIST:
        return False
    if scenario_question:
        q_canonical = _canonical(scenario_question)
        if canonical == q_canonical:
            return False
        # Reject candidates that are >70% the scenario question by token overlap.
        if q_canonical and len(canonical) > 0 and canonical in q_canonical and len(canonical.split()) >= 4:
            return False
    if not candidate.kb_entry_ids:
        return False
    if not is_subject and candidate.confidence < 0.4:
        return False
    return True


def _classify_term(term: str) -> NodeType:
    lower = term.lower()
    if any(word in lower for word in ("rate", "price", "inflation", "demand", "supply", "flow", "yield", "gdp", "revenue", "cost")):
        return "metric"
    if any(word in lower for word in ("policy", "regulation", "tariff", "sanction", "fed", "central bank")):
        return "policy"
    if any(word in lower for word in ("bank", "company", "government", "fed", "china", "india", "opec")):
        return "actor"
    return "entity"


ENTITY_EXTRACTOR_SYSTEM = """You are The Seldon Project's Entity Extractor.

Given a batch of KB evidence entries about a forecasting scenario, identify the
real-world entities, metrics, policies, and actors that appear in the evidence
and should become graph nodes.

Rules:
- Only emit nodes for concepts that are explicitly grounded in the supplied
  evidence. Do not invent.
- Use specific, named entities (e.g. "Central bank gold purchases",
  "US 10-year real yield", "OPEC+ production cuts") — not generic words
  (avoid: "factors", "data", "things", "question", "scope").
- Each candidate must list the kb_entry_ids that mention it.
- Set node type from {entity, event, topic, metric, policy, actor}.
- Pick confidence in [0.0, 1.0]; prefer 0.6-0.85 for solid evidence,
  0.4-0.6 for weak evidence. Anything below 0.4 will be dropped.
- aliases: list 0-3 alternative names the same node appears under.
- tags: assign evidence-grounded category labels on every creation/update (e.g. data-center, utility, semiconductor, country:us). A physical campus is data-center; a funding programme or general AI theme is not. Do not infer location or owners without evidence.

Return STRICT JSON: {"candidates": [NodeCandidate, ...]}. Aim for 8-20 candidates."""


class _ExtractionResponse(BaseModel):
    candidates: list[NodeCandidate] = Field(default_factory=list)


class EntityExtractor(AgentBase[dict, BaseModel]):  # type: ignore[type-var]
    """LLM-first entity extractor.

    Asks the model to read a batch of KB entries and produce typed NodeCandidates
    grounded in the evidence. A deterministic heuristic survives only as a
    development-mode fallback when ``agents.allow_deterministic_dev_fallback`` is
    set. Previously the heuristic ran by default and produced stopword nodes
    like "question" and "temporal" when the KB was sparse.
    """

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
        scenario_id = payload["scenario_id"]
        json_payload = {"scenario_id": scenario_id, "entry_ids": [entry.id for entry in entries], "parent_run_id": parent_run_id}
        run = self.runs.create(agent_id=self.agent_id, phase=self.phase, status="running", input=json_payload)
        try:
            scenario = self.db.get(Scenario, scenario_id)
            question = scenario.target_question if scenario is not None else ""
            output = self._extract(run.id, scenario_id, entries, scenario_question=question)
            data = TypeAdapter(list[NodeCandidate]).dump_python(output, mode="json")
            self.runs.update(run.id, status="completed", output={"candidates": data}, elapsed_ms=int((time.perf_counter() - started) * 1000))
            return run.id, output
        except Exception as exc:
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
            raise

    def _run(self, payload, *, run_id: str, parent_run_id: str | None):  # pragma: no cover
        raise NotImplementedError

    def _extract(self, run_id: str, scenario_id: str, entries: list[KBEntry], *, scenario_question: str = "") -> list[NodeCandidate]:
        # LLM-first path
        if self.llm_client is not None and entries:
            try:
                evidence_block = "\n".join(
                    f"- id={entry.id} | source={entry.source_name} | topics={entry.topics or []} | content={(entry.content or '')[:800]}"
                    for entry in entries[:40]
                )
                result = self.llm_complete_json(
                    [
                        {
                            "role": "user",
                            "content": (
                                f"Scenario: {scenario_question}\n"
                                f"scenario_id: {scenario_id}\n"
                                "Extract grounded entity/metric/policy/actor nodes from this evidence.\n"
                                "Use the exact kb_entry_ids shown when citing support.\n\n"
                                f"Evidence:\n{evidence_block}"
                            ),
                        }
                    ],
                    run_id=run_id,
                    system=ENTITY_EXTRACTOR_SYSTEM,
                    schema=_ExtractionResponse,
                    repair_retries=1,
                    escalation_profiles=("balanced",),
                )
                response = _ExtractionResponse.model_validate(result)
                gated: list[NodeCandidate] = []
                valid_ids = {entry.id for entry in entries}
                for candidate in response.candidates:
                    candidate = candidate.model_copy(
                        update={
                            "name": _clean_name(candidate.name),
                            "scenario_ids": sorted({*candidate.scenario_ids, scenario_id}),
                            "kb_entry_ids": [kb_id for kb_id in candidate.kb_entry_ids if kb_id in valid_ids],
                        }
                    )
                    if validate_node_candidate(candidate, scenario_question=scenario_question):
                        gated.append(candidate)
                if gated:
                    return _deduplicate_candidates(gated)
                # If everything failed the gate, log and fall through to heuristic
                # (if dev-fallback is enabled) — but typically this means the LLM
                # output was junk and we should surface it as an error.
                self.runs.add_message(run_id, "system", "EntityExtractor LLM returned no candidates passing quality gate.", payload={"raw_count": len(response.candidates)})
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                if not self.config.agents.allow_deterministic_dev_fallback:
                    raise
                self.runs.add_message(run_id, "system", "EntityExtractor LLM path failed; using deterministic fallback.", payload={"error": str(exc)})

        # No LLM client configured (test/CI mode) or dev-fallback explicitly enabled:
        # use the heuristic path. We only return [] when an LLM was attempted and
        # the configured strict mode said to surface the error (above branch raised).
        return self._heuristic_extract(scenario_id, entries, scenario_question=scenario_question)

    def _heuristic_extract(self, scenario_id: str, entries: list[KBEntry], *, scenario_question: str = "") -> list[NodeCandidate]:
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
        return [c for c in candidates.values() if validate_node_candidate(c, scenario_question=scenario_question)]


def kb_entries_supporting(name: str, aliases: list[str], entries: list[KBEntry]) -> list[str]:
    """Return IDs of KB entries whose entities/topics/content reference this node.

    Used to enrich the LLM-chosen kb_entry_ids so we don't miss obvious mentions.
    """
    needles = {_canonical(n) for n in [name, *aliases] if n}
    if not needles:
        return []
    matched: list[str] = []
    for entry in entries:
        haystack = " ".join([_canonical(t) for t in [*(entry.entities or []), *(entry.topics or [])]])
        content = _canonical(entry.content or "")
        if any(needle and (needle in haystack or needle in content) for needle in needles):
            matched.append(entry.id)
    return matched


def _deduplicate_candidates(candidates: list[NodeCandidate]) -> list[NodeCandidate]:
    """Merge candidates that share canonical name + type, unioning kb_entry_ids."""
    merged: dict[tuple[str, NodeType], NodeCandidate] = {}
    for candidate in candidates:
        key = (_canonical(candidate.name), candidate.type)
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue
        merged[key] = existing.model_copy(
            update={
                "kb_entry_ids": sorted({*existing.kb_entry_ids, *candidate.kb_entry_ids}),
                "aliases": sorted({*existing.aliases, *candidate.aliases, candidate.name}),
                "tags": sorted({*existing.tags, *candidate.tags}),
                "confidence": max(existing.confidence, candidate.confidence),
            }
        )
    return list(merged.values())


EVENT_EXTRACTOR_SYSTEM = """You are The Seldon Project's Event Extractor.

From the supplied KB evidence, identify *events* — discrete, time-bound
occurrences that have happened or are scheduled. Examples: "Fed rate cut in
March 2025", "US-China tariff hike announcement", "OPEC+ production cut decision".

Each event must:
- Be grounded in the supplied evidence (list the kb_entry_ids that mention it).
- Have a specific name (avoid generic words like "event", "announcement").
- Have type="event".

Return STRICT JSON: {"candidates": [NodeCandidate, ...]}. Aim for 3-10 events
(fewer is fine if the evidence is sparse on event-like content)."""


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
        scenario_id = payload["scenario_id"]
        run = self.runs.create(agent_id=self.agent_id, phase=self.phase, status="running", input={"scenario_id": scenario_id, "entry_ids": [e.id for e in payload["entries"]], "parent_run_id": parent_run_id})
        try:
            scenario = self.db.get(Scenario, scenario_id)
            question = scenario.target_question if scenario is not None else ""
            output = self._extract(run.id, scenario_id, payload["entries"], scenario_question=question)
            self.runs.update(run.id, status="completed", output={"candidates": TypeAdapter(list[NodeCandidate]).dump_python(output, mode="json")}, elapsed_ms=int((time.perf_counter() - started) * 1000))
            return run.id, output
        except Exception as exc:
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
            raise

    def _run(self, payload, *, run_id: str, parent_run_id: str | None):  # pragma: no cover
        raise NotImplementedError

    def _extract(self, run_id: str, scenario_id: str, entries: list[KBEntry], *, scenario_question: str = "") -> list[NodeCandidate]:
        if self.llm_client is not None and entries:
            try:
                evidence_block = "\n".join(
                    f"- id={entry.id} | source={entry.source_name} | content={(entry.content or '')[:600]}"
                    for entry in entries[:40]
                )
                result = self.llm_complete_json(
                    [
                        {
                            "role": "user",
                            "content": (
                                f"Scenario: {scenario_question}\n"
                                f"scenario_id: {scenario_id}\n\n"
                                f"Evidence:\n{evidence_block}"
                            ),
                        }
                    ],
                    run_id=run_id,
                    system=EVENT_EXTRACTOR_SYSTEM,
                    schema=_ExtractionResponse,
                    repair_retries=1,
                    escalation_profiles=("balanced",),
                )
                response = _ExtractionResponse.model_validate(result)
                valid_ids = {entry.id for entry in entries}
                gated = []
                for candidate in response.candidates:
                    candidate = candidate.model_copy(
                        update={
                            "name": _clean_name(candidate.name),
                            "type": "event",
                            "scenario_ids": sorted({*candidate.scenario_ids, scenario_id}),
                            "kb_entry_ids": [kb_id for kb_id in candidate.kb_entry_ids if kb_id in valid_ids],
                        }
                    )
                    if validate_node_candidate(candidate, scenario_question=scenario_question):
                        gated.append(candidate)
                if gated:
                    return _deduplicate_candidates(gated)
                self.runs.add_message(run_id, "system", "EventExtractor LLM returned no candidates passing quality gate.", payload={"raw_count": len(response.candidates)})
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                if not self.config.agents.allow_deterministic_dev_fallback:
                    raise
                self.runs.add_message(run_id, "system", "EventExtractor LLM path failed; using deterministic fallback.", payload={"error": str(exc)})

        candidates: list[NodeCandidate] = []
        for entry in entries:
            content = _sentence(entry.content)
            if any(hint in entry.content.lower() for hint in self.EVENT_HINTS):
                candidates.append(NodeCandidate(name=content[:70], type="event", description=f"Event-like observation from {entry.source_name}: {content}", current_state=content, kb_entry_ids=[entry.id], scenario_ids=[scenario_id], confidence=float((entry.perspective_tags or {}).get("confidence", 0.55))))
        return [c for c in candidates if validate_node_candidate(c, scenario_question=scenario_question)]


TOPIC_THEME_EXTRACTOR_SYSTEM = """You are The Seldon Project's Topic/Theme Extractor.

Identify the broad themes and topic clusters present across the evidence — the
domains/categories that connect multiple pieces of evidence. Examples for a gold
forecast: "Monetary policy", "Geopolitical risk", "Currency dynamics",
"Mining supply".

Each topic must:
- Be grounded in evidence (list kb_entry_ids).
- Be a recognizable theme name, not a single word like "gold" (the scenario
  subject itself is already covered by entity extraction).
- Have type="topic".

Return STRICT JSON: {"candidates": [NodeCandidate, ...]}. Aim for 3-6 themes."""


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
            output = self._extract(run.id, payload["scenario_id"], payload["question"], payload["entries"])
            self.runs.update(run.id, status="completed", output={"candidates": TypeAdapter(list[NodeCandidate]).dump_python(output, mode="json")}, elapsed_ms=int((time.perf_counter() - started) * 1000))
            return run.id, output
        except Exception as exc:
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
            raise

    def _run(self, payload, *, run_id: str, parent_run_id: str | None):  # pragma: no cover
        raise NotImplementedError

    def _extract(self, run_id: str, scenario_id: str, question: str, entries: list[KBEntry]) -> list[NodeCandidate]:
        if self.llm_client is not None and entries:
            try:
                evidence_block = "\n".join(
                    f"- id={entry.id} | topics={entry.topics or []} | content={(entry.content or '')[:500]}"
                    for entry in entries[:40]
                )
                result = self.llm_complete_json(
                    [
                        {
                            "role": "user",
                            "content": (
                                f"Scenario: {question}\nscenario_id: {scenario_id}\n\n"
                                f"Evidence:\n{evidence_block}"
                            ),
                        }
                    ],
                    run_id=run_id,
                    system=TOPIC_THEME_EXTRACTOR_SYSTEM,
                    schema=_ExtractionResponse,
                    repair_retries=1,
                    escalation_profiles=("balanced",),
                )
                response = _ExtractionResponse.model_validate(result)
                valid_ids = {entry.id for entry in entries}
                gated = []
                for candidate in response.candidates:
                    candidate = candidate.model_copy(
                        update={
                            "name": _clean_name(candidate.name),
                            "type": "topic",
                            "scenario_ids": sorted({*candidate.scenario_ids, scenario_id}),
                            "kb_entry_ids": [kb_id for kb_id in candidate.kb_entry_ids if kb_id in valid_ids],
                        }
                    )
                    if validate_node_candidate(candidate, scenario_question=question):
                        gated.append(candidate)
                if gated:
                    return _deduplicate_candidates(gated)
                self.runs.add_message(run_id, "system", "TopicThemeExtractor LLM returned no candidates passing quality gate.", payload={"raw_count": len(response.candidates)})
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                if not self.config.agents.allow_deterministic_dev_fallback:
                    raise
                self.runs.add_message(run_id, "system", "TopicThemeExtractor LLM path failed; using deterministic fallback.", payload={"error": str(exc)})

        topics: dict[str, list[str]] = {}
        for entry in entries:
            for topic in [*entry.topics, *compact_terms(question, limit=5)]:
                if topic:
                    topics.setdefault(_clean_name(topic), []).append(entry.id)
        candidates = [NodeCandidate(name=name, type="topic", description=f"Scenario theme/topic: {name}", kb_entry_ids=sorted(set(ids)), scenario_ids=[scenario_id], confidence=0.65) for name, ids in topics.items()]
        return [c for c in candidates if validate_node_candidate(c, scenario_question=question)]


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
        existing_vecs = {node.id: embed_text(node.name) for node in existing}
        proposals: list[MergeProposal] = []
        grouped: dict[tuple[str, NodeType], list[NodeCandidate]] = {}
        for candidate in candidates:
            grouped.setdefault((_canonical(candidate.name), candidate.type), []).append(candidate)
        for (_canon, ntype), group in grouped.items():
            keys: set[str] = set()
            for candidate in group:
                keys |= _name_keys(candidate.name, candidate.aliases)
            # 1) exact canonical name or alias match against an existing node
            match = next((node for node in existing if node.type == ntype and _canonical(node.name) in keys), None)
            reason = "Exact name/alias match; safe merge candidate, not auto-destructive"
            confidence = 0.9
            # 2) embedding-similarity fallback for near-duplicate surface forms
            if match is None:
                gvec = embed_text(group[0].name)
                best, best_score = None, 0.0
                for node in existing:
                    if node.type != ntype:
                        continue
                    score = cosine_similarity(gvec, existing_vecs.get(node.id))
                    if score > best_score:
                        best, best_score = node, score
                if best is not None and best_score >= _EMBED_MERGE_THRESHOLD:
                    match, reason, confidence = best, f"Embedding similarity {best_score:.2f}", round(best_score, 2)
            if match or len(group) > 1:
                proposals.append(
                    MergeProposal(
                        canonical_name=group[0].name,
                        type=ntype,
                        existing_node_id=match.id if match else None,
                        candidate_names=[candidate.name for candidate in group],
                        alias_node_ids=[match.id] if match else [],
                        reason=reason if match else "Multiple candidates share a canonical name; intra-batch merge",
                        confidence=confidence if match else 0.75,
                    )
                )
        return proposals


ENTITY_RESOLVER_SYSTEM = """You are The Seldon Project's Entity Resolver.

Given NEW candidate nodes and the EXISTING graph nodes for this scenario, decide
for each candidate whether it denotes the SAME real-world entity as an existing
node. For each candidate emit exactly one decision:

- "merge"  : same entity as an existing node -> give its existing_node_id
             (e.g. "Fed" and "Federal Reserve", "Gold price" and "Gold spot price").
- "alias"  : an abbreviation/surface-form of an existing node -> give existing_node_id.
- "reject" : not a real domain entity (generic word, question scaffolding, a
             restatement of the scenario question).
- "create" : a genuinely new entity not already present.

Rules:
- Only merge/alias when confident they are the same thing. Prefer "create" if unsure.
- Never merge across different node types (an actor is not a metric).

Return STRICT JSON:
{"resolved_nodes": [{"candidate_name": "...", "action": "create|merge|alias|reject",
                     "existing_node_id": "<id or null>", "reason": "...", "confidence": 0.0-1.0}]}."""


class _ResolverDecision(BaseModel):
    candidate_name: str
    action: Literal["create", "merge", "alias", "reject"] = "create"
    existing_node_id: str | None = None
    reason: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class _ResolverResponse(BaseModel):
    resolved_nodes: list[_ResolverDecision] = Field(default_factory=list)


class ExtractionCoordinator(AgentBase[ExtractionInput, ExtractionOutput]):
    agent_id = "extraction_coordinator"
    phase = "extraction"
    model_profile = "balanced"

    def _llm_resolutions(self, run_id: str, candidates: list[NodeCandidate], existing_nodes: list) -> dict[str, _ResolverDecision]:
        """Best-effort LLM entity resolution layered on top of deterministic rules.

        Returns a map of canonical candidate name -> decision. Skipped entirely
        when no LLM is configured (tests/CI). Any non-auth failure degrades to
        deterministic resolution rather than failing extraction; auth failures
        propagate so the job queue pauses.
        """
        if self.llm_client is None or not candidates:
            return {}
        try:
            existing_block = "\n".join(f"- id={node.id} | type={node.type} | name={node.name}" for node in existing_nodes[:60]) or "(none)"
            candidate_block = "\n".join(f"- name={c.name} | type={c.type} | aliases={c.aliases or []}" for c in candidates[:60])
            result = self.llm_complete_json(
                [{"role": "user", "content": f"EXISTING NODES:\n{existing_block}\n\nNEW CANDIDATES:\n{candidate_block}"}],
                run_id=run_id,
                system=ENTITY_RESOLVER_SYSTEM,
                schema=_ResolverResponse,
                repair_retries=1,
                escalation_profiles=("balanced",),
            )
            response = _ResolverResponse.model_validate(result)
        except LLMAuthenticationError:
            raise
        except Exception as exc:
            self.runs.add_message(run_id, "system", "EntityResolver unavailable; using deterministic resolution.", payload={"error": str(exc)})
            return {}
        valid_ids = {node.id for node in existing_nodes}
        decisions: dict[str, _ResolverDecision] = {}
        for decision in response.resolved_nodes:
            if decision.action in ("merge", "alias") and decision.existing_node_id not in valid_ids:
                continue  # hallucinated node id — ignore the hint
            decisions[_canonical(decision.candidate_name)] = decision
        return decisions

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
        # Resolution maps: every canonical name/alias key -> the node it belongs
        # to, plus a per-node name-embedding cache for similarity matching. Seeded
        # with already-persisted nodes so new candidates merge onto them.
        by_key: dict[tuple[str, str], Any] = {}
        node_vecs: dict[str, list[float]] = {}
        existing_nodes = graph.list_nodes()
        for node in existing_nodes:
            by_key[(_canonical(node.name), node.type)] = node
            node_vecs[node.id] = embed_text(node.name)
        now = datetime.now(timezone.utc)

        # Optional LLM resolution layered on top of the deterministic rules below.
        resolutions = self._llm_resolutions(run_id, all_candidates, existing_nodes)
        existing_by_id = {node.id: node for node in existing_nodes}

        def _resolve_existing(candidate: NodeCandidate):
            # 1) exact canonical name or any alias canonical match (same type)
            for key in _name_keys(candidate.name, candidate.aliases):
                node = by_key.get((key, candidate.type))
                if node is not None:
                    return node
            # 2) embedding similarity against already-seen same-type nodes
            cvec = embed_text(candidate.name)
            best = None
            best_score = 0.0
            for (_ck, ctype), node in by_key.items():
                if ctype != candidate.type:
                    continue
                score = cosine_similarity(cvec, node_vecs.get(node.id))
                if score > best_score:
                    best, best_score = node, score
            if best is not None and best_score >= _EMBED_MERGE_THRESHOLD:
                return best
            return None

        def _register(node, candidate: NodeCandidate) -> None:
            for key in _name_keys(candidate.name, candidate.aliases):
                by_key[(key, candidate.type)] = node
            node_vecs.setdefault(node.id, embed_text(node.name))

        rejected: list[str] = []
        for candidate in all_candidates:
            decision = resolutions.get(_canonical(candidate.name))
            if decision is not None and decision.action == "reject" and decision.confidence >= 0.6:
                # LLM judged this not a real domain entity — drop it.
                rejected.append(candidate.name)
                continue

            # Enrich the candidate's kb_entry_ids with any KB entries that
            # explicitly mention this node by name/alias in their entities,
            # topics, or content. Ensures each node carries its full evidence
            # trail rather than just the entries the LLM happened to cite.
            supporting = kb_entries_supporting(candidate.name, candidate.aliases or [], kb_entries)
            candidate_kb_ids = sorted({*(candidate.kb_entry_ids or []), *supporting})

            existing = None
            if decision is not None and decision.action in ("merge", "alias") and decision.existing_node_id:
                existing = existing_by_id.get(decision.existing_node_id)
            if existing is None:
                existing = _resolve_existing(candidate)
            if existing is not None:
                kb_ids = sorted({*(existing.kb_entry_ids or []), *candidate_kb_ids})
                scenario_ids = sorted({*(existing.scenario_ids or []), *candidate.scenario_ids})
                node = graph.update_node(existing.id, tags=sorted({*(existing.tags or []), *candidate.tags}), kb_entry_ids=kb_ids, scenario_ids=scenario_ids, current_state=candidate.current_state or existing.current_state, state_updated_at=now)
                # Register the candidate's surface forms so later candidates that
                # use any of them collapse onto this same node.
                _register(node, candidate)
                if node.id not in updated and node.id not in created:
                    updated.append(node.id)
                continue
            node = graph.create_node(name=candidate.name, type=candidate.type, tags=candidate.tags, description=candidate.description, current_state=candidate.current_state, state_updated_at=now, kb_entry_ids=candidate_kb_ids, scenario_ids=candidate.scenario_ids, stability_score=0.5, importance_score=0.0)
            _register(node, candidate)
            created.append(node.id)

        AuditRepository(self.db).emit("scenario", payload.scenario_id, "extraction_graph_write", actor=self.agent_id, reason="Phase F extraction wrote ERG nodes", after={"created_node_ids": created, "updated_node_ids": updated, "merge_proposals": [p.model_dump(mode="json") for p in proposals], "rejected_candidates": rejected})
        return ExtractionOutput(child_run_ids=child_run_ids, entity_candidates=entities, event_candidates=events, topic_candidates=topics, merge_proposals=proposals, created_node_ids=created, updated_node_ids=updated)
