# Console API facade

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table.

`api.ts` re-exports typed domain clients and supplies a compatibility `api` object used by consumers. [api/](api/AGENTS.md) owns transport, browser/server endpoint configuration, types and domain request builders.

Keep request behavior in the domain modules and preserve facade compatibility when changing imports. Python schemas/routes remain the backend contract; TypeScript shapes must follow them.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
