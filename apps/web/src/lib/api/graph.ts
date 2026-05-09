import { getJson, sendJson } from "./client";
import type { GraphEdge, GraphNode, GraphSnapshot, MergeProposal } from "./types";

export type GraphFilters = {
  scenario_id?: string;
  type?: string;
  relationship_type?: string;
  direction?: string;
  lag?: string;
  min_confidence?: string;
  min_strength?: string;
  min_importance?: string;
  max_stability?: string;
  min_evidence_count?: string;
  hide_low_confidence?: string;
  selected_node?: string;
  selected_edge?: string;
  overlay?: string;
  layout?: string;
};

function queryString(params: Record<string, string | undefined> = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") query.set(key, value);
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

export const graphApi = {
  nodes: (filters: GraphFilters = {}) => getJson<GraphNode[]>(`/graph/nodes${queryString({ scenario_id: filters.scenario_id, type: filters.type, min_importance: filters.min_importance, max_stability: filters.max_stability })}`),
  node: (id: string) => getJson<GraphNode>(`/graph/nodes/${id}`),
  updateNode: (id: string, body: Record<string, unknown>) => sendJson<GraphNode>("PATCH", `/graph/nodes/${id}`, body),
  edges: (filters: GraphFilters = {}) => getJson<GraphEdge[]>(`/graph/edges${queryString({ node_id: filters.selected_node, scenario_id: filters.scenario_id, relationship_type: filters.relationship_type, direction: filters.direction, lag: filters.lag, min_confidence: filters.hide_low_confidence === "true" ? "0.4" : filters.min_confidence, min_strength: filters.min_strength, min_evidence_count: filters.min_evidence_count })}`),
  edge: (id: string) => getJson<GraphEdge>(`/graph/edges/${id}`),
  updateEdge: (id: string, body: Record<string, unknown>) => sendJson<GraphEdge>("PATCH", `/graph/edges/${id}`, body),
  neighborhood: (nodeId: string) => getJson<{ center: GraphNode; nodes: GraphNode[]; edges: GraphEdge[] }>(`/graph/neighborhood/${nodeId}`),
  snapshots: (scenarioId?: string) => getJson<GraphSnapshot[]>(`/graph/snapshots${queryString({ scenario_id: scenarioId })}`),
  createSnapshot: (body: Record<string, unknown>) => sendJson<GraphSnapshot>("POST", "/graph/snapshots", body),
  diffSnapshots: (olderId: string, newerId: string) => getJson<Record<string, string[]>>(`/graph/snapshots/${olderId}/diff/${newerId}`),
  reuseCandidates: (scenarioId: string, q?: string) => getJson<{ nodes: GraphNode[]; edges: GraphEdge[] }>(`/graph/reuse-candidates/${scenarioId}${queryString({ q })}`),
  mergeProposals: (status?: string) => getJson<MergeProposal[]>(`/graph/merge-proposals${queryString({ status })}`),
  approveMerge: (proposalId: string, body: Record<string, unknown>) => sendJson<Record<string, unknown>>("POST", `/graph/merge-proposals/${proposalId}/approve`, body),
  rejectMerge: (proposalId: string, body: Record<string, unknown>) => sendJson<Record<string, unknown>>("POST", `/graph/merge-proposals/${proposalId}/reject`, body),
};
