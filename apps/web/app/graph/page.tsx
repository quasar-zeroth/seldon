import Link from "next/link";
import { revalidatePath } from "next/cache";
import { PageHeader, Card, EmptyState, EndpointList, EvidencePill, StatusBadge, ConfirmMutationDialog, AuditTrail } from "../../src/components/ui";
import { GraphExplorerCanvas } from "../../src/components/graph-explorer-canvas";
import { graphApi, type GraphFilters } from "../../src/lib/api";
import type { GraphEdge, GraphNode } from "../../src/lib/api/types";

function splitIds(value: FormDataEntryValue | null) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function nodeName(nodes: GraphNode[], id: string) {
  return nodes.find((node) => node.id === id)?.name ?? id.slice(0, 8);
}

async function updateNodeAction(id: string, formData: FormData) {
  "use server";
  await graphApi.updateNode(id, {
    description: String(formData.get("description") || ""),
    current_state: String(formData.get("current_state") || "") || null,
    stability_score: Number(formData.get("stability_score") || 0.5),
    importance_score: Number(formData.get("importance_score") || 0),
    scenario_ids: splitIds(formData.get("scenario_ids")),
  });
  revalidatePath("/graph");
}

async function updateEdgeAction(id: string, formData: FormData) {
  "use server";
  await graphApi.updateEdge(id, {
    relationship_type: String(formData.get("relationship_type") || "causes"),
    description: String(formData.get("description") || ""),
    confidence: Number(formData.get("confidence") || 0.5),
    strength: Number(formData.get("strength") || 0.5),
    direction: String(formData.get("direction") || "complex"),
    lag: String(formData.get("lag") || "") || null,
    scenario_ids: splitIds(formData.get("scenario_ids")),
  });
  revalidatePath("/graph");
}

async function createSnapshotAction(formData: FormData) {
  "use server";
  await graphApi.createSnapshot({ scenario_id: String(formData.get("scenario_id") || "") || null, reason: String(formData.get("reason") || "UI graph snapshot"), agent_id: "web" });
  revalidatePath("/graph");
}

async function approveMergeAction(formData: FormData) {
  "use server";
  const proposalId = String(formData.get("proposal_id") || "").trim();
  if (!proposalId) return;
  await graphApi.approveMerge(proposalId, { reason: String(formData.get("reason") || "approved in Graph Explorer"), actor: "web" });
  revalidatePath("/graph");
}

async function rejectMergeAction(formData: FormData) {
  "use server";
  const proposalId = String(formData.get("proposal_id") || "").trim();
  if (!proposalId) return;
  await graphApi.rejectMerge(proposalId, { reason: String(formData.get("reason") || "rejected in Graph Explorer"), actor: "web" });
  revalidatePath("/graph");
}

function nodeDetail(node?: GraphNode) {
  if (!node) return null;
  return <Card title="Selected node detail">
    <h3>{node.name}</h3>
    <p className="muted">{node.type} · importance {Math.round(node.importance_score * 100)}% · stability {Math.round(node.stability_score * 100)}%</p>
    <p>{node.description || "No description stored."}</p>
    <p className="muted">Current state: {node.current_state || "not set"}</p>
    <div className="pill-row">{node.kb_entry_ids.map((id) => <EvidencePill key={id} id={id} href={`/kb/${id}`} />)}</div>
    <ConfirmMutationDialog label="Edit node metadata">
      <form action={updateNodeAction.bind(null, node.id)} className="form-stack">
        <textarea name="description" defaultValue={node.description} rows={3} />
        <textarea name="current_state" defaultValue={node.current_state ?? ""} rows={2} />
        <input name="stability_score" type="number" min="0" max="1" step="0.05" defaultValue={node.stability_score} />
        <input name="importance_score" type="number" min="0" max="1" step="0.05" defaultValue={node.importance_score} />
        <input name="scenario_ids" defaultValue={node.scenario_ids.join(", ")} placeholder="Scenario IDs" />
        <button className="button" type="submit">Persist node changes</button>
      </form>
    </ConfirmMutationDialog>
  </Card>;
}

