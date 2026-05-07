from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from seldon.agents import AdvancedIntelligenceCoordinator, AdvancedIntelligenceInput
from seldon.api.app import create_app
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AdvancedAnalysis, AssumptionRecord, BaseRateEvidence, HistoricalAnalogy, ScenarioPrediction, SentimentDrift
from seldon.data.repositories import GraphRepository, KBRepository, ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def seed_phase_j(db):
    scenario = ScenarioRepository(db).create_scenario(
        name="Gold outlook",
        description="Six-month gold forecast",
        target_question="Will gold rise over the next 6 months?",
        time_horizon="6 months",
    )
    kb = KBRepository(db).create_entry(
        content="Past gold rallies followed rate-cut expectations, but surprise inflation can invalidate the easy-money assumption.",
        original_snippet="Historical episode: rate-cut hopes reversed after inflation surprise.",
        topics=["gold", "rates", "inflation"],
        entities=["gold", "Federal Reserve"],
        scenario_ids=[scenario.id],
        perspective_tags={"sentiment": 0.25, "confidence": 0.8},
    )
    graph = GraphRepository(db)
    rates = graph.create_node(
        name="Rate-cut expectations",
        type="policy",
        current_state="Markets expect easing.",
        kb_entry_ids=[kb.id],
        scenario_ids=[scenario.id],
        stability_score=0.35,
        importance_score=0.9,
    )
    gold = graph.create_node(
        name="Gold prices",
        type="metric",
        current_state="Prices are sensitive to real rates.",
        kb_entry_ids=[kb.id],
        scenario_ids=[scenario.id],
        stability_score=0.5,
        importance_score=0.85,
    )
    graph.create_edge(
        source_node_id=rates.id,
        target_node_id=gold.id,
        relationship_type="amplifies",
        strength=0.8,
        confidence=0.7,
        direction="positive",
        evidence_kb_ids=[kb.id],
        scenario_ids=[scenario.id],
    )
    repo = ScenarioRepository(db)
    prediction = repo.create_prediction(
        scenario_id=scenario.id,
        statement=scenario.target_question,
        timeframe="6 months",
        resolution_criteria="Resolve with spot gold price.",
        probabilities={"bull": 0.52, "base": 0.33, "bear": 0.15},
        confidence=0.62,
        key_drivers=[rates.id, gold.id],
        evidence_links=[kb.id],
        assumptions=["Rate cuts proceed", "No surprise inflation shock dominates."],
        status="active",
    )
    repo.update_prediction(
        prediction.id,
        reason="test refresh",
        probabilities={"bull": 0.58, "base": 0.27, "bear": 0.15},
        assumptions=["Rate cuts proceed", "No surprise inflation shock dominates.", "Dollar remains soft"],
    )
    return scenario, prediction


def test_advanced_intelligence_coordinator_persists_phase_j_artifacts(tmp_path):
    factory = session_factory()
    with factory() as db:
        with db.begin():
            _, prediction = seed_phase_j(db)
            run_id, output = AdvancedIntelligenceCoordinator(db, config=SeldonConfig(data_dir=tmp_path)).run(
                AdvancedIntelligenceInput(prediction_id=prediction.id, max_items=4)
            )

        assert run_id
        assert output.red_team.objections
        assert output.historical_analogies.analogy_ids
        assert output.base_rates.base_rate_ids
        assert output.sentiment_drift.topic_velocity
        assert len(output.assumption_registry.assumption_ids) == 3
        assert output.uncertainty.uncertainty_score > 0
        assert output.expert_perspectives.perspectives
        assert output.information_value.suggestions
        assert output.scenario_diff.current_version == 2
        assert output.scenario_diff.previous_version == 1
        assert output.cascade_risks.risks[0]["keystone"] is True
        assert db.get(AdvancedAnalysis, output.analysis_id) is not None
        assert db.scalar(select(HistoricalAnalogy).where(HistoricalAnalogy.prediction_id == prediction.id)) is not None
        assert db.scalar(select(BaseRateEvidence).where(BaseRateEvidence.prediction_id == prediction.id)) is not None
        assert db.scalar(select(SentimentDrift)) is not None
        assert db.scalar(select(AssumptionRecord).where(AssumptionRecord.prediction_id == prediction.id)) is not None
        refreshed = db.get(ScenarioPrediction, prediction.id)
        assert refreshed.calibration_result["advanced_intelligence"]["analysis_id"] == output.analysis_id


def test_advanced_intelligence_api_exposes_analysis(tmp_path):
    factory = session_factory()
    client = TestClient(create_app(SeldonConfig(data_dir=tmp_path), session_factory=factory))
    with factory() as db:
        with db.begin():
            _, prediction = seed_phase_j(db)
            prediction_id = prediction.id

    response = client.post(f"/predictions/{prediction_id}/run-advanced-intelligence", json={"max_items": 3})
    assert response.status_code == 202
    body = response.json()
    assert body["agent_id"] == "advanced_intelligence_coordinator"
    analysis_id = body["advanced_intelligence"]["analysis_id"]
    assert body["advanced_intelligence"]["red_team"]["strongest_counterargument"]
    assert body["advanced_intelligence"]["uncertainty"]["confidence_in_probabilities"] <= 1

    analysis = client.get(f"/advanced-analyses/{analysis_id}").json()
    assert analysis["prediction_id"] == prediction_id
    assert analysis["red_team"]["objections"]
    listed = client.get("/advanced-analyses", params={"prediction_id": prediction_id}).json()
    assert listed[0]["id"] == analysis_id
