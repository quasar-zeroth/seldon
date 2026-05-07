from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from seldon.agents import PredictionCoordinator, ScenarioSynthesisOutput, SynthesizedOutcome
from seldon.api.app import create_app
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AgentRun, ScenarioPrediction, ScenarioVersion
from seldon.data.repositories import GraphRepository, KBRepository, ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def seed_phase_h_graph(db):
    scenario = ScenarioRepository(db).create_scenario(
        name="Gold outlook",
        description="Six-month gold forecast",
        target_question="Will gold rise over the next 6 months?",
        time_horizon="6 months",
    )
    kb = KBRepository(db).create_entry(
        content="Federal Reserve rate cuts can boost gold demand and lift gold prices over coming months.",
        topics=["gold", "rates"],
        entities=["Federal Reserve", "gold demand", "gold prices"],
        scenario_ids=[scenario.id],
        perspective_tags={"confidence": 0.85},
    )
    graph = GraphRepository(db)
    fed = graph.create_node(
        name="Federal Reserve policy",
        type="policy",
        description="US monetary policy stance",
        current_state="Rate cut expectations are rising.",
        kb_entry_ids=[kb.id],
        scenario_ids=[scenario.id],
        stability_score=0.55,
        importance_score=0.9,
    )
    demand = graph.create_node(
        name="Gold demand",
        type="metric",
        description="Investment and central bank demand for gold",
        current_state="Demand is supported by easing expectations.",
        kb_entry_ids=[kb.id],
        scenario_ids=[scenario.id],
        stability_score=0.6,
        importance_score=0.7,
    )
    price = graph.create_node(
        name="Gold prices",
        type="metric",
        description="Spot gold price level",
        current_state="Prices respond to demand and real-rate expectations.",
        kb_entry_ids=[kb.id],
        scenario_ids=[scenario.id],
        stability_score=0.3,
        importance_score=0.8,
    )
    edge_1 = graph.create_edge(
        source_node_id=fed.id,
        target_node_id=demand.id,
        relationship_type="amplifies",
        description="Expected rate cuts can boost investment demand for gold.",
        strength=0.8,
        confidence=0.75,
        direction="positive",
        evidence_kb_ids=[kb.id],
        scenario_ids=[scenario.id],
    )
    edge_2 = graph.create_edge(
        source_node_id=demand.id,
        target_node_id=price.id,
        relationship_type="causes",
        description="Higher demand tends to lift gold prices.",
        strength=0.75,
        confidence=0.7,
        direction="positive",
        evidence_kb_ids=[kb.id],
        scenario_ids=[scenario.id],
    )
    return scenario, kb, [fed, demand, price], [edge_1, edge_2]


def test_scenario_synthesis_probability_validation_rejects_bad_totals():
    outcome = SynthesizedOutcome(outcome="x", probability=0.5, confidence=0.5)
    try:
        ScenarioSynthesisOutput(
            statement="Bad probabilities",
            resolution_criteria="test",
            outcomes=[outcome],
            probabilities={"bull": 0.7, "base": 0.2, "bear": 0.2},
            confidence=0.5,
        )
    except ValueError as exc:
        assert "sum to 1.0" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected probability validation failure")


def test_prediction_coordinator_creates_versioned_prediction_with_provenance(tmp_path):
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario, kb, nodes, edges = seed_phase_h_graph(db)
            run_id, output = PredictionCoordinator(db, config=SeldonConfig(data_dir=tmp_path)).run(
                PredictionCoordinator.input_from_scenario(scenario, max_driver_nodes=3)
            )

        run = db.get(AgentRun, run_id)
        prediction = db.get(ScenarioPrediction, output.prediction_id)
        assert run is not None and run.status == "completed"
        assert run.phase == "prediction"
        assert prediction is not None
        assert prediction.scenario_id == scenario.id
        assert prediction.status == "active"
        assert abs(sum(prediction.probabilities.values()) - 1.0) < 0.01
        assert prediction.key_drivers
        assert kb.id in prediction.evidence_links
        assert prediction.probability_history
        assert output.traversal.traversal_log
        assert output.instability.hotspots
        assert output.markdown_path and (tmp_path / "exports" / "scenarios" / f"{prediction.id}.md").exists()
        assert db.scalar(select(ScenarioVersion).where(ScenarioVersion.scenario_prediction_id == prediction.id)) is not None


