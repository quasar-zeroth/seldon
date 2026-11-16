# Gold in six months: dated agent-workflow example

Question: **Where will gold price be in 6 months?**

This example was researched on **28 September 2026**, with a resolution date of **28 March 2027**. It is a working demonstration of an external agent researching, building, expanding, and forecasting from a Seldon DAG. Forecast probabilities are subjective and uncalibrated. Replaying the files does not refresh the research.

## Reproduce without a provider account

```bash
uv sync
uv run python examples/gold/replay.py --db data/gold-example.db --out data/gold-example
```

The script creates a new scenario each time and prints its IDs and artifact paths. It uses the normal workspace schema and service, creates durable KB/graph/prediction/run records, and exports `workspace.json` and `report.md`. Existing scenarios are preserved. The three input files can also be submitted through `research apply` or `/workspace/apply` after filling the scenario ID and current revision.

- `01-research.json`: initial drivers, sourced observations, explicitly labeled causal assumptions, and research log.
- `02-expand.json`: updated spot/real-yield evidence plus currency and investor-flow dependencies.
- `03-forecast.json`: final bounded review, per-node forecasts, synthesis, branches, resolution criteria, assumptions, opposing arguments, and gaps.

## Graph and outcome

The dependency structure includes US–Iran conflict → Hormuz shipping → oil/energy inflation → Federal Reserve policy → bond-market real yields → gold. Central-bank buying, the dollar, investor flows, and safe-haven effects add further paths. The graph deliberately preserves opposing mechanisms: geopolitical tension can increase safe-haven demand while inflation-driven tightening can hurt gold.

The saved illustrative forecast has a **45% base branch of USD 3,900 to below 4,700 per troy ounce**, a **30% branch below 3,900**, and a **25% branch at or above 4,700**. These thresholds and probabilities are the researching agent's judgments, not claims made by the sources or outputs of a fitted statistical model. The resolution uses the last published LBMA PM USD benchmark on or before the resolution date, accounting for non-trading days.

## Dated evidence

The example records a 28 September spot observation of USD 4,171.85/oz at 06:27 UTC from [Reuters via MarketScreener](https://ca.marketscreener.com/news/gold-drops-more-than-1-on-us-rate-hike-bets-ce785adcdb89f32d). It is a timestamped reference, not a streaming price.

The principal primary sources are the [Federal Reserve's September decision](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm), [FRED real-yield observations](https://fred.stlouisfed.org/series/DFII10), [World Gold Council official-sector demand](https://www.gold.org/goldhub/research/gold-demand-trends/gold-demand-trends-q2-2026/central-banks), [WGC market commentary](https://www.gold.org/goldhub/research/gold-market-commentary-august-2026), and [EIA's historical Hormuz transmission analysis](https://www.eia.gov/Todayinenergy/detail.php?id=67865). [AP's dated conflict report](https://apnews.com/article/iran-us-yemen-saudi-houthis-hormuz-september-21-2026-82714681bde58c6525c2d7a1bc587b25) provides additional security context.

Exact observations, publication/retrieval dates, links, confidence judgments, and assumptions live in the JSON inputs and exported KB. The last review found no new material drivers within the reviewed source set; it does not establish exhaustive web coverage. Fresh demand flows, shipping volumes, calibrated return distributions, and future policy outcomes remain explicit gaps.

For another date or subject, use [the general agent workflow](../../docs/agent-workflow.md), research again, and regenerate the graph and forecast.
