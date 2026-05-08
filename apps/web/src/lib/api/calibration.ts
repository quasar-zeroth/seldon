import { getJson, sendJson } from "./client";
import type { CalibrationSummary, FeedbackEntry, OutcomeCheck } from "./types";

export type PredictionResolutionPayload = {
  actual_outcome: string;
  resolved_outcome_key: string;
  resolution_confidence?: number;
  source_references?: string[];
  notes?: string;
  missed_factors?: string[];
  failed_assumptions?: string[];
  graph_corrections?: Array<Record<string, unknown>>;
  update_kb?: boolean;
  trigger_reprediction?: boolean;
};

export const calibrationApi = {
  summary: () => getJson<CalibrationSummary>("/calibration/summary"),
  feedbackEntries: () => getJson<FeedbackEntry[]>("/feedback-entries"),
  outcomeChecks: () => getJson<OutcomeCheck[]>("/outcome-checks"),
  resolvePrediction: (predictionId: string, payload: PredictionResolutionPayload) =>
    sendJson<Record<string, unknown>>("POST", `/predictions/${predictionId}/resolve`, payload),
};
