import { getJson, sendJson } from "./client";
import type { Health, ModelConfig } from "./types";
export const settingsApi = { health: () => getJson<Health>("/health"), modelConfig: () => getJson<ModelConfig>("/config/models"), patchModelConfig: (body: Record<string, unknown>) => sendJson<ModelConfig>("PATCH", "/config/models", body) };
