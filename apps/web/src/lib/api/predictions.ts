import { getJson, sendJson } from "./client";
import type { ScenarioPrediction } from "./types";
export const predictionsApi = { list: (scenarioId?: string) => getJson<ScenarioPrediction[]>(`/predictions${scenarioId ? `?scenario_id=${encodeURIComponent(scenarioId)}` : ""}`), get: (id: string) => getJson<ScenarioPrediction>(`/predictions/${id}`), versions: (id: string) => getJson<Record<string, unknown>[]>(`/predictions/${id}/versions`),
  evidence: (id: string) => getJson<Record<string, unknown>[]>(`/predictions/${id}/evidence`),
  runAdvanced: (id: string) => sendJson<Record<string, unknown>>("POST", `/predictions/${id}/run-advanced-intelligence`) };
