# Cycle factors

[Root AGENTS.md](../../../../AGENTS.md) contains the project-wide lookup table; [workspace map](../AGENTS.md) covers research integration. Agent procedure: [seldon-cycles skill](../../../../skills/seldon-cycles/SKILL.md). Modeling rationale and limits: [docs/cycles.md](../../../../docs/cycles.md).

Recurring macro dimensions (credit, war intensity, globalization, generational mood, ideology) are stored as factors with dated, attributed observations. Deterministic curve fits produce phase, turning points and projections that feed forecasts as explicit, model-derived priors. No provider or network calls are made.

| File | Logic |
| --- | --- |
| `schemas.py` | Factor, observation, fit-spec, composite, apply/import/combine contracts and provenance rules. |
| `catalog.py` | Discovery catalog: models, phase conventions, verdict meanings, extension points, theory templates, `RELEVANCE_FLOOR` and `CYCLE_GUIDANCE` (the single cycle message used by every research entry point). |
| `fitting.py` | Pure numpy models: harmonic period search (generalized Lomb-Scargle), AR(p) oscillator, red-noise surrogates, holdout backtests, turning points, residual spectrum. |
| `__init__.py` | Append-only `AgentRun` event store (`cycle_registry`), `Source` lock row, revisions/replay, derived-factor series, automatic refits, CSV import, topics and relevance lookup, views, outlook and forecast context. |
| `combine.py` | Standardized composites, phase alignment windows and lead/lag correlations. |
| `charts.py` | Self-contained SVG charts with light/dark tokens and tooltips. |
| `cli.py`, `api.py` | `seldon research cycles ...` and `/workspace/cycles` adapters over the same functions. |

Invariants:

- Observations are append-only. Revisions and withdrawals add versions, and a fit records the data revision it used.
- Fit IDs are deterministic in the factor's data revision, normalized spec and `ALGORITHM_VERSION`; random draws are seeded from those digests. Bump `ALGORITHM_VERSION` when fitting behavior changes so new fits do not reuse old IDs.
- Only the factor's preferred `fit` spec drives forecast context. Other specs are recorded as exploratory comparisons.
- Derived factors form a DAG and accept no direct observations; component changes refit dependents.
- `research_context` includes a cycle only through an explicit entity link or a matched topic scoring it at or above `RELEVANCE_FLOOR`. Unrelated cycle work must not change a question's knowledge revision, and snapshots omit `cycles` when empty, so older revisions stay stable. Order by `target_score` (topics containing the forecast target) before the highest topic score.
- Harmonic projections and backtest baselines are anchored by AR(1) residual persistence (`ALGORITHM_VERSION` 2). Series are memoized per loaded state; `_index` resets the memo whenever a state mutates.
- Research handoffs, rerun prompts and the built-in synthesizer must keep using `CYCLE_GUIDANCE` (or an equivalent built-in wording) rather than diverging copies.
- Verdicts and warnings must accompany every surfaced fit. Never present a projection as an observation.

Adding a model: implement it in `fitting.py` with the same output keys (`params`, `diagnostics`, `turning_points`, `projection`, `curve`, `warnings`, `verdict`), extend `FitSpec.model`, register it in `catalog.MODELS`, handle phase in `phases_at`, and add recovery plus null-model tests.

Verification: [test_cycles.py](../../../../tests/unit/test_cycles.py) covers model recovery, red-noise rejection, oscillator overshoot, residual discovery, persistence/replay/conflicts, derived factors, combination, topic relevance selection and target ordering, guidance in handoffs and reruns, forecast freezing/staleness, reports, CLI and HTTP.

Implementation is the source of truth: code, schemas, CLI help and tests outrank design notes. Update relevant AGENTS.md files and the skill when behavior changes; keep numbers and contracts in code.
