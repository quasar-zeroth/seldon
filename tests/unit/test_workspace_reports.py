import pytest
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.repositories import GraphRepository
from seldon.workspace.knowledge import search_library
from seldon.workspace.reports import (
    ReportRequest,
    generate_report,
    list_reports,
    report_file,
)
from seldon.workspace.service import WorkspaceConflict, WorkspaceService


def test_reports_persist_and_do_not_change_with_later_research(tmp_path):
    engine = make_engine(sqlite_path=tmp_path / "reports.db")
    create_all(engine)
    factory = make_session_factory(engine)
    with factory() as db, db.begin():
        service = WorkspaceService(db)
        w = service.start("Campus energy and funding?", "As of today")
        sid = w["scenario"]["id"]
        node = GraphRepository(db).create_node(
            name="Test data center",
            type="entity",
            current_state="Original research",
            scenario_ids=[sid],
            tags=["Country:US", "Data Centers"],
        )
        assert node.tags == ["country:us", "data-center", "type:entity"]
        req = ReportRequest(
            request_id="saved-report",
            attachments=[
                {
                    "name": "inventory.csv",
                    "media_type": "text/csv",
                    "content": " site,mw\nTest,100 \n",
                }
            ],
        )
        result = generate_report(db, sid, req)
        assert generate_report(db, sid, req)["replayed"]
        content = report_file(db, result["id"], "detailed.md")["content"]
        assert "Original research" in content
        assert "summary.md" in [f["name"] for f in result["files"]]
        GraphRepository(db).update_node(node.id, current_state="Changed research")
        assert "country:us" in node.tags
        assert report_file(db, result["id"], "detailed.md")["content"] == content
        assert search_library(db, tag="data center", limit=1)["total"] == 1
        assert search_library(db, tag="data-center", offset=1)["nodes"] == []
        assert search_library(db, tag="utility")["total"] == 0
        with pytest.raises(WorkspaceConflict):
            generate_report(
                db, sid, ReportRequest(request_id="saved-report", title="Different")
            )
        with pytest.raises(WorkspaceConflict):
            generate_report(
                db, sid, ReportRequest(request_id="stale", expected_revision="old")
            )
        with pytest.raises(ValueError, match="current research scope"):
            generate_report(
                db,
                sid,
                ReportRequest(
                    request_id="bad-source",
                    sections=[
                        {"title": "Bad", "body": "x", "evidence_ids": ["not-in-scope"]}
                    ],
                ),
            )
    with factory() as db:
        assert len(list_reports(db, sid)) == 1
        assert (
            report_file(db, result["id"], "inventory.csv")["content"]
            == " site,mw\nTest,100 \n"
        )
        with pytest.raises(KeyError):
            report_file(db, result["id"], "../private")
        assert all(
            r["phase"] != "research_report"
            for r in WorkspaceService(db).export(sid)["runs"]
        )
    from argparse import Namespace
    from seldon.workspace.cli import execute

    downloaded = tmp_path / "downloaded.csv"
    execute(Namespace(
        research_command="reports", report_command="download",
        db=tmp_path / "reports.db", report_id=result["id"],
        name="inventory.csv", out=downloaded,
    ))
    assert downloaded.read_bytes() == b" site,mw\nTest,100 \n"
    engine.dispose()


def test_programmes_are_not_automatically_physical_sites(tmp_path):
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    with make_session_factory(engine)() as db, db.begin():
        repo = GraphRepository(db)
        programme = repo.create_node(
            name="Stargate UK programme",
            type="entity",
            description="AI infrastructure inventory",
        )
        assert "data-center" not in programme.tags
    engine.dispose()


def test_generated_report_preserves_large_history_without_relaxing_upload_limits(tmp_path):
    from pydantic import ValidationError
    from seldon.workspace.reports import ReportAttachment
    engine = make_engine(sqlite_path=tmp_path / 'large-report.db')
    create_all(engine)
    with make_session_factory(engine)() as db, db.begin():
        sid = WorkspaceService(db).start('Large accumulated research?', 'Today')['scenario']['id']
        # Individually valid research sections together exceed the attachment-upload limit.
        sections = [{'title': f'Finding {i}', 'body': 'Retained evidence. ' * 13000 + f'End of section {i}'} for i in range(14)]
        request = ReportRequest(request_id='large', sections=sections)
        result = generate_report(db, sid, request)
        text = report_file(db, result['id'], 'detailed.md')['content']
        assert len(text) > 3_000_000
        assert all(f'End of section {i}' in text for i in range(14))
        with pytest.raises(ValidationError):
            ReportAttachment(name='upload.txt',media_type='text/plain',content=text)
    with make_session_factory(engine)() as db:
        assert report_file(db, result['id'], 'detailed.md')['content'] == text
    engine.dispose()
