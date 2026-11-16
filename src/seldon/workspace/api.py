"""HTTP adapter; shares the host API's authentication and database."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .schemas import StartRequest, WorkspaceApply
from .service import WorkspaceConflict, WorkspaceService, render_markdown
from .reports import ReportRequest, generate_report, list_reports, report_file


class RerunRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(
        default="Refresh the forecast with current evidence", min_length=1
    )
    horizon: str | None = None


def build_router(session_dependency) -> APIRouter:
    router = APIRouter(prefix="/workspace", tags=["external-agent research"])

    @router.get("/schema")
    def schema():
        return WorkspaceApply.model_json_schema()

    @router.get("/library")
    def library(
        q: str = "",
        entity_id: str | None = None,
        tag: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(30, ge=1, le=100),
        db: Session = Depends(session_dependency),
    ):
        from .knowledge import search_library

        return search_library(db, q, limit, tag=tag, offset=offset, entity_id=entity_id)

    @router.get("/reports")
    def reports(scenario_id: str | None = None, db: Session = Depends(session_dependency)):
        return list_reports(db, scenario_id)

    @router.post("/scenarios/{scenario_id}/reports", status_code=201)
    def generate(scenario_id: str, payload: ReportRequest, db: Session = Depends(session_dependency)):
        try:
            with db.begin():
                return generate_report(db, scenario_id, payload)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except WorkspaceConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/reports/{report_id}/files/{name}")
    def download_report(report_id: str, name: str, db: Session = Depends(session_dependency)):
        try:
            file = report_file(db, report_id, name)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return PlainTextResponse(file['content'], media_type=file['media_type'], headers={'Content-Disposition': f'attachment; filename="{name}"', 'X-Content-Type-Options': 'nosniff'})

    @router.get("/prediction-requests")
    def requests(
        scenario_id: str | None = None, db: Session = Depends(session_dependency)
    ):
        from .reruns import list_requests

        return list_requests(db, scenario_id)

    @router.post("/scenarios/{scenario_id}/rerun", status_code=202)
    def rerun(
        scenario_id: str,
        payload: RerunRequest,
        db: Session = Depends(session_dependency),
    ):
        from .reruns import request_prediction

        try:
            with db.begin():
                return request_prediction(db, scenario_id, **payload.model_dump())
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/pipeline")
    def pipeline(
        scenario_id: str | None = None,
        history_limit: int = Query(50, ge=1, le=200),
        db: Session = Depends(session_dependency),
    ):
        from .pipeline import pipeline_snapshot

        try:
            return pipeline_snapshot(db, scenario_id, history_limit=history_limit)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/scenarios", status_code=201)
    def start(payload: StartRequest, db: Session = Depends(session_dependency)):
        try:
            with db.begin():
                return WorkspaceService(db).start(
                    payload.question, payload.horizon, name=payload.name
                )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/scenarios/{scenario_id}")
    def export(
        scenario_id: str,
        format: str = "json",
        db: Session = Depends(session_dependency),
    ):
        if format not in {"json", "markdown"}:
            raise HTTPException(422, "format must be json or markdown")
        try:
            result = WorkspaceService(db).export(scenario_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return (
            PlainTextResponse(render_markdown(result))
            if format == "markdown"
            else result
        )

    @router.post("/apply")
    def apply(payload: WorkspaceApply, db: Session = Depends(session_dependency)):
        try:
            with db.begin():
                return WorkspaceService(db).apply(payload)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except WorkspaceConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    from .perspectives.api import build_router as perspective_router
    router.include_router(perspective_router(session_dependency))
    return router
