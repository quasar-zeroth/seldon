"""DuckDuckGo search provider.

Implements the `ExternalRetrievalProvider` protocol. No API key required.

Search uses the `ddgs` library (the maintained successor to `duckduckgo-search`).
If the library is missing or rate-limited, we fall back to scraping
`html.duckduckgo.com` directly via httpx + BeautifulSoup so the pipeline keeps
working in degraded mode.

Fetch uses trafilatura to extract readable text from result URLs, with httpx as
the HTTP client. Per-domain throttling prevents hammering a single source.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from seldon.agents.retrieval import (
    ExternalSearchResult,
    RawDocument,
    normalize_document_text,
)
from seldon.config import RetrievalConfig

logger = logging.getLogger(__name__)

_DDG_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"


class DuckDuckGoProvider:
    """DuckDuckGo-backed search + fetch provider."""

    name = "duckduckgo"

    def __init__(self, config: RetrievalConfig):
        self.config = config
        self._last_domain_request_ms: dict[str, float] = defaultdict(float)

    # ----------------- search -----------------

    def search(self, query: str, *, limit: int = 5) -> list[ExternalSearchResult]:
        cap = min(limit, self.config.per_subquery_limit)
        results = self._search_via_ddgs(query, cap)
        if not results:
            results = self._search_via_html(query, cap)
        return results[:cap]

    def _search_via_ddgs(self, query: str, limit: int) -> list[ExternalSearchResult]:
        try:
            from ddgs import DDGS  # type: ignore
        except Exception as exc:
            logger.debug("ddgs_unavailable", extra={"event": "ddgs_unavailable", "error": str(exc)})
            return []
        try:
            with DDGS(timeout=self.config.fetch_timeout_seconds) as ddgs:
                hits = list(ddgs.text(query, max_results=limit, safesearch="moderate"))
        except Exception as exc:
            logger.info("ddgs_search_failed", extra={"event": "ddgs_search_failed", "query": query, "error": str(exc)})
            return []
        ranked: list[ExternalSearchResult] = []
        for idx, hit in enumerate(hits):
            url = hit.get("href") or hit.get("url")
            title = (hit.get("title") or "Untitled").strip()
            snippet = (hit.get("body") or hit.get("snippet") or "").strip()
            if not url:
                continue
            ranked.append(
                ExternalSearchResult(
                    query=query,
                    title=title,
                    url=url,
                    snippet=snippet,
                    source_name=_domain(url) or "DuckDuckGo",
                    source_type="web_search",
                    score=max(0.1, 1.0 - idx * 0.1),
                    metadata={"provider": self.name, "raw": hit},
                )
            )
        return ranked

    def _search_via_html(self, query: str, limit: int) -> list[ExternalSearchResult]:
        """Fallback: scrape html.duckduckgo.com directly. Used when ddgs lib is missing."""
        headers = {"User-Agent": self.config.user_agent}
        try:
            with httpx.Client(timeout=self.config.fetch_timeout_seconds, headers=headers, follow_redirects=True) as client:
                response = client.post(_DDG_HTML_ENDPOINT, data={"q": query})
                response.raise_for_status()
                html = response.text
        except Exception as exc:
            logger.info("ddg_html_search_failed", extra={"event": "ddg_html_search_failed", "query": query, "error": str(exc)})
            return []
        soup = BeautifulSoup(html, "html.parser")
        results: list[ExternalSearchResult] = []
        for idx, result_div in enumerate(soup.select("div.result")):
            if idx >= limit:
                break
            anchor = result_div.select_one("a.result__a")
            snippet_el = result_div.select_one(".result__snippet")
            if anchor is None:
                continue
            url = anchor.get("href") or ""
            title = anchor.get_text(strip=True)
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            if not url:
                continue
            results.append(
                ExternalSearchResult(
                    query=query,
                    title=title,
                    url=url,
                    snippet=snippet,
                    source_name=_domain(url) or "DuckDuckGo",
                    source_type="web_search",
                    score=max(0.1, 1.0 - idx * 0.1),
                    metadata={"provider": self.name, "via": "html_fallback"},
                )
            )
        return results

    # ----------------- fetch -----------------

    def fetch(self, result: ExternalSearchResult) -> RawDocument | None:
        if not result.url:
            return None
        self._respect_throttle(result.url)
        html = self._fetch_url(result.url)
        if not html:
            return None
        text = self._extract_text(html, result.url)
        if not text:
            return None
        normalized = normalize_document_text(text)
        if not normalized:
            return None
        return RawDocument(
            title=result.title or "Untitled",
            content=normalized[: 16_000],
            url=result.url,
            source_name=result.source_name or _domain(result.url) or "Web",
            source_type="web_document",
            original_snippet=result.snippet or normalized[:300],
            published_at=result.published_at,
            metadata={**result.metadata, "provider": self.name, "fetched_bytes": len(normalized)},
        )

    def _respect_throttle(self, url: str) -> None:
        domain = _domain(url)
        if not domain:
            return
        throttle_ms = self.config.per_domain_throttle_ms
        now_ms = time.monotonic() * 1000
        last_ms = self._last_domain_request_ms[domain]
        wait_ms = throttle_ms - (now_ms - last_ms)
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
        self._last_domain_request_ms[domain] = time.monotonic() * 1000

    def _fetch_url(self, url: str) -> str | None:
        headers = {"User-Agent": self.config.user_agent, "Accept": "text/html,*/*"}
        last_error: str | None = None
        for attempt in range(2):  # one retry on transient (429/5xx/network) failures
            try:
                with httpx.Client(timeout=self.config.fetch_timeout_seconds, headers=headers, follow_redirects=True) as client:
                    response = client.get(url)
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    last_error = f"http_{response.status_code}"
                    time.sleep(0.5 * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    logger.info("fetch_skipped", extra={"event": "fetch_skipped", "url": url, "status": response.status_code})
                    return None
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type and "text" not in content_type:
                    logger.info("fetch_skipped_non_html", extra={"event": "fetch_skipped_non_html", "url": url, "content_type": content_type})
                    return None
                return response.text
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.5 * (attempt + 1))
        # Surface fetch failures at info (not debug) so silent zero-document runs
        # are diagnosable from the logs.
        logger.info("fetch_failed", extra={"event": "fetch_failed", "url": url, "error": last_error})
        return None

    def _extract_text(self, html: str, url: str) -> str | None:
        try:
            import trafilatura  # type: ignore

            text = trafilatura.extract(html, url=url, favor_recall=True, include_comments=False)
            if text:
                return text
        except Exception:
            pass
        # Fallback: BeautifulSoup tag-strip.
        try:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
                tag.decompose()
            return soup.get_text("\n", strip=True)
        except Exception:
            return None


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlparse(url).netloc or None
    except Exception:
        return None


__all__ = ["DuckDuckGoProvider"]
