# Applications

[Root AGENTS.md](../AGENTS.md) contains the project-wide lookup table.

Seldon's application layer contains the existing operating console. Backend persistence, forecasting and workspace validation live under `src/seldon/`; this directory consumes those interfaces.

| Directory | Responsibility |
| --- | --- |
| [web/](web/AGENTS.md) | Next.js console: scenarios, evidence, graphs, runs, calibration and settings. |

The root map describes the Parallax boundary. Keep this package independent of Parallax imports. Browser fixtures are test data, never live research results.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
