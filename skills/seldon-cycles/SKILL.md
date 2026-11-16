---
name: seldon-cycles
description: Model recurring macro cycles in Seldon (business, credit, monetary, dollar, commodity, conflict, technology-capex, generational or political cycles, plus short or unconventional rhythms such as seasonality or chip cycles). Defines cycle factors, loads dated historical series from CSV/JSON, fits sin/cos harmonic or damped-oscillator (inertia and whiplash) models with red-noise significance and holdout checks, searches residuals for hidden cycles, combines factors, scores topic-to-cycle relevance, renders SVG charts, and feeds cycle priors into forecasts. Use when making or refreshing a forecast, when a question involves regime timing, historical recurrence, momentum/overshoot dynamics, or "where are we in the cycle", or when a recurring pattern appears in research.
---

# Seldon cycles

Seldon stores cycle factors, dated observations, immutable fits and composites in the shared research database. You do the research (finding and coding historical data); Seldon validates, fits, records history and connects results to forecasts. No model provider or network access is used by these commands.

Model theory, verdict rules and limits: [docs/cycles.md](../../docs/cycles.md). Terms: [GLOSSARY.md](../../GLOSSARY.md).

## Setup

- Run from the Seldon repository: `uv run seldon research --db /ABSOLUTE/PATH.db cycles <command>`. Use the same shared database as other research (see root `AGENTS.md`); `parallax research cycles ...` uses Parallax's installed database automatically.
- HTTP equivalents live under `/workspace/cycles` on the Seldon API (same authentication).
- Discover before writing: `cycles catalog` (models, phase conventions, verdict meanings, templates) and `cycles schema --part apply|fit|import|combine|fit-request`.
- Add `--out FILE` to any command to save its output.

## Using cycles in every forecast

Before any forecast or rerun, run `cycles relevance --scenario SCENARIO_ID`. It shows the topics the question's entities match and every cycle it inherits, ordered by `target_score` (relevance to topics containing the forecast target) and then the highest topic `score`. Use all of them, following the same rule printed in each question's handoff:

- State each inherited cycle's phase or projection at the resolution date, its verdict and its relevance.
- Only `supported` cycles with material relevance may shift probabilities. `weak`, `under-identified` and `not-oscillatory` cycles are context, and a weak cycle that contradicts evidence never overrides it.
- If research shows a recurring pattern no stored cycle covers, add it (step 2 onward), including very short or unconventional rhythms such as seasonality, guidance or earnings cadence, inventory, election or policy rhythms. Score its topic relevance, refit, and cite it as a hypothesis until its verdict is supported.

## Workflow

1. **Reuse first.** `cycles export --format markdown` lists factors, data coverage, preferred fits and composites. Extend an existing factor instead of creating a near-duplicate. `cycles export --factor ID` shows its observations and full fit.
2. **Define the factor** with `cycles apply changes.json` (get `base_revision` from `cycles export`):

   ```json
   {
     "request_id": "define-us-credit-cycle",
     "base_revision": "FROM_EXPORT",
     "agent": "your-agent-name",
     "reason": "Hypothesis: US credit booms and busts recur",
     "factors": [{
       "id": "us-credit-cycle",
       "name": "US credit and speculation cycle",
       "template": "financial-speculation",
       "region": "United States",
       "measurement": "measured",
       "units": "credit-to-GDP gap, percentage points",
       "hypothesis": "Leverage builds during stability until a bust forces deleveraging",
       "references": ["https://example.org/literature"],
       "entity_ids": ["SHARED-ENTITY-UUID-IF-ANY"]
     }]
   }
   ```

   - One consistent measure per factor. Splice different sources only through a `derived` factor, or say so in `note`.
   - Name the `region`; cycles are population-specific. Set `low_label`/`high_label` so values have meaning.
   - `coded` factors (historical records scored by you) need a `rubric`. Code from primary indicators and events, never from a theory's own phase dates (circular).
   - A template fills unspecified period bounds, labels and model. Inspect it in `cycles catalog`.
   - Find entity UUIDs with `research library QUERY`; `entity_ids` must already exist.
3. **Load history.** Download a CSV with your own tools, then:
   `cycles import us-credit-cycle data.csv --source-name "BIS credit-to-GDP gaps" --source-url https://... [--value-column COL] [--uncertainty-column COL] [--kind coded] [--year-anchor mid]`.
   FRED-style `date,value` and `year,value` files work directly; `.` and blank values are skipped. Or put `observations` in an apply file. Each value records its date, source, retrieval time and optional standard error. To correct a value, resubmit the same observation `id`. To remove one, set `"status": "withdrawn"`. Old versions stay in history.
   - Convert event lists (wars, crises) into rates or intensities per period. Log-transform heavy-tailed magnitudes.
   - Code multi-year eras as dated points (midpoints or annual samples), with `uncertainty` reflecting coding doubt.
