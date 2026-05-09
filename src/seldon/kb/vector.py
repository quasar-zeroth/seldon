"""Embedding provider seam with SQLite fallback and OpenRouter-compatible embeddings."""
from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from seldon.config import OpenRouterConfig

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]*", re.I)


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    metadata: dict[str, Any]


class EmbeddingProvider(Protocol):
    backend: str

    def embed(self, text: str) -> EmbeddingResult:
        """Return an embedding vector plus audit metadata."""


def embed_text(text: str, *, dims: int = 64) -> list[float]:
    """Deterministic local embedding used by tests/dev and SQLite fallback."""
    vector = [0.0] * dims
    for token in TOKEN_RE.findall(text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / norm, 6) for v in vector]


class LocalHashEmbeddingProvider:
    backend = "local_hash"

    def __init__(self, *, dims: int = 64):
        self.dims = dims

    def embed(self, text: str) -> EmbeddingResult:
        vector = embed_text(text, dims=self.dims)
        return EmbeddingResult(vector=vector, metadata={"backend": self.backend, "dimensions": len(vector)})


class OpenRouterEmbeddingProvider:
    """OpenAI-compatible embeddings client configured from OpenRouterConfig.

    The provider intentionally mirrors OpenRouter's OpenAI-style API shape. If a
    deployment routes embeddings through a compatible gateway, this can be used
    directly; local tests keep using ``LocalHashEmbeddingProvider``.
    """

    backend = "openrouter_embeddings"

    def __init__(self, config: OpenRouterConfig, *, api_key: str | None = None, http_client: httpx.Client | None = None):
        self.config = config
        self.api_key = api_key
        self._client = http_client

    def _headers(self) -> dict[str, str]:
        key = self.api_key or os.getenv(self.config.api_key_env)
        headers = {"Content-Type": "application/json", "X-Title": self.config.app_name}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if self.config.site_url:
            headers["HTTP-Referer"] = self.config.site_url
        return headers

    def embed(self, text: str) -> EmbeddingResult:
        client = self._client or httpx.Client(timeout=self.config.timeout_seconds)
        close_client = self._client is None
        try:
            response = client.post(
                f"{self.config.base_url.rstrip('/')}/embeddings",
                headers=self._headers(),
                json={"model": self.config.embedding_model, "input": text},
            )
            response.raise_for_status()
            raw = response.json()
        finally:
            if close_client:
                client.close()
        data = raw.get("data") or []
        if not data or not isinstance(data[0], dict) or not isinstance(data[0].get("embedding"), list):
            raise ValueError("Embedding response did not contain data[0].embedding")
        vector = [float(v) for v in data[0]["embedding"]]
        return EmbeddingResult(
            vector=vector,
            metadata={
                "backend": self.backend,
                "model": raw.get("model") or self.config.embedding_model,
                "dimensions": len(vector),
                "usage": raw.get("usage") or {},
            },
        )


def embedding_provider_from_config(config: OpenRouterConfig | None = None, *, prefer_remote: bool = False) -> EmbeddingProvider:
    config = config or OpenRouterConfig()
    if prefer_remote:
        return OpenRouterEmbeddingProvider(config)
    return LocalHashEmbeddingProvider()


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right:
        return 0.0
    n = min(len(left), len(right))
    dot = sum(left[i] * right[i] for i in range(n))
    ln = math.sqrt(sum(v * v for v in left[:n])) or 1.0
    rn = math.sqrt(sum(v * v for v in right[:n])) or 1.0
    return dot / (ln * rn)


def pgvector_literal(vector: list[float]) -> str:
    """Format a vector for pgvector casts, e.g. '[0.1,0.2]'::vector."""
    return "[" + ",".join(f"{float(v):.9g}" for v in vector) + "]"
