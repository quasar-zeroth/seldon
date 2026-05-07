"""Phase J advanced intelligence agents for prediction hardening."""
from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from seldon.data.models import (
    AdvancedAnalysis,
    AssumptionRecord,
    BaseRateEvidence,
    HistoricalAnalogy,
    KBEntry,
    ScenarioPrediction,
    ScenarioVersion,
    SentimentDrift,
    utcnow,
)
from seldon.data.repositories import AuditRepository, GraphRepository, row_to_dict

from .base import AgentBase


class AdvancedIntelligenceInput(BaseModel):
    prediction_id: str
    previous_prediction_id: str | None = None
    max_items: int = Field(default=5, ge=1, le=20)


class RedTeamOutput(BaseModel):
    strongest_counterargument: str
    pivotal_assumption: str | None = None
    objections: list[str] = Field(default_factory=list)
    activation_recommendation: str = "proceed"


class HistoricalAnalogyOutput(BaseModel):
    analogy_ids: list[str]
    analogies: list[dict[str, Any]]


class BaseRateOutput(BaseModel):
    base_rate_ids: list[str]
    base_rates: list[dict[str, Any]]


class SentimentDriftOutput(BaseModel):
    drift_ids: list[str]
    topic_velocity: dict[str, float]


class AssumptionRegistryOutput(BaseModel):
    assumption_ids: list[str]
    invalid_assumption_ids: list[str] = Field(default_factory=list)
    assumptions: list[dict[str, Any]]


class UncertaintyOutput(BaseModel):
    uncertainty_score: float = Field(ge=0.0, le=1.0)
    confidence_in_probabilities: float = Field(ge=0.0, le=1.0)
    entropy: float = Field(ge=0.0, le=1.0)
    drivers: list[str] = Field(default_factory=list)
    research_recommended: bool = False


class ExpertPerspectiveOutput(BaseModel):
    perspectives: list[dict[str, Any]]


class InformationValueOutput(BaseModel):
    suggestions: list[dict[str, Any]]


class ScenarioDiffOutput(BaseModel):
    previous_version: int | None = None
    current_version: int | None = None
    probability_shifts: dict[str, float] = Field(default_factory=dict)
    added_assumptions: list[str] = Field(default_factory=list)
    removed_assumptions: list[str] = Field(default_factory=list)
    status_change: list[str | None] | None = None


class CascadeRiskOutput(BaseModel):
    risks: list[dict[str, Any]]


class AdvancedIntelligenceOutput(BaseModel):
    child_run_ids: list[str]
    analysis_id: str
    red_team: RedTeamOutput
    historical_analogies: HistoricalAnalogyOutput
    base_rates: BaseRateOutput
    sentiment_drift: SentimentDriftOutput
    assumption_registry: AssumptionRegistryOutput
    uncertainty: UncertaintyOutput
    expert_perspectives: ExpertPerspectiveOutput
    information_value: InformationValueOutput
    scenario_diff: ScenarioDiffOutput
    cascade_risks: CascadeRiskOutput


def _probabilities(prediction: ScenarioPrediction) -> dict[str, float]:
    return {str(k): float(v) for k, v in (prediction.probabilities or {}).items() if isinstance(v, int | float)}


def _entropy(probabilities: dict[str, float]) -> float:
    if not probabilities:
        return 1.0
    n = len(probabilities)
    if n <= 1:
        return 0.0
    return min(1.0, -sum(p * math.log(max(p, 1e-12)) for p in probabilities.values()) / math.log(n))


def _prediction(db: Any, prediction_id: str) -> ScenarioPrediction:
    prediction = db.get(ScenarioPrediction, prediction_id)
    if prediction is None:
        raise KeyError(f"scenario_prediction not found: {prediction_id}")
    return prediction


class AdversarialRedTeamAgent(AgentBase[AdvancedIntelligenceInput, RedTeamOutput]):
    agent_id = "adversarial_red_team_agent"
    phase = "advanced_intelligence"
    model_profile = "reasoning"

    def _run(self, payload: AdvancedIntelligenceInput, *, run_id: str, parent_run_id: str | None) -> RedTeamOutput:
        prediction = _prediction(self.db, payload.prediction_id)
        probs = _probabilities(prediction)
        top = max(probs, key=probs.get) if probs else "top scenario"
        weak_assumption = (prediction.assumptions or [None])[-1]
        objections = [
            f"The highest-probability case '{top}' may be overfit to current KB evidence.",
            "A low-probability shock could dominate the graph before the resolution date.",
        ]
        if weak_assumption:
            objections.append(f"If this assumption fails, probabilities should move materially: {weak_assumption}")
        recommendation = "needs_review" if prediction.confidence < 0.45 or max(probs.values(), default=0.0) < 0.45 else "proceed"
        return RedTeamOutput(strongest_counterargument=objections[0], pivotal_assumption=weak_assumption, objections=objections[: payload.max_items], activation_recommendation=recommendation)


