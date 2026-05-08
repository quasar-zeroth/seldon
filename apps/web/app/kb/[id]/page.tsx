import Link from "next/link";
import { revalidatePath } from "next/cache";
import { PageHeader, Card, EmptyState, EndpointList, SourceLink, AuditTrail, StatusBadge, ConfirmMutationDialog } from "../../../src/components/ui";
import { kbApi } from "../../../src/lib/api";

function splitTags(value: FormDataEntryValue | null) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

async function updateKBEntryAction(id: string, formData: FormData) {
  "use server";
  await kbApi.update(id, {
    content: String(formData.get("content") || ""),
    original_snippet: String(formData.get("original_snippet") || ""),
    source_name: String(formData.get("source_name") || "Unknown"),
    source_url: String(formData.get("source_url") || "") || null,
    topics: splitTags(formData.get("topics")),
    entities: splitTags(formData.get("entities")),
    scenario_ids: splitTags(formData.get("scenario_ids")),
    perspective_tags: {
      sentiment: Number(formData.get("sentiment") || 0),
      confidence: Number(formData.get("confidence") || 0.5),
      geopolitical_lens: String(formData.get("geopolitical_lens") || "") || null,
    },
  });
  revalidatePath(`/kb/${id}`);
  revalidatePath("/kb");
}

async function supersedeKBEntryAction(id: string, formData: FormData) {
  "use server";
  const newEntryId = String(formData.get("new_entry_id") || "").trim();
  if (!newEntryId) return;
  await kbApi.supersede(id, newEntryId);
  revalidatePath(`/kb/${id}`);
  revalidatePath("/kb");
}

async function createContradictionAction(id: string, formData: FormData) {
  "use server";
  const contradicts = String(formData.get("contradicts_kb_entry_id") || "").trim();
  const description = String(formData.get("description") || "").trim();
  if (!contradicts || !description) return;
  await kbApi.createContradiction({ kb_entry_id: id, contradicts_kb_entry_id: contradicts, description, status: "open" });
  revalidatePath(`/kb/${id}`);
  revalidatePath("/kb");
}

async function updateContradictionAction(id: string, formData: FormData) {
  "use server";
  const contradictionId = String(formData.get("contradiction_id") || "").trim();
  if (!contradictionId) return;
  await kbApi.updateContradiction(contradictionId, {
    status: String(formData.get("status") || "open"),
    description: String(formData.get("description") || ""),
  });
  revalidatePath(`/kb/${id}`);
  revalidatePath("/kb");
}