def test_prediction_coordinator_refreshes_existing_prediction_and_appends_history(tmp_path):
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario, *_ = seed_phase_h_graph(db)
            _, first = PredictionCoordinator(db, config=SeldonConfig(data_dir=tmp_path)).run(
                PredictionCoordinator.input_from_scenario(scenario, max_driver_nodes=2, export_markdown=False)
            )
            _, second = PredictionCoordinator(db, config=SeldonConfig(data_dir=tmp_path)).run(
                PredictionCoordinator.input_from_scenario(scenario, max_driver_nodes=2, export_markdown=False)
            )

        assert first.prediction_id == second.prediction_id
        prediction = db.get(ScenarioPrediction, first.prediction_id)
        assert prediction is not None
        assert len(prediction.probability_history) == 2
        versions = list(db.scalars(select(ScenarioVersion).where(ScenarioVersion.scenario_prediction_id == prediction.id).order_by(ScenarioVersion.version)))
        assert [version.version for version in versions] == [1, 2]
        assert second.version == 2


def test_prediction_api_runs_real_phase_h_workflow_and_exposes_predictions(tmp_path):
    factory = session_factory()
    client = TestClient(create_app(SeldonConfig(data_dir=tmp_path), session_factory=factory))
    scenario = client.post(
        "/scenarios",
        json={"name": "Gold outlook", "target_question": "Will gold rise over the next 6 months?", "time_horizon": "6 months"},
    ).json()
    kb = client.post(
        "/kb/entries",
        json={
            "content": "Rate cuts can boost gold demand and lift gold prices.",
            "topics": ["gold", "rates"],
            "entities": ["rate cuts", "gold demand", "gold prices"],
            "scenario_ids": [scenario["id"]],
            "perspective_tags": {"confidence": 0.8},
        },
    ).json()
    fed = client.post(
        "/graph/nodes",
        json={"name": "Rate cuts", "type": "policy", "current_state": "Cuts are increasingly expected.", "kb_entry_ids": [kb["id"]], "scenario_ids": [scenario["id"]], "importance_score": 0.9, "stability_score": 0.5},
    ).json()
    price = client.post(
        "/graph/nodes",
        json={"name": "Gold prices", "type": "metric", "current_state": "Prices track demand.", "kb_entry_ids": [kb["id"]], "scenario_ids": [scenario["id"]], "importance_score": 0.8, "stability_score": 0.55},
    ).json()
    client.post(
        "/graph/edges",
        json={
            "source_node_id": fed["id"],
            "target_node_id": price["id"],
            "relationship_type": "amplifies",
            "description": "Rate cuts may amplify gold prices through demand.",
            "strength": 0.8,
            "confidence": 0.75,
            "direction": "positive",
            "evidence_kb_ids": [kb["id"]],
            "scenario_ids": [scenario["id"]],
        },
    )

    response = client.post(f"/scenarios/{scenario['id']}/run-prediction", json={"max_driver_nodes": 2})
    assert response.status_code == 202
    body = response.json()
    assert body["agent_id"] == "prediction_coordinator"
    assert body["status"] == "completed"
    prediction_id = body["prediction"]["prediction_id"]
    assert body["prediction"]["synthesis"]["probabilities"]["bull"] > 0

    prediction = client.get(f"/predictions/{prediction_id}").json()
    assert prediction["scenario_id"] == scenario["id"]
    assert prediction["evidence_links"] == [kb["id"]]
    assert client.get("/predictions", params={"scenario_id": scenario["id"]}).json()[0]["id"] == prediction_id

    runs = client.get("/runs").json()
    assert {run["agent_id"] for run in runs} >= {
        "prediction_coordinator",
        "node_state_predictor",
        "graph_traversal_simulator",
        "instability_analyzer",
        "scenario_synthesizer",
    }