function edgeDetail(edge: GraphEdge | undefined, nodes: GraphNode[]) {
  if (!edge) return null;
  return <Card title="Selected edge detail">
    <h3>{nodeName(nodes, edge.source_node_id)} → {nodeName(nodes, edge.target_node_id)}</h3>
    <p className="muted">{edge.relationship_type} · {edge.direction} · confidence {Math.round(edge.confidence * 100)}% · strength {Math.round(edge.strength * 100)}%</p>
    <p>{edge.description || "No relationship description stored."}</p>
    <p className="muted">Lag: {edge.lag || "not specified"}</p>
    <div className="pill-row">{edge.evidence_kb_ids.map((id) => <EvidencePill key={id} id={id} href={`/kb/${id}`} />)}</div>
    <ConfirmMutationDialog label="Edit edge metadata">
      <form action={updateEdgeAction.bind(null, edge.id)} className="form-stack">
        <select name="relationship_type" defaultValue={edge.relationship_type}>{["causes", "correlates_with", "depends_on", "constrains", "enables", "opposes", "amplifies", "dampens"].map((kind) => <option key={kind} value={kind}>{kind}</option>)}</select>
        <textarea name="description" defaultValue={edge.description} rows={3} />
        <input name="confidence" type="number" min="0" max="1" step="0.05" defaultValue={edge.confidence} />
        <input name="strength" type="number" min="0" max="1" step="0.05" defaultValue={edge.strength} />
        <select name="direction" defaultValue={edge.direction}><option value="positive">positive</option><option value="negative">negative</option><option value="complex">complex</option></select>
        <input name="lag" defaultValue={edge.lag ?? ""} placeholder="Lag" />
        <input name="scenario_ids" defaultValue={edge.scenario_ids.join(", ")} placeholder="Scenario IDs" />
        <button className="button" type="submit">Persist edge changes</button>
      </form>
    </ConfirmMutationDialog>
  </Card>;
}

