# Scenario workspace

[Root AGENTS.md](../../../../../AGENTS.md) contains the project-wide lookup table.

`page.tsx` combines scenario metadata, predictions, graph nodes, runs, jobs and analytics. Its server actions edit/delete a scenario, queue a workflow phase, request advanced analysis and submit feedback. The rendered sections expose evidence, assumptions, history/versions, jobs, related runs/nodes and report downloads.

`error.tsx` and `loading.tsx` provide route boundaries. Charts are delegated to `charts-dashboard.tsx`; API behavior lives in the typed clients and Python backend.

Job state currently requires refresh; queuing a job is not completion. Report links use the browser API base and ordinary anchors, so authenticated downloads need separate consideration. Preserve probability/assumption/evidence distinctions and do not imply every listed node or run belongs to this scenario without checking its links.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
