"""Small in-process background job queue for local productionization.

The queue is intentionally simple: it gives the API durable-enough job state for a
single process and a clean seam for replacing it with Dramatiq/Celery/RQ later.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(timezone.utc)


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
        }


JobHandler = Callable[[dict[str, Any]], dict[str, Any] | None]


class InProcessJobQueue:
    """Single-worker FIFO queue with in-memory job records."""

    def __init__(self) -> None:
        self._queue: Queue[str] = Queue()
        self._jobs: dict[str, JobRecord] = {}
        self._handlers: dict[str, JobHandler] = {}
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None

    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="seldon-job-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def enqueue(self, kind: str, payload: dict[str, Any] | None = None) -> JobRecord:
        if kind not in self._handlers:
            raise KeyError(f"unknown job kind: {kind}")
        job = JobRecord(id=str(uuid4()), kind=kind, status="queued", payload=payload or {})
        with self._lock:
            self._jobs[job.id] = job
        self._queue.put(job.id)
        return job

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[JobRecord]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    def run_one(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if job is None:
            raise KeyError(f"job not found: {job_id}")
        self._execute(job)
        return job

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = self._queue.get(timeout=0.1)
            except Empty:
                continue
            job = self.get(job_id)
            if job is not None:
                self._execute(job)
            self._queue.task_done()

    def _execute(self, job: JobRecord) -> None:
        handler = self._handlers[job.kind]
        self._mark(job, status="running", started_at=_now(), error=None)
        try:
            result = handler(job.payload) or {}
        except Exception as exc:  # pragma: no cover - defensive state capture
            self._mark(job, status="failed", completed_at=_now(), error=str(exc))
            return
        self._mark(job, status="completed", completed_at=_now(), result=result)

    def _mark(self, job: JobRecord, **values: Any) -> None:
        with self._lock:
            for key, value in values.items():
                setattr(job, key, value)
            job.updated_at = _now()
