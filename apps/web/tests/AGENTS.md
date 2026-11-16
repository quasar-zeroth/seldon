# Frontend verification harness

[Root AGENTS.md](../../../AGENTS.md) contains the project-wide lookup table.

| File or directory | Responsibility |
| --- | --- |
| `route-smoke.mjs` | Static assertions for route files, shared components, API modules, CI scripts and Docker URL wiring. |
| `mock-api.mjs` | In-memory HTTP fixtures and mutation responses for browser workflows. |
| `dev-with-mock.mjs` | Starts mock API and Next dev process; handles shutdown. |
| [e2e/](e2e/AGENTS.md) | Playwright route rendering and interactive workflows. |

`../playwright.config.ts` owns browser/test-server setup; `../package.json` defines scripts and the frontend gate. Browser fixtures do not establish compatibility with a running Python API or provider-backed research.

Keep fixture contracts aligned with actual routes. When running isolated browser tests, ensure inherited server API configuration cannot override the mock endpoint. For documentation-only changes, static map/link validation is sufficient.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
