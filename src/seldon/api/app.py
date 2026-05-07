"""FastAPI application shell for The Seldon Project."""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from pydantic import BaseModel, Field

from seldon.agents import AdvancedIntelligenceCoordinator, AdvancedIntelligenceInput, ContextGatheringCoordinator, ConvergenceLoopCoordinator, ConvergenceLoopInput, ExtractionCoordinator, FeedbackCoordinator, FeedbackInput, GraphConstructionCoordinator, PredictionCoordinator, compute_calibration_summary
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AdvancedAnalysis, AgentRun, ERGNode, KBEntry, ModelInvocation, OutcomeCheck, Scenario, ScenarioPrediction
from seldon.data.repositories import AgentRunRepository, GraphRepository, KBRepository, ScenarioRepository, row_to_dict
from seldon.data.schemas import (
    AgentRunCreate,
    AgentRunUpdate,
    ERGEdgeCreate,
    ERGNodeCreate,
    KBEntryCreate,
    KBEntryUpdate,
    ScenarioCreate,
    ScenarioUpdate,
)
from seldon.llm.openrouter import OpenRouterClient
from seldon.ops import InProcessJobQueue, configure_structured_logging, create_backup, seed_demo_data


logger = logging.getLogger(__name__)


class ContextGatheringRequest(BaseModel):
    depth: str = "standard"
    source_policy: str = "kb_first"
    max_subqueries: int = Field(default=8, ge=1, le=20)


class ExtractionRequest(BaseModel):
    max_kb_entries: int = Field(default=50, ge=1, le=500)
    max_nodes: int = Field(default=50, ge=1, le=200)


class GraphConstructionRequest(BaseModel):
    max_candidate_pairs: int = Field(default=40, ge=1, le=500)
    min_confidence_to_write: float = Field(default=0.35, ge=0.0, le=1.0)
    run_convergence_loop: bool = False
    max_iterations: int = Field(default=3, ge=1, le=10)
    min_new_info_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    coverage_target: float = Field(default=0.65, ge=0.0, le=1.0)


class PredictionRequest(BaseModel):
    max_driver_nodes: int = Field(default=8, ge=1, le=50)
    min_confidence_to_activate: float = Field(default=0.35, ge=0.0, le=1.0)
    export_markdown: bool = True


class AdvancedIntelligenceRequest(BaseModel):
    max_items: int = Field(default=5, ge=1, le=20)
    previous_prediction_id: str | None = None


class FeedbackRequest(BaseModel):
    prediction_id: str
    actual_outcome: str
    resolved_outcome_key: str
    resolution_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_references: list[str] = Field(default_factory=list)
    notes: str = ""
    missed_factors: list[str] = Field(default_factory=list)
    failed_assumptions: list[str] = Field(default_factory=list)
    graph_corrections: list[dict[str, Any]] = Field(default_factory=list)
    update_kb: bool = True


def _error(code: str, message: str, *, details: Any | None = None, http_status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=http_status, content={"error": {"code": code, "message": message, "details": details}})


def _values(model: Any) -> dict[str, Any]:
    return model.model_dump(exclude_unset=True, mode="json")


def _row(row: Any) -> dict[str, Any]:
    return row_to_dict(row)


def _rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [_row(row) for row in rows]


