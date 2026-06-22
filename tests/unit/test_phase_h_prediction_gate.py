"""Prediction safety gate: refuse to forecast over an empty/garbage graph."""
from __future__ import annotations

import pytest

from seldon.agents.prediction import InsufficientGraphNodesError, PredictionCoordinator, is_valid_domain_node
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import ERGNode
from seldon.data.repositories import GraphRepository, ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def test_is_valid_domain_node_rejects_stopword_nodes():
    assert is_valid_domain_node(ERGNode(name="Gold", type="entity")) is True
    assert is_valid_domain_node(ERGNode(name="Federal Reserve", type="actor")) is True
    assert is_valid_domain_node(ERGNode(name="would", type="topic")) is False
    assert is_valid_domain_node(ERGNode(name="outcome", type="topic")) is False
    assert is_valid_domain_node(ERGNode(name="", type="topic")) is False


def test_prediction_blocks_when_only_stopword_nodes(tmp_path):
    factory = session_factory()
    with factory() as db:
        with db.begin():
            scenario = ScenarioRepository(db).create_scenario(
                name="Garbage graph",
                target_question="What will gold do in 6 months?",
                time_horizon="6 months",
            )
            # Only scaffolding nodes exist — no real domain entity to forecast over.
            GraphRepository(db).create_node(name="would", type="topic", scenario_ids=[scenario.id])
            GraphRepository(db).create_node(name="outcome", type="topic", scenario_ids=[scenario.id])
            with pytest.raises(InsufficientGraphNodesError) as excinfo:
                PredictionCoordinator(db, config=SeldonConfig(data_dir=tmp_path)).run(
                    PredictionCoordinator.input_from_scenario(scenario, export_markdown=False)
                )
    assert "insufficient_valid_graph_nodes" in str(excinfo.value)
    # Marked no-retry so the job queue fails it immediately instead of looping.
    assert getattr(excinfo.value, "no_retry", False) is True
