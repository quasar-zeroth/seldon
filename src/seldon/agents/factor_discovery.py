"""FactorDiscovery agent.

Runs at the start of context gathering. Takes the user's raw scenario question
and asks the LLM to identify:
- The forecast subject and primary topic (e.g. "Gold price")
- A multi-sentence description of the drivers (becomes Scenario.description)
- Key entities that should become seed graph nodes
- Key metrics with directional effect on the subject
- 5-8 web subqueries, one per driver, with rationales

This output drives the rest of the pipeline:
- description → Scenario.description (so the UI shows a real narrative)
- subqueries → fed directly into InformationRetriever (replaces the old
  heuristic QueryDecomposer for the first pass)
- key_entities + metrics → seed candidates for entity extraction

Without this step the pipeline starts from the raw question, which is why the
prior gold-price scenario produced stopword nodes like "question" and "scope".
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from seldon.data.models import Scenario
from seldon.llm.openrouter import LLMAuthenticationError

from .base import AgentBase
from .contracts import QueryPlan, Subquery


FACTOR_DISCOVERY_SYSTEM = """You are The Seldon Project's Factor Discovery agent.

Given a forecasting scenario, identify the real-world factors that drive the outcome.
Examples:
- "What will gold prices be in 6 months?" -> drivers: central bank gold purchases,
  US dollar index, real yields, geopolitical risk, equity-market stress, ETF flows.
- "Will Brazil cut rates this year?" -> drivers: inflation print, currency stability,
  fiscal deficit, political pressure, regional rate differentials.

Be concrete and specific. Avoid generic categories ("economic factors") in favor of
named, observable phenomena.

Return STRICT JSON matching this shape:
{
  "forecast_subject": "<short noun phrase, e.g. 'Gold spot price'>",
  "primary_topic": "<single-word topic tag, e.g. 'gold' or 'commodities'>",
  "description": "<2-4 sentence narrative naming the main drivers and how they
                   interact to determine the outcome>",
  "key_entities": [
    {"name": "<concrete named entity>", "type": "<entity|actor|metric|policy|event|topic>",
     "why_relevant": "<one sentence>"}
  ],
  "metrics": [
    {"name": "<observable metric>", "unit": "<e.g. USD/oz, %, index>",
     "direction_of_effect": "<positive|negative|complex>"}
  ],
  "subqueries": [
    {"query": "<web-searchable query for this driver, including current/2025/recent
                  terms if temporal>",
     "topic": "<tag>",
     "rationale": "<why we need this evidence>"}
  ]
}

Produce 5-8 entities and 5-8 subqueries. No prose outside JSON."""


class FactorEntity(BaseModel):
    name: str
    type: Literal["entity", "actor", "metric", "policy", "event", "topic"] = "entity"
    why_relevant: str = ""


class FactorMetric(BaseModel):
    name: str
    unit: str = ""
    direction_of_effect: Literal["positive", "negative", "complex"] = "complex"


class FactorDiscoveryOutput(BaseModel):
    forecast_subject: str
    primary_topic: str
    description: str
    key_entities: list[FactorEntity] = Field(default_factory=list)
    metrics: list[FactorMetric] = Field(default_factory=list)
    subqueries: list[Subquery] = Field(default_factory=list)


class FactorDiscoveryInput(BaseModel):
    scenario_id: str
    question: str
    timeframe: str = ""
    max_subqueries: int = 8


class FactorDiscovery(AgentBase[FactorDiscoveryInput, FactorDiscoveryOutput]):
    agent_id = "factor_discovery"
    phase = "context_gathering"
    model_profile = "balanced"

    def _run(self, payload: FactorDiscoveryInput, *, run_id: str, parent_run_id: str | None) -> FactorDiscoveryOutput:
        if self.llm_client is not None:
            try:
                user_message = (
                    f"Scenario question: {payload.question}\n"
                    f"Time horizon: {payload.timeframe or 'unspecified'}\n"
                    f"Maximum subqueries: {payload.max_subqueries}\n"
                    "Identify the drivers and return the JSON described in the system prompt."
                )
                result = self.llm_complete_json(
                    [{"role": "user", "content": user_message}],
                    run_id=run_id,
                    system=FACTOR_DISCOVERY_SYSTEM,
                    schema=FactorDiscoveryOutput,
                    repair_retries=1,
                    escalation_profiles=("reasoning",),
                )
                output = FactorDiscoveryOutput.model_validate(result)
                # Cap subqueries so we don't blow past retrieval budget.
                if len(output.subqueries) > payload.max_subqueries:
                    output = output.model_copy(update={"subqueries": output.subqueries[: payload.max_subqueries]})
                scenario_row = self.db.get(Scenario, payload.scenario_id)
                if scenario_row is not None and output.description:
                    scenario_row.description = output.description
                    self.db.flush()
                return output
            except LLMAuthenticationError:
                raise
            except Exception as exc:
                if not self.config.agents.allow_deterministic_dev_fallback:
                    raise
                self.runs.add_message(run_id, "system", "FactorDiscovery LLM path failed; using deterministic fallback.", payload={"error": str(exc)})

        # No LLM client OR dev-fallback enabled: return a minimal output so the
        # rest of the pipeline keeps running. Quality is intentionally bare in
        # this mode; production should always have a working LLM.
        output = FactorDiscoveryOutput(
            forecast_subject=payload.question[:80],
            primary_topic=payload.question.split()[0].lower() if payload.question else "topic",
            description=f"Forecast about: {payload.question}",
            subqueries=[Subquery(query=payload.question, topic=None, rationale="Original question (LLM unavailable)")],
        )
        # Cap subqueries so we don't blow past retrieval budget.
        if len(output.subqueries) > payload.max_subqueries:
            output = output.model_copy(update={"subqueries": output.subqueries[: payload.max_subqueries]})

        # Persist the discovered description onto the scenario row so the UI can
        # show "gold price depends on central banks, real yields, ..." without
        # waiting for downstream phases.
        scenario_row = self.db.get(Scenario, payload.scenario_id)
        if scenario_row is not None and output.description:
            scenario_row.description = output.description
            self.db.flush()
        return output

    def to_query_plan(self, output: FactorDiscoveryOutput, timeframe: str) -> QueryPlan:
        """Convert FactorDiscovery output into a QueryPlan for InformationRetriever."""
        return QueryPlan(
            primary_topic=output.primary_topic,
            temporal_scope=timeframe,
            subqueries=list(output.subqueries),
            topics=[output.primary_topic, *{e.name.lower() for e in output.key_entities}],
            entities=[e.name for e in output.key_entities],
        )


__all__ = [
    "FactorDiscovery",
    "FactorDiscoveryInput",
    "FactorDiscoveryOutput",
    "FactorEntity",
    "FactorMetric",
]
