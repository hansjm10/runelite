# Expanded experiment and recorder handoff — 2026-11-02

## What is working

- A frozen, pre-test-selected **50-item cohort**, excluding the three original
  smoke-test items. Selection was balanced across historical price/liquidity bands.
- **8,400 hourly rows** over seven days, with 13 explicit missing buckets and 7,712
  rows containing both price sides. Missing data was not filled with invented values.
- The unchanged Chronos-2 model evaluated locally/offline on the final 48 hours.
- One fresh all-item hourly API observation captured for the frozen cohort. The
  collector is one-shot; no scheduled task or unattended process was installed.
- An independent, opt-in, local-only RuneLite **GE Offer Recorder** plugin, packaged
  in a built client JAR. It records manual-offer observations, not recommendations.

## Forecast results

Macro WAPE gives each of the 100 item/price-side series equal weight:

| Model | Macro WAPE (%) |
| --- | ---: |
| Last-observed-price persistence | 4.353783 |
| Same UTC hour the previous day | 8.439220 |
| Chronos-2 | 3.914292 |

Chronos reduced macro error by **10.09% relative to persistence**, winning 66 of
100 series. It did not win universally. The broader cohort includes less liquid,
more variable items, so these error levels are not directly comparable to the
original three-item cohort's lower error levels.

Fixed pre-test liquidity strata (tiers are relative within each price band):

| Liquidity tier | Items | Persistence WAPE (%) | Chronos WAPE (%) |
| --- | ---: | ---: | ---: |
| Lower sampled activity | 17 | 5.3870 | 4.8319 |
| Middle sampled activity | 17 | 6.0354 | 5.3562 |
| Higher sampled activity | 16 | 1.4693 | 1.4072 |

There were **4,481 scored outcomes per model**. The common evaluation mask excluded
319 item/side/hour observations: 195 missing actuals and 124 missing previous-day
references. This means the metrics describe the scored subset, not every possible
trade opportunity.

Nominal 80% interval coverage averaged **77.89% across series**, but individual
series ranged from **50.00% to 97.62%**. The overall average hides substantial
calibration problems. Do not present these ranges as guaranteed confidence.

Test period: **2026-10-31 20:00 UTC through 2026-11-02 20:00 UTC**, end exclusive.
The calendar-week breakdown contains only 28 hours and 20 hours respectively;
it is not two independent full-week tests. Forecast inference took approximately
94 seconds, excluding installation/model loading. No model settings were tuned.

Dataset SHA-256:
`f24c8fd8bcd6ce93750549da54179a928b863720db18d2aeb5f3b6f1871f2597`

Cohort SHA-256:
`caf2f453bc90073e4b7ce28bad3067648b767242d90d563133bf1b75128e6fef`

## Verification

- **51 Python tests passed**; the changed Python collector/benchmark/tests passed Pyright.
- **13 focused Java tests passed** for recorder lifecycle, snapshots, deduplication,
  long values, observation gaps, supported worlds, file ordering, limits and failures.
- Client main/test Checkstyle reports contain zero violations.
- `./gradlew :client:shadowJar` succeeded. Recorder classes were verified inside
  `runelite-client/build/libs/client-1.13.6-SNAPSHOT-shaded.jar`.
- No live client was launched, no game input was automated, and no manual offer or
  login flow was tested. The plugin is disabled by default; user-run verification
  is still required before relying on its logs.

## What is still pending

A live 30-day API probe returned six-hour data, so **a 30-day hourly backtest was
not performed**. A suitable archive or agreed bulk-access route is still needed,
or hourly data must accumulate prospectively. No bulk historical crawl was run.

The expanded test uses new items but the same short calendar holdout. It is not a
new forward-period validation and establishes neither statistical significance nor
profitability. Offer logs are not yet joined to market data. Fill probabilities,
queue position, realistic execution, fees and bankroll/slot allocation remain
unvalidated. No trading recommendations or automated orders have been enabled.

Instructions: [expanded data workflow](EXPANDED_RESEARCH.md),
[local recorder](OFFER_RECORDER.md). Detailed local results are in
`output/expanded/benchmark/report.md`, `metrics.json`, and `forecasts.csv`.
