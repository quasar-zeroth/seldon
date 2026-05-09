"""Phase H prediction synthesis agents.

The Phase H implementation consumes the DB-backed KB, ERG nodes, and ERG
relationships produced by Phases E-G, then writes versioned scenario predictions
with provenance, probability history, drivers, assumptions, and traversal logs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from seldon.data.models import ERGEdge, ERGNode, Scenario, ScenarioPrediction, ScenarioVersion
from seldon.data.repositories import AuditRepository, GraphRepository, MarkdownExporter, ScenarioRepository

from .base import AgentBase

ForecastDirection = Literal["up", "down", "flat", "uncertain"]
StabilityLabel = Literal["stable", "moderately_stable", "unstable"]


class PredictionInput(BaseModel):
    scenario_id: str
    question: str
    timeframe: str = ""
    max_driver_nodes: int = Field(default=8, ge=1, le=50)
    min_confidence_to_activate: float = Field(default=0.35, ge=0.0, le=1.0)
    export_markdown: bool = True


class NodeStateForecast(BaseModel):
    node_id: str
    node_name: str
    forecast: str
    direction: ForecastDirection = "uncertain"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    time_horizon: str = ""
    drivers: list[str] = Field(default_factory=list)


class NodeForecastInput(BaseModel):
    scenario_id: str
    node_id: str
    time_horizon: str = ""


class TraversalStep(BaseModel):
    source_node_id: str
    target_node_id: str
    edge_id: str
    relationship_type: str
    direction: str
    influence: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class GraphTraversalInput(BaseModel):
    scenario_id: str
    node_forecasts: list[NodeStateForecast]


class GraphTraversalOutput(BaseModel):
    traversal_log: list[TraversalStep]
    aggregate_signal: float = Field(ge=-1.0, le=1.0)
    visited_node_ids: list[str] = Field(default_factory=list)


class InstabilityHotspot(BaseModel):
    node_id: str | None = None
    edge_id: str | None = None
    severity: float = Field(ge=0.0, le=1.0)
    reason: str
    cascade_risk: float = Field(default=0.0, ge=0.0, le=1.0)


class InstabilityInput(BaseModel):
    scenario_id: str
    traversal: GraphTraversalOutput


class InstabilityOutput(BaseModel):
    hotspots: list[InstabilityHotspot]
    overall_instability: float = Field(ge=0.0, le=1.0)


class SynthesizedOutcome(BaseModel):
    outcome: str
    probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    key_drivers: list[str] = Field(default_factory=list)
    key_assumptions: list[str] = Field(default_factory=list)
    stability: StabilityLabel = "moderately_stable"
    reasoning_trace: str = ""


class ScenarioSynthesisInput(BaseModel):
    scenario_id: str
    question: str
    timeframe: str = ""
    node_forecasts: list[NodeStateForecast]
    traversal: GraphTraversalOutput
    instability: InstabilityOutput


class ScenarioSynthesisOutput(BaseModel):
    statement: str
    scope: str = ""
    timeframe: str = ""
    resolution_criteria: str
    outcomes: list[SynthesizedOutcome]
    probabilities: dict[str, float]
    confidence: float = Field(ge=0.0, le=1.0)
    key_drivers: list[str] = Field(default_factory=list)
    evidence_links: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def probabilities_sum_to_one(self) -> "ScenarioSynthesisOutput":
        total = sum(self.probabilities.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"scenario probabilities must sum to 1.0, got {total:.3f}")
        return self


class PredictionOutput(BaseModel):
    child_run_ids: list[str]
    prediction_id: str
    version: int
    node_forecasts: list[NodeStateForecast]
    traversal: GraphTraversalOutput
    instability: InstabilityOutput
    synthesis: ScenarioSynthesisOutput
    markdown_path: str | None = None


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def _signed_direction(direction: str, relationship_type: str) -> float:
    if direction == "positive":
        return 1.0
    if direction == "negative":
        return -1.0
    if relationship_type in {"amplifies", "enables", "causes"}:
        return 0.5
    if relationship_type in {"dampens", "opposes", "constrains"}:
        return -0.5
    return 0.0


def _normalise_probabilities(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in values.values()) or 1.0
    rounded = {k: round(max(0.0, v) / total, 4) for k, v in values.items()}
    drift = round(1.0 - sum(rounded.values()), 4)
    if rounded:
        largest = max(rounded, key=rounded.get)
        rounded[largest] = round(rounded[largest] + drift, 4)
    return rounded


SCENARIO_SYNTHESIZER_SYSTEM = """You are The Seldon Project's Scenario Synthesizer.
Synthesize 3-7 coherent, mutually distinct forecast scenarios from node forecasts, traversal results, and instability analysis.
Probabilities must sum to 1.0, confidence must reflect evidence quality, and assumptions/drivers must be auditable.
Do not force bull/base/bear labels unless they are the best natural scenario names. Return only JSON matching the ScenarioSynthesisOutput schema."""


class NodeStatePredictor(AgentBase[NodeForecastInput, NodeStateForecast]):
    agent_id = "node_state_predictor"
    phase = "prediction"
    model_profile = "fast"

    def _run(self, payload: NodeForecastInput, *, run_id: str, parent_run_id: str | None) -> NodeStateForecast:
        graph = GraphRepository(self.db)
        node = graph.get_node(payload.node_id)
        if node is None:
            raise KeyError(f"erg_node not found: {payload.node_id}")
        edges = [edge for edge in graph.list_edges(node_id=node.id) if payload.scenario_id in (edge.scenario_ids or [])]
        evidence_count = len(node.kb_entry_ids or [])
        confidence = _clamp(0.35 + 0.25 * node.importance_score + 0.08 * evidence_count + 0.05 * len(edges))
        signal = sum(_signed_direction(edge.direction, edge.relationship_type) * edge.strength * edge.confidence for edge in edges)
        if signal > 0.2:
            direction: ForecastDirection = "up"
        elif signal < -0.2:
            direction = "down"
        elif edges:
            direction = "flat"
        else:
            direction = "uncertain"
        state = node.current_state or node.description or "No current state recorded."
        forecast = f"{node.name} is expected to be {direction} over {payload.time_horizon or 'the scenario horizon'}; current evidence says: {state[:220]}"
        return NodeStateForecast(node_id=node.id, node_name=node.name, forecast=forecast, direction=direction, confidence=confidence, time_horizon=payload.time_horizon, drivers=[edge.id for edge in edges[:5]])


class GraphTraversalSimulator(AgentBase[GraphTraversalInput, GraphTraversalOutput]):
    agent_id = "graph_traversal_simulator"
    phase = "prediction"
    model_profile = "balanced"

    def _run(self, payload: GraphTraversalInput, *, run_id: str, parent_run_id: str | None) -> GraphTraversalOutput:
        forecast_ids = {forecast.node_id for forecast in payload.node_forecasts}
        forecast_direction = {forecast.node_id: forecast.direction for forecast in payload.node_forecasts}
        steps: list[TraversalStep] = []
        visited: set[str] = set(forecast_ids)
        aggregate = 0.0
        graph = GraphRepository(self.db)
        edges = [edge for edge in graph.list_edges() if payload.scenario_id in (edge.scenario_ids or []) and (edge.source_node_id in forecast_ids or edge.target_node_id in forecast_ids)]
        for edge in edges:
            source_signal = 1.0 if forecast_direction.get(edge.source_node_id) == "up" else -1.0 if forecast_direction.get(edge.source_node_id) == "down" else 0.0
            relation_signal = _signed_direction(edge.direction, edge.relationship_type)
            influence = _clamp(source_signal * relation_signal * edge.strength * edge.confidence, -1.0, 1.0)
            aggregate += influence
            visited.update([edge.source_node_id, edge.target_node_id])
            steps.append(TraversalStep(source_node_id=edge.source_node_id, target_node_id=edge.target_node_id, edge_id=edge.id, relationship_type=edge.relationship_type, direction=edge.direction, influence=influence, confidence=edge.confidence, rationale=edge.description[:240]))
        divisor = max(1, len(steps))
        return GraphTraversalOutput(traversal_log=steps, aggregate_signal=_clamp(aggregate / divisor, -1.0, 1.0), visited_node_ids=sorted(visited))


class InstabilityAnalyzer(AgentBase[InstabilityInput, InstabilityOutput]):
    agent_id = "instability_analyzer"
    phase = "prediction"
    model_profile = "reasoning"

    def _run(self, payload: InstabilityInput, *, run_id: str, parent_run_id: str | None) -> InstabilityOutput:
        graph = GraphRepository(self.db)
        nodes = [node for node in graph.list_nodes() if payload.scenario_id in (node.scenario_ids or [])]
        edges = [edge for edge in graph.list_edges() if payload.scenario_id in (edge.scenario_ids or [])]
        hotspots: list[InstabilityHotspot] = []
        for node in nodes:
            evidence_gap = 1.0 if not node.kb_entry_ids else 0.0
            severity = _clamp((1.0 - node.stability_score) * 0.7 + evidence_gap * 0.3)
            if severity >= 0.45:
                connected = len(graph.list_edges(node_id=node.id))
                hotspots.append(InstabilityHotspot(node_id=node.id, severity=severity, reason="Low node stability and/or weak evidence coverage", cascade_risk=_clamp(connected / max(1, len(edges)))))
        for edge in edges:
            if edge.strength >= 0.7 and edge.confidence < 0.45:
                hotspots.append(InstabilityHotspot(edge_id=edge.id, severity=_clamp(edge.strength * (1 - edge.confidence)), reason="Strong relationship has low confidence", cascade_risk=edge.strength))
        traversal_volatility = sum(abs(step.influence) for step in payload.traversal.traversal_log) / max(1, len(payload.traversal.traversal_log))
        overall = _clamp((sum(h.severity for h in hotspots) / max(1, len(hotspots))) * 0.7 + traversal_volatility * 0.3)
        hotspots.sort(key=lambda h: h.severity, reverse=True)
        return InstabilityOutput(hotspots=hotspots[:10], overall_instability=overall)


class ScenarioSynthesizer(AgentBase[ScenarioSynthesisInput, ScenarioSynthesisOutput]):
    agent_id = "scenario_synthesizer"
    phase = "prediction"
    model_profile = "reasoning"

    def _run(self, payload: ScenarioSynthesisInput, *, run_id: str, parent_run_id: str | None) -> ScenarioSynthesisOutput:
        scenario = self.db.get(Scenario, payload.scenario_id)
        if scenario is None:
            raise KeyError(f"scenario not found: {payload.scenario_id}")
        if self.llm_client is not None:
            try:
                result = self.llm_complete_json(
                    [
                        {
                            "role": "user",
                            "content": (
                                "Synthesize forecast scenarios from this prediction context.\n"
                                f"Scenario: {scenario.name}\nQuestion: {payload.question}\nTimeframe: {payload.timeframe or scenario.time_horizon}\n"
                                f"Node forecasts: {[f.model_dump(mode='json') for f in payload.node_forecasts]}\n"
                                f"Traversal: {payload.traversal.model_dump(mode='json')}\n"
                                f"Instability: {payload.instability.model_dump(mode='json')}"
                            ),
                        }
                    ],
                    run_id=run_id,
                    system=SCENARIO_SYNTHESIZER_SYSTEM,
                    schema=ScenarioSynthesisOutput,
                    repair_retries=1,
                    min_confidence=0.4,
                    escalation_profiles=("reasoning",),
                )
                return ScenarioSynthesisOutput.model_validate(result)
            except Exception as exc:
                self.runs.add_message(run_id, "system", "ScenarioSynthesizer LLM path failed; using deterministic fallback.", payload={"error": str(exc)})

        signal = payload.traversal.aggregate_signal
        instability = payload.instability.overall_instability
        bull = 0.33 + max(0.0, signal) * 0.22 - instability * 0.08
        bear = 0.33 + max(0.0, -signal) * 0.22 + instability * 0.10
        base = 1.0 - bull - bear
        probabilities = _normalise_probabilities({"bull": bull, "base": base, "bear": bear})
        confidence = _clamp(0.72 - instability * 0.35 + min(0.18, len(payload.node_forecasts) * 0.02))
        driver_ids = [forecast.node_id for forecast in sorted(payload.node_forecasts, key=lambda f: f.confidence, reverse=True)[:5]]
        evidence_ids: set[str] = set()
        for node_id in driver_ids:
            node = self.db.get(ERGNode, node_id)
            if node is not None:
                evidence_ids.update(node.kb_entry_ids or [])
        for step in payload.traversal.traversal_log:
            edge = self.db.get(ERGEdge, step.edge_id)
            if edge is not None:
                evidence_ids.update(edge.evidence_kb_ids or [])
        stability: StabilityLabel = "unstable" if instability > 0.65 else "moderately_stable" if instability > 0.35 else "stable"
        assumptions = [
            "Current KB evidence remains materially valid through the forecast horizon.",
            "Persisted ERG relationships are directionally correct enough for traversal simulation.",
            "No unobserved shock dominates the listed key drivers.",
        ]
        outcomes = [
            SynthesizedOutcome(outcome=f"Bull case for: {scenario.target_question}", probability=probabilities["bull"], confidence=confidence, key_drivers=driver_ids, key_assumptions=assumptions[:2], stability=stability, reasoning_trace=f"Positive graph signal={signal:.2f}; instability={instability:.2f}."),
            SynthesizedOutcome(outcome=f"Base case for: {scenario.target_question}", probability=probabilities["base"], confidence=confidence, key_drivers=driver_ids, key_assumptions=assumptions, stability=stability, reasoning_trace="Most evidence remains balanced; no single driver overwhelms the graph."),
            SynthesizedOutcome(outcome=f"Bear case for: {scenario.target_question}", probability=probabilities["bear"], confidence=confidence, key_drivers=driver_ids, key_assumptions=assumptions[:2], stability=stability, reasoning_trace=f"Negative/cascade risk from graph signal={signal:.2f}; instability={instability:.2f}."),
        ]
        return ScenarioSynthesisOutput(
            statement=scenario.target_question,
            scope=scenario.description or scenario.name,
            timeframe=payload.timeframe or scenario.time_horizon,
            resolution_criteria=f"Resolve after {payload.timeframe or scenario.time_horizon or 'the stated horizon'} using the observable outcome of: {scenario.target_question}",
            outcomes=outcomes,
            probabilities=probabilities,
            confidence=confidence,
            key_drivers=driver_ids,
            evidence_links=sorted(evidence_ids),
            assumptions=assumptions,
        )


class PredictionCoordinator(AgentBase[PredictionInput, PredictionOutput]):
    agent_id = "prediction_coordinator"
    phase = "prediction"
    model_profile = "reasoning"

    @classmethod
    def input_from_scenario(cls, scenario: Scenario, *, max_driver_nodes: int = 8, min_confidence_to_activate: float = 0.35, export_markdown: bool = True) -> PredictionInput:
        return PredictionInput(scenario_id=scenario.id, question=scenario.target_question, timeframe=scenario.time_horizon, max_driver_nodes=max_driver_nodes, min_confidence_to_activate=min_confidence_to_activate, export_markdown=export_markdown)

    def _run(self, payload: PredictionInput, *, run_id: str, parent_run_id: str | None) -> PredictionOutput:
        scenario = self.db.get(Scenario, payload.scenario_id)
        if scenario is None:
            raise KeyError(f"scenario not found: {payload.scenario_id}")
        nodes = [node for node in GraphRepository(self.db).list_nodes() if payload.scenario_id in (node.scenario_ids or [])]
        nodes.sort(key=lambda node: (node.importance_score, len(node.kb_entry_ids or [])), reverse=True)
        driver_nodes = nodes[: payload.max_driver_nodes]
        child_run_ids: list[str] = []
        forecasts: list[NodeStateForecast] = []
        for node in driver_nodes:
            n_run, forecast = NodeStatePredictor(self.db, config=self.config, llm_client=self.llm_client).run(NodeForecastInput(scenario_id=payload.scenario_id, node_id=node.id, time_horizon=payload.timeframe), parent_run_id=run_id)
            child_run_ids.append(n_run)
            forecasts.append(forecast)
        t_run, traversal = GraphTraversalSimulator(self.db, config=self.config, llm_client=self.llm_client).run(GraphTraversalInput(scenario_id=payload.scenario_id, node_forecasts=forecasts), parent_run_id=run_id)
        child_run_ids.append(t_run)
        i_run, instability = InstabilityAnalyzer(self.db, config=self.config, llm_client=self.llm_client).run(InstabilityInput(scenario_id=payload.scenario_id, traversal=traversal), parent_run_id=run_id)
        child_run_ids.append(i_run)
        s_run, synthesis = ScenarioSynthesizer(self.db, config=self.config, llm_client=self.llm_client).run(ScenarioSynthesisInput(scenario_id=payload.scenario_id, question=payload.question, timeframe=payload.timeframe, node_forecasts=forecasts, traversal=traversal, instability=instability), parent_run_id=run_id)
        child_run_ids.append(s_run)

        repo = ScenarioRepository(self.db)
        existing = self.db.scalar(select(ScenarioPrediction).where(ScenarioPrediction.scenario_id == payload.scenario_id, ScenarioPrediction.status.in_(["draft", "active", "monitoring"])).order_by(ScenarioPrediction.updated_at.desc()))
        now = datetime.now(timezone.utc).isoformat()
        probability_history = [{"date": now, **synthesis.probabilities, "trigger": "Phase H prediction synthesis"}]
        status = "active" if synthesis.confidence >= payload.min_confidence_to_activate else "draft"
        values: dict[str, Any] = {
            "scenario_id": payload.scenario_id,
            "statement": synthesis.statement,
            "scope": synthesis.scope,
            "timeframe": synthesis.timeframe,
            "resolution_criteria": synthesis.resolution_criteria,
            "scenarios": [outcome.model_dump(mode="json") for outcome in synthesis.outcomes],
            "probabilities": synthesis.probabilities,
            "confidence": synthesis.confidence,
            "key_drivers": synthesis.key_drivers,
            "evidence_links": synthesis.evidence_links,
            "assumptions": synthesis.assumptions,
            "status": status,
        }
        if existing is None:
            prediction = repo.create_prediction(actor=self.agent_id, reason="Phase H prediction synthesis", probability_history=probability_history, **values)
            version = 1
        else:
            history = [*(existing.probability_history or []), *probability_history]
            prediction = repo.update_prediction(existing.id, actor=self.agent_id, reason="Phase H prediction refresh", probability_history=history, **values)
            version = self.db.scalar(select(ScenarioVersion.version).where(ScenarioVersion.scenario_prediction_id == prediction.id).order_by(ScenarioVersion.version.desc())) or 1
        markdown_path = None
        if payload.export_markdown:
            markdown_path = str(MarkdownExporter(self.config.data_dir / "exports").export_scenario(prediction))
        AuditRepository(self.db).emit("scenario", payload.scenario_id, "prediction_synthesis", actor=self.agent_id, reason="Phase H produced versioned prediction", after={"prediction_id": prediction.id, "version": version, "child_run_ids": child_run_ids})
        return PredictionOutput(child_run_ids=child_run_ids, prediction_id=prediction.id, version=version, node_forecasts=forecasts, traversal=traversal, instability=instability, synthesis=synthesis, markdown_path=markdown_path)
