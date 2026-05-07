from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from seldon.agents import GraphConstructionCoordinator, GraphConsistencyChecker, ImportanceScorer
from seldon.api.app import create_app
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AgentRun, AuditLog, ERGEdge, GraphSnapshot
from seldon.data.repositories import GraphRepository, KBRepository, ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def seed_graph(db):
    scenario = ScenarioRepository(db).create_scenario(
        name="Gold outlook",
        target_question="Where will gold trade in 6 months?",
        time_horizon="6 months",
    )
    kb = KBRepository(db).create_entry(
        content="Federal Reserve rate cuts can boost gold demand and drive gold prices higher over coming months.",
        topics=["gold", "rates"],
        entities=["Federal Reserve", "gold prices"],
        scenario_ids=[scenario.id],
        source_name="Seed KB",
        perspective_tags={"confidence": 0.8},
    )
    graph = GraphRepository(db)
    fed = graph.create_node(
        name="Federal Reserve policy",
        type="policy",
        description="US monetary policy stance",
        kb_entry_ids=[kb.id],
        scenario_ids=[scenario.id],
    )
    gold = graph.create_node(
        name="Gold prices",
        type="metric",
        description="Spot gold price level",
        kb_entry_ids=[kb.id],
        scenario_ids=[scenario.id],
    )
    demand = graph.create_node(
        name="Gold demand",
        type="metric",
        description="Demand for gold",
        kb_entry_ids=[kb.id],
        scenario_ids=[scenario.id],
    )
    return scenario, kb, fed, gold, demand


def test_graph_construction_generates_bounded_evidence_edges_and_importance_scores():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario, kb, fed, gold, demand = seed_graph(db)
            run_id, output = GraphConstructionCoordinator(db, config=SeldonConfig()).run(
                GraphConstructionCoordinator.input_from_scenario(scenario, max_candidate_pairs=2)
            )

        run = db.get(AgentRun, run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.phase == "graph_construction"
        assert len(output.candidate_pairs) == 2
        assert output.created_edge_ids
        assert output.snapshot_id is not None
        assert db.get(GraphSnapshot, output.snapshot_id) is not None

        edges = list(db.scalars(select(ERGEdge)))
        assert all(kb.id in edge.evidence_kb_ids for edge in edges)
        assert all(scenario.id in edge.scenario_ids for edge in edges)
        assert {edge.relationship_type for edge in edges} <= {
            "causes",
            "correlates_with",
            "depends_on",
            "constrains",
            "enables",
            "opposes",
            "amplifies",
            "dampens",
        }
        assert db.get(type(fed), fed.id).importance_score > 0
        assert db.scalar(select(AuditLog).where(AuditLog.action == "graph_construction_write")) is not None


def test_graph_construction_updates_existing_edges_instead_of_creating_duplicates():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario, kb, fed, gold, _ = seed_graph(db)
            existing = GraphRepository(db).create_edge(
                source_node_id=fed.id,
                target_node_id=gold.id,
                relationship_type="amplifies",
                description="older edge",
                strength=0.3,
                confidence=0.3,
                evidence_kb_ids=[],
                scenario_ids=[scenario.id],
            )
            run_id, output = GraphConstructionCoordinator(db, config=SeldonConfig()).run(
                GraphConstructionCoordinator.input_from_scenario(scenario, max_candidate_pairs=1)
            )

        assert run_id
        assert existing.id in output.updated_edge_ids or output.created_edge_ids
        edges = list(db.scalars(select(ERGEdge)))
        unique_keys = {(edge.source_node_id, edge.target_node_id, edge.relationship_type) for edge in edges}
        assert len(unique_keys) == len(edges)


def test_consistency_checker_flags_unsupported_high_confidence_and_importance_scorer_scores():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario, _, fed, gold, _ = seed_graph(db)
            edge = GraphRepository(db).create_edge(
                source_node_id=fed.id,
                target_node_id=gold.id,
                relationship_type="causes",
                description="unsupported high confidence",
                strength=0.9,
                confidence=0.9,
                evidence_kb_ids=[],
                scenario_ids=[scenario.id],
            )
            _, issues = GraphConsistencyChecker(db, config=SeldonConfig()).run_checks(scenario_id=scenario.id)
            _, updates = ImportanceScorer(db, config=SeldonConfig()).run_scores(scenario_id=scenario.id)

        assert any(issue.issue_type == "unsupported_high_confidence_edge" and edge.id in issue.edge_ids for issue in issues)
        assert {update.node_id for update in updates} >= {fed.id, gold.id}
        assert all(0 <= update.importance_score <= 1 for update in updates)


def test_graph_construction_api_runs_real_phase_g_workflow_and_persists_edges():
    factory = session_factory()
    client = TestClient(create_app(SeldonConfig(), session_factory=factory))
    scenario = client.post(
        "/scenarios",
        json={"name": "Gold outlook", "target_question": "Where will gold trade in 6 months?", "time_horizon": "6 months"},
    ).json()
    kb = client.post(
        "/kb/entries",
        json={
            "content": "Rate cuts may boost gold demand and raise gold prices over coming months.",
            "topics": ["gold", "rates"],
            "entities": ["rates", "gold prices"],
            "scenario_ids": [scenario["id"]],
            "perspective_tags": {"confidence": 0.8},
        },
    ).json()
    node_a = client.post(
        "/graph/nodes",
        json={"name": "Rate cuts", "type": "policy", "kb_entry_ids": [kb["id"]], "scenario_ids": [scenario["id"]]},
    ).json()
    node_b = client.post(
        "/graph/nodes",
        json={"name": "Gold prices", "type": "metric", "kb_entry_ids": [kb["id"]], "scenario_ids": [scenario["id"]]},
    ).json()

    response = client.post(f"/scenarios/{scenario['id']}/run-graph-construction", json={"max_candidate_pairs": 5})
    assert response.status_code == 202
    body = response.json()
    assert body["agent_id"] == "graph_construction_coordinator"
    assert body["status"] == "completed"
    assert body["graph_construction"]["created_edge_ids"]
    assert body["graph_construction"]["snapshot_id"]

    edges = client.get("/graph/edges").json()
    assert any(edge["source_node_id"] == node_a["id"] and edge["target_node_id"] == node_b["id"] for edge in edges)
    runs = client.get("/runs").json()
    assert {run["agent_id"] for run in runs} >= {
        "graph_construction_coordinator",
        "pairwise_relationship_detector",
        "graph_consistency_checker",
        "importance_scorer",
    }


def test_convergence_loop_api_runs_phases_e_f_g_until_threshold():
    factory = session_factory()
    client = TestClient(create_app(SeldonConfig(), session_factory=factory))
    scenario = client.post(
        "/scenarios",
        json={"name": "Rates outlook", "target_question": "Will rates fall this year?", "time_horizon": "12 months"},
    ).json()
    client.post(
        "/kb/entries",
        json={
            "content": "Federal Reserve policy easing could lower rates and support risk assets.",
            "topics": ["rates", "policy"],
            "entities": ["Federal Reserve", "risk assets"],
            "scenario_ids": [scenario["id"]],
        },
    )

    response = client.post(
        f"/scenarios/{scenario['id']}/run-graph-construction",
        json={"run_convergence_loop": True, "max_iterations": 1, "max_candidate_pairs": 5},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["agent_id"] == "convergence_loop_coordinator"
    assert body["convergence_loop"]["iterations"][0]["iteration"] == 1
    assert body["convergence_loop"]["final_graph"]["snapshot_id"]

    scenario_after = client.get(f"/scenarios/{scenario['id']}").json()
    assert scenario_after["erg_snapshot_id"]
