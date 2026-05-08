import { getJson, sendJson } from "./client";
import type { GraphEdge, GraphNode, KBContradiction, KBEntry, KBRelatedRecords, Scenario, ScenarioPrediction } from "./types";

export type KBSearchParams = {
  q?: string;
  topic?: string;
  entity?: string;
  source?: string;
  source_type?: string;
  valid_at?: string;
  created_since?: string;
  created_until?: string;
  updated_since?: string;
  updated_until?: string;
  geopolitical_lens?: string;
  min_sentiment?: string;
  max_sentiment?: string;
  min_political_lean?: string;
  max_political_lean?: string;
  min_confidence?: string;
  max_confidence?: string;
  scenario_id?: string;
  current_only?: string;
  semantic?: string;
  sort?: string;
  order?: string;
};

function queryString(params: KBSearchParams = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, value);
  }
  query.set("include_scores", "true");
  return query.toString();
}

export const kbApi = {
  search: (params: KBSearchParams | string = {}) => {
    const query = typeof params === "string" ? queryString({ q: params }) : queryString(params);
    return getJson<KBEntry[]>(`/kb/search?${query}`);
  },
  create: (body: Record<string, unknown>) => sendJson<KBEntry>("POST", "/kb/entries", body),
  get: (id: string) => getJson<KBEntry>(`/kb/entries/${id}`),
  update: (id: string, body: Record<string, unknown>) => sendJson<KBEntry>("PATCH", `/kb/entries/${id}`, body),
  versions: (id: string) => getJson<Record<string, unknown>[]>(`/kb/entries/${id}/versions`),
  contradictions: (id: string) => getJson<KBContradiction[]>(`/kb/entries/${id}/contradictions`),
  createContradiction: (body: Record<string, unknown>) => sendJson<KBContradiction>("POST", "/kb/contradictions", body),
  updateContradiction: (id: string, body: Record<string, unknown>) => sendJson<KBContradiction>("PATCH", `/kb/contradictions/${id}`, body),
  supersede: (id: string, newEntryId: string) => sendJson<KBEntry>("POST", `/kb/entries/${id}/supersede/${newEntryId}`),
  related: (id: string) => getJson<KBRelatedRecords>(`/kb/entries/${id}/related`),
};

export type KBRelated = { scenarios: Scenario[]; graph_nodes: GraphNode[]; graph_edges: GraphEdge[]; predictions: ScenarioPrediction[] };
