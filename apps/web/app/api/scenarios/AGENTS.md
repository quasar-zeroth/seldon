# Scenario creation proxy

[Root AGENTS.md](../../../../../AGENTS.md) contains the project-wide lookup table.

`route.ts` accepts browser POST requests, maps editable scenario fields and the original prompt into `scenariosApi.create`, returns the created record, and converts failures to JSON errors. The draft component uses this same-origin boundary before navigating to the scenario.

[draft/](draft/AGENTS.md) owns the separate drafting request. Backend schemas remain responsible for the actual scenario contract.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
