"""HTTP adapter for cycle factors; shares the host API's authentication and database."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from . import (
    PHASE,
    apply_cycles,
    discover,
    export_view,
    fitting,
    import_csv,
    load_state,
    outlook,
    parse_horizon,
    preferred_fit,
    record_fit,
    refit_stale,
    relevance_view,
    relevant,
    render_markdown,
)
from .catalog import RELEVANCE_FLOOR
from .cli import SCHEMAS
from .schemas import CombineRequest, CyclesApply, FitRequest, ImportRequest, RefitRequest


def _errors(call):
    from ..service import WorkspaceConflict

    try:
        return call()
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'")) from exc
    except WorkspaceConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, fitting.InsufficientData) as exc:
        raise HTTPException(422, str(exc)) from exc


def build_router(session_dependency) -> APIRouter:
    router = APIRouter(prefix="/cycles", tags=["cycle factors"])

    @router.get("/catalog")
    def catalog():
        from .catalog import catalog as build

        return build()

    @router.get("/schema")
    def schema(part: str = "apply"):
        if part not in SCHEMAS:
            raise HTTPException(422, f"part must be one of {', '.join(sorted(SCHEMAS))}")
        return SCHEMAS[part].model_json_schema()

    @router.get("")
    def export(factor_id: str | None = None, observations: bool = False, format: str = "json", db: Session = Depends(session_dependency)):
        if format not in {"json", "markdown"}:
            raise HTTPException(422, "format must be json or markdown")
        view = _errors(lambda: export_view(load_state(db), factor_id=factor_id, observations=observations))
        return PlainTextResponse(render_markdown(view)) if format == "markdown" else view

    @router.post("/apply")
    def apply(payload: CyclesApply, db: Session = Depends(session_dependency)):
        def run():
            with db.begin():
                return apply_cycles(db, payload)

        return _errors(run)

    @router.post("/factors/{factor_id}/import")
    def import_series(factor_id: str, payload: ImportRequest, db: Session = Depends(session_dependency)):
        def run():
            with db.begin():
                return import_csv(db, factor_id, payload)

        return _errors(run)

    @router.post("/factors/{factor_id}/fit")
    def fit(factor_id: str, payload: FitRequest, full: bool = False, db: Session = Depends(session_dependency)):
        def run():
            with db.begin():
                return record_fit(db, factor_id, payload.spec, agent=payload.agent, reason=payload.reason, full=full)

        return _errors(run)

    @router.post("/refit")
    def refit(payload: RefitRequest, db: Session = Depends(session_dependency)):
        def run():
            with db.begin():
                return refit_stale(db, agent=payload.agent, reason=payload.reason)

        return _errors(run)

    @router.get("/factors/{factor_id}/discover")
    def discover_cycles(factor_id: str, fit_id: str | None = None, surrogates: int = Query(200, ge=0, le=2000), db: Session = Depends(session_dependency)):
        return _errors(lambda: discover(load_state(db, revision=False), factor_id, fit_id, surrogates))

    @router.post("/combine")
    def combine_factors(payload: CombineRequest, db: Session = Depends(session_dependency)):
        from .combine import combine

        def run():
            state = load_state(db, revision=False)
            if payload.composite_id and payload.composite_id not in state["composites"]:
                raise KeyError(f"Cycle composite not found: {payload.composite_id}")
            components = state["composites"][payload.composite_id]["components"] if payload.composite_id else [c.model_dump() for c in payload.components]
            return combine(state, components, start=payload.start, end=payload.end, at=payload.at or date.today(), step=payload.step_years)

        return _errors(run)

    @router.get("/outlook")
    def outlook_view(scenario_id: str | None = None, factor_id: list[str] = Query(default=[]), composite_id: list[str] = Query(default=[]), at: date | None = None, floor: float = Query(RELEVANCE_FLOOR, ge=0, le=1), db: Session = Depends(session_dependency)):
        def run():
            state = load_state(db, revision=False)
            factors, composites, when = list(factor_id), list(composite_id), at
            details, topics = {}, None
            if scenario_id:
                from seldon.data.models import Scenario
                from seldon.workspace.knowledge import scoped_graph

                scenario = db.get(Scenario, scenario_id)
                if scenario is None:
                    raise KeyError(f"Scenario not found: {scenario_id}")
                view = scoped_graph(db, scenario_id)
                found_factors, found_composites, details, topics = relevant(state, view["nodes"], floor=floor, target_id=view["scope"].target_node_id)
                factors += [f for f in found_factors if f not in factors]
                composites += [c for c in found_composites if c not in composites]
                when = when or parse_horizon(scenario.time_horizon)
            result = outlook(state, factor_ids=factors, composite_ids=composites, at=when or date.today(), relevance=details)
            if topics is not None:
                result["matched_topics"] = topics
            return result

        return _errors(run)

    @router.get("/relevance")
    def relevance_lookup(topic_id: str | None = None, factor_id: str | None = None, scenario_id: str | None = None, floor: float = Query(RELEVANCE_FLOOR, ge=0, le=1), db: Session = Depends(session_dependency)):
        def run():
            nodes, target = None, None
            if scenario_id:
                from seldon.data.models import Scenario
                from seldon.workspace.knowledge import scoped_graph

                if db.get(Scenario, scenario_id) is None:
                    raise KeyError(f"Scenario not found: {scenario_id}")
                view = scoped_graph(db, scenario_id)
                nodes, target = view["nodes"], view["scope"].target_node_id
            return relevance_view(load_state(db, revision=False), topic_id=topic_id, factor_id=factor_id, nodes=nodes, floor=floor, target_id=target)

        return _errors(run)

    @router.get("/factors/{factor_id}/chart.svg")
    def factor_chart_view(factor_id: str, fit_id: str | None = None, as_of: date | None = None, db: Session = Depends(session_dependency)):
        from .charts import factor_chart
        from . import series_points

        def run():
            state = load_state(db, revision=False)
            factor = state["factors"].get(factor_id)
            if factor is None:
                raise KeyError(f"Cycle factor not found: {factor_id}")
            fit = state["fits"].get(fit_id) if fit_id else preferred_fit(state, factor_id)[0]
            if fit_id and (fit is None or fit["factor_id"] != factor_id):
                raise KeyError("Fit not found for this factor")
            rows = state["by_factor"].get(factor_id, [])
            if factor["measurement"] == "derived":
                rows = [{"date": fitting.to_date(t), "value": v, "kind": "measured", "status": "active", "source_name": "derived from components"} for t, v, _ in series_points(state, factor_id)[0]]
            return factor_chart(factor, rows, fit, as_of=as_of)

        return Response(_errors(run), media_type="image/svg+xml", headers={"X-Content-Type-Options": "nosniff"})

    @router.get("/composites/{composite_id}/chart.svg")
    def composite_chart_view(composite_id: str, as_of: date | None = None, db: Session = Depends(session_dependency)):
        from .charts import composite_chart
        from .combine import combine

        def run():
            state = load_state(db, revision=False)
            composite = state["composites"].get(composite_id)
            if composite is None:
                raise KeyError(f"Cycle composite not found: {composite_id}")
            return composite_chart(composite["name"], combine(state, composite["components"], at=as_of or date.today(), include_paths=True))

        return Response(_errors(run), media_type="image/svg+xml", headers={"X-Content-Type-Options": "nosniff"})

    @router.get("/history/{run_id}")
    def history(run_id: str, db: Session = Depends(session_dependency)):
        from seldon.data.models import AgentRun

        row = db.get(AgentRun, run_id)
        if not row or row.phase != PHASE:
            raise HTTPException(404, "Cycle registry change not found")
        return {"id": row.id, "agent": row.agent_id, "input": row.input, "event": row.output}

    return router
