# 30-minute GE research planner

A historical decision benchmark and manual RuneLite sidebar for **10m GP and six
available GE slots**. This is an experimental planning tool, **not a validated
profitable trader**. It does not place/cancel offers, generate game inputs, log in,
upload observations, or start a scheduler. No model training occurs.

Read [SESSION30_FINDINGS.md](SESSION30_FINDINGS.md) before using the output. The
first comparison found little capital deployment and no demonstrated trading edge.

## Components

- `session30.py`: bounded five-minute collection, historical comparison, snapshot export.
- `session_engine.py`: deterministic allocation, hypothetical partial fills and accounting.
- `chronos_backend.py`: pinned, local Chronos-2 inference; the hourly interface is retained.
- `runelite-client/src/main/java/net/runelite/client/plugins/geflipplanner/`:
  disabled-by-default **GE Flip Planner** sidebar. Reads a local JSON file only when
  you press **Refresh**. The model does not run inside RuneLite.
- [GE Offer Recorder](OFFER_RECORDER.md): separate, opt-in local observations of manual
  offers. These observations are not yet joined to the benchmark or used to fit fills.

## Collect and compare

Run from the repository root, using the existing isolated ML environment and cached
weights described in [README.md](README.md). Collection itself needs only standard
Python libraries. Choose a new root for each intentional fresh capture:

```sh
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/session30.py collect --root tools/ge-data/output/session30-new
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/session30.py benchmark --root tools/ge-data/output/session30-new
```

The default cohort is `output/expanded/cohort.json`, the previously frozen 50-item
research cohort. It is not a specially selected fast-flipping universe.

Collection makes at most **52 public API requests**: mapping, 50 item histories via
`lookback=24h`, and one latest-price snapshot. Requests are spaced by at least two
seconds, without automatic retries. Errors stop collection; there is no bulk crawl.
Actual returned resolution must be 300 seconds. The shared window must support the
fixed replay and context. Coarse data is rejected, never interpolated or relabelled.

Caches retain original retrieval times and response provenance. Reusing a cache does
not refresh it. `collect --offline` permits cached responses only. Existing dataset,
result and plan outputs are not overwritten. The model is always loaded **offline**;
missing weights are an error rather than an implicit download.

Outputs beneath the selected root:

- `cache/`: original response envelopes.
- `dataset/data.json`, `dataset/manifest.json`: common timestamp grid, explicit missing
  buckets, nullable prices/volumes, real zero volumes, source metadata and checksum.
- `results/forecasts.json`: item/origin forecasts and context cutoffs.
- `results/sessions.json`: hypothetical orders/fills, cash, inventory and resource usage.
- `results/metrics.json`, `results/report.md`: settings, model provenance and comparisons.
- `results/historical-plan.json`: initial Chronos allocation from the first session,
  explicitly historical and non-actionable. An empty candidate list is valid.

Nothing is copied into RuneLite automatically. Output and environment directories are
ignored by Git. No private offer observations are needed for this historical replay.

## Fixed policy and replay assumptions

Each of 24 non-overlapping half-hour sessions in the final 12 hours starts independently
with 10m cash, empty inventory, six free slots and assumed unused buy limits. These
resets are counterfactual: **do not sum session results into daily earnings**.

| Constraint | Rule |
| --- | --- |
| Cash reserve | 2m GP |
| Per-item allocation cap | 2m GP |
| Initial buy slots | At most four; two reserved for exits |
| Quantity cap | At most 1% of two buckets' activity, estimated from the preceding six five-minute buckets; also constrained by cash and assumed limits |
| Buy timeout | Cancel the unfilled remainder after 10 minutes |
| Late-session behavior | Cancel remaining buys and stop new buys from minute 20; remaining sell offers reprice toward a past instant-sell average |
| Sales tax | Assumed current 2%, rounded down per item, capped at 5m GP per item, with explicit exemptions |
| Residual inventory | Not sold automatically; hypothetical mark uses a past instant-sell average, 3% haircut and tax; absent prices remain unknown |

