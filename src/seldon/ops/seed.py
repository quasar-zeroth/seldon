"""Seed/demo data for local operation and screenshots."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from seldon.data.models import Scenario
from seldon.data.repositories import GraphRepository, KBRepository, ScenarioRepository


def seed_demo_data(session: Session) -> dict[str, object]:
    """Insert a compact demo scenario if the database is empty enough.

    The function is idempotent by scenario name, returning created=false when the
    demo already exists.
    """
    existing = session.scalar(select(Scenario).where(Scenario.name == "Demo: Gold 6-month outlook"))
    if existing is not None:
        return {"created": False, "scenario_id": existing.id}

    scenario = ScenarioRepository(session).create_scenario(
        name="Demo: Gold 6-month outlook",
        description="Seed scenario for exercising The Seldon Project console.",
        target_question="Where will gold trade over the next six months?",
        time_horizon="6 months",
    )
    kb = KBRepository(session).create_entry(
        content="Central bank gold purchases remain an important source of marginal demand.",
        original_snippet="Demo seed: central banks keep buying gold.",
        source_type="demo_seed",
        source_name="The Seldon Project seed data",
        topics=["gold", "central_banks"],
        entities=["Central banks", "Gold"],
        scenario_ids=[scenario.id],
        perspective_tags={"sentiment": 0.35, "confidence": 0.75},
    )
    graph = GraphRepository(session)
    demand = graph.create_node(
        name="Central bank gold demand",
        type="metric",
        description="Official-sector purchases of gold reserves.",
        kb_entry_ids=[kb.id],
        scenario_ids=[scenario.id],
        importance_score=0.72,
        stability_score=0.65,
    )
    price = graph.create_node(
        name="Gold spot price",
        type="metric",
        description="The market price of gold per troy ounce.",
        kb_entry_ids=[kb.id],
        scenario_ids=[scenario.id],
        importance_score=0.9,
        stability_score=0.55,
    )
    edge = graph.create_edge(
        source_node_id=demand.id,
        target_node_id=price.id,
        relationship_type="amplifies",
        description="Persistent official-sector buying can support gold price strength.",
        strength=0.65,
        confidence=0.7,
        direction="positive",
        evidence_kb_ids=[kb.id],
        scenario_ids=[scenario.id],
    )
    return {"created": True, "scenario_id": scenario.id, "kb_entry_id": kb.id, "node_ids": [demand.id, price.id], "edge_id": edge.id}
