import { getJson } from "./client";

export type OpsJob = {
  id: string;
  kind: string;
  status: string;
  payload?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
  completed_at?: string | null;
};

export const jobsApi = {
  list: () => getJson<OpsJob[]>("/ops/jobs"),
  get: (id: string) => getJson<OpsJob>(`/ops/jobs/${id}`),
};
