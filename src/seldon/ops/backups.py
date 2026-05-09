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


@dataclass(frozen=True)
class RestoreResult:
    archive_path: Path
    restored: list[str]

    def to_dict(self) -> dict[str, object]:
        return {"archive_path": str(self.archive_path), "restored": self.restored}


@dataclass(frozen=True)
class RetentionResult:
    kept: list[Path]
    deleted: list[Path]

    def to_dict(self) -> dict[str, object]:
        return {"kept": [str(path) for path in self.kept], "deleted": [str(path) for path in self.deleted]}


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


def restore_backup(config: SeldonConfig, archive_path: str | Path, *, overwrite: bool = False) -> RestoreResult:
    """Restore a local SQLite/vector backup created by :func:`create_backup`.

    The function is intentionally conservative: callers must pass ``overwrite``
    when the target DB or vector index already exists. PostgreSQL restores should
    use pg_restore/volume procedures; this helper covers the local dev/runtime
    artifact format produced by Seldon's backup command.
    """
    archive_path = Path(archive_path)
    if not archive_path.exists():
        raise FileNotFoundError(f"backup archive not found: {archive_path}")
    staging = config.ops.backup_dir / f".restore-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    restored: list[str] = []
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(staging, filter="data")

        db_snapshot = staging / "seldon.db"
        if db_snapshot.exists():
            db_path = Path(config.database.sqlite_path)
            if db_path.exists() and not overwrite:
                raise FileExistsError(f"database already exists: {db_path}; pass overwrite=True to replace it")
            db_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_snapshot, db_path)
            restored.append("database")

        vector_snapshot = staging / "vector-index"
        if vector_snapshot.exists():
            vector_path = config.ops.vector_index_path
            if vector_path.exists():
                if not overwrite:
                    raise FileExistsError(f"vector index already exists: {vector_path}; pass overwrite=True to replace it")
                if vector_path.is_dir():
                    shutil.rmtree(vector_path)
                else:
                    vector_path.unlink()
            if vector_snapshot.is_dir():
                shutil.copytree(vector_snapshot, vector_path)
            else:
                vector_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(vector_snapshot, vector_path)
            restored.append("vector_index")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return RestoreResult(archive_path=archive_path, restored=restored)


def prune_backups(config: SeldonConfig, *, keep_last: int = 7) -> RetentionResult:
    """Delete older Seldon backup archives, keeping the newest ``keep_last``."""
    if keep_last < 1:
        raise ValueError("keep_last must be >= 1")
    backup_dir = config.ops.backup_dir
    backups = sorted(backup_dir.glob("seldon-backup-*.tar.gz"), key=lambda path: path.stat().st_mtime, reverse=True)
    kept = backups[:keep_last]
    deleted: list[Path] = []
    for path in backups[keep_last:]:
        path.unlink()
        deleted.append(path)
    return RetentionResult(kept=kept, deleted=deleted)