class HistoricalAnalogyMatcher(AgentBase[AdvancedIntelligenceInput, HistoricalAnalogyOutput]):
    agent_id = "historical_analogy_matcher"
    phase = "advanced_intelligence"
    model_profile = "balanced"

    def _run(self, payload: AdvancedIntelligenceInput, *, run_id: str, parent_run_id: str | None) -> HistoricalAnalogyOutput:
        prediction = _prediction(self.db, payload.prediction_id)
        entries = [e for e in self.db.scalars(select(KBEntry)) if not prediction.scenario_id or prediction.scenario_id in (e.scenario_ids or [])]
        rows: list[HistoricalAnalogy] = []
        for entry in entries[: payload.max_items]:
            title = f"Analogy from {entry.source_name}: {entry.content[:80]}"
            row = HistoricalAnalogy(prediction_id=prediction.id, scenario_id=prediction.scenario_id, title=title, similarity_score=min(0.9, 0.45 + 0.05 * len(entry.topics or [])), historical_outcome=entry.original_snippet or entry.content[:240], rationale="Matched via shared scenario evidence, topics, and entities.", source_kb_ids=[entry.id])
            self.db.add(row)
            self.db.flush()
            rows.append(row)
        return HistoricalAnalogyOutput(analogy_ids=[r.id for r in rows], analogies=[row_to_dict(r) for r in rows])


class BaseRateAnchorer(AgentBase[AdvancedIntelligenceInput, BaseRateOutput]):
    agent_id = "base_rate_anchorer"
    phase = "advanced_intelligence"
    model_profile = "fast"

    def _run(self, payload: AdvancedIntelligenceInput, *, run_id: str, parent_run_id: str | None) -> BaseRateOutput:
        prediction = _prediction(self.db, payload.prediction_id)
        probs = _probabilities(prediction)
        rows: list[BaseRateEvidence] = []
        for key, value in list(probs.items())[: payload.max_items]:
            row = BaseRateEvidence(prediction_id=prediction.id, scenario_id=prediction.scenario_id, metric=f"base_rate_{key}", population="Current comparable prediction classes in Seldon history", observed_frequency=value, sample_size=max(1, len(probs)), rationale="Phase J anchor: use generated scenario probability as prior until external historical series are ingested.")
            self.db.add(row)
            self.db.flush()
            rows.append(row)
        return BaseRateOutput(base_rate_ids=[r.id for r in rows], base_rates=[row_to_dict(r) for r in rows])


class SentimentDriftTracker(AgentBase[AdvancedIntelligenceInput, SentimentDriftOutput]):
    agent_id = "sentiment_drift_tracker"
    phase = "advanced_intelligence"
    model_profile = "fast"

    def _run(self, payload: AdvancedIntelligenceInput, *, run_id: str, parent_run_id: str | None) -> SentimentDriftOutput:
        prediction = _prediction(self.db, payload.prediction_id)
        entries = [e for e in self.db.scalars(select(KBEntry)) if not prediction.scenario_id or prediction.scenario_id in (e.scenario_ids or [])]
        by_topic: dict[str, list[KBEntry]] = {}
        for entry in entries:
            for topic in entry.topics or ["general"]:
                by_topic.setdefault(topic, []).append(entry)
        ids: list[str] = []
        velocities: dict[str, float] = {}
        for topic, topic_entries in list(by_topic.items())[: payload.max_items]:
            sentiments = [float((e.perspective_tags or {}).get("sentiment", 0.0)) for e in topic_entries]
            current = sum(sentiments) / len(sentiments)
            previous = self.db.scalar(select(SentimentDrift).where(SentimentDrift.topic == topic).order_by(SentimentDrift.measured_at.desc()))
            prev_value = previous.sentiment if previous else None
            velocity = current - (prev_value if prev_value is not None else current)
            row = SentimentDrift(scenario_id=prediction.scenario_id, topic=topic, sentiment=current, previous_sentiment=prev_value, velocity=velocity, evidence_kb_ids=[e.id for e in topic_entries])
            self.db.add(row)
            self.db.flush()
            ids.append(row.id)
            velocities[topic] = velocity
        return SentimentDriftOutput(drift_ids=ids, topic_velocity=velocities)


