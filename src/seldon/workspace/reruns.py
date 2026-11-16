"""Durable external-agent prediction requests and immutable forecast history."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from seldon.data.models import (
    AgentRun,
    GraphSnapshot,
    Scenario,
    ScenarioPrediction,
    ScenarioVersion,
)
from seldon.data.repositories import AgentRunRepository, row_to_dict
from .knowledge import knowledge_revision, scoped_graph


def list_requests(db: Session, scenario_id: str | None = None) -> list[dict]:
    return [
        row_to_dict(row)
        for row in db.scalars(
            select(AgentRun)
            .where(AgentRun.phase == "prediction_request")
            .order_by(AgentRun.created_at.desc(), AgentRun.id)
        )
        if not scenario_id or row.input.get("scenario_id") == scenario_id
    ]


def request_prediction(
    db: Session,
    scenario_id: str,
    *,
    request_id: str,
    reason: str,
    horizon: str | None = None,
) -> dict:
    scenario = db.get(Scenario, scenario_id)
    if not scenario:
        raise KeyError(f"Scenario not found: {scenario_id}")
    id = str(
        uuid5(NAMESPACE_URL, f"seldon:prediction-request:{scenario_id}:{request_id}")
    )
    previous = db.get(AgentRun, id)
    if previous:
        if (
            previous.input.get("reason") != reason
            or previous.input.get("requested_horizon") != horizon
        ):
            raise ValueError("Request ID already used with different details")
        return row_to_dict(previous)
    view = scoped_graph(db, scenario_id)
    if not view["scope"].target_node_id or len(view["nodes"]) < 2:
        raise ValueError(
            "Set a forecast target and build its dependency graph before requesting a rerun"
        )
    requested_horizon = horizon
    horizon = horizon or scenario.time_horizon
    try:
        resolution_date = date.fromisoformat(horizon)
    except ValueError as exc:
        raise ValueError("Choose a YYYY-MM-DD resolution date for this rerun") from exc
    if resolution_date <= datetime.now(timezone.utc).date():
        raise ValueError("Choose a future resolution date for a new prediction")
    prompt = (
        f"Read AGENTS.md and docs/agent-workflow.md in Seldon. Complete prediction request {id} "
        f"for scenario {scenario_id}: {scenario.target_question}\n"
        f"Requested horizon: {horizon}. Reason: {reason}\n"
        "Use the same database as the running service (read Parallax service.json or use its Seldon HTTP API). "
        "Export the current workspace and inspect its graph_scope. Reuse shared entity UUIDs and evidence; "
        "verify dates, refresh stale facts, seek counterevidence, and research within the configured upstream depth. "
        "Record each material research round with research apply. Then submit a fresh forecast and completed "
        f"research review with prediction_request_id={id}, a new request_id and the latest base_revision. "
        "Preserve the resolution rule for comparable forecasts; disclose any change in horizon or branch meanings. "
        "Do not copy the previous probabilities without fresh reasoning. Do not use provider-backed endpoints or trade."
    )
    row = AgentRunRepository(db).create(
        id=id,
        agent_id="external_agent",
        phase="prediction_request",
        status="pending",
        input={
            "scenario_id": scenario_id,
            "request_id": request_id,
            "reason": reason,
            "requested_horizon": requested_horizon,
            "horizon": horizon,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "graph_scope": view["scope"].model_dump(),
            "knowledge_revision": knowledge_revision(view),
        },
        output={"handoff_prompt": prompt},
        actor="user",
        reason=reason,
    )
    return row_to_dict(row)


def complete_request(
    db: Session, id: str, scenario_id: str, prediction_id: str, agent: str
) -> None:
    row = db.get(AgentRun, id)
    if (
        not row
        or row.phase != "prediction_request"
        or row.input.get("scenario_id") != scenario_id
    ):
        raise ValueError("Prediction request does not belong to this scenario")
    if row.status == "completed":
        raise ValueError("Prediction request already completed")
    prediction = db.get(ScenarioPrediction, prediction_id)
    if prediction.timeframe != row.input["horizon"]:
        raise ValueError(
            "Forecast resolution date must match the prediction request horizon"
        )
    AgentRunRepository(db).update(
        id,
        status="completed",
        output={
            **(row.output or {}),
            "prediction_id": prediction_id,
            "completed_by": agent,
        },
        actor=agent,
    )


def prediction_history(db: Session, scenario_id: str) -> list[dict]:
    predictions = list(
        db.scalars(
            select(ScenarioPrediction).where(
                ScenarioPrediction.scenario_id == scenario_id
            )
        )
    )
    ids = {p.id for p in predictions}
    view_revision = knowledge_revision(scoped_graph(db, scenario_id))
    result = []
    versions = list(
        db.scalars(
            select(ScenarioVersion).order_by(
                ScenarioVersion.created_at, ScenarioVersion.id
            )
        )
    )
    for version in versions:
        if version.scenario_prediction_id not in ids:
            continue
        prediction = version.snapshot
        details = prediction.get("calibration_result") or {}
        snapshot = (
            db.get(GraphSnapshot, details["graph_snapshot_id"])
            if details.get("graph_snapshot_id")
            else None
        )
        result.append(
            {
                "id": version.id,
                "prediction_id": version.scenario_prediction_id,
                "version": version.version,
                "recorded_at": version.created_at.replace(
                    tzinfo=version.created_at.tzinfo or timezone.utc
                ).isoformat(),
                "as_of": (details.get("forecast") or {}).get("as_of")
                or details.get("as_of")
                or prediction.get("created_at"),
                "prediction": prediction,
                "graph_snapshot": snapshot.snapshot if snapshot else None,
                "knowledge_changed": details.get("knowledge_revision") != view_revision
                if details.get("knowledge_revision")
                else None,
            }
        )
    for p in predictions:
        if not any(row["prediction_id"] == p.id for row in result):
            result.append(
                {
                    "id": p.id,
                    "prediction_id": p.id,
                    "version": 1,
                    "recorded_at": p.created_at.isoformat(),
                    "as_of": p.created_at.isoformat(),
                    "prediction": row_to_dict(p),
                    "graph_snapshot": None,
                    "knowledge_changed": None,
                }
            )
    return sorted(result, key=lambda row: (row["recorded_at"], row["id"]))
