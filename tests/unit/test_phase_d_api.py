from __future__ import annotations

from fastapi.testclient import TestClient

from seldon.api.app import create_app
from seldon.config import SeldonConfig
from seldon.data.database import create_all, make_engine, make_session_factory


class ScenarioDraftLLM:
    def complete_json(self, messages, system=None, **kwargs):
        return {
            "name": "Gold breakout",
            "target_question": "Will gold break above $2,800 within six months?",
            "time_horizon": "6 months",
            "description": "Scope includes Fed cuts, dollar strength, central-bank demand, and geopolitical risk.",
        }


class FailingScenarioDraftLLM:
    def complete_json(self, messages, system=None, **kwargs):
        raise RuntimeError("unauthorized")


def api_client() -> TestClient:
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    return TestClient(create_app(SeldonConfig(), session_factory=make_session_factory(engine)))


def test_api_writes_structured_logs_to_file(tmp_path):
    cfg = SeldonConfig(data_dir=tmp_path)
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    client = TestClient(create_app(cfg, session_factory=make_session_factory(engine)))

    response = client.get("/health")

    assert response.status_code == 200
    log_file = tmp_path / "logs" / "seldon.log"
    assert log_file.exists()
    assert "request completed" in log_file.read_text()


def test_health_and_openapi_are_available():
    client = api_client()

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "The Seldon Project API"


def test_scenario_draft_endpoint_uses_fast_llm_metadata_extraction():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    client = TestClient(create_app(SeldonConfig(), session_factory=make_session_factory(engine), llm_client=ScenarioDraftLLM()))

    response = client.post("/scenarios/draft", json={"prompt": "I want to understand whether gold breaks above $2,800 in the next six months."})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Gold breakout"
    assert body["time_horizon"] == "6 months"
    assert "gold" in body["target_question"].lower()
    assert body["source_prompt"].startswith("I want to understand")


