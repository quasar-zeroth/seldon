from __future__ import annotations

from fastapi.testclient import TestClient

from seldon.api.app import create_app
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory


def api_client() -> TestClient:
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(SeldonConfig(), session_factory=make_session_factory(engine)))


def test_health_and_openapi_are_available():
    client = api_client()

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "The Seldon Project API"


def test_scenario_kb_graph_and_run_routes_smoke():
    client = api_client()

    scenario_response = client.post(
        "/scenarios",
        json={"name": "Gold outlook", "target_question": "Where will gold trade in 6 months?", "time_horizon": "6 months"},
    )
    assert scenario_response.status_code == 201
    scenario = scenario_response.json()
    assert client.get("/scenarios").json()[0]["id"] == scenario["id"]

    kb_response = client.post(
        "/kb/entries",
        json={"content": "Central banks continue buying gold.", "topics": ["gold"], "entities": ["central banks"], "scenario_ids": [scenario["id"]]},
    )
    assert kb_response.status_code == 201
    kb_entry = kb_response.json()
    assert client.get("/kb/search", params={"topic": "gold"}).json()[0]["id"] == kb_entry["id"]
    assert client.get(f"/kb/entries/{kb_entry['id']}").json()["content"].startswith("Central banks")

    node_a = client.post("/graph/nodes", json={"name": "Fed policy", "type": "policy"}).json()
    node_b = client.post("/graph/nodes", json={"name": "Gold price", "type": "metric"}).json()
    edge_response = client.post(
        "/graph/edges",
        json={
            "source_node_id": node_a["id"],
            "target_node_id": node_b["id"],
            "relationship_type": "opposes",
            "direction": "negative",
        },
    )
    assert edge_response.status_code == 201
    neighborhood = client.get(f"/graph/neighborhood/{node_a['id']}").json()
    assert {node["id"] for node in neighborhood["nodes"]} == {node_a["id"], node_b["id"]}
    assert len(neighborhood["edges"]) == 1

    run_response = client.post(f"/scenarios/{scenario['id']}/run-context-gathering")
    assert run_response.status_code == 202
    run = run_response.json()
    assert run["phase"] == "context_gathering"
    assert client.get("/runs").json()[0]["id"] == run["id"]


def test_error_responses_are_consistent():
    client = api_client()

    missing = client.get("/scenarios/missing")
    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found", "message": "scenario not found: missing", "details": None}}

    invalid = client.post("/scenarios", json={"name": "No target"})
    assert invalid.status_code == 422
    body = invalid.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]


def test_scenario_filters_patch_and_backend_report_export():
    client = api_client()

    gold = client.post("/scenarios", json={"name": "Gold outlook", "target_question": "Gold?", "description": "Metals", "status": "active"}).json()
    client.post("/scenarios", json={"name": "Oil outlook", "target_question": "Oil?", "status": "paused"})

    filtered = client.get("/scenarios", params={"q": "gold", "status": "active"})
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [gold["id"]]

    patched = client.patch(f"/scenarios/{gold['id']}", json={"time_horizon": "6 months", "status": "paused"})
    assert patched.status_code == 200
    assert patched.json()["time_horizon"] == "6 months"
    assert patched.json()["status"] == "paused"

    prediction = client.post(
        "/predictions",
        json={
            "scenario_id": gold["id"],
            "statement": "Gold base case remains constructive.",
            "probabilities": {"bull": 0.25, "base": 0.55, "bear": 0.2},
            "confidence": 0.7,
            "assumptions": ["Rates fall"],
            "evidence_links": ["kb-1"],
        },
    )
    assert prediction.status_code == 201

    report = client.get(f"/scenarios/{gold['id']}/report")
    assert report.status_code == 200
    assert "# Gold outlook" in report.text
    assert "Gold base case remains constructive." in report.text
    assert "- base: 55%" in report.text


