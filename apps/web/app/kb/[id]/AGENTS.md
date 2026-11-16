# Knowledge Base entry detail

[Root AGENTS.md](../../../../../AGENTS.md) contains the project-wide lookup table.

`page.tsx` loads an entry, its versions, contradictions and related scenarios/graph/predictions. Server actions update content/provenance/tags, supersede with another entry, and create or update contradictions; affected KB routes are revalidated.

`error.tsx` and `loading.tsx` provide route boundaries. Version snapshots and related records come from the backend. The current `AuditTrail` renders without loaded items, so it is an empty display rather than an audit-history integration.

Retain supersession and contradiction distinctions instead of treating edits as destructive replacements.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
