"""External-agent integration: real DB/CLI/API, no model or search provider."""

from __future__ import annotations

import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from seldon.cli import main
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AgentRun, AuditLog, KBEntry, ScenarioVersion
from seldon.workspace.schemas import WorkspaceApply
from seldon.workspace.service import (
    WorkspaceConflict,
    WorkspaceService,
    render_markdown,
)


@pytest.fixture
def factory(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Provider/network access is forbidden in workspace tests")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    engine = make_engine(sqlite_path=tmp_path / "research.db")
    create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


def initial(factory):
    with factory() as db, db.begin():
        return WorkspaceService(db).start(
            "Where will gold price be in 6 months?", "2027-03-28"
        )


def changes(state):
    return {
        "scenario_id": state["scenario"]["id"],
        "base_revision": state["revision"],
        "request_id": "round-1",
        "agent": "test-agent",
        "reason": "Test source-backed dependency graph",
        "evidence": [
            {
                "id": "source",
                "content": "A fixture source reports central bank demand.",
                "source_name": "Test source",
                "source_url": "https://example.org/gold",
                "published_at": "2026-09-01T00:00:00Z",
                "retrieved_at": "2026-09-28T00:00:00Z",
                "confidence": 0.8,
            }
        ],
        "nodes": [
            {"id": id, "name": name, "type": "metric", "evidence_ids": ["source"]}
            for id, name in (("gold", "Gold price"), ("buying", "Central bank buying"))
        ],
        "edges": [
            {
                "id": "demand",
                "source": "buying",
                "target": "gold",
                "description": "Demand may support prices",
                "evidence_ids": ["source"],
            }
        ],
        "research_round": {
            "queries": ["central bank buying"],
            "checked_node_ids": ["buying", "gold"],
            "new_information": True,
            "stop_reason": "continue",
            "summary": "Added a driver",
        },
    }


def forecast_payload(state):
    return {
        "scenario_id": state["scenario"]["id"],
        "base_revision": state["revision"],
        "request_id": "forecast-1",
        "agent": "test-agent",
        "reason": "Synthesize reviewed DAG",
        "research_round": {
            "queries": ["counterevidence to central bank demand thesis"],
            "checked_node_ids": ["gold", "buying"],
            "new_information": False,
            "stop_reason": "exhausted",
            "summary": "No material new facts in this bounded fixture review",
        },
        "forecast": {
            "target_node_id": "gold",
            "as_of": "2026-09-28T12:00:00Z",
            "resolution_date": "2027-03-28",
            "units": "USD per troy ounce",
            "statement": "Illustrative forecast",
            "resolution_criteria": "Gold reference price on or before resolution date",
            "branches": [
                {
                    "key": "up",
                    "probability": 0.6,
                    "outcome": "Higher",
                    "rationale": "Demand persists",
                },
                {
                    "key": "down",
                    "probability": 0.4,
                    "outcome": "Lower",
                    "rationale": "Demand reverses",
                },
            ],
            "confidence": 0.4,
            "node_assessments": [
                {
                    "node_id": id,
                    "forecast": "Stable or higher",
                    "rationale": "Fixture evidence",
                    "evidence_ids": ["source"],
                }
                for id in ["gold", "buying"]
            ],
            "synthesis": "Demand influences gold through the stored edge",
            "base_rate": "No empirical base rate established",
            "assumptions": ["Other factors held fixed"],
            "red_team": ["Demand could reverse"],
            "uncertainties": ["No calibration"],
        },
    }


def apply(factory, payload):
    with factory() as db, db.begin():
        return WorkspaceService(db).apply(WorkspaceApply.model_validate(payload))


def export(factory, id):
    with factory() as db:
        return WorkspaceService(db).export(id)


def researched(factory):
    state = initial(factory)
    apply(factory, changes(state))
    return export(factory, state["scenario"]["id"])


def test_hot_take_bounds_are_scoped_frozen_and_visible_in_reports(factory):
    from seldon.workspace.reports import ReportRequest, generate_report, report_file

    state = researched(factory)
    payload = forecast_payload(state)
    bounds = {
        side: {
            "outcome": outcome,
            "rationale": "Conditional compounding of demand and rates, not a guaranteed limit",
            "assumptions": ["Joint driver moves remain feasible"],
            "evidence_ids": ["source"],
            "value": value,
        }
        for side, outcome, value in (("lower", "Demand reversal", 2000), ("upper", "Demand acceleration", 6000))
    }
    payload["forecast"]["case_bounds"] = bounds
    result = apply(factory, payload)
    assert apply(factory, payload)["replayed"]
    state = export(factory, state["scenario"]["id"])
    saved = state["predictions"][-1]["calibration_result"]["forecast"]["case_bounds"]
    assert saved["lower"]["value"] == 2000
    assert saved["upper"]["evidence_ids"] == [state["evidence"][0]["id"]]
    assert sum(state["predictions"][-1]["probabilities"].values()) == 1
    assert len(state["predictions"][-1]["scenarios"]) == 2
    from seldon.workspace.pipeline import workspace_steps

    synthesis = next(step for step in workspace_steps(payload, result) if step["stage"] == "synthesis")
    assert synthesis["result"]["case_bounds"] == saved
    assert "Hot takes: conditional stress bounds" in render_markdown(state)
    with factory() as db, db.begin():
        version = db.scalar(select(ScenarioVersion).where(ScenarioVersion.scenario_prediction_id == result["prediction_id"]))
        assert version.snapshot["calibration_result"]["forecast"]["case_bounds"] == saved
        report = generate_report(db, state["scenario"]["id"], ReportRequest(request_id="hot-takes-report"))
        original_report = report_file(db, report["id"], "summary.md")["content"]
        assert "Demand acceleration" in original_report
    newer = forecast_payload(state)
    newer["request_id"] = "newer-forecast"
    newer["forecast"]["case_bounds"] = copy.deepcopy(bounds)
    newer["forecast"]["case_bounds"]["upper"]["value"] = 6500
    apply(factory, newer)
    with factory() as db:
        assert report_file(db, report["id"], "summary.md")["content"] == original_report
        assert db.scalar(select(ScenarioVersion).where(ScenarioVersion.scenario_prediction_id == result["prediction_id"])).snapshot["calibration_result"]["forecast"]["case_bounds"] == saved


def test_hot_take_bounds_reject_invalid_values_and_out_of_scope_citations(factory):
    from seldon.data.repositories import KBRepository

    state = researched(factory)
    with factory() as db, db.begin():
        orphan = KBRepository(db).create_entry(content="Not attached to the dependency scope", scenario_ids=[state["scenario"]["id"]])
        orphan_id = orphan.id
    state = export(factory, state["scenario"]["id"])
    payload = forecast_payload(state)
    bound = {"outcome": "Stress", "rationale": "Conditional drivers", "assumptions": ["A premise"], "evidence_ids": ["missing"], "value": None}
    payload["forecast"]["case_bounds"] = {"lower": dict(bound), "upper": dict(bound)}
    with pytest.raises(ValueError):
        apply(factory, payload)
    for side in ("lower", "upper"):
        payload["forecast"]["case_bounds"][side]["evidence_ids"] = [orphan_id]
    with pytest.raises(ValueError, match="outside the configured dependency scope"):
        apply(factory, payload)
    assert export(factory, state["scenario"]["id"])["revision"] == state["revision"]
    for lower, upper in ((5000, 2000), (2000, None), (2000, float("inf")), (2000, 2000)):
        payload["forecast"]["case_bounds"]["lower"]["value"] = lower
        payload["forecast"]["case_bounds"]["upper"]["value"] = upper
        with pytest.raises(ValidationError):
            WorkspaceApply.model_validate(payload)


def test_legacy_forecast_replay_fingerprint_is_preserved(factory):
    from seldon.workspace.service import _digest

    state = researched(factory)
    payload = forecast_payload(state)
    apply(factory, payload)
    with factory() as db, db.begin():
        run = next(r for r in db.scalars(select(AgentRun)) if r.input.get("request_id") == payload["request_id"])
        legacy = WorkspaceApply.model_validate(payload).model_dump(mode="json")
        for key in ("graph_scope", "reuse_node_ids", "reuse_edge_ids", "reuse_evidence_ids", "allow_shared_updates", "prediction_request_id"):
            legacy.pop(key)
        legacy["forecast"].pop("case_bounds")
        assert run.input["request_hash"] == _digest(legacy)
    assert apply(factory, payload)["replayed"]


def test_shared_knowledge_depth_and_frozen_forecast_history(factory):
    from seldon.data.models import ERGNode
    from seldon.workspace.knowledge import search_library

    gold = researched(factory)
    original = forecast_payload(gold)
    apply(factory, original)
    gold = export(factory, gold["scenario"]["id"])
    shared = next(n for n in gold["nodes"] if n["name"] == "Central bank buying")
    evidence_id = shared["kb_entry_ids"][0]
    with factory() as db, db.begin():
        ai = WorkspaceService(db).start(
            "AI data-center construction outlook?", "2027-03-28"
        )
    change = {
        "scenario_id": ai["scenario"]["id"],
        "base_revision": ai["revision"],
        "request_id": "reuse",
        "agent": "test",
        "reason": "Reuse researched policy driver",
        "reuse_node_ids": [shared["id"]],
        "nodes": [
            {
                "id": "ai",
                "name": "AI data-center buildout",
                "type": "metric",
                "evidence_ids": [evidence_id],
            }
        ],
        "edges": [
            {
                "id": "shared-ai",
                "source": shared["id"],
                "target": "ai",
                "description": "Fixture dependence",
                "evidence_ids": [evidence_id],
            }
        ],
        "graph_scope": {"target_node_id": "ai", "max_depth": 1},
    }
    apply(factory, change)
    ai = export(factory, ai["scenario"]["id"])
    assert {n["name"] for n in ai["nodes"]} == {
        "Central bank buying",
        "AI data-center buildout",
    }
    assert not any(n["name"] == "Gold price" for n in ai["nodes"])
    assert ai["graph_scope"]["max_depth"] == 1
    with factory() as db:
        assert len(search_library(db, "Central bank")["nodes"]) == 1
        assert set(db.get(ERGNode, shared["id"]).scenario_ids) == {
            ai["scenario"]["id"],
            gold["scenario"]["id"],
        }
    # A new upstream driver is immediately reusable through the shared entity,
    # but is unavailable to the shallow AI question until its depth increases.
    gold = export(factory, gold["scenario"]["id"])
    apply(
        factory,
        {
            "scenario_id": gold["scenario"]["id"],
            "base_revision": gold["revision"],
            "request_id": "upstream",
            "agent": "test",
            "reason": "Expand shared dependencies",
            "nodes": [
                {
                    "id": "policy",
                    "name": "Federal funds rate",
                    "type": "metric",
                    "evidence_ids": [evidence_id],
                }
            ],
            "edges": [
                {
                    "id": "policy-shared",
                    "source": "policy",
                    "target": shared["id"],
                    "description": "Fixture upstream driver",
                    "evidence_ids": [evidence_id],
                }
            ],
        },
    )
    ai = export(factory, ai["scenario"]["id"])
    assert len(ai["nodes"]) == 2
    apply(
        factory,
        {
            "scenario_id": ai["scenario"]["id"],
            "base_revision": ai["revision"],
            "request_id": "depth",
            "agent": "test",
            "reason": "Review an additional upstream hop",
            "graph_scope": {**ai["graph_scope"], "max_depth": 2},
        },
    )
    ai = export(factory, ai["scenario"]["id"])
    assert {n["name"] for n in ai["nodes"]} == {
        "Central bank buying",
        "AI data-center buildout",
        "Federal funds rate",
    }
    shared_update = {
        "scenario_id": ai["scenario"]["id"],
        "base_revision": ai["revision"],
        "request_id": "refresh",
        "agent": "test",
        "reason": "Reviewed use in both questions",
        "nodes": [
            {
                "id": shared["id"],
                "name": shared["name"],
                "type": shared["type"],
                "current_state": "Updated shared observation",
                "evidence_ids": [evidence_id],
            }
        ],
    }
    with pytest.raises(ValueError, match="Shared records"):
        apply(factory, shared_update)
    apply(factory, {**shared_update, "allow_shared_updates": True})
    ai = export(factory, ai["scenario"]["id"])
    refreshed_evidence = {
        **changes(ai)["evidence"][0],
        "id": evidence_id,
        "content": "Updated shared source observation",
    }
    apply(
        factory,
        {
            "scenario_id": ai["scenario"]["id"],
            "base_revision": ai["revision"],
            "request_id": "shared-evidence-refresh",
            "agent": "test",
            "reason": "Verify source-version reuse",
            "allow_shared_updates": True,
            "evidence": [refreshed_evidence],
        },
    )
    for id in (gold["scenario"]["id"], ai["scenario"]["id"]):
        current = export(factory, id)
        assert (
            next(e for e in current["evidence"] if e["id"] == evidence_id)["content"]
            == "Updated shared source observation"
        )
        assert (
            next(n for n in current["nodes"] if n["id"] == shared["id"])[
                "current_state"
            ]
            == "Updated shared observation"
        )
    history = export(factory, gold["scenario"]["id"])["prediction_history"]
    assert history[0]["knowledge_changed"] is True
    old_node = next(
        n for n in history[0]["graph_snapshot"]["nodes"] if n["id"] == shared["id"]
    )
    assert old_node["current_state"] != "Updated shared observation"
    assert (
        history[0]["graph_snapshot"]["evidence"][0]["content"]
        == "A fixture source reports central bank demand."
    )


def test_rerun_requests_complete_atomically_and_keep_forecasts(factory):
    from seldon.workspace.reruns import request_prediction, list_requests

    state = researched(factory)
    first = forecast_payload(state)
    first_result = apply(factory, first)
    id = state["scenario"]["id"]
    state = export(factory, id)
    assert state["prediction_history"][0]["knowledge_changed"] is False
    with factory() as db, db.begin():
        request = request_prediction(
            db, id, request_id="rerun", reason="New evidence review"
        )
        assert (
            request_prediction(
                db, id, request_id="rerun", reason="New evidence review"
            )["id"]
            == request["id"]
        )
    second = forecast_payload(state)
    second.update(request_id="forecast-2", prediction_request_id=request["id"])
    second["forecast"]["branches"][0]["probability"] = 0.7
    second["forecast"]["branches"][1]["probability"] = 0.3
    second["forecast"]["as_of"] = "2026-09-29T12:00:00Z"
    bad = copy.deepcopy(second)
    bad["forecast"]["resolution_date"] = "2027-04-28"
    with pytest.raises(ValueError, match="horizon"):
        apply(factory, bad)
    with factory() as db:
        assert list_requests(db, id)[0]["status"] == "pending"
    result = apply(factory, second)
    assert result["prediction_id"] != first_result["prediction_id"]
    state = export(factory, id)
    assert len(state["prediction_history"]) == 2
    assert state["prediction_history"][0]["prediction"]["probabilities"]["up"] == 0.6
    assert state["prediction_history"][1]["prediction"]["probabilities"]["up"] == 0.7
    assert state["prediction_requests"][0]["status"] == "completed"
    assert apply(factory, second)["replayed"]


def test_forecast_cannot_use_nodes_beyond_configured_depth(factory):
    state = researched(factory)
    id = state["scenario"]["id"]
    ev = state["evidence"][0]["id"]
    apply(
        factory,
        {
            "scenario_id": id,
            "base_revision": state["revision"],
            "request_id": "upstream",
            "agent": "test",
            "reason": "Bound prediction context",
            "nodes": [
                {
                    "id": "upstream",
                    "name": "Upstream policy",
                    "type": "policy",
                    "evidence_ids": [ev],
                }
            ],
            "edges": [
                {
                    "id": "upstream-buying",
                    "source": "upstream",
                    "target": "buying",
                    "description": "Policy drives demand",
                    "evidence_ids": [ev],
                }
            ],
            "graph_scope": {"target_node_id": "gold", "max_depth": 1},
        },
    )
    state = export(factory, id)
    assert len(state["nodes"]) == 2
    payload = forecast_payload(state)
    payload["forecast"]["node_assessments"].append(
        {
            "node_id": "upstream",
            "forecast": "Stable",
            "rationale": "Out of scope",
            "evidence_ids": [ev],
        }
    )
    with pytest.raises(ValueError, match="exactly one"):
        apply(factory, payload)
    assert not export(factory, id)["predictions"]


def test_research_forecast_export_and_replay_across_sessions(factory):
    state = initial(factory)
    assert export(factory, state["scenario"]["id"])["revision"] == state["revision"]
    payload = changes(state)
    result = apply(factory, payload)
    assert apply(factory, payload)["replayed"]
    state = export(factory, state["scenario"]["id"])
    assert result["revision"] == state["revision"]
    forecast = forecast_payload(state)
    result = apply(factory, forecast)
    assert result["prediction_id"]
    assert apply(factory, forecast)["prediction_id"] == result["prediction_id"]
    state = export(factory, state["scenario"]["id"])
    assert len(state["predictions"]) == 1
    assert state["dag"]["acyclic"]
    assert state["predictions"][0]["calibration_result"]["calibrated"] is False
    report = render_markdown(state)
    assert "Synthesize reviewed DAG" in report and "https://example.org/gold" in report
    with factory() as db:
        assert len(list(db.scalars(select(KBEntry)))) == 1
        assert len(list(db.scalars(select(ScenarioVersion)))) == 1
        assert len(list(db.scalars(select(AgentRun).where(AgentRun.phase == "external_workspace")))) == 2
        assert list(db.scalars(select(AuditLog)))


def test_current_research_report_surfaces_findings_without_forecast(factory):
    state = initial(factory)
    payload = changes(state)
    payload["nodes"][0]["current_state"] = "A sourced current assessment"
    payload["research_round"].update(
        stop_reason="budget",
        summary="Research findings with explicit limits",
        remaining_gaps=["Site ownership still needs verification"],
    )
    apply(factory, payload)
    state = export(factory, state["scenario"]["id"])
    report = render_markdown(state)
    overview = report.split("## Dependency map")[0]
    assert "Research findings with explicit limits" in overview
    assert "Site ownership still needs verification" in overview
    assert "A sourced current assessment" in overview
    assert "Latest forecast" not in report
    assert "Forecast probabilities" not in report
    assert state["predictions"] == []


@pytest.mark.parametrize(
    "invalid", ["cycle", "dangling", "duplicate", "stale", "cross_scenario"]
)
def test_bad_graph_mutation_rolls_back(factory, invalid):
    state = researched(factory)
    p = {
        "scenario_id": state["scenario"]["id"],
        "base_revision": state["revision"],
        "request_id": "bad",
        "agent": "test",
        "reason": "Should roll back",
        "evidence": [
            {
                "id": "unsaved",
                "content": "Must roll back",
                "kind": "assumption",
                "source_name": "test",
                "retrieved_at": "2026-09-28T00:00:00Z",
                "confidence": 0.1,
            }
        ],
        "edges": [
            {
                "id": "back",
                "source": "gold",
                "target": "buying",
                "description": "Invalid feedback",
            }
        ],
    }
    if invalid == "dangling":
        p["edges"][0]["source"] = "missing"
    elif invalid == "duplicate":
        p["edges"].append(copy.deepcopy(p["edges"][0]))
    elif invalid == "stale":
        p["base_revision"] = "old"
    elif invalid == "cross_scenario":
        other = researched(factory)
        p["edges"][0]["source"] = other["nodes"][0]["id"]
    # Caller intentionally catches error and commits: service savepoint must undo writes.
    with factory() as db, db.begin():
        with pytest.raises(ValueError):
            WorkspaceService(db).apply(WorkspaceApply.model_validate(p))
    assert export(factory, state["scenario"]["id"])["revision"] == state["revision"]


@pytest.mark.parametrize(
    "invalid",
    [
        "probabilities",
        "nan",
        "coverage",
        "no_stop",
        "assessment",
        "future_evidence",
        "exhausted_changes",
        "no_observations",
        "edge_evidence",
    ],
)
def test_forecast_gates(factory, invalid):
    state = researched(factory)
    p = forecast_payload(state)
    if invalid == "probabilities":
        p["forecast"]["branches"][0]["probability"] = 0.9
    elif invalid == "nan":
        p["forecast"]["branches"][0]["value_low"] = float("nan")
    elif invalid == "coverage":
        p["research_round"]["checked_node_ids"] = ["gold"]
    elif invalid == "no_stop":
        p["research_round"]["stop_reason"] = "continue"
    elif invalid == "assessment":
        p["forecast"]["node_assessments"].pop()
    elif invalid == "future_evidence":
        p["forecast"]["as_of"] = "2026-08-01T00:00:00Z"
    elif invalid == "exhausted_changes":
        p["nodes"] = [{"id": "extra", "name": "Additional factor", "type": "topic"}]
    else:
        with factory() as db, db.begin():
            if invalid == "no_observations":
                entry = db.get(KBEntry, state["evidence"][0]["id"])
                entry.source_type = "assumption"
            else:
                from seldon.data.models import ERGEdge

                db.get(ERGEdge, state["edges"][0]["id"]).evidence_kb_ids = []
        state = export(factory, state["scenario"]["id"])
        p["base_revision"] = state["revision"]
    with pytest.raises((ValueError, ValidationError)):
        apply(factory, p)
    assert export(factory, state["scenario"]["id"])["revision"] == state["revision"]


def test_request_id_collision_rejected(factory):
    state = initial(factory)
    p = changes(state)
    apply(factory, p)
    p["reason"] = "Different input"
    with pytest.raises(WorkspaceConflict, match="request_id"):
        apply(factory, p)


def test_cli_no_provider_configuration(tmp_path, capsys, monkeypatch):
    for key in ("OPENROUTER_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / "cli.db"
    assert (
        main(
            [
                "research",
                "--db",
                str(path),
                "start",
                "Will AI investment boom?",
                "--horizon",
                "2027-03-28",
            ]
        )
        == 0
    )
    state = json.loads(capsys.readouterr().out)
    assert str(path) in state["research_handoff"]
    assert state["scenario"]["id"] in state["research_handoff"]
    assert "current-state investigation" in state["research_handoff"]
    assert state["runs"] == []
    p = tmp_path / "changes.json"
    p.write_text(json.dumps(changes(state)))
    assert main(["research", "--db", str(path), "apply", str(p)]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "research",
                "--db",
                str(path),
                "export",
                state["scenario"]["id"],
                "--format",
                "markdown",
            ]
        )
        == 0
    )
    assert "Central bank buying" in capsys.readouterr().out
    assert (
        main(["research", "--db", str(path), "pipeline", state["scenario"]["id"]]) == 0
    )
    pipeline = json.loads(capsys.readouterr().out)
    assert pipeline["totals"]["completed"] == 3
    assert pipeline["totals"]["needs_followup"] == 1
    assert {event["entrypoint"] for event in pipeline["history"]} == {"external_agent"}


