"""Cycle factors: model recovery, red-noise honesty, event persistence, combination and forecast hooks."""

import json
import math
from datetime import date

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import GraphSnapshot
from seldon.workspace.cycles import (
    apply_cycles,
    discover,
    export_view,
    import_csv,
    load_state,
    outlook,
    parse_csv,
    preferred_fit,
    record_fit,
    refit_stale,
)
from seldon.workspace.cycles.combine import combine
from seldon.workspace.cycles.fitting import Series, fit_harmonic, fit_oscillator, harmonic_value, residual_spectrum
from seldon.workspace.cycles.schemas import CyclesApply, Factor, FitSpec, ImportRequest, Observation
from seldon.workspace.knowledge import knowledge_revision, scoped_graph, snapshot_data
from seldon.workspace.schemas import WorkspaceApply
from seldon.workspace.service import WorkspaceConflict, WorkspaceService

SPEC = FitSpec(surrogates=100).model_dump(mode="json")
RETRIEVED = "2026-11-01T00:00:00Z"


@pytest.fixture
def factory(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Cycle tools must not use providers or the network")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    engine = make_engine(sqlite_path=tmp_path / "cycles.db")
    create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


def wave(years, period=80.0, peak=2050.0, noise=0.3, trend=0.0, seed=1):
    rng = np.random.default_rng(seed)
    t = np.asarray(years, dtype=float)
    return np.cos(2 * math.pi * (t - peak) / period) + trend * (t - t[0]) + noise * rng.standard_normal(len(t))


def observations(factor_id, years, values, **extra):
    return [
        {"factor_id": factor_id, "date": f"{int(y)}-07-02", "value": float(v), "source_name": "Fixture dataset", "source_url": "https://example.org/data", "retrieved_at": RETRIEVED, **extra}
        for y, v in zip(years, values)
    ]


def change(db, request_id, **kwargs):
    kwargs.setdefault("agent", "test-agent")
    kwargs.setdefault("reason", "Fixture change")
    return apply_cycles(db, CyclesApply.model_validate({"request_id": request_id, "base_revision": load_state(db)["revision"], **kwargs}))


# ----------------------------------------------------------------------------- models


def test_harmonic_recovers_period_phase_and_turning_points():
    years = np.arange(1800, 2025)
    fit = fit_harmonic(Series(years.astype(float), wave(years, trend=0.002)), SPEC, seed=4)
    cycle = fit["components"][0]
    assert abs(cycle["period_years"] - 80) < 2
    assert cycle["phase_label_at_end"] == "rising"  # 2024 sits between the 2010 trough and 2050 peak
    assert fit["diagnostics"]["significance"]["p_value"] < 0.05
    assert fit["diagnostics"]["backtest"]["skill_vs_trend"] > 0
    assert fit["verdict"] == "supported"
    peak = fit["turning_points"]["upcoming"][0]
    assert peak["type"] == "peak" and 2046 <= int(peak["date"][:4]) <= 2056
    assert peak["window"][0] <= peak["date"] <= peak["window"][1]
    assert all(lo <= m <= hi for lo, m, hi in zip(fit["projection"]["lower"][5:], fit["projection"]["mean"][5:], fit["projection"]["upper"][5:]))


def test_asymmetric_boom_bust_needs_harmonics_and_short_records_are_under_identified():
    years = np.arange(1870, 2025).astype(float)
    phase = ((years - 1872) % 18) / 18
    saw = np.where(phase < 0.8, phase * 2 - 1, 1 - (phase - 0.8) / 0.2 * 2)
    one = fit_harmonic(Series(years, saw), SPEC, seed=1)
    three = fit_harmonic(Series(years, saw), {**SPEC, "harmonics": 3}, seed=1)
    assert three["diagnostics"]["r2"] > one["diagnostics"]["r2"] + 0.05
    short = np.arange(1990, 2025).astype(float)
    fit = fit_harmonic(Series(short, wave(short, period=60, peak=2000, noise=0.05)), {**SPEC, "period_min_years": 40, "period_max_years": 80}, seed=2)
    assert fit["verdict"] == "under-identified"
    assert any("Fewer than two full cycles" in w for w in fit["warnings"])


def test_red_noise_is_not_reported_as_a_supported_cycle():
    rng = np.random.default_rng(11)
    x = np.zeros(225)
    for i in range(1, len(x)):
        x[i] = 0.9 * x[i - 1] + rng.standard_normal()
    fit = fit_harmonic(Series(np.arange(1800, 2025).astype(float), x), SPEC, seed=3)
    assert fit["verdict"] != "supported"
    assert fit["diagnostics"]["significance"]["p_value"] >= 0.05


def test_oscillator_measures_inertia_and_whiplash():
    rng = np.random.default_rng(5)
    r, theta = 0.9, 2 * math.pi / 9
    phi = [2 * r * math.cos(theta), -r * r]
    x = np.zeros(300)
    for i in range(2, len(x)):
        x[i] = phi[0] * x[i - 1] + phi[1] * x[i - 2] + rng.standard_normal()
    fit = fit_oscillator(Series(np.arange(1725, 2025).astype(float), x), {**SPEC, "model": "oscillator"}, seed=6)
    dynamics = fit["dynamics"]
    assert dynamics["oscillatory"] and abs(dynamics["period_years"] - 9) < 1
    assert dynamics["overshoot"] > 0.5 and dynamics["first_zero_crossing_years"] <= 4
    assert 0 < dynamics["damping_ratio"] < 1 and dynamics["phase_label_at_end"]
    assert fit["verdict"] == "supported"
    persistent = np.zeros(300)
    for i in range(1, len(persistent)):
        persistent[i] = 0.8 * persistent[i - 1] + rng.standard_normal()
    calm = fit_oscillator(Series(np.arange(1725, 2025).astype(float), persistent), {**SPEC, "model": "oscillator"}, seed=6)
    assert calm["verdict"] == "not-oscillatory" and calm["dynamics"]["overshoot"] < 0.05
    assert calm["dynamics"]["half_life_years"] > 1


def test_residual_search_finds_hidden_cycle_and_flags_harmonics():
    years = np.arange(1800, 2025).astype(float)
    rng = np.random.default_rng(9)
    y = np.cos(2 * math.pi * years / 60) + 0.6 * np.sin(2 * math.pi * years / 11) + 0.2 * rng.standard_normal(len(years))
    fit = fit_harmonic(Series(years, y), SPEC, seed=5)
    assert abs(fit["components"][0]["period_years"] - 60) < 2
    found = residual_spectrum(years, y - harmonic_value(fit["params"], years), np.ones(len(years)), [60.0], seed=1, surrogates=100)
    best = found["candidates"][0]
    assert abs(best["period_years"] - 11) < 0.5 and best["p_value"] < 0.05 and best["relation"] is None
    harmonic = residual_spectrum(years, np.cos(2 * math.pi * years / 30) + 0.1 * rng.standard_normal(len(years)), np.ones(len(years)), [60.0], seed=1, surrogates=50)
    assert "harmonic 2" in harmonic["candidates"][0]["relation"]
    joint = fit_harmonic(Series(years, y), {**SPEC, "cycles": 2}, seed=5)
    assert sorted(round(c["period_years"]) for c in joint["components"]) == [11, 60]


# ----------------------------------------------------------------------------- contracts


def test_contracts_require_provenance_and_coherent_specs():
    with pytest.raises(ValidationError, match="rubric"):
        Factor(id="mood", name="Mood", measurement="coded")
    with pytest.raises(ValidationError, match="derived_from"):
        Factor(id="latent", name="Latent", measurement="derived")
    with pytest.raises(ValidationError, match="source URL"):
        Observation(factor_id="x", date="2000-01-01", value=1, source_name="Blog", retrieved_at=RETRIEVED)
    Observation(factor_id="x", date="2000-01-01", value=1, kind="assumption", source_name="Analyst prior", retrieved_at=RETRIEVED)
    with pytest.raises(ValidationError, match="timezone"):
        Observation(factor_id="x", date="2000-01-01", value=1, source_name="S", source_url="https://example.org", retrieved_at="2026-01-01T00:00:00")
    with pytest.raises(ValidationError):
        FitSpec(period_min_years=50, period_max_years=40)
    with pytest.raises(ValidationError):
        FitSpec(period_years=80, cycles=2)


def test_csv_parser_handles_fred_missing_values_and_year_anchors():
    fred = 'observation_date,GDP\n2000-01-01,10\n2000-04-01,.\n2000-07-01,"1,234.5"\n'
    rows = parse_csv(fred, ImportRequest(csv=fred, source_name="FRED"))
    assert [r["value"] for r in rows] == [10.0, 1234.5]
    annual = "year,value,se\n1900,1,0.1\n1901,2,\n"
    rows = parse_csv(annual, ImportRequest(csv=annual, source_name="S", value_column="value", uncertainty_column="se", year_anchor="end"))
    assert rows[0] == {"date": "1900-12-31", "value": 1.0, "uncertainty": 0.1} and rows[1]["uncertainty"] is None
    with pytest.raises(ValueError, match="value_column"):
        parse_csv(annual, ImportRequest(csv=annual, source_name="S"))


# ----------------------------------------------------------------------------- persistence


def test_registry_apply_refits_replays_conflicts_and_keeps_history(factory):
    years = np.arange(1850, 2025)
    with factory() as db, db.begin():
        result = change(db, "define", factors=[{"id": "credit", "name": "Credit cycle", "template": "financial-speculation", "region": "United States", "fit": {"surrogates": 50}}])
        assert result["warnings"] and not result["fits"]  # no data yet: defined, not fitted
        factor = load_state(db)["factors"]["credit"]
        assert factor["fit"]["period_min_years"] == 10 and factor["phase_labels"]["peak"].startswith("Mania")
        payload = CyclesApply.model_validate({"request_id": "load", "base_revision": load_state(db)["revision"], "agent": "loader", "reason": "Load", "observations": observations("credit", years, wave(years, period=18, peak=2006))})
        loaded = apply_cycles(db, payload)
        assert loaded["counts"]["observations"] == len(years) and len(loaded["fits"]) == 1
        assert loaded["fits"][0]["verdict"] == "supported"
        assert apply_cycles(db, payload)["replayed"]
        with pytest.raises(WorkspaceConflict, match="different input"):
            apply_cycles(db, payload.model_copy(update={"reason": "changed"}))
        with pytest.raises(WorkspaceConflict, match="changed"):
            apply_cycles(db, payload.model_copy(update={"request_id": "stale"}))
        before = load_state(db)
        with pytest.raises(ValueError, match="Unknown cycle factor"):
            change(db, "bad", factors=[{"id": "ghost-free", "name": "Must roll back"}], observations=observations("missing", [2000], [1]))
        assert load_state(db)["revision"] == before["revision"] and "ghost-free" not in load_state(db)["factors"]
        first_fit, status = preferred_fit(before, "credit")
        assert status == "fresh"
        key = before["by_factor"]["credit"][-1]["id"]
        change(db, "revise", observations=[{**observations("credit", [2024], [5.0])[0], "id": key}])
        change(db, "withdraw", observations=[{**observations("credit", [2024], [5.0])[0], "id": key, "status": "withdrawn"}])
    with factory() as db:
        state = load_state(db)
        fit, status = preferred_fit(state, "credit")
        assert status == "fresh" and fit["id"] != first_fit["id"]
        assert first_fit["id"] in state["fits"]  # old fits stay immutable in history
        assert state["versions"][key] == 3 and fit["data"]["n"] == len(years) - 1
        view = export_view(state, factor_id="credit")["factors"][0]
        assert view["series"]["withdrawn"] == 1 and view["series"]["revised"] == 1
        assert len(view["fits"]) == 3 and all(f["preferred"] for f in view["fits"])
        assert len(state["history"]) == 4  # the rejected request left no event


def test_explicit_fits_are_exploratory_and_refit_catches_up(factory):
    years = np.arange(1900, 2025)
    with factory() as db, db.begin():
        change(db, "define", refit=False, factors=[{"id": "war", "name": "War intensity", "template": "great-power-war", "fit": {"model": "oscillator", "surrogates": 0}}], observations=observations("war", years, wave(years, period=30, peak=1945)))
        assert preferred_fit(load_state(db), "war")[1] == "missing"
        harmonic = record_fit(db, "war", FitSpec(model="harmonic", surrogates=50), agent="a", reason="compare")
        assert not harmonic["preferred"] and "Exploratory" in harmonic["note"]
        assert record_fit(db, "war", FitSpec(model="harmonic", surrogates=50), agent="a", reason="compare")["replayed"]
        refit = refit_stale(db, agent="a", reason="catch up")
        assert [f["factor_id"] for f in refit["fitted"]] == ["war"] and refit["fitted"][0]["model"] == "oscillator"
        assert refit_stale(db, agent="a", reason="again")["unchanged"]
        with pytest.raises(KeyError):
            record_fit(db, "missing", None, agent="a", reason="x")


def test_derived_latent_factor_tracks_components_and_rejects_cycles(factory):
    years = np.arange(1900, 2025)
    with factory() as db, db.begin():
        change(db, "define", factors=[{"id": "a", "name": "A", "fit": {"surrogates": 0}}, {"id": "b", "name": "B", "fit": {"surrogates": 0}}, {"id": "latent", "name": "Latent driver", "measurement": "derived", "derived_from": [{"factor_id": "a"}, {"factor_id": "b", "weight": -1}], "fit": {"surrogates": 0}}], observations=observations("a", years, wave(years, period=40, peak=2000)) + observations("b", years, -wave(years, period=40, peak=2000, seed=2)))
        state = load_state(db)
        latent, status = preferred_fit(state, "latent")
        assert status == "fresh" and abs(latent["components"][0]["period_years"] - 40) < 2
        result = change(db, "more-a", observations=observations("a", [2025], [0.5]))
        assert {f["factor_id"] for f in result["fits"]} == {"a", "latent"}  # dependents refit with their components
        with pytest.raises(ValueError, match="DAG"):
            change(db, "loop", factors=[{**load_state(db)["factors"]["a"], "measurement": "derived", "derived_from": [{"factor_id": "latent"}]}])
        with pytest.raises(ValueError, match="computed from components"):
            change(db, "direct", observations=observations("latent", [2000], [1]))


def test_combination_alignment_lead_lag_and_outlook(factory):
    years = np.arange(1850, 2025)
    with factory() as db, db.begin():
        change(db, "define", factors=[{"id": "x", "name": "X", "fit": {"surrogates": 0, "period_min_years": 20, "period_max_years": 60}}, {"id": "y", "name": "Y", "fit": {"surrogates": 0, "period_min_years": 20, "period_max_years": 60}}], observations=observations("x", years, wave(years, period=40, peak=2030, noise=0.05)) + observations("y", years, wave(years, period=40, peak=2025, noise=0.05, seed=3)))
        state = load_state(db)
        same = combine(state, [{"factor_id": "x", "weight": 1, "lag_years": 0}, {"factor_id": "y", "weight": 1, "lag_years": 5}], at=date(2040, 1, 1))
        assert same["at"]["alignment"] > 0.95 and same["alignment_windows"]
        opposed = combine(state, [{"factor_id": "x", "weight": 1, "lag_years": 0}, {"factor_id": "y", "weight": -1, "lag_years": 5}], at=date(2040, 1, 1))
        assert opposed["at"]["alignment"] < 0.1
        relation = same["lead_lag"][0]
        assert relation["strength"] == "strong" and abs(abs(relation["lag_years"]) - 5) <= 1 and "y leads x" in relation["relation"]
        result = outlook(state, factor_ids=["x"], at=date(2030, 1, 1))["factors"][0]
        assert result["at"]["relation"] == "projected" and result["at"]["phases"][0]["quadrant"] == "peak"
        assert result["evidence_template"]["kind"] == "assumption" and "not an observation" in result["evidence_template"]["content"]
        assert discover(state, "x", surrogates=20)["candidates"]


# ----------------------------------------------------------------------------- forecast hook


def _research(db):
    service = WorkspaceService(db)
    state = service.start("Will US credit stress rise by 2030?", "Resolve on 2030-01-01")
    sid = state["scenario"]["id"]
    payload = {
        "scenario_id": sid, "base_revision": state["revision"], "request_id": "round-1", "agent": "agent", "reason": "Graph",
        "evidence": [{"id": "src", "content": "Fixture source on credit conditions.", "source_name": "Fixture", "source_url": "https://example.org/credit", "published_at": "2026-09-01T00:00:00Z", "retrieved_at": "2026-09-28T00:00:00Z", "confidence": 0.7}],
        "nodes": [{"id": "stress", "name": "Credit stress", "type": "metric", "evidence_ids": ["src"]}, {"id": "cycle", "name": "Credit cycle position", "type": "metric", "evidence_ids": ["src"]}],
        "edges": [{"id": "edge", "source": "cycle", "target": "stress", "description": "Late-cycle leverage raises stress", "evidence_ids": ["src"]}],
        "graph_scope": {"target_node_id": "stress"},
    }
    result = service.apply(WorkspaceApply.model_validate(payload))
    return sid, result["ids"]["node"]["cycle"]


def test_linked_cycles_enter_forecast_context_freeze_and_mark_staleness(factory):
    years = np.arange(1870, 2025)
    with factory() as db, db.begin():
        sid, cycle_node = _research(db)
        baseline = knowledge_revision(scoped_graph(db, sid))
        change(db, "unlinked", factors=[{"id": "other", "name": "Unlinked", "fit": {"surrogates": 0}}], observations=observations("other", years, wave(years)))
        assert knowledge_revision(scoped_graph(db, sid)) == baseline  # unrelated cycle work never stales a question
        assert "cycles" not in snapshot_data(scoped_graph(db, sid))
        change(db, "linked", factors=[{"id": "credit", "name": "Credit cycle", "template": "financial-speculation", "entity_ids": [cycle_node], "fit": {"surrogates": 50}}], observations=observations("credit", years, wave(years, period=18, peak=2006)))
        view = scoped_graph(db, sid)
        context = view["cycles"]
        assert context["at"] == "2030-01-01" and [f["factor_id"] for f in context["factors"]] == ["credit"]
        assert context["factors"][0]["at"]["relation"] == "projected"
        linked_revision = knowledge_revision(view)
        assert linked_revision != baseline
        snapshot = GraphSnapshot(scenario_id=sid, snapshot=snapshot_data(view), agent_id="t", reason="freeze")
        db.add(snapshot)
        db.flush()
        export = WorkspaceService(db).export(sid)
        assert export["cycles"]["factors"][0]["fit"]["verdict"] in {"supported", "weak"}
        assert "seldon-cycles" in export["research_handoff"]
        from seldon.workspace.service import render_markdown
        assert "## Cycle priors" in render_markdown(export)
        change(db, "new-data", observations=observations("credit", [2025], [0.9]))
        assert knowledge_revision(scoped_graph(db, sid)) != linked_revision  # new data refits and stales linked forecasts
        assert snapshot.snapshot["cycles"]["factors"][0]["fit"]["data"]["n"] == len(years)  # frozen context is unchanged
        from seldon.workspace.reports import ReportRequest, generate_report, report_file
        report = generate_report(db, sid, ReportRequest(request_id="r"))
        assert "Cycle priors" in report_file(db, report["id"], "summary.md")["content"]


# ----------------------------------------------------------------------------- interfaces


def test_cli_roundtrip_without_providers(factory, tmp_path, capsys):
    from seldon.cli import main

    db = str(tmp_path / "cli.db")

    def run(*args):
        assert main(["research", "--db", db, "cycles", *args]) == 0
        out = capsys.readouterr().out
        return json.loads(out) if out.lstrip().startswith(("{", "[")) else out

    assert "harmonic" in run("catalog")["models"]
    assert "observations" in run("schema")["properties"]
    revision = run("export")["revision"]
    spec = tmp_path / "factors.json"
    spec.write_text(json.dumps({"request_id": "define", "base_revision": revision, "agent": "cli", "reason": "Define", "factors": [{"id": "trade", "name": "Trade openness", "template": "globalization-wave", "units": "% GDP", "fit": {"surrogates": 30}}]}))
    run("apply", str(spec))
    years = np.arange(1820, 2025, 2)
    csv = tmp_path / "trade.csv"
    csv.write_text("date,openness\n" + "\n".join(f"{y}-07-01,{30 + 10 * v:.3f}" for y, v in zip(years, wave(years, period=95, peak=1913))))
    imported = run("import", "trade", str(csv), "--source-name", "Fixture", "--source-url", "https://example.org/trade")
    assert imported["imported"] == len(years) and imported["fits"]
    assert run("import", "trade", str(csv), "--source-name", "Fixture", "--source-url", "https://example.org/trade")["replayed"]
    explored = run("fit", "trade", "--model", "oscillator", "--set", "step_years=2")
    assert explored["fit"]["model"] == "oscillator" and not explored["preferred"]
    assert "| Trade openness |" in run("export", "--format", "markdown")
    assert run("outlook", "--factor", "trade", "--at", "2030-01-01")["factors"][0]["at"]["relation"] == "projected"
    assert "candidates" in run("discover", "trade", "--surrogates", "20")
    assert run("combine", "--component", "trade:1:0", "--at", "2030-01-01")["at"]["date"] == "2030-01-01"
    out = tmp_path / "trade.svg"
    run("chart", "--factor", "trade", "--out", str(out))
    svg = out.read_text()
    assert svg.startswith("<svg") and "Trade openness" in svg and "prefers-color-scheme: dark" in svg
    history = run("export")["history"]
    assert run("history", history[0]["id"])["event"]["changes"]["factors"][0]["id"] == "trade"


def test_api_routes_share_validation_and_render_charts(tmp_path, monkeypatch):
    from seldon.api.app import create_app
    from seldon.config import SeldonConfig
    from seldon.llm.openrouter import OpenRouterClient

    monkeypatch.setattr(OpenRouterClient, "complete_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model calls")))
    engine = make_engine(sqlite_path=tmp_path / "api.db")
    create_all(engine)
    client = TestClient(create_app(SeldonConfig(data_dir=tmp_path), session_factory=make_session_factory(engine)))
    assert client.get("/workspace/cycles/catalog").json()["templates"]["generational-saeculum"]["phase_labels"]["rising"].startswith("Crisis")
    assert client.get("/workspace/cycles/schema?part=fit").status_code == 200
    revision = client.get("/workspace/cycles").json()["revision"]
    body = {"request_id": "define", "base_revision": revision, "agent": "api", "reason": "Define", "factors": [{"id": "mood", "name": "Civic mood", "measurement": "coded", "rubric": "+1 strong institutions, -1 fragmentation", "template": "generational-saeculum", "fit": {"surrogates": 0}}]}
    assert client.post("/workspace/cycles/apply", json=body).status_code == 200
    assert client.post("/workspace/cycles/apply", json={**body, "request_id": "stale"}).status_code == 409
    assert client.post("/workspace/cycles/apply", json={**body, "factors": [{"id": "bad", "name": "Bad", "measurement": "coded"}]}).status_code == 422
    years = np.arange(1700, 2025, 5)
    csv = "year,score\n" + "\n".join(f"{y},{v:.3f}" for y, v in zip(years, wave(years, period=85, peak=1950, noise=0.1)))
    imported = client.post("/workspace/cycles/factors/mood/import", json={"csv": csv, "source_name": "Fixture coding", "source_url": "https://example.org/mood", "kind": "coded"})
    assert imported.status_code == 200, imported.text
    assert imported.json()["fits"][0]["cycles"][0]["phase_at_end"] in {"High", "Awakening", "Unraveling", "Crisis (Fourth Turning)"}
    assert client.post("/workspace/cycles/factors/missing/import", json={"csv": csv, "source_name": "x", "kind": "assumption"}).status_code == 404
    fit = client.post("/workspace/cycles/factors/mood/fit", json={"spec": {"model": "harmonic", "period_years": 80, "surrogates": 20}})
    assert fit.status_code == 200 and fit.json()["fit"]["cycles"][0]["period_years"] == 80
    chart = client.get("/workspace/cycles/factors/mood/chart.svg")
    assert chart.status_code == 200 and chart.headers["content-type"].startswith("image/svg+xml") and "Civic mood" in chart.text
    assert client.get("/workspace/cycles/outlook", params={"factor_id": "mood", "at": "2035-01-01"}).json()["factors"][0]["at"]["phases"]
    assert client.post("/workspace/cycles/combine", json={"components": [{"factor_id": "mood"}]}).status_code == 200
    assert client.post("/workspace/cycles/combine", json={}).status_code == 422
    assert client.get("/workspace/cycles/factors/mood/discover", params={"surrogates": 10}).status_code == 200
    assert client.get("/workspace/cycles", params={"format": "markdown"}).text.startswith("# Cycle factors")
    assert client.get("/workspace/cycles/history/missing").status_code == 404


