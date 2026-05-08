import { revalidatePath } from "next/cache";
import Link from "next/link";
import { redirect } from "next/navigation";
import { PageHeader, Card, EmptyState, EndpointList, StatusBadge, EvidencePill, RunStatus, ConfirmMutationDialog, MetricCard } from "../../../src/components/ui";
import { scenariosApi, predictionsApi, runsApi, graphApi, jobsApi, type ScenarioPrediction } from "../../../src/lib/api";

const phases = ["context_gathering", "extraction", "graph_construction", "prediction"] as const;

async function editScenarioAction(formData: FormData) {
  "use server";
  const id = String(formData.get("scenario_id"));
  await scenariosApi.update(id, {
    name: String(formData.get("name") || ""),
    target_question: String(formData.get("target_question") || ""),
    description: String(formData.get("description") || ""),
    time_horizon: String(formData.get("time_horizon") || ""),
    status: String(formData.get("status") || "active"),
  });
  revalidatePath(`/scenarios/${id}`);
}

async function enqueuePhaseAction(formData: FormData) {
  "use server";
  const id = String(formData.get("scenario_id"));
  const phase = String(formData.get("phase")) as (typeof phases)[number];
  const job = await scenariosApi.enqueuePhase(id, phase);
  redirect(`/scenarios/${id}?job_id=${encodeURIComponent(String(job.id ?? ""))}`);
}

async function advancedAction(formData: FormData) {
  "use server";
  const scenarioId = String(formData.get("scenario_id"));
  const predictionId = String(formData.get("prediction_id"));
  const run = await predictionsApi.runAdvanced(predictionId);
  redirect(`/scenarios/${scenarioId}?advanced_run=${encodeURIComponent(String(run.id ?? ""))}`);
}

async function feedbackAction(formData: FormData) {
  "use server";
  const scenarioId = String(formData.get("scenario_id"));
  const predictionId = String(formData.get("prediction_id"));
  await scenariosApi.runFeedback(scenarioId, {
    prediction_id: predictionId,
    actual_outcome: String(formData.get("actual_outcome") || ""),
    resolved_outcome_key: String(formData.get("resolved_outcome_key") || "base"),
    notes: String(formData.get("notes") || ""),
  });
  revalidatePath(`/scenarios/${scenarioId}`);
}

function probabilityEntries(prediction?: ScenarioPrediction) {
  if (!prediction) return [];
  const fromMap = Object.entries(prediction.probabilities ?? {}).map(([label, value]) => ({ label, probability: Number(value), confidence: prediction.confidence }));
  if (fromMap.length) return fromMap;
  return prediction.scenarios.map((item, index) => ({ label: item.outcome ?? `Branch ${index + 1}`, probability: Number(item.probability ?? 0), confidence: Number(item.confidence ?? prediction.confidence) }));
}

