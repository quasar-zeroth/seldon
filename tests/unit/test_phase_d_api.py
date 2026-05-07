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


def test_model_config_patch_updates_local_profiles():
    client = api_client()

    patched = client.patch("/config/models", json={"profiles": {"fast": "google/gemini-2.5-flash"}, "fallback_models": ["openrouter/auto"]})
    assert patched.status_code == 200
    body = patched.json()
    assert body["profiles"]["fast"] == "google/gemini-2.5-flash"
    assert body["fallback_models"] == ["openrouter/auto"]
