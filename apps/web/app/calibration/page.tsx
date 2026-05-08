import Link from "next/link";
import { revalidatePath } from "next/cache";
import { PageHeader, Card, EmptyState, EndpointList, MetricCard, StatusBadge, ConfirmMutationDialog } from "../../src/components/ui";
import { CalibrationAnalyticsCharts } from "../../src/components/charts-dashboard";
import { calibrationApi, predictionsApi, scenariosApi, analyticsApi } from "../../src/lib/api";
import type { CalibrationBucket, FeedbackEntry, OutcomeCheck, ScenarioPrediction } from "../../src/lib/api/types";

function csv(value: FormDataEntryValue | null) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function parseGraphCorrections(value: FormDataEntryValue | null) {
  const raw = String(value || "").trim();
  if (!raw) return [];
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed)) throw new Error("Graph corrections must be a JSON array.");
  return parsed as Array<Record<string, unknown>>;
}

async function resolvePredictionAction(formData: FormData) {
  "use server";
  const predictionId = String(formData.get("prediction_id") || "").trim();
  const actualOutcome = String(formData.get("actual_outcome") || "").trim();
  const resolvedOutcomeKey = String(formData.get("resolved_outcome_key") || "").trim();
  if (!predictionId || !actualOutcome || !resolvedOutcomeKey) return;
  await calibrationApi.resolvePrediction(predictionId, {
    actual_outcome: actualOutcome,
    resolved_outcome_key: resolvedOutcomeKey,
    resolution_confidence: Number(formData.get("resolution_confidence") || 1),
    source_references: csv(formData.get("source_references")),
    notes: String(formData.get("notes") || ""),
    missed_factors: csv(formData.get("missed_factors")),
    failed_assumptions: csv(formData.get("failed_assumptions")),
    graph_corrections: parseGraphCorrections(formData.get("graph_corrections")),
    update_kb: formData.get("update_kb") === "on",
    trigger_reprediction: formData.get("trigger_reprediction") === "on",
  });
  revalidatePath("/calibration");
}

function percent(value?: number | null) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function score(value?: number | null) {
  return value == null ? "—" : Number(value).toFixed(3);
}

function probabilityKeys(prediction?: ScenarioPrediction) {
  return Object.keys(prediction?.probabilities ?? {});
}

function PredictionPicker({ predictions }: { predictions: ScenarioPrediction[] }) {
  return <select name="prediction_id" required>
    <option value="">Choose active/draft prediction</option>
    {predictions.filter((prediction) => prediction.status !== "resolved").map((prediction) => <option key={prediction.id} value={prediction.id}>{prediction.statement.slice(0, 90)} · {prediction.id.slice(0, 8)}</option>)}
  </select>;
}

function CalibrationChart({ buckets }: { buckets: CalibrationBucket[] }) {
  if (!buckets.length) return <EmptyState detail="Resolve predictions through feedback to populate the confidence vs observed frequency chart." />;
  return <div className="calibration-chart" aria-label="bucketed confidence vs observed frequency chart">
    {buckets.map((bucket) => <div className="calibration-row" key={bucket.bucket}>
      <span>{bucket.bucket}</span>
      <div><i style={{ width: `${Math.round(bucket.average_confidence * 100)}%` }} /><b style={{ width: `${Math.round(bucket.empirical_accuracy * 100)}%` }} /></div>
      <small>{bucket.count} sample(s) · forecast {percent(bucket.average_confidence)} · observed {percent(bucket.empirical_accuracy)}</small>
    </div>)}
    <p className="muted">Blue shows average forecast confidence; violet shows observed frequency.</p>
  </div>;
}

function MissAnalysis({ entries }: { entries: FeedbackEntry[] }) {
  const misses = entries.filter((entry) => entry.missed_factors?.length || entry.comparison || entry.lessons_learned);
  if (!misses.length) return <EmptyState detail="Root-cause analysis records will appear after feedback is submitted." />;
  return <div>{misses.map((entry) => <details className="timeline-item" key={entry.id}>
    <summary>{entry.comparison || "Root-cause analysis"}</summary>
    <p className="muted">Prediction {entry.prediction_id ? <Link href={`/scenarios/${entry.scenario_id ?? ""}`}>{entry.prediction_id.slice(0, 8)}</Link> : "not linked"} · {new Date(entry.recorded_at).toLocaleString()}</p>
    {entry.missed_factors?.length ? <p>Missed factors: {entry.missed_factors.join(", ")}</p> : null}
    {entry.lessons_learned ? <p className="muted">{entry.lessons_learned}</p> : null}
    {entry.graph_corrections?.length ? <pre>{JSON.stringify(entry.graph_corrections, null, 2)}</pre> : null}
  </details>)}</div>;
}

