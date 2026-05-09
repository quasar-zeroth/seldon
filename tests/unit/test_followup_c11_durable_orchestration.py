from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from seldon.api.app import create_app
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AgentMessage, OpsJob
from seldon.data.repositories import AgentRunRepository, ScenarioRepository
from seldon.ops.jobs import InProcessJobQueue


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def test_durable_job_queue_persists_idempotency_and_recovers_queued_work():
    factory = session_factory()
    calls: list[dict[str, object]] = []
    queue = InProcessJobQueue(session_factory=factory, worker_id="test-worker")
    queue.register("echo", lambda payload: calls.append(payload) or {"echoed": payload})

    first = queue.enqueue("echo", {"value": 42}, idempotency_key="same-job")
    duplicate = queue.enqueue("echo", {"value": 99}, idempotency_key="same-job")

    assert duplicate.id == first.id
    with factory() as db:
        row = db.get(OpsJob, first.id)
        assert row is not None
        assert row.status == "queued"
        assert row.payload == {"value": 42}

    recovered = InProcessJobQueue(session_factory=factory, worker_id="recovering-worker")
    recovered.register("echo", lambda payload: {"recovered": payload["value"]})
    recovered.start()
    recovered.stop()
    final = recovered.run_one(first.id) if recovered.get(first.id).status == "queued" else recovered.get(first.id)

    assert final.status == "completed"
    assert final.result == {"recovered": 42}
    with factory() as db:
        row = db.get(OpsJob, first.id)
        assert row is not None
        assert row.status == "completed"
        assert row.attempt_count >= 1
        assert row.lease_owner is None


def test_agent_message_timeline_is_structured_and_replayable():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            repo = AgentRunRepository(db)
            run = repo.create(agent_id="coordinator", phase="test", status="running", input={"scenario_id": "s1"})
            repo.publish(run.id, "specialist.requested", payload={"target_agent": "worker", "route": "extract"})
            repo.publish(run.id, "specialist.completed", payload={"target_agent": "worker", "items": 3})
            messages = repo.timeline(run.id)

        assert [message.payload["event_type"] for message in messages] == ["specialist.requested", "specialist.completed"]
        assert messages[0].role == "event"
        assert messages[1].payload["items"] == 3


def test_api_exposes_durable_jobs_timeline_and_sse_event_streams(tmp_path):
    factory = session_factory()
    queue = InProcessJobQueue(session_factory=factory, worker_id="api-test-worker")
    app = create_app(SeldonConfig(data_dir=tmp_path), session_factory=factory, job_queue=queue)
    with TestClient(app) as client:
        with factory() as db:
            with db.begin():
                scenario = ScenarioRepository(db).create_scenario(
                    name="Durable orchestration",
                    target_question="Will orchestration replay updates?",
                    time_horizon="1 week",
                )
                run_repo = AgentRunRepository(db)
                run = run_repo.create(agent_id="context_gathering_coordinator", phase="context_gathering", status="completed", input={"scenario_id": scenario.id}, output={"ok": True})
                run_repo.publish(run.id, "run.completed", payload={"agent_id": run.agent_id})
                run_id = run.id
                scenario_id = scenario.id

        response = client.post("/ops/jobs", json={"kind": "seed_demo", "payload": {}, "idempotency_key": "seed-once"})
        assert response.status_code == 202
        job_id = response.json()["id"]
        duplicate = client.post("/ops/jobs", json={"kind": "seed_demo", "payload": {"ignored": True}, "idempotency_key": "seed-once"})
        assert duplicate.json()["id"] == job_id
        assert client.get(f"/ops/jobs/{job_id}").json()["idempotency_key"] == "seed-once"

        timeline = client.get(f"/runs/{run_id}/timeline").json()
        assert timeline["run"]["id"] == run_id
        assert timeline["messages"][0]["payload"]["event_type"] == "run.completed"

        run_stream = client.get(f"/events/runs?run_id={run_id}&once=true")
        assert run_stream.status_code == 200
        assert "event: run" in run_stream.text
        assert "event: agent_message" in run_stream.text

        scenario_stream = client.get(f"/events/scenarios/{scenario_id}?once=true")
        assert scenario_stream.status_code == 200
        assert "event: scenario" in scenario_stream.text
        assert scenario_id in scenario_stream.text

    with factory() as db:
        assert db.scalar(select(OpsJob).where(OpsJob.idempotency_key == "seed-once")) is not None
        assert db.scalar(select(AgentMessage).where(AgentMessage.agent_run_id == run_id)) is not None
