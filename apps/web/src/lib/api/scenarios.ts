import { getJson, sendJson } from "./client";
import type { Scenario } from "./types";
export const scenariosApi = {
  list: () => getJson<Scenario[]>("/scenarios"),
  get: (id: string) => getJson<Scenario>(`/scenarios/${id}`),
  create: (body: { name: string; target_question: string; time_horizon?: string; description?: string }) => sendJson<Scenario>("POST", "/scenarios", body),
  update: (id: string, body: Partial<Scenario>) => sendJson<Scenario>("PATCH", `/scenarios/${id}`, body),
  enqueuePhase: (id: string, phase: "context_gathering" | "extraction" | "graph_construction" | "prediction", body: Record<string, unknown> = {}) => sendJson<Record<string, unknown>>("POST", `/scenarios/${id}/jobs/${phase}`, body),
};
