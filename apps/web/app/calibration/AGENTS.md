# Calibration and outcome feedback

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table.

`page.tsx` combines calibration summaries, predictions, feedback entries, outcome checks, scenarios and analytics. Its resolution action sends actual outcomes, source references, lessons, graph corrections and optional KB/re-prediction choices to the backend.

Local helpers render the prediction picker, resolved table, miss analysis and fallback confidence buckets; shared chart components render analytics. `error.tsx` and `loading.tsx` provide route boundaries.

Backend scoring/resolution logic is authoritative. Keep forecasts distinct from observed outcomes and retain sample-size/staleness signals. Guided correction fields and optional manual JSON are request inputs, not proof that a correction has been applied.

Actual implementation, API contracts and tests are the source of truth; this file explains broad design. Update relevant AGENTS.md files when guidance is incorrect, missing or newly relevant. Keep maps concise; split growing detail into focused linked documentation.
