"""Tests for KnowledgeGraph (graph/knowledge_graph.py)."""
from __future__ import annotations

import pytest

from seldon.graph.knowledge_graph import KnowledgeGraph


def make_kg(tmp_path) -> KnowledgeGraph:
    return KnowledgeGraph(path=tmp_path / "test_kg.json")


class TestAddEntity:
    def test_add_entity_creates_node(self, tmp_path):
        kg = make_kg(tmp_path)
        kg.add_entity("Topic", "fed-rates-2025", title="Fed Rate Decision 2025")
        assert kg.graph.has_node("Topic:fed-rates-2025")

    def test_add_entity_stores_attributes(self, tmp_path):
        kg = make_kg(tmp_path)
        kg.add_entity("Ticker", "TLT", name="iShares 20+ Year Treasury ETF", sector="Fixed Income")
        node = kg.graph.nodes["Ticker:TLT"]
        assert node.get("name") == "iShares 20+ Year Treasury ETF"
        assert node.get("sector") == "Fixed Income"

    def test_add_entity_updates_existing(self, tmp_path):
        kg = make_kg(tmp_path)
        kg.add_entity("Ticker", "AAPL", price=180.0)
        kg.add_entity("Ticker", "AAPL", price=185.0)
        node = kg.graph.nodes["Ticker:AAPL"]
        assert node.get("price") == 185.0

    def test_unknown_entity_type_no_crash(self, tmp_path):
        """Unknown entity type should not crash — just warn."""
        kg = make_kg(tmp_path)
        kg.add_entity("UnknownType", "test-id")  # should not raise


class TestAddRelation:
    def test_add_relation_creates_edge(self, tmp_path):
        kg = make_kg(tmp_path)
        kg.add_entity("Topic", "fed-rates")
        kg.add_entity("Ticker", "TLT")
        kg.add_relation("Topic:fed-rates", "Ticker:TLT", "impacts")
        assert kg.graph.has_edge("Topic:fed-rates", "Ticker:TLT")

    def test_relation_has_type_attribute(self, tmp_path):
        kg = make_kg(tmp_path)
        kg.add_entity("Prediction", "pred-1")
        kg.add_entity("Topic", "fed-rates")
        kg.add_relation("Prediction:pred-1", "Topic:fed-rates", "based_on")
        edge_data = kg.graph.edges["Prediction:pred-1", "Topic:fed-rates"]
        assert edge_data.get("relation") == "based_on"


class TestQueryRelated:
    def test_query_related_finds_connected_nodes(self, tmp_path):
        kg = make_kg(tmp_path)
        kg.add_entity("Topic", "fed-rates")
        kg.add_entity("Ticker", "TLT")
        kg.add_entity("Ticker", "SPY")
        kg.add_relation("Topic:fed-rates", "Ticker:TLT", "impacts")
        kg.add_relation("Topic:fed-rates", "Ticker:SPY", "impacts")

        related = kg.query_related("Topic:fed-rates")
        related_node_ids = [r["node_id"] for r in related]
        assert "Ticker:TLT" in related_node_ids
        assert "Ticker:SPY" in related_node_ids

    def test_query_related_isolated_node_empty(self, tmp_path):
        kg = make_kg(tmp_path)
        kg.add_entity("Topic", "isolated-topic")
        related = kg.query_related("Topic:isolated-topic")
        assert related == []

    def test_query_related_nonexistent_node_empty(self, tmp_path):
        kg = make_kg(tmp_path)
        result = kg.query_related("Topic:nonexistent")
        assert result == []


class TestSearch:
    def test_search_finds_matching_entity(self, tmp_path):
        kg = make_kg(tmp_path)
        kg.add_entity("Topic", "federal-reserve-rate-decision", title="Federal Reserve Rate Decision")
        kg.add_entity("Company", "apple-inc", name="Apple Inc")

        results = kg.search("federal")
        result_node_ids = [r["node_id"] for r in results]
        assert any("federal-reserve" in nid for nid in result_node_ids)

    def test_search_case_insensitive(self, tmp_path):
        kg = make_kg(tmp_path)
        kg.add_entity("Ticker", "AAPL", name="Apple Inc")
        results_lower = kg.search("apple")
        results_upper = kg.search("APPLE")
        assert len(results_lower) > 0
        assert len(results_upper) > 0

    def test_search_no_match_empty(self, tmp_path):
        kg = make_kg(tmp_path)
        kg.add_entity("Ticker", "AAPL", name="Apple Inc")
        results = kg.search("zzz_no_match_xyz")
        assert results == []


class TestSaveLoad:
    def test_save_creates_file(self, tmp_path):
        kg = make_kg(tmp_path)
        kg.add_entity("Topic", "test-topic")
        kg.save()
        assert (tmp_path / "test_kg.json").exists()

    def test_reload_preserves_nodes(self, tmp_path):
        path = tmp_path / "test_kg.json"
        kg1 = KnowledgeGraph(path=path)
        kg1.add_entity("Topic", "fed-rates")
        kg1.add_entity("Ticker", "TLT")
        kg1.add_relation("Topic:fed-rates", "Ticker:TLT", "impacts")
        kg1.save()

        kg2 = KnowledgeGraph(path=path)
        assert kg2.graph.number_of_nodes() == kg1.graph.number_of_nodes()
        assert kg2.graph.number_of_edges() == kg1.graph.number_of_edges()
        assert kg2.graph.has_node("Topic:fed-rates")
        assert kg2.graph.has_node("Ticker:TLT")

    def test_reload_preserves_edges(self, tmp_path):
        path = tmp_path / "test_kg.json"
        kg1 = KnowledgeGraph(path=path)
        kg1.add_entity("Prediction", "pred-1")
        kg1.add_entity("Ticker", "SPY")
        kg1.add_relation("Prediction:pred-1", "Ticker:SPY", "targets")
        kg1.save()

        kg2 = KnowledgeGraph(path=path)
        assert kg2.graph.has_edge("Prediction:pred-1", "Ticker:SPY")

    def test_empty_graph_save_load(self, tmp_path):
        path = tmp_path / "empty_kg.json"
        kg1 = KnowledgeGraph(path=path)
        kg1.save()
        kg2 = KnowledgeGraph(path=path)
        assert kg2.graph.number_of_nodes() == 0
