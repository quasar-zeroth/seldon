from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from seldon.agents import ContextGatheringCoordinator
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AgentRun, AuditLog, KBEntry
from seldon.data.repositories import KBRepository, ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def test_context_gathering_coordinator_serializes_phase_e_agents_and_writes_kb():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario = ScenarioRepository(db).create_scenario(
                name="Gold outlook",
                target_question="Where will gold trade in 6 months?",
                time_horizon="6 months",
            )
            KBRepository(db).create_entry(
                content="Central banks continue buying gold and supporting demand.",
                topics=["gold"],
                entities=["central banks"],
                scenario_ids=[],
                source_name="Seed KB",
                perspective_tags={"confidence": 0.8},
            )
            payload = ContextGatheringCoordinator.input_from_scenario(scenario, max_subqueries=4)
            run_id, output = ContextGatheringCoordinator(db, config=SeldonConfig()).run(payload)

        parent = db.get(AgentRun, run_id)
        assert parent is not None
        assert parent.status == "completed"
        assert parent.output["child_run_ids"] == output.child_run_ids
        assert len(output.child_run_ids) >= 5
        assert output.run_plan.subqueries
        assert output.kb_entry_ids

        entries = list(db.scalars(select(KBEntry)))
        assert any(scenario.id in entry.scenario_ids for entry in entries)
        assert db.scalar(select(AuditLog).where(AuditLog.action == "context_gathering_kb_write")) is not None


def test_context_gathering_api_runs_real_phase_e_workflow():
    factory = session_factory()
    from seldon.api.app import create_app

    client = TestClient(create_app(SeldonConfig(), session_factory=factory))
    scenario = client.post(
        "/scenarios",
        json={"name": "Rates outlook", "target_question": "Will rates fall this year?", "time_horizon": "12 months"},
    ).json()

    response = client.post(f"/scenarios/{scenario['id']}/run-context-gathering", json={"max_subqueries": 3})
    assert response.status_code == 202
    body = response.json()
    assert body["agent_id"] == "context_gathering_coordinator"
    assert body["status"] == "completed"
    assert body["context_gathering"]["kb_entry_ids"]

    runs = client.get("/runs").json()
    assert runs[0]["id"] == body["id"]
    assert {run["agent_id"] for run in runs} >= {
        "context_gathering_coordinator",
        "query_decomposer",
        "information_retriever",
        "information_summarizer",
        "deduplication_delta_detector",
        "kb_writer",
    }

    kb_entries = client.get("/kb/search", params={"scenario_id": scenario["id"]}).json()
    assert kb_entries
