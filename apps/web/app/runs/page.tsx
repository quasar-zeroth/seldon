import Link from "next/link";
import { revalidatePath } from "next/cache";
import { PageHeader, Card, EmptyState, EndpointList, RunStatus, ConfirmMutationDialog, StatusBadge } from "../../src/components/ui";
import { runsApi, type RunFilters } from "../../src/lib/api";
import type { AgentRun } from "../../src/lib/api/types";

async function retryRunAction(formData: FormData) {
  "use server";
  const id = String(formData.get("run_id") || "").trim();
  if (!id) return;
  await runsApi.retry(id);
  revalidatePath("/runs");
}

function scenarioId(run: AgentRun) {
  const input = run.input ?? {};
  const payload = input.payload && typeof input.payload === "object" ? input.payload as Record<string, unknown> : {};
  return String(input.scenario_id ?? payload.scenario_id ?? "");
}

function firstModel(run: AgentRun) {
  return run.model_invocations?.[0]?.model ?? "model not recorded";
}

function timelineGroups(runs: AgentRun[], groupBy = "phase") {
  return runs.reduce<Record<string, AgentRun[]>>((groups, run) => {
    const key = groupBy === "scenario" ? scenarioId(run) || "no scenario" : run.phase || "no phase";
    groups[key] = [...(groups[key] ?? []), run];
    return groups;
  }, {});
}

export default async function RunsPage({ searchParams }: { searchParams?: RunFilters }) {
  const filters = searchParams ?? {};
  const runs = await runsApi.list(filters);
  const groups = timelineGroups(runs, filters.group_by || "phase");

  return <>
    <PageHeader title="Agent Runs" subtitle="Filter, replay, and inspect persisted agent execution records with model metadata, failures, and related artifacts." />
    <EndpointList endpoints={["GET /runs?filters", "GET /runs/{id}", "POST /runs/{id}/retry"]} />
    <Card title="Run filters">
      <form className="kb-filter-grid">
        <input name="scenario_id" defaultValue={filters.scenario_id ?? ""} placeholder="Scenario ID" />
        <input name="phase" defaultValue={filters.phase ?? ""} placeholder="Phase" />
        <input name="agent" defaultValue={filters.agent ?? ""} placeholder="Agent ID" />
        <select name="status" defaultValue={filters.status ?? ""}><option value="">All statuses</option><option value="pending">pending</option><option value="running">running</option><option value="completed">completed</option><option value="failed">failed</option><option value="cancelled">cancelled</option></select>
        <input name="model" defaultValue={filters.model ?? ""} placeholder="Model/profile" />
        <select name="failure_state" defaultValue={filters.failure_state ?? ""}><option value="">All runs</option><option value="failed">Failed/error runs</option><option value="retryable">Retryable runs</option></select>
        <input name="created_since" defaultValue={filters.created_since ?? ""} placeholder="Created since ISO" />
        <input name="created_until" defaultValue={filters.created_until ?? ""} placeholder="Created until ISO" />
        <select name="group_by" defaultValue={filters.group_by ?? "phase"}><option value="phase">Group by phase</option><option value="scenario">Group by scenario</option></select>
        <button className="button" type="submit">Apply filters</button>
        <Link className="button" href="/runs">Reset</Link>
      </form>
    </Card>
    <section className="wide-grid">
      <Card title="Run console">
        {runs.length ? runs.map((run) => <div className="stack-row" key={run.id}>
          <div>
            <Link href={`/runs/${run.id}`}><strong>{run.agent_id}</strong></Link>
            <p className="muted">{run.phase ?? "no phase"} · {firstModel(run)} · updated {new Date(run.updated_at).toLocaleString()}</p>
            <p className="muted">Scenario {scenarioId(run) || "not linked"} · {run.model_invocations?.length ?? 0} model invocation(s)</p>
            {run.error ? <p className="muted">Error: {run.error.slice(0, 180)}</p> : null}
          </div>
          <div className="stack-mini">
            <RunStatus status={run.status} />
            {run.status !== "completed" ? <form action={retryRunAction}><input type="hidden" name="run_id" value={run.id} /><button className="button" type="submit">Retry</button></form> : null}
          </div>
        </div>) : <EmptyState detail="No run records match the current backend filters." />}
      </Card>
      <Card title="Run timeline">
        {Object.keys(groups).length ? Object.entries(groups).map(([group, items]) => <details className="timeline-item" key={group} open>
          <summary>{group} · {items.length} run(s)</summary>
          {items.map((run) => <p className="muted" key={run.id}><Link href={`/runs/${run.id}`}>{run.id.slice(0, 8)}</Link> · {run.agent_id} · <StatusBadge status={run.status} /> · {new Date(run.created_at).toLocaleString()}</p>)}
        </details>) : <EmptyState detail="No timeline groups to show." />}
      </Card>
    </section>
  </>;
}