def test_api_workspace_contract_and_existing_views(tmp_path, monkeypatch):
    # Permit TestClient requests while making any LLM method fail immediately.
    from seldon.api.app import create_app
    from seldon.config import SeldonConfig
    from seldon.llm.openrouter import OpenRouterClient

    def forbidden(*args, **kwargs):
        raise AssertionError("Workspace must not call a model")

    monkeypatch.setattr(OpenRouterClient, "complete_json", forbidden)
    engine = make_engine(sqlite_path=tmp_path / "api.db")
    create_all(engine)
    client = TestClient(
        create_app(
            SeldonConfig(data_dir=tmp_path),
            session_factory=make_session_factory(engine),
        )
    )
    response = client.post(
        "/workspace/scenarios",
        json={"question": "Gold outlook?", "horizon": "2027-03-28"},
    )
    assert response.status_code == 201
    state = response.json()
    assert state["scenario"]["id"] in state["research_handoff"]
    assert client.post("/workspace/scenarios", json={"question": " ", "horizon": "today"}).status_code == 422
    response = client.post("/workspace/apply", json=changes(state))
    assert response.status_code == 200, response.text
    state = client.get(f"/workspace/scenarios/{state['scenario']['id']}").json()
    response = client.post("/workspace/apply", json=forecast_payload(state))
    assert response.status_code == 200, response.text
    id = response.json()["prediction_id"]
    assert client.get(f"/predictions/{id}").status_code == 200
    assert client.get("/graph/nodes").json()
    assert client.get("/workspace/schema").json()["properties"]["base_revision"]
    stale = forecast_payload(state)
    stale["request_id"] = "new-request-stale-state"
    assert client.post("/workspace/apply", json=stale).status_code == 409
    assert client.get("/workspace/scenarios/missing").status_code == 404
    pipeline = client.get(
        "/workspace/pipeline", params={"scenario_id": state["scenario"]["id"]}
    ).json()
    assert pipeline["totals"]["completed"] == pipeline["totals"]["stage_count"]
    assert any(item["id"] == id for item in pipeline["artifacts"])
    assert all(event["duration_s"] is None for event in pipeline["history"])
    assert client.get("/workspace/pipeline?scenario_id=missing").status_code == 404
    library = client.get("/workspace/library?q=Central%20bank").json()
    assert library["total"] == 1
    request = client.post(
        f"/workspace/scenarios/{state['scenario']['id']}/rerun",
        json={"request_id": "api-rerun"},
    )
    assert request.status_code == 202
    assert request.json()["status"] == "pending"
    requests = client.get(
        "/workspace/prediction-requests",
        params={"scenario_id": state["scenario"]["id"]},
    ).json()
    assert requests[0]["id"] == request.json()["id"]
    assert "handoff_prompt" in requests[0]["output"]
    engine.dispose()


