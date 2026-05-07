import { revalidatePath } from "next/cache";
import { api, type AgentRun, type GraphEdge, type GraphNode, type Scenario, type ScenarioPrediction } from "../src/lib/api";

async function createScenarioAction(formData: FormData) {
  "use server";
  const name = String(formData.get("name") || "").trim();
  const target = String(formData.get("target_question") || "").trim();
  if (!name || !target) return;
  await api.createScenario({ name, target_question: target, time_horizon: String(formData.get("time_horizon") || "") });
  revalidatePath("/");
}

async function enqueuePhaseAction(formData: FormData) {
  "use server";
  const scenarioId = String(formData.get("scenario_id") || "");
  const phase = String(formData.get("phase") || "") as "context_gathering" | "extraction" | "graph_construction" | "prediction";
  if (!scenarioId || !phase) return;
  await api.enqueuePhase(scenarioId, phase);
  revalidatePath("/");
}

async function retryRunAction(formData: FormData) {
  "use server";
  const runId = String(formData.get("run_id") || "");
  if (!runId) return;
  await api.retryRun(runId);
  revalidatePath("/");
}

async function safe<T>(loader: () => Promise<T>): Promise<{ data?: T; error?: string }> {
  try {
    return { data: await loader() };
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

type ExtractionOutput = {
  merge_proposals?: Array<{
    canonical_name: string;
    type: string;
    existing_node_id?: string | null;
    candidate_names?: string[];
    alias_node_ids?: string[];
    reason?: string;
    confidence?: number;
  }>;
};

function latestExtractionRun(runs: AgentRun[] = []): AgentRun | undefined {
  return runs.find((run) => run.agent_id === "extraction_coordinator" && run.status === "completed");
}

function extractionOutput(run?: AgentRun): ExtractionOutput | undefined {
  return run?.output as ExtractionOutput | undefined;
}

function selectedScenario(scenarios: Scenario[] = [], nodes: GraphNode[] = []): Scenario | undefined {
  return scenarios.find((scenario) => nodes.some((node) => node.scenario_ids.includes(scenario.id))) ?? scenarios[0];
}

function nodesForScenario(nodes: GraphNode[] = [], scenario?: Scenario): GraphNode[] {
  if (!scenario) return nodes;
  return nodes.filter((node) => node.scenario_ids.includes(scenario.id));
}

function nodeName(nodes: GraphNode[], id: string): string {
  return nodes.find((node) => node.id === id)?.name ?? id.slice(0, 8);
}

function strongestEdge(edges: GraphEdge[] = []): GraphEdge | undefined {
  return [...edges].sort((a, b) => (b.confidence + b.strength) - (a.confidence + a.strength))[0];
}

function latestPrediction(predictions: ScenarioPrediction[] = [], scenario?: Scenario): ScenarioPrediction | undefined {
  const scoped = scenario ? predictions.filter((prediction) => prediction.scenario_id === scenario.id) : predictions;
  return scoped[0];
}

function scenarioReport(scenario?: Scenario, prediction?: ScenarioPrediction): string {
  if (!scenario) return "# The Seldon Project\n\nNo scenario selected yet.\n";
  const lines = [
    `# ${scenario.name}`,
    "",
    `Question: ${scenario.target_question}`,
    `Horizon: ${scenario.time_horizon || "not set"}`,
    `Status: ${scenario.status}`,
  ];
  if (prediction) {
    lines.push(
      "",
      "## Latest prediction",
      prediction.statement,
      "",
      `Confidence: ${Math.round(prediction.confidence * 100)}%`,
      `Bull/base/bear: ${Math.round((prediction.probabilities.bull ?? 0) * 100)}% / ${Math.round((prediction.probabilities.base ?? 0) * 100)}% / ${Math.round((prediction.probabilities.bear ?? 0) * 100)}%`,
      "",
      "## Assumptions",
      ...(prediction.assumptions.length ? prediction.assumptions.map((item) => `- ${item}`) : ["- None recorded yet"]),
    );
  }
  return `${lines.join("\n")}\n`;
}

export default async function MissionControl() {
  const [health, scenarios, runs, graphNodes, graphEdges, predictions, modelConfig] = await Promise.all([
    safe(api.health),
    safe(api.scenarios),
    safe(api.runs),
    safe(api.graphNodes),
    safe(api.graphEdges),
    safe(api.predictions),
    safe(api.modelConfig),
  ]);

  const activeScenario = selectedScenario(scenarios.data, graphNodes.data);
  const scenarioNodes = nodesForScenario(graphNodes.data, activeScenario);
  const extraction = extractionOutput(latestExtractionRun(runs.data));
  const mergeProposals = extraction?.merge_proposals ?? [];
  const scenarioNodeIds = new Set(scenarioNodes.map((node) => node.id));
  const scenarioEdges = (graphEdges.data ?? []).filter(
    (edge) => scenarioNodeIds.has(edge.source_node_id) || scenarioNodeIds.has(edge.target_node_id),
  );
  const highlightedEdge = strongestEdge(scenarioEdges);
  const importantNodes = [...scenarioNodes].sort((a, b) => b.importance_score - a.importance_score).slice(0, 8);
  const activePrediction = latestPrediction(predictions.data, activeScenario);
  const reportHref = `data:text/markdown;charset=utf-8,${encodeURIComponent(scenarioReport(activeScenario, activePrediction))}`;

  return (
    <main>
      <section className="header">
        <div>
          <div className="eyebrow">The Seldon Project</div>
          <h1>Mission Control</h1>
          <p className="muted">Scenario intelligence, agent runs, extraction review, and graph evidence in one operating console.</p>
        </div>
        <div className="header-actions">
          <a className="button" href={reportHref} download={`${activeScenario?.name ?? "seldon-report"}.md`}>Download report</a>
          <div className={health.data?.ok ? "status" : "status bad"}>{health.data?.ok ? "API online" : "API offline"}</div>
        </div>
      </section>

      <section className="grid">
        <div className="card">
          <h2>Create scenario</h2>
          <form action={createScenarioAction} className="form-stack">
            <input name="name" placeholder="Scenario name" />
            <textarea name="target_question" placeholder="Target question" rows={3} />
            <input name="time_horizon" placeholder="Time horizon" />
            <button className="button" type="submit">Create</button>
          </form>
        </div>

        <div className="card">
          <h2>Run workflow phase</h2>
          <form action={enqueuePhaseAction} className="form-stack">
            <select name="scenario_id" defaultValue={activeScenario?.id ?? ""}>
              {scenarios.data?.map((scenario) => <option value={scenario.id} key={scenario.id}>{scenario.name}</option>)}
            </select>
            <select name="phase" defaultValue="context_gathering">
              <option value="context_gathering">Context gathering</option>
              <option value="extraction">Extraction</option>
              <option value="graph_construction">Graph construction</option>
              <option value="prediction">Prediction</option>
            </select>
            <button className="button" type="submit">Queue phase</button>
          </form>
        </div>

        <div className="card">
          <h2>Health</h2>
          {health.data ? (
            <>
              <p>Service: <code>{health.data.service}</code></p>
              <p className="muted">Default model: {health.data.llm_default_model}</p>
            </>
          ) : <p className="muted">{health.error}</p>}
        </div>

        <div className="card">
          <h2>Active scenarios</h2>
          {scenarios.data?.length ? scenarios.data.slice(0, 5).map((scenario) => (
            <div className="row" key={scenario.id}>
              <span>{scenario.name}</span>
              <span className="muted">{scenario.status}</span>
            </div>
          )) : <p className="muted">No scenarios yet.</p>}
        </div>

        <div className="card">
          <h2>Latest prediction</h2>
          {activePrediction ? (
            <>
              <p><strong>{activePrediction.statement}</strong></p>
              <p className="muted">{activePrediction.status} · confidence {Math.round(activePrediction.confidence * 100)}%</p>
              <div className="row"><span>Bull</span><span>{Math.round((activePrediction.probabilities.bull ?? 0) * 100)}%</span></div>
              <div className="row"><span>Base</span><span>{Math.round((activePrediction.probabilities.base ?? 0) * 100)}%</span></div>
              <div className="row"><span>Bear</span><span>{Math.round((activePrediction.probabilities.bear ?? 0) * 100)}%</span></div>
            </>
          ) : <p className="muted">Run Phase H to synthesize probabilities, assumptions, and evidence.</p>}
        </div>

        <div className="card">
          <h2>Agent runs</h2>
          {runs.data?.length ? runs.data.slice(0, 6).map((run) => (
            <div className="row" key={run.id}>
              <span>{run.agent_id}</span>
              <span className="muted">{run.model_invocations?.[0]?.model ?? run.status}</span>
              <form action={retryRunAction}>
                <input type="hidden" name="run_id" value={run.id} />
                <button className="link-button" type="submit">Retry</button>
              </form>
            </div>
          )) : <p className="muted">No agent runs yet.</p>}
        </div>

        <div className="card">
          <h2>Settings mock</h2>
          {modelConfig.data ? Object.entries(modelConfig.data.profiles).map(([profile, model]) => (
            <div className="row" key={profile}>
              <span>{profile}</span>
              <span className="muted">{model}</span>
            </div>
          )) : <p className="muted">{modelConfig.error}</p>}
        </div>
      </section>

      <section className="wide-grid">
        <div className="card">
          <h2>Scenario entity/topic panel</h2>
          <p className="muted">{activeScenario ? `Showing extracted nodes for ${activeScenario.name}` : "Run extraction to populate scenario nodes."}</p>
          <div className="pill-row">
            {scenarioNodes.length ? scenarioNodes.slice(0, 16).map((node) => (
              <span className={`pill ${node.type}`} key={node.id}>{node.type}: {node.name}</span>
            )) : <span className="muted">No persisted nodes yet.</span>}
          </div>
        </div>

        <div className="card">
          <h2>Node merge review</h2>
          {mergeProposals.length ? mergeProposals.slice(0, 6).map((proposal) => (
            <div className="stack-row" key={`${proposal.type}-${proposal.canonical_name}`}>
              <div>
                <strong>{proposal.canonical_name}</strong>
                <p className="muted">{proposal.reason ?? "Merge candidate"}</p>
              </div>
              <span className="muted">{Math.round((proposal.confidence ?? 0) * 100)}%</span>
            </div>
          )) : <p className="muted">No merge proposals pending from the latest extraction run.</p>}
        </div>

        <div className="card graph-card">
          <h2>Graph explorer v1</h2>
          <p className="muted">Persisted nodes and edges from ERG storage, now including Phase G relationship evidence and importance scoring.</p>
          <div className="graph-list">
            {scenarioNodes.slice(0, 12).map((node) => (
              <div className="graph-node" key={node.id}>
                <strong>{node.name}</strong>
                <span className="muted">{node.type} · evidence {node.kb_entry_ids.length}</span>
              </div>
            ))}
          </div>
          <div className="edge-list">
            {scenarioEdges.length ? scenarioEdges.slice(0, 8).map((edge) => (
              <div className="stack-row" key={edge.id}>
                <div>
                  <strong>{nodeName(scenarioNodes, edge.source_node_id)} → {nodeName(scenarioNodes, edge.target_node_id)}</strong>
                  <p className="muted">{edge.relationship_type} · {edge.direction} · evidence {edge.evidence_kb_ids.length}</p>
                </div>
                <span className="muted">{Math.round(edge.confidence * 100)}% / {Math.round(edge.strength * 100)}%</span>
              </div>
            )) : <p className="muted">No persisted edges yet. Run Phase G to populate relationships.</p>}
          </div>
        </div>

        <div className="card">
          <h2>Relationship evidence drawer</h2>
          {highlightedEdge ? (
            <div>
              <p><strong>{nodeName(scenarioNodes, highlightedEdge.source_node_id)}</strong> → <strong>{nodeName(scenarioNodes, highlightedEdge.target_node_id)}</strong></p>
              <p className="muted">{highlightedEdge.description}</p>
              <div className="pill-row">
                {highlightedEdge.evidence_kb_ids.map((id) => <span className="pill" key={id}>KB {id.slice(0, 8)}</span>)}
              </div>
            </div>
          ) : <p className="muted">Select a graph relationship once Phase G has written edges.</p>}
        </div>

        <div className="card">
          <h2>Edge confidence / strength controls</h2>
          {scenarioEdges.length ? scenarioEdges.slice(0, 5).map((edge) => (
            <div className="stack-row" key={edge.id}>
              <div>
                <strong>{edge.relationship_type}</strong>
                <p className="muted">{nodeName(scenarioNodes, edge.source_node_id)} → {nodeName(scenarioNodes, edge.target_node_id)}</p>
              </div>
              <span className="muted">C {Math.round(edge.confidence * 100)} · S {Math.round(edge.strength * 100)}</span>
            </div>
          )) : <p className="muted">No edge controls to show yet.</p>}
        </div>

        <div className="card">
          <h2>Graph importance heatmap</h2>
          {importantNodes.length ? importantNodes.map((node) => (
            <div className="row" key={node.id}>
              <span>{node.name}</span>
              <span className="muted">{Math.round(node.importance_score * 100)} importance</span>
            </div>
          )) : <p className="muted">Importance scores appear after Phase G.</p>}
        </div>

        <div className="card">
          <h2>Prediction drivers / assumptions / evidence</h2>
          {activePrediction ? (
            <div>
              <p className="muted">Resolution: {activePrediction.resolution_criteria}</p>
              <div className="pill-row">
                {activePrediction.key_drivers.slice(0, 6).map((id) => <span className="pill" key={id}>Driver {nodeName(scenarioNodes, id)}</span>)}
              </div>
              <ul>
                {activePrediction.assumptions.slice(0, 3).map((assumption) => <li key={assumption}>{assumption}</li>)}
              </ul>
              <p className="muted">Evidence links: {activePrediction.evidence_links.length} · History points: {activePrediction.probability_history.length}</p>
            </div>
          ) : <p className="muted">No prediction detail yet.</p>}
        </div>
      </section>
    </main>
  );
}
