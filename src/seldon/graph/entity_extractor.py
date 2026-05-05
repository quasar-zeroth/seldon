"""EntityExtractor: uses LLM to extract entities and relations from pipeline outputs."""
from __future__ import annotations

import json
from typing import Any

from rich.console import Console

from seldon.llm import LLMClientProtocol, NullLLMClient
from seldon.graph.knowledge_graph import KnowledgeGraph

console = Console(stderr=True)

EXTRACTION_SYSTEM = """You are an entity extraction system for financial news analysis.

Extract entities and relations from the provided text. Respond with JSON:
{
  "entities": [
    {
      "type": "Topic|Article|Ticker|Prediction|Bet|Trade|Source|Company|Sector|Person|Event",
      "id": "unique-kebab-id",
      "name": "Display Name",
      "attrs": {"key": "value"}
    }
  ],
  "relations": [
    {
      "source_type": "EntityType",
      "source_id": "source-id",
      "target_type": "EntityType",
      "target_id": "target-id",
      "relation": "mentions|covers|caused_by|impacts|related_to|issued_by|belongs_to|predicted_by"
    }
  ]
}

Focus on:
- Companies and their tickers
- Sectors affected
- Key people (executives, analysts)
- Events (earnings, regulatory actions, product launches)
- Topics (macro themes, geopolitical events)
- Relations between entities

Keep IDs as short kebab-case slugs.
"""


