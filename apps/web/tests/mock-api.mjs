import http from "node:http";
import { randomUUID } from "node:crypto";

const now = () => new Date().toISOString();

const scenario = {
  id: "scenario-1",
  name: "Gold outlook",
  description: "Browser-test scenario",
  target_question: "Where will gold trade in 6 months?",
  time_horizon: "6 months",
  status: "active",
  created_at: now(),
  updated_at: now(),
};
const prediction = {
  id: "prediction-1",
  scenario_id: "scenario-1",
  statement: "Gold base case remains constructive.",
  scope: "Gold spot",
  timeframe: "6 months",
  resolution_criteria: "Resolved against spot price range.",
  probabilities: { bull: 0.25, base: 0.55, bear: 0.2 },
  scenarios: [],
  confidence: 0.72,
  assumptions: ["Rates fall"],
  evidence_links: ["kb-1"],
  probability_history: [{ timestamp: now(), bull: 0.25, base: 0.55, bear: 0.2, confidence: 0.72 }],
  status: "active",
  outcome: {},
  calibration_result: {},
  created_at: now(),
  updated_at: now(),
};
const kbEntry = {
  id: "kb-1",
  content: "Central banks continue buying gold.",
  source_type: "news_article",
  source_url: "https://example.test/gold",
  source_name: "Example News",
  original_snippet: "Central bank demand remains resilient.",
  topics: ["gold"],
  entities: ["central banks"],
  scenario_ids: ["scenario-1"],
  perspective_tags: { sentiment: 0.4, confidence: 0.8, geopolitical_lens: "neutral" },
  superseded_by: null,
  version: 1,
  created_at: now(),
  updated_at: now(),
  valid_from: null,
  valid_until: null,
  contradiction_count: 1,
  open_contradiction_count: 1,
  is_current: true,
  decay_score: 0.99,
};
const nodes = [
  { id: "node-1", name: "Fed policy", type: "policy", description: "Federal Reserve policy stance.", current_state: "restrictive", state_updated_at: now(), kb_entry_ids: ["kb-1"], scenario_ids: ["scenario-1"], stability_score: 0.6, importance_score: 0.9, created_at: now(), updated_at: now() },
  { id: "node-2", name: "Gold price", type: "metric", description: "Spot gold price.", current_state: "elevated", state_updated_at: now(), kb_entry_ids: [], scenario_ids: ["scenario-1"], stability_score: 0.5, importance_score: 0.8, created_at: now(), updated_at: now() },
];
const edges = [
  { id: "edge-1", source_node_id: "node-1", target_node_id: "node-2", relationship_type: "opposes", description: "Higher rates pressure gold.", strength: 0.7, confidence: 0.8, lag: "2-4 weeks", direction: "negative", evidence_kb_ids: ["kb-1"], scenario_ids: ["scenario-1"], created_at: now(), updated_at: now() },
];
const run = { id: "run-1", agent_id: "prediction_coordinator", phase: "prediction", status: "failed", input: { scenario_id: "scenario-1" }, output: { prediction_id: "prediction-1" }, error: "retryable", source_references: ["kb-1"], model_invocations: [{ model: "test/model", provider: "mock", usage: { total_tokens: 42 }, estimated_cost: 0.01, ok: false }], created_at: now(), updated_at: now(), elapsed_ms: 1200 };
const job = { id: "job-1", kind: "phase", status: "queued", payload: { scenario_id: "scenario-1" }, result: null, error: null, created_at: now(), updated_at: now() };
const configStatus = {
  source_configuration: { configured_sources: "database", runtime_editable: false },
  persistence_backend: { kind: "sqlite", sqlite_path: "/tmp/seldon.db", runtime_editable: false },
  vector_backend: { kind: "local_hash", index_path: "/tmp/vector.json", runtime_editable: false },
  auth: { api_key_required: false, api_key_configured: false, secrets_exposed: false },
  runtime_editable: ["profiles.fast", "fallback_models", "agents.*.model_profile"],
  deploy_time: ["database", "auth secrets"],
};
const modelConfig = {
  profiles: { fast: "mock/fast", balanced: "mock/balanced", reasoning: "mock/reasoning", embedding: "mock/embedding" },
  fallback_models: ["openrouter/auto"],
  agents: { query_decomposer: { model_profile: "fast", model: null, temperature: null, max_tokens: null } },
  status: configStatus,
};

