import { revalidatePath } from "next/cache";
import Link from "next/link";
import { PageHeader, Card, EmptyState, EndpointList, ConfirmMutationDialog } from "../../src/components/ui";
import { ScenarioDraftChat } from "../../src/components/scenario-draft-chat";
import { scenariosApi, predictionsApi } from "../../src/lib/api";

async function deleteScenarioAction(formData: FormData) {
  "use server";
  const id = String(formData.get("scenario_id") || "");
  if (!id) return;
  await scenariosApi.delete(id);
  revalidatePath("/scenarios");
}

export default async function ScenariosPage({ searchParams }: { searchParams?: { q?: string } }) {
  const q = searchParams?.q ?? "";
  const [scenarios, predictions] = await Promise.all([
    scenariosApi.list({ q }),
    predictionsApi.list(),
  ]);

  return <>
    <PageHeader title="Scenarios" subtitle="Describe a forecast in plain English, review the draft, then open the scenario workspace." action={<a className="button" href="#create">Create scenario</a>} />
    <EndpointList endpoints={["POST /scenarios/draft", "POST /scenarios", "GET /scenarios?q="]} />
    <section className="wide-grid">
      <Card title="Create from a conversation">
        <ScenarioDraftChat />
      </Card>
      <Card title="Scenario list">
        <form className="filter-bar simple-filter" action="/scenarios">
          <input name="q" placeholder="Search scenarios" defaultValue={q} />
          <button className="button" type="submit">Search</button>
        </form>
        {scenarios.length ? scenarios.map((scenario) => {
          const latest = predictions.find((item) => item.scenario_id === scenario.id);
          return <div className="stack-row" key={scenario.id}>
            <div>
              <Link href={`/scenarios/${scenario.id}`}><strong>{scenario.name}</strong></Link>
              <p className="muted">{scenario.target_question}</p>
              <small className="muted">{scenario.time_horizon || "no horizon"} · updated {new Date(scenario.updated_at).toLocaleString()}</small>
              {latest ? <p className="muted">Latest prediction: {latest.statement} · {Math.round(latest.confidence * 100)}% confidence</p> : <p className="muted">No prediction yet.</p>}
            </div>
            <form action={deleteScenarioAction}>
              <input type="hidden" name="scenario_id" value={scenario.id} />
              <ConfirmMutationDialog label="Delete scenario">
                <button className="button danger-button" type="submit">Delete permanently</button>
              </ConfirmMutationDialog>
            </form>
          </div>;
        }) : <EmptyState detail="No scenarios matched the current search." />}
      </Card>
    </section>
  </>;
}
