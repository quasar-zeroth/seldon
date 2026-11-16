"""Plain-text/JSON interface usable by any coding agent with a shell."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.workspace.schemas import WorkspaceApply
from seldon.workspace.service import WorkspaceService, render_markdown


def execute(args: argparse.Namespace) -> int:
    if args.research_command == "cycles" and args.cycles_command in ("schema", "catalog"):
        from .cycles.cli import static
        result = static(args)
    elif args.research_command == "transcripts" and args.transcripts_command in ("schema", "catalog"):
        from .transcripts.cli import static
        result = static(args)
    elif args.research_command == "perspectives" and args.perspective_command == "schema":
        from .perspectives.schemas import PerspectiveApply
        result = PerspectiveApply.model_json_schema()
    elif args.research_command == "schema":
        result = WorkspaceApply.model_json_schema()
    else:
        # Explicit local DB avoids loading provider configuration, .env secrets,
        # or starting model/retrieval clients. API users share their API DB.
        engine = make_engine(sqlite_path=args.db)
        create_all(engine)
        try:
            with make_session_factory(engine)() as db, db.begin():
                service = WorkspaceService(db)
                if args.research_command == "cycles":
                    from .cycles.cli import run
                    result = run(args, db)
                elif args.research_command == "transcripts":
                    from .transcripts.cli import run
                    result = run(args, db)
                elif args.research_command == "perspectives":
                    from .perspectives import export_graph, apply_graph, index_scenario, select_context
                    from .perspectives.schemas import PerspectiveApply
                    if args.perspective_command == "connections":
                        from .perspectives.connections import connections
                        result = connections(db, args.kind, args.id, depth=args.depth, to_kind=args.to_kind, to_id=args.to_id)
                    elif args.perspective_command == "catalog":
                        from .perspectives.connections import connection_catalog
                        result = connection_catalog(db)
                    elif args.perspective_command == "apply":
                        result = apply_graph(db, PerspectiveApply.model_validate_json(args.file.read_text()))
                    elif args.perspective_command == "index":
                        result = index_scenario(db, args.scenario_id)
                    else:
                        graph = export_graph(db)
                        result = select_context(graph, topic_id=args.topic, source_id=args.source, depth=args.depth)
                        result.update(revision=graph["revision"], history=graph["history"])
                        if args.format == "markdown":
                            result = "# Topics, claims and sources\n\n```json\n" + json.dumps(result, indent=2, ensure_ascii=False) + "\n```"
                elif args.research_command == "start":
                    result = service.start(args.question, args.horizon, name=args.name)
                elif args.research_command == "list":
                    from sqlalchemy import select
                    from seldon.data.models import Scenario
                    from seldon.data.repositories import row_to_dict

                    result = [
                        row_to_dict(s)
                        for s in db.scalars(
                            select(Scenario).order_by(Scenario.created_at)
                        )
                    ]
                elif args.research_command == "apply":
                    result = service.apply(
                        WorkspaceApply.model_validate_json(args.file.read_text())
                    )
                elif args.research_command == "pipeline":
                    from .pipeline import pipeline_snapshot

                    result = pipeline_snapshot(db, args.scenario_id)
                elif args.research_command == "library":
                    from .knowledge import search_library

                    result = search_library(db, args.query, args.limit, tag=args.tag, offset=args.offset)
                elif args.research_command == "reports":
                    from .reports import ReportRequest, generate_report, list_reports, report_file
                    from uuid import uuid4
                    if args.report_command == "generate":
                        payload = json.loads(args.file.read_text()) if args.file else {}
                        payload.setdefault("request_id", args.request_id or str(uuid4()))
                        result = generate_report(db, args.scenario_id, ReportRequest.model_validate(payload))
                    elif args.report_command == "download":
                        result = report_file(db, args.report_id, args.name)["content"]
                    else:
                        result = list_reports(db, args.scenario_id)
                elif args.research_command == "rerun":
                    from .reruns import request_prediction
                    from uuid import uuid4

                    result = request_prediction(
                        db,
                        args.scenario_id,
                        request_id=args.request_id or str(uuid4()),
                        reason=args.reason,
                        horizon=args.horizon,
                    )
                elif args.research_command == "requests":
                    from .reruns import list_requests

                    result = list_requests(db, args.scenario_id)
                else:
                    result = service.export(args.scenario_id)
        finally:
            engine.dispose()
    output = result if isinstance(result, str) else (
        render_markdown(result)
        if getattr(args, "format", "json") == "markdown"
        else json.dumps(result, indent=2)
    )
    exact_download = (
        args.research_command == "reports" and args.report_command == "download"
    )
    if getattr(args, "out", None):
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if exact_download:
            args.out.write_bytes(output.encode("utf-8"))
        else:
            args.out.write_text(output + "\n")
    elif exact_download:
        import sys

        sys.stdout.write(output)
    else:
        print(output)
    return 0


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(
        "research", help="Agent-led DAG research; no model provider credentials or calls (transcripts fetch is the one network command)"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/seldon.db"),
        help="SQLite file; use an absolute path across repositories",
    )
    commands = parser.add_subparsers(dest="research_command", required=True)
    start = commands.add_parser(
        "start", help="Create a research scenario from a question"
    )
    start.add_argument("question")
    start.add_argument(
        "--horizon", required=True, help="Explicit time horizon or resolution date"
    )
    start.add_argument("--name")
    export = commands.add_parser(
        "export", help="Export all evidence, DAG, forecasts, and research steps"
    )
    export.add_argument("scenario_id")
    export.add_argument("--format", choices=["json", "markdown"], default="json")
    apply = commands.add_parser(
        "apply", help="Validate and atomically persist an agent-authored JSON change"
    )
    apply.add_argument("file", type=Path)
    schema = commands.add_parser(
        "schema", help="Print the complete JSON Schema for apply"
    )
    listing = commands.add_parser(
        "list", help="List scenarios in the selected database"
    )
    pipeline = commands.add_parser(
        "pipeline", help="Inspect shared research stages, history, and outputs"
    )
    pipeline.add_argument(
        "scenario_id",
        nargs="?",
        help="Scenario ID; defaults to the most recently updated scenario",
    )
    library = commands.add_parser(
        "library",
        help="Search shared entities and their evidence before creating duplicate nodes",
    )
    library.add_argument("query", nargs="?", default="")
    library.add_argument("--tag", help="Exact normalized tag, e.g. data-center")
    library.add_argument("--limit", type=int, default=30)
    library.add_argument("--offset", type=int, default=0)
    reports = commands.add_parser("reports", help="Generate, list and download immutable summary/detailed research reports")
    report_commands = reports.add_subparsers(dest="report_command", required=True)
    report_generate = report_commands.add_parser("generate")
    report_generate.add_argument("scenario_id")
    report_generate.add_argument("--request-id")
    report_generate.add_argument("--file", type=Path, help="Optional ReportRequest JSON with authored sections and CSV/JSON attachments")
    report_list = report_commands.add_parser("list")
    report_list.add_argument("--scenario-id")
    report_download = report_commands.add_parser("download")
    report_download.add_argument("report_id")
    report_download.add_argument("name", help="summary.md, detailed.md or an attached filename")
    rerun = commands.add_parser(
        "rerun",
        help="Queue a fresh forecast for your existing agent; returns its handoff prompt",
    )
    rerun.add_argument("scenario_id")
    rerun.add_argument("--request-id")
    rerun.add_argument("--reason", default="Refresh the forecast with current evidence")
    rerun.add_argument("--horizon")
    requests = commands.add_parser(
        "requests", help="List queued/completed external-agent forecast requests"
    )
    requests.add_argument("--scenario-id")
    perspectives = commands.add_parser("perspectives", help="Shared topics, attributed claims, trust reviews and source affiliations")
    perspective_commands = perspectives.add_subparsers(dest="perspective_command", required=True)
    perspective_catalog = perspective_commands.add_parser("catalog")
    perspective_connections = perspective_commands.add_parser("connections", help="Explain provenance paths across entities, topics, claims and sources")
    perspective_connections.add_argument("kind", choices=["entity", "topic", "source", "claim", "evidence"])
    perspective_connections.add_argument("id")
    perspective_connections.add_argument("--depth", type=int, default=3)
    perspective_connections.add_argument("--to-kind", choices=["entity", "topic", "source", "claim", "evidence"])
    perspective_connections.add_argument("--to-id")
    perspective_schema = perspective_commands.add_parser("schema")
    perspective_export = perspective_commands.add_parser("export")
    perspective_export.add_argument("--topic")
    perspective_export.add_argument("--source")
    perspective_export.add_argument("--depth", type=int, default=4)
    perspective_export.add_argument("--format", choices=["json", "markdown"], default="json")
    perspective_apply = perspective_commands.add_parser("apply")
    perspective_apply.add_argument("file", type=Path)
    perspective_index = perspective_commands.add_parser("index", help="Index a saved research question without assuming its claims are verified")
    perspective_index.add_argument("scenario_id")
    from .cycles.cli import add_parser as add_cycles
    from .transcripts.cli import add_parser as add_transcripts
    cycle_commands = add_cycles(commands)
    transcript_commands = add_transcripts(commands)
    for command in (
        *cycle_commands,
        *transcript_commands,
        perspective_connections, perspective_catalog, perspective_schema, perspective_export, perspective_apply, perspective_index,
        start,
        export,
        apply,
        schema,
        listing,
        pipeline,
        library,
        rerun,
        requests,
        report_generate,
        report_list,
        report_download,
    ):
        command.add_argument("--out", type=Path, help="Write UTF-8 text to this path")
        command.set_defaults(func=execute)
