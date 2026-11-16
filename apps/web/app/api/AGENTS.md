# Same-origin console API routes

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table.

These Next.js handlers bridge browser requests to the configured Seldon backend. They are a narrow console boundary, not the primary Python API.

- [scenarios/](scenarios/AGENTS.md): scenario creation proxy.
- [scenarios/draft/](scenarios/draft/AGENTS.md): prompt-to-draft proxy.

Both use shared API clients so server configuration/auth stays centralized. Preserve backend persistence ownership and JSON error responses; do not copy specialist or workspace logic into handlers.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
