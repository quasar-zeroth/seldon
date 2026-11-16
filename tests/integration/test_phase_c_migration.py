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


def test_entity_tags_upgrade_preserves_existing_unversioned_database(tmp_path):
    from seldon.data.database import create_all, make_engine, make_session_factory
    from seldon.data.repositories import GraphRepository
    from sqlalchemy import text

    path = tmp_path / "existing.db"
    engine = make_engine(sqlite_path=path)
    create_all(engine)
    with make_session_factory(engine)() as db, db.begin():
        node = GraphRepository(db).create_node(name="Existing campus", type="entity", current_state="Preserve evidence")
        node_id = node.id
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE erg_nodes DROP COLUMN tags"))
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT current_state, tags FROM erg_nodes WHERE id=:id"), {"id": node_id}).one()
        assert row == ("Preserve evidence", "[]")
    engine.dispose()
