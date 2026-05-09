import { BROWSER_API_BASE, getJson, sendJson } from "./client";
import type { Scenario } from "./types";
export const scenariosApi = {
  list: (filters: { q?: string; status?: string } = {}) => {
    const params = new URLSearchParams();
    if (filters.q) params.set("q", filters.q);
    if (filters.status) params.set("status", filters.status);
    const query = params.toString();
    return getJson<Scenario[]>(`/scenarios${query ? `?${query}` : ""}`);
  },
  get: (id: string) => getJson<Scenario>(`/scenarios/${id}`),
  create: (body: { name: string; target_question: string; time_horizon?: string; description?: string }) => sendJson<Scenario>("POST", "/scenarios", body),
  update: (id: string, body: Partial<Scenario>) => sendJson<Scenario>("PATCH", `/scenarios/${id}`, body),
  reportHref: (id: string, format: "markdown" | "json" | "html" = "markdown") => `${BROWSER_API_BASE}/scenarios/${id}/report?format=${format}`,
  enqueuePhase: (id: string, phase: "context_gathering" | "extraction" | "graph_construction" | "prediction", body: Record<string, unknown> = {}) => sendJson<Record<string, unknown>>("POST", `/scenarios/${id}/jobs/${phase}`, body),
  runFeedback: (id: string, body: Record<string, unknown>) => sendJson<Record<string, unknown>>("POST", `/scenarios/${id}/run-feedback`, body),
};
