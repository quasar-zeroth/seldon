# Agent run inspection

[Root AGENTS.md](../../../../../AGENTS.md) contains the project-wide lookup table.

`page.tsx` loads run detail, messages and related records; it uses related audit entries or an audit-log lookup. It displays inputs/outputs, status/errors/timestamps, model token/latency/cost metadata, evidence, graph changes, predictions and feedback. A server action requests retry and revalidates run routes.

`error.tsx` and `loading.tsx` are scoped route boundaries. Missing invocation metadata is displayed as missing, not reconstructed. This page loads actual audit items, unlike the current empty KB/graph audit panels.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
