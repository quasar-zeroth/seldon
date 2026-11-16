"""HTTP adapter for video transcripts; shares the host API's authentication and database."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from . import fetch_transcript, import_transcript, ingest, list_transcripts, load_state, mentions, providers, render_markdown, transcript_view
from .cli import SCHEMAS
from .schemas import FetchRequest, ImportRequest, IngestRequest


def _errors(call):
    from ..service import WorkspaceConflict

    try:
        return call()
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'\"")) from exc
    except WorkspaceConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except providers.TranscriptUnavailable as exc:
        raise HTTPException(422, str(exc)) from exc
    except providers.ServiceError as exc:
        raise HTTPException(502, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def build_router(session_dependency) -> APIRouter:
    router = APIRouter(prefix="/transcripts", tags=["video transcripts"])

    @router.get("/catalog")
    def catalog():
        from .catalog import catalog as build

        return build()

    @router.get("/schema")
    def schema(part: str = "ingest"):
        if part not in SCHEMAS:
            raise HTTPException(422, f"part must be one of {', '.join(sorted(SCHEMAS))}")
        return SCHEMAS[part].model_json_schema()

    @router.get("")
    def listing(scenario_id: str | None = None, db: Session = Depends(session_dependency)):
        return list_transcripts(db, scenario_id)

    @router.post("/fetch", status_code=201)
    def fetch(payload: FetchRequest, db: Session = Depends(session_dependency)):
        def run():
            with db.begin():
                return fetch_transcript(db, payload)

        return _errors(run)

    @router.post("/import", status_code=201)
    def supplied(payload: ImportRequest, db: Session = Depends(session_dependency)):
        def run():
            with db.begin():
                return import_transcript(db, payload)

        return _errors(run)

    @router.post("/ingest")
    def ingest_excerpts(payload: IngestRequest, db: Session = Depends(session_dependency)):
        def run():
            with db.begin():
                return ingest(db, payload)

        return _errors(run)

    @router.get("/{transcript_id}")
    def show(transcript_id: str, version: int | None = Query(None, ge=1), start: str | None = None, end: str | None = None, format: str = "json", db: Session = Depends(session_dependency)):
        if format not in {"json", "markdown"}:
            raise HTTPException(422, "format must be json or markdown")
        view = _errors(lambda: transcript_view(load_state(db), transcript_id, version=version, start=start, end=end))
        return PlainTextResponse(render_markdown(view), media_type="text/markdown; charset=utf-8") if format == "markdown" else view

    @router.get("/{transcript_id}/mentions")
    def found(transcript_id: str, version: int | None = Query(None, ge=1), limit: int = Query(50, ge=1, le=500), db: Session = Depends(session_dependency)):
        return _errors(lambda: mentions(db, transcript_id, version=version, limit=limit))

    return router
