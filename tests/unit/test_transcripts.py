"""Video transcripts: services, versioned storage, excerpt checks, ingestion, pipeline, CLI and HTTP (offline)."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import httpx
import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import select

from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AgentRun, ERGNode, KBEntry
from seldon.workspace import transcripts as tx
from seldon.workspace.perspectives import export_graph
from seldon.workspace.pipeline import pipeline_snapshot
from seldon.workspace.reruns import list_requests, prediction_history
from seldon.workspace.schemas import WorkspaceApply
from seldon.workspace.service import WorkspaceConflict, WorkspaceService
from seldon.workspace.transcripts import providers
from seldon.workspace.transcripts.schemas import Excerpt, FetchRequest, ImportRequest, IngestRequest

VIDEO = "abcdefghijk"
URL = f"https://www.youtube.com/watch?v={VIDEO}"
SEGMENTS = [
    {"start": 0.0, "duration": 5.0, "text": "welcome back to the channel"},
    {"start": 5.0, "duration": 6.0, "text": "central banks bought more gold"},
    {"start": 11.0, "duration": 7.0, "text": "than in any year since nineteen sixty seven"},
    {"start": 18.0, "duration": 8.0, "text": "and real yields are still falling says the guest"},
    {"start": 60.0, "duration": 10.0, "text": "i expect gold to reach four thousand dollars"},
]


def fetched(segments=None, **media):
    return {
        "service": "youtube",
        "segments": copy.deepcopy(segments or SEGMENTS),
        "language": "en",
        "caption_kind": "auto-generated",
        "available": [{"language": "en", "kind": "auto-generated"}],
        "detail": "YouTube caption track",
        "media": {"platform": "youtube", "media_id": VIDEO, "url": URL, "title": "Central banks and gold", "channel": "Macro Channel", "channel_id": "UC" + "x" * 22, "channel_url": "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx", "published_at": "2026-09-01T12:00:00+00:00", "duration_seconds": 70.0, **media},
        "warnings": [],
        "attempts": [],
    }


def offline(*args, **kwargs):
    raise AssertionError("Transcript tests must not reach the network")


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx.Client, "send", offline)
    monkeypatch.setattr(requests.Session, "send", offline)
    monkeypatch.setattr(providers, "retrieve", lambda *a, **k: fetched())
    engine = make_engine(sqlite_path=tmp_path / "transcripts.db")
    create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


def start(factory, question="Where will gold be in 6 months?"):
    with factory() as db, db.begin():
        return WorkspaceService(db).start(question, "2027-03-28")["scenario"]["id"]


def export(factory, sid):
    with factory() as db:
        return WorkspaceService(db).export(sid)


def fetch(factory, **values):
    with factory() as db, db.begin():
        return tx.fetch_transcript(db, FetchRequest(url=URL, **values))


def run_ingest(factory, payload):
    with factory() as db, db.begin():
        return tx.ingest(db, IngestRequest.model_validate(payload))


def ingest_payload(factory, sid, tid, **extra):
    return {
        "transcript_id": tid,
        "scenario_id": sid,
        "base_revision": export(factory, sid)["revision"],
        "request_id": "video-1",
        "agent": "test-agent",
        "reason": "Excerpts from a macro video",
        "excerpts": [
            {"id": "cb-buying", "start": "0:05", "end": 18, "content": "The host reports record central-bank gold buying.", "quote": "Central banks bought more gold, than in any year", "speaker": "Host", "confidence": 0.7},
            {"id": "guest-yields", "start": 18, "content": "The guest says real yields are falling.", "confidence": 0.6},
        ],
        "nodes": [
            {"id": "gold", "name": "Gold price", "type": "metric", "evidence_ids": ["cb-buying"]},
            {"id": "buying", "name": "Central banks", "type": "actor", "evidence_ids": ["cb-buying"]},
            {"id": "yields", "name": "Real yields", "type": "metric", "evidence_ids": ["guest-yields"]},
        ],
        "edges": [
            {"id": "buying-gold", "source": "buying", "target": "gold", "description": "Official demand supports price", "evidence_ids": ["cb-buying"]},
            {"id": "yields-gold", "source": "yields", "target": "gold", "direction": "negative", "description": "Lower real yields reduce the opportunity cost of gold", "evidence_ids": ["guest-yields"]},
        ],
        "graph_scope": {"target_node_id": "gold", "max_depth": 3},
        **extra,
    }


# ----------------------------------------------------------------------------- services and parsing


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VIDEO}&t=42s",
    f"https://youtu.be/{VIDEO}?si=tracking",
    f"https://m.youtube.com/shorts/{VIDEO}",
    f"https://www.youtube.com/live/{VIDEO}?feature=share",
    f"https://www.youtube-nocookie.com/embed/{VIDEO}",
    VIDEO,
])
def test_youtube_urls_canonicalize(url):
    ref = providers.parse_media_url(url)
    assert (ref.platform, ref.media_id, ref.url) == ("youtube", VIDEO, URL)
    assert ref.at(754.9) == f"{URL}&t=754s"


def test_other_platforms_and_bad_urls():
    a = providers.parse_media_url("https://www.tiktok.com/@user/video/123?utm_source=x&lang=en")
    b = providers.parse_media_url("https://tiktok.com/@user/video/123?lang=en")
    assert a.platform == "tiktok" and a.url.endswith("?lang=en") and a.media_id == b.media_id
    assert a.at(5) == a.url + "#t=5"
    for bad in ("ftp://example.org/x", "https://www.youtube.com/watch?v=short", "not a url"):
        with pytest.raises(ValueError):
            providers.parse_media_url(bad)


def test_supplied_formats_parse_to_timed_segments():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhello <c>there</c>\n\n00:00:03.000 --> 00:00:05.500\nhello there\nnew words\n"
    assert tx._clean(tx.parse_supplied(vtt, "auto")) == [{"start": 1.0, "duration": 2.0, "text": "hello there"}, {"start": 3.0, "duration": 2.5, "text": "new words"}]
    srt = "1\n00:01:02,500 --> 00:01:04,000\nFirst line\n\n2\n00:01:04,000 --> 00:01:06,000\nSecond\n"
    assert [s["start"] for s in tx.parse_supplied(srt, "auto")] == [62.5, 64.0]
    assert tx.parse_supplied(json.dumps([{"offset": 1500, "duration": 500, "text": "ms"}]), "auto")[0]["start"] == 1.5
    assert tx.parse_supplied(json.dumps({"segments": [{"start": "1:00", "text": "s"}]}), "json")[0]["start"] == 60
    panel = "0:00\nIntro words\n1:05\nlater words\nmore\n"
    inline = "[0:00] Intro words\n1:02:05 - hours later\n"
    assert tx._clean(tx.parse_supplied(panel, "auto"))[1] == {"start": 65.0, "duration": 0.0, "text": "later words more"}
    assert [s["start"] for s in tx.parse_supplied(inline, "text")] == [0.0, 3725.0]
    with pytest.raises(ValueError, match="Untimed"):
        tx.parse_supplied("just words without times", "auto")


def test_youtube_caption_selection_prefers_creator_tracks(monkeypatch):
    import youtube_transcript_api

    def track(code, generated):
        snippets = [SimpleNamespace(start=1.0, duration=2.0, text=f"{code} &amp; text"), SimpleNamespace(start=3.0, duration=1.0, text=" ")]
        return SimpleNamespace(language_code=code, language=code, is_generated=generated, fetch=lambda: SimpleNamespace(snippets=snippets))

    tracks = [track("en", True), track("de", False), track("en-GB", False)]
    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", lambda: SimpleNamespace(list=lambda vid: tracks))
    spoken = providers.youtube_captions(VIDEO, [])
    assert (spoken["language"], spoken["caption_kind"], spoken["segments"]) == ("en-GB", "manual", [{"start": 1.0, "duration": 2.0, "text": "en-GB & text"}])
    assert providers.youtube_captions(VIDEO, ["fr", "de"])["language"] == "de"
    with pytest.raises(providers.TranscriptUnavailable, match="available: de, en, en-GB"):
        providers.youtube_captions(VIDEO, ["fr"])


def test_watch_page_metadata_parsing():
    page = '"publishDate":"2026-09-01T05:00:00-07:00" "lengthSeconds":"125" "channelId":"UC' + "a" * 22 + '" "ownerChannelName":"Macro \\u0026 Co" <meta name="title" content="A &amp; B">'
    meta = providers._watch_page(page)
    assert meta["published_at"] == "2026-09-01T12:00:00+00:00" and meta["duration_seconds"] == 125
    assert meta["channel"] == "Macro & Co" and meta["title"] == "A & B" and meta["channel_url"].endswith("UC" + "a" * 22)


class Stub:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        status, body = self.responses.pop(0)
        return SimpleNamespace(status_code=status, json=lambda: body, text=json.dumps(body))


def test_supadata_sync_async_and_errors(monkeypatch):
    monkeypatch.setattr(providers, "JOB_POLL_SECONDS", 0)
    sync = Stub((200, {"content": [{"text": "hi", "offset": 1500, "duration": 1000}], "lang": "en", "availableLangs": ["en"]}))
    result = providers.supadata_transcript("https://x.com/a/status/1", ["en"], "auto", key="k", client=sync)
    assert result["segments"] == [{"start": 1.5, "duration": 1.0, "text": "hi"}] and result["caption_kind"] == "unknown"
    assert sync.calls[0][1]["lang"] == "en" and sync.calls[0][2] == {"x-api-key": "k"}
    job = Stub((202, {"jobId": "j1"}), (200, {"status": "active"}), (200, {"status": "completed", "content": [{"text": "late", "offset": 0, "duration": 2000}], "lang": "es"}))
    result = providers.supadata_transcript(URL, [], "auto", key="k", client=job)
    assert result["caption_kind"] == "ai-generated" and result["language"] == "es" and job.calls[-1][0].endswith("/transcript/j1")
    with pytest.raises(providers.TranscriptUnavailable):
        providers.supadata_transcript(URL, [], "native", key="k", client=Stub((206, {"error": "transcript-unavailable", "message": "none"})))
    with pytest.raises(providers.ServiceError, match="unauthorized"):
        providers.supadata_transcript(URL, [], "auto", key="k", client=Stub((401, {"error": "unauthorized", "message": "bad key"})))
    monkeypatch.delenv(providers.SUPADATA_KEY_ENV, raising=False)
    with pytest.raises(providers.ServiceError, match="SUPADATA_API_KEY"):
        providers.supadata_transcript(URL, [], "auto")


def test_retrieve_falls_back_only_when_configured(monkeypatch):
    def no_captions(*a):
        raise providers.TranscriptUnavailable("captions disabled")

    monkeypatch.setattr(providers, "youtube_captions", no_captions)
    monkeypatch.setattr(providers, "youtube_metadata", lambda vid: ({"title": "T"}, []))
    monkeypatch.delenv(providers.SUPADATA_KEY_ENV, raising=False)
    with pytest.raises(providers.TranscriptUnavailable, match="transcripts import"):
        providers.retrieve(URL, [], "auto", "auto")
    with pytest.raises(providers.TranscriptUnavailable, match="captions disabled"):
        providers.retrieve(URL, [], "youtube", "auto")
    with pytest.raises(ValueError):
        providers.retrieve("https://vimeo.com/1", [], "youtube", "auto")
    monkeypatch.setenv(providers.SUPADATA_KEY_ENV, "k")
    monkeypatch.setattr(providers, "supadata_transcript", lambda url, langs, mode: {"service": "supadata", "segments": [{"start": 0, "duration": 1, "text": "x"}], "language": "en", "caption_kind": "ai-generated"})
    result = providers.retrieve(URL, [], "auto", "auto")
    assert result["service"] == "supadata" and result["attempts"] == ["youtube: captions disabled"] and result["media"]["title"] == "T"


# ----------------------------------------------------------------------------- storage


def test_fetch_versions_replays_and_conflicts(factory, monkeypatch):
    first = fetch(factory, request_id="f1")
    assert first["recorded"] and first["changed"] and first["version"] == 1 and first["caption_kind"] == "auto-generated"
    assert fetch(factory, request_id="f1")["replayed"]
    with pytest.raises(WorkspaceConflict):
        fetch(factory, request_id="f1", languages=["en"])
    unchanged = fetch(factory)
    assert not unchanged["recorded"] and unchanged["version"] == 1
    monkeypatch.setattr(providers, "retrieve", lambda *a, **k: fetched(SEGMENTS[:-1] + [{"start": 60.0, "duration": 10.0, "text": "i expect gold to reach five thousand dollars"}]))
    second = fetch(factory)
    assert second["changed"] and second["version"] == 2 and second["versions"] == 2
    with factory() as db:
        state = tx.load_state(db)
        assert tx.transcript_view(state, first["transcript_id"], version=1)["transcript"][-1]["text"].endswith("four thousand dollars")
        assert tx.transcript_view(state, first["transcript_id"], start="0:50")["transcript"][0]["text"].endswith("five thousand dollars")
        with pytest.raises(KeyError):
            tx.get_version(state, first["transcript_id"], 3)
        assert len(tx.list_transcripts(db)["transcripts"]) == 1


def test_import_supplied_transcript(factory):
    with factory() as db, db.begin():
        result = tx.import_transcript(db, ImportRequest(url=f"https://youtu.be/{VIDEO}", content="0:00\nhello\n0:04\nworld\n", caption_kind="manual", title="Supplied", obtained_from="Copied from the YouTube transcript panel", request_id="imp"))
    assert result["service"] == "supplied" and result["media"]["title"] == "Supplied" and result["warnings"]
    with factory() as db, db.begin():
        assert tx.import_transcript(db, ImportRequest(url=f"https://youtu.be/{VIDEO}", content="0:00\nhello\n0:04\nworld\n", caption_kind="manual", title="Supplied", obtained_from="Copied from the YouTube transcript panel", request_id="imp"))["replayed"]
    with pytest.raises(ValueError):
        ImportRequest(url=URL, content="x", segments=[{"start": 0, "text": "y"}])


def test_fetch_for_a_question_updates_its_pipeline(factory):
    sid = start(factory)
    other = start(factory, "Unrelated question")
    with factory() as db:
        assert "transcription" not in [s["name"] for s in pipeline_snapshot(db, sid)["stages"]]
    result = fetch(factory, scenario_id=sid)
    assert result["recorded"] and result["scenario_id"] == sid
    with factory() as db:
        stage = pipeline_snapshot(db, sid)["stages"][0]
        assert (stage["name"], stage["status"]) == ("transcription", "needs_followup") and "awaiting excerpt" in stage["latest"]["summary"]
        assert stage["latest"]["duration_s"] is not None
        assert pipeline_snapshot(db, other)["totals"]["stage_count"] == 9
    assert not fetch(factory, scenario_id=sid)["recorded"]  # already linked; no duplicate pipeline event
    with pytest.raises(KeyError):
        fetch(factory, scenario_id="missing")


# ----------------------------------------------------------------------------- ingestion


def test_ingest_creates_cited_evidence_nodes_sources_and_pipeline(factory):
    sid = start(factory)
    tid = fetch(factory, scenario_id=sid)["transcript_id"]
    payload = ingest_payload(factory, sid, tid)
    result = run_ingest(factory, payload)
    assert not result["replayed"] and result["out_of_scope_node_ids"] == [] and result["rerun"]["queued"] is False
    state = export(factory, sid)
    assert len(state["nodes"]) == 3 and len(state["edges"]) == 2
    evidence = {e["id"]: e for e in state["evidence"]}
    entry = evidence[result["ids"]["evidence"]["cb-buying"]]
    assert entry["source_url"] == URL and entry["source_name"] == "Central banks and gold — Macro Channel (YouTube)"
    assert entry["valid_from"].startswith("2026-09-01") and entry["perspective_tags"]["retrieved_at"]
    assert "(automatic captions) 0:05-0:18, Host: “Central banks bought more gold, than in any year”" in entry["content"]
    assert f"{URL}&t=5s" in entry["content"]
    assert "real yields are still falling" in evidence[result["ids"]["evidence"]["guest-yields"]]["content"]  # window text when no quote
    with factory() as db:
        stages = {s["name"]: s for s in pipeline_snapshot(db, sid)["stages"]}
        assert stages["transcription"]["status"] == "completed" and "2 timestamped excerpts" in stages["transcription"]["latest"]["summary"]
        assert all(stages[name]["status"] == "completed" for name in ("context_gathering", "extraction", "graph_construction"))
        graph = export_graph(db)
        kinds = {s["id"]: s["kind"] for s in graph["sources"]}
        assert kinds[result["sources"]["document_source_id"]] == "document" and kinds[result["sources"]["channel_source_id"]] == "publication"
        assert any(link["relationship"] == "published_by" and link["source"] == result["sources"]["document_source_id"] for link in graph["source_links"])
        claims = [c for c in graph["claims"] if result["ids"]["evidence"]["cb-buying"] in c["evidence_ids"]]
        assert claims and claims[0]["source_ids"] == [result["sources"]["document_source_id"]] and claims[0]["origin_id"] == URL
        assert tx.list_transcripts(db, sid)["transcripts"][0]["ingested_into"][0]["scenario_id"] == sid
    replay = run_ingest(factory, payload)
    assert replay["replayed"] and replay["run_id"] == result["run_id"]
    with factory() as db:
        assert len([r for r in db.scalars(select(AgentRun).where(AgentRun.phase == "external_workspace"))]) == 1
    with pytest.raises(WorkspaceConflict):
        run_ingest(factory, {**payload, "reason": "changed"})


@pytest.mark.parametrize("change, message", [
    (lambda p: p["excerpts"][0].update(quote="gold fell sharply"), "quote does not occur"),
    (lambda p: p["excerpts"][1].update(start="9:00", end="9:10"), "after the transcript ends"),
    (lambda p: p["excerpts"][1].update(start=40, end=50), "No transcript text"),
    (lambda p: p["nodes"][2].update(evidence_ids=[]) or p["edges"][1].update(evidence_ids=["cb-buying"]), "not attached"),
    (lambda p: p["edges"].append({"id": "loop", "source": "gold", "target": "buying", "description": "cycle", "evidence_ids": ["cb-buying"]}), "DAG"),
])
def test_bad_ingest_rolls_back(factory, change, message):
    sid = start(factory)
    tid = fetch(factory)["transcript_id"]
    before = export(factory, sid)["revision"]
    payload = ingest_payload(factory, sid, tid)
    change(payload)
    with pytest.raises(ValueError, match=message):
        run_ingest(factory, payload)
    assert export(factory, sid)["revision"] == before
    with factory() as db:
        assert db.scalar(select(KBEntry.id).limit(1)) is None and not export_graph(db)["sources"]


def test_excerpt_window_validation():
    assert Excerpt(id="a", start="1:02:03", content="x", confidence=0.5).end == 3753
    for values in ({"start": 10, "end": 5}, {"start": 0, "end": 601}, {"start": "ten"}):
        with pytest.raises(ValueError):
            Excerpt(id="a", content="x", confidence=0.5, **values)


def test_stale_revision_is_rejected(factory):
    sid = start(factory)
    tid = fetch(factory)["transcript_id"]
    payload = ingest_payload(factory, sid, tid)
    payload["base_revision"] = "stale"
    with pytest.raises(WorkspaceConflict):
        run_ingest(factory, payload)


def forecast(factory, sid):
    state = export(factory, sid)
    ids = [n["id"] for n in state["nodes"]]
    evidence = {n["id"]: n["kb_entry_ids"][0] for n in state["nodes"]}
    target = next(n["id"] for n in state["nodes"] if n["name"] == "Gold price")
    payload = {
        "scenario_id": sid, "base_revision": state["revision"], "request_id": "forecast-1", "agent": "test-agent", "reason": "Forecast",
        "research_round": {"queries": ["video review"], "checked_node_ids": ids, "new_information": False, "stop_reason": "exhausted", "summary": "Reviewed"},
        "forecast": {
            "target_node_id": target, "as_of": "2026-10-01T00:00:00Z", "resolution_date": "2027-03-28", "units": "USD/oz", "statement": "Gold forecast",
            "resolution_criteria": "LBMA PM price", "confidence": 0.4, "synthesis": "Drivers feed price", "base_rate": "None established",
            "assumptions": ["Fixture"], "red_team": ["Reversal"], "uncertainties": ["Captions may be wrong"],
            "branches": [{"key": "up", "probability": 0.6, "outcome": "Higher", "rationale": "Demand"}, {"key": "down", "probability": 0.4, "outcome": "Lower", "rationale": "Yields"}],
            "node_assessments": [{"node_id": id, "forecast": "Stable", "rationale": "Video", "evidence_ids": [evidence[id]]} for id in ids],
        },
    }
    with factory() as db, db.begin():
        return WorkspaceService(db).apply(WorkspaceApply.model_validate(payload))


def test_attach_appends_evidence_and_queues_one_rerun(factory, monkeypatch):
    sid = start(factory)
    tid = fetch(factory)["transcript_id"]
    first = run_ingest(factory, ingest_payload(factory, sid, tid))
    forecast(factory, sid)
    buying = first["ids"]["node"]["buying"]
    old_evidence = first["ids"]["evidence"]["cb-buying"]
    later = {
        "transcript_id": tid, "scenario_id": sid, "base_revision": export(factory, sid)["revision"], "request_id": "video-2", "agent": "test-agent", "reason": "Add the guest's price call",
        "excerpts": [{"id": "price-call", "start": "1:00", "content": "The guest predicts gold at $4,000 (an opinion, not an outcome).", "quote": "I expect gold to reach four thousand dollars", "kind": "assumption", "confidence": 0.8}],
        "attach": [{"id": "buying", "evidence_ids": ["price-call"]}],
    }
    result = run_ingest(factory, later)
    with factory() as db:
        node = db.get(ERGNode, buying)
        assert node.kb_entry_ids == [old_evidence, result["ids"]["evidence"]["price-call"]] and node.name == "Central banks"
        assert prediction_history(db, sid)[-1]["knowledge_changed"] is True
    assert result["rerun"]["queued"] is True
    with factory() as db:
        pending = [r for r in list_requests(db, sid) if r["status"] == "pending"]
        assert len(pending) == 1 and pending[0]["id"] == result["rerun"]["request_id"]
        assert pending[0]["input"]["request_id"] == "transcript-video-2" and "Central banks and gold" in pending[0]["input"]["reason"]
    again = {**later, "request_id": "video-3", "base_revision": export(factory, sid)["revision"], "excerpts": [{**later["excerpts"][0], "id": "price-call-2"}], "attach": [{"id": "buying", "evidence_ids": ["price-call-2"]}]}
    assert run_ingest(factory, again)["rerun"] == {"queued": False, "reason": "A forecast refresh is already pending", "pending_request_id": pending[0]["id"]}
    never = {**again, "request_id": "video-4", "base_revision": export(factory, sid)["revision"], "excerpts": [{**later["excerpts"][0], "id": "price-call-3"}], "attach": [{"id": "buying", "evidence_ids": ["price-call-3"]}], "queue_rerun": "never"}
    assert run_ingest(factory, never)["rerun"]["queued"] is False
    with pytest.raises(ValueError, match="Attach target not found"):
        run_ingest(factory, {**never, "request_id": "video-5", "base_revision": export(factory, sid)["revision"], "attach": [{"id": "missing", "evidence_ids": ["price-call-3"]}]})


def test_disconnected_entities_are_flagged(factory):
    sid = start(factory)
    tid = fetch(factory)["transcript_id"]
    payload = ingest_payload(factory, sid, tid)
    payload["nodes"].append({"id": "aside", "name": "Channel sponsor", "type": "entity", "evidence_ids": ["guest-yields"]})
    result = run_ingest(factory, payload)
    assert result["out_of_scope_node_ids"] == [result["ids"]["node"]["aside"]] and "outside the question's dependency scope" in result["warnings"][-1]


def test_mentions_find_shared_entities_and_their_questions(factory):
    sid = start(factory)
    tid = fetch(factory)["transcript_id"]
    run_ingest(factory, ingest_payload(factory, sid, tid))
    with factory() as db, db.begin():
        db.add(ERGNode(name="US", type="entity", scenario_ids=[sid]))
    with factory() as db:
        found = tx.mentions(db, tid)
    names = {e["name"]: e for e in found["entities"]}
    assert names["Central banks"]["mentions"] == 1 and names["Central banks"]["at"] == ["0:05"] and names["Real yields"]["first_link"] == f"{URL}&t=18s"
    assert "US" not in names and "Gold price" not in names
    assert found["scenarios"][0]["scenario_id"] == sid and found["scenarios"][0]["matched_entities"] == 2


# ----------------------------------------------------------------------------- interfaces


def test_cli_roundtrip(tmp_path, capsys, monkeypatch):
    from seldon.cli import main

    monkeypatch.setattr(httpx.Client, "send", offline)
    monkeypatch.setattr(requests.Session, "send", offline)
    monkeypatch.setattr(providers, "retrieve", lambda *a, **k: fetched())
    db = str(tmp_path / "cli.db")

    def run(*args):
        assert main(["research", "--db", db, *args]) == 0
        out = capsys.readouterr().out
        return json.loads(out) if out.lstrip().startswith(("{", "[")) else out

    assert "supadata" in run("transcripts", "catalog")["services"]
    assert "excerpts" in run("transcripts", "schema")["properties"]
    assert "content" in run("transcripts", "schema", "--part", "import")["properties"]
    sid = run("start", "Where will gold be?", "--horizon", "2027-03-28")["scenario"]["id"]
    tid = run("transcripts", "fetch", URL, "--scenario", sid, "--request-id", "cli-fetch")["transcript_id"]
    vtt = tmp_path / "talk.vtt"
    vtt.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nsupplied words\n")
    imported = run("transcripts", "import", str(vtt), "--url", "https://vimeo.com/42", "--title", "Talk", "--published-at", "2026-08-01T00:00:00Z")
    assert imported["media"]["platform"] == "vimeo" and imported["service"] == "supplied"
    assert len(run("transcripts", "list")["transcripts"]) == 2 and len(run("transcripts", "list", "--scenario", sid)["transcripts"]) == 1
    markdown = run("transcripts", "show", tid, "--from", "0:12")
    assert markdown.startswith("# Central banks and gold") and f"[0:11]({URL}&t=11s)" in markdown and "welcome back" not in markdown
    assert run("transcripts", "show", tid, "--format", "json")["segments"] == len(SEGMENTS)
    assert run("transcripts", "mentions", tid)["entity_total"] == 0
    revision = run("export", sid)["revision"]
    body = tmp_path / "ingest.json"
    body.write_text(json.dumps({
        "transcript_id": tid, "scenario_id": sid, "base_revision": revision, "request_id": "cli-ingest", "agent": "cli", "reason": "CLI ingest",
        "excerpts": [{"id": "e1", "start": 5, "content": "Host reports buying.", "confidence": 0.5}],
        "nodes": [{"id": "gold", "name": "Gold price", "type": "metric", "evidence_ids": ["e1"]}],
    }))
    out = tmp_path / "result.json"
    assert main(["research", "--db", db, "transcripts", "ingest", str(body), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["transcript_id"] == tid
    capsys.readouterr()
    assert run("pipeline", sid)["stages"][0]["status"] == "completed"
    assert main(["research", "--db", db, "transcripts", "show", "missing"]) == 1
    assert "Transcript not found" in capsys.readouterr().err


def test_http_routes(tmp_path, monkeypatch):
    from seldon.api.app import create_app
    from seldon.config import SeldonConfig

    monkeypatch.setattr(requests.Session, "send", offline)
    monkeypatch.setattr(providers, "retrieve", lambda *a, **k: fetched())
    engine = make_engine(sqlite_path=tmp_path / "api.db")
    create_all(engine)
    client = TestClient(create_app(SeldonConfig(data_dir=tmp_path), session_factory=make_session_factory(engine)))
    assert client.get("/workspace/transcripts/catalog").json()["caption_kinds"]["auto-generated"]
    assert client.get("/workspace/transcripts/schema", params={"part": "fetch"}).json()["properties"]["service"]
    assert client.get("/workspace/transcripts/schema", params={"part": "nope"}).status_code == 422
    sid = client.post("/workspace/scenarios", json={"question": "Gold?", "horizon": "2027-03-28"}).json()["scenario"]["id"]
    created = client.post("/workspace/transcripts/fetch", json={"url": URL, "scenario_id": sid})
    assert created.status_code == 201, created.text
    tid = created.json()["transcript_id"]
    assert client.post("/workspace/transcripts/fetch", json={"url": "ftp://bad"}).status_code == 422
    assert client.post("/workspace/transcripts/fetch", json={"url": URL, "scenario_id": "missing"}).status_code == 404

    def down(*a, **k):
        raise providers.ServiceError("YouTube blocked this address")

    monkeypatch.setattr(providers, "retrieve", down)
    assert client.post("/workspace/transcripts/fetch", json={"url": URL}).status_code == 502
    assert client.post("/workspace/transcripts/import", json={"url": URL, "content": "0:01 words"}).status_code == 201
    assert client.get("/workspace/transcripts", params={"scenario_id": sid}).json()["transcripts"][0]["transcript_id"] == tid
    shown = client.get(f"/workspace/transcripts/{tid}", params={"format": "markdown", "start": "0:15"})
    assert shown.status_code == 200 and shown.headers["content-type"].startswith("text/markdown") and "real yields" in shown.text
    assert client.get(f"/workspace/transcripts/{tid}").json()["transcript"][0]["text"] == "welcome back to the channel"
    assert client.get("/workspace/transcripts/missing").status_code == 404
    assert client.get(f"/workspace/transcripts/{tid}/mentions").status_code == 200
    body = {
        "transcript_id": tid, "scenario_id": sid, "base_revision": client.get(f"/workspace/scenarios/{sid}").json()["revision"], "request_id": "http-ingest", "agent": "api", "reason": "HTTP ingest",
        "excerpts": [{"id": "e1", "start": 5, "quote": "central banks bought more gold", "content": "Host reports buying.", "confidence": 0.5}],
        "nodes": [{"id": "gold", "name": "Gold price", "type": "metric", "evidence_ids": ["e1"]}],
    }
    assert client.post("/workspace/transcripts/ingest", json={**body, "excerpts": [{**body["excerpts"][0], "quote": "invented"}]}).status_code == 422
    ok = client.post("/workspace/transcripts/ingest", json=body)
    assert ok.status_code == 200, ok.text
    assert client.post("/workspace/transcripts/ingest", json=body).json()["replayed"]
    assert client.post("/workspace/transcripts/ingest", json={**body, "reason": "different"}).status_code == 409
    pipeline = client.get("/workspace/pipeline", params={"scenario_id": sid}).json()
    assert pipeline["stages"][0]["name"] == "transcription" and pipeline["stages"][0]["status"] == "completed"
    assert "seldon-transcripts" in client.get(f"/workspace/scenarios/{sid}").json()["research_handoff"]
