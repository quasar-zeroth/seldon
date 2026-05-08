import Link from "next/link";
import { revalidatePath } from "next/cache";
import { PageHeader, Card, EmptyState, EndpointList, RunStatus, ConfirmMutationDialog, EvidencePill, AuditTrail, StatusBadge } from "../../../src/components/ui";
import { runsApi } from "../../../src/lib/api";
import type { AgentRun, ModelInvocation } from "../../../src/lib/api/types";

async function retryAction(formData: FormData) {
  "use server";
  const id = String(formData.get("run_id") || "").trim();
  if (!id) return;
  await runsApi.retry(id);
  revalidatePath(`/runs/${id}`);
  revalidatePath("/runs");
}

function tokens(invocation: ModelInvocation) {
  const usage = invocation.usage ?? {};
  return Number(invocation.total_tokens ?? usage.total_tokens ?? usage.total ?? 0);
}

function scenarioId(run: AgentRun) {
  const input = run.input ?? {};
  const payload = input.payload && typeof input.payload === "object" ? input.payload as Record<string, unknown> : {};
  return String(input.scenario_id ?? payload.scenario_id ?? "");
}

export default async function RunDetail({ params }: { params: { id: string } }) {
  const [run, messages, related] = await Promise.all([runsApi.get(params.id), runsApi.messages(params.id), runsApi.related(params.id)]);
  const auditItems = related.audit_log.length ? related.audit_log : await runsApi.auditLog(run.id).catch(() => []);

  return <>
    <PageHeader
      title={run.agent_id}
      subtitle={`Run ${run.id} · ${run.phase ?? "no phase"} · ${scenarioId(run) || "no scenario"}`}
      status={<RunStatus status={run.status} />}
      action={<form action={retryAction}><input type="hidden" name="run_id" value={run.id} /><ConfirmMutationDialog label="Retry / re-dispatch run"><button className="button" type="submit">Retry through backend</button></ConfirmMutationDialog></form>}
    />
    <EndpointList endpoints={["GET /runs/{id}", "GET /runs/{id}/messages", "GET /runs/{id}/related", "GET /model-invocations?run_id=", "GET /audit-log", "POST /runs/{id}/retry"]} />
    <section className="wide-grid">
      <Card title="Execution summary">
        <p><strong>Status:</strong> <RunStatus status={run.status} /></p>
        <p className="muted">Created {new Date(run.created_at).toLocaleString()} · updated {new Date(run.updated_at).toLocaleString()} · elapsed {run.elapsed_ms ? `${run.elapsed_ms}ms` : "not recorded"}</p>
        {run.error ? <div className="error-card card"><strong>Error</strong><p>{run.error}</p></div> : <p className="muted">No error recorded.</p>}
        <div className="pill-row">{(run.source_references ?? []).map((ref) => ref.includes("http") ? <a className="pill" key={ref} href={ref} target="_blank" rel="noreferrer">source</a> : <span className="pill" key={ref}>{ref}</span>)}</div>
      </Card>
      <Card title="Input JSON"><pre>{JSON.stringify(run.input ?? {}, null, 2)}</pre></Card>
      <Card title="Output JSON"><pre>{JSON.stringify(run.output ?? {}, null, 2)}</pre></Card>
      <Card title="Model invocations">
        {run.model_invocations?.length ? run.model_invocations.map((m, i) => <div className="stack-row" key={m.id ?? i}>
          <div>
            <strong>{m.model}</strong>
            <p className="muted">Provider {m.provider ?? "unknown"} · {m.ok ? "ok" : "failed"} · {tokens(m)} tokens · latency {m.latency_ms ?? 0}ms · cost {m.estimated_cost ?? 0}</p>
            {m.error ? <p className="muted">Error: {m.error}</p> : null}
          </div>
          <StatusBadge status={m.ok ? "ok" : "failed"} />
        </div>) : <EmptyState detail="No model invocation metadata recorded for this run." />}
      </Card>
      <Card title="Messages">
        {messages.length ? messages.map((message) => <div className="stack-row" key={message.id}><div><strong>{message.role}</strong><p className="muted">{message.content}</p>{Object.keys(message.payload ?? {}).length ? <pre>{JSON.stringify(message.payload, null, 2)}</pre> : null}</div></div>) : <EmptyState detail="No run messages persisted." />}
      </Card>
      <Card title="Related records">
        <h3>KB entries</h3>
        {related.kb_entries.length ? related.kb_entries.map((entry) => <p key={entry.id}><EvidencePill id={entry.id} href={`/kb/${entry.id}`} /> {entry.content.slice(0, 90)}</p>) : <p className="muted">No KB entries referenced by this run.</p>}
        <h3>Graph changes</h3>
        {related.graph_nodes.length || related.graph_edges.length ? <ul>{related.graph_nodes.map((node) => <li key={node.id}><Link href={`/graph?selected_node=${node.id}`}>Node: {node.name}</Link></li>)}{related.graph_edges.map((edge) => <li key={edge.id}><Link href={`/graph?selected_edge=${edge.id}`}>Edge: {edge.relationship_type}</Link></li>)}</ul> : <p className="muted">No graph records referenced.</p>}
        <h3>Predictions and feedback</h3>
        {related.predictions.length ? related.predictions.map((prediction) => <p key={prediction.id}><Link href={`/scenarios/${prediction.scenario_id ?? ""}`}>{prediction.statement}</Link></p>) : <p className="muted">No predictions referenced.</p>}
        {related.feedback_entries.length ? related.feedback_entries.map((feedback) => <pre key={String(feedback.id)}>{JSON.stringify(feedback, null, 2)}</pre>) : <p className="muted">No feedback records referenced.</p>}
      </Card>
      <AuditTrail items={auditItems} />
    </section>
  </>;
}
