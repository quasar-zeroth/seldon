import Link from "next/link";
import { PageHeader, StatusBadge, MetricCard, Card, EmptyState, EndpointList, RunStatus } from "../src/components/ui";
import { safe, scenariosApi, runsApi, graphApi, predictionsApi, settingsApi } from "../src/lib/api";

export default async function MissionControl() {
  const [health, scenarios, runs, nodes, edges, predictions] = await Promise.all([safe(settingsApi.health), safe(scenariosApi.list), safe(runsApi.list), safe(graphApi.nodes), safe(graphApi.edges), safe(predictionsApi.list)]);
  const active = scenarios.data?.[0];
  const latest = predictions.data?.find((p) => p.scenario_id === active?.id) ?? predictions.data?.[0];
  return <>
    <PageHeader title="Mission Control" subtitle="Overview of persisted scenarios, graph state, predictions, and agent activity." status={<StatusBadge status={health.data?.ok ?? false} />} />
    <EndpointList endpoints={["GET /health", "GET /scenarios", "GET /runs", "GET /graph/nodes", "GET /graph/edges", "GET /predictions"]} />
    <section className="grid"><MetricCard label="Scenarios" value={scenarios.data?.length ?? "—"} hint={scenarios.error} /><MetricCard label="Agent runs" value={runs.data?.length ?? "—"} /><MetricCard label="Graph" value={`${nodes.data?.length ?? 0} nodes / ${edges.data?.length ?? 0} edges`} /><MetricCard label="Predictions" value={predictions.data?.length ?? "—"} /></section>
    <section className="wide-grid">
      <Card title="Active scenarios">{scenarios.data?.length ? scenarios.data.slice(0, 6).map((s) => <div className="row" key={s.id}><Link href={`/scenarios/${s.id}`}>{s.name}</Link><span className="muted">{s.status}</span></div>) : <EmptyState detail="Create the first scenario from the Scenarios page." action={<Link className="button" href="/scenarios">Open scenarios</Link>} />}</Card>
      <Card title="Latest prediction">{latest ? <><strong>{latest.statement}</strong><p className="muted">confidence {Math.round(latest.confidence * 100)}% · {latest.status}</p><Link className="button" href={`/scenarios/${latest.scenario_id ?? ""}`}>Open scenario</Link></> : <EmptyState detail="Run a prediction phase to populate this card." />}</Card>
      <Card title="Recent runs">{runs.data?.length ? runs.data.slice(0, 6).map((run) => <div className="row" key={run.id}><Link href={`/runs/${run.id}`}>{run.agent_id}</Link><RunStatus status={run.status} /></div>) : <EmptyState detail="Queued workflows and agent executions will appear here." />}</Card>
    </section>
  </>;
}
