"""Deterministic gold-scenario regression test for the Phase 2 pipeline fixes.

Ties together the fixes for the original failure mode: stopword KB topics, the
scenario question written as a "fact", and stopword ERG nodes. Runs without an
LLM (heuristic paths) so it is fast and network-free.
"""
from __future__ import annotations

from sqlalchemy import select

from seldon.agents import ContextGatheringCoordinator, ExtractionCoordinator
from seldon.agents.extraction import _NODE_NAME_BLOCKLIST, _canonical
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import ERGNode, KBEntry
from seldon.data.repositories import KBRepository, ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def test_context_gathering_never_writes_the_question_as_a_fact():
    """With no KB matches and no providers, we record a neutral marker, not the
    scenario question dressed up as evidence with stopword topics."""
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario = ScenarioRepository(db).create_scenario(
                name="Gold price outlook over 6 and 12 months",
                target_question="Roughly what would be the price of gold in 6 and 12 months?",
                time_horizon="6 months / 1 year",
            )
            payload = ContextGatheringCoordinator.input_from_scenario(scenario, max_subqueries=4)
            ContextGatheringCoordinator(db, config=SeldonConfig()).run(payload)

        entries = list(db.scalars(select(KBEntry)))
        assert entries, "context gathering should still record a marker entry"
        for entry in entries:
            # The literal question must never become a KB fact...
            assert "roughly what would be the price of gold" not in (entry.content or "").lower()
            # ...and no stopword topics ("roughly", "would", "now") may leak in.
            assert not (set(entry.topics or []) & _NODE_NAME_BLOCKLIST)
            assert "would" not in (entry.topics or [])


def test_extraction_builds_domain_graph_without_stopword_nodes():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario = ScenarioRepository(db).create_scenario(
                name="Gold price outlook over 6 and 12 months",
                target_question="Where will gold trade in 6 and 12 months?",
                time_horizon="6 months / 1 year",
            )
            kb = KBRepository(db)
            kb.create_entry(
                content="The Federal Reserve signalled rate cuts while central banks increased gold purchases.",
                topics=["gold", "monetary policy"],
                entities=["Federal Reserve", "central banks", "gold"],
                scenario_ids=[scenario.id],
                source_name="Reuters",
                perspective_tags={"confidence": 0.8},
            )
            kb.create_entry(
                content="Real yields fell and the US dollar weakened, supporting gold prices.",
                topics=["gold", "real yields"],
                entities=["real yields", "US dollar", "gold"],
                scenario_ids=[scenario.id],
                source_name="Bloomberg",
                perspective_tags={"confidence": 0.8},
            )
            payload = ExtractionCoordinator.input_from_scenario(scenario)
            ExtractionCoordinator(db, config=SeldonConfig()).run(payload)

        nodes = list(db.scalars(select(ERGNode)))
        assert nodes, "extraction should populate the graph"
        names = {_canonical(node.name) for node in nodes}
        # No scaffolding/stopword nodes like "would", "outcome", "roughly".
        assert not (names & _NODE_NAME_BLOCKLIST)
        # The forecast subject and a macro driver are represented.
        assert "gold" in names
        assert "federal reserve" in names
        # "gold" is mentioned as an entity in both KB entries but resolves to a
        # single entity node (cross-entry merge), not one per mention.
        gold_entities = [node for node in nodes if _canonical(node.name) == "gold" and node.type == "entity"]
        assert len(gold_entities) == 1
