"""First-class operational CLI for The Seldon Project."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from seldon.config import config_from_env
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.kb.vector import LocalHashEmbeddingProvider
from seldon.data.models import KBEntry
from seldon.ops import create_backup, prune_backups, restore_backup, seed_demo_data


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_migrate(args: argparse.Namespace) -> int:
    cmd = ["alembic", "upgrade", args.revision]
    subprocess.run(cmd, check=True)
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    cfg = config_from_env()
    engine = make_engine(cfg.database.url, sqlite_path=cfg.database.sqlite_path, echo=cfg.database.echo)
    _print_json(create_backup(cfg, engine=engine, label=args.label).to_dict())
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    cfg = config_from_env()
    _print_json(restore_backup(cfg, args.archive, overwrite=args.overwrite).to_dict())
    return 0


def cmd_prune_backups(args: argparse.Namespace) -> int:
    _print_json(prune_backups(config_from_env(), keep_last=args.keep_last).to_dict())
    return 0


def cmd_seed_demo(_: argparse.Namespace) -> int:
    cfg = config_from_env()
    engine = make_engine(cfg.database.url, sqlite_path=cfg.database.sqlite_path, echo=cfg.database.echo)
    create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        with session.begin():
            _print_json(seed_demo_data(session))
    return 0


def cmd_vector_rebuild(_: argparse.Namespace) -> int:
    cfg = config_from_env()
    engine = make_engine(cfg.database.url, sqlite_path=cfg.database.sqlite_path, echo=cfg.database.echo)
    create_all(engine)
    factory = make_session_factory(engine)
    provider = LocalHashEmbeddingProvider()
    count = 0
    with factory() as session:
        with session.begin():
            for entry in session.query(KBEntry).all():
                embedding = provider.embed(entry.content)
                entry.content_embedding = embedding.vector
                entry.embedding_metadata = {**(entry.embedding_metadata or {}), **embedding.metadata}
                entry.vector_index_pointer = entry.vector_index_pointer or f"kb:{entry.id}"
                count += 1
    _print_json({"rebuilt_embeddings": count, "provider": "local_hash"})
    return 0


def cmd_healthcheck(_: argparse.Namespace) -> int:
    cfg = config_from_env()
    engine = make_engine(cfg.database.url, sqlite_path=cfg.database.sqlite_path, echo=cfg.database.echo)
    create_all(engine)
    with engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1")
    report = {
        "ok": True,
        "database": str(engine.url).replace(str(engine.url.password), "***") if getattr(engine.url, "password", None) else str(engine.url),
        "api_key_required": cfg.ops.require_api_key,
        "backup_dir": str(cfg.ops.backup_dir),
        "vector_index_path": str(cfg.ops.vector_index_path),
    }
    _print_json(report)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seldon", description="Operational CLI for The Seldon Project")
    sub = parser.add_subparsers(dest="command", required=True)

    migrate = sub.add_parser("migrate", help="Run Alembic migrations")
    migrate.add_argument("revision", nargs="?", default="head")
    migrate.set_defaults(func=cmd_migrate)

    backup = sub.add_parser("backup", help="Create a local SQLite/vector backup")
    backup.add_argument("--label")
    backup.set_defaults(func=cmd_backup)

    restore = sub.add_parser("restore", help="Restore a local backup archive")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--overwrite", action="store_true")
    restore.set_defaults(func=cmd_restore)

    prune = sub.add_parser("prune-backups", help="Apply backup retention")
    prune.add_argument("--keep-last", type=int, default=7)
    prune.set_defaults(func=cmd_prune_backups)

    seed = sub.add_parser("seed-demo", help="Seed demo scenario data")
    seed.set_defaults(func=cmd_seed_demo)

    vector = sub.add_parser("vector-rebuild", help="Rebuild local deterministic KB embeddings")
    vector.set_defaults(func=cmd_vector_rebuild)

    health = sub.add_parser("healthcheck", help="Check DB/config reachability")
    health.set_defaults(func=cmd_healthcheck)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except Exception as exc:
        print(f"seldon: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
