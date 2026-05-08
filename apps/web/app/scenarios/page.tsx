import { redirect } from "next/navigation";
import Link from "next/link";
import { PageHeader, Card, EmptyState, EndpointList, StatusBadge } from "../../src/components/ui";
import { scenariosApi, predictionsApi } from "../../src/lib/api";

async function createScenarioAction(formData: FormData) {
  "use server";
  const name = String(formData.get("name") || "").trim();
  const target_question = String(formData.get("target_question") || "").trim();
  if (!name || !target_question) return;
  const scenario = await scenariosApi.create({
    name,
    target_question,
    description: String(formData.get("description") || ""),
    time_horizon: String(formData.get("time_horizon") || ""),
  });
  redirect(`/scenarios/${scenario.id}`);
}

export default async function ScenariosPage({ searchParams }: { searchParams?: { q?: string; status?: string } }) {
  const q = searchParams?.q ?? "";
  const status = searchParams?.status ?? "";
  const [scenarios, predictions] = await Promise.all([
    scenariosApi.list({ q, status: status || undefined }),
    predictionsApi.list(),
  ]);

  return <>
    <PageHeader title="Scenarios" subtitle="Search, filter, create, and inspect persisted prediction scenarios." action={<a className="button" href="#create">Create scenario</a>} />
    <EndpointList endpoints={["GET /scenarios?q=&status=", "POST /scenarios", "GET /predictions"]} />
    <Card title="Search and filters">
      <form className="filter-bar">
        <input name="q" defaultValue={q} placeholder="Search name, description, or target question" />
        <select name="status" defaultValue={status}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="completed">Completed</option>
          <option value="archived">Archived</option>
        </select>
        <button className="button" type="submit">Apply</button>
      </form>
    </Card>
    <section className="wide-grid">
      <Card title="Scenario list">
        {scenarios.length ? scenarios.map((scenario) => {
          const latest = predictions.find((item) => item.scenario_id === scenario.id);
          return <div className="stack-row" key={scenario.id}>
            <div>
              <Link href={`/scenarios/${scenario.id}`}><strong>{scenario.name}</strong></Link>
              <p className="muted">{scenario.target_question}</p>
              <small className="muted">{scenario.time_horizon || "no horizon"} · updated {new Date(scenario.updated_at).toLocaleString()}</small>
              {latest ? <p className="muted">Latest prediction: {latest.statement} · {Math.round(latest.confidence * 100)}% confidence</p> : <p className="muted">No prediction yet.</p>}
            </div>
            <StatusBadge status={scenario.status} />
          </div>;
        }) : <EmptyState detail="No scenarios matched the current backend filters." />}
      </Card>
      <Card title="Create scenario">
        <form id="create" action={createScenarioAction} className="form-stack">
          <input name="name" placeholder="Scenario name" required />
          <textarea name="target_question" placeholder="Target question" rows={3} required />
          <textarea name="description" placeholder="Description / scope notes" rows={3} />
          <input name="time_horizon" placeholder="Time horizon" />
          <button className="button" type="submit">Create and open</button>
        </form>
      </Card>
    </section>
  </>;
}
