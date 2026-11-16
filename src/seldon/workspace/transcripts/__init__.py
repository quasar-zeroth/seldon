"""Video transcripts as versioned, append-only AgentRun events, and their ingestion into research.

`fetch_transcript` is the only network path (see providers.py); it runs before the
registry lock so a slow service never holds the database write lock. Ingestion is
provider-free: the calling agent chooses timestamped excerpts, entities and
relationships, and Seldon checks them against the stored transcript before
persisting them through the ordinary workspace apply transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from seldon.data.models import AgentRun, ERGEdge, ERGNode, Scenario, ScenarioPrediction, Source

from . import providers
from .catalog import CAPTION_KINDS
from .schemas import MAX_SEGMENTS, FetchRequest, ImportRequest, IngestRequest, seconds

PHASE = "media_transcript"
LOCK_ID = str(uuid5(NAMESPACE_URL, "seldon/transcripts/lock"))
NOTE = "A transcript records what a service returned for the video at retrieval time. It does not verify any statement, identify speakers or establish that a speaker's forecast is evidence of the outcome."
CAPTION_LABELS = {"manual": "creator captions", "auto-generated": "automatic captions", "ai-generated": "AI transcription", "unknown": "captions of unreported origin", "supplied": "supplied transcript"}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def stable(kind: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"seldon/transcripts/{kind}/{key}"))


def hms(value: float) -> str:
    total = int(value)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[\w']+", text.casefold().replace("’", "'")))


# ----------------------------------------------------------------------------- state


def load_state(db: Session) -> dict:
    transcripts: dict[str, dict] = {}
    history = []
    runs = sorted(db.scalars(select(AgentRun).where(AgentRun.phase == PHASE)), key=lambda r: (r.output or {}).get("sequence", 0))
    for run in runs:
        event = run.output or {}
        tid = event.get("transcript_id")
        item = transcripts.setdefault(tid, {"id": tid, "media": {}, "versions": [], "scenarios": []})
        if event.get("record"):
            record = {**event["record"], "version": event["version"], "run_id": run.id, "recorded_at": event["recorded_at"]}
            item["versions"].append(record)
            item["media"] = record["media"]
        scenario = (run.input or {}).get("scenario_id")
        if scenario and scenario not in item["scenarios"]:
            item["scenarios"].append(scenario)
        history.append({"id": run.id, "sequence": event.get("sequence"), "kind": (run.input or {}).get("kind"), "agent": run.agent_id, "transcript_id": tid, "version": event.get("version"), "changed": bool(event.get("record")), "scenario_id": scenario, "recorded_at": event.get("recorded_at")})
    revision = digest(sorted((tid, [v["hash"] for v in t["versions"]], sorted(t["scenarios"])) for tid, t in transcripts.items()))
    return {"transcripts": transcripts, "history": history, "revision": revision}


def get_version(state: dict, transcript_id: str, version: int | None = None) -> tuple[dict, dict]:
    transcript = state["transcripts"].get(transcript_id)
    if not transcript or not transcript["versions"]:
        raise KeyError(f"Transcript not found: {transcript_id}")
    versions = transcript["versions"]
    if version is None:
        return transcript, versions[-1]
    if not 1 <= version <= len(versions):
        raise KeyError(f"Transcript {transcript_id} has versions 1-{len(versions)}")
    return transcript, versions[version - 1]


def _lock(db: Session) -> None:
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if connection.dialect.name == "postgresql" else sqlite_insert
    db.execute(insert(Source).values(id=LOCK_ID, source_type="transcript_registry", name="Transcript registry revision lock", metadata_={}).on_conflict_do_nothing(index_elements=["id"]))
    db.execute(update(Source).where(Source.id == LOCK_ID).values(updated_at=Source.updated_at))


def ingested_into(db: Session, transcript_id: str | None = None) -> dict[str, list[dict]]:
    """Workspace applies that cited a transcript, keyed by transcript ID."""
    out: dict[str, list[dict]] = {}
    for run in db.scalars(select(AgentRun).where(AgentRun.phase == "external_workspace", AgentRun.status == "completed")):
        for media in (run.input or {}).get("media") or []:
            if transcript_id in (None, media.get("transcript_id")):
                out.setdefault(media["transcript_id"], []).append({"scenario_id": run.input.get("scenario_id"), "version": media.get("version"), "run_id": run.id, "excerpts": len(media.get("excerpts", []))})
    return out


# ----------------------------------------------------------------------------- parsing supplied transcripts

_CUE = re.compile(r"((?:\d+:)?\d{1,2}:\d{2}(?:[.,]\d+)?)\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}(?:[.,]\d+)?)")
_STAMP = re.compile(r"^\[?((?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?)\]?(?:\s+[-–—]?\s*(.*))?$")


def _clock(text: str) -> float:
    return seconds(text.replace(",", "."))


def parse_supplied(content: str, fmt: str) -> list[dict]:
    text = content.lstrip("﻿").strip()
    if fmt == "auto":
        if text.startswith("WEBVTT"):
            fmt = "vtt"
        elif text[:1] in "[{":
            try:
                json.loads(text)
                fmt = "json"
            except ValueError:
                fmt = "text"
        elif "-->" in text:
            fmt = "srt"
        else:
            fmt = "text"
    if fmt == "json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("segments") or data.get("content") or data.get("snippets") or []
        if not isinstance(data, list):
            raise ValueError("JSON transcripts must be a list of segments")
        out = []
        for item in data:
            if "offset" in item:  # Supadata-style milliseconds
                out.append({"start": float(item["offset"]) / 1000, "duration": float(item.get("duration") or 0) / 1000, "text": str(item.get("text", ""))})
            else:
                out.append({"start": float(seconds(item.get("start", 0))), "duration": float(item.get("duration") or 0), "text": str(item.get("text", ""))})
        return out
    if fmt in {"vtt", "srt"}:
        out, current = [], None
        for line in text.splitlines():
            cue = _CUE.search(line)
            if cue:
                start, end = _clock(cue.group(1)), _clock(cue.group(2))
                current = {"start": start, "duration": max(0.0, end - start), "text": ""}
                out.append(current)
            elif not line.strip():
                current = None
            elif current is not None:
                clean = re.sub(r"<[^>]+>", "", line).strip()
                if clean and clean not in current["text"]:
                    current["text"] = f"{current['text']} {clean}".strip()
        # Rolling automatic captions repeat the previous cue's line; keep only new words.
        deduped = []
        for seg in out:
            if deduped and seg["text"].startswith(deduped[-1]["text"]) and deduped[-1]["text"]:
                seg = {**seg, "text": seg["text"][len(deduped[-1]["text"]):].strip()}
            if seg["text"]:
                deduped.append(seg)
        return deduped
    out, pending = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        stamp = _STAMP.match(line)
        if stamp:
            pending = {"start": _clock(stamp.group(1)), "duration": 0.0, "text": (stamp.group(2) or "").strip()}
            out.append(pending)
        elif pending is not None:
            pending["text"] = f"{pending['text']} {line}".strip()
    if not out:
        raise ValueError("Untimed text cannot be cited by time; supply WebVTT, SRT, JSON segments or timestamped lines")
    return out


def _clean(segments: list[dict]) -> list[dict]:
    rows = sorted(({"start": round(float(s["start"]), 3), "duration": round(max(float(s.get("duration") or 0), 0.0), 3), "text": " ".join(str(s["text"]).split())} for s in segments if str(s.get("text", "")).strip()), key=lambda s: s["start"])
    if not rows:
        raise ValueError("The transcript has no text")
    if len(rows) > MAX_SEGMENTS:
        raise ValueError(f"Transcripts are limited to {MAX_SEGMENTS} segments")
    for row, nxt in zip(rows, rows[1:]):
        if row["duration"] == 0:
            row["duration"] = round(max(nxt["start"] - row["start"], 0.0), 3)
    return rows


# ----------------------------------------------------------------------------- writes


def _replay(db: Session, rid: str | None, fingerprint: str) -> dict | None:
    if not rid:
        return None
    old = db.get(AgentRun, rid)
    if old is None:
        return None
    if old.phase != PHASE or (old.input or {}).get("request_hash") != fingerprint:
        from ..service import WorkspaceConflict

        raise WorkspaceConflict("Transcript request_id already used for different input")
    state = load_state(db)
    return {**_summary(state, old.output["transcript_id"], old.output["version"]), "run_id": old.id, "changed": bool(old.output.get("record")), "recorded": True, "replayed": True, "scenario_id": old.input.get("scenario_id")}


def fetch_transcript(db: Session, request: FetchRequest, *, retriever=None) -> dict:
    """Retrieve from the online service, then record a new version only if something changed."""
    providers.parse_media_url(request.url)  # reject malformed links before any network call
    rid = stable("request", request.request_id) if request.request_id else None
    fingerprint = digest(request.model_dump(mode="json"))
    replay = _replay(db, rid, fingerprint)
    if replay:
        return replay
    if request.scenario_id and db.get(Scenario, request.scenario_id) is None:
        raise KeyError(f"Scenario not found: {request.scenario_id}")
    started = time.monotonic()
    fetched = (retriever or providers.retrieve)(request.url, request.languages, request.service, request.mode)
    elapsed = int((time.monotonic() - started) * 1000)
    fetched["retrieved_at"] = _now()
    params = {k: v for k, v in request.model_dump(mode="json").items() if k not in {"agent", "reason"}}
    return _store(db, kind="fetch", params=params, rid=rid, fingerprint=fingerprint, fetched=fetched, agent=request.agent, reason=request.reason, elapsed_ms=elapsed)


def import_transcript(db: Session, request: ImportRequest) -> dict:
    ref = providers.parse_media_url(request.url)
    rid = stable("request", request.request_id) if request.request_id else None
    fingerprint = digest(request.model_dump(mode="json"))
    replay = _replay(db, rid, fingerprint)
    if replay:
        return replay
    if request.scenario_id and db.get(Scenario, request.scenario_id) is None:
        raise KeyError(f"Scenario not found: {request.scenario_id}")
    raw = [s.model_dump() for s in request.segments] if request.segments else parse_supplied(request.content, request.format)
    segments = _clean(raw)
    media = {"platform": ref.platform, "media_id": ref.media_id, "url": ref.url, "title": request.title, "channel": request.channel, "channel_url": request.channel_url, "published_at": request.published_at.astimezone(timezone.utc).isoformat() if request.published_at else None, "duration_seconds": round(segments[-1]["start"] + segments[-1]["duration"], 3)}
    fetched = {
        "service": "supplied",
        "segments": segments,
        "language": request.language,
        "caption_kind": request.caption_kind,
        "detail": request.obtained_from,
        "available": [],
        "media": {k: v for k, v in media.items() if v not in (None, "")},
        "warnings": [] if request.published_at else ["Upload date unknown; supply published_at before citing excerpts in a dated forecast"],
        "attempts": [],
        "retrieved_at": (request.retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
    }
    params = {"url": request.url, "format": request.format, "scenario_id": request.scenario_id, "request_id": request.request_id, "content_sha256": digest(raw)}
    return _store(db, kind="import", params=params, rid=rid, fingerprint=fingerprint, fetched=fetched, agent=request.agent, reason=request.reason, elapsed_ms=None)


def _store(db: Session, *, kind: str, params: dict, rid: str | None, fingerprint: str, fetched: dict, agent: str, reason: str, elapsed_ms: int | None) -> dict:
    segments = _clean(fetched["segments"])
    media = fetched["media"]
    language = (fetched.get("language") or "und").lower()
    caption_kind = fetched.get("caption_kind") or "unknown"
    tid = stable("transcript", f"{media['platform']}/{media['media_id']}/{fetched['service']}/{language}/{caption_kind}")
    core = {"media": {k: media.get(k) for k in ("url", "title", "channel", "published_at")}, "language": language, "caption_kind": caption_kind, "segments": segments}
    version_hash = digest(core)
    scenario_id = params.get("scenario_id")
    _lock(db)
    replay = _replay(db, rid, fingerprint)  # a concurrent writer may have finished the same request
    if replay:
        return replay
    state = load_state(db)
    existing = state["transcripts"].get(tid)
    latest = existing["versions"][-1] if existing and existing["versions"] else None
    changed = latest is None or latest["hash"] != version_hash
    version = len(existing["versions"]) + 1 if changed and existing else 1 if changed else latest["version"]
    ingested = {row["scenario_id"] for row in ingested_into(db, tid).get(tid, []) if row["version"] == version}
    known = bool(existing and scenario_id in existing["scenarios"]) or scenario_id in ingested
    if not changed and not rid and (not scenario_id or known):
        return {**_summary(state, tid, version), "changed": False, "recorded": False, "replayed": False, "scenario_id": scenario_id, "already_ingested_into": sorted(ingested)}
    record = None
    if changed:
        record = {
            "id": tid,
            "hash": version_hash,
            "service": fetched["service"],
            "detail": fetched.get("detail"),
            "language": language,
            "caption_kind": caption_kind,
            "retrieved_at": fetched["retrieved_at"],
            "media": media,
            "segments": segments,
            "available": fetched.get("available", []),
            "warnings": fetched.get("warnings", []),
            "attempts": fetched.get("attempts", []),
        }
    run_id = rid or str(uuid4())
    sequence = len(state["history"]) + 1
    title = media.get("title") or media["url"]
    steps = []
    if scenario_id:
        done = not changed and scenario_id in ingested
        steps.append({
            "stage": "transcription",
            "status": "completed" if done else "needs_followup",
            "summary": f"{'Linked stored' if not changed else 'Fetched' if kind == 'fetch' else 'Imported'} transcript v{version} of '{title}' ({CAPTION_LABELS.get(caption_kind if fetched['service'] != 'supplied' else 'supplied')}, {language}, {hms(segments[-1]['start'] + segments[-1]['duration'])})" + ("; already ingested" if done else "; awaiting excerpt and entity extraction"),
            "result": {"transcript_id": tid, "version": version, "url": media["url"], "title": media.get("title"), "channel": media.get("channel"), "service": fetched["service"], "caption_kind": caption_kind, "language": language, "segments": len(segments), "warnings": fetched.get("warnings", [])},
        })
    db.add(AgentRun(
        id=run_id,
        agent_id=agent,
        phase=PHASE,
        status="completed",
        input={"kind": kind, **params, "request_hash": fingerprint, "reason": reason},
        output={"sequence": sequence, "recorded_at": _now(), "transcript_id": tid, "version": version, "record": record, "pipeline_steps": steps},
        source_references=[media["url"]],
        elapsed_ms=elapsed_ms,
    ))
    db.flush()
    state = load_state(db)
    return {**_summary(state, tid, version), "run_id": run_id, "changed": changed, "recorded": True, "replayed": False, "scenario_id": scenario_id, "already_ingested_into": sorted(ingested)}


# ----------------------------------------------------------------------------- views


def _summary(state: dict, tid: str, version: int | None = None) -> dict:
    transcript, row = get_version(state, tid, version)
    segments = row["segments"]
    end = segments[-1]["start"] + segments[-1]["duration"]
    kind = row["caption_kind"]
    return {
        "transcript_id": tid,
        "version": row["version"],
        "versions": len(transcript["versions"]),
        "media": row["media"],
        "service": row["service"],
        "detail": row.get("detail"),
        "language": row["language"],
        "caption_kind": kind,
        "caption_note": CAPTION_KINDS.get(kind),
        "retrieved_at": row["retrieved_at"],
        "segments": len(segments),
        "words": sum(len(s["text"].split()) for s in segments),
        "span": f"{hms(segments[0]['start'])}-{hms(end)}",
        "available_languages": sorted({a["language"] for a in row.get("available", []) if a.get("language")}),
        "warnings": row.get("warnings", []),
        "attempts": row.get("attempts", []),
        "next": f"research transcripts show {tid} --format markdown; research transcripts mentions {tid}; then research transcripts ingest FILE",
        "note": NOTE,
    }


def list_transcripts(db: Session, scenario_id: str | None = None) -> dict:
    state = load_state(db)
    uses = ingested_into(db)
    rows = []
    for tid, transcript in state["transcripts"].items():
        if not transcript["versions"]:
            continue
        ingests = uses.get(tid, [])
        if scenario_id and scenario_id not in transcript["scenarios"] and scenario_id not in {u["scenario_id"] for u in ingests}:
            continue
        summary = _summary(state, tid)
        rows.append({k: summary[k] for k in ("transcript_id", "version", "versions", "media", "service", "language", "caption_kind", "retrieved_at", "span", "words", "warnings")} | {"requested_for": transcript["scenarios"], "ingested_into": ingests})
    rows.sort(key=lambda r: r["retrieved_at"], reverse=True)
    return {"transcripts": rows, "revision": state["revision"], "history": state["history"][-50:], "note": NOTE}


def transcript_view(state: dict, tid: str, *, version: int | None = None, start=None, end=None) -> dict:
    transcript, row = get_version(state, tid, version)
    start, end = seconds(start), seconds(end)
    segments = [s for s in row["segments"] if (start is None or s["start"] + s["duration"] > start) and (end is None or s["start"] < end)]
    return {**_summary(state, tid, row["version"]), "range": {"start": start, "end": end}, "transcript": segments, "history": [{"version": v["version"], "retrieved_at": v["retrieved_at"], "service": v["service"], "hash": v["hash"]} for v in transcript["versions"]]}


def paragraphs(segments: list[dict], target: float = 45.0) -> list[dict]:
    out, current = [], None
    for seg in segments:
        if current is None:
            current = {"start": seg["start"], "end": seg["start"] + seg["duration"], "text": seg["text"]}
            out.append(current)
        else:
            current["text"] += " " + seg["text"]
            current["end"] = seg["start"] + seg["duration"]
        length = current["end"] - current["start"]
        if length >= target or (length >= target / 2 and seg["text"].rstrip().endswith((".", "?", "!"))):
            current = None
    return out


def render_markdown(view: dict) -> str:
    media = view["media"]
    ref = providers.MediaRef(media["platform"], media["media_id"], media["url"])
    lines = [
        f"# {media.get('title') or media['url']}",
        "",
        f"- Channel: {media.get('channel') or 'unknown'}",
        f"- Published: {media.get('published_at') or 'unknown'}",
        f"- URL: {media['url']}",
        f"- Transcript: {view['transcript_id']} v{view['version']} of {view['versions']}, {view['service']} ({view.get('detail') or ''}), {view['language']}, {view['caption_kind']}",
        f"- Retrieved: {view['retrieved_at']} · {view['words']} words · {view['span']}",
        "",
        f"> {view['caption_note'] or ''} {view['note']}",
        "",
    ]
    for warning in view["warnings"]:
        lines.append(f"> Warning: {warning}")
    if view["warnings"]:
        lines.append("")
    for para in paragraphs(view["transcript"]):
        lines.append(f"[{hms(para['start'])}]({ref.at(para['start'])}) {para['text']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def mentions(db: Session, tid: str, *, version: int | None = None, limit: int = 50) -> dict:
    """Lexical matches of shared entity names, to find UUIDs worth reusing. Not identity resolution."""
    if not 1 <= limit <= 500:
        raise ValueError("Mention limit must be 1-500")
    state = load_state(db)
    _, row = get_version(state, tid, version)
    words, times = [], []
    for seg in row["segments"]:
        for token in _tokens(seg["text"]):
            words.append(token)
            times.append(seg["start"])
    index: dict[tuple, list[ERGNode]] = {}
    for node in db.scalars(select(ERGNode).where(ERGNode.scenario_ids.is_not(None))):
        key = tuple(_tokens(node.name))
        if not key or len(key) > 8 or (len(key) == 1 and len(key[0]) < 3) or not node.scenario_ids:
            continue
        index.setdefault(key, []).append(node)
    lengths = sorted({len(k) for k in index})
    hits: dict[str, dict] = {}
    for i in range(len(words)):
        for n in lengths:
            key = tuple(words[i:i + n])
            for node in index.get(key, []):
                hit = hits.setdefault(node.id, {"entity_id": node.id, "name": node.name, "type": node.type, "tags": node.tags or [], "scenario_ids": node.scenario_ids or [], "mentions": 0, "at": []})
                hit["mentions"] += 1
                if len(hit["at"]) < 5 and (not hit["at"] or times[i] - hit["at"][-1] >= 30):
                    hit["at"].append(times[i])
    media = row["media"]
    ref = providers.MediaRef(media["platform"], media["media_id"], media["url"])
    entities = sorted(hits.values(), key=lambda h: (-h["mentions"], h["name"]))
    for hit in entities:
        hit["first_link"] = ref.at(hit["at"][0])
        hit["at"] = [hms(t) for t in hit["at"]]
    scenarios: dict[str, dict] = {}
    for hit in entities:
        for sid in hit["scenario_ids"]:
            row_ = scenarios.setdefault(sid, {"scenario_id": sid, "matched_entities": 0, "mentions": 0})
            row_["matched_entities"] += 1
            row_["mentions"] += hit["mentions"]
    for sid, row_ in scenarios.items():
        scenario = db.get(Scenario, sid)
        if scenario:
            row_.update(name=scenario.name, question=scenario.target_question, horizon=scenario.time_horizon)
    return {
        "transcript_id": tid,
        "version": row["version"],
        "entities": entities[:limit],
        "entity_total": len(entities),
        "scenarios": sorted(scenarios.values(), key=lambda r: (-r["matched_entities"], -r["mentions"]))[:20],
        "note": "Name matches are lexical. Confirm that the video means the same entity before reusing its UUID; absence of a match is not absence of relevance. Automatic captions often mis-spell names.",
    }


# ----------------------------------------------------------------------------- ingestion


def _excerpt_text(segments: list[dict], start: float, end: float) -> tuple[str, str]:
    """Window text, plus the window widened by one segment each side for quote tolerance."""
    hits = [i for i, s in enumerate(segments) if s["start"] < end and s["start"] + max(s["duration"], 0.01) > start]
    if not hits:
        return "", ""
    window = " ".join(segments[i]["text"] for i in hits)
    wide = " ".join(s["text"] for s in segments[max(hits[0] - 1, 0):hits[-1] + 2])
    return window, wide


def _clip(text: str, limit: int = 700) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _covered(windows: list[tuple[float, float]]) -> float:
    total, last = 0.0, None
    for start, end in sorted(windows):
        if last is None or start > last[1]:
            if last:
                total += last[1] - last[0]
            last = [start, end]
        else:
            last[1] = max(last[1], end)
    return round(total + (last[1] - last[0] if last else 0), 1)


def source_name(media: dict) -> str:
    platform = {"youtube": "YouTube", "x": "X"}.get(media["platform"], media["platform"].title())
    title = media.get("title") or f"{platform} video {media['media_id']}"
    channel = f" — {media['channel']}" if media.get("channel") else ""
    return f"{title}{channel} ({platform})"[:255]


def _attachments(db: Session, payload: IngestRequest) -> tuple[list[dict], list[dict], set[str]]:
    """Merge excerpt keys into node/edge writes, appending to existing rows for `attach`."""
    from ..service import record_id

    nodes = [n.model_dump(mode="json") for n in payload.nodes]
    edges = [e.model_dump(mode="json") for e in payload.edges]
    for row in nodes:
        if row.get("tags") is None:
            row.pop("tags", None)
    by_ref = {("node", record_id(payload.scenario_id, "node", n["id"])): n for n in nodes}
    by_ref.update({("edge", record_id(payload.scenario_id, "edge", e["id"])): e for e in edges})
    for item in payload.attach:
        kind = item.kind
        rid = record_id(payload.scenario_id, kind, item.id)
        target = by_ref.get((kind, rid))
        if target is None:
            row = db.get(ERGNode if kind == "node" else ERGEdge, rid)
            if row is None:
                raise ValueError(f"Attach target not found: {kind} {item.id}; create it under {kind}s")
            if kind == "node":
                target = {"id": row.id, "name": row.name, "type": row.type, "description": row.description or "", "current_state": row.current_state or "Unknown; research required", "evidence_ids": list(row.kb_entry_ids or [])}
                nodes.append(target)
            else:
                target = {"id": row.id, "source": row.source_node_id, "target": row.target_node_id, "relationship": row.relationship_type, "description": row.description or "Existing relationship", "direction": row.direction, "strength": row.strength, "confidence": row.confidence, "lag": row.lag, "evidence_ids": list(row.evidence_kb_ids or [])}
                edges.append(target)
            by_ref[(kind, rid)] = target
        target["evidence_ids"] = target["evidence_ids"] + [e for e in item.evidence_ids if e not in target["evidence_ids"]]
    cited = {key for row in [*nodes, *edges] for key in row["evidence_ids"]}
    return nodes, edges, cited


def ingest(db: Session, payload: IngestRequest) -> dict:
    """Persist excerpts as evidence plus the entities/relationships they support, in one apply."""
    from ..schemas import EvidenceWrite, WorkspaceApply
    from ..service import WorkspaceConflict, WorkspaceService

    service = WorkspaceService(db)
    ingest_hash = digest(payload.model_dump(mode="json"))
    # Exact replay must not depend on a transcript version fetched afterwards.
    for run in db.scalars(select(AgentRun).where(AgentRun.phase == "external_workspace")):
        if run.input.get("scenario_id") == payload.scenario_id and run.input.get("request_id") == payload.request_id:
            media = (run.input.get("media") or [{}])[0]
            if media.get("ingest_hash") != ingest_hash:
                raise WorkspaceConflict("request_id already used for different input")
            return {**run.output, "transcript_id": media["transcript_id"], "replayed": True, "revision": service.export(payload.scenario_id)["revision"]}
    state = load_state(db)
    transcript, row = get_version(state, payload.transcript_id, payload.version)
    media, segments = row["media"], row["segments"]
    ref = providers.MediaRef(media["platform"], media["media_id"], media["url"])
    end_of_media = max(media.get("duration_seconds") or 0, segments[-1]["start"] + segments[-1]["duration"])
    label = CAPTION_LABELS["supplied" if row["service"] == "supplied" else row["caption_kind"]]
    name = source_name(media)
    nodes, edges, cited = _attachments(db, payload)
    evidence, excerpts = [], []
    for ex in payload.excerpts:
        if ex.id not in cited:
            raise ValueError(f"Excerpt {ex.id} is not attached to any node or edge; cite it in nodes, edges or attach so the question can use it")
        if ex.start >= end_of_media + 1:
            raise ValueError(f"Excerpt {ex.id} starts at {hms(ex.start)}, after the transcript ends ({hms(end_of_media)})")
        window, wide = _excerpt_text(segments, ex.start, ex.end)
        if not window:
            raise ValueError(f"No transcript text between {hms(ex.start)} and {hms(ex.end)} for excerpt {ex.id}")
        if ex.quote and _norm(ex.quote) not in _norm(wide):
            raise ValueError(f"Excerpt {ex.id} quote does not occur in the transcript between {hms(ex.start)} and {hms(ex.end)}; quote the transcript text verbatim or omit quote")
        speaker = f", {ex.speaker}" if ex.speaker else ""
        quote = ex.quote or _clip(window)
        evidence.append(EvidenceWrite(
            id=ex.id,
            content=f"{ex.content}\n\nVideo transcript ({label}) {hms(ex.start)}-{hms(ex.end)}{speaker}: “{quote}” {ref.at(ex.start)}",
            kind=ex.kind,
            source_name=name,
            source_url=ref.url,
            published_at=media.get("published_at"),
            retrieved_at=row["retrieved_at"],
            confidence=ex.confidence,
        ))
        excerpts.append({"id": ex.id, "start": ex.start, "end": ex.end, "speaker": ex.speaker, "link": ref.at(ex.start)})
    apply = WorkspaceApply.model_validate({
        "scenario_id": payload.scenario_id,
        "base_revision": payload.base_revision,
        "request_id": payload.request_id,
        "agent": payload.agent,
        "reason": payload.reason,
        "graph_scope": payload.graph_scope.model_dump(mode="json") if payload.graph_scope else None,
        "reuse_node_ids": payload.reuse_node_ids,
        "reuse_edge_ids": payload.reuse_edge_ids,
        "reuse_evidence_ids": payload.reuse_evidence_ids,
        "allow_shared_updates": payload.allow_shared_updates,
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "nodes": nodes,
        "edges": edges,
        "research_round": payload.research_round.model_dump(mode="json") if payload.research_round else None,
    })
    record = {
        "transcript_id": payload.transcript_id,
        "version": row["version"],
        "transcript_hash": row["hash"],
        "ingest_hash": ingest_hash,
        "url": media["url"],
        "title": media.get("title"),
        "channel": media.get("channel"),
        "published_at": media.get("published_at"),
        "service": row["service"],
        "caption_kind": row["caption_kind"],
        "language": row["language"],
        "duration_seconds": round(end_of_media, 1),
        "covered_seconds": _covered([(e["start"], e["end"]) for e in excerpts]),
        "excerpts": excerpts,
    }
    result = service.apply(apply, media=[record])
    sources = _register_sources(db, media, name, payload.agent)
    warnings = list(row.get("warnings", []))
    from ..knowledge import scoped_graph

    view = scoped_graph(db, payload.scenario_id)
    visible = {n.id for n in view["nodes"]}
    outside = sorted(id for id in result["ids"].get("node", {}).values() if id not in visible)
    if outside:
        warnings.append(f"{len(outside)} new or updated entities are outside the question's dependency scope (no directed path to the target within max_depth); connect them or they will not inform forecasts")
    rerun = _maybe_rerun(db, payload, media)
    return {
        **result,
        "transcript_id": payload.transcript_id,
        "transcript_version": row["version"],
        "excerpts": excerpts,
        "sources": sources,
        "out_of_scope_node_ids": outside,
        "rerun": rerun,
        "warnings": warnings,
        "revision": service.export(payload.scenario_id)["revision"],
        "note": NOTE,
    }


def _register_sources(db: Session, media: dict, name: str, agent: str) -> dict:
    """Give the video and its channel distinct source identities in the perspectives graph."""
    from ..perspectives import apply_graph, export_graph
    from ..perspectives import stable as perspective_id
    from ..perspectives.schemas import PerspectiveApply

    graph = export_graph(db)
    sources = {s["id"]: s for s in graph["sources"]}
    links = {link["id"] for link in graph["source_links"]}
    document_id = perspective_id("source-name", name.casefold().strip())  # same ID the evidence indexer uses
    payload = {"sources": [], "source_links": []}
    existing = sources.get(document_id)
    if existing is None or (existing["kind"] == "unknown" and existing.get("description", "").startswith("Imported source label")):
        published = (media.get("published_at") or "")[:10]
        payload["sources"].append({**(existing or {}), "id": document_id, "name": name, "kind": "document", "url": media["url"], "description": f"Video{' published ' + published if published else ''}. Transcript excerpts are attributed statements; speakers are separate identities."})
    channel_id = None
    if media.get("channel"):
        key = media.get("channel_id") or media.get("channel_url") or media["channel"].casefold()
        channel_id = perspective_id("media-channel", f"{media['platform']}/{key}")
        if channel_id not in sources:
            payload["sources"].append({"id": channel_id, "name": media["channel"][:255], "kind": "publication", "url": media.get("channel_url"), "description": "Video channel recorded from platform metadata. Ownership, funding and leaning are unassessed."})
        link_id = perspective_id("source-link", f"{document_id}/published_by/{channel_id}")
        if link_id not in links:
            payload["source_links"].append({"id": link_id, "source": document_id, "target": channel_id, "relationship": "published_by", "rationale": "Platform metadata lists this channel as the uploader.", "citations": [media["url"]], "status": "reported"})
    if any(payload.values()):
        apply_graph(db, PerspectiveApply.model_validate({**payload, "request_id": f"transcript-sources-{digest(payload)[:40]}", "base_revision": graph["revision"], "agent": agent, "reason": "Record the video and its channel as distinct source identities"}))
    return {"document_source_id": document_id, "channel_source_id": channel_id}


def _maybe_rerun(db: Session, payload: IngestRequest, media: dict) -> dict:
    if payload.queue_rerun == "never":
        return {"queued": False, "reason": "queue_rerun=never"}
    from ..reruns import list_requests, request_prediction

    has_forecast = db.scalar(select(ScenarioPrediction.id).where(ScenarioPrediction.scenario_id == payload.scenario_id).limit(1)) is not None
    pending = [r for r in list_requests(db, payload.scenario_id) if r["status"] == "pending"]
    if payload.queue_rerun == "auto" and not has_forecast:
        return {"queued": False, "reason": "No saved forecast yet; continue research and forecast when ready"}
    if payload.queue_rerun == "auto" and pending:
        return {"queued": False, "reason": "A forecast refresh is already pending", "pending_request_id": pending[0]["id"]}
    title = media.get("title") or media["url"]
    try:
        row = request_prediction(db, payload.scenario_id, request_id=f"transcript-{payload.request_id}"[:128], reason=f"New video transcript evidence: {title}"[:500])
    except ValueError as exc:
        return {"queued": False, "reason": str(exc)}
    return {"queued": True, "request_id": row["id"], "status": row["status"], "note": "A pending request is a handoff for an agent to research and forecast; it is not a new forecast."}