def create_app(
    config: SeldonConfig | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    llm_client: OpenRouterClient | None = None,
    job_queue: InProcessJobQueue | None = None,
) -> FastAPI:
    """Create the Seldon FastAPI app with overrideable dependencies for tests/hosts."""
    app_config = config or SeldonConfig()
    configure_structured_logging(json_logs=app_config.ops.structured_logs, level=app_config.ops.log_level)
    engine: Engine | None = None
    if session_factory is None:
        engine = make_engine(app_config.database.url, sqlite_path=app_config.database.sqlite_path, echo=app_config.database.echo)
        create_all(engine)
        session_factory = make_session_factory(engine)
    else:
        bind = session_factory.kw.get("bind")
        engine = bind if isinstance(bind, Engine) else None
    app_llm_client = llm_client or OpenRouterClient(app_config.llm)
    app_job_queue = job_queue or InProcessJobQueue()

    def get_config_dep() -> SeldonConfig:
        return app_config

    def get_llm_dep() -> OpenRouterClient:
        return app_llm_client

    def get_session_dep() -> Iterator[Session]:
        assert session_factory is not None
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def backup_job(payload: dict[str, Any]) -> dict[str, Any]:
        label = payload.get("label") if isinstance(payload.get("label"), str) else None
        return create_backup(app_config, engine=engine, label=label).to_dict()

    def seed_job(_: dict[str, Any]) -> dict[str, Any]:
        assert session_factory is not None
        session = session_factory()
        try:
            with session.begin():
                return seed_demo_data(session)
        finally:
            session.close()

    app_job_queue.register("backup", backup_job)
    app_job_queue.register("seed_demo", seed_job)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        app_job_queue.start()
        try:
            yield
        finally:
            app_job_queue.stop()

    app = FastAPI(
        title="The Seldon Project API",
        description="FastAPI backend shell for scenarios, KB, graph, runs, and model configuration.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def operations_middleware(request: Request, call_next: Any) -> JSONResponse:
        if app_config.ops.require_api_key and request.url.path not in {"/health", "/openapi.json", "/docs", "/redoc"}:
            client_host = request.client.host if request.client else ""
            local = client_host in {"127.0.0.1", "::1", "testclient"}
            if not (local and app_config.ops.allow_localhost_without_api_key):
                expected = os.getenv(app_config.ops.api_key_env)
                supplied = request.headers.get("x-seldon-api-key")
                auth = request.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    supplied = auth.split(" ", 1)[1]
                if not expected or supplied != expected:
                    return _error("unauthorized", "Valid API key required", http_status=status.HTTP_401_UNAUTHORIZED)
        response = await call_next(request)
        logger.info(
            "request completed",
            extra={
                "seldon_method": request.method,
                "seldon_path": request.url.path,
                "seldon_status_code": response.status_code,
            },
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return _error(str(detail.get("code", "http_error")), str(detail.get("message", exc.detail)), details=detail.get("details"), http_status=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error("validation_error", "Request validation failed", details=exc.errors(), http_status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    @app.exception_handler(KeyError)
    async def key_error_handler(_: Request, exc: KeyError) -> JSONResponse:
        return _error("not_found", str(exc).strip("'"), http_status=status.HTTP_404_NOT_FOUND)

    def not_found(entity: str, id: str) -> HTTPException:
        return HTTPException(status_code=404, detail={"code": "not_found", "message": f"{entity} not found: {id}"})

    @app.get("/health")
    def health(db: Session = Depends(get_session_dep), llm: OpenRouterClient = Depends(get_llm_dep)) -> dict[str, Any]:
        db.execute(select(1)).scalar_one()
        return {"ok": True, "service": "seldon-api", "llm_default_model": llm.config.default_model}

    @app.get("/config/models")
    def model_config(cfg: SeldonConfig = Depends(get_config_dep)) -> dict[str, Any]:
        return {
            "profiles": {
                "fast": cfg.llm.fast_model,
                "balanced": cfg.llm.default_model,
                "reasoning": cfg.llm.reasoning_model,
                "embedding": cfg.llm.embedding_model,
            },
            "fallback_models": cfg.llm.fallback_models,
            "agents": cfg.agents.model_dump(mode="json"),
        }

    @app.patch("/config/models")
    def patch_model_config(patch: dict[str, Any], cfg: SeldonConfig = Depends(get_config_dep)) -> dict[str, Any]:
        profiles = patch.get("profiles", {})
        mapping = {"fast": "fast_model", "balanced": "default_model", "reasoning": "reasoning_model", "embedding": "embedding_model"}
        for profile, field in mapping.items():
            if profile in profiles:
                setattr(cfg.llm, field, profiles[profile])
        if "fallback_models" in patch:
            cfg.llm.fallback_models = list(patch["fallback_models"])
        return model_config(cfg)

    @app.post("/scenarios", status_code=201)
    def create_scenario(payload: ScenarioCreate, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        with db.begin():
            row = ScenarioRepository(db).create_scenario(**_values(payload))
        return _row(row)

    @app.get("/scenarios")
    def list_scenarios(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_session_dep)) -> list[dict[str, Any]]:
        return _rows(list(db.scalars(select(Scenario).order_by(Scenario.created_at.desc()).offset(offset).limit(limit))))

    @app.get("/scenarios/{scenario_id}")
    def get_scenario(scenario_id: str, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        row = db.get(Scenario, scenario_id)
        if row is None:
            raise not_found("scenario", scenario_id)
        return _row(row)

    @app.patch("/scenarios/{scenario_id}")
    def update_scenario(scenario_id: str, payload: ScenarioUpdate, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        values = _values(payload)
        with db.begin():
            row = db.get(Scenario, scenario_id)
            if row is None:
                raise not_found("scenario", scenario_id)
            before = row_to_dict(row)
            for key, value in values.items():
                setattr(row, key, value)
            db.flush()
            ScenarioRepository(db).audit.emit("scenario", scenario_id, "update", before=before, after=row_to_dict(row))
        return _row(row)

    def _stub_phase_run(scenario_id: str, phase: str, db: Session) -> dict[str, Any]:
        with db.begin():
            if db.get(Scenario, scenario_id) is None:
                raise not_found("scenario", scenario_id)
            row = AgentRunRepository(db).create(agent_id=f"{phase}_coordinator", phase=phase, status="pending", input={"scenario_id": scenario_id})
        return _row(row)

    @app.post("/scenarios/{scenario_id}/run-context-gathering", status_code=202)
    def run_context(
        scenario_id: str,
        payload: ContextGatheringRequest | None = None,
        db: Session = Depends(get_session_dep),
        cfg: SeldonConfig = Depends(get_config_dep),
        llm: OpenRouterClient = Depends(get_llm_dep),
    ) -> dict[str, Any]:
        request = payload or ContextGatheringRequest()
        with db.begin():
            scenario = db.get(Scenario, scenario_id)
            if scenario is None:
                raise not_found("scenario", scenario_id)
            agent_input = ContextGatheringCoordinator.input_from_scenario(
                scenario,
                depth=request.depth,
                source_policy=request.source_policy,
                max_subqueries=request.max_subqueries,
            )
            run_id, output = ContextGatheringCoordinator(db, config=cfg, llm_client=llm).run(agent_input)
            row = db.get(AgentRun, run_id)
        assert row is not None
        data = _row(row)
        data["context_gathering"] = output.model_dump(mode="json")
        return data

    @app.post("/scenarios/{scenario_id}/run-extraction", status_code=202)
    def run_extraction(
        scenario_id: str,
        payload: ExtractionRequest | None = None,
        db: Session = Depends(get_session_dep),
        cfg: SeldonConfig = Depends(get_config_dep),
        llm: OpenRouterClient = Depends(get_llm_dep),
    ) -> dict[str, Any]:
        request = payload or ExtractionRequest()
        with db.begin():
            scenario = db.get(Scenario, scenario_id)
            if scenario is None:
                raise not_found("scenario", scenario_id)
            agent_input = ExtractionCoordinator.input_from_scenario(scenario, max_kb_entries=request.max_kb_entries, max_nodes=request.max_nodes)
            run_id, output = ExtractionCoordinator(db, config=cfg, llm_client=llm).run(agent_input)
            row = db.get(AgentRun, run_id)
        assert row is not None
        data = _row(row)
        data["extraction"] = output.model_dump(mode="json")
        return data

    @app.post("/scenarios/{scenario_id}/run-graph-construction", status_code=202)
    def run_graph_construction(
        scenario_id: str,
        payload: GraphConstructionRequest | None = None,
        db: Session = Depends(get_session_dep),
        cfg: SeldonConfig = Depends(get_config_dep),
        llm: OpenRouterClient = Depends(get_llm_dep),
    ) -> dict[str, Any]:
        request = payload or GraphConstructionRequest()
        with db.begin():
            scenario = db.get(Scenario, scenario_id)
            if scenario is None:
                raise not_found("scenario", scenario_id)
            if request.run_convergence_loop:
                agent_input = ConvergenceLoopInput(
                    scenario_id=scenario_id,
                    max_iterations=request.max_iterations,
                    min_new_info_threshold=request.min_new_info_threshold,
                    coverage_target=request.coverage_target,
                    max_candidate_pairs=request.max_candidate_pairs,
                )
                run_id, output = ConvergenceLoopCoordinator(db, config=cfg, llm_client=llm).run(agent_input)
                row = db.get(AgentRun, run_id)
                assert row is not None
                data = _row(row)
                data["convergence_loop"] = output.model_dump(mode="json")
                return data
            agent_input = GraphConstructionCoordinator.input_from_scenario(
                scenario,
                max_candidate_pairs=request.max_candidate_pairs,
                min_confidence_to_write=request.min_confidence_to_write,
            )
            run_id, output = GraphConstructionCoordinator(db, config=cfg, llm_client=llm).run(agent_input)
            row = db.get(AgentRun, run_id)
        assert row is not None
        data = _row(row)
        data["graph_construction"] = output.model_dump(mode="json")
        return data

    @app.post("/scenarios/{scenario_id}/run-prediction", status_code=202)
    def run_prediction(
        scenario_id: str,
        payload: PredictionRequest | None = None,
        db: Session = Depends(get_session_dep),
        cfg: SeldonConfig = Depends(get_config_dep),
        llm: OpenRouterClient = Depends(get_llm_dep),
    ) -> dict[str, Any]:
        request = payload or PredictionRequest()
        with db.begin():
            scenario = db.get(Scenario, scenario_id)
            if scenario is None:
                raise not_found("scenario", scenario_id)
            agent_input = PredictionCoordinator.input_from_scenario(
                scenario,
                max_driver_nodes=request.max_driver_nodes,
                min_confidence_to_activate=request.min_confidence_to_activate,
                export_markdown=request.export_markdown,
            )
            run_id, output = PredictionCoordinator(db, config=cfg, llm_client=llm).run(agent_input)
            row = db.get(AgentRun, run_id)
        assert row is not None
        data = _row(row)
        data["prediction"] = output.model_dump(mode="json")
        return data

    @app.post("/predictions/{prediction_id}/run-advanced-intelligence", status_code=202)
    def run_advanced_intelligence(
        prediction_id: str,
        payload: AdvancedIntelligenceRequest | None = None,
        db: Session = Depends(get_session_dep),
        cfg: SeldonConfig = Depends(get_config_dep),
        llm: OpenRouterClient = Depends(get_llm_dep),
    ) -> dict[str, Any]:
        request = payload or AdvancedIntelligenceRequest()
        with db.begin():
            prediction = db.get(ScenarioPrediction, prediction_id)
            if prediction is None:
                raise not_found("scenario_prediction", prediction_id)
            agent_input = AdvancedIntelligenceInput(prediction_id=prediction_id, previous_prediction_id=request.previous_prediction_id, max_items=request.max_items)
            run_id, output = AdvancedIntelligenceCoordinator(db, config=cfg, llm_client=llm).run(agent_input)
            row = db.get(AgentRun, run_id)
        assert row is not None
        data = _row(row)
        data["advanced_intelligence"] = output.model_dump(mode="json")
        return data

    @app.post("/scenarios/{scenario_id}/run-feedback", status_code=202)
    def run_feedback(
        scenario_id: str,
        payload: FeedbackRequest,
        db: Session = Depends(get_session_dep),
        cfg: SeldonConfig = Depends(get_config_dep),
        llm: OpenRouterClient = Depends(get_llm_dep),
    ) -> dict[str, Any]:
        with db.begin():
            scenario = db.get(Scenario, scenario_id)
            if scenario is None:
                raise not_found("scenario", scenario_id)
            prediction = db.get(ScenarioPrediction, payload.prediction_id)
            if prediction is None:
                raise not_found("scenario_prediction", payload.prediction_id)
            if prediction.scenario_id != scenario_id:
                raise HTTPException(status_code=400, detail={"code": "scenario_mismatch", "message": "prediction does not belong to scenario"})
            run_id, output = FeedbackCoordinator(db, config=cfg, llm_client=llm).run(FeedbackInput(**_values(payload)))
            row = db.get(AgentRun, run_id)
        assert row is not None
        data = _row(row)
        data["feedback"] = output.model_dump(mode="json")
        return data

    @app.post("/kb/entries", status_code=201)
    def create_kb_entry(payload: KBEntryCreate, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        with db.begin():
            row = KBRepository(db).create_entry(**_values(payload))
        return _row(row)

    @app.get("/kb/search")
    def search_kb(
        q: str | None = None,
        topic: str | None = None,
        entity: str | None = None,
        scenario_id: str | None = None,
        current_only: bool = False,
        db: Session = Depends(get_session_dep),
    ) -> list[dict[str, Any]]:
        return _rows(KBRepository(db).search(q, topic=topic, entity=entity, scenario_id=scenario_id, current_only=current_only))

    @app.get("/kb/entries/{entry_id}")
    def get_kb_entry(entry_id: str, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        row = db.get(KBEntry, entry_id)
        if row is None:
            raise not_found("kb_entry", entry_id)
        return _row(row)

    @app.patch("/kb/entries/{entry_id}")
    def update_kb_entry(entry_id: str, payload: KBEntryUpdate, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        with db.begin():
            row = KBRepository(db).update_entry(entry_id, **_values(payload))
        return _row(row)

    @app.post("/graph/nodes", status_code=201)
    def create_graph_node(payload: ERGNodeCreate, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        with db.begin():
            row = GraphRepository(db).create_node(**_values(payload))
        return _row(row)

    @app.get("/graph/nodes")
    def list_graph_nodes(db: Session = Depends(get_session_dep)) -> list[dict[str, Any]]:
        return _rows(GraphRepository(db).list_nodes())

    @app.get("/graph/nodes/{node_id}")
    def get_graph_node(node_id: str, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        row = GraphRepository(db).get_node(node_id)
        if row is None:
            raise not_found("erg_node", node_id)
        return _row(row)

    @app.post("/graph/edges", status_code=201)
    def create_graph_edge(payload: ERGEdgeCreate, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        with db.begin():
            row = GraphRepository(db).create_edge(**_values(payload))
        return _row(row)

    @app.get("/graph/edges")
    def list_graph_edges(node_id: str | None = None, db: Session = Depends(get_session_dep)) -> list[dict[str, Any]]:
        return _rows(GraphRepository(db).list_edges(node_id=node_id))

    @app.get("/graph/neighborhood/{node_id}")
    def graph_neighborhood(node_id: str, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        repo = GraphRepository(db)
        node = repo.get_node(node_id)
        if node is None:
            raise not_found("erg_node", node_id)
        edges = repo.list_edges(node_id=node_id)
        neighbor_ids = {e.source_node_id for e in edges} | {e.target_node_id for e in edges}
        nodes = [db.get(ERGNode, id) for id in neighbor_ids]
        return {"center": _row(node), "nodes": _rows([n for n in nodes if n is not None]), "edges": _rows(edges)}

    @app.post("/runs", status_code=201)
    def create_run(payload: AgentRunCreate, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        with db.begin():
            row = AgentRunRepository(db).create(**_values(payload))
        return _row(row)

    @app.get("/runs")
    def list_runs(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_session_dep)) -> list[dict[str, Any]]:
        runs = list(db.scalars(select(AgentRun).order_by(AgentRun.updated_at.desc()).offset(offset).limit(limit)))
        invocations = list(db.scalars(select(ModelInvocation)))
        by_run: dict[str, list[dict[str, Any]]] = {}
        for invocation in invocations:
            if invocation.agent_run_id:
                by_run.setdefault(invocation.agent_run_id, []).append(_row(invocation))
        rows = []
        for run in runs:
            data = _row(run)
            data["model_invocations"] = by_run.get(run.id, [])
            rows.append(data)
        return rows

    @app.get("/predictions")
    def list_predictions(scenario_id: str | None = None, db: Session = Depends(get_session_dep)) -> list[dict[str, Any]]:
        stmt = select(ScenarioPrediction).order_by(ScenarioPrediction.updated_at.desc())
        if scenario_id:
            stmt = stmt.where(ScenarioPrediction.scenario_id == scenario_id)
        return _rows(list(db.scalars(stmt)))

    @app.get("/predictions/{prediction_id}")
    def get_prediction(prediction_id: str, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        row = db.get(ScenarioPrediction, prediction_id)
        if row is None:
            raise not_found("scenario_prediction", prediction_id)
        return _row(row)

    @app.get("/runs/{run_id}")
    def get_run(run_id: str, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        row = db.get(AgentRun, run_id)
        if row is None:
            raise not_found("agent_run", run_id)
        data = _row(row)
        data["model_invocations"] = _rows(list(db.scalars(select(ModelInvocation).where(ModelInvocation.agent_run_id == run_id))))
        return data

    @app.patch("/runs/{run_id}")
    def update_run(run_id: str, payload: AgentRunUpdate, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        with db.begin():
            row = AgentRunRepository(db).update(run_id, **_values(payload))
        return _row(row)

    @app.post("/runs/{run_id}/retry", status_code=202)
    def retry_run(run_id: str, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        with db.begin():
            old = db.get(AgentRun, run_id)
            if old is None:
                raise not_found("agent_run", run_id)
            row = AgentRunRepository(db).create(agent_id=old.agent_id, phase=old.phase, status="pending", input={"retry_of": run_id, **(old.input or {})}, source_references=old.source_references or [])
        return _row(row)

    @app.get("/advanced-analyses")
    def list_advanced_analyses(prediction_id: str | None = None, db: Session = Depends(get_session_dep)) -> list[dict[str, Any]]:
        stmt = select(AdvancedAnalysis).order_by(AdvancedAnalysis.created_at.desc())
        if prediction_id:
            stmt = stmt.where(AdvancedAnalysis.prediction_id == prediction_id)
        return _rows(list(db.scalars(stmt)))

    @app.get("/advanced-analyses/{analysis_id}")
    def get_advanced_analysis(analysis_id: str, db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        row = db.get(AdvancedAnalysis, analysis_id)
        if row is None:
            raise not_found("advanced_analysis", analysis_id)
        return _row(row)

    @app.get("/outcome-checks")
    def list_outcome_checks(prediction_id: str | None = None, db: Session = Depends(get_session_dep)) -> list[dict[str, Any]]:
        stmt = select(OutcomeCheck).order_by(OutcomeCheck.checked_at.desc())
        if prediction_id:
            stmt = stmt.where(OutcomeCheck.prediction_id == prediction_id)
        return _rows(list(db.scalars(stmt)))

    @app.get("/calibration/summary")
    def calibration_summary(db: Session = Depends(get_session_dep)) -> dict[str, Any]:
        return compute_calibration_summary(db).model_dump(mode="json")

    @app.post("/ops/jobs", status_code=202)
    def enqueue_job(payload: dict[str, Any]) -> dict[str, Any]:
        kind = payload.get("kind")
        if not isinstance(kind, str):
            raise HTTPException(status_code=422, detail={"code": "validation_error", "message": "job kind is required"})
        job_payload = payload.get("payload", {})
        if not isinstance(job_payload, dict):
            raise HTTPException(status_code=422, detail={"code": "validation_error", "message": "job payload must be an object"})
        job = app_job_queue.enqueue(kind, job_payload)
        return job.to_dict()

    @app.get("/ops/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return [job.to_dict() for job in app_job_queue.list()]

    @app.get("/ops/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = app_job_queue.get(job_id)
        if job is None:
            raise not_found("job", job_id)
        return job.to_dict()

    @app.post("/ops/backups", status_code=202)
    def enqueue_backup(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        job = app_job_queue.enqueue("backup", payload or {})
        return job.to_dict()

    @app.post("/ops/seed-demo", status_code=202)
    def enqueue_seed_demo() -> dict[str, Any]:
        job = app_job_queue.enqueue("seed_demo", {})
        return job.to_dict()

    return app


app = create_app()
