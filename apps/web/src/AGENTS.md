# Shared console implementation

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table.

This source layer supports App Router pages without owning backend persistence or forecasting.

- [components/](components/AGENTS.md): reusable server/client presentation, draft interaction, graph canvas and charts.
- [lib/](lib/AGENTS.md): API facade and domain clients.

Keep server-only configuration behind the request layer and pass serializable persisted data into browser components.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
