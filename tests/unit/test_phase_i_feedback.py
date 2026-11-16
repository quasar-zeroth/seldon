from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from seldon.agents import FeedbackCoordinator, FeedbackInput, compute_calibration_summary
from seldon.api.app import create_app
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import FeedbackEntry, KBEntry, OutcomeCheck, ScenarioPrediction
from seldon.data.repositories import ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def seed_prediction(db):
    scenario = ScenarioRepository(db).create_scenario(
        name="Gold outlook",
        description="Six-month gold forecast",
        target_question="Will gold rise over the next 6 months?",
        time_horizon="6 months",
    )
    prediction = ScenarioRepository(db).create_prediction(
        scenario_id=scenario.id,
        statement=scenario.target_question,
        timeframe="6 months",
        resolution_criteria="Resolve using spot gold price in six months.",
        scenarios=[{"outcome": "Bull", "probability": 0.6}, {"outcome": "Base", "probability": 0.3}, {"outcome": "Bear", "probability": 0.1}],
        probabilities={"bull": 0.6, "base": 0.3, "bear": 0.1},
        confidence=0.72,
        assumptions=["Rate cuts proceed", "No unobserved shock dominates the listed key drivers."],
        status="active",
    )
    return scenario, prediction


def test_feedback_coordinator_resolves_prediction_records_outcome_and_calibration(tmp_path):
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario, prediction = seed_prediction(db)
            original_context = {"case_bounds": {"lower": {"value": 2000}, "upper": {"value": 6000}}, "graph_snapshot_id": "frozen-context"}
            prediction.calibration_result = original_context
            run_id, output = FeedbackCoordinator(db, config=SeldonConfig(data_dir=tmp_path)).run(
                FeedbackInput(
                    prediction_id=prediction.id,
                    actual_outcome="Gold fell after a surprise inflation shock.",
                    resolved_outcome_key="bear",
                    resolution_confidence=0.95,
                    source_references=["https://example.test/gold-resolution"],
                    missed_factors=["surprise inflation print"],
                    failed_assumptions=["No unobserved shock dominates the listed key drivers."],
                    notes="Inflation surprise dominated rate-cut expectations.",
                )
            )

        resolved = db.get(ScenarioPrediction, prediction.id)
        assert resolved is not None
        assert resolved.status == "resolved"
        assert resolved.outcome["resolved_outcome_key"] == "bear"
        assert resolved.calibration_result["probability_assigned"] == 0.1
        assert resolved.calibration_result["case_bounds"] == original_context["case_bounds"]
        assert resolved.calibration_result["graph_snapshot_id"] == "frozen-context"
        assert output.outcome_check.probability_assigned == 0.1
        assert output.root_cause.failed_assumptions == ["No unobserved shock dominates the listed key drivers."]
        assert output.calibration.resolved_predictions == 1
        assert output.calibration.brier_score is not None
        assert output.kb_correction_ids
        assert db.scalar(select(OutcomeCheck).where(OutcomeCheck.prediction_id == prediction.id)) is not None
        assert db.scalar(select(FeedbackEntry).where(FeedbackEntry.prediction_id == prediction.id)) is not None
        correction = db.get(KBEntry, output.kb_correction_ids[0])
        assert correction is not None and correction.source_type == "feedback_correction"
        assert run_id


def test_calibration_summary_buckets_resolved_predictions(tmp_path):
    factory = session_factory()
    with factory() as db:
        with db.begin():
            _, first = seed_prediction(db)
            _, second = seed_prediction(db)
            ScenarioRepository(db).update_prediction(second.id, confidence=0.35, reason="test confidence")
            FeedbackCoordinator(db, config=SeldonConfig(data_dir=tmp_path)).run(FeedbackInput(prediction_id=first.id, actual_outcome="Bull happened", resolved_outcome_key="bull", update_kb=False))
            FeedbackCoordinator(db, config=SeldonConfig(data_dir=tmp_path)).run(FeedbackInput(prediction_id=second.id, actual_outcome="Bear happened", resolved_outcome_key="bear", update_kb=False))

        summary = compute_calibration_summary(db)
        assert summary.resolved_predictions == 2
        assert summary.brier_score is not None and summary.brier_score > 0
        assert {bucket.bucket for bucket in summary.calibration_buckets} >= {"0.3-0.4", "0.7-0.8"}
        assert "feedback_coordinator" not in summary.per_agent or summary.per_agent["feedback_coordinator"]["runs"] >= 0


