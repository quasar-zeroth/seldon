"""Phase I feedback, resolution, and calibration agents.

These agents close the prediction loop: record observed outcomes, compare them
against forecast probabilities and assumptions, persist feedback corrections, and
compute calibration metrics over resolved predictions.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from seldon.data.models import AgentRun, ModelInvocation, OutcomeCheck, ScenarioPrediction
from seldon.data.repositories import AuditRepository, KBRepository, ScenarioRepository, row_to_dict

from .base import AgentBase


class FeedbackInput(BaseModel):
    prediction_id: str
    actual_outcome: str
    resolved_outcome_key: str
    resolution_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_references: list[str] = Field(default_factory=list)
    notes: str = ""
    missed_factors: list[str] = Field(default_factory=list)
    failed_assumptions: list[str] = Field(default_factory=list)
    graph_corrections: list[dict[str, Any]] = Field(default_factory=list)
    update_kb: bool = True


class OutcomeMonitorOutput(BaseModel):
    outcome_check_id: str
    prediction_id: str
    scenario_id: str | None = None
    resolved_outcome_key: str
    actual_outcome: str
    probability_assigned: float = Field(ge=0.0, le=1.0)
    resolution_confidence: float = Field(ge=0.0, le=1.0)
    matched_declared_outcome: bool


class RootCauseOutput(BaseModel):
    comparison: str
    missed_factors: list[str] = Field(default_factory=list)
    failed_assumptions: list[str] = Field(default_factory=list)
    lessons_learned: str = ""
    assumption_diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class CalibrationBucket(BaseModel):
    bucket: str
    count: int
    average_confidence: float
    average_probability_assigned: float
    empirical_accuracy: float
    brier_score: float


class CalibrationSummary(BaseModel):
    resolved_predictions: int
    brier_score: float | None = None
    log_score: float | None = None
    calibration_buckets: list[CalibrationBucket] = Field(default_factory=list)
    per_agent: dict[str, dict[str, Any]] = Field(default_factory=dict)
    per_model: dict[str, dict[str, Any]] = Field(default_factory=dict)


class FeedbackOutput(BaseModel):
    child_run_ids: list[str]
    feedback_entry_id: str
    outcome_check: OutcomeMonitorOutput
    root_cause: RootCauseOutput
    calibration: CalibrationSummary
    kb_correction_ids: list[str] = Field(default_factory=list)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def _prediction_probabilities(prediction: ScenarioPrediction) -> dict[str, float]:
    values: dict[str, float] = {}
    for key, value in (prediction.probabilities or {}).items():
        try:
            values[str(key)] = _clamp(float(value))
        except (TypeError, ValueError):
            continue
    return values


def _brier(probabilities: dict[str, float], observed_key: str) -> float:
    keys = set(probabilities) | {observed_key}
    return sum((probabilities.get(key, 0.0) - (1.0 if key == observed_key else 0.0)) ** 2 for key in keys)


def _log_score(probability: float) -> float:
    return -math.log(max(probability, 1e-12))


def _confidence_bucket(confidence: float) -> str:
    low = int(_clamp(confidence) * 10) / 10
    high = min(1.0, low + 0.1)
    return f"{low:.1f}-{high:.1f}"


class OutcomeMonitor(AgentBase[FeedbackInput, OutcomeMonitorOutput]):
    agent_id = "outcome_monitor"
    phase = "feedback"
    model_profile = "fast"

    def _run(self, payload: FeedbackInput, *, run_id: str, parent_run_id: str | None) -> OutcomeMonitorOutput:
        prediction = self.db.get(ScenarioPrediction, payload.prediction_id)
        if prediction is None:
            raise KeyError(f"scenario_prediction not found: {payload.prediction_id}")
        probabilities = _prediction_probabilities(prediction)
        probability_assigned = probabilities.get(payload.resolved_outcome_key, 0.0)
        matched = payload.resolved_outcome_key in probabilities
        row = OutcomeCheck(
            prediction_id=prediction.id,
            scenario_id=prediction.scenario_id,
            actual_outcome=payload.actual_outcome,
            resolved_outcome_key=payload.resolved_outcome_key,
            probability_assigned=probability_assigned,
            resolution_confidence=payload.resolution_confidence,
            source_references=payload.source_references,
            notes=payload.notes,
        )
        self.db.add(row)
        self.db.flush()
        AuditRepository(self.db).emit("outcome_check", row.id, "create", actor=self.agent_id, reason="Phase I outcome check", after=row_to_dict(row))
        return OutcomeMonitorOutput(
            outcome_check_id=row.id,
            prediction_id=prediction.id,
            scenario_id=prediction.scenario_id,
            resolved_outcome_key=payload.resolved_outcome_key,
            actual_outcome=payload.actual_outcome,
            probability_assigned=probability_assigned,
            resolution_confidence=payload.resolution_confidence,
            matched_declared_outcome=matched,
        )


class RootCauseAnalyzer(AgentBase[FeedbackInput, RootCauseOutput]):
    agent_id = "root_cause_analyzer"
    phase = "feedback"
    model_profile = "reasoning"

    def _run(self, payload: FeedbackInput, *, run_id: str, parent_run_id: str | None) -> RootCauseOutput:
        prediction = self.db.get(ScenarioPrediction, payload.prediction_id)
        if prediction is None:
            raise KeyError(f"scenario_prediction not found: {payload.prediction_id}")
        probabilities = _prediction_probabilities(prediction)
        assigned = probabilities.get(payload.resolved_outcome_key, 0.0)
        top_key = max(probabilities, key=probabilities.get) if probabilities else None
        failed = list(payload.failed_assumptions)
        declared_assumptions = list(prediction.assumptions or [])
        diagnostics = []
        for assumption in declared_assumptions:
            failed_flag = assumption in failed
            diagnostics.append({"assumption": assumption, "status": "failed" if failed_flag else "not_flagged", "evidence": payload.actual_outcome if failed_flag else None})
        if payload.resolved_outcome_key != top_key and assigned < 0.35:
            comparison = f"Outcome '{payload.resolved_outcome_key}' was underweighted at {assigned:.0%}; highest forecast was '{top_key}'."
        elif payload.resolved_outcome_key != top_key:
            comparison = f"Outcome '{payload.resolved_outcome_key}' was plausible at {assigned:.0%}, but was not the top forecast."
        else:
            comparison = f"Top forecast matched observed outcome '{payload.resolved_outcome_key}' with probability {assigned:.0%}."
        lessons = payload.notes or "Record outcome evidence, review failed assumptions, and update future graph/KB weights where needed."
        if payload.missed_factors:
            lessons = f"Missed factors to incorporate next time: {', '.join(payload.missed_factors)}. {lessons}"
        return RootCauseOutput(comparison=comparison, missed_factors=payload.missed_factors, failed_assumptions=failed, lessons_learned=lessons, assumption_diagnostics=diagnostics)


class CalibrationInput(BaseModel):
    scenario_id: str | None = None


class CalibrationTracker(AgentBase[CalibrationInput, CalibrationSummary]):
    agent_id = "calibration_tracker"
    phase = "feedback"
    model_profile = "fast"

    def _run(self, payload: CalibrationInput, *, run_id: str, parent_run_id: str | None) -> CalibrationSummary:
        return compute_calibration_summary(self.db)


class FeedbackCoordinator(AgentBase[FeedbackInput, FeedbackOutput]):
    agent_id = "feedback_coordinator"
    phase = "feedback"
    model_profile = "reasoning"

    def _run(self, payload: FeedbackInput, *, run_id: str, parent_run_id: str | None) -> FeedbackOutput:
        prediction = self.db.get(ScenarioPrediction, payload.prediction_id)
        if prediction is None:
            raise KeyError(f"scenario_prediction not found: {payload.prediction_id}")
        child_run_ids: list[str] = []
        monitor_run, outcome = OutcomeMonitor(self.db, config=self.config, llm_client=self.llm_client).run(payload, parent_run_id=run_id)
        child_run_ids.append(monitor_run)
        root_run, root_cause = RootCauseAnalyzer(self.db, config=self.config, llm_client=self.llm_client).run(payload, parent_run_id=run_id)
        child_run_ids.append(root_run)

        probabilities = _prediction_probabilities(prediction)
        calibration_result = {
            "brier_score": _brier(probabilities, payload.resolved_outcome_key),
            "log_score": _log_score(outcome.probability_assigned),
            "probability_assigned": outcome.probability_assigned,
            "resolved_outcome_key": payload.resolved_outcome_key,
            "resolution_confidence": payload.resolution_confidence,
        }
        kb_ids: list[str] = []
        if payload.update_kb and (root_cause.missed_factors or root_cause.failed_assumptions or root_cause.lessons_learned):
            kb_repo = KBRepository(self.db)
            content = "Feedback correction for resolved prediction: " + root_cause.lessons_learned
            if root_cause.failed_assumptions:
                content += " Failed assumptions: " + "; ".join(root_cause.failed_assumptions)
            correction = kb_repo.create_entry(
                actor=self.agent_id,
                reason="Phase I feedback correction",
                content=content,
                original_snippet=payload.actual_outcome,
                source_type="feedback_correction",
                source_name="Outcome feedback",
                scenario_ids=[prediction.scenario_id] if prediction.scenario_id else [],
                topics=["feedback", "calibration"],
                entities=[],
                perspective_tags={"confidence": payload.resolution_confidence},
            )
            kb_ids.append(correction.id)

        repo = ScenarioRepository(self.db)
        updated_outcome = {
            "actual_outcome": payload.actual_outcome,
            "resolved_outcome_key": payload.resolved_outcome_key,
            "outcome_check_id": outcome.outcome_check_id,
            "source_references": payload.source_references,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        repo.update_prediction(prediction.id, actor=self.agent_id, reason="Phase I prediction resolution", status="resolved", outcome=updated_outcome, calibration_result=calibration_result)
        feedback = repo.record_feedback(
            actor=self.agent_id,
            reason="Phase I feedback and learning",
            scenario_id=prediction.scenario_id,
            prediction_id=prediction.id,
            actual_outcome=payload.actual_outcome,
            comparison=root_cause.comparison,
            missed_factors=root_cause.missed_factors,
            graph_corrections=payload.graph_corrections,
            lessons_learned=root_cause.lessons_learned,
        )
        calibration_run, calibration = CalibrationTracker(self.db, config=self.config, llm_client=self.llm_client).run(CalibrationInput(scenario_id=prediction.scenario_id), parent_run_id=run_id)
        child_run_ids.append(calibration_run)
        AuditRepository(self.db).emit("scenario_prediction", prediction.id, "resolved", actor=self.agent_id, reason="Phase I feedback loop completed", after={"feedback_entry_id": feedback.id, "outcome_check_id": outcome.outcome_check_id, "kb_correction_ids": kb_ids})
        return FeedbackOutput(child_run_ids=child_run_ids, feedback_entry_id=feedback.id, outcome_check=outcome, root_cause=root_cause, calibration=calibration, kb_correction_ids=kb_ids)


def compute_calibration_summary(db: Any) -> CalibrationSummary:
    checks = list(db.scalars(select(OutcomeCheck).order_by(OutcomeCheck.checked_at)))
    if not checks:
        return CalibrationSummary(resolved_predictions=0)
    prediction_ids = {check.prediction_id for check in checks}
    predictions = {p.id: p for p in db.scalars(select(ScenarioPrediction).where(ScenarioPrediction.id.in_(prediction_ids)))}
    briers: list[float] = []
    logs: list[float] = []
    bucket_rows: dict[str, list[tuple[OutcomeCheck, ScenarioPrediction, float]]] = {}
    for check in checks:
        prediction = predictions.get(check.prediction_id)
        if prediction is None:
            continue
        probs = _prediction_probabilities(prediction)
        brier = _brier(probs, check.resolved_outcome_key)
        briers.append(brier)
        logs.append(_log_score(check.probability_assigned))
        bucket_rows.setdefault(_confidence_bucket(prediction.confidence), []).append((check, prediction, brier))
    buckets: list[CalibrationBucket] = []
    for bucket, rows in sorted(bucket_rows.items()):
        count = len(rows)
        buckets.append(CalibrationBucket(
            bucket=bucket,
            count=count,
            average_confidence=sum(pred.confidence for _, pred, _ in rows) / count,
            average_probability_assigned=sum(check.probability_assigned for check, _, _ in rows) / count,
            empirical_accuracy=sum(1.0 if check.probability_assigned >= 0.5 else 0.0 for check, _, _ in rows) / count,
            brier_score=sum(brier for _, _, brier in rows) / count,
        ))
    per_agent: dict[str, dict[str, Any]] = {}
    for run in db.scalars(select(AgentRun).where(AgentRun.agent_id.in_(["prediction_coordinator", "scenario_synthesizer"]))):
        per_agent.setdefault(run.agent_id, {"runs": 0})["runs"] += 1
    per_model: dict[str, dict[str, Any]] = {}
    for invocation in db.scalars(select(ModelInvocation)):
        per_model.setdefault(invocation.model, {"invocations": 0, "ok": 0})
        per_model[invocation.model]["invocations"] += 1
        per_model[invocation.model]["ok"] += 1 if invocation.ok else 0
    return CalibrationSummary(
        resolved_predictions=len(checks),
        brier_score=sum(briers) / len(briers) if briers else None,
        log_score=sum(logs) / len(logs) if logs else None,
        calibration_buckets=buckets,
        per_agent=per_agent,
        per_model=per_model,
    )
