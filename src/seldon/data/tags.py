"""Conservative lexical tags; agents supply richer evidence-grounded labels."""

from __future__ import annotations

import re


def normalize_tag(value: str) -> str:
    tag = re.sub(r"[^a-z0-9:]+", "-", value.strip().lower()).strip("-")
    return {
        "datacenter": "data-center",
        "data-centre": "data-center",
        "data-centers": "data-center",
    }.get(tag, tag)


def entity_tags(
    name: str, description: str, kind: str, supplied: list[str] | None = None
) -> list[str]:
    tags = {normalize_tag(t) for t in supplied or []}
    if any(len(tag) > 80 for tag in tags) or len(tags) > 40:
        raise ValueError("Use at most 40 tags, each at most 80 characters")
    text = f"{name} {description}".casefold()
    tags.add(f"type:{kind}")
    if kind == "entity" and not any(word in text for word in ("programme", "program;")):
        if re.search(
            r"\bdata[ -]?(?:center|centre)s?\b|\bai (?:campus|infrastructure inventory|factory)\b",
            text,
        ):
            tags.add("data-center")
    return sorted(tags - {""})
