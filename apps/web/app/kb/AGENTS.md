# Knowledge Base explorer

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table.

`page.tsx` renders backend search results with semantic/keyword, provenance, time, scenario, perspective and current-entry filters. Its create action stores a KB entry with source/snippet/tags and redirects to detail.

- [[id]/]([id]/AGENTS.md): provenance, versions, contradictions, supersession and editing.
- `error.tsx`, `loading.tsx`: scoped route boundaries.

Search behavior and scoring belong to the backend. Preserve source metadata and distinguish a KB entry's textual entity tags from reusable graph entity UUIDs.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