class EntityExtractor:
    """Extract entities and relations from pipeline outputs and add to knowledge graph."""

    def __init__(
        self,
        entity_extraction_model: str | None = None,
        entity_extraction_model_profile: str = "fast",
        llm_client: LLMClientProtocol | None = None,
    ):
        self.model = entity_extraction_model
        self.model_profile = entity_extraction_model_profile
        self.llm = llm_client or NullLLMClient()

    def _extract_and_add(self, text: str, graph: KnowledgeGraph, context_note: str = "") -> dict:
        """Call LLM to extract entities, then add them to the graph."""
        prompt = f"{context_note}\n\n{text[:2000]}" if context_note else text[:2000]

        result = self.llm.complete_json(
            messages=[{"role": "user", "content": prompt}],
            system=EXTRACTION_SYSTEM,
            model=self.model,
            model_profile=self.model_profile,
            agent="entity_extractor",
        )

        if not result:
            return {"entities_added": 0, "relations_added": 0}

        entities_added = 0
        relations_added = 0
        node_map: dict[str, str] = {}  # "Type:id" -> graph node_id

        for entity in result.get("entities", []):
            try:
                etype = entity.get("type", "Event")
                eid = entity.get("id", "unknown")
                name = entity.get("name", eid)
                attrs = entity.get("attrs", {})
                if isinstance(attrs, dict):
                    attrs["name"] = name
                else:
                    attrs = {"name": name}

                node_id = graph.add_entity(etype, eid, **attrs)
                node_map[f"{etype}:{eid}"] = node_id
                entities_added += 1
            except Exception as e:
                console.print(f"[dim]Entity extraction error: {e}[/dim]")

        for relation in result.get("relations", []):
            try:
                src_type = relation.get("source_type", "")
                src_id = relation.get("source_id", "")
                tgt_type = relation.get("target_type", "")
                tgt_id = relation.get("target_id", "")
                rel = relation.get("relation", "related_to")

                src_node = node_map.get(f"{src_type}:{src_id}") or f"{src_type}:{src_id}"
                tgt_node = node_map.get(f"{tgt_type}:{tgt_id}") or f"{tgt_type}:{tgt_id}"

                graph.add_relation(src_node, tgt_node, rel)
                relations_added += 1
            except Exception as e:
                console.print(f"[dim]Relation extraction error: {e}[/dim]")

        return {"entities_added": entities_added, "relations_added": relations_added}

    def extract_from_article(self, article_data: dict, graph: KnowledgeGraph) -> dict:
        """
        Extract entities and relations from a news article.
        Adds Article node and links to Sources, Tickers, Topics, Companies, etc.
        """
        title = article_data.get("title", "")
        content = article_data.get("content", article_data.get("summary", ""))
        source = article_data.get("source", article_data.get("feed_name", ""))
        url = article_data.get("url", "")
        article_id = article_data.get("id", article_data.get("slug", title[:40].lower().replace(" ", "-")))
        tickers = article_data.get("tickers", [])
        topics = article_data.get("topics", [])

        # First, add the article node
        article_node = graph.add_entity(
            "Article",
            article_id,
            name=title,
            url=url,
            source=source,
        )

        # Add source node and link
        if source:
            src_node = graph.add_entity("Source", source.lower().replace(" ", "-"), name=source)
            graph.add_relation(article_node, src_node, "issued_by")

        # Add ticker nodes and link
        for ticker in tickers:
            ticker_node = graph.add_entity("Ticker", ticker.upper(), name=ticker.upper())
            graph.add_relation(article_node, ticker_node, "mentions")

        # Add topic nodes and link
        for topic in topics:
            topic_id = topic.lower().replace(" ", "-")
            topic_node = graph.add_entity("Topic", topic_id, name=topic)
            graph.add_relation(article_node, topic_node, "covers")

        # LLM extraction for deeper entities
        text = f"Title: {title}\n\nContent: {content[:1000]}"
        llm_result = self._extract_and_add(
            text, graph,
            context_note=f"Extract entities from this financial news article about {', '.join(tickers) or 'general markets'}:"
        )

        return {
            "article_node": article_node,
            "entities_added": llm_result["entities_added"] + len(tickers) + len(topics) + (1 if source else 0),
            "relations_added": llm_result["relations_added"],
        }

    def extract_from_prediction(self, prediction_data: dict, graph: KnowledgeGraph) -> dict:
        """
        Link a prediction to its related topics and tickers.
        """
        slug = prediction_data.get("slug", "unknown-prediction")
        title = prediction_data.get("title", slug)
        category = prediction_data.get("category", "")
        tickers = prediction_data.get("tickers", [])
        confidence = prediction_data.get("confidence", 0)
        rationale = prediction_data.get("rationale", "")

        # Add prediction node
        pred_node = graph.add_entity(
            "Prediction",
            slug,
            name=title,
            category=category,
            confidence=confidence,
        )

        # Link to tickers
        for ticker in tickers:
            ticker_node = graph.add_entity("Ticker", ticker.upper(), name=ticker.upper())
            graph.add_relation(pred_node, ticker_node, "impacts")

        # Link to category/sector topic
        if category:
            cat_id = category.lower().replace(" ", "-")
            cat_node = graph.add_entity("Topic", cat_id, name=category)
            graph.add_relation(pred_node, cat_node, "belongs_to")

        # LLM extraction from rationale
        llm_result = {"entities_added": 0, "relations_added": 0}
        if rationale:
            llm_result = self._extract_and_add(
                f"Prediction: {title}\n\nRationale: {rationale}",
                graph,
                context_note="Extract entities from this financial prediction:",
            )

        return {
            "prediction_node": pred_node,
            "entities_added": llm_result["entities_added"] + len(tickers) + (1 if category else 0),
            "relations_added": llm_result["relations_added"],
        }

    def extract_from_bet(self, bet_data: dict, graph: KnowledgeGraph) -> dict:
        """
        Link a bet to its prediction and ticker.
        """
        slug = bet_data.get("slug", "unknown-bet")
        title = bet_data.get("title", slug)
        ticker = bet_data.get("asset_ticker", "")
        direction = bet_data.get("direction", "")
        prediction_slug = bet_data.get("prediction_slug", "")
        thesis = bet_data.get("thesis", "")

        # Add bet node
        bet_node = graph.add_entity(
            "Bet",
            slug,
            name=title,
            ticker=ticker,
            direction=direction,
        )

        # Link to ticker
        if ticker:
            ticker_node = graph.add_entity("Ticker", ticker.upper(), name=ticker.upper())
            graph.add_relation(bet_node, ticker_node, "impacts")

        # Link to prediction
        if prediction_slug:
            pred_node_id = f"Prediction:{prediction_slug}"
            graph.add_relation(bet_node, pred_node_id, "predicted_by")

        # Also link company node
        company_nodes_added = 0
        if ticker:
            company_node = graph.add_entity("Company", ticker.lower(), ticker=ticker)
            graph.add_relation(f"Ticker:{ticker.upper()}", company_node, "belongs_to")
            company_nodes_added = 1

        return {
            "bet_node": bet_node,
            "entities_added": company_nodes_added + (1 if ticker else 0) + (1 if prediction_slug else 0),
            "relations_added": 0,
        }