export default async function KBDetail({ params }: { params: { id: string } }) {
  const [entry, versions, contradictions, related] = await Promise.all([
    kbApi.get(params.id),
    kbApi.versions(params.id),
    kbApi.contradictions(params.id),
    kbApi.related(params.id),
  ]);
  const perspective = entry.perspective_tags ?? {};

  return <>
    <PageHeader title={`KB ${entry.id.slice(0, 8)}`} subtitle={entry.content} status={<StatusBadge status={entry.superseded_by ? "superseded" : "current"} />} />
    <EndpointList endpoints={["GET /kb/entries/{id}", "PATCH /kb/entries/{id}", "GET /kb/entries/{id}/versions", "GET /kb/entries/{id}/contradictions", "GET /kb/entries/{id}/related", "POST /kb/entries/{id}/supersede/{new_id}", "POST/PATCH /kb/contradictions"]} />
    <section className="wide-grid">
      <Card title="Content and summary">
        <p>{entry.content}</p>
        <div className="pill-row">
          {(entry.topics ?? []).map((tag) => <span className="pill topic" key={`topic-${tag}`}>{tag}</span>)}
          {(entry.entities ?? []).map((tag) => <span className="pill" key={`entity-${tag}`}>{tag}</span>)}
        </div>
        <p className="muted">Created {new Date(entry.created_at).toLocaleString()} · updated {new Date(entry.updated_at).toLocaleString()} · version {entry.version}</p>
      </Card>
      <Card title="Source and provenance">
        <p>{entry.original_snippet || "No original snippet stored."}</p>
        <p className="muted">Type: {entry.source_type}</p>
        <SourceLink url={entry.source_url} name={entry.source_name} />
        <p className="muted">Valid from {entry.valid_from ? new Date(entry.valid_from).toLocaleString() : "unknown"} to {entry.valid_until ? new Date(entry.valid_until).toLocaleString() : "open-ended"}</p>
      </Card>
      <Card title="Perspective and confidence">
        <p className="muted">Sentiment: {String(perspective.sentiment ?? "not tagged")}</p>
        <p className="muted">Political lean: {String(perspective.political_lean ?? "not tagged")}</p>
        <p className="muted">Geopolitical lens: {String(perspective.geopolitical_lens ?? "not tagged")}</p>
        <p className="muted">Confidence: {String(perspective.confidence ?? "not tagged")}</p>
      </Card>
      <Card title="Supersession state">
        {entry.superseded_by ? <p>This entry is superseded by <Link href={`/kb/${entry.superseded_by}`}>{entry.superseded_by}</Link>.</p> : <p>This entry is current.</p>}
        <ConfirmMutationDialog label="Supersede this entry">
          <form action={supersedeKBEntryAction.bind(null, entry.id)} className="form-stack">
            <input name="new_entry_id" placeholder="Replacement KB entry ID" required />
            <button className="button" type="submit">Record supersession</button>
          </form>
        </ConfirmMutationDialog>
      </Card>
      <Card title="Linked scenarios, graph, and predictions">
        <h3>Scenarios</h3>
        {related.scenarios.length ? related.scenarios.map((scenario) => <p key={scenario.id}><Link href={`/scenarios/${scenario.id}`}>{scenario.name}</Link></p>) : <EmptyState detail="No scenarios are linked to this KB entry." />}
        <h3>Graph nodes and edges</h3>
        {related.graph_nodes.length || related.graph_edges.length ? <ul>{related.graph_nodes.map((node) => <li key={node.id}>Node: {node.name}</li>)}{related.graph_edges.map((edge) => <li key={edge.id}>Edge: {edge.relationship_type} ({Math.round(edge.confidence * 100)}% confidence)</li>)}</ul> : <p className="muted">No graph relationships reference this evidence yet.</p>}
        <h3>Predictions</h3>
        {related.predictions.length ? related.predictions.map((prediction) => <p key={prediction.id}><Link href={`/scenarios/${prediction.scenario_id ?? ""}`}>{prediction.statement}</Link></p>) : <p className="muted">No predictions cite this entry yet.</p>}
      </Card>
      <Card title="Versions timeline">
        {versions.length ? versions.map((version, i) => <details key={String(version.id ?? i)} className="timeline-item"><summary>Version {String(version.version ?? i + 1)} · {String(version.created_at ?? "recorded")}</summary><pre>{JSON.stringify(version.snapshot ?? version, null, 2)}</pre></details>) : <EmptyState detail="No version history stored for this entry yet." />}
      </Card>
      <Card title="Contradictions">
        {contradictions.length ? contradictions.map((contradiction) => <div className="stack-row" key={contradiction.id}>
          <div>
            <strong>{contradiction.description}</strong>
            <p className="muted">{contradiction.kb_entry_id === entry.id ? "Contradicts" : "Contradicted by"} <Link href={`/kb/${contradiction.kb_entry_id === entry.id ? contradiction.contradicts_kb_entry_id : contradiction.kb_entry_id}`}>{contradiction.kb_entry_id === entry.id ? contradiction.contradicts_kb_entry_id : contradiction.kb_entry_id}</Link></p>
            <form action={updateContradictionAction.bind(null, entry.id)} className="inline-form">
              <input type="hidden" name="contradiction_id" value={contradiction.id} />
              <input name="description" defaultValue={contradiction.description} />
              <select name="status" defaultValue={contradiction.status}><option value="open">open</option><option value="resolved">resolved</option><option value="ignored">ignored</option></select>
              <button className="button" type="submit">Update</button>
            </form>
          </div>
          <StatusBadge status={contradiction.status} />
        </div>) : <EmptyState detail="No contradictions have been recorded for this entry." />}
        <ConfirmMutationDialog label="Record contradiction">
          <form action={createContradictionAction.bind(null, entry.id)} className="form-stack">
            <input name="contradicts_kb_entry_id" placeholder="Contradicting KB entry ID" required />
            <textarea name="description" placeholder="Why these entries conflict" rows={3} required />
            <button className="button" type="submit">Create contradiction</button>
          </form>
        </ConfirmMutationDialog>
      </Card>
      <Card title="Edit KB entry">
        <form action={updateKBEntryAction.bind(null, entry.id)} className="form-stack">
          <textarea name="content" defaultValue={entry.content} rows={4} required />
          <textarea name="original_snippet" defaultValue={entry.original_snippet ?? ""} rows={3} />
          <input name="source_name" defaultValue={entry.source_name} />
          <input name="source_url" defaultValue={entry.source_url ?? ""} />
          <input name="topics" defaultValue={(entry.topics ?? []).join(", ")} />
          <input name="entities" defaultValue={(entry.entities ?? []).join(", ")} />
          <input name="scenario_ids" defaultValue={(entry.scenario_ids ?? []).join(", ")} />
          <input name="geopolitical_lens" defaultValue={String(perspective.geopolitical_lens ?? "")} />
          <input name="sentiment" type="number" min="-1" max="1" step="0.1" defaultValue={String(perspective.sentiment ?? 0)} />
          <input name="confidence" type="number" min="0" max="1" step="0.05" defaultValue={String(perspective.confidence ?? 0.5)} />
          <button className="button" type="submit">Save persisted changes</button>
        </form>
      </Card>
      <AuditTrail />
    </section>
  </>;
}