export default async function ScenarioDetail({ params, searchParams }: { params: { id: string }; searchParams?: { job_id?: string; advanced_run?: string } }) {
  const [scenario, predictions, runs, nodes, jobs] = await Promise.all([
    scenariosApi.get(params.id),
    predictionsApi.list(params.id),
    runsApi.list(),
    graphApi.nodes(),
    jobsApi.list(),
  ]);
  const latest = predictions[0];
  const [versions, evidenceRows] = latest ? await Promise.all([predictionsApi.versions(latest.id), predictionsApi.evidence(latest.id)]) : [[], []];
  const scopedRuns = runs.filter((run) => run.input?.scenario_id === params.id || predictions.some((prediction) => prediction.id === run.input?.prediction_id));
  const scopedJobs = jobs.filter((job) => job.payload?.scenario_id === params.id || job.id === searchParams?.job_id);
  const scopedNodes = nodes.filter((node) => node.scenario_ids.includes(params.id));
  const probabilities = probabilityEntries(latest);

  return <>
    <PageHeader
      title={scenario.name}
      subtitle={scenario.target_question}
      status={<StatusBadge status={scenario.status} />}
      action={<a className="button" href={scenariosApi.reportHref(scenario.id)}>Download backend report</a>}
    />
    <EndpointList endpoints={["GET /scenarios/{id}", "PATCH /scenarios/{id}", "GET /predictions?scenario_id=...", "GET /predictions/{id}/versions", "GET /predictions/{id}/evidence", "POST /scenarios/{id}/jobs/{phase}", "GET /ops/jobs", "GET /runs", "POST /predictions/{id}/run-advanced-intelligence", "POST /scenarios/{id}/run-feedback", "GET /scenarios/{id}/report"]} />
    <section className="grid">
      <MetricCard label="Timeframe" value={latest?.timeframe || scenario.time_horizon || "—"} />
      <MetricCard label="Confidence" value={latest ? `${Math.round(latest.confidence * 100)}%` : "—"} />
      <MetricCard label="Predictions" value={predictions.length} />
      <MetricCard label="Related runs" value={scopedRuns.length} />
    </section>
    <section className="wide-grid">
      <Card title="Edit scenario metadata">
        <form action={editScenarioAction} className="form-stack">
          <input type="hidden" name="scenario_id" value={scenario.id} />
          <input name="name" defaultValue={scenario.name} />
          <textarea name="target_question" defaultValue={scenario.target_question} rows={3} />
          <textarea name="description" defaultValue={scenario.description} rows={3} />
          <input name="time_horizon" defaultValue={scenario.time_horizon} />
          <select name="status" defaultValue={scenario.status}>
            <option value="active">Active</option><option value="paused">Paused</option><option value="completed">Completed</option><option value="archived">Archived</option>
          </select>
          <button className="button" type="submit">Save metadata</button>
        </form>
      </Card>
      <Card title="Run workflow phase">
        <form action={enqueuePhaseAction} className="form-stack">
          <input type="hidden" name="scenario_id" value={scenario.id} />
          <select name="phase">{phases.map((phase) => <option key={phase} value={phase}>{phase.replaceAll("_", " ")}</option>)}</select>
          <ConfirmMutationDialog label="Queue persisted phase job"><button className="button" type="submit">Queue phase</button></ConfirmMutationDialog>
        </form>
        {searchParams?.job_id ? <p className="muted">Queued job {searchParams.job_id}. Refresh to follow persisted job status.</p> : null}
      </Card>
      <Card title="Latest prediction">
        {latest ? <>
          <strong>{latest.statement}</strong>
          <p className="muted">Scope: {latest.scope || "not set"} · Status: {latest.status}</p>
          <p className="muted">Resolution: {latest.resolution_criteria || "No criteria recorded."}</p>
          <div className="probability-list">{probabilities.map((item) => <div className="probability-row" key={item.label}><span>{item.label}</span><div><i style={{ width: `${Math.max(0, Math.min(100, item.probability * 100))}%` }} /></div><strong>{Math.round(item.probability * 100)}%</strong></div>)}</div>
        </> : <EmptyState detail="No prediction has been generated for this scenario. Queue the prediction phase when evidence and graph context are ready." />}
      </Card>
      <Card title="Evidence chain">
        {latest?.evidence_links.length || evidenceRows.length ? <div className="pill-row">{[...latest.evidence_links, ...evidenceRows.map((row) => String(row.kb_entry_id ?? ""))].filter(Boolean).slice(0, 12).map((id) => <EvidencePill key={id} id={id} href={`/kb/${id}`} />)}</div> : <EmptyState detail="No KB evidence links have been attached to the latest prediction." />}
      </Card>
      <Card title="Assumptions registry preview">
        {latest?.assumptions.length ? <ul>{latest.assumptions.slice(0, 8).map((assumption) => <li key={assumption}>{assumption}</li>)}</ul> : <EmptyState detail="Prediction assumptions will appear here once a prediction is synthesized." />}
      </Card>
      <Card title="Advanced intelligence and feedback">
        {latest ? <div className="form-stack">
          <form action={advancedAction}><input type="hidden" name="scenario_id" value={scenario.id} /><input type="hidden" name="prediction_id" value={latest.id} /><button className="button" type="submit">Run advanced intelligence</button></form>
          {searchParams?.advanced_run ? <p className="muted">Advanced run queued: {searchParams.advanced_run}</p> : null}
          <form action={feedbackAction} className="form-stack"><input type="hidden" name="scenario_id" value={scenario.id} /><input type="hidden" name="prediction_id" value={latest.id} /><input name="actual_outcome" placeholder="Actual outcome" required /><select name="resolved_outcome_key"><option value="bull">Bull</option><option value="base">Base</option><option value="bear">Bear</option></select><textarea name="notes" placeholder="Feedback notes" rows={2} /><ConfirmMutationDialog label="Resolve prediction with feedback"><button className="button" type="submit">Run feedback</button></ConfirmMutationDialog></form>
        </div> : <EmptyState detail="Generate a prediction before running advanced intelligence or feedback." />}
      </Card>
      <Card title="Scenario history and versions">
        {latest?.probability_history.length ? latest.probability_history.map((point, index) => <pre key={index}>{JSON.stringify(point, null, 2)}</pre>) : <p className="muted">No probability history stored yet.</p>}
        {versions.length ? versions.map((version, index) => <p className="muted" key={String(version.id ?? index)}>Prediction version {String(version.version ?? index + 1)}</p>) : <p className="muted">No prediction version records yet.</p>}
      </Card>
      <Card title="Related agent runs and jobs">
        {scopedJobs.length ? scopedJobs.slice(0, 8).map((job) => <div className="row" key={job.id}><span>{job.kind} job</span><RunStatus status={job.status} /></div>) : <p className="muted">No persisted jobs associated with this scenario yet.</p>}
        {scopedRuns.length ? scopedRuns.slice(0, 8).map((run) => <div className="row" key={run.id}><Link href={`/runs/${run.id}`}>{run.agent_id}</Link><RunStatus status={run.status} /></div>) : <EmptyState detail="No agent runs found yet." />}
      </Card>
      <Card title="Related graph nodes">
        {scopedNodes.length ? <div className="pill-row">{scopedNodes.slice(0, 16).map((node) => <span className={`pill ${node.type}`} key={node.id}>{node.type}: {node.name}</span>)}</div> : <EmptyState detail="Run extraction/graph construction to attach nodes." />}
      </Card>
    </section>
  </>;
}
