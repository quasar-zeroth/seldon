"""Immutable summary/detailed report bundles in the shared database, without a provider."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, StringConstraints
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from seldon.data.models import AgentRun, Scenario
from .schemas import Contract
from .service import WorkspaceConflict, WorkspaceService

PHASE = "research_report"


class ReportFile(Contract):
    """Generated files can contain the complete accumulated research history."""
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
    media_type: Literal["text/csv", "application/json", "text/plain", "text/markdown"]
    content: Annotated[str, StringConstraints(strip_whitespace=False)]


class ReportAttachment(ReportFile):
    """Keep submitted attachments bounded independently of generated reports."""
    content: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(
        max_length=3_000_000
    )


class ReportSection(Contract):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=250_000)
    evidence_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)


class ReportRequest(Contract):
    request_id: str = Field(min_length=1, max_length=128)
    expected_revision: str | None = None
    title: str | None = Field(default=None, max_length=255)
    summary: str | None = Field(default=None, max_length=30_000)
    sections: list[ReportSection] = Field(default_factory=list, max_length=50)
    attachments: list[ReportAttachment] = Field(default_factory=list, max_length=10)


def _time(value) -> str:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()


def metadata(run: AgentRun) -> dict:
    out = run.output or {}
    return {
        "id": run.id,
        "scenario_id": run.input["scenario_id"],
        "title": out["title"],
        "created_at": _time(run.created_at),
        "knowledge_revision": out["knowledge_revision"],
        "source_revision": out["source_revision"],
        "counts": out["counts"],
        "files": [
            {
                "name": name,
                "media_type": f["media_type"],
                "bytes": len(f["content"].encode()),
                "sha256": f["sha256"],
            }
            for name, f in out["files"].items()
        ],
    }


def get_report(db: Session, report_id: str) -> AgentRun:
    run = db.get(AgentRun, report_id)
    if not run or run.phase != PHASE or run.status != "completed":
        raise KeyError("Report not found")
    return run


def list_reports(db: Session, scenario_id: str | None = None) -> list[dict]:
    rows = db.scalars(
        select(AgentRun)
        .where(AgentRun.phase == PHASE, AgentRun.status == "completed")
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
    )
    return [
        metadata(r)
        for r in rows
        if scenario_id is None or r.input.get("scenario_id") == scenario_id
    ]


def report_file(db: Session, report_id: str, name: str) -> dict:
    files = (get_report(db, report_id).output or {})["files"]
    if name not in files:
        raise KeyError("Report file not found")
    return files[name]


def generate_report(db: Session, scenario_id: str, request: ReportRequest) -> dict:
    # Serialize requests for this scenario, including concurrent HTTP/CLI callers.
    db.execute(
        update(Scenario)
        .where(Scenario.id == scenario_id)
        .values(updated_at=Scenario.updated_at)
    )
    rid = str(uuid5(NAMESPACE_URL, f"seldon/report/{scenario_id}/{request.request_id}"))
    fingerprint = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
    existing = db.get(AgentRun, rid)
    if existing:
        if existing.input.get("request_hash") != fingerprint:
            raise WorkspaceConflict(
                "Report request_id was already used for different input"
            )
        return {**metadata(existing), "replayed": True}
    w = WorkspaceService(db).export(scenario_id)
    if request.expected_revision and request.expected_revision != w["revision"]:
        raise WorkspaceConflict(
            "Research changed; refresh before generating the report"
        )
    evidence = {e["id"]: e for e in w["evidence"]}
    nodes = {n["id"]: n for n in w["nodes"]}
    for section in request.sections:
        if set(section.evidence_ids) - set(evidence) or set(section.node_ids) - set(
            nodes
        ):
            raise ValueError(
                "Report sections must cite evidence/entities in the current research scope"
            )
    filenames = [a.name for a in request.attachments]
    if len(set(filenames)) != len(filenames) or {"summary.md", "detailed.md"} & set(
        filenames
    ):
        raise ValueError(
            "Attachment names must be unique and cannot replace report files"
        )
    title = request.title or w["scenario"]["name"]
    now = datetime.now(timezone.utc)
    rounds = [
        (
            r,
            (r.get("output") or {}).get("research_round")
            or r["input"].get("research_round"),
        )
        for r in w["runs"]
    ]
    rounds = [(r, review) for r, review in rounds if review]
    latest = rounds[-1][1] if rounds else {}
    lines = [
        f"# {title}",
        "",
        f"Question: {w['scenario']['target_question']}",
        "",
        f"Horizon / as-of scope: {w['scenario']['time_horizon']}",
        f"Generated: {now.isoformat()}",
        f"Knowledge revision: {w['knowledge_revision']}",
        "",
        "## Executive summary",
        "",
        request.summary
        or latest.get("summary")
        or "No research synthesis has been recorded yet.",
        "",
        f"Coverage: {len(nodes)} scoped entities; {len(w['edges'])} relationships; {len(evidence)} evidence records. Upstream depth: {w['graph_scope']['max_depth']}.",
        "",
        "This is a saved snapshot of recorded research. Report generation does not perform new searches or independently verify the underlying claims.",
        "",
    ]
    if w["predictions"]:
        lines += [
            "## Saved forecasts",
            "",
            "Probabilities are agent judgments; statistical calibration has not been established.",
            "",
        ]
        for p in w["predictions"]:
            as_of = ((p.get("calibration_result") or {}).get("forecast") or {}).get("as_of") or p.get("created_at", "Unknown")
            lines += [
                f"### {p['statement']}",
                f"Forecast recorded as of: {as_of}. Prediction ID: {p['id']}.",
                f"Resolution: {p['timeframe']}. Full resolution rules and reasoning are in the detailed report.",
                "",
            ]
            for branch in p["scenarios"]:
                prob = branch.get("probability")
                probability = (
                    f"{prob:.0%}" if isinstance(prob, (int, float)) else "unspecified"
                )
                lines.append(
                    f"- {branch.get('key', 'Scenario')}: {probability} — {branch.get('outcome', '')}"
                )
            lines.append("")
    else:
        lines += ["No probabilistic forecast has been recorded for this research.", ""]
    lines += [
        "## Limits and remaining questions",
        "",
        f"Research stopping decision: {latest.get('stop_reason', 'No research round recorded')}",
        "",
    ]
    lines += ["- " + gap for gap in latest.get("remaining_gaps", [])] or [
        "No explicit gaps recorded; this is not proof of complete coverage."
    ]
    perspectives = w.get("perspectives") or {}
    if perspectives.get("claims"):
        lines += ["", "## Claim and source review", "", f"{len(perspectives['claims'])} attributed claims and {len(perspectives['assessments'])} dated assessments are attached to this snapshot. Imported observations are not automatically verified facts. Trust percentages are subjective judgments, not calibrated probabilities. Conflicting claims, corrections, provenance and assessment history appear in the detailed report.", ""]
    summary = "\n".join(lines) + "\n"
    detailed = list(lines)
    for section in request.sections:
        detailed += ["", "## " + section.title, "", section.body, ""]
        for eid in section.evidence_ids:
            e = evidence[eid]
            detailed.append(
                f"- Source {eid}: {e['source_name']} — {e.get('source_url') or 'Explicit assumption'}"
            )
        if section.node_ids:
            detailed.append(
                "Entities: " + ", ".join(nodes[nid]["name"] for nid in section.node_ids)
            )
    detailed += ["", "## Entities and research aspects", ""]
    for n in sorted(nodes.values(), key=lambda n: n["name"].casefold()):
        detailed += [
            "### " + n["name"],
            "",
            "Tags: " + ", ".join(n.get("tags") or []),
            "",
            n["description"],
            "",
            n["current_state"] or "Unknown; requires research.",
            "",
            "Evidence IDs: " + ", ".join(n["kb_entry_ids"]),
            "",
        ]
    detailed += ["## Dependencies and assumptions", ""]
    for edge in w["edges"]:
        detailed.append(
            f"- {nodes[edge['source_node_id']]['name']} → {nodes[edge['target_node_id']]['name']}: {edge['description']} (direction: {edge['direction']}; evidence: {', '.join(edge['evidence_kb_ids'])})"
        )
    detailed += ["", "## Sources and provenance", ""]
    for eid, e in evidence.items():
        detailed += [
            f"### {e['source_name']} [{eid}]",
            f"URL: {e.get('source_url') or 'No external source; see kind'}",
            f"Kind: {e['source_type']}; published: {e.get('valid_from') or 'Unknown'}; retrieved: {(e.get('perspective_tags') or {}).get('retrieved_at', 'Not recorded')}",
            "",
            e["content"],
            "",
        ]
    detailed += ["## Research history", ""]
    for run, review in rounds:
        detailed += [
            f"### {run['created_at']} — {run['agent_id']}",
            review["summary"],
            "Queries: " + "; ".join(review.get("queries", [])),
            "Stopping decision: " + review["stop_reason"],
            "",
        ]
    # Keep all per-node forecasts and review arguments, including assumptions and counterevidence.
    for prediction in w["predictions"]:
        detailed += [
            "## Forecast reasoning and review",
            "",
            prediction["statement"],
            "",
            f"Resolution: {prediction['timeframe']}",
            prediction["resolution_criteria"],
            "",
            "```json",
            json.dumps(
                prediction.get("calibration_result") or {}, indent=2, ensure_ascii=False
            ),
            "```",
            "",
        ]
    if perspectives.get("claims"):
        detailed += ["## Attributed claims, source affiliations and assessment history", "", "```json", json.dumps(perspectives, indent=2, ensure_ascii=False), "```", ""]
    contents = [
        ReportFile(
            name="summary.md", media_type="text/markdown", content=summary
        ),
        ReportFile(
            name="detailed.md",
            media_type="text/markdown",
            content="\n".join(detailed) + "\n",
        ),
        *request.attachments,
    ]
    files = {
        a.name: {
            "media_type": a.media_type,
            "content": a.content,
            "sha256": hashlib.sha256(a.content.encode()).hexdigest(),
        }
        for a in contents
    }
    run = AgentRun(
        id=rid,
        agent_id="research_report_generator",
        phase=PHASE,
        status="completed",
        input={
            "scenario_id": scenario_id,
            "request_id": request.request_id,
            "request_hash": fingerprint,
        },
        output={
            "title": title,
            "source_revision": w["revision"],
            "knowledge_revision": w["knowledge_revision"],
            "counts": {
                "nodes": len(nodes),
                "evidence": len(evidence),
                "predictions": len(w["predictions"]),
            },
            "files": files,
        },
        created_at=now,
    )
    db.add(run)
    db.flush()
    return {**metadata(run), "replayed": False}
