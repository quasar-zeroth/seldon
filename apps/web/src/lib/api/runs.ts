import { getJson, sendJson } from "./client";
import type { AgentMessage, AgentRun } from "./types";
export const runsApi = { list: () => getJson<AgentRun[]>("/runs"), get: (id: string) => getJson<AgentRun>(`/runs/${id}`), messages: (id: string) => getJson<AgentMessage[]>(`/runs/${id}/messages`), retry: (id: string) => sendJson<Record<string, unknown>>("POST", `/runs/${id}/retry`) };
