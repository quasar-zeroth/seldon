import { getJson, sendJson } from "./client";
import type { AgentMessage, AgentRun, AuditLog, RunRelatedRecords } from "./types";

export type RunFilters = {
  scenario_id?: string;
  phase?: string;
  agent?: string;
  status?: string;
  model?: string;
  failure_state?: string;
  created_since?: string;
  created_until?: string;
  group_by?: string;
};

function queryString(params: RunFilters = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "" && key !== "group_by") query.set(key, value);
  }
  const text = query.toString();
  return text ? `?${text}` : "";
}

export const runsApi = {
  list: (filters: RunFilters = {}) => getJson<AgentRun[]>(`/runs${queryString(filters)}`),
  get: (id: string) => getJson<AgentRun>(`/runs/${id}`),
  messages: (id: string) => getJson<AgentMessage[]>(`/runs/${id}/messages`),
  related: (id: string) => getJson<RunRelatedRecords>(`/runs/${id}/related`),
  auditLog: (entityId?: string) => getJson<AuditLog[]>(`/audit-log${entityId ? `?entity_id=${encodeURIComponent(entityId)}` : ""}`),
  retry: (id: string) => sendJson<Record<string, unknown>>("POST", `/runs/${id}/retry`),
};
