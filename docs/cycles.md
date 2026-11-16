# Cycle factors: modeling and semantics

The hypothesis behind this feature: macro history can be partly described as overlapping waves, each a recurring swing between two poles. Examples are credit booms and busts, war and peace, globalization and localization, and left/right moods. Systems with momentum (inertia) and corrective feedback overshoot, which produces whiplash. Seldon treats every such wave as a testable factor, not an assumed law. This document explains the models and what their outputs mean. The operational procedure is the [seldon-cycles skill](../skills/seldon-cycles/SKILL.md), and code ownership is in the [cycles map](../src/seldon/workspace/cycles/AGENTS.md).

## Records

| Record | Meaning |
| --- | --- |
| Factor | One recurring dimension for a named region, with poles (`low_label`/`high_label`), units, a measurement mode, a hypothesis, explicit entity links and a preferred fit specification. |
| Observation | A dated value with source URL, retrieval time, kind (`measured`, `coded` with a rubric, or `assumption`) and an optional standard error. Corrections and withdrawals are new versions. |
| Derived factor | A latent (hidden) variable computed as the weighted mean of standardized, optionally lagged component factors. Use it when a driver is seen only through proxies. |
| Fit | An immutable model result for one data revision and specification. |
| Composite | A saved weighted combination of factors, used for combined outlooks and alignment. |
| Topic | A reusable research subject (e.g. gold, AI investment) matched to questions by explicit entity UUIDs or normalized entity tags. |
| Relevance | A scored judgment (0-1) of how strongly a cycle or composite bears on a topic's outcome. It carries a direction (the topic's typical move when the cycle is high), a channel, a horizon and a rationale. It is not a correlation. |

## Models

### Harmonic: deterministic waves

`y(t) = trend(t) + Σ_periods Σ_k [a_k cos(2πkt/P) + b_k sin(2πkt/P)] + ε`

- The **period search** maximizes the generalized (trend-aware, floating-mean) Lomb-Scargle power over a frequency grid, then refines it with golden-section search. This works with irregular historical dating. `period_years` instead fixes a theory's stated period to test it.
- **Harmonics** (`k > 1`) give non-sinusoidal shapes. Two or three harmonics capture a slow speculative build-up followed by a fast collapse.
- **Several cycles** are found greedily (each search runs on the model containing the earlier periods), then refined jointly.
- **Anchoring:** projections start from the latest observation. The last residual decays toward the fitted curve at the residuals' own AR(1) persistence, and the interval grows from near zero to the full residual variance. Without anchoring, a poorly fitting cycle would project from its curve rather than from current conditions; for example, the federal funds fit projected a negative rate while the actual rate was 3.88%. The holdout's trend baseline is anchored the same way, so skill measures what the cycle adds beyond AR(1) persistence.
- **Uncertainty:** the period standard error comes from the curvature of the residual sum of squares. Residual autocorrelation inflates the covariances. Projection bands come from 300 draws of period and coefficients plus residual noise, so bands widen as phase uncertainty accumulates. Turning-point windows are the 10th-90th percentile timing of the matching extremum across draws. `support` is the share of draws that contain it.
- **Phase** refers to the fundamental of each cycle relative to trend: 0 = peak, π/2 = declining, π = trough, 3π/2 = rising. Factor `phase_labels` rename the quadrants. The generational template, for example, maps them to High, Awakening, Unraveling and Crisis.

### Oscillator: inertia and whiplash

The series is resampled to a regular grid and detrended, and an AR(p) model is fitted (`x_t = Σ φ_i x_{t-i} + ε_t`). This is the discrete form of a damped, noise-driven second-order system, `x'' + 2ζω x' + ω²x = shock`, which is the textbook mechanism of momentum plus corrective feedback.

- Complex characteristic roots `r·e^{±iθ}` imply an intrinsic period `2π/θ` steps, damping `r`, half-life and damping ratio `ζ`. Real roots mean persistence without oscillation.
- **Persistence** (`Σφ`) measures inertia: how much of a deviation carries forward.
- The **impulse response** traces the system's path after a single shock. Its negative excursion, **overshoot**, measures whiplash: how far the system swings past equilibrium after the shock. This is the quantitative form of "markets and wars have inertia".
- **Evidence for oscillation** is the share of coefficient draws with complex dominant roots, plus the AIC gain over AR(1), which cannot oscillate.
- Forecasts revert to trend. Their bands include future shocks and coefficient uncertainty. Order 2 gives a deterministic phase; higher orders do not.

### Choosing

A harmonic fit answers "is there a stable wave, and where are we on it?" An oscillator answers "how much momentum and overshoot does this system have?" Fitting both and comparing them is cheap: only the factor's preferred specification drives forecasts.

## Honesty checks and verdicts

Autocorrelated random series produce convincing apparent cycles (the Slutsky-Yule effect). Long social cycles also have few historical repetitions. Every fit therefore carries:

