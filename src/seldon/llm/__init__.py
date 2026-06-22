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
    LLMAuthenticationError,
    LLMModelUnavailableError,
    LLMResponseError,
    ModelInvocationRecorder,
    OpenRouterClient,
    OpenRouterResponse,
    extract_json_object,
)

# Provider-neutral name for the OpenAI-compatible client. The class serves both
# OpenRouter and NVIDIA NIM (and any OpenAI-compatible endpoint); the concrete
# provider is carried in the config, not the class. New code should prefer this.
LLMClient = OpenRouterClient


def build_llm_client(config: Any, *, recorder: "ModelInvocationRecorder | None" = None, **kwargs: Any) -> OpenRouterClient:
    """Construct the LLM client for the active provider.

    Accepts a ``SeldonConfig`` (uses ``.llm``) or an ``LLMProviderConfig``
    directly. Both OpenRouter and NVIDIA NIM speak the same OpenAI-compatible
    wire format, so one client class serves both — the provider/base_url/key env
    var/model IDs all live in the config. Mirrors
    ``seldon.agents.providers.build_providers_from_config``.
    """
    from seldon.config import LLMProviderConfig, SeldonConfig

    llm_config = config.llm if isinstance(config, SeldonConfig) else config
    if not isinstance(llm_config, LLMProviderConfig):
        raise TypeError(f"build_llm_client expected SeldonConfig or LLMProviderConfig, got {type(config)!r}")
    return OpenRouterClient(llm_config, recorder=recorder, **kwargs)


__all__ = [
    "AsyncLLMClientProtocol",
    "LLMAuthenticationError",
    "LLMClient",
    "LLMClientProtocol",
    "LLMModelUnavailableError",
    "LLMResponseError",
    "ModelInvocationRecorder",
    "NullLLMClient",
    "OpenRouterClient",
    "OpenRouterResponse",
    "build_llm_client",
    "extract_json_object",
]
