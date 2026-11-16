"""One research-stage view over durable Python-agent and external-agent runs.

This is a projection of recorded work, never a scheduler or a claim that an
unrecorded stage ran. Historical workspace runs already contain the inputs and
outputs needed to recover their stage history without rewriting the database.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from seldon.data.models import (
    AgentRun,
    ERGEdge,
    ERGNode,
    KBEntry,
    Scenario,
    ScenarioPrediction,
)
from seldon.data.repositories import row_to_dict

STAGES = (
    ("transcription", "Video transcripts"),
    ("context_gathering", "Research & evidence"),
    ("extraction", "Entity extraction"),
    ("graph_construction", "Dependency graph"),
    ("convergence", "Research convergence"),
    ("node_prediction", "Node forecasts"),
    ("simulation", "Graph reasoning"),
    ("synthesis", "Scenario synthesis"),
    ("review", "Base rates & adversarial review"),
    ("prediction", "Saved prediction"),
)
# Shown only once a question has recorded work for them, so other questions keep their stage counts.
OPTIONAL_STAGES = {"transcription"}
TRANSCRIPT_PHASE = "media_transcript"

AGENT_STAGES = {
    "node_state_predictor": "node_prediction",
    "graph_traversal_simulator": "simulation",
    "scenario_synthesizer": "synthesis",
    "prediction_base_rate_anchorer": "review",
    "instability_analyzer": "review",
    "adversarial_red_team": "review",
    "adversarial_red_team_agent": "review",
    "uncertainty_quantification_layer": "review",
    "base_rate_anchorer": "review",
}


def workspace_steps(request: dict, output: dict) -> list[dict]:
    """Describe only work supplied and accepted in this workspace transaction."""
    steps = []

    def add(stage, summary, result, status="completed"):
        steps.append(
            {"stage": stage, "status": status, "summary": summary, "result": result}
        )

    for media in request.get("media") or []:
        excerpts = media.get("excerpts", [])
        add(
            "transcription",
            f"{len(excerpts)} timestamped excerpts from '{media.get('title') or media.get('url')}' "
            f"({media.get('service')}, {media.get('caption_kind')}, {media.get('language')}); "
            f"{media.get('covered_seconds')} of {media.get('duration_seconds')} seconds cited",
            media,
        )
    research = output.get("research_round") or request.get("research_round") or {}
    if (
        request.get("evidence")
        or research.get("queries")
        or research.get("sources_consulted")
    ):
        add(
            "context_gathering",
            f"{len(request.get('evidence', []))} evidence updates; {len(research.get('queries', []))} research queries",
            {
                "evidence": request.get("evidence", []),
                "queries": research.get("queries", []),
                "sources": research.get("sources_consulted", []),
            },
        )
    if request.get("nodes"):
        add(
            "extraction",
            f"{len(request['nodes'])} entity updates",
            {"nodes": request["nodes"]},
        )
    if any(
        request.get(key) for key in ("nodes", "edges", "detach_nodes", "detach_edges")
    ):
        add(
            "graph_construction",
            f"DAG validated; {len(request.get('edges', []))} relationship updates",
            {
                "edges": request.get("edges", []),
                "detached": output.get("detached", {}),
                "topological_order": output.get("topological_order", []),
            },
        )
    if research:
        stop = research.get("stop_reason", "continue")
        add(
            "convergence",
            f"{stop}: {research.get('summary', '')}",
            research,
            "needs_followup" if stop == "continue" else "completed",
        )
    forecast = output.get("forecast") or {}
    if forecast:
        add(
            "node_prediction",
            f"{len(forecast.get('node_assessments', []))} evidence-backed node assessments",
            {"node_assessments": forecast.get("node_assessments", [])},
        )
        add(
            "simulation",
            "Upstream-to-downstream graph reasoning recorded",
            {
                "synthesis": forecast.get("synthesis"),
                "topological_order": output.get("topological_order", []),
            },
        )
        add(
            "synthesis",
            f"{len(forecast.get('branches', []))} forecast branches; probability checks passed",
            {
                "statement": forecast.get("statement"),
                "case_bounds": forecast.get("case_bounds"),
                "branches": forecast.get("branches", []),
            },
        )
        add(
            "review",
            "Base-rate anchor, counterarguments, assumptions, and uncertainty recorded",
            {
                key: forecast.get(key)
                for key in ("base_rate", "red_team", "assumptions", "uncertainties")
            },
        )
        if output.get("prediction_id"):
            add(
                "prediction",
                forecast.get("statement", "Forecast saved"),
                {
                    "prediction_id": output["prediction_id"],
                    "confidence": forecast.get("confidence"),
                    "resolution_date": forecast.get("resolution_date"),
                },
            )
    return steps


def _timestamp(value: datetime) -> str:
    return (
        value.replace(tzinfo=value.tzinfo or timezone.utc)
        .astimezone(timezone.utc)
        .isoformat()
    )


def pipeline_snapshot(
    db: Session, scenario_id: str | None = None, *, history_limit: int = 50
) -> dict:
    scenarios = list(
        db.scalars(select(Scenario).order_by(Scenario.updated_at.desc(), Scenario.id))
    )
    scenario = (
        next((s for s in scenarios if s.id == scenario_id), None)
        if scenario_id
        else next(iter(scenarios), None)
    )
    if scenario_id and scenario is None:
        raise KeyError(f"Scenario not found: {scenario_id}")
    scenario_id = scenario.id if scenario else None
    runs = list(db.scalars(select(AgentRun).order_by(AgentRun.updated_at, AgentRun.id)))
    by_id = {r.id: r for r in runs}
    predictions = list(
        db.scalars(
            select(ScenarioPrediction).order_by(
                ScenarioPrediction.created_at, ScenarioPrediction.id
            )
        )
    )
    prediction_scenarios = {p.id: p.scenario_id for p in predictions}

    def run_scenario(run: AgentRun, seen: set[str] | None = None):
        seen = set() if seen is None else seen
        if run.id in seen:
            return None
        seen.add(run.id)
        raw = run.input or {}
        payload = raw.get("payload", raw)
        if payload.get("scenario_id"):
            return payload["scenario_id"]
        if payload.get("prediction_id") in prediction_scenarios:
            return prediction_scenarios[payload["prediction_id"]]
        parent = by_id.get(raw.get("parent_run_id") or payload.get("parent_run_id"))
        return run_scenario(parent, seen) if parent else None

    history = []
    for run in runs:
        if not scenario_id or run_scenario(run) != scenario_id:
            continue
        external = run.phase in {"external_workspace", TRANSCRIPT_PHASE}
        if run.phase == TRANSCRIPT_PHASE:
            steps = (run.output or {}).get("pipeline_steps") or []
        elif external:
            if run.status != "completed":
                continue
            steps = (run.output or {}).get("pipeline_steps")
            if steps is None:
                steps = workspace_steps(run.input or {}, run.output or {})
        else:
            stage = AGENT_STAGES.get(run.agent_id, run.phase)
            if stage not in dict(STAGES):
                continue
            steps = [
                {
                    "stage": stage,
                    "status": run.status,
                    "summary": run.error
                    or f"{run.agent_id.replace('_', ' ')}: {run.status}",
                    "result": run.output or {},
                }
            ]
        for step in steps:
            history.append(
                {
                    **step,
                    "id": f"{run.id}:{step['stage']}",
                    "run_id": run.id,
                    "agent": run.agent_id,
                    "entrypoint": "external_agent" if external else "python",
                "time": _timestamp(run.created_at if external else run.updated_at),
                    # External wall time is unknown; apply duration is not research duration.
                    # Transcript retrieval is Seldon's own network work, so its time is real.
                    "duration_s": None
                    if run.elapsed_ms is None
                    or (external and run.phase != TRANSCRIPT_PHASE)
                    else run.elapsed_ms / 1000,
                    "error": run.error,
                }
            )
    order = {key: index for index, (key, _) in enumerate(STAGES)}
    history.sort(key=lambda item: (item["time"], item["run_id"], order.get(item["stage"], 0)))
    stages = []
    for key, label in STAGES:
        matching = [item for item in history if item["stage"] == key]
        if key in OPTIONAL_STAGES and not matching:
            continue
        latest = matching[-1] if matching else {}
        stages.append(
            {
                "name": key,
                "label": label,
                "status": latest.get("status", "not_started"),
                "last_run": latest.get("time"),
                "run_count": len(matching),
                "latest": latest or None,
            }
        )

    artifacts = []
    if scenario_id:
        from .knowledge import scoped_graph

        view = scoped_graph(db, scenario_id)

        def scoped_count(model):
            return len(
                view[{KBEntry: "evidence", ERGNode: "nodes", ERGEdge: "edges"}[model]]
            )

        for kind, label, count in (
            ("evidence", "Evidence records", scoped_count(KBEntry)),
            ("nodes", "Graph entities", scoped_count(ERGNode)),
            ("edges", "Graph relationships", scoped_count(ERGEdge)),
        ):
            if count:
                artifacts.append(
                    {
                        "id": kind,
                        "kind": kind,
                        "label": label,
                        "count": count,
                        "scenario_id": scenario_id,
                    }
                )
        for prediction in predictions:
            if prediction.scenario_id == scenario_id:
                artifacts.append(
                    {
                        "id": prediction.id,
                        "kind": "prediction",
                        "label": prediction.statement,
                        "status": prediction.status,
                        "updated_at": _timestamp(prediction.updated_at),
                        "scenario_id": scenario_id,
                    }
                )
        if artifacts:
            artifacts.append(
                {
                    "id": "report",
                    "kind": "report",
                    "label": "Research report (Markdown)",
                    "scenario_id": scenario_id,
                }
            )
    totals = {
        status: sum(s["status"] == status for s in stages)
        for status in (
            "completed",
            "failed",
            "running",
            "pending",
            "not_started",
            "needs_followup",
        )
    }
    return {
        "scenario": row_to_dict(scenario) if scenario else None,
        "scenarios": [{"id": s.id, "name": s.name} for s in scenarios],
        "stages": stages,
        "totals": {**totals, "stage_count": len(stages)},
        "history": list(reversed(history))[:history_limit],
        "history_total": len(history),
        "artifacts": artifacts,
        "last_activity": history[-1]["time"] if history else None,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
