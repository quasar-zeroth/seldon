import { getJson } from "./client";
import type { ChartAnalytics } from "./types";

export const analyticsApi = {
  charts: (scenarioId?: string) => getJson<ChartAnalytics>(`/analytics/charts${scenarioId ? `?scenario_id=${encodeURIComponent(scenarioId)}` : ""}`),
};