class AssumptionRegistry(AgentBase[AdvancedIntelligenceInput, AssumptionRegistryOutput]):
    agent_id = "assumption_registry"
    phase = "advanced_intelligence"
    model_profile = "fast"

    def _run(self, payload: AdvancedIntelligenceInput, *, run_id: str, parent_run_id: str | None) -> AssumptionRegistryOutput:
        prediction = _prediction(self.db, payload.prediction_id)
        assumptions: list[AssumptionRecord] = []
        invalid: list[str] = []
        kb_entries = list(self.db.scalars(select(KBEntry)))
        for statement in prediction.assumptions or []:
            invalidator = next((e for e in kb_entries if any(term in e.content.lower() for term in ["contradicts", "invalidates", "failed assumption", statement[:24].lower()])), None)
            row = AssumptionRecord(prediction_id=prediction.id, scenario_id=prediction.scenario_id, statement=statement, used_in_scenarios=[prediction.scenario_id] if prediction.scenario_id else [], still_valid=invalidator is None, status="invalid" if invalidator else "valid", last_checked=utcnow(), invalidated_by=invalidator.id if invalidator else None)
            self.db.add(row)
            self.db.flush()
            assumptions.append(row)
            if invalidator:
                invalid.append(row.id)
        return AssumptionRegistryOutput(assumption_ids=[a.id for a in assumptions], invalid_assumption_ids=invalid, assumptions=[row_to_dict(a) for a in assumptions])


class UncertaintyQuantificationLayer(AgentBase[AdvancedIntelligenceInput, UncertaintyOutput]):
    agent_id = "uncertainty_quantification_layer"
    phase = "advanced_intelligence"
    model_profile = "fast"

    def _run(self, payload: AdvancedIntelligenceInput, *, run_id: str, parent_run_id: str | None) -> UncertaintyOutput:
        prediction = _prediction(self.db, payload.prediction_id)
        ent = _entropy(_probabilities(prediction))
        uncertainty = min(1.0, (1.0 - prediction.confidence) * 0.55 + ent * 0.45)
        drivers = []
        if prediction.confidence < 0.5:
            drivers.append("low model confidence")
        if ent > 0.8:
            drivers.append("flat scenario probability distribution")
        return UncertaintyOutput(uncertainty_score=uncertainty, confidence_in_probabilities=1.0 - uncertainty, entropy=ent, drivers=drivers, research_recommended=uncertainty > 0.55)


class ExpertPerspectiveSimulator(AgentBase[AdvancedIntelligenceInput, ExpertPerspectiveOutput]):
    agent_id = "expert_perspective_simulator"
    phase = "advanced_intelligence"
    model_profile = "reasoning"

    def _run(self, payload: AdvancedIntelligenceInput, *, run_id: str, parent_run_id: str | None) -> ExpertPerspectiveOutput:
        prediction = _prediction(self.db, payload.prediction_id)
        archetypes = ["macro hedge fund manager", "central bank economist", "commodity trader"]
        perspectives = [{"archetype": a, "view": f"A {a} would scrutinize '{prediction.statement}' through drivers {', '.join((prediction.key_drivers or [])[:3]) or 'not yet identified'}.", "bias_check": "Use as perspective, not consensus."} for a in archetypes]
        return ExpertPerspectiveOutput(perspectives=perspectives[: payload.max_items])


class InformationValueCalculator(AgentBase[AdvancedIntelligenceInput, InformationValueOutput]):
    agent_id = "information_value_calculator"
    phase = "advanced_intelligence"
    model_profile = "balanced"

    def _run(self, payload: AdvancedIntelligenceInput, *, run_id: str, parent_run_id: str | None) -> InformationValueOutput:
        prediction = _prediction(self.db, payload.prediction_id)
        graph = GraphRepository(self.db)
        nodes = [n for n in graph.list_nodes() if prediction.scenario_id in (n.scenario_ids or [])]
        suggestions = []
        for node in sorted(nodes, key=lambda n: n.importance_score * (1 - n.stability_score) + (0.2 if not n.kb_entry_ids else 0), reverse=True)[: payload.max_items]:
            value = min(1.0, node.importance_score * (1 - node.stability_score) + (0.2 if not node.kb_entry_ids else 0.0))
            suggestions.append({"node_id": node.id, "question": f"Get fresher evidence for {node.name}", "estimated_value": value, "reason": "High importance and/or low stability/evidence coverage."})
        return InformationValueOutput(suggestions=suggestions)


class ScenarioVersioningDiff(AgentBase[AdvancedIntelligenceInput, ScenarioDiffOutput]):
    agent_id = "scenario_versioning_diff"
    phase = "advanced_intelligence"
    model_profile = "fast"

    def _run(self, payload: AdvancedIntelligenceInput, *, run_id: str, parent_run_id: str | None) -> ScenarioDiffOutput:
        versions = list(self.db.scalars(select(ScenarioVersion).where(ScenarioVersion.scenario_prediction_id == payload.prediction_id).order_by(ScenarioVersion.version.desc()).limit(2)))
        if not versions:
            return ScenarioDiffOutput()
        current = versions[0]
        previous = versions[1] if len(versions) > 1 else None
        if previous is None:
            return ScenarioDiffOutput(current_version=current.version)
        cur_probs = current.snapshot.get("probabilities", {}) or {}
        prev_probs = previous.snapshot.get("probabilities", {}) or {}
        shifts = {key: float(cur_probs.get(key, 0.0)) - float(prev_probs.get(key, 0.0)) for key in set(cur_probs) | set(prev_probs)}
        cur_assumptions = set(current.snapshot.get("assumptions", []) or [])
        prev_assumptions = set(previous.snapshot.get("assumptions", []) or [])
        return ScenarioDiffOutput(previous_version=previous.version, current_version=current.version, probability_shifts=shifts, added_assumptions=sorted(cur_assumptions - prev_assumptions), removed_assumptions=sorted(prev_assumptions - cur_assumptions), status_change=[previous.snapshot.get("status"), current.snapshot.get("status")])


