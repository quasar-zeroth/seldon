import { getJson } from "./client";
import type { CalibrationSummary } from "./types";
export const calibrationApi = { summary: () => getJson<CalibrationSummary>("/calibration/summary") };
