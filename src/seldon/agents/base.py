"""Agent base class with a typed run contract and AgentRun persistence."""
from __future__ import annotations

import time
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from seldon.config import AgentModelConfig, SeldonConfig
from seldon.data.repositories import AgentRunRepository, DatabaseModelInvocationRecorder
from seldon.llm.openrouter import LLMResponseError, OpenRouterClient

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


def _validate_model_payload(payload: dict[str, Any], schema: Any | None) -> dict[str, Any]:
    if schema is None:
        return payload
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_validate(payload).model_dump(mode="json")
    if isinstance(schema, BaseModel):
        return schema.__class__.model_validate(payload).model_dump(mode="json")
    if callable(schema):
        validated = schema(payload)
        if isinstance(validated, BaseModel):
            return validated.model_dump(mode="json")
        if isinstance(validated, dict):
            return validated
    return payload


def _payload_confidence(payload: dict[str, Any]) -> float | None:
    value = payload.get("confidence")
    if value is None and isinstance(payload.get("metadata"), dict):
        value = payload["metadata"].get("confidence")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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
        original_llm_client = self.llm_client
        if isinstance(original_llm_client, OpenRouterClient):
            self.llm_client = self._db_recording_llm_client(run.id, original_llm_client)
        self.runs.publish(run.id, "run.started", payload={"agent_id": self.agent_id, "phase": self.phase, "parent_run_id": parent_run_id})
        try:
            output = self._run(payload, run_id=run.id, parent_run_id=parent_run_id)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self.runs.update(run.id, status="completed", output=output.model_dump(mode="json"), elapsed_ms=elapsed_ms)
            self.runs.publish(run.id, "run.completed", payload={"agent_id": self.agent_id, "phase": self.phase, "elapsed_ms": elapsed_ms})
            return run.id, output
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self.runs.update(run.id, status="failed", error=str(exc), elapsed_ms=elapsed_ms)
            self.runs.publish(run.id, "run.failed", payload={"agent_id": self.agent_id, "phase": self.phase, "elapsed_ms": elapsed_ms, "error": str(exc)})
            raise
        finally:
            self.llm_client = original_llm_client

    def _db_recording_llm_client(self, run_id: str, client: OpenRouterClient) -> OpenRouterClient:
        """Clone an OpenRouter client so this run writes invocations to the active DB session.

        The FastAPI app keeps one OpenRouter client at application scope. Cloning avoids
        mutating that shared client while binding model_invocations.agent_run_id to the
        currently executing agent run.
        """
        return OpenRouterClient(
            client.config,
            api_key=client.api_key,
            http_client=getattr(client, "_client", None),
            async_http_client=getattr(client, "_async_client", None),
            recorder=DatabaseModelInvocationRecorder(self.db, agent_run_id=run_id),
        )

    def agent_model_config(self) -> AgentModelConfig:
        configured = getattr(self.config.agents, self.agent_id, None)
        if isinstance(configured, AgentModelConfig):
            return configured
        return AgentModelConfig(model_profile=self.model_profile)

    def llm_complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        run_id: str,
        system: str | None = None,
        schema: Any | None = None,
        repair_retries: int = 1,
        min_confidence: float | None = None,
        escalation_profiles: tuple[str, ...] = ("balanced", "reasoning"),
        **overrides: Any,
    ) -> dict[str, Any]:
        """Call the configured LLM with per-agent defaults, DB audit, repair, and escalation.

        This is the standard helper specialists should use for model-backed work.
        It applies ``config.agents.<agent_id>`` model settings, validates structured
        output, retries with a repair prompt after schema failures, and can escalate
        to stronger model profiles when validation fails or confidence is below a
        caller-supplied threshold.
        """
        if self.llm_client is None:
            raise LLMResponseError(f"{self.agent_id} has no llm_client configured")

        agent_cfg = self.agent_model_config()
        base_profile = overrides.pop("model_profile", None) or agent_cfg.model_profile or self.model_profile
        profiles = [base_profile]
        for profile in escalation_profiles:
            if profile not in profiles:
                profiles.append(profile)

        last_error: Exception | None = None
        working_messages = list(messages)
        for profile_index, profile in enumerate(profiles):
            for repair_attempt in range(repair_retries + 1):
                call_kwargs = {
                    "agent": self.agent_id,
                    "agent_run_id": run_id,
                    "agent_config": agent_cfg,
                    "model_profile": profile,
                    "schema": schema,
                    "temperature": agent_cfg.temperature,
                    "max_tokens": agent_cfg.max_tokens,
                    "escalated_from": base_profile if profile_index else None,
                    "repair_attempt": repair_attempt,
                    **overrides,
                }
                if agent_cfg.model and profile == base_profile:
                    call_kwargs["model"] = agent_cfg.model
                try:
                    if hasattr(self.llm_client, "complete_json_with_metadata"):
                        result = self.llm_client.complete_json_with_metadata(working_messages, system=system, **call_kwargs).payload  # type: ignore[attr-defined]
                    else:
                        result = self.llm_client.complete_json(working_messages, system=system, **call_kwargs)  # type: ignore[union-attr]
                    result = _validate_model_payload(result, schema)
                    confidence = _payload_confidence(result)
                    if min_confidence is not None and confidence is not None and confidence < min_confidence and profile_index < len(profiles) - 1:
                        self.runs.add_message(
                            run_id,
                            "system",
                            f"Escalating {self.agent_id} from {profile} because confidence {confidence:.3f} is below {min_confidence:.3f}.",
                            payload={"confidence": confidence, "threshold": min_confidence, "from_profile": profile, "to_profile": profiles[profile_index + 1]},
                        )
                        break
                    return result
                except (LLMResponseError, ValidationError, ValueError, TypeError) as exc:
                    last_error = exc
                    if repair_attempt < repair_retries:
                        working_messages = [
                            *working_messages,
                            {
                                "role": "user",
                                "content": (
                                    "The previous response failed structured validation. "
                                    "Return only corrected JSON matching the requested schema. "
                                    f"Validation error: {exc}"
                                ),
                            },
                        ]
                        continue
                    if profile_index < len(profiles) - 1:
                        self.runs.add_message(
                            run_id,
                            "system",
                            f"Escalating {self.agent_id} from {profile} after structured-output failure.",
                            payload={"error": str(exc), "from_profile": profile, "to_profile": profiles[profile_index + 1]},
                        )
                        break
                    raise
        raise LLMResponseError(f"{self.agent_id} LLM call failed after repair/escalation attempts: {last_error}") from last_error

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
