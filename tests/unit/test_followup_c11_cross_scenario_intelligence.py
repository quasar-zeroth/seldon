from __future__ import annotations

from seldon.agents import (
    CrossScenarioCorrelationDetector,
    CrossScenarioCorrelationInput,
    SharedGraphInput,
    SharedGraphManager,
)
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.repositories import GraphRepository, KBRepository, ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def seed_cross_scenario_graph(db):
    scenarios = ScenarioRepository(db)
    gold = scenarios.create_scenario(
        name="Gold liquidity outlook",
        target_question="Will gold rise if global liquidity improves?",
        time_horizon="6 months",
    )
    copper = scenarios.create_scenario(
        name="Copper liquidity outlook",
        target_question="Will copper fall despite liquidity improving?",
        time_horizon="6 months",
    )
    kb = KBRepository(db)
    shared_kb = kb.create_entry(
        content="Global liquidity changes affect metals demand and risk appetite.",
        topics=["liquidity", "metals", "demand"],
        entities=["Global liquidity", "Gold", "Copper"],
        scenario_ids=[gold.id],
        perspective_tags={"confidence": 0.8},
    )
    target_kb = kb.create_entry(
        content="Copper demand is sensitive to liquidity and industrial activity.",
        topics=["liquidity", "copper", "demand"],
        entities=["Global liquidity", "Copper"],
        scenario_ids=[copper.id],
        perspective_tags={"confidence": 0.75},
    )
    graph = GraphRepository(db)
    liquidity = graph.create_node(
        name="Global liquidity",
        type="metric",
        description="Market-wide liquidity conditions for risk assets and metals.",
        current_state="Liquidity is improving but unstable.",
        kb_entry_ids=[shared_kb.id],
        scenario_ids=[gold.id],
        stability_score=0.3,
        importance_score=0.88,
    )
    gold_node = graph.create_node(
        name="Gold demand",
        type="metric",
        description="Demand for gold as a monetary metal.",
        kb_entry_ids=[shared_kb.id],
        scenario_ids=[gold.id],
        stability_score=0.55,
        importance_score=0.7,
    )
    edge = graph.create_edge(
        source_node_id=liquidity.id,
        target_node_id=gold_node.id,
        relationship_type="amplifies",
        description="Improving liquidity tends to amplify demand for metals.",
        strength=0.8,
        confidence=0.75,
        direction="positive",
        evidence_kb_ids=[shared_kb.id],
        scenario_ids=[gold.id],
    )
    copper_node = graph.create_node(
        name="Copper demand",
        type="metric",
        description="Industrial copper demand.",
        kb_entry_ids=[target_kb.id],
        scenario_ids=[copper.id],
        stability_score=0.5,
        importance_score=0.65,
    )
    return gold, copper, liquidity, gold_node, copper_node, edge, shared_kb, target_kb


def test_shared_graph_manager_proposes_and_imports_reusable_graph_with_lineage():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            _, copper, liquidity, gold_node, _, edge, _, _ = seed_cross_scenario_graph(db)
            run_id, output = SharedGraphManager(db, config=SeldonConfig()).run(
                SharedGraphInput(
                    scenario_id=copper.id,
                    query="liquidity",
                    max_items=5,
                    accepted_node_ids=[liquidity.id],
                    import_accepted=True,
                )
            )
            graph = GraphRepository(db)
            refreshed_liquidity = graph.get_node(liquidity.id)
            refreshed_gold = graph.get_node(gold_node.id)
            refreshed_edge = db.get(type(edge), edge.id)

        assert run_id
        assert output.proposals[0].node_id == liquidity.id
        assert output.proposals[0].score > 0.2
        assert liquidity.id in output.imported_node_ids
        assert edge.id in output.imported_edge_ids
        assert output.lineage[liquidity.id]["kind"] == "shared_node"
        assert output.propagation_alerts
        assert copper.id in refreshed_liquidity.scenario_ids
        # The selected relationship imports both endpoints so traversals remain valid.
        assert copper.id in refreshed_gold.scenario_ids
        assert copper.id in refreshed_edge.scenario_ids


def test_cross_scenario_correlation_detector_flags_shared_dependencies_and_contradictions():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            gold, copper, liquidity, _, copper_node, edge, shared_kb, target_kb = seed_cross_scenario_graph(db)
            graph = GraphRepository(db)
            graph.update_node(liquidity.id, scenario_ids=[gold.id, copper.id])
            graph.update_edge(edge.id, scenario_ids=[gold.id, copper.id])
            repo = ScenarioRepository(db)
            gold_prediction = repo.create_prediction(
                scenario_id=gold.id,
                statement="Gold will rise as liquidity improves.",
                timeframe="6 months",
                resolution_criteria="Resolve against spot gold.",
                probabilities={"bull": 0.62, "bear": 0.18},
                key_drivers=[liquidity.id],
                evidence_links=[shared_kb.id],
                confidence=0.66,
                status="active",
            )
            copper_prediction = repo.create_prediction(
                scenario_id=copper.id,
                statement="Copper will fall despite liquidity improving.",
                timeframe="6 months",
                resolution_criteria="Resolve against spot copper.",
                probabilities={"bear": 0.57, "bull": 0.21},
                key_drivers=[liquidity.id, copper_node.id],
                evidence_links=[shared_kb.id, target_kb.id],
                confidence=0.6,
                status="active",
            )
            _, output = CrossScenarioCorrelationDetector(db, config=SeldonConfig()).run(
                CrossScenarioCorrelationInput(scenario_id=copper.id, max_items=5)
            )

        assert output.shared_dependency_changes[0]["node_id"] == liquidity.id
        assert {gold.id, copper.id}.issubset(set(output.shared_dependency_changes[0]["scenario_ids"]))
        assert output.contradictory_predictions
        contradiction = output.contradictory_predictions[0]
        assert {contradiction["left_prediction_id"], contradiction["right_prediction_id"]} == {gold_prediction.id, copper_prediction.id}
        assert contradiction["shared_driver_ids"] == [liquidity.id]
        assert output.correlation_clusters
        assert any(cluster["scenario_id"] == copper.id for cluster in output.correlation_clusters)
