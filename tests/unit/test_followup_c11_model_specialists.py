from __future__ import annotations

from seldon.agents.advanced import AdversarialRedTeamAgent, AdvancedIntelligenceInput
from seldon.agents.context_gathering import InformationSummarizer
from seldon.agents.contracts import RetrievalResult, RetrievedSource
from seldon.agents.feedback import FeedbackInput, RootCauseAnalyzer
from seldon.agents.graph_construction import NodePairCandidate, PairwiseRelationshipDetector
from seldon.agents.prediction import (
    GraphTraversalOutput,
    InstabilityOutput,
    NodeStateForecast,
    ScenarioSynthesisInput,
    ScenarioSynthesizer,
)
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.repositories import GraphRepository, KBRepository, ScenarioRepository


def session_factory():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return make_session_factory(engine)


def seed_prediction_context(db):
    scenario = ScenarioRepository(db).create_scenario(
        name="Gold outlook",
        description="Six-month gold forecast",
        target_question="Will gold rise over the next 6 months?",
        time_horizon="6 months",
    )
    kb = KBRepository(db).create_entry(
        content="Rate cuts can increase gold demand and push gold prices higher over the next quarter.",
        topics=["gold", "rates"],
        entities=["Federal Reserve", "gold demand", "gold prices"],
        scenario_ids=[scenario.id],
        source_name="Seed KB",
        perspective_tags={"confidence": 0.8},
    )
    graph = GraphRepository(db)
    rates = graph.create_node(name="Rate cuts", type="policy", description="Lower policy rates", kb_entry_ids=[kb.id], scenario_ids=[scenario.id], importance_score=0.8)
    price = graph.create_node(name="Gold prices", type="metric", description="Spot gold price level", kb_entry_ids=[kb.id], scenario_ids=[scenario.id], importance_score=0.7)
    edge = graph.create_edge(
        source_node_id=rates.id,
        target_node_id=price.id,
        relationship_type="amplifies",
        description="Rate cuts amplify gold prices through demand.",
        strength=0.8,
        confidence=0.7,
        direction="positive",
        evidence_kb_ids=[kb.id],
        scenario_ids=[scenario.id],
    )
    prediction = ScenarioRepository(db).create_prediction(
        scenario_id=scenario.id,
        statement=scenario.target_question,
        timeframe="6 months",
        resolution_criteria="Resolve against spot gold.",
        probabilities={"rate-cut rally": 0.55, "range-bound": 0.3, "inflation shock": 0.15},
        confidence=0.62,
        assumptions=["Rate cuts proceed", "No inflation shock dominates"],
        status="active",
    )
    return scenario, kb, rates, price, edge, prediction


def test_information_summarizer_uses_llm_contract(mock_llm):
    mock_llm["Information Summarizer"] = {
        "content": "Rate cuts are expected to support gold demand.",
        "original_snippet": "Analysts said rate cuts support gold demand.",
        "source_type": "news_article",
        "source_url": "https://example.test/rates-gold",
        "source_name": "Example News",
        "topics": ["gold", "rates"],
        "entities": ["Federal Reserve", "gold"],
        "perspective_tags": {"confidence": 0.76, "sentiment": 0.4},
        "source_reference": "doc-1",
    }
    factory = session_factory()
    with factory() as db, db.begin():
        _, output = InformationSummarizer(db, config=SeldonConfig(), llm_client=mock_llm).run(
            RetrievalResult(
                query="gold rates",
                sources=[RetrievedSource(source_type="news_article", source_id="doc-1", url="https://example.test/rates-gold", name="Example News", content="long article")],
            )
        )

    assert output.content == "Rate cuts are expected to support gold demand."
    assert output.source_name == "Example News"
    assert mock_llm["_call_count"]["n"] == 1


def test_relationship_detector_uses_llm_contract_and_preserves_pair_ids(mock_llm):
    mock_llm["Pairwise Relationship Detector"] = {
        "source_node_id": "wrong-source",
        "target_node_id": "wrong-target",
        "relationship_type": "causes",
        "description": "Rate cuts causally support gold prices by reducing real yields.",
        "strength": 0.82,
        "confidence": 0.74,
        "lag": "1-3 months",
        "direction": "positive",
        "evidence_kb_ids": [],
        "scenario_ids": [],
    }
    factory = session_factory()
    with factory() as db, db.begin():
        scenario, kb, rates, price, *_ = seed_prediction_context(db)
        _, output = PairwiseRelationshipDetector(db, config=SeldonConfig(), llm_client=mock_llm).run(
            NodePairCandidate(source_node_id=rates.id, target_node_id=price.id, evidence_kb_ids=[kb.id], score=0.9)
        )

    assert output.source_node_id == rates.id
    assert output.target_node_id == price.id
    assert output.evidence_kb_ids == [kb.id]
    assert scenario.id in output.scenario_ids
    assert output.relationship_type == "causes"


