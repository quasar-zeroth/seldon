from __future__ import annotations

from seldon.agents.graph_construction import ImportanceScorer
from seldon.agents.prediction import GraphTraversalInput, GraphTraversalSimulator, NodeStateForecast
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.repositories import GraphRepository, KBRepository, ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def seed_cascade_graph(db):
    scenario = ScenarioRepository(db).create_scenario(
        name="Cascade outlook",
        target_question="Will the final metric rise?",
        time_horizon="6 months",
    )
    kb = KBRepository(db).create_entry(
        content="Policy easing boosts liquidity, liquidity lifts demand, and demand raises the final metric.",
        topics=["policy", "liquidity", "demand"],
        entities=["Policy easing", "Liquidity", "Demand", "Final metric"],
        scenario_ids=[scenario.id],
        perspective_tags={"confidence": 0.8},
    )
    graph = GraphRepository(db)
    policy = graph.create_node(name="Policy easing", type="policy", kb_entry_ids=[kb.id], scenario_ids=[scenario.id])
    liquidity = graph.create_node(name="Liquidity", type="metric", kb_entry_ids=[kb.id], scenario_ids=[scenario.id])
    demand = graph.create_node(name="Demand", type="metric", kb_entry_ids=[kb.id], scenario_ids=[scenario.id])
    final = graph.create_node(name="Final metric", type="metric", kb_entry_ids=[kb.id], scenario_ids=[scenario.id])
    other = graph.create_node(name="Other scenario node", type="topic", kb_entry_ids=[kb.id], scenario_ids=["other-scenario"])
    edge_1 = graph.create_edge(
        source_node_id=policy.id,
        target_node_id=liquidity.id,
        relationship_type="amplifies",
        description="Policy easing boosts liquidity.",
        strength=0.9,
        confidence=0.9,
        direction="positive",
        evidence_kb_ids=[kb.id],
        scenario_ids=[scenario.id],
    )
    edge_2 = graph.create_edge(
        source_node_id=liquidity.id,
        target_node_id=demand.id,
        relationship_type="causes",
        description="Liquidity lifts demand.",
        strength=0.8,
        confidence=0.8,
        direction="positive",
        evidence_kb_ids=[kb.id],
        scenario_ids=[scenario.id],
    )
    edge_3 = graph.create_edge(
        source_node_id=demand.id,
        target_node_id=final.id,
        relationship_type="causes",
        description="Demand raises the final metric.",
        strength=0.75,
        confidence=0.75,
        direction="positive",
        evidence_kb_ids=[kb.id],
        scenario_ids=[scenario.id],
    )
    graph.create_edge(
        source_node_id=other.id,
        target_node_id=policy.id,
        relationship_type="correlates_with",
        description="Should be filtered from the scenario graph view.",
        strength=1.0,
        confidence=1.0,
        scenario_ids=["other-scenario"],
    )
    return scenario, (policy, liquidity, demand, final, other), (edge_1, edge_2, edge_3)


def test_graph_repository_builds_scenario_scoped_networkx_view_and_centrality_scores():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario, nodes, edges = seed_cascade_graph(db)
            graph_repo = GraphRepository(db)
            nx_graph = graph_repo.to_networkx(scenario_id=scenario.id)
            scores = graph_repo.centrality_scores(scenario_id=scenario.id)
            _, liquidity, demand, final, other = nodes

        assert set(nx_graph.nodes) == {node.id for node in nodes[:4]}
        assert other.id not in nx_graph.nodes
        assert nx_graph.number_of_edges() == 3
        assert nx_graph[edges[0].source_node_id][edges[0].target_node_id]["edge_ids"] == [edges[0].id]
        assert scores[liquidity.id]["degree"] > scores[final.id]["degree"]
        assert scores[demand.id]["betweenness"] > scores[final.id]["betweenness"]


def test_importance_scorer_uses_networkx_centrality_components():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario, nodes, _ = seed_cascade_graph(db)
            _, updates = ImportanceScorer(db, config=SeldonConfig()).run_scores(scenario_id=scenario.id)
            by_node = {update.node_id: update for update in updates}
            policy, liquidity, demand, final, _ = nodes

        assert set(by_node) == {node.id for node in nodes[:4]}
        assert by_node[policy.id].components["dependency_reach"] == 1.0
        assert by_node[liquidity.id].components["pagerank"] > 0
        assert by_node[demand.id].importance_score > by_node[final.id].importance_score


def test_graph_traversal_simulator_propagates_multi_hop_cascades():
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario, nodes, edges = seed_cascade_graph(db)
            policy, _, _, final, _ = nodes
            _, traversal = GraphTraversalSimulator(db, config=SeldonConfig()).run(
                GraphTraversalInput(
                    scenario_id=scenario.id,
                    node_forecasts=[
                        NodeStateForecast(
                            node_id=policy.id,
                            node_name=policy.name,
                            forecast="Policy easing is expected to rise.",
                            direction="up",
                            confidence=0.9,
                        )
                    ],
                    max_depth=3,
                    min_influence=0.01,
                )
            )

        assert [step.edge_id for step in traversal.traversal_log] == [edge.id for edge in edges]
        assert final.id in traversal.visited_node_ids
        assert traversal.aggregate_signal > 0
        assert traversal.traversal_log[-1].rationale.startswith("Cascade depth 3")
