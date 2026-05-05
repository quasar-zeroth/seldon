from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import inspect

from seldon.data import (
    DatabaseModelInvocationRecorder,
    GraphRepository,
    KBRepository,
    ScenarioRepository,
    create_all,
    make_engine,
    make_session_factory,
)
from seldon.data.models import FeedbackEntry, GraphSnapshot, ModelInvocation, Scenario
from seldon.data.schemas import (
    AgentMessageCreate,
    AgentRunCreate,
    AuditLogRead,
    FeedbackEntryCreate,
    GraphSnapshotRead,
    KBEntryContradictionCreate,
    KBEntryCreate,
    KBEntryRead,
    KBEntryVersionRead,
    ModelInvocationCreate,
    ScenarioCreate,
    ScenarioEvidenceLinkCreate,
    ScenarioPredictionCreate,
    ScenarioVersionRead,
    SourceCreate,
)
from seldon.llm import OpenRouterClient
from seldon.config import OpenRouterConfig


def make_session(tmp_path):
    engine = make_engine(sqlite_path=tmp_path / "c1.db")
    create_all(engine)
    return engine, make_session_factory(engine)()


def test_c1_tables_are_present(tmp_path):
    engine, _ = make_session(tmp_path)
    tables = set(inspect(engine).get_table_names())
    assert {"scenarios", "feedback_entries", "graph_snapshots"}.issubset(tables)


def test_c1_schema_contracts_validate_minimal_payloads():
    now = datetime.now(timezone.utc)
    source = SourceCreate(source_type="news_article", name="Reuters")
    kb = KBEntryCreate(content="Gold ETF inflows increased", content_embedding=[0.1, 0.2])
    scenario = ScenarioCreate(name="Gold", target_question="Where will gold trade?", time_horizon="6 months")
    prediction = ScenarioPredictionCreate(statement="Gold rises", scenario_id="scenario-id")
    feedback = FeedbackEntryCreate(actual_outcome="Gold rose", missed_factors=["USD weakness"])
    invocation = ModelInvocationCreate(model="mock/model", usage={"total_tokens": 4})
    run = AgentRunCreate(agent_id="agent")
    msg = AgentMessageCreate(agent_run_id="run", role="user", content="hello")
    contradiction = KBEntryContradictionCreate(kb_entry_id="a", contradicts_kb_entry_id="b", description="conflict")
    evidence = ScenarioEvidenceLinkCreate(scenario_prediction_id="p", kb_entry_id="k")
    KBEntryRead(id="k", version=1, created_at=now, updated_at=now, **kb.model_dump())
    KBEntryVersionRead(id="v", kb_entry_id="k", version=1, snapshot={}, created_at=now)
    ScenarioVersionRead(id="sv", scenario_prediction_id="p", version=1, snapshot={}, created_at=now)
    GraphSnapshotRead(id="gs", snapshot={}, created_at=now)
    AuditLogRead(id="a", entity_type="x", entity_id="y", action="create", actor="agent", created_at=now)

    assert source.name == "Reuters"
    assert scenario.target_question.startswith("Where")
    assert prediction.statement == "Gold rises"
    assert feedback.missed_factors == ["USD weakness"]
    assert invocation.model == "mock/model"
    assert run.status == "pending"
    assert msg.role == "user"
    assert contradiction.status == "open"
    assert evidence.relationship == "supports"


def test_kb_temporal_perspective_scenario_and_current_filters(tmp_path):
    _, session = make_session(tmp_path)
    now = datetime.now(timezone.utc)
    with session.begin():
        kb = KBRepository(session)
        old = kb.create_entry(
            content="Old gold note",
            topics=["gold"],
            entities=["Gold"],
            scenario_ids=["gold-scenario"],
            valid_from=now - timedelta(days=10),
            valid_until=now - timedelta(days=2),
            perspective_tags={"sentiment": -0.5, "confidence": 0.4},
        )
        current = kb.create_entry(
            content="Current bullish gold ETF flows",
            topics=["gold"],
            entities=["ETF"],
            scenario_ids=["gold-scenario"],
            valid_from=now - timedelta(days=1),
            perspective_tags={"sentiment": 0.7, "confidence": 0.9},
            content_embedding=[0.1, 0.2, 0.3],
        )
        kb.supersede(old.id, current.id)

        results = kb.search(topic="gold", scenario_id="gold-scenario", valid_at=now, current_only=True, min_sentiment=0.1, min_confidence=0.8)
        summary = kb.confidence_summary(results)

    assert [r.id for r in results] == [current.id]
    assert summary["count"] == 1
    assert summary["average"] == 0.9
    assert KBRepository(session).semantic_search("ETF", limit=1)[0].id == current.id


def test_scenario_feedback_graph_snapshot_reuse_and_db_invocation_recorder(tmp_path):
    _, session = make_session(tmp_path)
    with session.begin():
        scenarios = ScenarioRepository(session)
        scenario = scenarios.create_scenario(name="Gold", target_question="Gold?", time_horizon="6 months")
        prediction = scenarios.create_prediction(scenario_id=scenario.id, statement="Gold rises", status="active")
        feedback = scenarios.record_feedback(scenario_id=scenario.id, prediction_id=prediction.id, actual_outcome="Gold rose")

        graph = GraphRepository(session)
        node = graph.create_node(name="Federal Reserve", type="actor", scenario_ids=["other-scenario"])
        graph.create_node(name="Gold", type="metric", scenario_ids=[scenario.id])
        snapshot = graph.create_snapshot(scenario_id=scenario.id, reason="baseline")
        candidates = graph.reuse_candidates(scenario.id, query="Federal")

        DatabaseModelInvocationRecorder(session).record({"model": "mock/model", "provider": "mock", "latency_ms": 12, "usage": {"total_tokens": 2}, "ok": True})

    assert session.get(Scenario, scenario.id).name == "Gold"
    assert session.get(FeedbackEntry, feedback.id).actual_outcome == "Gold rose"
    assert session.get(GraphSnapshot, snapshot.id).snapshot["nodes"]
    assert [n.id for n in candidates["nodes"]] == [node.id]
    assert session.query(ModelInvocation).filter_by(model="mock/model").count() == 1


def test_transaction_rollback_keeps_failed_write_and_audit_out(tmp_path):
    _, session = make_session(tmp_path)
    try:
        with session.begin():
            KBRepository(session).create_entry(content="This should roll back")
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert KBRepository(session).search("roll back") == []


def test_openrouter_retries_429_before_success(monkeypatch):
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate limited"})
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": "{\"ok\": true}"}}]})

    monkeypatch.setattr("seldon.llm.openrouter.time.sleep", lambda seconds: sleeps.append(seconds))
    client = OpenRouterClient(OpenRouterConfig(default_model="m", base_url="https://openrouter.test/api/v1"), http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert client.complete_json([{"role": "user", "content": "hi"}], max_retries=1) == {"ok": True}
    assert calls["n"] == 2
    assert sleeps == [0.0]
