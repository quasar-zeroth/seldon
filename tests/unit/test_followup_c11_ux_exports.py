from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from seldon.api.app import create_app
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory
from seldon.data.models import AuditLog, ERGNode, KBEntry, Scenario, ScenarioPrediction


def make_client_with_session():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    session_factory = make_session_factory(engine)
    app = create_app(SeldonConfig(), session_factory=session_factory)
    return TestClient(app), session_factory


@pytest.mark.parametrize("bounds_path", ["builtin", "workspace", "legacy"])
def test_scenario_report_exports_markdown_json_and_html(bounds_path):
    client, session_factory = make_client_with_session()
    with session_factory() as db, db.begin():
        scenario = Scenario(id="scenario-ux", name="UX report", target_question="Will exports work?", time_horizon="Q4", description="Export coverage")
        kb = KBEntry(id="kb-ux", content="Evidence detail should be included.", source_name="Fixture", source_type="note")
        node = ERGNode(id="node-ux", name="Important node", type="metric", scenario_ids=["scenario-ux"], importance_score=0.91)
        prediction = ScenarioPrediction(id="prediction-ux", scenario_id="scenario-ux", statement="Exports should include context.", probabilities={"yes": 0.7}, confidence=0.7, assumptions=["API works"], evidence_links=["kb-ux"], status="active")
        bounds = {side: {"outcome": "Stress <script>text</script>", "rationale": "Conditional drivers", "assumptions": ["Joint premises"], "evidence_ids": ["kb-ux"], "value": None} for side in ("lower", "upper")}
        if bounds_path == "builtin":
            prediction.calibration_result = {"case_bounds": bounds}
        elif bounds_path == "workspace":
            prediction.calibration_result = {"forecast": {"case_bounds": bounds}}
        db.add_all([scenario, kb, node, prediction])

    markdown = client.get("/scenarios/scenario-ux/report").text
    assert "## Graph summary" in markdown
    assert "Important node" in markdown
    assert "Evidence detail should be included" in markdown

    payload = client.get("/scenarios/scenario-ux/report?format=json").json()
    assert payload["graph_summary"]["node_count"] == 1
    assert payload["latest_prediction"]["id"] == "prediction-ux"
    assert payload["evidence"][0]["id"] == "kb-ux"

    html = client.get("/scenarios/scenario-ux/report?format=html")
    assert html.headers["content-type"].startswith("text/html")
    assert "<h1>UX report</h1>" in html.text
    if bounds_path != "legacy":
        assert markdown.index("Hot takes: conditional stress bounds") < markdown.index("## Probabilities")
        assert "<h3>Hot takes: conditional stress bounds</h3>" in html.text
        assert "&lt;script&gt;text&lt;/script&gt;" in html.text
        assert "<script>" not in html.text


def test_merge_proposal_inbox_tracks_pending_and_decisions():
    client, session_factory = make_client_with_session()
    with session_factory() as db, db.begin():
        db.add(AuditLog(entity_type="scenario", entity_id="scenario-ux", action="extraction_graph_write", actor="test", after={"merge_proposals": [{"id": "merge-ux", "canonical_name": "Fed policy", "type": "policy", "candidate_names": ["Fed", "Federal Reserve"], "reason": "aliases", "confidence": 0.88}]}))

    pending = client.get("/graph/merge-proposals?status=pending").json()
    assert pending[0]["id"] == "merge-ux"
    assert pending[0]["status"] == "pending"
    assert pending[0]["candidate_names"] == ["Fed", "Federal Reserve"]

    response = client.post("/graph/merge-proposals/merge-ux/approve", json={"reason": "verified", "actor": "test"})
    assert response.status_code == 202
    decided = client.get("/graph/merge-proposals").json()
    assert decided[0]["status"] == "approved"
    assert decided[0]["decision_reason"] == "verified"
