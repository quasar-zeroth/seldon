"""Agent base class with a typed run contract and AgentRun persistence."""
from __future__ import annotations

import time
from typing import Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from seldon.config import SeldonConfig
from seldon.data.repositories import AgentRunRepository
from seldon.llm.openrouter import OpenRouterClient

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class AgentBase(Generic[InputT, OutputT]):
    agent_id: str
    phase: str = "context_gathering"
    model_profile: str = "fast"

    def __init__(self, db: Session, *, config: SeldonConfig | None = None, llm_client: OpenRouterClient | None = None):
        self.db = db
        self.config = config or SeldonConfig()
        self.llm_client = llm_client
        self.runs = AgentRunRepository(db)

    def run(self, payload: InputT, *, parent_run_id: str | None = None) -> tuple[str, OutputT]:
        started = time.perf_counter()
        run = self.runs.create(
            agent_id=self.agent_id,
            phase=self.phase,
            status="running",
            input={"payload": payload.model_dump(mode="json"), "parent_run_id": parent_run_id} if parent_run_id else payload.model_dump(mode="json"),
        )
        try:
            output = self._run(payload, run_id=run.id, parent_run_id=parent_run_id)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self.runs.update(run.id, status="completed", output=output.model_dump(mode="json"), elapsed_ms=elapsed_ms)
            return run.id, output
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=elapsed_ms)
            raise

    def _run(self, payload: InputT, *, run_id: str, parent_run_id: str | None) -> OutputT:  # pragma: no cover - abstract
        raise NotImplementedError


def compact_terms(text: str, *, limit: int = 8) -> list[str]:
    stop = {"what", "will", "where", "when", "does", "this", "that", "with", "from", "into", "about", "price", "trade", "over", "next", "months", "month", "year", "years", "the", "and", "for", "are", "how", "why", "which", "scenario"}
    words = ["".join(ch for ch in w.lower() if ch.isalnum() or ch in {"-", "_"}).strip("-_") for w in text.split()]
    terms: list[str] = []
    for word in words:
        if len(word) < 3 or word in stop or word in terms:
            continue
        terms.append(word)
        if len(terms) >= limit:
            break
    return terms