def test_scenario_draft_endpoint_falls_back_when_llm_is_unavailable():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    client = TestClient(create_app(SeldonConfig(), session_factory=make_session_factory(engine), llm_client=FailingScenarioDraftLLM()))

    response = client.post("/scenarios/draft", json={"prompt": "Forecast copper demand with no horizon"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Forecast copper demand with no horizon"
    assert body["time_horizon"] == "6 months / 1 year"
    assert "current baseline" in body["description"]
    assert body["description"] != body["source_prompt"]


def test_scenario_draft_fallback_summarizes_gold_price_question_without_truncating_prompt():
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    client = TestClient(create_app(SeldonConfig(), session_factory=make_session_factory(engine), llm_client=FailingScenarioDraftLLM()))

    response = client.post("/scenarios/draft", json={"prompt": "I want to know what would the price of gold would look like in 6 months and in a year"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Gold price outlook over 6 months and 12 months"
    assert not body["name"].lower().startswith("i want")
    assert "current spot price" in body["description"]
    assert "Federal Reserve policy" in body["description"]
    assert body["description"] != body["source_prompt"]


def test_scenario_kb_graph_and_run_routes_smoke():
    client = api_client()

    scenario_response = client.post(
        "/scenarios",
        json={"name": "Gold outlook", "target_question": "Where will gold trade in 6 months?", "time_horizon": "6 months", "original_prompt": "I want to understand gold over the next 6 months."},
    )
    assert scenario_response.status_code == 201
    scenario = scenario_response.json()
    assert scenario["original_prompt"] == "I want to understand gold over the next 6 months."
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


def test_scenario_search_patch_and_backend_report_export():
    client = api_client()

    gold = client.post("/scenarios", json={"name": "Gold outlook", "target_question": "Gold?", "description": "Metals"}).json()
    client.post("/scenarios", json={"name": "Oil outlook", "target_question": "Oil?"})

    filtered = client.get("/scenarios", params={"q": "gold"})
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [gold["id"]]

    patched = client.patch(f"/scenarios/{gold['id']}", json={"time_horizon": "6 months"})
    assert patched.status_code == 200
    assert patched.json()["time_horizon"] == "6 months"

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


def test_delete_scenario_removes_owned_records_and_unlinks_shared_context():
    client = api_client()

    scenario = client.post("/scenarios", json={"name": "Delete me", "target_question": "Delete?"}).json()
    prediction = client.post("/predictions", json={"scenario_id": scenario["id"], "statement": "Temporary prediction"}).json()
    kb = client.post("/kb/entries", json={"content": "Temporary context", "scenario_ids": [scenario["id"]]}).json()
    node = client.post("/graph/nodes", json={"name": "Temporary node", "type": "topic", "scenario_ids": [scenario["id"]]}).json()

    response = client.delete(f"/scenarios/{scenario['id']}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "scenario_id": scenario["id"]}
    assert client.get(f"/scenarios/{scenario['id']}").status_code == 404
    assert client.get(f"/predictions/{prediction['id']}").status_code == 404
    assert scenario["id"] not in client.get(f"/kb/entries/{kb['id']}").json()["scenario_ids"]
    assert scenario["id"] not in client.get(f"/graph/nodes/{node['id']}").json()["scenario_ids"]


def test_model_config_patch_updates_local_profiles():
    client = api_client()

    patched = client.patch("/config/models", json={"profiles": {"fast": "google/gemini-2.5-flash"}, "fallback_models": ["openrouter/auto"]})
    assert patched.status_code == 200
    body = patched.json()
    assert body["profiles"]["fast"] == "google/gemini-2.5-flash"
    assert body["fallback_models"] == ["openrouter/auto"]


def test_clear_all_data_requires_confirmation_and_removes_runtime_records(tmp_path):
    cfg = SeldonConfig(data_dir=tmp_path)
    cfg.ops.vector_index_path = tmp_path / "vector-index"
    cfg.ops.vector_index_path.mkdir(parents=True)
    (cfg.ops.vector_index_path / "index.json").write_text("{}")
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    client = TestClient(create_app(cfg, session_factory=make_session_factory(engine)))

    scenario = client.post("/scenarios", json={"name": "Reset me", "target_question": "Reset?"}).json()
    client.post("/kb/entries", json={"content": "Temporary context", "scenario_ids": [scenario["id"]]})
    node = client.post("/graph/nodes", json={"name": "Temporary node", "type": "topic"}).json()
    other_node = client.post("/graph/nodes", json={"name": "Temporary metric", "type": "metric"}).json()
    client.post("/graph/edges", json={"source_node_id": node["id"], "target_node_id": other_node["id"], "relationship_type": "causes"})
    client.post("/predictions", json={"scenario_id": scenario["id"], "statement": "Temporary prediction"})

    rejected = client.request("DELETE", "/ops/data", json={"confirmation": "nope"})
    assert rejected.status_code == 422

    response = client.request("DELETE", "/ops/data", json={"confirmation": "CLEAR ALL DATA"})

    assert response.status_code == 200
    body = response.json()
    assert body["cleared"] is True
    assert body["deleted"]["scenarios"] == 1
    assert body["deleted"]["kb_entries"] == 1
    assert body["deleted"]["erg_nodes"] == 2
    assert body["deleted"]["erg_edges"] == 1
    assert body["deleted"]["scenario_predictions"] == 1
    assert body["vector_index_cleared"] is True
    assert client.get("/scenarios").json() == []
    assert client.get("/kb/search").json() == []
    assert client.get("/graph/nodes").json() == []
    assert client.get("/graph/edges").json() == []
    assert client.get("/predictions").json() == []
    assert not cfg.ops.vector_index_path.exists()


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


def test_runs_console_filters_detail_retry_and_related_records():
    client = api_client()

    scenario = client.post("/scenarios", json={"name": "Run scenario", "target_question": "What happened?"}).json()
    kb = client.post("/kb/entries", json={"content": "Run cited fact."}).json()
    node = client.post("/graph/nodes", json={"name": "Run node", "type": "entity"}).json()
    edge_target = client.post("/graph/nodes", json={"name": "Run target", "type": "metric"}).json()
    edge = client.post("/graph/edges", json={"source_node_id": node["id"], "target_node_id": edge_target["id"], "relationship_type": "causes"}).json()
    prediction = client.post("/predictions", json={"scenario_id": scenario["id"], "statement": "Run prediction"}).json()

    run = client.post(
        "/runs",
        json={"agent_id": "test_agent", "phase": "extraction", "status": "failed", "input": {"scenario_id": scenario["id"]}, "source_references": [kb["id"]]},
    ).json()
    patched = client.patch(
        f"/runs/{run['id']}",
        json={"output": {"kb_entry_id": kb["id"], "node_id": node["id"], "edge_id": edge["id"], "prediction_id": prediction["id"]}, "error": "boom"},
    )
    assert patched.status_code == 200
    message = client.post(f"/runs/{run['id']}/messages", json={"agent_run_id": run["id"], "role": "assistant", "content": "created records"})
    assert message.status_code == 201
    invocation = client.post(
        f"/runs/{run['id']}/model-invocations",
        json={"agent_run_id": run["id"], "model": "test/model", "provider": "openrouter", "usage": {"total_tokens": 42}, "estimated_cost": 0.01, "ok": False, "error": "model failed"},
    )
    assert invocation.status_code == 201

    filtered = client.get(
        "/runs",
        params={"scenario_id": scenario["id"], "phase": "extraction", "agent": "test_agent", "status": "failed", "model": "test/model", "failure_state": "failed"},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [run["id"]]
    assert filtered.json()[0]["model_invocations"][0]["model"] == "test/model"

    detail = client.get(f"/runs/{run['id']}").json()
    assert detail["model_invocations"][0]["usage"]["total_tokens"] == 42
    assert client.get(f"/runs/{run['id']}/messages").json()[0]["content"] == "created records"
    related = client.get(f"/runs/{run['id']}/related").json()
    assert related["kb_entries"][0]["id"] == kb["id"]
    assert related["graph_nodes"][0]["id"] == node["id"]
    assert related["graph_edges"][0]["id"] == edge["id"]
    assert related["predictions"][0]["id"] == prediction["id"]

    retry = client.post(f"/runs/{run['id']}/retry")
    assert retry.status_code == 202
    assert retry.json()["status"] == "pending"


def test_graph_explorer_filters_mutations_snapshots_and_merge_decisions():
    client = api_client()

    scenario = client.post("/scenarios", json={"name": "Rates outlook", "target_question": "Rates?"}).json()
    node_a = client.post(
        "/graph/nodes",
        json={
            "name": "Fed funds rate",
            "type": "policy",
            "description": "Policy rate",
            "scenario_ids": [scenario["id"]],
            "kb_entry_ids": ["kb-rate"],
            "stability_score": 0.3,
            "importance_score": 0.9,
        },
    ).json()
    node_b = client.post(
        "/graph/nodes",
        json={"name": "Gold price", "type": "metric", "scenario_ids": [scenario["id"]], "importance_score": 0.6},
    ).json()
    edge = client.post(
        "/graph/edges",
        json={
            "source_node_id": node_a["id"],
            "target_node_id": node_b["id"],
            "relationship_type": "opposes",
            "direction": "negative",
            "confidence": 0.8,
            "strength": 0.7,
            "lag": "2 weeks",
            "evidence_kb_ids": ["kb-rate"],
            "scenario_ids": [scenario["id"]],
        },
    ).json()

    nodes = client.get("/graph/nodes", params={"scenario_id": scenario["id"], "type": "policy", "min_importance": 0.8, "max_stability": 0.4})
    assert nodes.status_code == 200
    assert [item["id"] for item in nodes.json()] == [node_a["id"]]

    edges = client.get("/graph/edges", params={"scenario_id": scenario["id"], "relationship_type": "opposes", "direction": "negative", "min_confidence": 0.75, "min_strength": 0.6, "min_evidence_count": 1})
    assert edges.status_code == 200
    assert [item["id"] for item in edges.json()] == [edge["id"]]

    patched_node = client.patch(f"/graph/nodes/{node_a['id']}", json={"current_state": "watching", "importance_score": 0.95})
    assert patched_node.status_code == 200
    assert client.get(f"/graph/nodes/{node_a['id']}").json()["current_state"] == "watching"
    patched_edge = client.patch(f"/graph/edges/{edge['id']}", json={"confidence": 0.55, "strength": 0.5})
    assert patched_edge.status_code == 200
    assert client.get(f"/graph/edges/{edge['id']}").json()["confidence"] == 0.55

    neighborhood = client.get(f"/graph/neighborhood/{node_a['id']}").json()
    assert {node["id"] for node in neighborhood["nodes"]} == {node_a["id"], node_b["id"]}
    assert neighborhood["edges"][0]["id"] == edge["id"]

    first_snapshot = client.post("/graph/snapshots", json={"scenario_id": scenario["id"], "reason": "before"}).json()
    node_c = client.post("/graph/nodes", json={"name": "Inflation", "type": "metric"}).json()
    second_snapshot = client.post("/graph/snapshots", json={"scenario_id": scenario["id"], "reason": "after"}).json()
    diff = client.get(f"/graph/snapshots/{first_snapshot['id']}/diff/{second_snapshot['id']}").json()
    assert node_c["id"] in diff["added_nodes"]

    reuse = client.get(f"/graph/reuse-candidates/{scenario['id']}").json()
    assert node_c["id"] in {node["id"] for node in reuse["nodes"]}

    approved = client.post("/graph/merge-proposals/proposal-1/approve", json={"reason": "same entity"})
    rejected = client.post("/graph/merge-proposals/proposal-2/reject", json={"reason": "different entities"})
    assert approved.status_code == 202
    assert approved.json()["status"] == "approved"
    assert rejected.json()["status"] == "rejected"
    audit = client.get("/audit-log", params={"entity_type": "graph_merge_proposal", "entity_id": "proposal-1"}).json()
    assert audit[0]["action"] == "approve"


def test_chart_analytics_endpoint_aggregates_persisted_visualization_records():
    from seldon.data.models import AdvancedAnalysis, SentimentDrift

    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    factory = make_session_factory(engine)
    client = TestClient(create_app(SeldonConfig(), session_factory=factory))

    scenario = client.post("/scenarios", json={"name": "Analytics scenario", "target_question": "Will charts work?"}).json()
    prediction = client.post(
        "/predictions",
        json={
            "scenario_id": scenario["id"],
            "statement": "Charts should render from persisted rows.",
            "probabilities": {"bull": 0.4, "base": 0.4, "bear": 0.2},
            "confidence": 0.64,
            "probability_history": [
                {"timestamp": "2026-01-01T00:00:00Z", "bull": 0.3, "base": 0.5, "bear": 0.2, "confidence": 0.6},
                {"timestamp": "2026-01-02T00:00:00Z", "bull": 0.4, "base": 0.4, "bear": 0.2, "confidence": 0.64},
            ],
            "status": "active",
        },
    ).json()
    run = client.post("/runs", json={"agent_id": "prediction_coordinator", "phase": "prediction", "status": "completed", "input": {"scenario_id": scenario["id"]}}).json()
    client.post(f"/runs/{run['id']}/model-invocations", json={"model": "test/model", "latency_ms": 120, "usage": {"total_tokens": 99}, "estimated_cost": 0.02, "ok": True})

    with factory() as db:
        with db.begin():
            db.add(SentimentDrift(scenario_id=scenario["id"], topic="charts", sentiment=0.25, previous_sentiment=0.1, velocity=0.15, evidence_kb_ids=[]))
            db.add(
                AdvancedAnalysis(
                    prediction_id=prediction["id"],
                    scenario_id=scenario["id"],
                    uncertainty={"factor": "policy surprise", "probability": 0.35, "impact": 0.8},
                    cascade_risks=[{"risk": "liquidity shock", "probability": 0.2, "impact": 0.7}],
                )
            )

    response = client.get("/analytics/charts", params={"scenario_id": scenario["id"]})
    assert response.status_code == 200
    body = response.json()
    assert body["scenario_id"] == scenario["id"]
    assert len(body["probability_history"]) == 2
    assert body["prediction_confidence"][0]["confidence"] == 0.64
    assert body["sentiment_drift"][0]["topic"] == "charts"
    assert body["uncertainty"][0]["factor"] == "policy surprise"
    assert body["cascade_risks"][0]["risk"] == "liquidity shock"
    assert body["model_performance"][0]["agent"] == "prediction_coordinator"
    assert body["model_performance"][0]["total_tokens"] == 99


def test_gui_endpoint_contract_documents_backend_integration_surface():
    client = api_client()

    response = client.get("/config/gui-endpoints")
    assert response.status_code == 200
    body = response.json()
    assert body["auth"]["header"] == "x-seldon-api-key"
    assert body["auth"]["secrets_exposed"] is False
    assert "GET /analytics/charts" in body["pages"]["calibration"]
    assert body["mutations"]["prediction_resolution"] == "POST /predictions/{prediction_id}/resolve"
    assert body["pagination"]["max_limit"] == 500


def test_gui_list_endpoints_support_sorting_pagination_and_empty_states():
    client = api_client()

    scenario = client.post("/scenarios", json={"name": "Pagination scenario", "target_question": "Do filters work?"}).json()
    low = client.post("/graph/nodes", json={"name": "Low importance", "type": "metric", "importance_score": 0.1}).json()
    high = client.post("/graph/nodes", json={"name": "High importance", "type": "metric", "importance_score": 0.9}).json()
    client.post("/graph/edges", json={"source_node_id": low["id"], "target_node_id": high["id"], "relationship_type": "causes", "confidence": 0.2, "strength": 0.3}).json()
    strong_edge = client.post("/graph/edges", json={"source_node_id": high["id"], "target_node_id": low["id"], "relationship_type": "opposes", "confidence": 0.8, "strength": 0.9}).json()
    client.post("/predictions", json={"scenario_id": scenario["id"], "statement": "Weak confidence", "confidence": 0.25, "status": "draft"})
    strong_prediction = client.post("/predictions", json={"scenario_id": scenario["id"], "statement": "Strong confidence", "confidence": 0.85, "status": "active"}).json()

    nodes = client.get("/graph/nodes", params={"sort": "importance_score", "order": "desc", "limit": 1}).json()
    assert [node["id"] for node in nodes] == [high["id"]]
    edges = client.get("/graph/edges", params={"sort": "strength", "order": "desc", "limit": 1}).json()
    assert [edge["id"] for edge in edges] == [strong_edge["id"]]
    predictions = client.get("/predictions", params={"scenario_id": scenario["id"], "status": "active", "min_confidence": 0.8, "sort": "confidence", "limit": 1}).json()
    assert [prediction["id"] for prediction in predictions] == [strong_prediction["id"]]

    assert client.get("/graph/nodes", params={"type": "actor"}).json() == []
    assert client.get("/predictions", params={"scenario_id": "missing"}).json() == []
    assert client.get("/graph/nodes", params={"sort": "unsupported"}).status_code == 422


def test_settings_status_and_model_patch_validation_and_agent_overrides():
    client = api_client()

    status = client.get("/config/status")
    assert status.status_code == 200
    body = status.json()
    assert body["auth"]["secrets_exposed"] is False
    assert "api_key_configured" in body["auth"]
    assert body["persistence_backend"]["runtime_editable"] is False
    assert "profiles.fast" in body["runtime_editable"]

    patched = client.patch(
        "/config/models",
        json={
            "profiles": {"fast": "google/gemini-2.5-flash", "balanced": "anthropic/claude-sonnet-4.5"},
            "fallback_models": ["openrouter/auto"],
            "agents": {"query_decomposer": {"model_profile": "fast", "model": "openrouter/auto", "temperature": 0.25, "max_tokens": 512}},
        },
    )
    assert patched.status_code == 200
    config = patched.json()
    assert config["profiles"]["fast"] == "google/gemini-2.5-flash"
    assert config["fallback_models"] == ["openrouter/auto"]
    assert config["agents"]["query_decomposer"]["model"] == "openrouter/auto"
    assert config["agents"]["query_decomposer"]["temperature"] == 0.25
    assert config["status"]["vector_backend"]["kind"] == "local_hash"

    bad_profile = client.patch("/config/models", json={"agents": {"query_decomposer": {"model_profile": "slow"}}})
    assert bad_profile.status_code == 422
    assert bad_profile.json()["error"]["code"] == "validation_error"

    bad_agent = client.patch("/config/models", json={"agents": {"not_an_agent": {"model_profile": "fast"}}})
    assert bad_agent.status_code == 422
