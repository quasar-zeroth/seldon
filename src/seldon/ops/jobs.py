"""Durable local background job queue.

The queue still runs in-process for local development, but job state is now
optionally backed by the relational DB. That gives the API restart recovery,
idempotency keys, leases, retry counters, and an easy seam for swapping the
worker implementation later.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from seldon.data.models import OpsJob
from seldon.llm.openrouter import LLMAuthenticationError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class JobRecord:
    id: str
    kind: str
    status: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    idempotency_key: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None

    @classmethod
    def from_row(cls, row: OpsJob) -> "JobRecord":
        return cls(
            id=row.id,
            kind=row.kind,
            status=row.status,
            payload=row.payload or {},
            created_at=row.created_at,
            updated_at=row.updated_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            result=row.result,
            error=row.error,
            idempotency_key=row.idempotency_key,
            attempt_count=row.attempt_count,
            max_attempts=row.max_attempts,
            lease_owner=row.lease_owner,
            lease_expires_at=row.lease_expires_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "payload": self.payload,
            "created_at": _json_dt(self.created_at),
            "updated_at": _json_dt(self.updated_at),
            "started_at": _json_dt(self.started_at),
            "completed_at": _json_dt(self.completed_at),
            "result": self.result,
            "error": self.error,
            "idempotency_key": self.idempotency_key,
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "lease_owner": self.lease_owner,
            "lease_expires_at": _json_dt(self.lease_expires_at),
        }


JobHandler = Callable[[dict[str, Any]], dict[str, Any] | None]


class InProcessJobQueue:
    """Single-worker FIFO queue with optional DB-backed durable job records."""

    def __init__(self, *, session_factory: sessionmaker[Session] | None = None, worker_id: str | None = None, lease_seconds: int = 300) -> None:
        self._queue: Queue[str] = Queue()
        self._jobs: dict[str, JobRecord] = {}
        self._handlers: dict[str, JobHandler] = {}
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._session_factory = session_factory
        self._worker_id = worker_id or f"seldon-worker-{uuid4()}"
        self._lease_seconds = lease_seconds
        self._paused: bool = False
        self._pause_reason: str | None = None
        self._paused_at: datetime | None = None

    def pause(self, reason: str) -> None:
        """Pause job processing. Currently-running jobs finish; queued jobs wait."""
        with self._lock:
            self._paused = True
            self._pause_reason = reason
            self._paused_at = _now()

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self._pause_reason = None
            self._paused_at = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "paused": self._paused,
                "pause_reason": self._pause_reason,
                "paused_at": _json_dt(self._paused_at),
                "worker_id": self._worker_id,
                "queue_depth": self._queue.qsize(),
            }

    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    def start(self) -> None:
        self._recover_durable_jobs()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="seldon-job-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
    ) -> JobRecord:
        if kind not in self._handlers:
            raise KeyError(f"unknown job kind: {kind}")
        payload = payload or {}
        if self._session_factory is not None:
            with self._session_factory() as session:
                with session.begin():
                    if idempotency_key:
                        existing = session.scalar(select(OpsJob).where(OpsJob.idempotency_key == idempotency_key))
                        if existing is not None:
                            return JobRecord.from_row(existing)
                    row = OpsJob(kind=kind, status="queued", payload=payload, idempotency_key=idempotency_key, max_attempts=max_attempts)
                    session.add(row)
                    session.flush()
                    job = JobRecord.from_row(row)
            self._queue.put(job.id)
            return job
        job = JobRecord(id=str(uuid4()), kind=kind, status="queued", payload=payload, idempotency_key=idempotency_key, max_attempts=max_attempts)
        with self._lock:
            self._jobs[job.id] = job
        self._queue.put(job.id)
        return job

    def get(self, job_id: str) -> JobRecord | None:
        if self._session_factory is not None:
            with self._session_factory() as session:
                row = session.get(OpsJob, job_id)
                return JobRecord.from_row(row) if row else None
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[JobRecord]:
        if self._session_factory is not None:
            with self._session_factory() as session:
                rows = list(session.scalars(select(OpsJob).order_by(OpsJob.created_at.desc())))
                return [JobRecord.from_row(row) for row in rows]
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def run_one(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if job is None:
            raise KeyError(f"job not found: {job_id}")
        self._execute(job)
        refreshed = self.get(job_id)
        return refreshed or job

    def _recover_durable_jobs(self) -> None:
        if self._session_factory is None:
            return
        now = _now()
        with self._session_factory() as session:
            with session.begin():
                rows = list(
                    session.scalars(
                        select(OpsJob).where(
                            OpsJob.status.in_(["queued", "running"]),
                        )
                    )
                )
                for row in rows:
                    if row.status == "running" and row.lease_expires_at and row.lease_expires_at > now:
                        continue
                    if row.status == "running":
                        row.status = "queued"
                        row.lease_owner = None
                        row.lease_expires_at = None
                    self._queue.put(row.id)

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._paused:
                # Hold the worker idle while paused; the queue retains its items.
                # Operator must call resume() (typically via /ops/queue) to continue.
                self._stop.wait(timeout=0.5)
                continue
            try:
                job_id = self._queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                job = self.get(job_id)
                if job is not None:
                    self._execute(job)
            finally:
                self._queue.task_done()

    def _execute(self, job: JobRecord) -> None:
        handler = self._handlers[job.kind]
        lease = _now() + timedelta(seconds=self._lease_seconds)
        try:
            job = self._mark(job, status="running", started_at=job.started_at or _now(), error=None, lease_owner=self._worker_id, lease_expires_at=lease, attempt_count=job.attempt_count + 1)
        except KeyError:
            return
        try:
            result = handler(job.payload) or {}
        except LLMAuthenticationError as exc:
            # Auth failures are account-wide — pause the queue so the operator can
            # fix OPENROUTER_API_KEY without burning every queued scenario through
            # the same broken credential. The current job is marked failed (no retry
            # because retries would all hit the same auth wall).
            try:
                self._mark(job, status="failed", error=f"LLM authentication failed: {exc}", lease_owner=None, lease_expires_at=None, completed_at=_now())
            except KeyError:
                pass
            self.pause(f"llm_auth_failed: {exc}")
            return
        except Exception as exc:  # pragma: no cover - defensive state capture
            # Some errors are deterministic (e.g. insufficient graph nodes): retrying
            # can't help, so fail immediately when the exception opts out of retries.
            no_retry = getattr(exc, "no_retry", False)
            status = "failed" if no_retry or job.attempt_count >= job.max_attempts else "queued"
            try:
                marked = self._mark(job, status=status, error=str(exc), lease_owner=None, lease_expires_at=None, completed_at=_now() if status == "failed" else None)
            except KeyError:
                return
            if status == "queued":
                self._queue.put(marked.id)
            return
        try:
            self._mark(job, status="completed", completed_at=_now(), result=result, error=None, lease_owner=None, lease_expires_at=None)
        except KeyError:
            return

    def _mark(self, job: JobRecord, **values: Any) -> JobRecord:
        if self._session_factory is not None:
            with self._session_factory() as session:
                with session.begin():
                    row = session.get(OpsJob, job.id)
                    if row is None:
                        raise KeyError(f"job not found: {job.id}")
                    for key, value in values.items():
                        setattr(row, key, value)
                    row.updated_at = _now()
                    session.flush()
                    return JobRecord.from_row(row)
        with self._lock:
            for key, value in values.items():
                setattr(job, key, value)
            job.updated_at = _now()
        return job
