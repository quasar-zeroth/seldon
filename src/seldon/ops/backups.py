"""Backup helpers for Seldon's DB and local vector index."""
from __future__ import annotations

import shutil
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Engine

from seldon.config import SeldonConfig


@dataclass(frozen=True)
class BackupResult:
    path: Path
    included: list[str]

    def to_dict(self) -> dict[str, object]:
        return {"path": str(self.path), "included": self.included}


def create_backup(config: SeldonConfig, *, engine: Engine | None = None, label: str | None = None) -> BackupResult:
    """Create a compressed backup of SQLite storage and the vector index path.

    For SQLite, uses the online backup API when an engine is supplied so tests and
    local services can snapshot a live DB. PostgreSQL deployments should use the
    compose-managed database volume or pg_dump; this function still captures the
    local vector/index files if present.
    """
    backup_dir = config.ops.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = backup_dir / f"seldon-backup-{label or stamp}.tar.gz"
    staging = backup_dir / f".staging-{stamp}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    included: list[str] = []
    try:
        db_snapshot = staging / "seldon.db"
        db_path = Path(config.database.sqlite_path)
        if engine is not None and str(engine.url).startswith("sqlite"):
            raw = engine.raw_connection()
            try:
                target = __import__("sqlite3").connect(db_snapshot)
                try:
                    raw.driver_connection.backup(target)
                finally:
                    target.close()
            finally:
                raw.close()
            included.append("database")
        elif db_path.exists():
            shutil.copy2(db_path, db_snapshot)
            included.append("database")

        vector_path = config.ops.vector_index_path
        if vector_path.exists():
            dest = staging / "vector-index"
            if vector_path.is_dir():
                shutil.copytree(vector_path, dest)
            else:
                dest.mkdir()
                shutil.copy2(vector_path, dest / vector_path.name)
            included.append("vector_index")

        with tarfile.open(archive_path, "w:gz") as archive:
            for child in staging.iterdir():
                archive.add(child, arcname=child.name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return BackupResult(path=archive_path, included=included)