def test_feedback_api_runs_real_phase_i_workflow(tmp_path):
    factory = session_factory()
    client = TestClient(create_app(SeldonConfig(data_dir=tmp_path), session_factory=factory))
    scenario = client.post("/scenarios", json={"name": "Gold outlook", "target_question": "Will gold rise?", "time_horizon": "6 months"}).json()
    with factory() as db:
        with db.begin():
            prediction = ScenarioRepository(db).create_prediction(
                scenario_id=scenario["id"],
                statement="Will gold rise?",
                timeframe="6 months",
                resolution_criteria="Resolve later.",
                probabilities={"bull": 0.55, "base": 0.3, "bear": 0.15},
                confidence=0.66,
                assumptions=["Dollar weakens"],
                status="active",
            )
            prediction_id = prediction.id

    response = client.post(
        f"/scenarios/{scenario['id']}/run-feedback",
        json={
            "prediction_id": prediction_id,
            "actual_outcome": "Gold rose into the resolution date.",
            "resolved_outcome_key": "bull",
            "resolution_confidence": 0.9,
            "source_references": ["manual://resolution"],
        },
    )
    assert response.status_code == 202
    body = response.json()
    assert body["agent_id"] == "feedback_coordinator"
    assert body["status"] == "completed"
    assert body["feedback"]["outcome_check"]["resolved_outcome_key"] == "bull"

    prediction = client.get(f"/predictions/{prediction_id}").json()
    assert prediction["status"] == "resolved"
    assert prediction["outcome"]["actual_outcome"] == "Gold rose into the resolution date."
    assert client.get("/outcome-checks", params={"prediction_id": prediction_id}).json()[0]["resolved_outcome_key"] == "bull"
    summary = client.get("/calibration/summary").json()
    assert summary["resolved_predictions"] == 1
    assert summary["calibration_buckets"]


def test_prediction_resolution_endpoint_updates_calibration_and_can_queue_reprediction(tmp_path):
    factory = session_factory()
    client = TestClient(create_app(SeldonConfig(data_dir=tmp_path), session_factory=factory))
    scenario = client.post("/scenarios", json={"name": "Rates outlook", "target_question": "Will rates fall?", "time_horizon": "1 quarter"}).json()
    with factory() as db:
        with db.begin():
            prediction = ScenarioRepository(db).create_prediction(
                scenario_id=scenario["id"],
                statement="Will rates fall?",
                timeframe="1 quarter",
                resolution_criteria="Resolve using central bank decision.",
                probabilities={"fall": 0.7, "hold": 0.2, "rise": 0.1},
                confidence=0.74,
                assumptions=["Inflation continues cooling"],
                status="active",
            )
            prediction_id = prediction.id

    response = client.post(
        f"/predictions/{prediction_id}/resolve",
        json={
            "actual_outcome": "Rates were held after inflation reaccelerated.",
            "resolved_outcome_key": "hold",
            "resolution_confidence": 0.95,
            "missed_factors": ["inflation reacceleration"],
            "failed_assumptions": ["Inflation continues cooling"],
            "notes": "Feedback should invalidate the failed assumption and refresh the forecast.",
            "update_kb": True,
            "trigger_reprediction": True,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["feedback"]["outcome_check"]["resolved_outcome_key"] == "hold"
    assert body["reprediction_job"]["kind"] == "phase"
    assert body["reprediction_job"]["payload"]["phase"] == "prediction"

    prediction = client.get(f"/predictions/{prediction_id}").json()
    assert prediction["status"] == "resolved"
    assert prediction["calibration_result"]["probability_assigned"] == 0.2
    assert client.get("/feedback-entries").json()[0]["missed_factors"] == ["inflation reacceleration"]
    assert client.get("/calibration/summary").json()["resolved_predictions"] == 1
