# Seldon operating console

[Root AGENTS.md](../../AGENTS.md) contains the project-wide lookup table.

This Next.js application makes persisted scenarios, evidence, graph relationships, agent work and forecast uncertainty inspectable. It consumes Seldon's HTTP API; backend records remain authoritative. Parallax is the intended primary frontend/orchestration boundary described in the root map, while this console remains a usable client.

| Location | Responsibility |
| --- | --- |
| [app/](app/AGENTS.md) | Server-rendered routes, server actions and same-origin scenario proxies. |
| [src/](src/AGENTS.md) | Shared presentation and typed API access. |
| [tests/](tests/AGENTS.md) | Static route checks and browser workflows against a mock API. |
| `package.json` | Dependency and supported script definitions. |
| `tsconfig.json`, `next-env.d.ts` | TypeScript/Next integration; the declaration file is generated. |
| `playwright.config.ts` | Browser projects and test-server lifecycle. |

Supported flows include conversational scenario drafting/creation, metadata edits/deletion, queued phase requests, prediction history/evidence/report exports, KB search/edit/supersession/contradictions, graph inspection/edits/snapshots/merge review, run inspection/retry, outcome resolution, analytics and model settings.

[Project status](../../docs/project-status.md) separates current capabilities from remaining work; [GLOSSARY.md](../../GLOSSARY.md) defines domain terms. [design.md](../../design.md) records presentation goals, not a completed-feature inventory. Current limitations include manual refresh for job state, detail selection through graph table links, and unloaded audit panels on KB/graph views. [Agent workflow](../../docs/agent-workflow.md) covers provider-free workspace research; there is no dedicated workspace or perspectives editor here.

Preserve separate server/browser API bases and keep server credentials out of browser bundles. Persist mutations through backend APIs and reconcile with returned state. Do not label canned data as live. For UI behavior changes, use the relevant scripts in `package.json` (typecheck, build, route checks and browser tests); documentation-only changes need link/map checks.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
