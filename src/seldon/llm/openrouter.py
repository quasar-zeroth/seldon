"""OpenRouter-compatible LLM adapter.

The adapter intentionally exposes the same small ``complete_json`` surface used by
legacy Seldon code while adding async support, profile-based model selection,
fallbacks, JSON recovery, and durable invocation metadata.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from seldon.config import AgentModelConfig, OpenRouterConfig


class LLMResponseError(RuntimeError):
    """Raised when an LLM response cannot be parsed or validated."""


@dataclass(frozen=True)
class OpenRouterResponse:
    payload: dict[str, Any]
    model: str
    raw: dict[str, Any]
    metadata: dict[str, Any]


class ModelInvocationRecorder:
    """Append-only JSONL recorder for Phase B model invocation metadata.

    Phase C will move this behind the relational ``model_invocations`` table.
    Keeping a file-backed recorder now gives every run an auditable trail without
    forcing the DB migration early.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else None

    def record(self, row: dict[str, Any]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str, sort_keys=True) + "\n")


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response.

    Handles clean JSON, markdown fences, and prose-wrapped JSON. This is the
    tool-free fallback for models that do not reliably honor strict JSON mode.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise LLMResponseError("OpenRouter response did not contain a JSON object")
        value = json.loads(stripped[start : end + 1])

    if not isinstance(value, dict):
        raise LLMResponseError("OpenRouter response JSON was not an object")
    return value


def _validate_payload(payload: dict[str, Any], schema: Any | None) -> dict[str, Any]:
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


