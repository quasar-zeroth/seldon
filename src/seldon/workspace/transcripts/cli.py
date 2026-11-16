"""`seldon research transcripts ...`: fetch, read and ingest video transcripts. JSON in, JSON/Markdown out."""

from __future__ import annotations

import argparse
from pathlib import Path

from .schemas import FetchRequest, ImportRequest, IngestRequest

SCHEMAS = {"fetch": FetchRequest, "import": ImportRequest, "ingest": IngestRequest}


def static(args: argparse.Namespace) -> dict:
    if args.transcripts_command == "catalog":
        from .catalog import catalog

        return catalog()
    return SCHEMAS[args.part].model_json_schema()


def run(args: argparse.Namespace, db):
    from . import fetch_transcript, import_transcript, ingest, list_transcripts, load_state, mentions, render_markdown, transcript_view

    command = args.transcripts_command
    if command == "fetch":
        return fetch_transcript(db, FetchRequest(
            url=args.url, languages=args.lang or [], service=args.service, mode=args.mode,
            scenario_id=args.scenario, request_id=args.request_id, agent=args.agent, reason=args.reason,
        ))
    if command == "import":
        return import_transcript(db, ImportRequest(
            url=args.url, content=args.file.read_text(encoding="utf-8"), format=args.format, language=args.lang,
            caption_kind=args.caption_kind, title=args.title, channel=args.channel, channel_url=args.channel_url,
            published_at=args.published_at, retrieved_at=args.retrieved_at, obtained_from=args.obtained_from,
            scenario_id=args.scenario, request_id=args.request_id, agent=args.agent, reason=args.reason,
        ))
    if command == "ingest":
        return ingest(db, IngestRequest.model_validate_json(args.file.read_text()))
    if command == "list":
        return list_transcripts(db, args.scenario)
    if command == "mentions":
        return mentions(db, args.transcript_id, version=args.version, limit=args.limit)
    view = transcript_view(load_state(db), args.transcript_id, version=args.version, start=args.start, end=args.end)
    return render_markdown(view) if args.format == "markdown" else view


def add_parser(commands) -> list[argparse.ArgumentParser]:
    transcripts = commands.add_parser("transcripts", help="Video transcripts (YouTube and others): fetch from an online service, read with timestamps, ingest excerpts as evidence and graph updates")
    sub = transcripts.add_subparsers(dest="transcripts_command", required=True)
    parsers = []

    def command(name, help):
        parser = sub.add_parser(name, help=help)
        parsers.append(parser)
        return parser

    command("catalog", help="Services, caption kinds, URL forms, import formats, excerpt rules and limits")
    schema = command("schema", help="JSON Schema for a request body")
    schema.add_argument("--part", choices=sorted(SCHEMAS), default="ingest")

    def writer(parser, default_agent, default_reason):
        parser.add_argument("--scenario", help="Research question this video was posted for; shows it in that question's pipeline")
        parser.add_argument("--request-id", help="Idempotency key; an exact repeat returns the stored result without refetching")
        parser.add_argument("--agent", default=default_agent)
        parser.add_argument("--reason", default=default_reason)

    fetch = command("fetch", help="Fetch a transcript from an online service (network); records a new version only when it changed")
    fetch.add_argument("url", help="Video URL or YouTube ID")
    fetch.add_argument("--lang", action="append", help="Preferred language code; repeat in order of preference (default: spoken language)")
    fetch.add_argument("--service", choices=["auto", "youtube", "supadata"], default="auto", help="auto: YouTube captions, then Supadata when SUPADATA_API_KEY is set")
    fetch.add_argument("--mode", choices=["native", "auto", "generate"], default="auto", help="Supadata: native captions only, captions else AI transcription, or always AI")
    writer(fetch, "transcript-fetcher", "Fetch video transcript")

    supplied = command("import", help="Store a transcript obtained elsewhere (WebVTT, SRT, JSON segments or timestamped text)")
    supplied.add_argument("file", type=Path)
    supplied.add_argument("--url", required=True, help="Media URL excerpts will cite")
    supplied.add_argument("--format", choices=["auto", "vtt", "srt", "json", "text"], default="auto")
    supplied.add_argument("--lang")
    supplied.add_argument("--caption-kind", choices=["manual", "auto-generated", "ai-generated", "unknown"], default="unknown")
    supplied.add_argument("--title")
    supplied.add_argument("--channel")
    supplied.add_argument("--channel-url")
    supplied.add_argument("--published-at", help="Upload time with timezone, e.g. 2026-11-02T14:00:00Z")
    supplied.add_argument("--retrieved-at")
    supplied.add_argument("--obtained-from", default="Supplied by the research agent", help="How and where the text was obtained")
    writer(supplied, "transcript-importer", "Import supplied video transcript")

    listing = command("list", help="Stored transcripts, versions, and the questions they were requested for or ingested into")
    listing.add_argument("--scenario")

    show = command("show", help="Read a transcript with timestamped deep links")
    show.add_argument("transcript_id")
    show.add_argument("--version", type=int)
    show.add_argument("--from", dest="start", help="Start time (seconds or [h:]mm:ss)")
    show.add_argument("--to", dest="end", help="End time (seconds or [h:]mm:ss)")
    show.add_argument("--format", choices=["json", "markdown"], default="markdown")

    found = command("mentions", help="Shared library entities named in the transcript, and the questions they belong to")
    found.add_argument("transcript_id")
    found.add_argument("--version", type=int)
    found.add_argument("--limit", type=int, default=50)

    ingest = command("ingest", help="Persist timestamped excerpts as evidence with the entities and relationships they support (one transaction)")
    ingest.add_argument("file", type=Path)
    return parsers
