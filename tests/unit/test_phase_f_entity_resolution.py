"""Entity-resolution behaviour: alias + embedding matching and applied merges.

These exercise the deterministic resolution paths (no LLM), which collapse
surface-form duplicates onto a single node instead of creating new ones.
"""
from __future__ import annotations

from sqlalchemy import select

from seldon.agents import ExtractionCoordinator, NodeCandidate, NodeDeduplicatorMerger
from seldon.agents.extraction import _canonical
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import ERGNode
from seldon.data.repositories import GraphRepository, KBRepository, ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def test_propose_matches_existing_node_via_alias():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            existing = GraphRepository(db).create_node(name="Federal Reserve", type="actor", description="US central bank")
            _run_id, proposals = NodeDeduplicatorMerger(db, config=SeldonConfig()).run_candidates(
                [NodeCandidate(name="Fed", type="actor", aliases=["Federal Reserve"], kb_entry_ids=["kb-1"], scenario_ids=["s1"])]
            )
        assert len(proposals) == 1
        # "Fed" resolves to the existing "Federal Reserve" node via its alias.
        assert proposals[0].existing_node_id == existing.id


def test_propose_matches_existing_node_via_embedding_when_word_order_differs():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            existing = GraphRepository(db).create_node(name="Federal Reserve", type="actor", description="US central bank")
            _run_id, proposals = NodeDeduplicatorMerger(db, config=SeldonConfig()).run_candidates(
                [NodeCandidate(name="Reserve Federal", type="actor", kb_entry_ids=["kb-1"], scenario_ids=["s1"])]
            )
        assert len(proposals) == 1
        assert proposals[0].existing_node_id == existing.id
        assert "Embedding similarity" in proposals[0].reason


def test_different_type_is_not_merged():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            GraphRepository(db).create_node(name="Gold", type="entity", description="precious metal")
            _run_id, proposals = NodeDeduplicatorMerger(db, config=SeldonConfig()).run_candidates(
                [NodeCandidate(name="Gold", type="metric", kb_entry_ids=["kb-1"], scenario_ids=["s1"])]
            )
        # Same name, different node type -> never a merge candidate against the entity.
        assert all(p.existing_node_id is None for p in proposals)


def test_coordinator_merges_candidate_onto_existing_node_without_duplicating():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario = ScenarioRepository(db).create_scenario(
                name="Gold outlook",
                target_question="Where will gold trade in 6 months?",
                time_horizon="6 months",
            )
            existing = GraphRepository(db).create_node(name="Gold", type="entity", description="precious metal")
            kb_entry = KBRepository(db).create_entry(
                content="Gold demand rose sharply as investors sought safety.",
                topics=["gold"],
                entities=["Gold"],
                scenario_ids=[scenario.id],
                source_name="Seed KB",
                perspective_tags={"confidence": 0.8},
            )
            payload = ExtractionCoordinator.input_from_scenario(scenario)
            ExtractionCoordinator(db, config=SeldonConfig()).run(payload)

        gold_entities = [n for n in db.scalars(select(ERGNode)) if _canonical(n.name) == "gold" and n.type == "entity"]
        # The "Gold" candidate collapses onto the existing node rather than duplicating it.
        assert len(gold_entities) == 1
        merged = gold_entities[0]
        assert merged.id == existing.id
        assert kb_entry.id in merged.kb_entry_ids
        assert scenario.id in merged.scenario_ids
