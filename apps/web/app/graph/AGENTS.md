# Graph Explorer

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table.

`page.tsx` loads filtered ERG nodes/edges, selected-node neighborhoods, snapshots/diffs, reuse candidates and merge proposals. It renders the shared React Flow canvas plus accessible node/edge tables and selected-record forms.

Server actions edit node/edge metadata, create snapshots and submit merge-proposal decisions. The backend currently audits approval/rejection without executing a merge or reference rewrite. `error.tsx` and `loading.tsx` are scoped route boundaries. Graph algorithms and reference rewriting remain backend concerns.

Current detail navigation uses query parameters from table links; the canvas does not wire selection callbacks to those parameters. Selecting a neighborhood replaces the filtered dataset. The audit panel has no loaded records, and reuse candidates are displayed rather than imported through this page.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
