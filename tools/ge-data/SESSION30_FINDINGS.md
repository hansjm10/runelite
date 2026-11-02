# First 30-minute strategy comparison

**Conclusion: the benchmark and manual sidebar work as a research prototype, but this
experiment does not demonstrate a useful trading edge.** The generic cohort and fixed
rules deploy almost none of a 10m bankroll. Improving opportunity selection and measuring
execution are more important next steps than tuning Chronos weights on this sample.

## Evidence and scope

- 50 previously frozen items; 52 bounded public requests, no scheduler or bulk crawl.
- Actual five-minute resolution. Shared window: **2026-11-01 21:35 to 2026-11-02 21:30 UTC**,
  end exclusive. 14,350 explicit rows, including **3,073 missing buckets** (21.4%). Null
  fields and real zero volumes remain distinct; no interpolation or timestamp relabelling.
- Dataset SHA-256: `0388eecbf1cd6b1f768fba144eb216d9bba3e962d6b92b2de35b3fa56ee9b9bd`.
- 24 independent half-hour sessions from **2026-11-02 09:30 to 21:30 UTC**. Two policies,
  five fill hypotheses: 240 simulated session records, not 240 independent market samples.
- 245 eligible item/origin forecasts, about 25.5 seconds including model loading. Local
  CPU, pinned Chronos-2 revision `29ec3766d36d6f73f0696f85560a422f50e8498c`, no training.
- The cohort and nearby hourly period were already inspected. This is exploratory
  historical analysis, not an untouched holdout or a profitability validation.

Authoritative local artifacts: `output/session30/results-paired/`. The original
`output/session30/results/` is retained. Its first marked-equity summaries used different
priced subsets for the two policies. The corrected summaries use a common mask per
scenario; `metrics.json` records the correction and hashes of the original inputs.
**Forecasts, session events, policy parameters and fill assumptions were not changed or
rerun.** The full per-session records remain available, including excluded valuation cases.

## Reference scenario: assumed 1% participation

All figures below are **hypothetical**, not observed executions or expected profits.
Most measures include all 24 sessions; marked equity uses 23 common priced sessions.

| Measure per 30-minute session | Liquidity/margin baseline | Chronos price-risk guard |
| --- | ---: | ---: |
| Mean simulated realized GP | 13.71 | 11.58 |
| Mean marked-equity change, GP | -30.91 | -12.26 |
| Mean residual inventory at purchase cost, GP | 1,262.54 | 741.29 |
| Mean time-averaged committed capital, GP | 7,969.09 | 3,097.15 |
| Flat at deadline | 66.7% | 75.0% |
| Sessions with no buy fills | 0/24 | 7/24 |
| Sessions with unpriced inventory | 1/24 | 0/24 |

Committed capital includes buy reservations and inventory at cost. Its time average is
capital-GP-minutes divided by 30: approximately **0.080%** and **0.031%** of the 10m budget.
This is not a meaningful test of deploying the full bankroll. The rules are conservative,
and the cohort was selected for broad hourly forecasting research, not fast-flip suitability.

Realized gains exclude unsold units; marked equity includes a hypothetical inventory
valuation, not a sale. Common-mask marked results omit one session for both policies,
including a priced Chronos outcome; they do not describe the complete risk distribution.
The all-session cash floors and residual inventory remain in the JSON. Flat percentages
include sessions with no trades, so Chronos's higher flat rate alone is not a trading win.

## Fill stress results

- **No fills:** zero gains and all sessions flat for both policies. This is inactivity,
  not successful execution.
- **Buys without sales:** zero realized gains and residual inventory. Baseline has five
  unpriced sessions. On the 19 common priced sessions, mean marked changes are -238.68 GP
  and -59.68 GP. Seven Chronos sessions make no purchases.
- **Thin 0.1% participation:** mean realized gains are 0.04 GP and 0.75 GP; common-mask
  marked changes are -13.22 GP and -1.26 GP over 23 sessions.
- **Optimistic 5% participation:** mean realized gains are 5.96 GP and 18.04 GP; common-mask
  marked changes are -29.00 GP and -4.64 GP over 22 sessions. More assumed fills do not
  guarantee better returns: exit repricing can realize losses.

These participation settings are not fitted probabilities. Transaction-side averages do
not reveal available quotes, queue position, your fill latency or the distribution of
prices within a bucket. Results cannot establish what manual offers would have earned.

## What is usable now

[SESSION30.md](SESSION30.md) documents collection, offline replay and the manual sidebar.
The first historical preview legitimately contains **no candidates**. It has not been
replaced with a better-looking session. No current snapshot plan was exported from the
now-stale dataset, and no file was installed in the user's RuneLite directory.

82 Python tests, scoped Pyright, 58 focused Java tests, client Checkstyle and the shaded
JAR build passed. These checks cover software behavior, not live execution or profit.
Live client startup and game behavior remain unverified.

## Recommended next experiment

1. Predeclare a budget/horizon-specific selection rule for liquid, affordable items with
   adequate post-tax spreads, using only data available before each decision. Compare it
   with the current cohort on another agreed chronological window. Historical evaluation
   does not require waiting for future data; avoid tuning and claiming validation on this
   already-inspected period.
2. Join opted-in manual-offer observations to public context locally. Preserve observation
   gaps, unknown placement times and cancellation censoring. Measure partial fills, time
   to exit, adverse price movement and net GP per slot-minute before fitting execution.
3. Keep the deterministic baseline. Require Chronos to improve execution-aware results
   under the same constraints and paired cases before adding complexity or fine-tuning.

None of these follow-up experiments or parameter changes has been started. Do not loosen
risk limits or increase assumed participation merely to make this report look profitable.