function ResolvedTable({ predictions, checks }: { predictions: ScenarioPrediction[]; checks: OutcomeCheck[] }) {
  const resolved = predictions.filter((prediction) => prediction.status === "resolved" || prediction.outcome);
  if (!resolved.length) return <EmptyState detail="No resolved predictions yet. Use the resolution form to record the actual outcome." />;
  return <div className="table-list">{resolved.map((prediction) => {
    const check = checks.find((item) => item.prediction_id === prediction.id);
    return <div className="stack-row" key={prediction.id}>
      <div>
        <strong>{prediction.statement}</strong>
        <p className="muted">Outcome: {String(prediction.outcome?.actual_outcome ?? check?.actual_outcome ?? "recorded")}</p>
        <p className="muted">Resolved key {String(prediction.outcome?.resolved_outcome_key ?? check?.resolved_outcome_key ?? "—")} · probability assigned {percent(check?.probability_assigned)}</p>
      </div>
      <StatusBadge status={prediction.status} />
    </div>;
  })}</div>;
}

export default async function CalibrationPage() {
  const [summary, predictions, feedbackEntries, outcomeChecks, scenarios, analytics] = await Promise.all([
    calibrationApi.summary(),
    predictionsApi.list(),
    calibrationApi.feedbackEntries(),
    calibrationApi.outcomeChecks(),
    scenariosApi.list(),
    analyticsApi.charts(),
  ]);
  const buckets = (summary.calibration_buckets ?? summary.buckets ?? []) as CalibrationBucket[];
  const resolvedCount = summary.resolved_predictions ?? outcomeChecks.length;
  const lowSample = resolvedCount < 20;
  const lastCheck = outcomeChecks[0]?.checked_at ? new Date(outcomeChecks[0].checked_at) : null;
  const stale = lastCheck ? Date.now() - lastCheck.getTime() > 1000 * 60 * 60 * 24 * 30 : false;

  return <>
    <PageHeader title="Calibration" subtitle="Resolve outcomes, inspect feedback/root-cause records, and watch backend calibration update from persisted prediction state." />
    <EndpointList endpoints={["GET /calibration/summary", "GET /feedback-entries", "GET /outcome-checks", "GET /analytics/charts", "POST /predictions/{id}/resolve", "POST /scenarios/{scenario_id}/run-feedback"]} />
    <section className="grid">
      <MetricCard label="Resolved predictions" value={String(resolvedCount)} hint={`${predictions.length} total prediction(s) loaded`} />
      <MetricCard label="Brier score" value={score(summary.brier_score)} hint="Lower is better; 0 is perfect." />
      <MetricCard label="Log score" value={score(summary.log_score)} hint="Penalizes overconfident misses." />
    </section>
    <div className="pill-row">
      {lowSample ? <span className="pill warning">Low sample size: calibration is directional until ~20+ resolutions</span> : null}
      {stale ? <span className="pill warning">Stale calibration: no outcome check in 30+ days</span> : null}
      {!outcomeChecks.length ? <span className="pill warning">No resolved outcomes yet</span> : null}
    </div>

    <section className="wide-grid">
      <Card title="Calibration charts and analytical visualizations">
        <CalibrationAnalyticsCharts analytics={analytics} />
        <details className="timeline-item"><summary>Raw confidence bucket fallback</summary><CalibrationChart buckets={buckets} /></details>
      </Card>
      <Card title="Resolve prediction with feedback">
        <form action={resolvePredictionAction} className="form-stack">
          <PredictionPicker predictions={predictions} />
          <input name="resolved_outcome_key" placeholder="Resolved outcome key, e.g. bull/base/bear" list="outcome-keys" required />
          <datalist id="outcome-keys">{predictions.flatMap(probabilityKeys).map((key) => <option key={key} value={key} />)}</datalist>
          <textarea name="actual_outcome" placeholder="Actual outcome / resolution evidence" rows={3} required />
          <input name="resolution_confidence" type="number" min="0" max="1" step="0.05" defaultValue="1" />
          <input name="source_references" placeholder="Source references, comma-separated URLs/IDs" />
          <input name="missed_factors" placeholder="Missed factors, comma-separated" />
          <input name="failed_assumptions" placeholder="Failed assumptions, comma-separated" />
          <textarea name="notes" placeholder="Root-cause notes / lessons" rows={3} />
          <ConfirmMutationDialog label="Submit graph corrections">
            <textarea name="graph_corrections" placeholder='[{"action":"modify_edge","details":{"id":"...","confidence":0.4}}]' rows={4} />
          </ConfirmMutationDialog>
          <label className="muted"><input name="update_kb" type="checkbox" defaultChecked /> Persist feedback correction to KB</label>
          <label className="muted"><input name="trigger_reprediction" type="checkbox" /> Trigger re-prediction when stale or corrected assumptions need a refresh</label>
          <button className="button" type="submit">Resolve and recalibrate</button>
        </form>
        <p className="muted">Loaded {scenarios.length} scenario(s). The backend records an outcome check, feedback entry, audit records, optional graph corrections, and optional re-prediction job.</p>
      </Card>
    </section>

    <section className="wide-grid">
      <Card title="Resolved predictions table"><ResolvedTable predictions={predictions} checks={outcomeChecks} /></Card>
      <Card title="Miss analysis and root-cause detail drawer"><MissAnalysis entries={feedbackEntries} /></Card>
    </section>
  </>;
}
