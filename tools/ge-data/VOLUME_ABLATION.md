# Price-only versus price-plus-volume comparison

## Retrospective comparison (completed)

Results and tradeoffs are recorded in [VOLUME_FINDINGS.md](VOLUME_FINDINGS.md).
The command below documents the completed run; its existing output directory is
protected against overwriting or repeated tuning.

Historical backtesting does **not** require waiting for a future date. The explicit
retrospective mode uses the existing 50-item dataset, including the already-inspected
final 48-hour period, without changing observation or retrieval timestamps:

```sh
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/ablation.py retrospective
```

Both variants run locally/offline from the same checkpoint. No market requests or
model downloads are made. Dataset/cohort checksums, chronological context cutoffs,
publication gap and the common scoring mask remain enforced. No settings are tuned.

Outputs go to the separate `output/volume-ablation-retrospective/results/` directory:
`forecasts.csv`, `metrics.json` and `report.md`. They are explicitly labelled
`retrospective_exploratory`, with actual creation times, original source provenance
and the historical test window. An existing output directory is never overwritten.
This command does not read or modify the frozen future-test plan or replace earlier
benchmark results. `--source-dataset` can select another validated cohort dataset;
`--root` must name a separate unused output directory.

Because this period was already inspected, the result is diagnostic evidence, not
fresh independent validation or proof of a profitable trading strategy. The future
holdout below remains a separate experiment, **not a prerequisite for backtesting**.

## Separate fresh holdout: prepared, awaiting new data

The experiment was frozen at **2026-11-02 20:59:08 UTC**, before the new test began.
The plan is `output/volume-ablation/plan.json`:

- **50 unchanged items**, from the existing frozen cohort; no reselection.
- Test: **2026-11-02 21:00 UTC through 2026-11-04 21:00 UTC**, end exclusive.
- Earliest collection: **2026-11-04 22:00 UTC**, allowing the final bucket to close
  plus the existing one-hour publication-delay assumption.
- The previously inspected dataset ends at 2026-11-02 20:00 UTC and cannot serve
  as this test's outcomes.

**No result for this fresh holdout exists yet.** Retrospective results use a different
period and do not satisfy this plan. No scheduler, unattended collector, or training job was installed.
Unit tests and a separate synthetic inference smoke test do not establish whether
volume improves market forecasts.

## What is held constant

Both variants use the same pinned Chronos-2 checkpoint, CPU float32 inference,
seed, two joint price targets, quantiles, context windows and forecast origins.
The original volume-enabled benchmark remains the default and is unchanged.

- `prices_only`: both historical price sides, with the volume covariates absent.
- `prices_and_volume`: the identical prices plus both historical volume series.

Removing volume means **omitting those covariates**, not replacing them with zero
or treating missing volumes as actual zero trading activity. No future covariates
are supplied. The weights are not trained, edited or fine-tuned.

At target hour T, context excludes the bucket starting at T-1h and all later
buckets. The model forecasts two steps and scores the second, with up to 120
context hours. Earlier holdout observations can enter later contexts only after
that gap. `cross_learning=False` isolates items and origins.

## Optional: run the separate fresh holdout when available

The fresh-holdout experiment is **already initialized**. After the collection time above:

```sh
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/ablation.py collect
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/ablation.py run
```

`collect` makes at most **50 new requests** (one seven-day hourly response per
frozen item), spaced by at least two seconds. It uses a separate cache, preserves
original retrieval times and payload hashes, and stops at the first unsuccessful
response, including 403/429. It does not backfill hourly endpoints or poll/retry.
An invocation before the declared time fails **before any request or model load**.

Collect promptly: the source's rolling seven-day window eventually loses required
context. Responses must cover the entire planned test and at least 49 pre-test
hours. Insufficient retention, stale snapshots or six-hour data fail rather than
shift the test window, change the cohort, interpolate prices, or shorten the test.
The dataset is clipped to the exact planned end; later observations are excluded.

A partial request run can resume using its cached responses. If a cached successful
response is stale or unusable, preserve it and explicitly select a new cache path:

```sh
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/ablation.py collect --cache tools/ge-data/output/volume-ablation/cache-retry
```

That is another manually invoked bounded collection, not an automatic retry. Never
change the test dates to get a more convenient or favourable sample.

`collect --offline` requires cached market responses. **Model inference is always
offline**, using the already-downloaded weights. `run` loads one checkpoint instance
for both variants, validates the dataset checksum/plan/cohort/window, and refuses to
overwrite existing results. No data is uploaded.

To initialize a genuinely later experiment deliberately, `ablation.py init --root
<new-directory>` freezes the next UTC hour and the subsequent 48 hours. Do not
reinitialize the current experiment, and do not tune against its eventual outcomes.

## Scoring and outputs

Primary comparison: **macro WAPE across item/price-side series**, giving each scored
series equal weight. The report shows both variants, persistence, and the previous-day
seasonal baseline. A positive `volume_wape_improvement_percentage_points` means
price-plus-volume has lower error than price-only; a negative value means it is worse.

All four methods use exactly the same complete-case observation mask. Missing actuals
or baseline references are reported as skipped. Invalid/crossed/non-finite quantiles
fail the comparison rather than silently removing hard cases. The mask can exclude
thinly traded periods, so it does not represent every possible trading opportunity.

Outputs in `output/volume-ablation/`:

- `plan.json`: predeclared settings, dates, cohort and prior-dataset hash.
- `cache/`: original market responses; nothing overwrites the earlier experiment's cache.
- `dataset/hourly.csv` and `manifest.json`: explicit gaps/nulls, original retrieval
  times, source regime, checksums, and binding to this plan.
- `results/forecasts.csv`: paired predictions and actuals for all four methods.
- `results/metrics.json`: per-variant/per-series errors, quantile loss, interval
  coverage/width, price-change metrics, exclusions, provenance and inference times.
- `results/report.md`: headline comparison and limitations.

Partial directories after write failures are not successful datasets/results;
preserve them for inspection before attempting recovery.

## Interpretation limits

The separate fresh-holdout experiment uses a **new predeclared calendar holdout**,
but its hourly histories will be retrieved retrospectively. Neither mode is a
prospective archive of forecasts committed
before each outcome. Historical revisions and actual publication delays remain
unknown. A truly point-in-time shadow test is a separate later step.

One 48-hour window cannot establish statistical significance or a reliable trading
edge. Calendar-week slices are partial weeks, not independent full-week replications.
Nominal 80% intervals are not guaranteed confidence. Execution, taxes, fill timing,
capital allocation and GP profit remain outside this experiment.

The earlier full checkpoint scan found no non-finite values and its SHA-256 matched
cached download metadata. This comparison investigates **predictive usefulness**,
not a detected corruption that needs repairing.
