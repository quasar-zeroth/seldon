# Shared presentation and browser interactions

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table.

| File | Responsibility |
| --- | --- |
| `shell.tsx` | Console navigation and shared page shell. |
| `ui.tsx` | Headers, cards, status/evidence/source labels, loading/error states, mutation disclosure and audit rendering. |
| `scenario-draft-chat.tsx` | Browser draft/edit/create flow through same-origin routes; preserves prompt and exposes an editable fallback when drafting fails. |
| `graph-explorer-canvas.tsx` | React Flow node/edge rendering, layouts, overlays, minimap and zoom controls. |
| `charts-dashboard.tsx` | Recharts scenario/calibration/confidence/sentiment/risk/model analytics with empty states. |

Styles live in `app/styles.css`; domain types come from `lib/api/types.ts`. Shared UI does not fetch audit records itself. `ConfirmMutationDialog` is a disclosure with nested action content, not a modal state machine. Canvas selections currently do not navigate to detail, and graph positions are presentation-only.

Do not mistake fallback drafting text or display defaults for observed research evidence. Keep units/uncertainty visible and reconcile interactive mutations with backend responses.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
