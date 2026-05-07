from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from seldon.agents import ExtractionCoordinator, NodeCandidate, NodeDeduplicatorMerger
from seldon.api.app import create_app
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AgentRun, AuditLog, ERGNode
from seldon.data.repositories import GraphRepository, KBRepository, ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def test_extraction_coordinator_writes_schema_valid_erg_nodes_from_kb_evidence():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario = ScenarioRepository(db).create_scenario(
                name="Gold outlook",
                target_question="Where will gold trade in 6 months?",
                time_horizon="6 months",
            )
            kb_entry = KBRepository(db).create_entry(
                content="The Federal Reserve cut rates while central banks reported stronger gold demand.",
                topics=["gold", "rates"],
                entities=["Federal Reserve", "central banks"],
                scenario_ids=[scenario.id],
                source_name="Seed KB",
                perspective_tags={"confidence": 0.8},
            )
            payload = ExtractionCoordinator.input_from_scenario(scenario)
            run_id, output = ExtractionCoordinator(db, config=SeldonConfig()).run(payload)

        parent = db.get(AgentRun, run_id)
        assert parent is not None
        assert parent.status == "completed"
        assert parent.phase == "extraction"
        assert parent.output["created_node_ids"] == output.created_node_ids
        assert len(output.child_run_ids) == 4
        assert output.created_node_ids

        nodes = list(db.scalars(select(ERGNode)))
        assert {node.type for node in nodes} >= {"actor", "topic", "event"}
        assert any(kb_entry.id in node.kb_entry_ids and scenario.id in node.scenario_ids for node in nodes)
        assert db.scalar(select(AuditLog).where(AuditLog.action == "extraction_graph_write")) is not None


def test_node_deduplicator_emits_merge_proposals_without_destructive_merge():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            existing = GraphRepository(db).create_node(name="Federal Reserve", type="actor", description="US central bank")
            run_id, proposals = NodeDeduplicatorMerger(db, config=SeldonConfig()).run_candidates(
                [
                    NodeCandidate(name="Federal Reserve", type="actor", kb_entry_ids=["kb-1"], scenario_ids=["scenario-1"]),
                    NodeCandidate(name="Federal   Reserve", type="actor", kb_entry_ids=["kb-2"], scenario_ids=["scenario-1"]),
                ]
            )

        run = db.get(AgentRun, run_id)
        assert run is not None and run.status == "completed"
        assert len(proposals) == 1
        assert proposals[0].existing_node_id == existing.id
        assert proposals[0].alias_node_ids == [existing.id]
        assert proposals[0].candidate_names == ["Federal Reserve", "Federal   Reserve"]
        assert db.get(ERGNode, existing.id).name == "Federal Reserve"


def test_extraction_api_runs_real_phase_f_workflow_and_persists_nodes():
    factory = session_factory()
    client = TestClient(create_app(SeldonConfig(), session_factory=factory))
    scenario = client.post(
        "/scenarios",
        json={"name": "Rates outlook", "target_question": "Will rates fall this year?", "time_horizon": "12 months"},
    ).json()
    client.post(
        "/kb/entries",
        json={
            "content": "The Federal Reserve signaled policy easing and lower rate pressure.",
            "topics": ["rates", "policy"],
            "entities": ["Federal Reserve"],
            "scenario_ids": [scenario["id"]],
            "perspective_tags": {"confidence": 0.7},
        },
    )

    response = client.post(f"/scenarios/{scenario['id']}/run-extraction", json={"max_kb_entries": 10, "max_nodes": 20})
    assert response.status_code == 202
    body = response.json()
    assert body["agent_id"] == "extraction_coordinator"
    assert body["status"] == "completed"
    assert body["extraction"]["created_node_ids"]

    runs = client.get("/runs").json()
    assert {run["agent_id"] for run in runs} >= {
        "extraction_coordinator",
        "entity_extractor",
        "event_extractor",
        "topic_theme_extractor",
        "node_deduplicator_merger",
    }
    graph_nodes = client.get("/graph/nodes").json()
    assert any(node["name"] == "Federal Reserve" and scenario["id"] in node["scenario_ids"] for node in graph_nodes)
