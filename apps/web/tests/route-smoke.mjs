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
const modules = ["scenarios", "kb", "graph", "runs", "predictions", "calibration", "settings"];

await Promise.all(routes.map((route) => access(new URL(`../${route}`, import.meta.url))));
const ui = await readFile(new URL("../src/components/ui.tsx", import.meta.url), "utf8");
for (const name of shared) {
  if (!ui.includes(`function ${name}`)) throw new Error(`missing shared component ${name}`);
}
await Promise.all(modules.map((name) => access(new URL(`../src/lib/api/${name}.ts`, import.meta.url))));
console.log(`Route smoke passed for ${routes.length} routes, ${shared.length} components, and ${modules.length} API modules.`);