def test_import_request_rejects_unsourced_measured_series(factory):
    with factory() as db, db.begin():
        change(db, "define", factors=[{"id": "f", "name": "F", "fit": {"surrogates": 0}}])
        with pytest.raises(ValidationError, match="source URL"):
            import_csv(db, "f", ImportRequest(csv="year,v\n2000,1\n2001,2\n", source_name="Unknown"))


def test_import_replays_default_ids_but_rejects_reused_explicit_ids(factory):
    with factory() as db, db.begin():
        change(db, "define", factors=[{"id": "f", "name": "F", "fit": {"surrogates": 0}}])
        csv = "year,v\n" + "\n".join(f"{y},{y % 7}" for y in range(1950, 2000))
        first = import_csv(db, "f", ImportRequest(csv=csv, source_name="S", source_url="https://example.org/s"))
        again = import_csv(db, "f", ImportRequest(csv=csv, source_name="S", source_url="https://example.org/s"))
        assert first["imported"] == 50 and again["replayed"]
        import_csv(db, "f", ImportRequest(csv=csv, source_name="T", source_url="https://example.org/t", request_id="mine"))
        with pytest.raises(WorkspaceConflict):
            import_csv(db, "f", ImportRequest(csv=csv + "\n2000,1", source_name="T", source_url="https://example.org/t", request_id="mine"))