export default async function GraphPage({ searchParams }: { searchParams?: GraphFilters }) {
  const filters = searchParams ?? {};
  const [filteredNodes, filteredEdges, snapshots] = await Promise.all([graphApi.nodes(filters), graphApi.edges(filters), graphApi.snapshots(filters.scenario_id)]);
  const neighborhood = filters.selected_node ? await graphApi.neighborhood(filters.selected_node).catch(() => null) : null;
  const nodes = neighborhood?.nodes ?? filteredNodes;
  const edges = neighborhood?.edges ?? filteredEdges;
  const selectedNode = nodes.find((node) => node.id === filters.selected_node);
  const selectedEdge = edges.find((edge) => edge.id === filters.selected_edge);
  const reuse = filters.scenario_id ? await graphApi.reuseCandidates(filters.scenario_id).catch(() => ({ nodes: [], edges: [] })) : { nodes: [], edges: [] };
  const diff = snapshots.length >= 2 ? await graphApi.diffSnapshots(snapshots[1].id, snapshots[0].id).catch(() => null) : null;

  return <>
    <PageHeader title="Graph Explorer" subtitle="Interactive React Flow canvas for persisted ERG nodes, relationships, evidence, graph mutations, snapshots, and reuse candidates." />
    <EndpointList endpoints={["GET/PATCH /graph/nodes", "GET/PATCH /graph/edges", "GET /graph/neighborhood/{node_id}", "GET/POST /graph/snapshots", "GET /graph/reuse-candidates/{scenario_id}", "POST /graph/merge-proposals/{id}/approve|reject"]} />
    <Card title="Filters and overlays">
      <form className="kb-filter-grid">
        <input name="scenario_id" defaultValue={filters.scenario_id ?? ""} placeholder="Scenario ID" />
        <select name="type" defaultValue={filters.type ?? ""}><option value="">All node types</option>{["entity", "event", "topic", "metric", "policy", "actor"].map((type) => <option key={type} value={type}>{type}</option>)}</select>
        <select name="relationship_type" defaultValue={filters.relationship_type ?? ""}><option value="">All relationships</option>{["causes", "correlates_with", "depends_on", "constrains", "enables", "opposes", "amplifies", "dampens"].map((kind) => <option key={kind} value={kind}>{kind}</option>)}</select>
        <select name="direction" defaultValue={filters.direction ?? ""}><option value="">All directions</option><option value="positive">positive</option><option value="negative">negative</option><option value="complex">complex</option></select>
        <input name="lag" defaultValue={filters.lag ?? ""} placeholder="Lag" />
        <input name="min_confidence" defaultValue={filters.min_confidence ?? ""} placeholder="Min confidence" />
        <input name="min_strength" defaultValue={filters.min_strength ?? ""} placeholder="Min strength" />
        <input name="min_evidence_count" defaultValue={filters.min_evidence_count ?? ""} placeholder="Min evidence count" />
        <input name="min_importance" defaultValue={filters.min_importance ?? ""} placeholder="Min importance" />
        <input name="max_stability" defaultValue={filters.max_stability ?? ""} placeholder="Max stability / instability" />
        <select name="hide_low_confidence" defaultValue={filters.hide_low_confidence ?? ""}><option value="">Show all confidence</option><option value="true">Hide low-confidence edges</option></select>
        <select name="overlay" defaultValue={filters.overlay ?? "confidence"}><option value="confidence">Confidence overlay</option><option value="strength">Strength overlay</option><option value="importance">Importance overlay</option><option value="instability">Instability overlay</option><option value="scenario">Scenario path overlay</option></select>
        <button className="button" type="submit">Apply filters</button>
        <Link className="button" href="/graph">Reset filters</Link>
      </form>
    </Card>
    <section className="graph-layout">
      <Card title="Graph canvas">
        {nodes.length ? <><div className="graph-controls"><Link className="button" href="/graph">Fit view/reset</Link>{selectedNode ? <Link className="button" href={`/graph?selected_node=${selectedNode.id}`}>Center selected node</Link> : null}<StatusBadge status={`${nodes.length} nodes / ${edges.length} edges`} /></div><GraphExplorerCanvas nodes={nodes} edges={edges} selectedNodeId={filters.selected_node} selectedEdgeId={filters.selected_edge} overlay={(filters.overlay as "confidence") ?? "confidence"} /></> : <EmptyState detail="Run extraction and graph construction to create persisted graph records." />}
      </Card>
      <aside className="detail-drawer">
        {nodeDetail(selectedNode)}
        {edgeDetail(selectedEdge, nodes)}
        {!selectedNode && !selectedEdge ? <Card title="Detail drawer"><EmptyState detail="Select a node or edge from the accessible tables below to inspect evidence, provenance, and editable metadata." /></Card> : null}
        <AuditTrail />
      </aside>
    </section>
    <section className="wide-grid">
      <Card title="Node table">
        {nodes.length ? nodes.map((node) => <div className="stack-row" key={node.id}><div><Link href={`/graph?selected_node=${node.id}`}><strong>{node.name}</strong></Link><p className="muted">{node.type} · importance {Math.round(node.importance_score * 100)}% · stability {Math.round(node.stability_score * 100)}%</p></div><span className="muted">evidence {node.kb_entry_ids.length}</span></div>) : <EmptyState detail="No nodes match the current backend filters." />}
      </Card>
      <Card title="Edge table">
        {edges.length ? edges.map((edge) => <div className="stack-row" key={edge.id}><div><Link href={`/graph?selected_edge=${edge.id}`}><strong>{nodeName(nodes, edge.source_node_id)} → {nodeName(nodes, edge.target_node_id)}</strong></Link><p className="muted">{edge.relationship_type} · {edge.direction} · C {Math.round(edge.confidence * 100)} / S {Math.round(edge.strength * 100)}</p><div className="pill-row">{edge.evidence_kb_ids.slice(0, 5).map((id) => <EvidencePill key={id} id={id} href={`/kb/${id}`} />)}</div></div></div>) : <EmptyState detail="No edges match the current backend filters." />}
      </Card>
      <Card title="Snapshots and diffs">
        <form action={createSnapshotAction} className="form-stack"><input name="scenario_id" defaultValue={filters.scenario_id ?? ""} placeholder="Optional scenario ID" /><input name="reason" defaultValue="Manual Graph Explorer snapshot" /><button className="button" type="submit">Create graph snapshot</button></form>
        {snapshots.length ? snapshots.slice(0, 4).map((snapshot) => <p className="muted" key={snapshot.id}>{snapshot.id.slice(0, 8)} · {new Date(snapshot.created_at).toLocaleString()} · {snapshot.reason ?? "snapshot"}</p>) : <EmptyState detail="No graph snapshots have been created yet." />}
        {diff ? <pre>{JSON.stringify(diff, null, 2)}</pre> : <p className="muted">Create at least two snapshots to compare graph diffs.</p>}
      </Card>
      <Card title="Reuse candidates and merge proposals">
        {filters.scenario_id ? <><p className="muted">{reuse.nodes.length} candidate nodes and {reuse.edges.length} candidate edges are available for scenario reuse.</p>{reuse.nodes.slice(0, 5).map((node) => <p key={node.id}>{node.name}</p>)}</> : <EmptyState detail="Enter a scenario ID in filters to load cross-scenario reuse candidates." />}
        <ConfirmMutationDialog label="Approve merge proposal"><form action={approveMergeAction} className="form-stack"><input name="proposal_id" placeholder="Merge proposal ID" required /><input name="reason" placeholder="Reason" /><button className="button" type="submit">Approve via backend</button></form></ConfirmMutationDialog>
        <ConfirmMutationDialog label="Reject merge proposal"><form action={rejectMergeAction} className="form-stack"><input name="proposal_id" placeholder="Merge proposal ID" required /><input name="reason" placeholder="Reason" /><button className="button" type="submit">Reject via backend</button></form></ConfirmMutationDialog>
      </Card>
    </section>
  </>;
}