4. **Fit.** Applying data refits each affected factor with its preferred `fit` specification automatically. Compare alternatives without changing what forecasts use:
   - `cycles fit ID --model oscillator`: inertia, damping and overshoot.
   - `cycles fit ID --set harmonics=2`: asymmetric slow-boom/fast-bust shape.
   - `cycles fit ID --set period_years=80`: test one theory's stated period.
   - `cycles fit ID --set since=1945-01-01`: fit one regime only.

   These are recorded as exploratory. To promote one, update the factor's `fit` through `apply`. Add `--full` to print curves and projections.

   | Situation | Model |
   | --- | --- |
   | Stable recurring wave; want phase and next peak/trough | `harmonic` (`harmonics` 2-3 if booms and busts are asymmetric) |
   | Momentum, overshoot after shocks, irregular cycle lengths | `oscillator` (`order` 2) |
   | Several overlapping waves | `harmonic` with `cycles` 2-3, or separate factors |
5. **Read the verdict before claiming anything.**
   - `supported`: beats red-noise surrogates (p < 0.05), at least two observed cycles, no negative holdout skill. You may report it as a fitted pattern, still not a law.
   - `weak`: report only as a hypothesis. Autocorrelated noise produces convincing fake cycles (Slutsky-Yule).
   - `under-identified`: fewer than two cycles observed. Do not cite a phase or turning-point date as informative.
   - `not-oscillatory`: inertia or persistence, but no intrinsic cycle.

   Also read `warnings`, `backtest`, the `period_se_years` and each turning point's `window`/`support`.
6. **Score topic relevance.** Topics are reusable research subjects matched to questions by explicit `entity_ids` or normalized entity `tags` (e.g. `role:hyperscaler`). In an apply file, add `topics` and `relevance` rows: `{"topic_id", "factor_id" or "composite_id", "score", "direction", "channel", "horizon", "rationale", "assessed_at"}`. Score 0.25 means background context (the default floor for entering a question's context), 0.5 a material driver and 0.8 or more central. `direction` is the topic's typical move when the cycle is high. Resubmit the same row to revise a score; history is kept. Score against the topic's outcome, not upstream drivers. `cycles relevance --topic ID` shows the lookup table.
7. **Search for hidden factors.** `cycles discover ID` reports residual periodicities. A candidate with p < 0.05, at least two cycles and no harmonic `relation` suggests a missing driver. Hypothesize the driver, find an independent series and add a factor. For a latent variable seen only through proxies, add a `derived` factor whose `derived_from` lists weighted, lagged components (negative weight inverts). A residual peak is not a discovered cause.
8. **Combine.** Save reusable `composites` with `apply`, or try `cycles combine --component a:1 --component b:-0.5:5` (`factor:weight:lag_years`). Results include the composite path, **alignment** (1 = cycles share a phase and reinforce, as in a "Fourth Turning" convergence), future alignment windows, and pairwise lead/lag. Lead/lag correlations are not causal evidence.
9. **Show charts.** `cycles chart --factor ID --out chart.svg`, `--composite ID`, or `--component ...`. HTTP: `/workspace/cycles/factors/ID/chart.svg`. Share the chart with the user when presenting results.
10. **Feed a forecast.** Questions inherit cycles through topic relevance automatically. Link a factor's `entity_ids` only when it measures the same concept as an entity (e.g. the dollar cycle and the US dollar node). `cycles outlook --scenario SCENARIO_ID [--at DATE]` evaluates inherited cycles at the question's latest horizon date, or at `--at` for a specific forecast resolution date.
   - The outlook's `evidence_template` is a ready-made **assumption** evidence record. Fill `confidence` and attach it to the driver node the cycle bears on. Node assessments can then cite it. Cite the fit ID in `base_rate`/`assumptions`.
   - Save every evidence round (including cycle priors on shared nodes) before the forecasts that use it. Indexing a shared node from another question can otherwise mark a just-saved forecast's knowledge as changed.
   - Never submit a cycle projection as an observation.
   - Linked cycle context is frozen into forecast snapshots and exports. New data or refits mark linked questions' knowledge as changed; queue `research rerun` when a forecast should be refreshed.
11. **Keep current.** After bulk changes run `cycles refit` (fits only missing or stale preferred fits; safe to repeat). `cycles export` shows `fit_status`: `fresh`, `stale` or `missing`.

## Guardrails

- Fits are model-derived structural priors, not evidence that a cycle will continue. State the verdict, data span and caveats whenever you cite one. Structural breaks end cycles.
- Keep requests idempotent: reuse a `request_id` only for identical input; on a 409/stale revision, re-export and reconcile.
- Do not delete or rewrite history to improve a fit. Withdraw bad values with a note, and keep conflicting series as separate factors.
- Ideological or political factors need an explicit dimension, region and rubric. No universal left/right scale exists.
- Research requests do not authorize trades.

## Troubleshooting

- `Not fitted yet: ... needs at least N observations`: add data or reduce `harmonics`/`cycles`/`order`.
- `Period search range ... is empty`: widen `period_min_years`/`period_max_years`, or the span is too short for the template's range.
- `Unknown research entity`: the UUID is not in the ERG; find it with `research library` or create the node first.
- Turning points with low `support` or wide windows: phase is poorly determined. Report the window, not the point.
