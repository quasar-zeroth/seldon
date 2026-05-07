"""Phase E context-gathering coordinator and specialist agents."""
from __future__ import annotations

from typing import Any


from seldon.data.models import Scenario
from seldon.data.repositories import AuditRepository, KBRepository, SourceRepository

from .base import AgentBase, compact_terms
from .contracts import (
    ContextGatheringInput,
    ContextGatheringOutput,
    Delta,
    KBWriteResult,
    Observation,
    QueryPlan,
    RetrievalResult,
    RetrievedSource,
    Subquery,
)


class QueryDecomposer(AgentBase[ContextGatheringInput, QueryPlan]):
    agent_id = "query_decomposer"
    model_profile = "fast"

    def _run(self, payload: ContextGatheringInput, *, run_id: str, parent_run_id: str | None) -> QueryPlan:
        terms = compact_terms(f"{payload.question} {payload.timeframe}", limit=payload.max_subqueries)
        primary = terms[0] if terms else payload.question[:80]
        subqueries = [
            Subquery(query=payload.question, topic=primary, rationale="Original scenario question"),
            Subquery(query=f"{payload.question} key drivers", topic=primary, rationale="Identify major drivers"),
            Subquery(query=f"{payload.question} risks contradictions", topic=primary, rationale="Surface counter-evidence and uncertainty"),
        ]
        for term in terms[1:]:
            subqueries.append(Subquery(query=f"{term} implications for {payload.question}", topic=term, rationale=f"Related topic: {term}"))
        return QueryPlan(
            primary_topic=primary,
            temporal_scope=payload.timeframe,
            subqueries=subqueries[: payload.max_subqueries],
            topics=terms or [primary],
            entities=[t for t in terms if t[:1].isupper()],
        )


class InformationRetriever(AgentBase[QueryPlan, RetrievalResult]):
    agent_id = "information_retriever"
    model_profile = "fast"

    def _run(self, payload: QueryPlan, *, run_id: str, parent_run_id: str | None) -> RetrievalResult:
        kb = KBRepository(self.db)
        collected: list[RetrievedSource] = []
        seen: set[str] = set()
        for subquery in payload.subqueries:
            matches = kb.semantic_search(subquery.query, limit=5)
            if subquery.topic:
                matches.extend(kb.search(topic=subquery.topic))
            for entry in matches:
                if entry.id in seen:
                    continue
                seen.add(entry.id)
                collected.append(
                    RetrievedSource(
                        source_id=entry.id,
                        url=entry.source_url,
                        name=entry.source_name,
                        content=entry.content,
                        original_snippet=entry.original_snippet,
                        topics=entry.topics or [],
                        entities=entry.entities or [],
                        valid_from=entry.valid_from,
                        confidence=float((entry.perspective_tags or {}).get("confidence", 0.5)),
                    )
                )
        if not collected:
            collected.append(
                RetrievedSource(
                    source_type="scenario_brief",
                    name="Scenario brief",
                    content=f"Scenario question: {payload.subqueries[0].query if payload.subqueries else payload.primary_topic}. Temporal scope: {payload.temporal_scope or 'unspecified'}.",
                    original_snippet=payload.subqueries[0].query if payload.subqueries else payload.primary_topic,
                    topics=payload.topics,
                    entities=payload.entities,
                    confidence=0.4,
                )
            )
        return RetrievalResult(query=payload.primary_topic, sources=collected)


class InformationSummarizer(AgentBase[RetrievalResult, Observation]):
    agent_id = "information_summarizer"
    model_profile = "fast"

    def _run(self, payload: RetrievalResult, *, run_id: str, parent_run_id: str | None) -> Observation:
        source = payload.sources[0]
        content = source.content.strip()
        if len(content) > 600:
            content = content[:597].rstrip() + "..."
        return Observation(
            content=content,
            original_snippet=source.original_snippet or source.content,
            source_type=source.source_type,
            source_url=source.url,
            source_name=source.name,
            valid_from=source.valid_from,
            topics=source.topics,
            entities=source.entities,
            perspective_tags={"confidence": source.confidence},
            source_reference=source.source_id,
        )


class DeduplicationDeltaDetector(AgentBase[Observation, Delta]):
    agent_id = "deduplication_delta_detector"
    model_profile = "fast"

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join(text.lower().split())

    def _run(self, payload: Observation, *, run_id: str, parent_run_id: str | None) -> Delta:
        kb = KBRepository(self.db)
        candidates = kb.search(payload.content[:80], current_only=True)
        norm = self._norm(payload.content)
        for entry in candidates:
            if self._norm(entry.content) == norm:
                return Delta(observation_index=0, status="duplicate", matched_kb_entry_id=entry.id, reason="Exact normalized content match")
        for topic in payload.topics:
            for entry in kb.search(topic=topic, current_only=True):
                if entry.source_url and payload.source_url and entry.source_url == payload.source_url:
                    return Delta(observation_index=0, status="duplicate", matched_kb_entry_id=entry.id, reason="Same source URL and topic")
        return Delta(observation_index=0, status="new", reason="No duplicate found in KB")


