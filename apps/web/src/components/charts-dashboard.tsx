"use client";

import type { ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { EmptyState } from "./ui";
import type { CalibrationBucket, ChartAnalytics, ScenarioPrediction } from "../lib/api/types";

type ChartCardProps = { title: string; detail?: string; children: ReactNode };

function ChartCard({ title, detail, children }: ChartCardProps) {
  return <div className="chart-card"><h3>{title}</h3>{detail ? <p className="muted">{detail}</p> : null}<div className="chart-frame">{children}</div></div>;
}

function n(value: unknown, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function labelDate(value: unknown, fallback: string) {
  const raw = String(value ?? "");
  if (!raw) return fallback;
  const date = new Date(raw);
  return Number.isNaN(date.getTime()) ? raw : date.toLocaleDateString();
}

function probabilityHistoryRows(prediction?: ScenarioPrediction, analytics?: ChartAnalytics) {
  const rows = (analytics?.probability_history ?? []).filter((row) => !prediction || row.prediction_id === prediction.id);
  if (rows.length) {
    return rows.map((row, index) => ({
      label: labelDate(row.timestamp ?? row.created_at ?? row.updated_at ?? row.date, `Point ${index + 1}`),
      bull: n(row.bull),
      base: n(row.base),
      bear: n(row.bear),
      confidence: n(row.confidence, prediction?.confidence ?? 0),
    }));
  }
  if (!prediction?.probability_history?.length) return [];
  return prediction.probability_history.map((row, index) => ({
    label: labelDate(row.timestamp ?? row.created_at ?? row.updated_at ?? row.date, `Point ${index + 1}`),
    bull: n(row.bull),
    base: n(row.base),
    bear: n(row.bear),
    confidence: n(row.confidence, prediction.confidence),
  }));
}

function confidenceRows(analytics: ChartAnalytics) {
  return analytics.prediction_confidence.map((row) => ({
    name: row.statement.length > 28 ? `${row.statement.slice(0, 28)}…` : row.statement,
    confidence: Math.round(row.confidence * 100),
    status: row.status,
  }));
}

function calibrationRows(analytics: ChartAnalytics) {
  const buckets = (analytics.calibration.calibration_buckets ?? analytics.calibration.buckets ?? []) as CalibrationBucket[];
  return buckets.map((bucket) => ({
    bucket: bucket.bucket,
    forecast: Math.round(bucket.average_confidence * 100),
    observed: Math.round(bucket.empirical_accuracy * 100),
    count: bucket.count,
    brier: Number(bucket.brier_score.toFixed(3)),
  }));
}

function sentimentRows(analytics: ChartAnalytics) {
  return analytics.sentiment_drift.map((row, index) => ({
    label: `${row.topic} ${labelDate(row.measured_at, String(index + 1))}`,
    sentiment: Number((row.sentiment * 100).toFixed(1)),
    velocity: Number((row.velocity * 100).toFixed(1)),
  }));
}

function uncertaintyRows(analytics: ChartAnalytics) {
  const uncertainty = analytics.uncertainty.map((row, index) => ({
    name: String(row.factor ?? row.name ?? row.dimension ?? `Uncertainty ${index + 1}`).slice(0, 28),
    probability: Math.round(n(row.probability ?? row.likelihood ?? row.score ?? row.uncertainty, 0.5) * 100),
    impact: Math.round(n(row.impact ?? row.severity ?? row.magnitude, 0.5) * 100),
  }));
  const risks = analytics.cascade_risks.map((row, index) => ({
    name: String(row.risk ?? row.name ?? row.trigger ?? `Cascade ${index + 1}`).slice(0, 28),
    probability: Math.round(n(row.probability ?? row.likelihood, 0.5) * 100),
    impact: Math.round(n(row.impact ?? row.severity ?? row.magnitude, 0.6) * 100),
  }));
  return [...uncertainty, ...risks];
}

function modelRows(analytics: ChartAnalytics) {
  return analytics.model_performance.map((row) => ({
    name: `${row.agent}\n${row.model}`.slice(0, 34),
    invocations: row.invocations,
    success: Math.round(row.success_rate * 100),
    latency: Math.round(row.average_latency_ms),
    cost: Number(row.estimated_cost.toFixed(4)),
  }));
}

export function ScenarioAnalyticsCharts({ prediction, analytics }: { prediction?: ScenarioPrediction; analytics: ChartAnalytics }) {
  const history = probabilityHistoryRows(prediction, analytics);
  const confidence = confidenceRows(analytics);
  const uncertainty = uncertaintyRows(analytics);
  return <div className="charts-grid" data-testid="b7-scenario-analytics-charts">
    <ChartCard title="Probability history chart" detail="Persisted probability_history from scenario predictions.">
      {history.length ? <ResponsiveContainer width="100%" height={260}><AreaChart data={history}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis domain={[0, 1]} /><Tooltip /><Legend /><Area dataKey="bull" stackId="1" stroke="#22c55e" fill="#22c55e" fillOpacity={0.35} /><Area dataKey="base" stackId="1" stroke="#60a5fa" fill="#60a5fa" fillOpacity={0.35} /><Area dataKey="bear" stackId="1" stroke="#f97316" fill="#f97316" fillOpacity={0.35} /><Line dataKey="confidence" stroke="#e879f9" /></AreaChart></ResponsiveContainer> : <EmptyState detail="No persisted probability history yet. Generate or refresh a prediction to populate this chart." />}
    </ChartCard>
    <ChartCard title="Prediction confidence chart" detail="Current confidence for backend predictions in this scope.">
      {confidence.length ? <ResponsiveContainer width="100%" height={260}><BarChart data={confidence}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis domain={[0, 100]} /><Tooltip /><Bar dataKey="confidence" fill="#8b5cf6" /></BarChart></ResponsiveContainer> : <EmptyState detail="No prediction confidence records are available yet." />}
    </ChartCard>
    <ChartCard title="Uncertainty / cascade-risk visualization" detail="Advanced analyses drive risk bubbles when available.">
      {uncertainty.length ? <ResponsiveContainer width="100%" height={260}><ScatterChart><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="probability" name="probability" unit="%" domain={[0, 100]} /><YAxis dataKey="impact" name="impact" unit="%" domain={[0, 100]} /><ZAxis range={[80, 420]} /><Tooltip cursor={{ strokeDasharray: "3 3" }} /><Scatter name="Risks" data={uncertainty} fill="#f59e0b">{uncertainty.map((_, index) => <Cell key={index} fill={index % 2 ? "#f59e0b" : "#ef4444"} />)}</Scatter></ScatterChart></ResponsiveContainer> : <EmptyState detail="No advanced uncertainty or cascade-risk records yet. Run advanced intelligence to populate this chart." />}
    </ChartCard>
  </div>;
}

export function CalibrationAnalyticsCharts({ analytics }: { analytics: ChartAnalytics }) {
  const calibration = calibrationRows(analytics);
  const sentiment = sentimentRows(analytics);
  const modelPerformance = modelRows(analytics);
  return <div className="charts-grid" data-testid="b7-calibration-analytics-charts">
    <ChartCard title="Calibration curve and bucket chart" detail="Forecast confidence compared with observed frequency from backend calibration summary.">
      {calibration.length ? <ResponsiveContainer width="100%" height={280}><ComposedChart data={calibration}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="bucket" /><YAxis domain={[0, 100]} /><Tooltip /><Legend /><Bar dataKey="count" fill="#334155" /><Line type="monotone" dataKey="forecast" stroke="#60a5fa" strokeWidth={2} /><Line type="monotone" dataKey="observed" stroke="#a78bfa" strokeWidth={2} /></ComposedChart></ResponsiveContainer> : <EmptyState detail="Insufficient resolved outcomes for a calibration curve. Resolve predictions to add buckets." />}
    </ChartCard>
    <ChartCard title="Sentiment drift chart" detail="Persisted sentiment_drift rows by topic and measurement time.">
      {sentiment.length ? <ResponsiveContainer width="100%" height={280}><LineChart data={sentiment}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis domain={[-100, 100]} /><Tooltip /><Legend /><Line type="monotone" dataKey="sentiment" stroke="#22c55e" strokeWidth={2} /><Line type="monotone" dataKey="velocity" stroke="#f97316" strokeWidth={2} /></LineChart></ResponsiveContainer> : <EmptyState detail="No sentiment drift records yet. Advanced intelligence or ingestion can add drift measurements." />}
    </ChartCard>
    <ChartCard title="Model/profile performance by agent type" detail="Aggregated model invocation success, latency, cost, and volume.">
      {modelPerformance.length ? <ResponsiveContainer width="100%" height={280}><BarChart data={modelPerformance}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis /><Tooltip /><Legend /><Bar dataKey="invocations" fill="#60a5fa" /><Bar dataKey="success" fill="#22c55e" /><Bar dataKey="latency" fill="#f59e0b" /></BarChart></ResponsiveContainer> : <EmptyState detail="No model invocation metadata has been recorded yet." />}
    </ChartCard>
  </div>;
}