function json(res, status, body) {
  res.writeHead(status, { "content-type": "application/json", "access-control-allow-origin": "*", "access-control-allow-headers": "content-type,x-seldon-api-key,authorization", "access-control-allow-methods": "GET,POST,PATCH,OPTIONS" });
  res.end(JSON.stringify(body));
}
function text(res, status, body) {
  res.writeHead(status, { "content-type": "text/markdown", "access-control-allow-origin": "*" });
  res.end(body);
}
async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
}

export function createMockApiServer() {
  return http.createServer(async (req, res) => {
    if (!req.url) return json(res, 404, { error: "missing url" });
    if (req.method === "OPTIONS") return json(res, 204, {});
    const url = new URL(req.url, "http://127.0.0.1");
    const path = url.pathname;
    try {
      if (path === "/health") return json(res, 200, { ok: true, service: "seldon-api", llm_default_model: "mock/balanced" });
      if (path === "/config/status") return json(res, 200, configStatus);
      if (path === "/config/models" && req.method === "GET") return json(res, 200, modelConfig);
      if (path === "/config/models" && req.method === "PATCH") return json(res, 200, { ...modelConfig, ...(await readJson(req)) });
      if (path === "/scenarios" && req.method === "GET") return json(res, 200, [scenario]);
      if (path === "/scenarios" && req.method === "POST") return json(res, 201, { ...scenario, ...(await readJson(req)), id: "scenario-created", created_at: now(), updated_at: now() });
      if (path === "/scenarios/scenario-1") return json(res, req.method === "PATCH" ? 200 : 200, req.method === "PATCH" ? { ...scenario, ...(await readJson(req)), updated_at: now() } : scenario);
      if (path === "/scenarios/scenario-created") return json(res, 200, { ...scenario, id: "scenario-created", name: "Created in browser" });
      if (path === "/scenarios/scenario-1/report") return text(res, 200, "# Gold outlook\n\nGold base case remains constructive.\n");
      if (path === "/scenarios/scenario-1/jobs/context_gathering" || path.startsWith("/scenarios/scenario-1/jobs/")) return json(res, 202, { ...job, id: `job-${randomUUID()}`, status: "queued" });
      if (path === "/scenarios/scenario-1/run-feedback") return json(res, 202, { agent_run_id: "run-feedback-1", feedback: { outcome_check: { resolved_outcome_key: "base" } } });
      if (path === "/predictions") return json(res, 200, [prediction]);
      if (path === "/predictions/prediction-1") return json(res, 200, prediction);
      if (path === "/predictions/prediction-1/versions") return json(res, 200, [{ id: "version-1", version: 1 }]);
      if (path === "/predictions/prediction-1/evidence") return json(res, 200, [{ id: "evidence-1", kb_entry_id: "kb-1" }]);
      if (path === "/predictions/prediction-1/run-advanced-intelligence") return json(res, 202, { id: "advanced-run-1", status: "pending" });
      if (path === "/predictions/prediction-1/resolve") return json(res, 202, { prediction: { ...prediction, status: "resolved" }, feedback: { outcome_check: { resolved_outcome_key: "base" } } });
      if (path === "/kb/search") return json(res, 200, [kbEntry]);
      if (path === "/kb/entries" && req.method === "POST") return json(res, 201, { ...kbEntry, ...(await readJson(req)), id: "kb-created" });
      if (path === "/kb/entries/kb-1") return json(res, req.method === "PATCH" ? 200 : 200, req.method === "PATCH" ? { ...kbEntry, ...(await readJson(req)), updated_at: now() } : kbEntry);
      if (path === "/kb/entries/kb-1/versions") return json(res, 200, [{ id: "kb-version-1", kb_entry_id: "kb-1", version: 1 }]);
      if (path === "/kb/entries/kb-1/contradictions") return json(res, 200, [{ id: "contradiction-1", kb_entry_id: "kb-1", contradicts_kb_entry_id: "kb-2", description: "conflict", status: "open" }]);
      if (path === "/kb/entries/kb-1/related") return json(res, 200, { scenarios: [scenario], graph_nodes: nodes, graph_edges: edges, predictions: [prediction], evidence_links: [] });
      if (path === "/kb/contradictions") return json(res, 201, { id: "contradiction-created", ...(await readJson(req)), status: "open" });
      if (path === "/kb/contradictions/contradiction-1") return json(res, 200, { id: "contradiction-1", ...(await readJson(req)) });
      if (path === "/kb/entries/kb-1/supersede/kb-1") return json(res, 200, { ...kbEntry, superseded_by: "kb-1" });
      if (path === "/graph/nodes") return json(res, 200, nodes);
      if (path === "/graph/edges") return json(res, 200, edges);
      if (path === "/graph/nodes/node-1") return json(res, 200, req.method === "PATCH" ? { ...nodes[0], ...(await readJson(req)) } : nodes[0]);
      if (path === "/graph/edges/edge-1") return json(res, 200, req.method === "PATCH" ? { ...edges[0], ...(await readJson(req)) } : edges[0]);
      if (path === "/graph/neighborhood/node-1") return json(res, 200, { center: nodes[0], nodes, edges });
      if (path === "/graph/snapshots") return json(res, req.method === "POST" ? 201 : 200, req.method === "POST" ? { id: "snapshot-new", created_at: now(), reason: "UI graph snapshot" } : [{ id: "snapshot-2", created_at: now(), reason: "new" }, { id: "snapshot-1", created_at: now(), reason: "old" }]);
      if (path === "/graph/snapshots/snapshot-1/diff/snapshot-2") return json(res, 200, { added_nodes: [], removed_nodes: [] });
      if (path === "/graph/reuse-candidates/scenario-1") return json(res, 200, { nodes, edges });
      if (path.startsWith("/graph/merge-proposals/")) return json(res, 202, { proposal_id: path.split("/")[3], status: path.endsWith("approve") ? "approved" : "rejected" });
      if (path === "/runs") return json(res, 200, [run]);
      if (path === "/runs/run-1") return json(res, 200, run);
      if (path === "/runs/run-1/messages") return json(res, 200, [{ id: "message-1", agent_run_id: "run-1", role: "assistant", content: "Created prediction", created_at: now() }]);
      if (path === "/runs/run-1/related") return json(res, 200, { kb_entries: [kbEntry], graph_nodes: nodes, graph_edges: edges, predictions: [prediction], feedback_entries: [], audit_log: [] });
      if (path === "/runs/run-1/retry") return json(res, 202, { ...run, id: "run-retry-1", status: "pending" });
      if (path === "/audit-log") return json(res, 200, []);
      if (path === "/ops/jobs") return json(res, 200, [job]);
      if (path === "/ops/jobs/job-1") return json(res, 200, job);
      if (path === "/calibration/summary") return json(res, 200, { resolved_predictions: 1, brier_score: 0.18, log_score: 0.6, buckets: [{ bucket: "50-75", average_confidence: 0.6, empirical_accuracy: 1, brier_score: 0.18, count: 1 }], low_sample_size: true });
      if (path === "/feedback-entries") return json(res, 200, [{ id: "feedback-1", prediction_id: "prediction-1", scenario_id: "scenario-1", missed_factors: ["policy shock"], lessons_learned: "watch rates", graph_corrections: [], recorded_at: now(), created_at: now() }]);
      if (path === "/outcome-checks") return json(res, 200, [{ id: "outcome-1", prediction_id: "prediction-1", resolved_outcome_key: "base", actual_outcome: "base happened", probability_assigned: 0.55, checked_at: now(), created_at: now() }]);
      if (path === "/analytics/charts") return json(res, 200, { scenario_id: url.searchParams.get("scenario_id"), probability_history: prediction.probability_history.map((row) => ({ ...row, prediction_id: "prediction-1" })), prediction_confidence: [{ prediction_id: "prediction-1", statement: prediction.statement, confidence: 0.72, status: "active" }], calibration: { buckets: [{ bucket: "50-75", average_confidence: 0.6, empirical_accuracy: 1, brier_score: 0.18, count: 1 }] }, sentiment_drift: [{ topic: "gold", measured_at: now(), sentiment: 0.3, previous_sentiment: 0.1, velocity: 0.2 }], uncertainty: [{ factor: "rates", probability: 0.35, impact: 0.8 }], cascade_risks: [{ risk: "liquidity shock", probability: 0.2, impact: 0.7 }], model_performance: [{ agent: "prediction_coordinator", model: "test/model", invocations: 2, estimated_cost: 0.01, average_latency_ms: 1200, success_rate: 0.5 }] });
      return json(res, 404, { error: { code: "not_found", message: path } });
    } catch (error) {
      return json(res, 500, { error: String(error) });
    }
  });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.env.MOCK_SELDON_API_PORT || 43111);
  createMockApiServer().listen(port, "127.0.0.1", () => console.log(`Mock Seldon API listening on ${port}`));
}