class OpenRouterClient:
    """OpenAI-compatible client for OpenRouter chat completions."""

    def __init__(
        self,
        config: OpenRouterConfig | None = None,
        *,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        async_http_client: httpx.AsyncClient | None = None,
        recorder: ModelInvocationRecorder | None = None,
    ):
        self.config = config or OpenRouterConfig()
        self.api_key = api_key
        self._client = http_client
        self._async_client = async_http_client
        self.recorder = recorder or ModelInvocationRecorder()

    def model_for_profile(self, profile: str | None) -> str:
        return self.config.model_for_profile(profile or "balanced")

    def candidate_models(self, *, model: str | None = None, model_profile: str | None = None) -> list[str]:
        primary = model or self.model_for_profile(model_profile)
        seen: set[str] = set()
        candidates: list[str] = []
        for candidate in [primary, *self.config.fallback_models]:
            if candidate and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
        return candidates

    def _headers(self) -> dict[str, str]:
        key = self.api_key or os.getenv(self.config.api_key_env)
        headers = {"Content-Type": "application/json", "X-Title": self.config.app_name}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if self.config.site_url:
            headers["HTTP-Referer"] = self.config.site_url
        return headers

    def _payload(
        self,
        messages: list[dict],
        *,
        system: str | None,
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        top_p: float | None,
        reasoning_effort: str | None,
        response_format: dict[str, Any] | None,
    ) -> dict[str, Any]:
        outbound = ([{"role": "system", "content": system}] if system else []) + list(messages)
        payload: dict[str, Any] = {"model": model, "messages": outbound}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if top_p is not None:
            payload["top_p"] = top_p
        if reasoning_effort is not None:
            payload["reasoning"] = {"effort": reasoning_effort}
        if response_format is not None:
            payload["response_format"] = response_format
        return payload

    def build_payload(self, messages: list[dict], system: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """Public helper used by tests and host apps to inspect request bodies."""
        profile_override = kwargs.get("model_profile")
        model = kwargs.get("model") or self.model_for_profile(profile_override)
        agent_cfg = kwargs.get("agent_config")
        if isinstance(agent_cfg, AgentModelConfig) and kwargs.get("model") is None:
            model = agent_cfg.model or self.model_for_profile(profile_override or agent_cfg.model_profile)
        return self._payload(
            messages,
            system=system,
            model=model,
            temperature=kwargs.get("temperature") if kwargs.get("temperature") is not None else getattr(agent_cfg, "temperature", None),
            max_tokens=kwargs.get("max_tokens") if kwargs.get("max_tokens") is not None else getattr(agent_cfg, "max_tokens", None),
            top_p=kwargs.get("top_p"),
            reasoning_effort=kwargs.get("reasoning_effort"),
            response_format=kwargs.get("response_format", {"type": "json_object"}),
        )

    def complete_json(self, messages: list[dict], system: str | None = None, **kwargs: Any) -> dict:
        return self.complete_json_with_metadata(messages, system=system, **kwargs).payload

    def complete_json_with_metadata(self, messages: list[dict], system: str | None = None, **kwargs: Any) -> OpenRouterResponse:
        last_error: Exception | None = None
        for model in self.candidate_models(model=kwargs.get("model"), model_profile=kwargs.get("model_profile")):
            try:
                return self._complete_once(model, messages, system, kwargs)
            except Exception as exc:  # try fallback models on transport/status/parse/validation failures
                last_error = exc
        raise LLMResponseError(f"All OpenRouter model candidates failed: {last_error}") from last_error

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        if response is not None and response.headers.get("Retry-After"):
            try:
                return float(response.headers["Retry-After"])
            except ValueError:
                pass
        return min(8.0, 0.25 * (2 ** attempt)) + random.uniform(0, 0.05)

    def _should_retry(self, response: httpx.Response | None, exc: Exception | None) -> bool:
        if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
            return True
        return response is not None and response.status_code in {429, 500, 502, 503, 504}

    async def _async_sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def _complete_once(self, model: str, messages: list[dict], system: str | None, kwargs: dict[str, Any]) -> OpenRouterResponse:
        started = time.perf_counter()
        payload = self.build_payload(messages, system=system, **{**kwargs, "model": model})
        client = self._client or httpx.Client(timeout=self.config.timeout_seconds)
        close_client = self._client is None
        raw: dict[str, Any] = {}
        error: str | None = None
        max_retries = int(kwargs.get("max_retries", 2))
        try:
            for attempt in range(max_retries + 1):
                response: httpx.Response | None = None
                exc: Exception | None = None
                try:
                    response = client.post(
                        f"{self.config.base_url.rstrip('/')}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
                    if self._should_retry(response, None) and attempt < max_retries:
                        time.sleep(self._retry_delay(response, attempt))
                        continue
                    response.raise_for_status()
                    raw = response.json()
                    parsed = self._parse_response(raw, kwargs.get("schema"))
                    metadata = self._metadata(raw, model, started, error=None)
                    self.recorder.record({**metadata, "agent": kwargs.get("agent"), "agent_run_id": kwargs.get("agent_run_id"), "repair_attempt": kwargs.get("repair_attempt"), "escalated_from": kwargs.get("escalated_from"), "ok": True})
                    return OpenRouterResponse(parsed, model=model, raw=raw, metadata=metadata)
                except Exception as retry_exc:
                    exc = retry_exc
                    if self._should_retry(response, exc) and attempt < max_retries:
                        time.sleep(self._retry_delay(response, attempt))
                        continue
                    raise
        except Exception as exc:
            error = str(exc)
            self.recorder.record({**self._metadata(raw, model, started, error=error), "agent": kwargs.get("agent"), "agent_run_id": kwargs.get("agent_run_id"), "repair_attempt": kwargs.get("repair_attempt"), "escalated_from": kwargs.get("escalated_from"), "ok": False})
            raise
        finally:
            if close_client:
                client.close()
        raise LLMResponseError("unreachable OpenRouter retry state")

    async def acomplete_json(self, messages: list[dict], system: str | None = None, **kwargs: Any) -> dict:
        return (await self.acomplete_json_with_metadata(messages, system=system, **kwargs)).payload

    async def acomplete_json_with_metadata(self, messages: list[dict], system: str | None = None, **kwargs: Any) -> OpenRouterResponse:
        last_error: Exception | None = None
        for model in self.candidate_models(model=kwargs.get("model"), model_profile=kwargs.get("model_profile")):
            try:
                return await self._acomplete_once(model, messages, system, kwargs)
            except Exception as exc:
                last_error = exc
        raise LLMResponseError(f"All OpenRouter model candidates failed: {last_error}") from last_error

    async def _acomplete_once(self, model: str, messages: list[dict], system: str | None, kwargs: dict[str, Any]) -> OpenRouterResponse:
        started = time.perf_counter()
        payload = self.build_payload(messages, system=system, **{**kwargs, "model": model})
        client = self._async_client or httpx.AsyncClient(timeout=self.config.timeout_seconds)
        close_client = self._async_client is None
        raw: dict[str, Any] = {}
        max_retries = int(kwargs.get("max_retries", 2))
        try:
            for attempt in range(max_retries + 1):
                response: httpx.Response | None = None
                try:
                    response = await client.post(
                        f"{self.config.base_url.rstrip('/')}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                    )
                    if self._should_retry(response, None) and attempt < max_retries:
                        await self._async_sleep(self._retry_delay(response, attempt))
                        continue
                    response.raise_for_status()
                    raw = response.json()
                    parsed = self._parse_response(raw, kwargs.get("schema"))
                    metadata = self._metadata(raw, model, started, error=None)
                    self.recorder.record({**metadata, "agent": kwargs.get("agent"), "agent_run_id": kwargs.get("agent_run_id"), "repair_attempt": kwargs.get("repair_attempt"), "escalated_from": kwargs.get("escalated_from"), "ok": True})
                    return OpenRouterResponse(parsed, model=model, raw=raw, metadata=metadata)
                except Exception as exc:
                    if self._should_retry(response, exc) and attempt < max_retries:
                        await self._async_sleep(self._retry_delay(response, attempt))
                        continue
                    raise
        except Exception as exc:
            self.recorder.record({**self._metadata(raw, model, started, error=str(exc)), "agent": kwargs.get("agent"), "agent_run_id": kwargs.get("agent_run_id"), "repair_attempt": kwargs.get("repair_attempt"), "escalated_from": kwargs.get("escalated_from"), "ok": False})
            raise
        finally:
            if close_client:
                await client.aclose()
        raise LLMResponseError("unreachable OpenRouter retry state")

    def _parse_response(self, raw: dict[str, Any], schema: Any | None) -> dict[str, Any]:
        choices = raw.get("choices") or []
        if not choices:
            raise LLMResponseError("OpenRouter response had no choices")
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        if not isinstance(content, str):
            raise LLMResponseError("OpenRouter response content was not text")
        payload = extract_json_object(content)
        try:
            return _validate_payload(payload, schema)
        except ValidationError as exc:
            raise LLMResponseError(f"OpenRouter JSON failed schema validation: {exc}") from exc

    def _metadata(self, raw: dict[str, Any], model: str, started: float, error: str | None) -> dict[str, Any]:
        return {
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "model": raw.get("model") or model,
            "provider": raw.get("provider"),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "usage": raw.get("usage", {}),
            "cost": raw.get("usage", {}).get("cost") or raw.get("cost"),
            "error": error,
        }
