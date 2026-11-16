from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from seldon.agents import PredictionCoordinator, ScenarioSynthesisOutput, SynthesizedOutcome
from seldon.api.app import create_app
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AgentRun, BaseRateEvidence, ScenarioPrediction, ScenarioVersion
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


def test_python_predictor_enforces_workspace_dependency_depth(tmp_path):
    import pytest
    from seldon.agents.prediction import NodeStatePredictor, NodeForecastInput
    from seldon.data.models import GraphSnapshot
    from seldon.workspace.service import WorkspaceService
    from seldon.workspace.schemas import WorkspaceApply

    factory = session_factory()
    with factory() as db, db.begin():
        scenario, _, nodes, _ = seed_phase_h_graph(db)
        service = WorkspaceService(db)
        state = service.export(scenario.id)
        service.apply(WorkspaceApply.model_validate({
            "scenario_id": scenario.id, "base_revision": state["revision"], "request_id": "depth", "agent": "test", "reason": "Forecast only direct dependencies",
            "graph_scope": {"target_node_id": nodes[2].id, "max_depth": 1},
        }))
        with pytest.raises(ValueError, match="outside"):
            NodeStatePredictor(db).run(NodeForecastInput(scenario_id=scenario.id, node_id=nodes[0].id, time_horizon=scenario.time_horizon))
        _, output = PredictionCoordinator(db, config=SeldonConfig(data_dir=tmp_path)).run(PredictionCoordinator.input_from_scenario(scenario))
        prediction = db.get(ScenarioPrediction, output.prediction_id)
        snapshot = db.get(GraphSnapshot, prediction.calibration_result["graph_snapshot_id"])
        assert {n["id"] for n in snapshot.snapshot["nodes"]} == {nodes[1].id, nodes[2].id}
        assert snapshot.snapshot["scope"]["max_depth"] == 1


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


def test_prediction_coordinator_anchors_synthesis_to_base_rates_before_activation(tmp_path):
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario, kb, nodes, _ = seed_phase_h_graph(db)
            previous = ScenarioRepository(db).create_prediction(
                scenario_id=scenario.id,
                statement="Prior gold outlook",
                timeframe="6 months",
                resolution_criteria="Resolve with spot gold.",
                probabilities={"bull": 0.1, "base": 0.8, "bear": 0.1},
                confidence=0.7,
                key_drivers=[nodes[0].id],
                evidence_links=[kb.id],
                assumptions=["Prior base-rate sample"],
                status="active",
            )
            _, output = PredictionCoordinator(db, config=SeldonConfig(data_dir=tmp_path)).run(
                PredictionCoordinator.input_from_scenario(scenario, max_driver_nodes=3, export_markdown=False)
            )

        prediction = db.get(ScenarioPrediction, output.prediction_id)
        assert prediction is not None
        assert output.prediction_id == previous.id
        assert output.base_rates.base_rate_ids
        assert output.base_rates.priors[0].sample_size >= 1
        assert output.synthesis.probabilities["base"] > output.synthesis.probabilities["bull"]
        assert output.activation_gate.activated is True
        assert prediction.status == "active"
        assert prediction.calibration_result["activation_gate"]["base_rate_ids"] == output.base_rates.base_rate_ids
        linked_base_rates = list(db.scalars(select(BaseRateEvidence).where(BaseRateEvidence.prediction_id == prediction.id)))
        assert {row.id for row in linked_base_rates} >= set(output.base_rates.base_rate_ids)


def test_prediction_activation_gate_keeps_flat_red_team_review_as_draft(tmp_path):
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario = ScenarioRepository(db).create_scenario(
                name="Sparse outlook",
                target_question="Will the sparse metric move?",
                time_horizon="3 months",
            )
            kb = KBRepository(db).create_entry(
                content="The sparse metric has limited evidence and no clear directional driver.",
                topics=["sparse"],
                entities=["sparse metric"],
                scenario_ids=[scenario.id],
            )
            GraphRepository(db).create_node(
                name="Sparse metric",
                type="metric",
                current_state="No clear current direction.",
                kb_entry_ids=[kb.id],
                scenario_ids=[scenario.id],
                importance_score=0.1,
                stability_score=0.7,
            )
            _, output = PredictionCoordinator(db, config=SeldonConfig(data_dir=tmp_path)).run(
                PredictionCoordinator.input_from_scenario(scenario, max_driver_nodes=1, min_confidence_to_activate=0.35, export_markdown=False)
            )

        prediction = db.get(ScenarioPrediction, output.prediction_id)
        assert prediction is not None
        assert output.activation_gate.activated is False
        assert output.activation_gate.red_team.activation_recommendation == "needs_review"
        assert output.activation_gate.status == "draft"
        assert any("red-team recommendation" in reason for reason in output.activation_gate.reasons)
        assert prediction.status == "draft"
        assert prediction.calibration_result["activation_gate"]["activated"] is False
