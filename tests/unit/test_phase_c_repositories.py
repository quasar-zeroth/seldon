from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from seldon.data import (
    AgentRunRepository,
    AuditRepository,
    GraphRepository,
    KBRepository,
    MarkdownExporter,
    ScenarioRepository,
    create_all,
    make_engine,
    make_session_factory,
)
from seldon.data.models import KBEntryVersion, ScenarioVersion


def make_session(tmp_path: Path):
    engine = make_engine(sqlite_path=tmp_path / "seldon.db")
    create_all(engine)
    return make_session_factory(engine)()


def test_phase_c_tables_created(tmp_path):
    engine = make_engine(sqlite_path=tmp_path / "seldon.db")
    create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {
        "kb_entries",
        "kb_entry_versions",
        "kb_entry_contradictions",
        "sources",
        "erg_nodes",
        "erg_edges",
        "scenario_predictions",
        "scenario_versions",
        "scenario_evidence_links",
        "agent_runs",
        "agent_messages",
        "model_invocations",
        "audit_log",
    }.issubset(tables)


def test_kb_repository_crud_versions_supersede_and_audit(tmp_path):
    session = make_session(tmp_path)
    with session.begin():
        kb = KBRepository(session)
        first = kb.create_entry(
            content="The Fed held rates steady.",
            source_type="news_article",
            source_name="Reuters",
            topics=["fed_policy"],
            entities=["Federal Reserve"],
            perspective_tags={"confidence": 0.9},
            actor="test-agent",
            reason="fixture",
        )
        second = kb.create_entry(content="The Fed cut rates.", source_name="AP")
        kb.update_entry(first.id, content="The Fed held rates steady in May.", actor="test-agent", reason="more precise")
        kb.supersede(first.id, second.id, actor="test-agent", reason="newer report")
        contradiction = kb.add_contradiction(first.id, second.id, "Held vs cut")

    stored = session.get(type(first), first.id)
    assert stored is not None
    assert stored.superseded_by == second.id
    assert stored.version == 3
    assert session.query(KBEntryVersion).filter_by(kb_entry_id=first.id).count() == 3
    assert contradiction.description == "Held vs cut"
    actions = [a.action for a in AuditRepository(session).list(entity_type="kb_entry", entity_id=first.id)]
    assert "create" in actions
    assert "update" in actions
    assert "supersede" in actions


def test_graph_repository_nodes_edges_export_and_audit(tmp_path):
    session = make_session(tmp_path)
    with session.begin():
        graph = GraphRepository(session)
        fed = graph.create_node(name="Federal Reserve", type="actor", description="US central bank")
        gold = graph.create_node(name="Gold price", type="metric")
        edge = graph.create_edge(
            source_node_id=fed.id,
            target_node_id=gold.id,
            relationship_type="causes",
            description="Higher rates pressure gold",
            strength=0.7,
            confidence=0.8,
            direction="negative",
        )
        exported = graph.export_graph_json()

    assert exported["nodes"][0]["name"] == "Federal Reserve"
    assert edge.relationship_type == "causes"
    assert len(AuditRepository(session).list(entity_type="erg_edge", entity_id=edge.id)) == 1


def test_scenario_and_agent_run_repositories_plus_markdown_exports(tmp_path):
    session = make_session(tmp_path)
    with session.begin():
        kb_entry = KBRepository(session).create_entry(content="ETF inflows are rising.")
        scenario_repo = ScenarioRepository(session)
        scenario = scenario_repo.create_prediction(
            statement="Gold rises over six months",
            timeframe="6 months",
            resolution_criteria="Spot gold closes above threshold",
            scenarios=[{"name": "bull", "probability": 0.4}],
            probabilities={"bull": 0.4, "base": 0.4, "bear": 0.2},
            confidence=0.62,
            evidence_links=[kb_entry.id],
            assumptions=["ETF demand persists"],
            status="active",
            actor="scenario-agent",
        )
        scenario_repo.update_prediction(scenario.id, confidence=0.65, reason="new evidence")

        runs = AgentRunRepository(session)
        run = runs.create(agent_id="query_decomposer", phase="context", status="succeeded", input={"q": "gold"})
        runs.add_message(run.id, "user", "Predict gold")
        invocation = runs.record_invocation(agent_run_id=run.id, agent="query_decomposer", model="mock/model", usage={"total_tokens": 3})

        exporter = MarkdownExporter(tmp_path / "exports")
        kb_path = exporter.export_kb_entry(kb_entry)
        scenario_path = exporter.export_scenario(scenario)

    assert session.query(ScenarioVersion).filter_by(scenario_prediction_id=scenario.id).count() == 2
    assert invocation.model == "mock/model"
    assert kb_path.exists()
    assert scenario_path.read_text().startswith("# Gold rises")
