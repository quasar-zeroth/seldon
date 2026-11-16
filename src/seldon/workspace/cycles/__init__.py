"""Cycle factors, dated series, immutable fits and composites as append-only AgentRun events.

A `Source` row serializes writers; every factor definition, observation revision
and fit stays in event history. Fits are deterministic functions of a factor's
data revision and specification. No provider or network access is used.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from calendar import monthrange
from datetime import date, datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import networkx as nx
import numpy as np
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from seldon.data.models import AgentRun, ERGNode, KBEntry, Source
from seldon.data.tags import normalize_tag

from . import fitting
from .catalog import CYCLE_GUIDANCE, RELEVANCE_FLOOR, TEMPLATES
from .schemas import CyclesApply, FitSpec, ImportRequest

PHASE = "cycle_registry"
LOCK_ID = str(uuid5(NAMESPACE_URL, "seldon/cycles/lock"))
KINDS = ("factors", "observations", "composites", "fits", "topics", "relevance")
SEMANTICS = {
    "fits": "Model-derived structural priors from historical curve fits. They are not observations or evidence that a cycle will continue; structural breaks end cycles.",
    "verdicts": "supported/weak/under-identified/not-oscillatory summarize red-noise significance, observed cycle count and holdout skill. Only 'supported' fits should inform a forecast beyond a stated hypothesis.",
    "phase": "Phase of the cyclical component relative to trend: peak, declining, trough, rising (factor-specific labels may rename them).",
    "use": "Cite fit IDs, verdicts and diagnostics; record forecast use as an explicit assumption and keep residual uncertainty open.",
    "selection": "Factors appear when explicitly linked to a scoped entity, or when a matched topic scores them at or above the relevance floor. Relevance scores are judged bearing on the topic, not correlations or probabilities.",
}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def stable(kind: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"seldon/cycles/{kind}/{key}"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------------- state


def _index(state: dict) -> dict:
    state["_series"] = {}  # memoized series_points for this snapshot; reset on every mutation
    by_factor: dict[str, list[dict]] = {}
    for row in state["observations"].values():
        by_factor.setdefault(row["factor_id"], []).append(row)
    state["by_factor"] = by_factor
    return state


def _revision(state: dict) -> str:
    return digest({kind: sorted(state[kind].items()) for kind in KINDS})


def has_events(db: Session) -> bool:
    return db.scalar(select(AgentRun.id).where(AgentRun.phase == PHASE).limit(1)) is not None


def load_state(db: Session, *, revision: bool = True) -> dict:
    state = {kind: {} for kind in KINDS}
    versions: dict[str, int] = {}
    history = []
    runs = list(db.scalars(select(AgentRun).where(AgentRun.phase == PHASE)))
    runs.sort(key=lambda r: (r.output or {}).get("sequence", 0))
    for run in runs:
        event = run.output or {}
        for kind in KINDS:
            for record in event.get("changes", {}).get(kind, []):
                if kind == "observations":
                    versions[record["id"]] = versions.get(record["id"], 0) + 1
                state[kind][record["id"]] = record
        history.append({
            "id": run.id,
            "sequence": event.get("sequence"),
            "agent": run.agent_id,
            "reason": (run.input or {}).get("reason"),
            "recorded_at": event.get("recorded_at"),
            "counts": {k: len(v) for k, v in event.get("changes", {}).items()},
        })
    state["versions"] = versions
    state["history"] = history
    state["revision"] = _revision(state) if revision else None
    return _index(state)


def _lock(db: Session) -> None:
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if connection.dialect.name == "postgresql" else sqlite_insert
    db.execute(insert(Source).values(id=LOCK_ID, source_type="cycle_registry", name="Cycle registry revision lock", metadata_={}).on_conflict_do_nothing(index_elements=["id"]))
    db.execute(update(Source).where(Source.id == LOCK_ID).values(updated_at=Source.updated_at))


def _record(db: Session, state: dict, *, run_id: str, agent: str, reason: str, request: dict, changes: dict) -> tuple[str, int]:
    sequence = len(state["history"]) + 1
    now = _now()
    for fit in changes.get("fits", []):
        fit.update(sequence=sequence, recorded_at=now, agent=agent)
    for kind in KINDS:
        for row in changes.get(kind, []):
            state[kind][row["id"]] = row
    _index(state)
    revision = _revision(state)
    urls = sorted({o["source_url"] for o in changes.get("observations", []) if o.get("source_url")})
    db.add(AgentRun(
        id=run_id,
        agent_id=agent,
        phase=PHASE,
        status="completed",
        input={**request, "reason": reason},
        output={"sequence": sequence, "recorded_at": now, "changes": {k: v for k, v in changes.items() if v}, "revision": revision},
        source_references=urls[:200],
    ))
    db.flush()
    state["history"].append({"id": run_id, "sequence": sequence, "agent": agent, "reason": reason, "recorded_at": now})
    state["revision"] = revision
    return revision, sequence


# ----------------------------------------------------------------------------- series


def spec_of(factor: dict) -> dict:
    return FitSpec.model_validate(factor.get("fit") or {}).model_dump(mode="json")


def series_points(state: dict, factor_id: str, _stack: tuple = ()) -> tuple[list, str, dict]:
    """(decimal year, value, standard error) points, data revision and coverage info."""
    cache = state.setdefault("_series", {})
    if factor_id in cache:
        return cache[factor_id]
    cache[factor_id] = result = _series_points(state, factor_id, _stack)
    return result


def _series_points(state: dict, factor_id: str, _stack: tuple) -> tuple[list, str, dict]:
    factor = state["factors"].get(factor_id)
    if factor is None:
        raise KeyError(f"Cycle factor not found: {factor_id}")
    if factor["measurement"] == "derived":
        if factor_id in _stack:
            raise ValueError(f"Derived factors form a cycle through {factor_id}")
        parts = []
        for component in factor["derived_from"]:
            points, revision, _ = series_points(state, component["factor_id"], (*_stack, factor_id))
            parts.append((component, points, revision))
        step = factor.get("fit", {}).get("step_years") or 1.0
        points = _derive(parts, step)
        info = {"n": len(points), "kinds": {"derived": len(points)}, "components": [c["factor_id"] for c in factor["derived_from"]]}
        return points, digest([factor["derived_from"], step, [p[2] for p in parts]]), info
    rows = sorted((o for o in state["by_factor"].get(factor_id, []) if o["status"] == "active"), key=lambda o: (o["date"], o["id"]))
    points = [(fitting.decimal_year(date.fromisoformat(o["date"])), float(o["value"]), o.get("uncertainty")) for o in rows]
    kinds: dict[str, int] = {}
    for row in rows:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    revision = digest([[o["id"], o["date"], o["value"], o.get("uncertainty")] for o in rows])
    return points, revision, {"n": len(rows), "kinds": kinds}


def _derive(parts: list, step: float) -> list:
    """Latent factor: weighted mean of standardized, lagged component series."""
    usable = [(c, p) for c, p, _ in parts if len(p) >= 2]
    if not usable:
        return []
    start = min(min(t for t, _, _ in p) + c["lag_years"] for c, p in usable)
    end = max(max(t for t, _, _ in p) + c["lag_years"] for c, p in usable)
    grid = np.arange(start, end + step / 2, step)
    total = sum(abs(c["weight"]) for c, _, _ in parts)
    acc, cover = np.zeros(len(grid)), np.zeros(len(grid))
    for component, points in usable:
        t = np.array([x[0] for x in points]) + component["lag_years"]
        y = np.array([x[1] for x in points])
        z = (y - y.mean()) / (y.std() or 1.0)
        inside = (grid >= t.min()) & (grid <= t.max())
        acc[inside] += component["weight"] * np.interp(grid[inside], t, z)
        cover[inside] += abs(component["weight"])
    keep = cover >= 0.5 * total
    return [(float(t), float(v / c), None) for t, v, c in zip(grid[keep], acc[keep], cover[keep])]


def series_arrays(state: dict, factor_id: str, spec: dict | None = None) -> tuple[fitting.Series, str, dict]:
    points, revision, info = series_points(state, factor_id)
    spec = spec or spec_of(state["factors"][factor_id])
    since = fitting.decimal_year(date.fromisoformat(spec["since"])) if spec.get("since") else None
    until = fitting.decimal_year(date.fromisoformat(spec["until"])) if spec.get("until") else None
    return fitting.make_series(points, since, until), revision, info


# ----------------------------------------------------------------------------- fits


def fit_id_for(factor_id: str, data_revision: str, spec: dict) -> str:
    return stable("fit", f"{factor_id}/{data_revision}/{digest(spec)}/{fitting.ALGORITHM_VERSION}")


def compute_fit(state: dict, factor_id: str, spec: dict) -> tuple[dict, bool]:
    """Return (fit, existing). Raises fitting.InsufficientData when the model is unidentifiable."""
    series, revision, info = series_arrays(state, factor_id, spec)
    fid = fit_id_for(factor_id, revision, spec)
    if fid in state["fits"]:
        return state["fits"][fid], True
    if len(series.t) < 2:
        raise fitting.InsufficientData(f"{factor_id}: needs observations at two or more dates; has {len(series.t)}")
    seed = int(digest([revision, digest(spec)])[:8], 16)
    model = fitting.fit_harmonic if spec["model"] == "harmonic" else fitting.fit_oscillator
    try:
        result = model(series, spec, seed)
    except fitting.InsufficientData as exc:
        raise fitting.InsufficientData(f"{factor_id}: {exc}") from exc
    fit = {
        "id": fid,
        "factor_id": factor_id,
        "model": spec["model"],
        "spec": spec,
        "spec_digest": digest(spec),
        "data_revision": revision,
        "algorithm_version": fitting.ALGORITHM_VERSION,
        "data": {
            "n": int(len(series.t)),
            "start": fitting.to_date(series.t[0]),
            "end": fitting.to_date(series.t[-1]),
            "span_years": fitting._r(series.t[-1] - series.t[0], 4),
            "median_spacing_years": fitting._r(fitting._spacing(series.t), 4),
            "kinds": info.get("kinds", {}),
            "weighted": series.sigma is not None,
        },
        **result,
    }
    return fit, False


def preferred_fit(state: dict, factor_id: str, data_revision: str | None = None) -> tuple[dict | None, str]:
    spec = spec_of(state["factors"][factor_id])
    key = digest(spec)
    fits = [f for f in state["fits"].values() if f["factor_id"] == factor_id and f["spec_digest"] == key]
    if not fits:
        return None, "missing"
    if data_revision is None:
        data_revision = series_points(state, factor_id)[1]
    fresh = [f for f in fits if f["data_revision"] == data_revision]
    if fresh:
        return max(fresh, key=lambda f: f["sequence"]), "fresh"
    return max(fits, key=lambda f: f["sequence"]), "stale"


def _dependents(state: dict, changed: set[str]) -> set[str]:
    graph = nx.DiGraph()
    for factor in state["factors"].values():
        for component in factor.get("derived_from", []):
            graph.add_edge(component["factor_id"], factor["id"])
    out = set(changed)
    for factor_id in changed:
        if factor_id in graph:
            out |= nx.descendants(graph, factor_id)
    return out


def _refit(state: dict, factor_ids: set[str]) -> tuple[list[dict], list[str]]:
    fits, warnings = [], []
    for factor_id in sorted(factor_ids):
        factor = state["factors"][factor_id]
        if factor["status"] != "active":
            continue
        try:
            fit, existing = compute_fit(state, factor_id, spec_of(factor))
        except fitting.InsufficientData as exc:
            warnings.append(f"Not fitted yet: {exc}")
            continue
        if not existing:
            fits.append(fit)
    return fits, warnings


def record_fit(db: Session, factor_id: str, spec: FitSpec | None, *, agent: str, reason: str, full: bool = False) -> dict:
    _lock(db)
    with db.begin_nested():
        state = load_state(db)
        if factor_id not in state["factors"]:
            raise KeyError(f"Cycle factor not found: {factor_id}")
        spec_dict = (spec or FitSpec.model_validate(state["factors"][factor_id]["fit"])).model_dump(mode="json")
        factor = state["factors"][factor_id]
        fit, existing = compute_fit(state, factor_id, spec_dict)
        revision = state["revision"]
        if not existing:
            revision, _ = _record(db, state, run_id=stable("request", f"fit/{fit['id']}"), agent=agent, reason=reason, request={"operation": "fit", "factor_id": factor_id, "spec": spec_dict}, changes={"fits": [fit]})
        return {
            "fit": fit if full else fit_summary(fit, factor),
            "replayed": existing,
            "revision": revision,
            "preferred": fit["spec_digest"] == digest(spec_of(factor)),
            "note": None if fit["spec_digest"] == digest(spec_of(factor)) else "Exploratory specification: recorded for comparison but does not drive forecast context. Update the factor's fit spec to promote it.",
        }


def refit_stale(db: Session, *, agent: str, reason: str) -> dict:
    _lock(db)
    with db.begin_nested():
        state = load_state(db)
        fits, warnings = _refit(state, set(state["factors"]))
        if not fits:
            return {"revision": state["revision"], "fitted": [], "warnings": warnings, "unchanged": True}
        revision, _ = _record(db, state, run_id=stable("request", "refit/" + digest(sorted(f["id"] for f in fits))), agent=agent, reason=reason, request={"operation": "refit"}, changes={"fits": fits})
        return {"revision": revision, "fitted": [fit_summary(f, state["factors"][f["factor_id"]]) for f in fits], "warnings": warnings}


# ----------------------------------------------------------------------------- apply


def _with_template(factor) -> dict:
    row = factor.model_dump(mode="json")
    if not factor.template:
        return row
    template = TEMPLATES.get(factor.template)
    if template is None:
        raise ValueError(f"Unknown template {factor.template}; choose one of {', '.join(sorted(TEMPLATES))}")
    given = factor.model_fields_set
    for key in ("domain", "low_label", "high_label"):
        if key not in given and template.get(key):
            row[key] = template[key]
    if "phase_labels" not in given and template.get("phase_labels"):
        row["phase_labels"] = template["phase_labels"]
    fit = dict(row["fit"])
    if "fit" not in given:
        fit.update(template.get("fit", {}))
    if template.get("period_years") and not (fit.get("period_years") or fit.get("period_min_years") or fit.get("period_max_years")):
        fit["period_min_years"], fit["period_max_years"] = template["period_years"]
    row["fit"] = FitSpec.model_validate(fit).model_dump(mode="json")
    return row


def _observation_key(row: dict) -> str:
    return f"{row['factor_id'][:96]}:{row['date']}:{digest(row['source_name'].casefold().strip())[:8]}"


def apply_cycles(db: Session, payload: CyclesApply) -> dict:
    from ..service import WorkspaceConflict

    _lock(db)
    with db.begin_nested():
        run_id = stable("request", payload.request_id)
        fingerprint = digest(payload.model_dump(mode="json"))
        old = db.get(AgentRun, run_id)
        if old:
            if old.input.get("request_hash") != fingerprint:
                raise WorkspaceConflict("Cycle request_id already used for different input")
            return {"revision": old.output["revision"], "run_id": run_id, "replayed": True}
        state = load_state(db)
        if state["revision"] != payload.base_revision:
            raise WorkspaceConflict("Cycle registry changed; export it again and reconcile")
        work = _index({**{k: dict(state[k]) for k in KINDS}, "versions": state["versions"], "history": state["history"]})
        changes = {kind: [] for kind in KINDS}
        touched: set[str] = set()

        seen: set[str] = set()
        for factor in payload.factors:
            if factor.id in seen:
                raise ValueError(f"Duplicate factor ID: {factor.id}")
            seen.add(factor.id)
            row = _with_template(factor)
            if work["factors"].get(factor.id) != row:
                work["factors"][factor.id] = row
                changes["factors"].append(row)
                touched.add(factor.id)
        for row in changes["factors"]:
            for entity_id in row["entity_ids"]:
                if db.get(ERGNode, entity_id) is None:
                    raise ValueError(f"Unknown research entity: {entity_id}")
            for component in row["derived_from"]:
                if component["factor_id"] not in work["factors"]:
                    raise ValueError(f"Unknown component factor: {component['factor_id']}")
        derived = nx.DiGraph()
        derived.add_edges_from((c["factor_id"], f["id"]) for f in work["factors"].values() for c in f.get("derived_from", []))
        if not nx.is_directed_acyclic_graph(derived):
            raise ValueError("Derived factors must form a DAG; a latent factor cannot depend on itself")

        seen = set()
        for observation in payload.observations:
            row = observation.model_dump(mode="json")
            row["id"] = row["id"] or _observation_key(row)
            if row["id"] in seen:
                raise ValueError(f"Duplicate observation ID in request: {row['id']}")
            seen.add(row["id"])
            factor = work["factors"].get(row["factor_id"])
            if factor is None:
                raise ValueError(f"Unknown cycle factor: {row['factor_id']}")
            if factor["measurement"] == "derived":
                raise ValueError(f"Derived factor {row['factor_id']} is computed from components; add observations to them")
            previous = work["observations"].get(row["id"])
            if previous and previous["factor_id"] != row["factor_id"]:
                raise ValueError(f"Observation {row['id']} belongs to factor {previous['factor_id']}")
            for evidence_id in row["evidence_ids"]:
                if db.get(KBEntry, evidence_id) is None:
                    raise ValueError(f"Unknown research evidence: {evidence_id}")
            if previous != row:
                work["observations"][row["id"]] = row
                changes["observations"].append(row)
                touched.add(row["factor_id"])
        _index(work)

        seen = set()
        for composite in payload.composites:
            if composite.id in seen:
                raise ValueError(f"Duplicate composite ID: {composite.id}")
            seen.add(composite.id)
            row = composite.model_dump(mode="json")
            for component in row["components"]:
                if component["factor_id"] not in work["factors"]:
                    raise ValueError(f"Unknown component factor: {component['factor_id']}")
            for entity_id in row["entity_ids"]:
                if db.get(ERGNode, entity_id) is None:
                    raise ValueError(f"Unknown research entity: {entity_id}")
            if work["composites"].get(composite.id) != row:
                work["composites"][composite.id] = row
                changes["composites"].append(row)

        seen = set()
        for topic in payload.topics:
            if topic.id in seen:
                raise ValueError(f"Duplicate topic ID: {topic.id}")
            seen.add(topic.id)
            row = topic.model_dump(mode="json")
            row["tags"] = sorted({normalize_tag(t) for t in row["tags"]} - {""})
            for entity_id in row["entity_ids"]:
                if db.get(ERGNode, entity_id) is None:
                    raise ValueError(f"Unknown research entity: {entity_id}")
            if work["topics"].get(topic.id) != row:
                work["topics"][topic.id] = row
                changes["topics"].append(row)

        seen = set()
        for relevance in payload.relevance:
            row = relevance.model_dump(mode="json")
            row["id"] = row["id"] or f"{row['topic_id']}:{row['factor_id'] or row['composite_id']}"
            if row["id"] in seen:
                raise ValueError(f"Duplicate relevance ID in request: {row['id']}")
            seen.add(row["id"])
            if row["topic_id"] not in work["topics"]:
                raise ValueError(f"Unknown cycle topic: {row['topic_id']}")
            if row["factor_id"] and row["factor_id"] not in work["factors"]:
                raise ValueError(f"Unknown cycle factor: {row['factor_id']}")
            if row["composite_id"] and row["composite_id"] not in work["composites"]:
                raise ValueError(f"Unknown cycle composite: {row['composite_id']}")
            previous = work["relevance"].get(row["id"])
            if previous and (previous["topic_id"], previous["factor_id"], previous["composite_id"]) != (row["topic_id"], row["factor_id"], row["composite_id"]):
                raise ValueError(f"Relevance {row['id']} already scores a different topic/cycle pair")
            if previous != row:
                work["relevance"][row["id"]] = row
                changes["relevance"].append(row)

        warnings: list[str] = []
        if payload.refit and touched:
            changes["fits"], warnings = _refit(work, _dependents(work, touched))
        if not any(changes.values()):
            return {"revision": state["revision"], "replayed": False, "unchanged": True, "warnings": warnings}
        request = {"request_id": payload.request_id, "request_hash": fingerprint}
        revision, sequence = _record(db, work, run_id=run_id, agent=payload.agent, reason=payload.reason, request=request, changes=changes)
        return {
            "revision": revision,
            "run_id": run_id,
            "sequence": sequence,
            "replayed": False,
            "counts": {k: len(v) for k, v in changes.items()},
            "fits": [fit_summary(f, work["factors"][f["factor_id"]]) for f in changes["fits"]],
            "warnings": warnings,
        }


# ----------------------------------------------------------------------------- CSV import

_MISSING = {"", ".", "na", "n/a", "nan", "null", "none", "#n/a"}


def _parse_date(text: str, anchor: str) -> date:
    text = text.strip()
    if re.fullmatch(r"-?\d{1,4}", text):
        year = int(text)
        return date(year, 1, 1) if anchor == "start" else date(year, 12, 31) if anchor == "end" else date(year, 7, 2)
    if re.fullmatch(r"\d{4}-\d{2}", text):
        year, month = map(int, text.split("-"))
        day = {"start": 1, "mid": 15, "end": monthrange(year, month)[1]}[anchor]
        return date(year, month, day)
    return date.fromisoformat(text[:10])


def parse_csv(text: str, request: ImportRequest) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    columns = reader.fieldnames or []
    if len(columns) < 2:
        raise ValueError("CSV needs a header row with date and value columns")
    lowered = {c.casefold(): c for c in columns}
    date_col = request.date_column or next((lowered[k] for k in ("date", "observation_date", "year", "time", "period") if k in lowered), columns[0])
    value_col = request.value_column or ([c for c in columns if c != date_col][0] if len(columns) == 2 else None)
    if not value_col:
        raise ValueError(f"Choose value_column from: {', '.join(columns)}")
    for column in (date_col, value_col, request.uncertainty_column):
        if column and column not in columns:
            raise ValueError(f"Unknown CSV column {column}; available: {', '.join(columns)}")
    rows = []
    for line, record in enumerate(reader, start=2):
        raw = (record.get(value_col) or "").strip()
        if raw.casefold() in _MISSING:
            continue
        try:
            when = _parse_date(record[date_col], request.year_anchor)
            value = float(raw.replace(",", ""))
            error = record.get(request.uncertainty_column) if request.uncertainty_column else None
            uncertainty = float(error) if error and error.strip().casefold() not in _MISSING else None
        except (ValueError, TypeError) as exc:
            raise ValueError(f"CSV line {line}: {exc}") from exc
        rows.append({"date": when.isoformat(), "value": value, "uncertainty": uncertainty})
    if not rows:
        raise ValueError("CSV contained no numeric observations")
    return rows


def import_csv(db: Session, factor_id: str, request: ImportRequest) -> dict:
    _lock(db)
    state = load_state(db)
    if factor_id not in state["factors"]:
        raise KeyError(f"Cycle factor not found: {factor_id}")
    retrieved = (request.retrieved_at or datetime.now(timezone.utc)).isoformat()
    observations = [
        {**row, "factor_id": factor_id, "kind": request.kind, "source_name": request.source_name, "source_url": request.source_url, "retrieved_at": retrieved, "note": request.note}
        for row in parse_csv(request.csv, request)
    ]
    request_id = request.request_id or f"import-{factor_id[:40]}-{digest([request.csv, request.source_name, request.source_url, request.kind, request.year_anchor])[:40]}"
    payload = CyclesApply.model_validate({
        "request_id": request_id,
        "base_revision": state["revision"],
        "agent": request.agent,
        "reason": request.reason,
        "observations": observations,
        "refit": request.refit,
    })
    old = db.get(AgentRun, stable("request", request_id))
    if old and request.request_id is None and old.input.get("request_hash") != digest(payload.model_dump(mode="json")):
        # The default ID encodes the CSV content; only retrieved_at/base revision differ on re-import.
        # A caller-chosen ID reused for different content still conflicts in apply_cycles.
        return {"revision": state["revision"], "run_id": old.id, "replayed": True, "imported": len(observations)}
    return {**apply_cycles(db, payload), "imported": len(observations)}


# ----------------------------------------------------------------------------- views


def _label(factor: dict, quadrant: str) -> str:
    labels = factor.get("phase_labels") or {}
    return labels.get(quadrant) or quadrant


def fit_summary(fit: dict, factor: dict) -> dict:
    diagnostics = fit.get("diagnostics", {})
    summary = {
        "id": fit["id"],
        "factor_id": fit["factor_id"],
        "model": fit["model"],
        "verdict": fit["verdict"],
        "data_revision": fit["data_revision"],
        "recorded_at": fit.get("recorded_at"),
        "data": fit["data"],
        "warnings": fit.get("warnings", []),
        "backtest": diagnostics.get("backtest"),
        "significance": diagnostics.get("significance"),
        "upcoming_turning_points": [{**p, "label": _label(factor, p["type"])} for p in fit["turning_points"]["upcoming"][:3]],
    }
    if fit["model"] == "harmonic":
        summary["r2"] = diagnostics.get("r2")
        summary["cycles"] = [{k: c[k] for k in ("period_years", "period_se_years", "amplitude", "cycles_observed")} | {"phase_at_end": _label(factor, c["phase_label_at_end"])} for c in fit["components"]]
    else:
        d = fit["dynamics"]
        summary["dynamics"] = {k: d.get(k) for k in ("oscillatory", "period_years", "damping_ratio", "half_life_years", "persistence", "overshoot", "p_oscillatory", "cycles_observed")}
        if d.get("phase_label_at_end"):
            summary["dynamics"]["phase_at_end"] = _label(factor, d["phase_label_at_end"])
    return summary


def factor_view(state: dict, factor: dict, *, observations: bool = False, full_fits: bool = False) -> dict:
    try:
        points, revision, info = series_points(state, factor["id"])
    except ValueError as exc:
        points, revision, info = [], None, {"error": str(exc)}
    rows = state["by_factor"].get(factor["id"], [])
    series = {
        **info,
        "data_revision": revision,
        "start": fitting.to_date(points[0][0]) if points else None,
        "end": fitting.to_date(points[-1][0]) if points else None,
        "last_value": points[-1][1] if points else None,
        "withdrawn": sum(1 for o in rows if o["status"] == "withdrawn"),
        "revised": sum(1 for o in rows if state["versions"].get(o["id"], 1) > 1),
    }
    fit, status = preferred_fit(state, factor["id"], revision) if revision else (None, "missing")
    others = sorted((f for f in state["fits"].values() if f["factor_id"] == factor["id"]), key=lambda f: f["sequence"])
    view = {
        **factor,
        "series": series,
        "fit_status": status,
        "current_fit": (fit if full_fits else fit_summary(fit, factor)) if fit else None,
        "fits": [{"id": f["id"], "model": f["model"], "verdict": f["verdict"], "spec_digest": f["spec_digest"], "data_revision": f["data_revision"], "recorded_at": f.get("recorded_at"), "preferred": fit is not None and f["spec_digest"] == fit["spec_digest"]} for f in others],
    }
    if observations:
        view["observations"] = sorted(rows, key=lambda o: (o["date"], o["id"]))
    return view


def export_view(state: dict, *, factor_id: str | None = None, observations: bool = False) -> dict:
    if factor_id and factor_id not in state["factors"]:
        raise KeyError(f"Cycle factor not found: {factor_id}")
    factors = [
        factor_view(state, f, observations=observations or bool(factor_id), full_fits=bool(factor_id))
        for f in sorted(state["factors"].values(), key=lambda f: f["id"])
        if not factor_id or f["id"] == factor_id
    ]
    return {
        "revision": state["revision"],
        "factors": factors,
        "composites": sorted(state["composites"].values(), key=lambda c: c["id"]),
        "topics": sorted(state["topics"].values(), key=lambda t: t["id"]),
        "relevance": sorted(state["relevance"].values(), key=lambda r: (r["topic_id"], -r["score"])),
        "totals": {"factors": len(state["factors"]), "observations": len(state["observations"]), "fits": len(state["fits"]), "composites": len(state["composites"]), "topics": len(state["topics"]), "relevance": len(state["relevance"])},
        "history": state["history"][-50:],
        "semantics": SEMANTICS,
    }


def render_markdown(view: dict) -> str:
    lines = ["# Cycle factors", "", f"Revision: {view['revision']}", "", SEMANTICS["fits"], "", "| Factor | Region | Data | Model | Verdict | Period (years) | Phase at last data | Next turning point |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for factor in view["factors"]:
        fit = factor.get("current_fit") or {}
        if fit and "turning_points" in fit:
            fit = fit_summary(fit, factor)
        cycles = fit.get("cycles") or ([fit["dynamics"]] if fit.get("dynamics") else [])
        period = ", ".join(f"{c['period_years']:.3g}" for c in cycles if c.get("period_years")) or "—"
        phase = ", ".join(str(c.get("phase_at_end")) for c in cycles if c.get("phase_at_end")) or "—"
        upcoming = fit.get("upcoming_turning_points") or []
        nxt = f"{upcoming[0]['label']} {upcoming[0]['date']}" if upcoming else "—"
        series = factor["series"]
        data = f"{series.get('n', 0)} pts {series.get('start') or ''}–{series.get('end') or ''}"
        lines.append(f"| {factor['name']} | {factor['region']} | {data} | {fit.get('model', '—')} | {fit.get('verdict', factor['fit_status'])} | {period} | {phase} | {nxt} |")
    if view.get("relevance"):
        topics = {t["id"]: t["name"] for t in view.get("topics", [])}
        names = {f["id"]: f["name"] for f in view["factors"]} | {c["id"]: c["name"] for c in view["composites"]}
        lines += ["", "## Topic relevance", "", f"Cycles scoring at least {RELEVANCE_FLOOR} enter the context of questions matched to the topic.", "", "| Topic | Cycle | Score | Direction when high | Horizon | Channel |", "| --- | --- | ---: | --- | --- | --- |"]
        for row in view["relevance"]:
            cycle = row["factor_id"] or row["composite_id"]
            channel = row["channel"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {topics.get(row['topic_id'], row['topic_id'])} | {names.get(cycle, cycle)} | {row['score']:.2f} | {row['direction']} | {row['horizon']} | {channel} |")
    lines += ["", "```json", json.dumps(view, indent=2, ensure_ascii=False), "```", ""]
    return "\n".join(lines)


# ----------------------------------------------------------------------------- outlook and forecast context


def _interp(t: float, xs: list, ys: list) -> float | None:
    if not xs or t < xs[0] or t > xs[-1] or any(y is None for y in ys):
        return None
    return float(np.interp(t, xs, ys))


def phases_at(fit: dict, t: float) -> list[float]:
    if fit["model"] == "harmonic":
        return [(fitting.TAU * t / c["period_years"] - c["phase_offset"]) % fitting.TAU for c in fit["params"]["components"]]
    phase = fitting.oscillator_phase(fit["params"], t) if t >= fit["params"]["t_end"] else None
    return [phase] if phase is not None else []


def outlook_factor(state: dict, factor_id: str, at: date | None) -> dict:
    factor = state["factors"][factor_id]
    _, revision, _ = series_points(state, factor_id)
    fit, status = preferred_fit(state, factor_id, revision)
    entry = {
        "factor_id": factor_id,
        "name": factor["name"],
        "domain": factor["domain"],
        "region": factor["region"],
        "units": factor["units"],
        "low_label": factor["low_label"],
        "high_label": factor["high_label"],
        "measurement": factor["measurement"],
        "entity_ids": factor["entity_ids"],
        "data_revision": revision,
        "fit_status": status,
    }
    if fit is None:
        entry["note"] = "No preferred fit; add data and run research cycles fit or refit."
        return entry
    entry["fit"] = fit_summary(fit, factor)
    if at is None:
        return entry
    t = fitting.decimal_year(at)
    projection = fit["projection"]
    position: dict = {"date": at.isoformat()}
    if t <= projection["t"][0]:
        position["relation"] = "within observed history"
        if fit["model"] == "harmonic":
            position["fitted"] = fitting._r(float(fitting.harmonic_value(fit["params"], np.array([t]))[0]))
    elif t <= projection["t"][-1]:
        mean = _interp(t, projection["t"], projection["mean"])
        position.update(relation="projected", mean=fitting._r(mean), lower=fitting._r(_interp(t, projection["t"], projection["lower"])), upper=fitting._r(_interp(t, projection["t"], projection["upper"])), interval=projection["interval"])
        later = _interp(min(t + 0.25, projection["t"][-1]), projection["t"], projection["mean"])
        earlier = _interp(max(t - 0.25, projection["t"][0]), projection["t"], projection["mean"])
        if later is not None and earlier is not None:
            position["direction"] = "rising" if later > earlier else "falling"
    else:
        position["relation"] = "beyond projection horizon; refit with a longer horizon_years before relying on it"
    phases = phases_at(fit, t)
    if phases:
        position["phases"] = [{"angle": fitting._r(p, 4), "quadrant": fitting.phase_label(p), "label": _label(factor, fitting.phase_label(p))} for p in phases]
    position["next_turning_points"] = [{**p, "label": _label(factor, p["type"])} for p in fit["turning_points"]["upcoming"] if p["t"] >= t][:2]
    entry["at"] = position
    cycles = entry["fit"].get("cycles") or [entry["fit"].get("dynamics") or {}]
    period = ", ".join(f"{c['period_years']:.3g}" for c in cycles if c.get("period_years")) or "none identified"
    phase_text = ", ".join(p["label"] for p in position.get("phases", [])) or "not defined"
    projected = f"projected {position['mean']:.4g} [{position['lower']:.4g}, {position['upper']:.4g}] {factor['units']} (80% band assuming the cycle persists)" if position.get("mean") is not None and position.get("lower") is not None else position["relation"]
    significance = fit["diagnostics"].get("significance") or {}
    backtest = fit["diagnostics"].get("backtest") or {}
    entry["evidence_template"] = {
        "id": f"cycle-{factor_id[:60]}-{fit['id'][:8]}",
        "kind": "assumption",
        "source_name": f"Seldon cycle fit {fit['id']}",
        "retrieved_at": fit.get("recorded_at"),
        "confidence": None,
        "complete_before_use": ["confidence: your judgment given the verdict and diagnostics"],
        "content": (
            f"Model-derived cycle prior, not an observation: {factor['name']} ({factor['region']}), {fit['model']} fit {fit['id']} on {fit['data']['n']} points "
            f"{fit['data']['start']} to {fit['data']['end']}; verdict {fit['verdict']}; period {period} years. At {at.isoformat()}: phase {phase_text}; {projected}. "
            f"Red-noise p={significance.get('p_value', significance.get('p_oscillatory'))}; holdout skill vs trend={backtest.get('skill_vs_trend')}."
        ),
    }
    return entry


def parse_horizon(text: str | None) -> date | None:
    found = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", text or "")
    dates = []
    for value in found:
        try:
            dates.append(date.fromisoformat(value))
        except ValueError:
            continue
    return max(dates) if dates else None


def outlook(state: dict, *, factor_ids=(), composite_ids=(), at: date | None = None, relevance: dict | None = None) -> dict:
    from .combine import composite_outlook

    relevance = relevance or {}

    for factor_id in factor_ids:
        if factor_id not in state["factors"]:
            raise KeyError(f"Cycle factor not found: {factor_id}")
    for composite_id in composite_ids:
        if composite_id not in state["composites"]:
            raise KeyError(f"Cycle composite not found: {composite_id}")
    return {
        "at": at.isoformat() if at else None,
        "factors": [{**outlook_factor(state, f, at), **({"relevance": relevance[("factor", f)]} if ("factor", f) in relevance else {})} for f in factor_ids],
        "composites": [{**composite_outlook(state, state["composites"][c], at), **({"relevance": relevance[("composite", c)]} if ("composite", c) in relevance else {})} for c in composite_ids],
        "semantics": SEMANTICS,
        "guidance": CYCLE_GUIDANCE,
    }


def matched_topics(state: dict, nodes) -> list[dict]:
    """Topics whose explicit entities or tags appear among the given research entities."""
    ids = {n.id for n in nodes}
    tags = {normalize_tag(t) for n in nodes for t in (n.tags or [])}
    out = []
    for topic in sorted(state["topics"].values(), key=lambda t: t["id"]):
        if topic["status"] != "active":
            continue
        entities = sorted(set(topic["entity_ids"]) & ids)
        tag_hits = sorted(set(topic["tags"]) & tags)
        if entities or tag_hits:
            out.append({"topic_id": topic["id"], "name": topic["name"], "matched_entity_ids": entities, "matched_tags": tag_hits})
    return out


def relevant(state: dict, nodes, *, floor: float = RELEVANCE_FLOOR, target_id: str | None = None) -> tuple[list[str], list[str], dict, list[dict]]:
    """Cycles a set of research entities inherits: explicit entity links plus topic relevance at or above the floor.

    `score` is the highest relevance across matched topics; `target_score` uses only topics that
    contain the forecast target, which best reflects bearing on the question's outcome. Returns
    ordered factor IDs, composite IDs, per-cycle relevance details and the matched topics.
    """
    ids = {n.id for n in nodes}
    topics = matched_topics(state, nodes)
    target = next((n for n in nodes if n.id == target_id), None)
    for topic in topics:
        topic["contains_target"] = bool(target and matched_topics({"topics": {topic["topic_id"]: state["topics"][topic["topic_id"]]}}, [target]))
    matched = {t["topic_id"] for t in topics}
    on_target = {t["topic_id"] for t in topics if t["contains_target"]}
    details: dict = {}

    def entry(kind: str, key: str) -> dict:
        return details.setdefault((kind, key), {"linked": False, "score": None, "target_score": None, "topics": []})

    for factor in state["factors"].values():
        if factor["status"] == "active" and set(factor["entity_ids"]) & ids:
            entry("factor", factor["id"])["linked"] = True
    for composite in state["composites"].values():
        if composite["status"] == "active" and set(composite["entity_ids"]) & ids:
            entry("composite", composite["id"])["linked"] = True
    for row in state["relevance"].values():
        kind, key = ("factor", row["factor_id"]) if row["factor_id"] else ("composite", row["composite_id"])
        target = state["factors" if kind == "factor" else "composites"].get(key)
        if row["topic_id"] not in matched or row["score"] < floor or not target or target["status"] != "active":
            continue
        item = entry(kind, key)
        item["topics"].append({k: row[k] for k in ("topic_id", "score", "direction", "channel", "horizon", "rationale")} | {"contains_target": row["topic_id"] in on_target})
        item["score"] = max(item["score"] or 0.0, row["score"])
        if row["topic_id"] in on_target:
            item["target_score"] = max(item["target_score"] or 0.0, row["score"])
    for item in details.values():
        item["topics"].sort(key=lambda r: (not r["contains_target"], -r["score"], r["topic_id"]))

    def order(kind):
        keys = [k for (c, k) in details if c == kind]
        return sorted(keys, key=lambda k: (-(details[(kind, k)]["target_score"] or 0), -(details[(kind, k)]["score"] or 0), not details[(kind, k)]["linked"], k))

    factors = order("factor")
    composites = order("composite")
    chosen = set(factors)
    for composite in sorted(state["composites"].values(), key=lambda c: c["id"]):
        if composite["status"] == "active" and composite["id"] not in composites and {x["factor_id"] for x in composite["components"]} & chosen:
            composites.append(composite["id"])
            details[("composite", composite["id"])] = {"linked": False, "score": None, "target_score": None, "topics": [], "via_components": True}
    return factors, composites, details, topics


def research_context(db: Session, nodes, horizon: str | None = None, target_id: str | None = None) -> dict:
    """Cycle priors for the scoped research entities: explicit links and topic relevance above the floor."""
    if not nodes or not has_events(db):
        return {}
    state = load_state(db, revision=False)
    factor_ids, composite_ids, details, topics = relevant(state, nodes, target_id=target_id)
    if not factor_ids and not composite_ids:
        return {}
    context = outlook(state, factor_ids=factor_ids, composite_ids=composite_ids, at=parse_horizon(horizon), relevance=details)
    context["topics"] = topics
    context["relevance_floor"] = RELEVANCE_FLOOR
    return context


def relevance_view(state: dict, *, topic_id: str | None = None, factor_id: str | None = None, nodes=None, floor: float = RELEVANCE_FLOOR, target_id: str | None = None) -> dict:
    """The stored topic-to-cycle lookup, optionally filtered or resolved for a question's entities."""
    if topic_id and topic_id not in state["topics"]:
        raise KeyError(f"Cycle topic not found: {topic_id}")
    if factor_id and factor_id not in state["factors"] and factor_id not in state["composites"]:
        raise KeyError(f"Cycle factor or composite not found: {factor_id}")
    rows = [
        r for r in state["relevance"].values()
        if (not topic_id or r["topic_id"] == topic_id) and (not factor_id or factor_id in (r["factor_id"], r["composite_id"]))
    ]
    rows.sort(key=lambda r: (r["topic_id"], -r["score"], r["factor_id"] or r["composite_id"]))
    view = {
        "floor": floor,
        "topics": [t for t in sorted(state["topics"].values(), key=lambda t: t["id"]) if not topic_id or t["id"] == topic_id],
        "relevance": rows,
    }
    if nodes is not None:
        factors, composites, details, topics = relevant(state, nodes, floor=floor, target_id=target_id)
        view["question"] = {
            "matched_topics": topics,
            "factors": [{"factor_id": f, "name": state["factors"][f]["name"], **details[("factor", f)]} for f in factors],
            "composites": [{"composite_id": c, "name": state["composites"][c]["name"], **details[("composite", c)]} for c in composites],
        }
    return view


