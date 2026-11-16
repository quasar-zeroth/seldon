"""`seldon research cycles ...`: shell interface for agents. JSON in, JSON/SVG/Markdown out."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .catalog import RELEVANCE_FLOOR
from .schemas import CombineRequest, Component, CyclesApply, FitRequest, FitSpec, ImportRequest

SCHEMAS = {"apply": CyclesApply, "fit": FitSpec, "import": ImportRequest, "combine": CombineRequest, "fit-request": FitRequest}


def _components(values: list[str]) -> list[dict]:
    out = []
    for text in values:
        pieces = text.split(":")
        numbers = []
        while pieces and len(numbers) < 2 and len(pieces) > 1:
            try:
                numbers.insert(0, float(pieces[-1]))
                pieces.pop()
            except ValueError:
                break
        values = {"factor_id": ":".join(pieces)}
        if numbers:
            values["weight"] = numbers[0]
        if len(numbers) > 1:
            values["lag_years"] = numbers[1]
        out.append(Component.model_validate(values).model_dump(mode="json"))
    return out


def _settings(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        key, _, raw = pair.partition("=")
        if not key or not _:
            raise ValueError(f"--set expects key=value, got {pair}")
        try:
            out[key] = json.loads(raw)
        except json.JSONDecodeError:
            out[key] = raw
    return out


def static(args: argparse.Namespace) -> dict:
    if args.cycles_command == "catalog":
        from .catalog import catalog

        return catalog()
    return SCHEMAS[args.part].model_json_schema()


def run(args: argparse.Namespace, db):
    from . import (
        apply_cycles,
        discover,
        export_view,
        import_csv,
        load_state,
        outlook,
        parse_horizon,
        record_fit,
        refit_stale,
        relevance_view,
        relevant,
        render_markdown,
    )

    command = args.cycles_command
    if command == "apply":
        return apply_cycles(db, CyclesApply.model_validate_json(args.file.read_text()))
    if command == "import":
        request = ImportRequest(
            csv=args.file.read_text(encoding="utf-8"),
            source_name=args.source_name,
            source_url=args.source_url,
            kind=args.kind,
            retrieved_at=args.retrieved_at,
            date_column=args.date_column,
            value_column=args.value_column,
            uncertainty_column=args.uncertainty_column,
            year_anchor=args.year_anchor,
            note=args.note,
            request_id=args.request_id,
            agent=args.agent,
            reason=args.reason,
            refit=not args.no_refit,
        )
        return import_csv(db, args.factor_id, request)
    if command == "fit":
        state = load_state(db)
        if args.factor_id not in state["factors"]:
            raise KeyError(f"Cycle factor not found: {args.factor_id}")
        spec = None
        if args.spec:
            spec = FitSpec.model_validate_json(args.spec.read_text())
        elif args.model or args.set:
            values = dict(state["factors"][args.factor_id]["fit"])
            if args.model:
                values["model"] = args.model
            values.update(_settings(args.set or []))
            spec = FitSpec.model_validate(values)
        return record_fit(db, args.factor_id, spec, agent=args.agent, reason=args.reason, full=args.full)
    if command == "refit":
        return refit_stale(db, agent=args.agent, reason=args.reason)
    if command == "history":
        from seldon.data.models import AgentRun

        from . import PHASE

        row = db.get(AgentRun, args.run_id)
        if not row or row.phase != PHASE:
            raise KeyError("Cycle registry change not found")
        return {"id": row.id, "agent": row.agent_id, "input": row.input, "event": row.output}
    state = load_state(db)
    if command == "export":
        view = export_view(state, factor_id=args.factor, observations=args.observations)
        return render_markdown(view) if args.format == "markdown" else view
    if command == "discover":
        return discover(state, args.factor_id, args.fit, args.surrogates)
    if command == "combine":
        from .combine import combine

        components = state["composites"][args.composite]["components"] if args.composite else _components(args.component or [])
        if args.composite and args.composite not in state["composites"]:
            raise KeyError(f"Cycle composite not found: {args.composite}")
        request = CombineRequest(composite_id=args.composite, components=[] if args.composite else components, start=args.start, end=args.end, at=args.at or date.today(), step_years=args.step_years)
        return combine(state, components, start=request.start, end=request.end, at=request.at, step=request.step_years)
    if command == "outlook":
        at = args.at
        factor_ids, composite_ids = list(args.factor or []), list(args.composite or [])
        details, topics = {}, None
        if args.scenario:
            from seldon.data.models import Scenario
            from seldon.workspace.knowledge import scoped_graph

            scenario = db.get(Scenario, args.scenario)
            if scenario is None:
                raise KeyError(f"Scenario not found: {args.scenario}")
            view = scoped_graph(db, args.scenario)
            found_factors, found_composites, details, topics = relevant(state, view["nodes"], floor=args.floor, target_id=view["scope"].target_node_id)
            factor_ids += [f for f in found_factors if f not in factor_ids]
            composite_ids += [c for c in found_composites if c not in composite_ids]
            at = at or parse_horizon(scenario.time_horizon)
            if not factor_ids and not composite_ids:
                return {"scenario_id": args.scenario, "factors": [], "composites": [], "matched_topics": topics, "note": "No cycle is linked to this question's scoped entities or scored at or above the floor for its matched topics. Link a factor's entity_ids or add topics and relevance scores."}
        result = outlook(state, factor_ids=factor_ids, composite_ids=composite_ids, at=at or date.today(), relevance=details)
        if topics is not None:
            result["matched_topics"] = topics
        return result
    if command == "relevance":
        nodes, target = None, None
        if args.scenario:
            from seldon.data.models import Scenario
            from seldon.workspace.knowledge import scoped_graph

            if db.get(Scenario, args.scenario) is None:
                raise KeyError(f"Scenario not found: {args.scenario}")
            view = scoped_graph(db, args.scenario)
            nodes, target = view["nodes"], view["scope"].target_node_id
        return relevance_view(state, topic_id=args.topic, factor_id=args.factor, nodes=nodes, floor=args.floor, target_id=target)
    if command == "chart":
        from .charts import composite_chart, factor_chart
        from .combine import combine

        if args.factor:
            factor = state["factors"].get(args.factor)
            if factor is None:
                raise KeyError(f"Cycle factor not found: {args.factor}")
            from . import preferred_fit

            fit = state["fits"].get(args.fit) if args.fit else preferred_fit(state, args.factor)[0]
            if args.fit and (fit is None or fit["factor_id"] != args.factor):
                raise KeyError("Fit not found for this factor")
            rows = state["by_factor"].get(args.factor, [])
            if factor["measurement"] == "derived":
                from . import series_points
                from .fitting import to_date

                rows = [{"date": to_date(t), "value": v, "kind": "measured", "status": "active", "source_name": "derived from components"} for t, v, _ in series_points(state, args.factor)[0]]
            return factor_chart(factor, rows, fit, as_of=args.as_of)
        if args.composite:
            composite = state["composites"].get(args.composite)
            if composite is None:
                raise KeyError(f"Cycle composite not found: {args.composite}")
            return composite_chart(composite["name"], combine(state, composite["components"], at=args.as_of or date.today(), include_paths=True))
        components = _components(args.component or [])
        if not components:
            raise ValueError("chart needs --factor, --composite or --component")
        return composite_chart("Ad hoc combination", combine(state, components, at=args.as_of or date.today(), include_paths=True))
    raise ValueError(f"Unknown cycles command: {command}")


def add_parser(commands) -> list[argparse.ArgumentParser]:
    cycles = commands.add_parser("cycles", help="Cyclical macro factors: historical series, curve fits, composites and forecast priors")
    sub = cycles.add_subparsers(dest="cycles_command", required=True)
    parsers = []

    def add(name: str, help: str) -> argparse.ArgumentParser:
        parser = sub.add_parser(name, help=help)
        parsers.append(parser)
        return parser

    add("catalog", help="Models, phase conventions, verdict meanings and starting templates")
    schema = add("schema", help="JSON Schema for a request body")
    schema.add_argument("--part", choices=sorted(SCHEMAS), default="apply")
    export = add("export", help="Factors, data coverage, preferred fits, composites and history")
    export.add_argument("--factor", help="Include this factor's observations and full fits")
    export.add_argument("--observations", action="store_true", help="Include every factor's observations")
    export.add_argument("--format", choices=["json", "markdown"], default="json")
    apply = add("apply", help="Validate and atomically persist factors, observations and composites; refits affected factors")
    apply.add_argument("file", type=Path)
    importer = add("import", help="Load a CSV series (FRED-style date,value or year,value) into a factor")
    importer.add_argument("factor_id")
    importer.add_argument("file", type=Path)
    importer.add_argument("--source-name", required=True)
    importer.add_argument("--source-url", help="Required unless --kind assumption")
    importer.add_argument("--kind", choices=["measured", "coded", "assumption"], default="measured")
    importer.add_argument("--retrieved-at", type=lambda s: __import__("datetime").datetime.fromisoformat(s), help="Timezone-aware ISO timestamp; defaults to now")
    importer.add_argument("--date-column")
    importer.add_argument("--value-column")
    importer.add_argument("--uncertainty-column")
    importer.add_argument("--year-anchor", choices=["start", "mid", "end"], default="mid", help="Date used for year-only rows")
    importer.add_argument("--note", default="")
    importer.add_argument("--request-id")
    importer.add_argument("--agent", default="cycle-importer")
    importer.add_argument("--reason", default="Import historical series")
    importer.add_argument("--no-refit", action="store_true")
    fit = add("fit", help="Record a fit; defaults to the factor's preferred specification")
    fit.add_argument("factor_id")
    fit.add_argument("--spec", type=Path, help="FitSpec JSON file")
    fit.add_argument("--model", choices=["harmonic", "oscillator"])
    fit.add_argument("--set", action="append", metavar="KEY=VALUE", help="Override a FitSpec field, e.g. --set harmonics=2 --set period_years=80")
    fit.add_argument("--full", action="store_true", help="Print the complete fit record (curves, projection, diagnostics)")
    fit.add_argument("--agent", default="cycle-fitter")
    fit.add_argument("--reason", default="Fit cycle model")
    refit = add("refit", help="Refit every factor whose preferred fit is missing or stale")
    refit.add_argument("--agent", default="cycle-fitter")
    refit.add_argument("--reason", default="Refit stale cycle factors after new data")
    discover_parser = add("discover", help="Search a fit's residuals for candidate hidden cycles")
    discover_parser.add_argument("factor_id")
    discover_parser.add_argument("--fit")
    discover_parser.add_argument("--surrogates", type=int, default=200)
    combine = add("combine", help="Combine factors: composite path, phase alignment windows and lead/lag")
    combine.add_argument("--composite")
    combine.add_argument("--component", action="append", metavar="FACTOR[:WEIGHT[:LAG_YEARS]]")
    combine.add_argument("--start", type=date.fromisoformat)
    combine.add_argument("--end", type=date.fromisoformat)
    combine.add_argument("--at", type=date.fromisoformat)
    combine.add_argument("--step-years", type=float, default=1.0)
    outlook_parser = add("outlook", help="Cycle priors at a date for factors, composites or a research question")
    outlook_parser.add_argument("--scenario", help="Use factors linked to this question's scoped entities and its horizon date")
    outlook_parser.add_argument("--factor", action="append")
    outlook_parser.add_argument("--composite", action="append")
    outlook_parser.add_argument("--at", type=date.fromisoformat)
    outlook_parser.add_argument("--floor", type=float, default=RELEVANCE_FLOOR, help="Minimum topic relevance score for --scenario")
    relevance = add("relevance", help="Topic-to-cycle relevance lookup; --scenario shows which cycles a question inherits")
    relevance.add_argument("--topic")
    relevance.add_argument("--factor", help="Factor or composite ID")
    relevance.add_argument("--scenario")
    relevance.add_argument("--floor", type=float, default=RELEVANCE_FLOOR)
    chart = add("chart", help="Render an SVG chart of a factor, composite or ad hoc combination")
    chart.add_argument("--factor")
    chart.add_argument("--fit")
    chart.add_argument("--composite")
    chart.add_argument("--component", action="append", metavar="FACTOR[:WEIGHT[:LAG_YEARS]]")
    chart.add_argument("--as-of", type=date.fromisoformat)
    history = add("history", help="Full event for one registry change")
    history.add_argument("run_id")
    return parsers