- **Red-noise significance (harmonic):** the maximum periodogram power over the searched band is compared with AR(1) surrogates simulated on the same irregular dates. The lag-1 correlation includes any real cycle, which makes the test conservative. A fixed period is tested at that period only.
- **Holdout backtest:** the final share of the span (default 20%) is withheld, refitted and forecast. The result is compared with persistence and trend-only baselines.
- **Cycles observed:** span divided by period. Below two, phase and period are under-identified.

| Verdict | Rule |
| --- | --- |
| `supported` | Harmonic: p < 0.05, at least two cycles observed, holdout skill vs trend not negative. Oscillator: complex roots in at least 90% of draws, AIC gain over AR(1) > 2, stationary, at least two implied cycles. |
| `weak` | Fitted, but fails one of those tests. Treat it as a hypothesis. |
| `under-identified` | Fewer than two cycles observed. |
| `not-oscillatory` | Oscillator found no intrinsic cycle. |

A `supported` verdict is a statistical description of the past, not evidence that the mechanism persists.

## Hidden cycles and latent factors

`discover` computes a periodogram of a fit's residuals and tests each peak against the maximum residual power of red-noise surrogates (a family-wise test). Peaks near the fitted period or its harmonics are labeled: they indicate amplitude or phase drift, or a need for more harmonics, rather than a new cycle. A remaining significant peak is a prompt to hypothesize a driver and measure it independently. Latent variables observed only through proxies become derived factors.

## Combination

- **Composite path:** each component is standardized (z-score over its observed data). The path uses observed values, then the preferred-fit projection. Components are lagged, weighted (a negative weight inverts) and averaged. The band assumes independent components.
- **Alignment:** `R(t) = |Σ|w_k| e^{iφ_k(t)}| / Σ|w_k|` over components with a defined phase (the Kuramoto order parameter). R near 1 means the cycles share a phase and their swings reinforce, which is the "several cycles turning together" pattern that generational theories describe. Future windows above 0.8 are listed. R is not a probability.
- **Lead/lag:** this is the best cross-correlation within ±30 years on observed data. Among near-equal correlations, the shortest lag is preferred because periodic series also correlate in anti-phase. The result is labeled negligible, weak, moderate or strong. Autocorrelation inflates these correlations, and they do not show causation.

## Connection to forecasts

- A question inherits a cycle in either of two ways. It inherits explicitly when the factor's `entity_ids` include a scoped node (the factor measures that entity). It inherits through the **topic relevance lookup** when a topic matches scoped entities (by UUID or tag) and scores the cycle at or above the relevance floor (`RELEVANCE_FLOOR`, 0.25). Each inherited cycle reports `score`, the highest across matched topics, and `target_score`, the highest across topics containing the forecast target. Context is ordered by `target_score` so cycles that bear on the outcome come before cycles that only touch upstream drivers. `research cycles relevance --scenario ID` shows the resolution.
- `scoped_graph` adds an outlook evaluated at the latest ISO date in the scenario horizon. Both the built-in prediction pipeline and external-agent exports receive this context. A question with several forecast dates freezes the scenario-level evaluation; per-date readings belong in the cycle-prior evidence attached to driver nodes (`cycles outlook --at`).
- All research entry points carry one message (`catalog.CYCLE_GUIDANCE`): workspace handoffs, rerun requests, the built-in synthesizer prompt and this skill. Use every relevant cycle. Only supported, materially relevant cycles shift judgments. Add new cycles, including short or unconventional ones, when a recurring pattern emerges.
- The context is frozen in forecast graph snapshots and included in knowledge revisions. New data or refits for linked factors therefore mark those forecasts' knowledge as changed, while frozen snapshots and saved reports stay unchanged. Unlinked cycle work does not affect a question.
- The built-in synthesizer receives linked cycle priors with an instruction to weigh verdicts. External agents receive an `evidence_template` to attach as an assumption, never as an observation.
- Workspace Markdown exports and generated reports show a "Cycle priors" table.

## Storage

The cycle registry uses append-only `AgentRun` events (`phase = "cycle_registry"`) serialized by a lock row in `sources`, as the perspectives graph does. No migration was needed. Request IDs make writes replay-safe, and the registry revision rejects stale writers. State is rebuilt from events on read, which is adequate for thousands of observations. A materialized projection is the scaling step if registries grow much larger.

## Limits and extension points

- Data acquisition is agent-driven. There are no built-in downloaders or scheduled refreshes; `refit` must be invoked by an agent or a scheduler.
- Structural breaks, drifting periods and regime changes are not modeled beyond `since`/`until` windows. Candidate extensions are wavelets (time-varying period), state-space stochastic cycles with Kalman filtering, and self-exciting (Hawkes) point processes for event histories such as wars. `cycles catalog` lists them as not implemented.
- Derived factors and oscillators interpolate onto regular grids, which smooths sparse history and can inflate persistence. Interpolated shares are reported.
- Template period ranges come from contested literature and only bound the period search.
- Relevance scores are judgments. No estimate maps a cycle's phase to a topic's outcome distribution.
- Composite outlooks interpolate a quarterly grid; their bands assume independent components.