def discover(state: dict, factor_id: str, fit_id: str | None = None, surrogates: int = 200) -> dict:
    factor = state["factors"].get(factor_id)
    if factor is None:
        raise KeyError(f"Cycle factor not found: {factor_id}")
    fit = state["fits"].get(fit_id) if fit_id else preferred_fit(state, factor_id)[0]
    if fit is None or fit["factor_id"] != factor_id:
        raise KeyError("Fit not found for this factor; fit it first")
    series, _, _ = series_arrays(state, factor_id, fit["spec"])
    params = fit["params"]
    if fit["model"] == "harmonic":
        resid = series.y - fitting.harmonic_value(params, series.t)
        existing = [c["period_years"] for c in fit["components"]]
    else:
        base = fitting._trend((series.t - params["t0"]) / params["scale"], params["trend"])
        resid = series.y - base @ np.array(params["trend_coefficients"])
        existing = [fit["dynamics"]["period_years"]] if fit["dynamics"].get("period_years") else []
    result = fitting.residual_spectrum(series.t, resid, series.weights, existing, int(digest([fit["id"], "discover"])[:8], 16), surrogates)
    return {
        "factor_id": factor_id,
        "fit_id": fit["id"],
        **result,
        "guidance": "A residual peak with p < 0.05, at least two observed cycles and no harmonic relation is a candidate hidden cycle. Hypothesize a driver, find an independent series for it and add a factor, or refit with more cycles/harmonics. A residual peak is not a discovered cause.",
    }
