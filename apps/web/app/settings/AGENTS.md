# Runtime settings and operations

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table.

`page.tsx` reads backend health, model configuration and deployment status. Server actions update model profiles/fallbacks, per-agent overrides, or request complete runtime-data clearing with the backend's confirmation contract. Clearing revalidates affected console routes.

`error.tsx` and `loading.tsx` provide route boundaries. Model options and writable fields are defined by actual backend configuration/contracts. Deployment-controlled sources, persistence, vectors and authentication are status displays rather than editors.

Preserve secret-safe status output and the destructive-action confirmation flow; documentation work never calls the data-clearing action.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
