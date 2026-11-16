# Typed Seldon HTTP clients

[Root AGENTS.md](../../../../../AGENTS.md) contains the project-wide lookup table.

This layer translates console state into backend HTTP requests. Transport is shared; modules do not implement forecasting, validation or persistence.

| File | Responsibility |
| --- | --- |
| `client.ts` | Server/browser API bases, API-key headers, uncached JSON GET/mutations and optional-error wrapper. |
| `types.ts` | Shared shapes for scenarios, KB, ERG, predictions, runs, configuration and analytics. |
| `scenarios.ts` | Search/detail, draft/create/edit/delete, phase jobs, feedback and browser report links. |
| `kb.ts` | Search filters, entry/version/related-record reads, edits, supersession and contradictions. |
| `graph.ts` | Node/edge filters and edits, neighborhoods, snapshots/diffs, reuse and merge review. |
| `runs.ts` | Execution filters/detail/messages/related records/audits and retry. |
| `predictions.ts` | Prediction detail/history/evidence and advanced-analysis requests. |
| `calibration.ts` | Summary/outcome/feedback reads and prediction resolution payloads. |
| `settings.ts` | Health/configuration reads, model updates and data-clearing requests. |
| `jobs.ts` | Persisted job list/detail reads; it does not schedule polling. |
| `analytics.ts` | Aggregate chart data, optionally scoped by scenario. |

Keep endpoint/auth policy centralized and preserve separate browser/server base configuration. Report URLs are ordinary links and do not attach transport auth headers. Avoid exposing server secrets through public environment variables. Update corresponding mock fixtures and contract checks when endpoint shapes change.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
