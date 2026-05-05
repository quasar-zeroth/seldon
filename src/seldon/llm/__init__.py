"""LLM protocols and clients for The Seldon Project."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMClientProtocol(Protocol):
    def complete_json(self, messages: list[dict], system: str | None = None, **kwargs: Any) -> dict:
        ...


@runtime_checkable
class AsyncLLMClientProtocol(Protocol):
    async def acomplete_json(self, messages: list[dict], system: str | None = None, **kwargs: Any) -> dict:
        ...


class NullLLMClient:
    """Safe default LLM client used when no host application adapter is supplied."""

    def complete_json(self, messages: list[dict], system: str | None = None, **kwargs: Any) -> dict:
        return {}

    async def acomplete_json(self, messages: list[dict], system: str | None = None, **kwargs: Any) -> dict:
        return {}


from .openrouter import (  # noqa: E402
    LLMResponseError,
    ModelInvocationRecorder,
    OpenRouterClient,
    OpenRouterResponse,
    extract_json_object,
)

__all__ = [
    "AsyncLLMClientProtocol",
    "LLMClientProtocol",
    "LLMResponseError",
    "ModelInvocationRecorder",
    "NullLLMClient",
    "OpenRouterClient",
    "OpenRouterResponse",
    "extract_json_object",
]
