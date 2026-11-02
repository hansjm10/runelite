# Expanded evaluation and forward collection

This stage adds a **frozen 50-item cohort**, an hourly sample, and an explicit
one-bucket forward collector. It does not turn on AI trading recommendations.

## Important coverage limit

A live `lookback=30d` probe on 2026-11-02 returned **120 six-hour observations**
(`timestep=21600`), not 720 hourly observations. We therefore retain the seven-day
hourly route rather than relabel coarse data or silently interpolate it.

The full 30-day hourly evaluation remains pending a suitable archive or an agreed
bulk-access route. No 720-request historical crawl is launched by these tools.
Forward collection can accumulate real hourly snapshots without that backfill.

## Reproduce the bounded expanded experiment

From the repository root, using the existing environment:

```sh
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/expanded.py collect --count 50
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/benchmark.py --offline --dataset tools/ge-data/output/expanded/dataset --output tools/ge-data/output/expanded/benchmark
```

The default collection makes at most **55 new requests**: one reference time-series,
four historical all-item hourly buckets, and 50 item time-series. Requests are spaced
by at least two seconds, cached, and not automatically retried. The first failed
request stops collection, including HTTP 403/429. A failed run can be resumed with
the same command: the cohort and successful responses are reused, not reselected.
`--offline` requires all requested responses to exist in the cache.

The collector does not overwrite an existing dataset. Use a new `--root` only for
an intentionally new experiment, not to repeatedly choose a more favourable cohort.

### Cohort selection before evaluation

The cohort is written to `output/expanded/cohort.json` before downloading the selected
items' full histories. Selection uses four hourly buckets at offsets 0, 6, 12 and 18
from the reference week's start; all precede the default final-48-hour holdout.

- An item must appear with both prices and volumes in at least three snapshots,
  with at least 20 units total across the sampled hours.
- Four historical price bands: below 1,000 GP; 1,000–99,999 GP; 100,000–9,999,999 GP;
  and at least 10 million GP.
- Within each price band, split candidates into three liquidity tiers using the
  sampled volume. This is not a complete daily volume estimate.
- Use deterministic hash ordering and round-robin selection across those strata.
- Exclude the three previously examined smoke-test items (4151, 561, 20997).
- No test-period performance, current price rankings, or future volume is used to
  pick the cohort. Retrospective source revisions remain an acknowledged limitation.

Requests may straddle an hour boundary. The exported dataset uses the common time
window across all item responses; it does not shift observations. Missing rows are
explicit, zero volumes remain zero, and null prices remain null. The manifest records
per-item coverage, original response bounds, source URLs/hashes, and cohort rules.

The benchmark verifies the cohort hash, selected IDs, and selection cutoff before
model inference. Model revision, context cap, publication gap and quantiles remain
unchanged from the first experiment. The test adds item breadth, **not a genuinely
new future-period holdout**. Do not treat these two experiments as independent proof
of an edge.

### Metrics

The existing paired-mask price errors and interval coverage are retained. Additional
per-series metrics in `metrics.json`:

- `change_mae_bps`: error in predicted price change relative to the last available
  context price, in basis points (100 basis points = 1%).
- `direction_accuracy_pct`: agreement of positive/zero/negative price changes;
  zero is its own outcome, so a persistence forecast only gets unchanged prices right.
- Calendar-week macro WAPE, with the number of observed test hours. Partial weeks
  are explicitly labelled and are not independent full-week tests.

A longer offline hourly dataset can use `--holdout-hours 336` for a predeclared
14-day holdout. The default remains 48 hours; the cohort selection must precede
whichever test window is chosen. Do not tune the window against its results.

## Capture fresh hourly snapshots

Once the cohort is frozen:

```sh
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/expanded.py capture
```

Each invocation requests **one** all-item hourly bucket and records the cohort's
observations. At time `T`, it uses the bucket starting at `floor_hour(T)-2h`, allowing
one hour after that bucket closes for publication. Repeating within the same hour
reuses the existing capture without another request or overwrite.

Files are written beneath `output/expanded/forward/<cohort-hash>/<epoch>.json` and
include interval bounds, original retrieval time, source hash, and nulls for absent
items. Raw API responses also remain cached. Existing captures are immutable; there
is no silent backfill, revision replacement, or forward-filling.

**No scheduled task or persistent background process is installed.** Run this command
hourly yourself, or configure your preferred scheduler. Missed invocations leave
unknown intervals. Retrospectively fetching those intervals would not recover their
original publication times. These raw forward captures are not yet automatically
merged into the frozen historical dataset or scored as new forecasts.

## Local manual-offer evidence

See [OFFER_RECORDER.md](OFFER_RECORDER.md) for the independent opt-in RuneLite recorder.
It records observations of your manual offers, not AI-generated orders. Offer logs
and public market snapshots serve different purposes and should not be merged until
observation gaps, account/session boundaries, and censored outcomes are handled.

Before enabling recommendations, require evidence on a new time period, realistic
execution assumptions, calibrated uncertainty, and a genuinely forward shadow test.
No result here establishes realised GP profit.
