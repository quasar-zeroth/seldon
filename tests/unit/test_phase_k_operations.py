from __future__ import annotations

import os
import tarfile

from fastapi.testclient import TestClient
from seldon.api.app import create_app
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.ops import InProcessJobQueue


def app_with_ops(tmp_path, *, require_api_key: bool = False) -> tuple[TestClient, InProcessJobQueue]:
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    config = SeldonConfig()
    config.ops.backup_dir = tmp_path / "backups"
    config.ops.vector_index_path = tmp_path / "vector-index"
    config.ops.require_api_key = require_api_key
    config.ops.allow_localhost_without_api_key = False
    config.ops.structured_logs = False
    queue = InProcessJobQueue()
    app = create_app(config, session_factory=make_session_factory(engine), job_queue=queue)
    return TestClient(app), queue


def test_api_key_auth_is_optional_but_enforced_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("SELDON_API_KEY", "secret")
    client, _ = app_with_ops(tmp_path, require_api_key=True)

    assert client.get("/health").status_code == 200
    assert client.get("/scenarios").status_code == 401
    assert client.get("/scenarios", headers={"x-seldon-api-key": "secret"}).status_code == 200
    assert client.get("/scenarios", headers={"authorization": "Bearer secret"}).status_code == 200


def test_seed_demo_job_populates_operating_console_data(tmp_path):
    client, queue = app_with_ops(tmp_path)

    response = client.post("/ops/seed-demo")
    assert response.status_code == 202
    job = queue.run_one(response.json()["id"])

    assert job.status == "completed"
    assert job.result and job.result["created"] is True
    scenarios = client.get("/scenarios").json()
    assert scenarios[0]["name"] == "Demo: Gold 6-month outlook"
    assert client.get("/graph/edges").json()[0]["relationship_type"] == "amplifies"


def test_backup_job_snapshots_database(tmp_path):
    client, queue = app_with_ops(tmp_path)
    client.post("/scenarios", json={"name": "Ops smoke", "target_question": "Will operations work?"})

    response = client.post("/ops/backups", json={"label": "smoke"})
    assert response.status_code == 202
    job = queue.run_one(response.json()["id"])

    assert job.status == "completed"
    archive_path = job.result["path"]
    assert job.result["included"] == ["database"]
    assert os.path.exists(archive_path)
    with tarfile.open(archive_path, "r:gz") as archive:
        assert "seldon.db" in archive.getnames()


def test_generic_job_routes_expose_status(tmp_path):
    client, queue = app_with_ops(tmp_path)

    response = client.post("/ops/jobs", json={"kind": "seed_demo", "payload": {}})
    job_id = response.json()["id"]
    queue.run_one(job_id)

    fetched = client.get(f"/ops/jobs/{job_id}").json()
    assert fetched["status"] == "completed"
    assert client.get("/ops/jobs").json()[0]["id"] == job_id