class KBWriter(AgentBase[dict[str, Any], KBWriteResult]):
    agent_id = "kb_writer"
    model_profile = "fast"

    def run_writer(self, *, scenario_id: str, observations: list[Observation], deltas: list[Delta], parent_run_id: str | None = None) -> tuple[str, KBWriteResult]:
        return self.run({"scenario_id": scenario_id, "observations": observations, "deltas": deltas}, parent_run_id=parent_run_id)  # type: ignore[arg-type]

    def run(self, payload: dict[str, Any], *, parent_run_id: str | None = None) -> tuple[str, KBWriteResult]:  # type: ignore[override]
        # dict payload keeps this aggregate writer simple while preserving the base persistence shape.
        import time

        started = time.perf_counter()
        json_payload = {
            "scenario_id": payload["scenario_id"],
            "observations": [o.model_dump(mode="json") for o in payload["observations"]],
            "deltas": [d.model_dump(mode="json") for d in payload["deltas"]],
            "parent_run_id": parent_run_id,
        }
        run = self.runs.create(agent_id=self.agent_id, phase=self.phase, status="running", input=json_payload)
        try:
            output = self._run_dict(payload, run_id=run.id)
            self.runs.update(run.id, status="completed", output=output.model_dump(mode="json"), elapsed_ms=int((time.perf_counter() - started) * 1000))
            return run.id, output
        except Exception as exc:
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=int((time.perf_counter() - started) * 1000))
            raise

    def _run(self, payload: Any, *, run_id: str, parent_run_id: str | None) -> KBWriteResult:
        raise NotImplementedError

    def _run_dict(self, payload: dict[str, Any], *, run_id: str) -> KBWriteResult:
        scenario_id: str = payload["scenario_id"]
        observations: list[Observation] = payload["observations"]
        deltas: list[Delta] = payload["deltas"]
        kb = KBRepository(self.db)
        sources = SourceRepository(self.db)
        created: list[str] = []
        linked: list[str] = []
        skipped: list[int] = []
        for idx, observation in enumerate(observations):
            delta = deltas[idx]
            if delta.status == "duplicate" and delta.matched_kb_entry_id:
                existing = kb.get(delta.matched_kb_entry_id)
                if existing is not None and scenario_id not in (existing.scenario_ids or []):
                    kb.update_entry(existing.id, actor=self.agent_id, reason="linked duplicate to context gathering scenario", scenario_ids=[*(existing.scenario_ids or []), scenario_id])
                linked.append(delta.matched_kb_entry_id)
                skipped.append(idx)
                continue
            source = sources.create(source_type=observation.source_type, url=observation.source_url, name=observation.source_name, actor=self.agent_id, reason="context gathering source")
            entry = kb.create_entry(
                actor=self.agent_id,
                reason="context gathering observation",
                content=observation.content,
                original_snippet=observation.original_snippet,
                source_type=observation.source_type,
                source_url=observation.source_url,
                source_name=observation.source_name,
                source_id=source.id,
                valid_from=observation.valid_from,
                topics=observation.topics,
                entities=observation.entities,
                scenario_ids=[scenario_id],
                perspective_tags=observation.perspective_tags,
            )
            created.append(entry.id)
            linked.append(entry.id)
        AuditRepository(self.db).emit("scenario", scenario_id, "context_gathering_kb_write", actor=self.agent_id, reason="Phase E context gathering wrote KB entries", after={"created_entry_ids": created, "linked_entry_ids": linked})
        return KBWriteResult(created_entry_ids=created, linked_entry_ids=linked, skipped_observation_indexes=skipped)


class ContextGatheringCoordinator(AgentBase[ContextGatheringInput, ContextGatheringOutput]):
    agent_id = "context_gathering_coordinator"
    model_profile = "balanced"

    @classmethod
    def input_from_scenario(cls, scenario: Scenario, *, depth: str = "standard", source_policy: str = "kb_first", max_subqueries: int = 8) -> ContextGatheringInput:
        return ContextGatheringInput(
            scenario_id=scenario.id,
            question=scenario.target_question,
            timeframe=scenario.time_horizon,
            depth=depth,  # type: ignore[arg-type]
            source_policy=source_policy,  # type: ignore[arg-type]
            max_subqueries=max_subqueries,
        )

    def _run(self, payload: ContextGatheringInput, *, run_id: str, parent_run_id: str | None) -> ContextGatheringOutput:
        child_run_ids: list[str] = []
        q_run, plan = QueryDecomposer(self.db, config=self.config, llm_client=self.llm_client).run(payload, parent_run_id=run_id)
        child_run_ids.append(q_run)

        r_run, retrieval = InformationRetriever(self.db, config=self.config, llm_client=self.llm_client).run(plan, parent_run_id=run_id)
        child_run_ids.append(r_run)

        observations: list[Observation] = []
        for source in retrieval.sources:
            s_run, observation = InformationSummarizer(self.db, config=self.config, llm_client=self.llm_client).run(RetrievalResult(query=retrieval.query, sources=[source]), parent_run_id=run_id)
            child_run_ids.append(s_run)
            observations.append(observation)

        deltas: list[Delta] = []
        for idx, observation in enumerate(observations):
            d_run, delta = DeduplicationDeltaDetector(self.db, config=self.config, llm_client=self.llm_client).run(observation, parent_run_id=run_id)
            child_run_ids.append(d_run)
            deltas.append(delta.model_copy(update={"observation_index": idx}))

        w_run, write_result = KBWriter(self.db, config=self.config, llm_client=self.llm_client).run_writer(scenario_id=payload.scenario_id, observations=observations, deltas=deltas, parent_run_id=run_id)
        child_run_ids.append(w_run)

        return ContextGatheringOutput(
            run_plan=plan,
            child_run_ids=child_run_ids,
            retrievals=[retrieval],
            observations=observations,
            deltas=deltas,
            kb_entry_ids=write_result.linked_entry_ids,
        )
