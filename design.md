# The Seldon Project — GUI Design Principles

This document defines the shared product and interface principles for all Seldon web pages. Use it alongside `implementation-plan.md` when building dedicated pages, mutation flows, charts, graph visualization, and backend integrations.

## 1. Product framing

The Seldon GUI is an operating console for prediction intelligence. It should help a human answer four questions quickly:

1. What scenario are we analyzing?
2. What evidence and graph structure support the current view?
3. What did the agents do, with which models, and can their work be replayed or corrected?
4. What changed since the last prediction, and what action should I take next?

The UI should feel like mission control: dense enough for serious analysis, but organized enough that uncertainty, provenance, and next actions are always visible.

## 2. Global design principles

- **Evidence first:** Every prediction, relationship, assumption, and correction should link back to KB entries, sources, runs, or audit records.
- **Backend truth:** Pages render persisted backend state, not frontend-only mock data. Temporary optimistic UI is allowed only when it reconciles with API responses.
- **Action with auditability:** Mutations must call backend endpoints that persist records, emit audit logs where applicable, and return updated state or job IDs.
- **Progress over mystery:** Long-running agent workflows should show queued/running/completed/failed states, run IDs, elapsed time, and retry options.
- **Uncertainty is a feature:** Probabilities, confidence, calibration, instability, missing evidence, and contradictions should be visually explicit.
- **Readable density:** Prefer cards, split panes, tabs, drawers, filters, and compact tables over long single-column pages.
- **Graceful degradation:** Empty, loading, error, stale, and partial-data states should be first-class and explain what the user can do next.
- **Local-first but production-ready:** The UI should work against a local FastAPI backend by default and allow configured backend URLs for Docker/production.

## 3. Navigation model

Use dedicated routes instead of putting everything on Mission Control:

- `/` — Mission Control overview
- `/scenarios` — scenario list and creation
- `/scenarios/[id]` — scenario detail, phase actions, latest prediction, evidence, assumptions
- `/kb` — Knowledge Base Explorer
- `/kb/[id]` — KB entry detail with provenance, versions, contradictions, supersession
- `/graph` — Graph Explorer
- `/runs` — Agent Runs Console
- `/runs/[id]` — run detail with input/output/messages/model invocations/errors
- `/calibration` — feedback, resolved predictions, calibration charts, miss analysis
- `/settings` — model profiles, agent overrides, source/backend status

Mission Control should summarize and link into these pages, not replace them.

## 4. Page layout conventions

Each dedicated page should follow a consistent structure:

1. **Header:** title, subtitle, primary status badge, primary action.
2. **Context strip:** selected scenario/time horizon/model profile/filter state where relevant.
3. **Main workspace:** cards, tables, graph canvas, charts, or detail panes.
4. **Evidence/action side panel:** provenance, audit trail, selected item details, related runs, mutation forms.
5. **Footer/status rail:** last refreshed time, backend URL, relevant job status, error notices.

Use a shared component vocabulary: `PageHeader`, `StatusBadge`, `EvidencePill`, `MetricCard`, `RunStatus`, `EmptyState`, `ErrorState`, `LoadingSkeleton`, `ConfirmMutationDialog`, `AuditTrail`, and `SourceLink`.

## 5. Data and backend integration rules

- Put all API calls in typed client modules under `apps/web/src/lib` or a dedicated `apps/web/src/api` package.
- Prefer server-rendered fetches for initial page state and client components for interactive filters, graph controls, polling, and mutation forms.
- Every mutation flow must call a real FastAPI endpoint. If the endpoint is missing, implement the backend endpoint first or add it as an explicit blocker in `implementation-plan.md`.
- Mutations should revalidate or refetch the affected routes after success.
- Job-triggering actions should display the returned job/run ID and poll `/ops/jobs/{job_id}` or `/runs/{run_id}` until terminal status.
- Use `NEXT_PUBLIC_SELDON_API_URL` for browser-side calls and a server-side API base setting for server actions/renders if those differ in Docker or production.
- Handle API-key mode explicitly: all client helpers must support sending `x-seldon-api-key` or bearer auth when production auth is enabled.

## 6. Mutation UX rules

- Make destructive or high-impact actions confirmable: node merge approval, edge deletion, supersession, feedback resolution, settings saves.
- Show validation errors next to fields and preserve user input.
- Use backend-returned records as the source of truth after create/update.
- For queued workflows, distinguish between “queued successfully” and “agent run completed”.
- Where possible, show a small audit/provenance note after mutation: who/what changed it, when, and which backend record was created.

## 7. Charts and analytics principles

- Charts should always include labels, units, date/time context, and empty states.
- Probability charts should show history over time and make bull/base/bear or branch probabilities visually comparable.
- Calibration charts should show bucketed confidence vs observed frequency, Brier/log scores, and sample size warnings.
- Instability, uncertainty, sentiment drift, and cascade risk should use consistent color semantics:
  - green/blue: stable or low risk
  - amber: watch/uncertain
  - red: contradiction/high risk/failed
  - purple: model/agent reasoning metadata

## 8. Graph visualization principles

The Graph Explorer should be an interactive reasoning surface, not just a node list:

- Use React Flow, Sigma.js, or another explicit graph visualization library.
- Support filters for relationship type, confidence, strength, direction, lag, scenario, evidence count, node type, and importance.
- Selecting a node or edge should open a detail drawer with evidence, related KB entries, run provenance, editable fields, and audit history.
- Provide layout controls: fit view, center on node, expand neighborhood, hide low-confidence edges, highlight scenario path, and reset filters.
- Use visual encoding consistently: edge thickness for strength, opacity for confidence, color for direction/type, node size for importance, border/halo for instability.
- Keep accessibility in mind: graph details must also be available in tables/lists for search, keyboard use, and screenshots.

## 9. Testing and acceptance expectations

Every meaningful GUI slice should include:

- Typecheck/build coverage (`npm run typecheck`, `npm run build`).
- API contract checks for endpoints used by the page.
- Component or browser tests for core interaction states when practical.
- At least one failure/empty-state test or story for user-facing workflows.

A page is not “integrated” until it reads from real backend endpoints, writes through real backend mutations where applicable, handles errors, and has at least minimal build/test evidence.