def test_scenario_synthesizer_uses_llm_contract_for_arbitrary_scenarios(mock_llm):
    factory = session_factory()
    with factory() as db, db.begin():
        scenario, _kb, rates, price, edge, _prediction = seed_prediction_context(db)
        mock_llm["Scenario Synthesizer"] = {
            "statement": scenario.target_question,
            "scope": "Gold market",
            "timeframe": "6 months",
            "resolution_criteria": "Resolve using spot gold after six months.",
            "outcomes": [
                {"outcome": "Rate-cut rally", "probability": 0.5, "confidence": 0.68, "key_drivers": [rates.id], "key_assumptions": ["Rate cuts proceed"], "stability": "moderately_stable", "reasoning_trace": "Easing supports demand."},
                {"outcome": "Range-bound chop", "probability": 0.3, "confidence": 0.6, "key_drivers": [price.id], "key_assumptions": ["Drivers offset"], "stability": "stable", "reasoning_trace": "Signals offset."},
                {"outcome": "Inflation shock selloff", "probability": 0.2, "confidence": 0.55, "key_drivers": [rates.id], "key_assumptions": ["Inflation reaccelerates"], "stability": "unstable", "reasoning_trace": "Cuts are delayed."},
            ],
            "probabilities": {"rate-cut rally": 0.5, "range-bound chop": 0.3, "inflation shock selloff": 0.2},
            "confidence": 0.64,
            "key_drivers": [rates.id, price.id],
            "evidence_links": [],
            "assumptions": ["Rate cuts proceed", "No inflation shock dominates"],
        }
        _, output = ScenarioSynthesizer(db, config=SeldonConfig(), llm_client=mock_llm).run(
            ScenarioSynthesisInput(
                scenario_id=scenario.id,
                question=scenario.target_question,
                timeframe="6 months",
                node_forecasts=[NodeStateForecast(node_id=rates.id, node_name="Rate cuts", forecast="Cuts likely", confidence=0.7)],
                traversal=GraphTraversalOutput(traversal_log=[], aggregate_signal=0.3, visited_node_ids=[rates.id, price.id]),
                instability=InstabilityOutput(hotspots=[], overall_instability=0.2),
            )
        )

    assert set(output.probabilities) == {"rate-cut rally", "range-bound chop", "inflation shock selloff"}
    assert abs(sum(output.probabilities.values()) - 1.0) < 0.01
    assert output.outcomes[0].outcome == "Rate-cut rally"


def test_red_team_and_root_cause_analyzers_use_llm_contracts(mock_llm):
    mock_llm["adversarial red-team gate"] = {
        "strongest_counterargument": "The forecast underweights an inflation shock that delays cuts.",
        "pivotal_assumption": "Rate cuts proceed",
        "objections": ["Inflation could reaccelerate", "Positioning may already price cuts"],
        "activation_recommendation": "needs_review",
    }
    mock_llm["Root-Cause Analyzer"] = {
        "comparison": "The observed bear outcome was underweighted.",
        "missed_factors": ["inflation shock"],
        "failed_assumptions": ["No inflation shock dominates"],
        "lessons_learned": "Track inflation surprise risk before activation.",
        "assumption_diagnostics": [{"assumption": "No inflation shock dominates", "status": "failed", "evidence": "actual outcome"}],
    }
    factory = session_factory()
    with factory() as db, db.begin():
        *_ctx, prediction = seed_prediction_context(db)
        _, red_team = AdversarialRedTeamAgent(db, config=SeldonConfig(), llm_client=mock_llm).run(
            AdvancedIntelligenceInput(prediction_id=prediction.id, max_items=1)
        )
        _, root_cause = RootCauseAnalyzer(db, config=SeldonConfig(), llm_client=mock_llm).run(
            FeedbackInput(
                prediction_id=prediction.id,
                actual_outcome="Gold fell after inflation reaccelerated.",
                resolved_outcome_key="inflation shock",
                failed_assumptions=["No inflation shock dominates"],
            )
        )

    assert red_team.activation_recommendation == "needs_review"
    assert red_team.objections == ["Inflation could reaccelerate"]
    assert root_cause.missed_factors == ["inflation shock"]
    assert root_cause.failed_assumptions == ["No inflation shock dominates"]
    assert mock_llm["_call_count"]["n"] == 2
