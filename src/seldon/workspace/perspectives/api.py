from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from seldon.data.models import AgentRun
from . import PHASE
from . import apply_graph, export_graph, select_context, index_scenario
from .schemas import PerspectiveApply
from ..service import WorkspaceConflict
import json


def build_router(session_dependency):
    router = APIRouter(prefix="/perspectives", tags=["topic and source graphs"])

    @router.get("/connections")
    def connection_view(kind: str, id: str, depth: int = Query(3, ge=0, le=12), to_kind: str | None = None, to_id: str | None = None, db: Session = Depends(session_dependency)):
        from .connections import connections
        try:
            return connections(db, kind, id, depth=depth, to_kind=to_kind, to_id=to_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/catalog")
    def catalog(db: Session = Depends(session_dependency)):
        from .connections import connection_catalog
        return connection_catalog(db)

    @router.get("/schema")
    def schema():
        return PerspectiveApply.model_json_schema()

    @router.get("")
    def export(topic_id: str | None = None, source_id: str | None = None, depth: int = Query(4, ge=0, le=12), format: str = "json", db: Session = Depends(session_dependency)):
        graph = export_graph(db)
        try:
            context = select_context(graph, topic_id=topic_id, source_id=source_id, depth=depth)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        context.update(revision=graph["revision"], history=graph["history"], totals={k: len(graph[k]) for k in ("topics", "sources", "claims", "assessments")})
        if format == "markdown":
            return PlainTextResponse("# Topics, claims and sources\n\n```json\n" + json.dumps(context, indent=2, ensure_ascii=False) + "\n```\n", headers={"Content-Disposition": 'attachment; filename="topic-source-graphs.md"'})
        if format != "json":
            raise HTTPException(422, "format must be json or markdown")
        return context

    @router.get("/history/{run_id}")
    def history(run_id: str, db: Session = Depends(session_dependency)):
        run = db.get(AgentRun, run_id)
        if not run or run.phase != PHASE:
            raise HTTPException(404, "Perspective change not found")
        return {"id": run.id, "agent": run.agent_id, "input": run.input, "event": run.output}

    @router.post("/apply")
    def apply(payload: PerspectiveApply, db: Session = Depends(session_dependency)):
        try:
            with db.begin():
                return apply_graph(db, payload)
        except WorkspaceConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/index/{scenario_id}")
    def index(scenario_id: str, db: Session = Depends(session_dependency)):
        try:
            with db.begin():
                return index_scenario(db, scenario_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return router