def test_model_config_patch_updates_local_profiles():
    client = api_client()

    patched = client.patch("/config/models", json={"profiles": {"fast": "google/gemini-2.5-flash"}, "fallback_models": ["openrouter/auto"]})
    assert patched.status_code == 200
    body = patched.json()
    assert body["profiles"]["fast"] == "google/gemini-2.5-flash"
    assert body["fallback_models"] == ["openrouter/auto"]


def test_kb_explorer_filters_versions_contradictions_and_related_records():
    client = api_client()

    scenario = client.post("/scenarios", json={"name": "Copper outlook", "target_question": "Copper?"}).json()
    first = client.post(
        "/kb/entries",
        json={
            "content": "Copper inventories are tightening.",
            "source_type": "news_article",
            "source_name": "Reuters",
            "topics": ["copper"],
            "entities": ["LME"],
            "scenario_ids": [scenario["id"]],
            "perspective_tags": {"sentiment": 0.6, "confidence": 0.8, "geopolitical_lens": "neutral"},
        },
    ).json()
    second = client.post(
        "/kb/entries",
        json={
            "content": "Copper inventories are rebuilding.",
            "source_type": "research_paper",
            "source_name": "Warehouse survey",
            "topics": ["copper"],
            "perspective_tags": {"sentiment": -0.5, "confidence": 0.7},
        },
    ).json()

    filtered = client.get(
        "/kb/search",
        params={
            "topic": "copper",
            "entity": "LME",
            "source": "Reuters",
            "source_type": "news_article",
            "scenario_id": scenario["id"],
            "current_only": True,
            "min_sentiment": 0.1,
            "min_confidence": 0.7,
            "geopolitical_lens": "neutral",
            "include_scores": True,
            "sort": "confidence",
        },
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [first["id"]]
    assert filtered.json()[0]["is_current"] is True
    assert "decay_score" in filtered.json()[0]

    patched = client.patch(f"/kb/entries/{first['id']}", json={"content": "Copper inventories are tightening fast."})
    assert patched.status_code == 200
    versions = client.get(f"/kb/entries/{first['id']}/versions").json()
    assert [version["version"] for version in versions] == [1, 2]

    contradiction = client.post(
        "/kb/contradictions",
        json={"kb_entry_id": first["id"], "contradicts_kb_entry_id": second["id"], "description": "Inventory direction conflicts."},
    )
    assert contradiction.status_code == 201
    entry_contradictions = client.get(f"/kb/entries/{first['id']}/contradictions").json()
    assert entry_contradictions[0]["description"] == "Inventory direction conflicts."
    assert client.patch(f"/kb/contradictions/{entry_contradictions[0]['id']}", json={"status": "resolved"}).json()["status"] == "resolved"

    node = client.post("/graph/nodes", json={"name": "Copper inventories", "type": "metric", "kb_entry_ids": [first["id"]]}).json()
    edge_target = client.post("/graph/nodes", json={"name": "Copper price", "type": "metric"}).json()
    edge = client.post(
        "/graph/edges",
        json={"source_node_id": node["id"], "target_node_id": edge_target["id"], "relationship_type": "opposes", "evidence_kb_ids": [first["id"]]},
    ).json()
    prediction = client.post(
        "/predictions",
        json={"scenario_id": scenario["id"], "statement": "Copper rises", "evidence_links": [first["id"]]},
    ).json()
    client.post("/predictions/{}/evidence".format(prediction["id"]), json={"scenario_prediction_id": prediction["id"], "kb_entry_id": first["id"], "relationship": "supports"})

    related = client.get(f"/kb/entries/{first['id']}/related").json()
    assert related["scenarios"][0]["id"] == scenario["id"]
    assert related["graph_nodes"][0]["id"] == node["id"]
    assert related["graph_edges"][0]["id"] == edge["id"]
    assert related["predictions"][0]["id"] == prediction["id"]

    assert client.post(f"/kb/entries/{first['id']}/supersede/{second['id']}").json()["superseded_by"] == second["id"]
    assert client.get("/kb/search", params={"topic": "copper", "current_only": True}).json()[0]["id"] == second["id"]