Tax assumptions are recorded in code with the
[Wiki reference](https://oldschool.runescape.wiki/w/Grand_Exchange#Convenience_fee_and_item_sink).
This is not a historical tax calendar. The replay accepts only the post-2026-09-30
API source regime. Current mapping limits and name-inferred variant families are not
proof of historical limits, complete shared groups, or your account's remaining limit.

Two policies share the same session starts and market inputs:

1. **`liquidity_margin`**: rank eligible quantities by quoted after-tax margin. Historical
   instant-sell/instant-buy averages are hypothetical bid/ask anchors, not executable quotes.
2. **`chronos_guard`**: apply the same rules, but cap the sale target at the minimum predicted
   10th-percentile instant-buy average over the remaining horizon. Reject nonpositive margins.
   This is a price-risk filter, not a calibrated confidence level or fill-time prediction.

Historical decisions use at most 120 five-minute context rows. The immediately preceding
bucket is withheld for an assumed five-minute publication delay. Seven steps are forecast;
the first is the withheld gap, not a tradable target. Price targets are joint, volume is
past-only, and `cross_learning=False` isolates item/origin tasks. Later observations cannot
enter earlier decisions. Historical revisions and actual publication latency remain unknown.

Five fill hypotheses are evaluated without changing the strategy:

| Scenario | Buy participation | Sell participation |
| --- | ---: | ---: |
| `no_fills` | 0% | 0% |
| `buy_only_stress` | 1% | 0% |
| `thin_0.1pct` | 0.1% | 0.1% |
| `reference_1pct` | 1% | 1% |
| `optimistic_5pct` | 5% | 5% |

These are **uncalibrated participation shares, not probabilities**. A qualifying bucket's
average price and volume permit an assumed partial fill at the offer price, recorded at
bucket end. Newly purchased units cannot sell in that same bucket. Buy reservations,
sell slots, spent shared-limit quantities and unsold inventory are tracked separately.
The replay does not reproduce queues, intrabucket price paths, manual reaction time or
actual cancellation latency. The 1% scenario is not an expected or proven typical outcome.

Marked-equity comparisons use a common priced-session mask across both policies within
each scenario. Reports expose its denominator and each policy's unpriced sessions.
Cash, realized gains, inventory cost and a zero-inventory-value cash floor are reported
for every session. A flat/no-trade session is not evidence of a successful flip.

## Inspect a historical plan in the sidebar

The source-built client contains **GE Flip Planner**, disabled by default. This is not
a Plugin Hub installation. Built artifact:

`runelite-client/build/libs/client-1.13.6-SNAPSHOT-shaded.jar`

The completed experiment's authoritative summaries and historical preview are in
`tools/ge-data/output/session30/results-paired/`; see the findings for the summary correction.
To inspect that preview, run these commands yourself in PowerShell:

```powershell
New-Item -ItemType Directory -Force "$HOME\.runelite\ge-flip-planner" | Out-Null
Copy-Item "tools/ge-data/output/session30/results-paired/historical-plan.json" "$HOME\.runelite\ge-flip-planner\plan.json"
```

This replaces the local plan file if one already exists. Enable **GE Flip Planner** in
the source-built client, open its sidebar and press **Refresh**. The default location is
`~/.runelite/ge-flip-planner/plan.json`. The initial preview has no candidates and an as-of
time of `2026-11-02T09:25:00Z`; it must not be presented as current advice.

Historical mode is visibly non-actionable. Snapshot mode displays expiry and clears
candidate cards when stale. Missing, invalid or oversized files clear previous cards
rather than leaving old recommendations visible. Parsing is bounded to 256 KiB on a
background worker, strings render literally, and shutdown cancels outstanding work.
The panel has no trading controls, network client or automatic file polling.

## Produce a fresh experimental snapshot

Use a **new root**, collect once, then export promptly. Do not first run a lengthy
benchmark or change timestamps to make old data appear fresh:

```sh
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/session30.py collect --root tools/ge-data/output/session30-fresh
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/session30.py snapshot --root tools/ge-data/output/session30-fresh
```

The default policy is `chronos_guard`; `--policy liquidity_margin` selects the baseline.
`--plan-output PATH` chooses a new output file. No model is loaded when the baseline has
no eligible candidates. This command makes no network requests: it uses the just-collected
history and latest snapshot.

History must be less than 15 minutes old, the latest response no more than five minutes
old, and each candidate's latest buy-side and sell-side trades no more than five minutes
old. Expiry is the earlier of five minutes after generation or 15 minutes after the
history's as-of time. Expiry is rechecked after inference. Freshness failures stop export;
a valid but empty plan means no eligible trade, not a reason to relax the filters.

Copy `session30-fresh/snapshot-plan.json` to the same sidebar location manually and press
**Refresh**. Verify actual cash, free slots, tax and remaining personal/shared buy limits
before considering any offer. Every exported plan declares `accountLimitsVerified:false`.
It is an initial allocation only: the panel neither observes your inventory nor replans
around existing offers. Refreshing the panel merely rereads the file; it does not refresh
market data or extend expiry.

## Verification and limits

Completed: 82 Python tests, scoped Pyright, 45 planner and 13 recorder Java tests,
client Checkstyle and the shaded JAR build. Shared producer fixtures are checked by both
Python and Java. Both plugin classes were verified inside the built JAR.

Not completed: live client/UI startup, actual game behavior, a fresh real-market snapshot
export, calibrated execution probabilities, joined recorder/market training data, verified
personal-limit tracking, or demonstrated trading profitability. No game was launched,
offers placed, scheduler installed or weights changed during this milestone.
