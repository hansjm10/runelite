# Retrospective volume comparison — 2026-11-02

## Outcome

Historical volume gives a **small improvement in the declared primary metric**, not
an unqualified improvement in forecasting behaviour. No weights were changed or
trained, and no new market data was fetched.

| Method | Macro WAPE (%) |
| --- | ---: |
| Last-observed-price persistence | 4.353783 |
| Same UTC hour the previous day | 8.439220 |
| Chronos-2, prices only | 3.987356 |
| Chronos-2, prices plus historical volume | 3.914292 |

Volume lowers macro WAPE by **0.073064 percentage points**, or **1.8324% relative
to prices only**. It improves MAE on **71 of 100 item/price-side series**, worsens
29, and ties none. Both variants beat persistence in aggregate; the volume-enabled
variant beats it on 66 series, versus 60 for prices only.

The volume-enabled per-series and aggregate metrics **exactly reproduce the earlier
expanded benchmark**. Most of the model's aggregate advantage over persistence
remains when volumes are removed.

## Secondary metrics: a meaningful tradeoff

All entries below are macro means across the same item/price-side series:

| Metric | Prices only | Prices + volume |
| --- | ---: | ---: |
| Price-change MAE (basis points) | 616.778 | 725.838 |
| Direction accuracy (%) | 53.671 | 54.995 |
| Weighted quantile loss (%) | 2.713853 | 2.672256 |
| Nominal 80% interval coverage (%) | 77.317 | 77.893 |
| Interval width relative to actual price (%) | 12.430 | 12.402 |

**Price-change error worsens with volume**, even though WAPE and quantile loss
improve. Change error divides each error by its last observed context price; WAPE
normalizes each series' total absolute error by total actual prices. Those are
different weightings, so improvements need not agree. Direction treats unchanged
prices as a separate outcome. Neither directional accuracy nor coverage establishes
profitable trades or guaranteed confidence.

Observed CPU inference time was about **41.4 seconds** for prices only and **96.0
seconds** with volume, excluding loading. These are observed run times, not a
controlled performance benchmark.

## Scope and pairing

- Existing frozen 50-item hourly cohort, with both prices forecast jointly.
- Historical test: **2026-10-31 20:00 UTC through 2026-11-02 20:00 UTC**, end exclusive.
- Same pinned model, quantiles, one-hour publication-gap assumption and up-to-120-hour
  context windows. No future prices/volumes enter any origin; attention groups isolate
  origins/items. Earlier outcomes enter later contexts only after the gap.
- **4,481 scored outcomes per method**, verified directly against the four CSV masks.
- **319 shared exclusions**: 195 missing actuals and 124 missing seasonal references.
  Thinly traded periods can therefore be underrepresented in the scored subset.
- Aggregate WAPE improved with volume in each of the three preselected liquidity
  tiers, but these overlapping descriptions are not independent validation tests.
- Calendar-week slices contain only 28 and 20 hours, not two independent full weeks.

Dataset SHA-256:
`f24c8fd8bcd6ce93750549da54179a928b863720db18d2aeb5f3b6f1871f2597`

The source CSV, original manifest, previous benchmark metrics and frozen future-test
plan were hash-checked before/after execution and remained unchanged. Actual
retrieval timestamps and experiment creation time were preserved, not backdated.

## Interpretation and next decision

This is explicitly **retrospective/exploratory** because the period's earlier
benchmark results were already inspected. Historical revisions and actual API
publication delays remain unknown. The comparison is useful diagnostic evidence,
not fresh independent validation, statistical significance, or GP profitability.

Keep both variants as candidates; the current volume-enabled default was not changed.
Before choosing trading signals, repeat the fixed comparison on another uninspected
historical period and investigate the worse price-change cases. There is no reason
to modify pretrained weights based on this small aggregate difference, nor to wait
for a future date merely to run a historical backtest.

## Implementation and verification

`ablation.py retrospective` runs this separate offline comparison without weakening
the existing fresh-holdout gates. Existing result directories cannot be overwritten.
The report and JSON identify `evaluation_mode: retrospective_exploratory` and include
the original dataset provenance and the actual historical test interval.

- **63 Python tests passed**, including new retrospective isolation/provenance checks.
- Scoped Pyright check: **zero errors or warnings**.
- Both full 2,400-origin inference passes completed on the cached checkpoint.
- No market requests, model downloads, training, game interaction or trading occurred.

Detailed local outputs:
`output/volume-ablation-retrospective/results/{report.md,metrics.json,forecasts.csv}`.
See [VOLUME_ABLATION.md](VOLUME_ABLATION.md) for commands and the separate future plan.
