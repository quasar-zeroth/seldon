export type Health = {
  ok: boolean;
  service: string;
  llm_default_model: string;
};

export type Scenario = {
  id: string;
  name: string;
  description: string;
  status: string;
  target_question: string;
  time_horizon: string;
  created_at: string;
  updated_at: string;
};

export type AgentRun = {
  id: string;
  agent_id: string;
  phase?: string | null;
  status: string;
  output?: Record<string, unknown> | null;
  model_invocations?: Array<{ model: string; provider?: string | null; ok: boolean }>;
  created_at: string;
  updated_at: string;
};

export type GraphNode = {
  id: string;
  name: string;
  type: "entity" | "event" | "topic" | "metric" | "policy" | "actor";
  description: string;
  current_state?: string | null;
  kb_entry_ids: string[];
  scenario_ids: string[];
  stability_score: number;
  importance_score: number;
};

export type GraphEdge = {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relationship_type: string;
  description: string;
  strength: number;
  confidence: number;
  lag?: string | null;
  direction: "positive" | "negative" | "complex";
  evidence_kb_ids: string[];
  scenario_ids: string[];
};

export type ScenarioPrediction = {
  id: string;
  scenario_id?: string | null;
  statement: string;
  scope: string;
  timeframe: string;
  resolution_criteria: string;
  scenarios: Array<{ outcome?: string; probability?: number; confidence?: number; key_drivers?: string[]; key_assumptions?: string[]; stability?: string; reasoning_trace?: string }>;
  probabilities: Record<string, number>;
  confidence: number;
  key_drivers: string[];
  evidence_links: string[];
  assumptions: string[];
  probability_history: Array<Record<string, string | number>>;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ModelConfig = {
  profiles: Record<"fast" | "balanced" | "reasoning" | "embedding", string>;
  fallback_models: string[];
  agents: Record<string, { model_profile: string; model?: string | null; temperature?: number | null; max_tokens?: number | null }>;
};

const API_BASE = process.env.NEXT_PUBLIC_SELDON_API_URL ?? "http://localhost:8000";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Seldon API ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function sendJson<T>(method: "POST" | "PATCH", path: string, body: Record<string, unknown> = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Seldon API ${method} ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => getJson<Health>("/health"),
  scenarios: () => getJson<Scenario[]>("/scenarios"),
  runs: () => getJson<AgentRun[]>("/runs"),
  graphNodes: () => getJson<GraphNode[]>("/graph/nodes"),
  graphEdges: () => getJson<GraphEdge[]>("/graph/edges"),
  predictions: () => getJson<ScenarioPrediction[]>("/predictions"),
  modelConfig: () => getJson<ModelConfig>("/config/models"),
  createScenario: (body: { name: string; target_question: string; time_horizon?: string; description?: string }) => sendJson<Scenario>("POST", "/scenarios", body),
  enqueuePhase: (scenarioId: string, phase: "context_gathering" | "extraction" | "graph_construction" | "prediction", body: Record<string, unknown> = {}) => sendJson<Record<string, unknown>>("POST", `/scenarios/${scenarioId}/jobs/${phase}`, body),
  retryRun: (runId: string) => sendJson<Record<string, unknown>>("POST", `/runs/${runId}/retry`),
  runAdvanced: (predictionId: string) => sendJson<Record<string, unknown>>("POST", `/predictions/${predictionId}/run-advanced-intelligence`),
};