def test_topic_relevance_lookup_selects_cycles_for_questions(factory, tmp_path, capsys):
    from seldon.cli import main
    from seldon.workspace.cycles import relevance_view
    from seldon.workspace.cycles.catalog import CYCLE_GUIDANCE
    from seldon.workspace.cycles.schemas import CycleTopic, Relevance
    from seldon.workspace.reruns import request_prediction

    years = np.arange(1900, 2025)
    with factory() as db, db.begin():
        sid, cycle_node = _research(db)
        stress = next(n for n in scoped_graph(db, sid)["nodes"] if n.id != cycle_node)
        stress.tags = [*stress.tags, "role:lender"]
        db.flush()
        baseline = knowledge_revision(scoped_graph(db, sid))
        factors = [{"id": key, "name": key.title(), "fit": {"surrogates": 0}} for key in ("rates", "credit", "noise")]
        series = observations("rates", years, wave(years, period=30)) + observations("credit", years, wave(years, period=12, seed=2)) + observations("noise", years, wave(years, period=50, seed=3))
        change(db, "factors", factors=factors, observations=series)
        assert knowledge_revision(scoped_graph(db, sid)) == baseline  # no topic or link yet
        rel = lambda topic, factor, score, **extra: {"topic_id": topic, "factor_id": factor, "score": score, "channel": "fixture channel", "rationale": "fixture rationale", "assessed_at": RETRIEVED, **extra}  # noqa: E731
        with pytest.raises(ValueError, match="Unknown cycle topic"):
            change(db, "bad-topic", relevance=[rel("missing", "rates", 0.5)])
        with pytest.raises(ValidationError, match="exactly one"):
            Relevance.model_validate({**rel("t", "rates", 0.5), "composite_id": "c"})
        with pytest.raises(ValidationError, match="entity_ids or tags"):
            CycleTopic(id="empty", name="Empty")
        change(
            db, "topics",
            topics=[{"id": "credit-markets", "name": "Credit markets", "entity_ids": [stress.id]}, {"id": "lenders", "name": "Lenders", "tags": ["Role:Lender"]}, {"id": "unrelated", "name": "Unrelated", "tags": ["role:nobody"]}],
            relevance=[rel("credit-markets", "rates", 0.6, direction="negative"), rel("lenders", "credit", 0.9), rel("credit-markets", "credit", 0.4), rel("credit-markets", "noise", 0.1), rel("unrelated", "noise", 1.0)],
        )
        state = load_state(db)
        assert state["topics"]["lenders"]["tags"] == ["role:lender"]  # normalized for tag matching
        context = scoped_graph(db, sid)["cycles"]
        assert [f["factor_id"] for f in context["factors"]] == ["credit", "rates"]  # by score; noise below floor / unmatched
        credit = context["factors"][0]["relevance"]
        assert credit["score"] == 0.9 and [t["topic_id"] for t in credit["topics"]] == ["lenders", "credit-markets"]
        assert {t["topic_id"] for t in context["topics"]} == {"credit-markets", "lenders"} and context["guidance"] == CYCLE_GUIDANCE
        assert knowledge_revision(scoped_graph(db, sid)) != baseline
        # A cycle scored highly only for an upstream driver ranks below cycles relevant to the forecast target.
        change(db, "driver-topic", topics=[{"id": "drivers", "name": "Drivers", "entity_ids": [cycle_node]}], relevance=[rel("drivers", "noise", 0.95)])
        ranked = scoped_graph(db, sid)["cycles"]["factors"]
        assert [f["factor_id"] for f in ranked] == ["credit", "rates", "noise"]
        assert ranked[2]["relevance"]["score"] == 0.95 and ranked[2]["relevance"]["target_score"] is None
        assert ranked[0]["relevance"]["target_score"] == 0.9
        change(db, "revise", relevance=[rel("credit-markets", "rates", 0.2)])
        assert [f["factor_id"] for f in scoped_graph(db, sid)["cycles"]["factors"]] == ["credit", "noise"]
        lookup = relevance_view(load_state(db), topic_id="credit-markets")
        assert [r["factor_id"] for r in lookup["relevance"]] == ["credit", "rates", "noise"]
        assert len(load_state(db)["history"]) == 4  # factors, topics, driver topic, revised score; failures left no events
        assert "use every relevant cycle prior" in WorkspaceService(db).export(sid)["research_handoff"]
        prompt = request_prediction(db, sid, request_id="cycles", reason="test", horizon="2030-01-01")["output"]["handoff_prompt"]
        assert CYCLE_GUIDANCE in prompt
    path = str(factory.kw["bind"].url.database)
    assert main(["research", "--db", path, "cycles", "relevance", "--scenario", sid]) == 0
    resolved = json.loads(capsys.readouterr().out)["question"]
    assert [f["factor_id"] for f in resolved["factors"]] == ["credit", "noise"]
    assert main(["research", "--db", path, "cycles", "outlook", "--scenario", sid, "--floor", "0.05"]) == 0
    assert {f["factor_id"] for f in json.loads(capsys.readouterr().out)["factors"]} == {"credit", "rates", "noise"}
