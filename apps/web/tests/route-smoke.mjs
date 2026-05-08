import { access, readFile } from "node:fs/promises";

const routes = [
  "app/page.tsx",
  "app/scenarios/page.tsx",
  "app/scenarios/[id]/page.tsx",
  "app/kb/page.tsx",
  "app/kb/[id]/page.tsx",
  "app/graph/page.tsx",
  "app/runs/page.tsx",
  "app/runs/[id]/page.tsx",
  "app/calibration/page.tsx",
  "app/settings/page.tsx",
];
const shared = ["PageHeader", "StatusBadge", "MetricCard", "EvidencePill", "RunStatus", "EmptyState", "ErrorState", "LoadingSkeleton", "ConfirmMutationDialog", "AuditTrail", "SourceLink"];
const modules = ["scenarios", "kb", "graph", "runs", "predictions", "calibration", "settings", "jobs"];

await Promise.all(routes.map((route) => access(new URL(`../${route}`, import.meta.url))));
const ui = await readFile(new URL("../src/components/ui.tsx", import.meta.url), "utf8");
for (const name of shared) {
  if (!ui.includes(`function ${name}`)) throw new Error(`missing shared component ${name}`);
}
await Promise.all(modules.map((name) => access(new URL(`../src/lib/api/${name}.ts`, import.meta.url))));
const scenariosPage = await readFile(new URL("../app/scenarios/page.tsx", import.meta.url), "utf8");
const scenarioDetail = await readFile(new URL("../app/scenarios/[id]/page.tsx", import.meta.url), "utf8");
const kbPage = await readFile(new URL("../app/kb/page.tsx", import.meta.url), "utf8");
const kbDetail = await readFile(new URL("../app/kb/[id]/page.tsx", import.meta.url), "utf8");
const graphPage = await readFile(new URL("../app/graph/page.tsx", import.meta.url), "utf8");
const graphCanvas = await readFile(new URL("../src/components/graph-explorer-canvas.tsx", import.meta.url), "utf8");
const runsPage = await readFile(new URL("../app/runs/page.tsx", import.meta.url), "utf8");
const runDetail = await readFile(new URL("../app/runs/[id]/page.tsx", import.meta.url), "utf8");
for (const needle of ["GET /scenarios?q=&status=", "Create and open", "Latest prediction"]) {
  if (!scenariosPage.includes(needle)) throw new Error(`missing B.2 scenarios list affordance: ${needle}`);
}
for (const needle of ["PATCH /scenarios/{id}", "Download backend report", "Run advanced intelligence", "Resolve prediction with feedback", "Scenario history and versions"]) {
  if (!scenarioDetail.includes(needle)) throw new Error(`missing B.2 scenario detail affordance: ${needle}`);
}
for (const needle of ["GET /kb/search?filters", "Semantic search", "current_only", "Create and inspect", "open contradiction"]){
  if (!kbPage.includes(needle)) throw new Error(`missing B.3 KB explorer affordance: ${needle}`);
}
for (const needle of ["GET /kb/entries/{id}/contradictions", "Record supersession", "Record contradiction", "Versions timeline", "Linked scenarios, graph, and predictions"]){
  if (!kbDetail.includes(needle)) throw new Error(`missing B.3 KB detail affordance: ${needle}`);
}
for (const needle of ["GraphExplorerCanvas", "GET/PATCH /graph/nodes", "selected_node", "Create graph snapshot", "Approve merge proposal", "Reject merge proposal"]){
  if (!graphPage.includes(needle)) throw new Error(`missing B.4 graph explorer affordance: ${needle}`);
}
for (const needle of ["ReactFlow", "MiniMap", "Controls", "data-testid=\"reactflow-graph-canvas\""]){
  if (!graphCanvas.includes(needle)) throw new Error(`missing B.4 React Flow canvas capability: ${needle}`);
}
for (const needle of ["GET /runs?filters", "failure_state", "Run timeline", "Retry"]){
  if (!runsPage.includes(needle)) throw new Error(`missing B.5 runs console affordance: ${needle}`);
}
for (const needle of ["GET /runs/{id}/messages", "GET /runs/{id}/related", "Model invocations", "Input JSON", "Output JSON", "Related records", "Retry through backend"]){
  if (!runDetail.includes(needle)) throw new Error(`missing B.5 run detail affordance: ${needle}`);
}
console.log(`Route smoke passed for ${routes.length} routes, ${shared.length} components, and ${modules.length} API modules.`);
