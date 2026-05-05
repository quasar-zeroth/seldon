"""LLM protocol and null implementation for seldon package."""
from __future__ import annotations

from typing import Protocol


class LLMClientProtocol(Protocol):
    def complete_json(self, messages: list[dict], system: str | None = None, **kwargs) -> dict:
        ...


class NullLLMClient:
    """Safe default LLM client used when no host application adapter is supplied."""

    def complete_json(self, messages: list[dict], system: str | None = None, **kwargs) -> dict:
        return {}
