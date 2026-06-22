import { getJson, sendJson } from "./client";
import type { ConfigStatus, Health, ModelConfig } from "./types";
export const settingsApi = {
  health: () => getJson<Health>("/health"),
  modelConfig: () => getJson<ModelConfig>("/config/models"),
  configStatus: () => getJson<ConfigStatus>("/config/status"),
  patchModelConfig: (body: Record<string, unknown>) => sendJson<ModelConfig>("PATCH", "/config/models", body),
  clearAllData: (confirmation: string) => sendJson<{ cleared: boolean; deleted: Record<string, number>; vector_index_cleared: boolean }>("DELETE", "/ops/data", { confirmation }),
};