class CascadeRiskScorer(AgentBase[AdvancedIntelligenceInput, CascadeRiskOutput]):
    agent_id = "cascade_risk_scorer"
    phase = "advanced_intelligence"
    model_profile = "balanced"

    def _run(self, payload: AdvancedIntelligenceInput, *, run_id: str, parent_run_id: str | None) -> CascadeRiskOutput:
        prediction = _prediction(self.db, payload.prediction_id)
        graph = GraphRepository(self.db)
        nodes = [n for n in graph.list_nodes() if prediction.scenario_id in (n.scenario_ids or [])]
        risks = []
        for node in nodes:
            edges = graph.list_edges(node.id)
            weighted = sum(edge.strength * edge.confidence for edge in edges)
            score = min(1.0, (weighted / max(1, len(edges))) * 0.7 + node.importance_score * 0.3) if edges else node.importance_score * 0.3
            risks.append({"node_id": node.id, "node_name": node.name, "cascade_risk": score, "connected_edges": len(edges), "keystone": score >= 0.65})
        risks.sort(key=lambda r: r["cascade_risk"], reverse=True)
        return CascadeRiskOutput(risks=risks[: payload.max_items])


class AdvancedIntelligenceCoordinator(AgentBase[AdvancedIntelligenceInput, AdvancedIntelligenceOutput]):
    agent_id = "advanced_intelligence_coordinator"
    phase = "advanced_intelligence"
    model_profile = "reasoning"

    def _run(self, payload: AdvancedIntelligenceInput, *, run_id: str, parent_run_id: str | None) -> AdvancedIntelligenceOutput:
        prediction = _prediction(self.db, payload.prediction_id)
        child_run_ids: list[str] = []
        agents = [
            AdversarialRedTeamAgent,
            HistoricalAnalogyMatcher,
            BaseRateAnchorer,
            SentimentDriftTracker,
            AssumptionRegistry,
            UncertaintyQuantificationLayer,
            ExpertPerspectiveSimulator,
            InformationValueCalculator,
            ScenarioVersioningDiff,
            CascadeRiskScorer,
        ]
        outputs = []
        for agent_cls in agents:
            child_run, output = agent_cls(self.db, config=self.config, llm_client=self.llm_client).run(payload, parent_run_id=run_id)
            child_run_ids.append(child_run)
            outputs.append(output)
        red_team, analogies, base_rates, drift, assumptions, uncertainty, perspectives, info_value, diff, cascade = outputs
        analysis = AdvancedAnalysis(
            prediction_id=prediction.id,
            scenario_id=prediction.scenario_id,
            red_team=red_team.model_dump(mode="json"),
            expert_perspectives=perspectives.model_dump(mode="json")["perspectives"],
            uncertainty=uncertainty.model_dump(mode="json"),
            information_value=info_value.model_dump(mode="json")["suggestions"],
            cascade_risks=cascade.model_dump(mode="json")["risks"],
            scenario_diff=diff.model_dump(mode="json"),
        )
        self.db.add(analysis)
        self.db.flush()
        prediction.calibration_result = {**(prediction.calibration_result or {}), "advanced_intelligence": {"analysis_id": analysis.id, "uncertainty_score": uncertainty.uncertainty_score, "activation_recommendation": red_team.activation_recommendation}}
        if prediction.status == "active" and red_team.activation_recommendation == "needs_review":
            prediction.status = "draft"
        self.db.flush()
        AuditRepository(self.db).emit("advanced_analysis", analysis.id, "create", actor=self.agent_id, reason="Phase J advanced intelligence", after=row_to_dict(analysis))
        return AdvancedIntelligenceOutput(
            child_run_ids=child_run_ids,
            analysis_id=analysis.id,
            red_team=red_team,
            historical_analogies=analogies,
            base_rates=base_rates,
            sentiment_drift=drift,
            assumption_registry=assumptions,
            uncertainty=uncertainty,
            expert_perspectives=perspectives,
            information_value=info_value,
            scenario_diff=diff,
            cascade_risks=cascade,
        )
