"""Google News RSS retrieval provider.

Implements the ``ExternalRetrievalProvider`` protocol against Google News' public
RSS search feed (no API key required), so ``source_type=news_article`` evidence
actually enters the KB instead of everything being generic web search.

Search parses the RSS feed; fetch tries to read the full article via trafilatura
but degrades to the RSS headline + snippet, so a news item still contributes
evidence even when the publisher page can't be scraped.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from seldon.agents.retrieval import ExternalSearchResult, RawDocument, normalize_document_text
from seldon.config import RetrievalConfig

logger = logging.getLogger(__name__)

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


class GoogleNewsRSSProvider:
    """Google News RSS-backed search + article fetch provider."""

    name = "google_news"

    def __init__(self, config: RetrievalConfig, *, http_client: httpx.Client | None = None):
        self.config = config
        self._client = http_client

    def _get(self, url: str) -> httpx.Response:
        headers = {"User-Agent": self.config.user_agent, "Accept": "text/html,application/rss+xml,application/xml,*/*"}
        client = self._client or httpx.Client(timeout=self.config.fetch_timeout_seconds, headers=headers, follow_redirects=True)
        close_client = self._client is None
        try:
            return client.get(url)
        finally:
            if close_client:
                client.close()

    # ----------------- search -----------------

    def search(self, query: str, *, limit: int = 5) -> list[ExternalSearchResult]:
        cap = min(limit, self.config.per_subquery_limit)
        url = f"{_GOOGLE_NEWS_RSS}?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        try:
            response = self._get(url)
            response.raise_for_status()
            xml = response.text
        except Exception as exc:
            logger.info("google_news_search_failed", extra={"event": "google_news_search_failed", "query": query, "error": str(exc)})
            return []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            logger.info("google_news_parse_failed", extra={"event": "google_news_parse_failed", "query": query, "error": str(exc)})
            return []

        results: list[ExternalSearchResult] = []
        for idx, item in enumerate(root.iter("item")):
            if idx >= cap:
                break
            title = (item.findtext("title") or "Untitled").strip()
            link = (item.findtext("link") or "").strip()
            if not link:
                continue
            snippet = _strip_html(item.findtext("description") or "")
            source_el = item.find("source")
            source_name = (source_el.text.strip() if source_el is not None and source_el.text else "Google News")
            results.append(
                ExternalSearchResult(
                    query=query,
                    title=title,
                    url=link,
                    snippet=snippet,
                    source_name=source_name,
                    source_type="news_article",
                    published_at=_parse_date(item.findtext("pubDate")),
                    score=max(0.1, 1.0 - idx * 0.1),
                    metadata={"provider": self.name},
                )
            )
        return results

    # ----------------- fetch -----------------

    def fetch(self, result: ExternalSearchResult) -> RawDocument | None:
        text = self._fetch_article_text(result.url) if result.url else None
        content = normalize_document_text(text) if text else (result.snippet or result.title)
        if not content:
            return None
        return RawDocument(
            title=result.title or "Untitled",
            content=content[:16_000],
            url=result.url,
            source_name=result.source_name or "Google News",
            source_type="news_article",
            original_snippet=result.snippet or content[:300],
            published_at=result.published_at,
            metadata={**result.metadata, "provider": self.name, "fetched_full_text": bool(text)},
        )

    def _fetch_article_text(self, url: str) -> str | None:
        try:
            response = self._get(url)
            if response.status_code >= 400 or "html" not in response.headers.get("content-type", ""):
                return None
            html = response.text
        except Exception:
            return None
        try:
            import trafilatura  # type: ignore

            return trafilatura.extract(html, url=url, favor_recall=True, include_comments=False)
        except Exception:
            return None


def _strip_html(value: str) -> str:
    if not value:
        return ""
    try:
        return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    except Exception:
        return value


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


__all__ = ["GoogleNewsRSSProvider"]