def test_pipeline_historical_runs_replay_and_scenario_isolation(factory):
    from seldon.workspace.pipeline import pipeline_snapshot

    state = researched(factory)
    id = state["scenario"]["id"]
    payload = forecast_payload(state)
    apply(factory, payload)
    apply(factory, payload)
    other = initial(factory)
    with factory() as db, db.begin():
        # Runs written before stage metadata was introduced remain visible.
        for run in db.scalars(select(AgentRun)):
            output = dict(run.output)
            output.pop("pipeline_steps", None)
            run.output = output
    with factory() as db:
        before = WorkspaceService(db).export(id)["revision"]
        pipeline = pipeline_snapshot(db, id)
        assert pipeline["totals"]["completed"] == 9
        assert pipeline["history_total"] == 11
        assert len({event["id"] for event in pipeline["history"]}) == 11
        assert pipeline_snapshot(db, other["scenario"]["id"])["history_total"] == 0
        assert WorkspaceService(db).export(id)["revision"] == before


def test_python_agents_share_pipeline_and_expose_failures(factory):
    from pydantic import BaseModel
    from seldon.agents.base import AgentBase
    from seldon.data.repositories import AgentRunRepository
    from seldon.workspace.pipeline import pipeline_snapshot

    class Payload(BaseModel):
        scenario_id: str

    class Result(BaseModel):
        nodes_created: int

    class PythonExtraction(AgentBase):
        agent_id = "extraction_coordinator"
        phase = "extraction"

        def _run(self, payload, **kwargs):
            return Result(nodes_created=2)

    state = initial(factory)
    id = state["scenario"]["id"]
    with factory() as db, db.begin():
        parent_id, _ = PythonExtraction(db).run(Payload(scenario_id=id))
        child = AgentRunRepository(db).create(
            agent_id="node_state_predictor",
            phase="prediction",
            status="failed",
            input={"payload": {"node_id": "a-node"}, "parent_run_id": parent_id},
            error="Provider unavailable",
            elapsed_ms=23,
        )
        child_id = child.id
    with factory() as db:
        pipeline = pipeline_snapshot(db, id)
        stages = {stage["name"]: stage for stage in pipeline["stages"]}
        assert stages["extraction"]["status"] == "completed"
        assert stages["node_prediction"]["status"] == "failed"
        assert stages["node_prediction"]["latest"]["run_id"] == child_id
        assert stages["node_prediction"]["latest"]["error"] == "Provider unavailable"
        assert stages["prediction"]["status"] == "not_started"
        assert {event["entrypoint"] for event in pipeline["history"]} == {"python"}


def test_caller_rollback_undoes_successful_apply(factory):
    state = initial(factory)
    with factory() as db:
        WorkspaceService(db).apply(WorkspaceApply.model_validate(changes(state)))
        db.rollback()
    assert export(factory, state["scenario"]["id"])["revision"] == state["revision"]


def test_scenario_detachment_preserves_history_and_rejects_dangling_edges(factory):
    from seldon.data.models import ERGEdge, ERGNode

    state = researched(factory)
    request = {
        "scenario_id": state["scenario"]["id"],
        "base_revision": state["revision"],
        "request_id": "retract",
        "agent": "test",
        "reason": "Retire an invalid factor",
        "detach_nodes": ["buying"],
    }
    with pytest.raises(ValueError, match="endpoints"):
        apply(factory, request)
    request["detach_edges"] = ["demand"]
    apply(factory, request)
    after = export(factory, state["scenario"]["id"])
    assert len(after["nodes"]) == 1 and not after["edges"]
    with factory() as db:
        assert len(list(db.scalars(select(ERGNode)))) == 2
        assert len(list(db.scalars(select(ERGEdge)))) == 1
        assert len(list(db.scalars(select(KBEntry)))) == 1
    assert apply(factory, request)["replayed"]
