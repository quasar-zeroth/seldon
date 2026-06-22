"""External retrieval provider contracts and raw document normalization.

Follow-up C.11(3) starts with a small, testable seam: providers can search and
fetch documents without tying Seldon to one live web/news/forum API. The context
retriever can use these providers in tests or production wiring, while keeping
KB-only behavior available as a deterministic fallback.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field


class ExternalSearchResult(BaseModel):
    query: str
    title: str
    url: str | None = None
    snippet: str = ""
    source_name: str = "External source"
    source_type: str = "web_search"
    published_at: datetime | None = None
    score: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawDocument(BaseModel):
    title: str
    content: str
    url: str | None = None
    source_name: str = "External source"
    source_type: str = "web_document"
    original_snippet: str | None = None
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalRetrievalProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 5) -> list[ExternalSearchResult]:
        """Return ranked external search results for a query variation."""

    def fetch(self, result: ExternalSearchResult) -> RawDocument | None:
        """Fetch/read a search result into a raw document, or return None if unavailable."""


def normalize_document_text(text: str) -> str:
    """Light boilerplate/whitespace normalization for fetched documents."""
    lines = []
    boilerplate = {"cookie", "subscribe", "sign up", "advertisement", "accept all", "privacy policy"}
    for raw_line in text.replace("\r", "\n").split("\n"):
        line = " ".join(raw_line.split())
        if not line:
            continue
        lowered = line.lower()
        if len(line) < 4 or any(marker in lowered for marker in boilerplate):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def relevance_score(query: str, document: RawDocument | ExternalSearchResult) -> float:
    """Simple lexical relevance used for provider-agnostic ranking and tests."""
    haystack = f"{getattr(document, 'title', '')} {getattr(document, 'snippet', '')} {getattr(document, 'content', '')}".lower()
    terms = {term.strip(".,:;!?()[]{}\"'").lower() for term in query.split() if len(term.strip(".,:;!?()[]{}\"'")) >= 3}
    if not terms:
        return float(getattr(document, "score", 0.5))
    overlap = sum(1 for term in terms if term in haystack)
    lexical = overlap / len(terms)
    provider_score = float(getattr(document, "score", 0.5))
    return max(0.0, min(1.0, 0.65 * lexical + 0.35 * provider_score))


def query_variations(query: str, *, limit: int = 3) -> list[str]:
    """Generate up to ``limit`` search variations per subquery.

    Capping the number of variations limits how many engine queries each
    subquery triggers, which is the main driver of 429 rate-limiting seen in
    practice. Default 3 preserves the original behaviour.
    """
    stripped = " ".join(query.split())
    variations = [stripped, f"{stripped} latest evidence", f"{stripped} news analysis"]
    deduped: list[str] = []
    for variation in variations:
        if variation and variation not in deduped:
            deduped.append(variation)
        if len(deduped) >= max(1, limit):
            break
    return deduped


class StaticExternalRetrievalProvider:
    """Small mocked-provider implementation for contract tests and demos."""

    name = "static"

    def __init__(self, documents: list[RawDocument | dict[str, Any]]):
        self.documents = [doc if isinstance(doc, RawDocument) else RawDocument.model_validate(doc) for doc in documents]
        self.search_queries: list[str] = []
        self.fetched_urls: list[str | None] = []

    def search(self, query: str, *, limit: int = 5) -> list[ExternalSearchResult]:
        self.search_queries.append(query)
        ranked = sorted(self.documents, key=lambda doc: relevance_score(query, doc), reverse=True)
        return [
            ExternalSearchResult(
                query=query,
                title=doc.title,
                url=doc.url,
                snippet=doc.original_snippet or doc.content[:300],
                source_name=doc.source_name,
                source_type=doc.source_type,
                published_at=doc.published_at,
                score=relevance_score(query, doc),
                metadata={**doc.metadata, "provider": self.name},
            )
            for doc in ranked[:limit]
        ]

    def fetch(self, result: ExternalSearchResult) -> RawDocument | None:
        self.fetched_urls.append(result.url)
        for doc in self.documents:
            if doc.url and result.url and doc.url == result.url:
                return doc
            if not doc.url and doc.title == result.title:
                return doc
        return RawDocument(
            title=result.title,
            url=result.url,
            source_name=result.source_name,
            source_type=result.source_type,
            content=result.snippet,
            original_snippet=result.snippet,
            published_at=result.published_at,
            metadata=result.metadata,
        )
