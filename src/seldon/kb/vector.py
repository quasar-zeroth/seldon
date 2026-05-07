"""SQLite-friendly deterministic embedding helpers.

This is intentionally lightweight: production deployments can replace this seam
with OpenRouter embeddings + pgvector, while local/dev tests still get semantic-ish
ranking instead of plain substring matching.
"""
from __future__ import annotations

import hashlib
import math
import re

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]*", re.I)


def embed_text(text: str, *, dims: int = 64) -> list[float]:
    vector = [0.0] * dims
    for token in TOKEN_RE.findall(text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / norm, 6) for v in vector]


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right:
        return 0.0
    n = min(len(left), len(right))
    dot = sum(left[i] * right[i] for i in range(n))
    ln = math.sqrt(sum(v * v for v in left[:n])) or 1.0
    rn = math.sqrt(sum(v * v for v in right[:n])) or 1.0
    return dot / (ln * rn)
