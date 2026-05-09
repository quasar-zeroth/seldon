from __future__ import annotations

import json
import tarfile

from fastapi.testclient import TestClient
from sqlalchemy import text

from seldon.api.app import create_app
from seldon.cli import main
from seldon.config import SeldonConfig, config_from_env
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.repositories import ScenarioRepository
from seldon.ops import create_backup, prune_backups, restore_backup
from seldon.ops.jobs import InProcessJobQueue


def test_backup_restore_and_retention_round_trip(tmp_path):
    source_db = tmp_path / "source.db"
    restore_db = tmp_path / "restore.db"
    vector_dir = tmp_path / "vector-index"
    vector_dir.mkdir()
    (vector_dir / "index.json").write_text('{"ok": true}', encoding="utf-8")

    source_config = SeldonConfig()
    source_config.database.sqlite_path = source_db
    source_config.ops.backup_dir = tmp_path / "backups"
    source_config.ops.vector_index_path = vector_dir
    engine = make_engine(sqlite_path=source_db)
    create_all(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        with db.begin():
            ScenarioRepository(db).create_scenario(name="Restore me", target_question="Can backup restore?", time_horizon="soon")

    backup = create_backup(source_config, engine=engine, label="roundtrip")
    assert backup.included == ["database", "vector_index"]
    with tarfile.open(backup.path, "r:gz") as archive:
        assert {"seldon.db", "vector-index/index.json"}.issubset(set(archive.getnames()))

    restore_config = SeldonConfig()
    restore_config.database.sqlite_path = restore_db
    restore_config.ops.backup_dir = source_config.ops.backup_dir
    restore_config.ops.vector_index_path = tmp_path / "restored-vector"
    restored = restore_backup(restore_config, backup.path)
    assert restored.restored == ["database", "vector_index"]
    restored_engine = make_engine(sqlite_path=restore_db)
    restored_factory = make_session_factory(restored_engine)
    with restored_factory() as db:
        assert db.execute(text("select count(*) from scenarios")).scalar_one() == 1
    assert (restore_config.ops.vector_index_path / "index.json").exists()

    create_backup(source_config, engine=engine, label="old-1")
    create_backup(source_config, engine=engine, label="old-2")
    retention = prune_backups(source_config, keep_last=1)
    assert len(retention.kept) == 1
    assert retention.deleted


def test_config_from_env_cli_healthcheck_and_metrics(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SELDON_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SELDON_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("SELDON_ALLOW_LOCALHOST_WITHOUT_API_KEY", "false")
    cfg = config_from_env()
    assert cfg.database.sqlite_path == tmp_path / "data" / "seldon.db"
    assert cfg.ops.require_api_key is True
    assert cfg.ops.allow_localhost_without_api_key is False

    assert main(["healthcheck"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["api_key_required"] is True

    engine = make_engine(sqlite_path=tmp_path / "metrics.db")
    create_all(engine)
    factory = make_session_factory(engine)
    app_config = SeldonConfig(data_dir=tmp_path)
    queue = InProcessJobQueue(session_factory=factory)
    client = TestClient(create_app(app_config, session_factory=factory, job_queue=queue))
    response = client.get("/ops/metrics")
    assert response.status_code == 200
    assert response.json()["runs"]["total"] == 0
    assert response.json()["jobs"]["total"] == 0
