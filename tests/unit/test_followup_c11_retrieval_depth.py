"""Retrieval depth: capped query variations + Google News RSS provider."""
from __future__ import annotations

import httpx

from seldon.agents.providers.news import GoogleNewsRSSProvider
from seldon.agents.retrieval import query_variations
from seldon.config import RetrievalConfig

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Gold - Google News</title>
  <item>
    <title>Gold hits record high on Fed cut bets</title>
    <link>https://example.com/gold-record</link>
    <pubDate>Wed, 01 Jan 2025 12:00:00 GMT</pubDate>
    <description>&lt;a href="https://example.com/gold-record"&gt;Gold rallied as investors priced in rate cuts&lt;/a&gt;</description>
    <source url="https://reuters.com">Reuters</source>
  </item>
</channel></rss>"""


def test_query_variations_respects_limit():
    assert query_variations("gold rate cuts", limit=1) == ["gold rate cuts"]
    assert query_variations("gold rate cuts", limit=2) == ["gold rate cuts", "gold rate cuts latest evidence"]
    assert len(query_variations("gold rate cuts", limit=3)) == 3
    # Default preserves the original 3-variation behaviour.
    assert len(query_variations("gold rate cuts")) == 3


def _news_provider(handler) -> GoogleNewsRSSProvider:
    return GoogleNewsRSSProvider(RetrievalConfig(), http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_google_news_search_parses_rss_items():
    def handler(request: httpx.Request) -> httpx.Response:
        if "news.google.com" in str(request.url):
            return httpx.Response(200, text=_RSS)
        return httpx.Response(404)

    results = _news_provider(handler).search("gold", limit=5)
    assert len(results) == 1
    item = results[0]
    assert item.title == "Gold hits record high on Fed cut bets"
    assert item.url == "https://example.com/gold-record"
    assert item.source_name == "Reuters"
    assert item.source_type == "news_article"
    assert item.published_at is not None
    assert "Gold rallied" in item.snippet  # HTML stripped from description


def test_google_news_fetch_falls_back_to_snippet_when_article_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        if "news.google.com" in str(request.url):
            return httpx.Response(200, text=_RSS)
        return httpx.Response(404)  # article page unavailable

    provider = _news_provider(handler)
    [item] = provider.search("gold", limit=5)
    doc = provider.fetch(item)
    assert doc is not None
    assert doc.source_type == "news_article"
    # Headline-level evidence still enters the KB even without the full article.
    assert "Gold rallied" in doc.content
    assert doc.metadata["fetched_full_text"] is False
