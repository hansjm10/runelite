# Budget-specific item selection

This adds a **past-only item screen** to the existing 10m GP / six-slot / 30-minute
experiment. It changes the candidate universe, not the model weights, per-item allocation
cap, reserve, tax assumptions or simulated participation shares. It is not a live-market
scanner or an automated trader.

## Checkpoint status

The first capture completed with 20 selected items. The Chronos comparison then stopped
on eight crossed quantile triplets across seven of 1,468 item/origin tasks. No completed
budget simulation comparison or historical plan was exported. A diagnostic replay preserved
raw forecasts locally without altering weights or validation. The baseline-only path is
follow-up work, not an implemented fallback. See [HANDOFF.md](HANDOFF.md) for details and
[SETUP.md](SETUP.md) to continue on another machine. Benchmark artifacts listed below are
produced only after successful validation.

## The 4–5% target

Interpreted as account growth per half-hour, 4–5% means **400,000–500,000 GP after tax**.
With the existing 2m reserve, one complete round trip deploying the remaining 8m would
need **5–6.25% net on deployed capital**. For taxable items at 2%, ignoring rounding and
caps, that corresponds to roughly 7.14–8.42% gross buy-to-sell markup. Partial deployment,
missed fills and unsold inventory make the account-level target harder to reach.

The target is a reporting yardstick, **not an assumed return, probability, screening
threshold or reason to loosen risk rules**. A target hit is counted only when a simulated
session finishes with no inventory and its cash increase reaches the threshold. Marked
inventory is not counted as a fully exited target success.

## Frozen screen

`budget_selection.py` implements `ge-budget-cohort-v1`:

1. Read exactly six consecutive all-item five-minute buckets ending five minutes before
   the first replay decision. The last bucket starts ten minutes before that decision,
   allowing its five-minute duration plus the assumed publication gap.
2. Require all six observations to contain both prices and positive volumes on both
   sides. Missing observations, nulls and real zero volumes are not filled in or equated.
3. Require a known mapping buy limit; exclude bonds. Group variants with the existing
   name-based family heuristic, using the smallest known limit across the full mapping.
   This is conservative bookkeeping, not authoritative personal/shared-limit tracking.
4. Set screening buy price to the ceiling of the **highest instant-sell average** and
   sell price to the floor of the **lowest instant-buy average** across those buckets.
   Require a positive spread after the existing per-item tax calculation. This asks
   whether a spread persisted, rather than selecting one anomalous wide bucket.
5. Cap quantity by 2m GP, the inferred group limit, and the unchanged 1% participation
   assumption for two five-minute buckets, estimated from the six observed buckets.
6. Rank by **after-tax quoted GP capacity** (margin times capped quantity), then capital
   capacity, then item ID. Select at most 50 items and one variant per inferred family.
   Do not pad with ineligible items if fewer qualify.

Quoted capacity is screening arithmetic, not expected profit, a fill probability or a
bound on actual future profit. It is deliberately different from ranking percentage
spread alone. The replay still uses its original decision rules and current-at-origin
historical inputs, not these frozen screening quotes as execution prices.

## Bounded historical workflow

From the repository root, using the existing isolated environment and cached weights:

```sh
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/budget30.py collect
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/budget30.py benchmark
```

Default output: `tools/ge-data/output/budget30/`.
Default control: `tools/ge-data/output/session30/`.

The control must have a completed generic-cohort dataset and benchmark. `--control-root`
selects another such control; `--root` selects an unused experiment directory. These are
not instructions to rerun the completed experiment or tune it against inspected outcomes.

Before requesting selection prices, collection writes `plan.json`: fixed rules, window,
control dataset/result hashes, simulator hash and account-return targets. It then makes
**six market-bucket requests and at most 50 selected-item history requests**. Mapping,
latest-price data and overlapping item histories are reused byte-for-byte from the control
cache, preserving their original retrieval times. Only matching cache entries are copied.
The cached latest prices are not used to select items or replay trades.

There is no scheduler, retry loop, bulk crawl or API fallback. Requests use the existing
two-second spacing and timeout rules. Failure stops the run. `--offline` allows only
cached collection; model inference is always offline. An incomplete run can reuse its
frozen plan and cached responses, but it cannot silently reselect or replace its control.
Completed datasets and result directories cannot be overwritten.

New histories must retain enough context for the **same fixed 24 historical sessions**.
Data after the control's end is discarded, never shifted into the test period. Missing
rows remain explicit. If the rolling 24-hour API no longer covers the required window,
collection fails instead of relabelling recent data or substituting coarse observations.
No waiting for a future date is imposed; availability of genuine historical data is the
constraint.

## Comparison and artifacts

- `plan.json`: rules and input bindings, written before new market requests.
- `cohort.json`: selected items, capacity estimates, rejection counts and source hashes.
- `selection-report.md`: transparent selection diagnostics and an initial quote-based
  allocation under the unchanged four-buy-slot/eight-million-deployable-GP constraints.
- `cache/`, `dataset/`: response envelopes and checksum-bound five-minute data.
- `results/`: the existing two-policy/five-scenario benchmark for the selected cohort,
  including forecasts, individual session events and an explicitly historical sidebar plan.
- `comparison/metrics.json`, `comparison/report.md`: generic versus budget cohort results.

Before new inference, the original control sessions are reproduced using their saved
forecasts and the current simulator. Any difference stops comparison. No control forecasts
are regenerated. Both cohorts use the same timestamps and five fill scenarios; aggregate
marked equity uses one common priced-session mask across **all four cohort/policy arms**
per scenario. Each arm's unpriced counts, inventory cost and all-session cash floors remain
in JSON. Flat-session counts include no-trade sessions and are not fill-success rates.

The original period was already inspected. This is an **exploratory same-period cohort
comparison**, not a fresh holdout. The new screen uses only pre-test market buckets, but
retrospective revisions, imperfect historical mapping and unmeasured publication delay
remain limitations. A favorable result cannot by itself establish live profitability.

The existing sidebar JSON contract is unchanged. Nothing is installed in the RuneLite
profile, and historical output is not current trading advice. See [SESSION30.md](SESSION30.md)
for the manual sidebar workflow and execution-model limitations.
