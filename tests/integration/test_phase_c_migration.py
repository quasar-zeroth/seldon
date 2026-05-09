from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_migration_smoke(tmp_path):
    db_path = tmp_path / "migrated.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    assert "kb_entries" in tables
    assert "agent_runs" in tables
    assert "audit_log" in tables
    assert "scenarios" in tables
    assert "feedback_entries" in tables
    assert "graph_snapshots" in tables
    assert "ops_jobs" in tables
