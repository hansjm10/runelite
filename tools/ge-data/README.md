# GE historical data coverage audit

Small research tools, separate from the RuneLite client. The audit samples public
historical APIs; the pilot exports cached hourly observations into a dataset with
explicit missing-data tracking. These data tools require Python 3.10+ and no third-party
packages. An optional Chronos-2 benchmark uses an isolated Python 3.12 ML environment.
There is no game interaction, fine-tuning, or bulk backfill.

Start with [SETUP.md](SETUP.md) on a new machine and [HANDOFF.md](HANDOFF.md) for the
current checkpoint, known blockers, and local artifacts that are intentionally not in Git.

## Run

From the repository root:

```sh
python tools/ge-data/audit.py
python -m unittest discover -s tools/ge-data -p 'test_*.py' -v
```

The default audit makes at most **19 requests**:

- Full retained guide-price history for Abyssal whip (4151), nature rune (561), and
  twisted bow (20997).
- Seven-day and one-year real-time series for each of those items. The report uses
  the **actual interval returned by the API**, not an assumed resolution.
- Five-minute and hourly all-item buckets at five sparse dates: yesterday UTC,
  2025-01-01, 2023-01-01, 2021-04-01, and 2021-02-01.

There are at least two seconds between network requests, a 30-second timeout,
no automatic retries, and a 40-probe limit. HTTP 403 or 429 stops the audit and
writes a partial report. HTTP 404 is recorded as an unavailable probe, not proof of
an exact retention boundary. Other network/schema errors and timestamp mismatches
produce a nonzero exit status. Empty or unavailable historical probes do not.

A descriptive User-Agent is supplied. Optionally identify your application/contact:

```sh
python tools/ge-data/audit.py --user-agent 'my-ge-research/0.1 (my public contact)'
```

## Output and replay

The default `tools/ge-data/output/` directory is git-ignored:

- `cache/`: JSON response envelopes keyed by URL, including original retrieval times.
- `report.json`: source URLs, response statuses, coverage, missing fields, gaps,
  duplicated timestamps, and sampled item values within historical market buckets.
- `report.md`: concise coverage table and interpretation limits.

Successful JSON responses are cached. Rerunning the same URLs uses that cache;
this is deliberate for reproducibility, including the otherwise-changing `/all`
and `/timeseries` responses. **Use a new output directory for a fresh observation.**
Failed HTTP requests are not cached, but remain in the report from that run.

Example fixed-date replay of the initial audit (requires its existing local cache):

```sh
python tools/ge-data/audit.py --offline --dates 2026-11-01 2025-01-01 2023-01-01 2021-04-01 2021-02-01
```

Offline mode never makes network requests. An uncached URL is reported as an error.
To preserve a prior report, copy it before replaying or use a separate output directory.

Custom small audit:

```sh
python tools/ge-data/audit.py --items 4151 561 --dates 2021-04-01 2025-01-01 --output tools/ge-data/output/fresh-audit
```

## Data contracts and limits

- [Historical guide-price API](https://runescape.wiki/w/RuneScape%3AGrand_Exchange_Market_Watch/Usage_and_APIs):
  `https://api.weirdgloop.org/exchange/history/osrs/all?id=4151`.
  Live responses use objects with millisecond timestamps; the parser also supports
  the legacy arrays described in the documentation. Volume may be absent in early
  history, and GE update periods are not necessarily exactly 24 hours.
- [Real-time API and acceptable use](https://oldschool.runescape.wiki/w/RuneScape%3AReal-time_Prices):
  `https://prices.runescape.wiki/api/v2/osrs`.
  Time-series intervals can change. Timestamped market buckets are checked against
  the requested timestamp to catch silently substituted recent data.
- Guide prices and transaction-side averages are **different series**. Never splice
  them into one price history. High/low indicate instant-buy/instant-sell sides,
  not the maximum/minimum trades in a period or guaranteed executable quotes.
- Sparse historical successes do not prove continuous, complete retention. Missing
  rows are not zero volume. Prices/volumes cannot establish order queue position,
  cancellation outcomes, or time-to-fill.
- Aggregated buckets are available only after their interval ends, plus publication
  delay. Future training features must respect availability time, historical tax
  and buy-limit rules, and chronological train/test splits.
- The Wiki documents a transition from RuneLite-only data to Jagex/all-client data
  on **2026-09-30**. Keep the source regime as metadata; do not interpret a coverage
  change as a demand shock.

## Try the hourly data pilot

After the audit has cached the seven-day item series:

```sh
python tools/ge-data/pilot.py
```

This is **offline only**: it reuses the cache, never fetches missing items, and
leaves the original responses and audit reports unchanged. Defaults are the same
three items as the audit. It writes to `tools/ge-data/output/pilot/`:

- `hourly.csv`: one row per item/hour within each response's reported window,
  with UTC interval start/end, the four original price/volume values, presence flag,
  data source/regime, and original retrieval time.
- `manifest.json`: coverage, explicit missing-hour lists, null counts among observed
  records, source URLs, retrieval times, normalized-payload hashes, and CSV SHA-256.
- `report.md`: readable results and interpretation limits.

Blank CSV cells represent nulls. `record_present=0` identifies a missing observation;
its values remain blank, not zero. Real zero volumes stay zero. There is no
forward-filling or imputation. The exporter rejects non-hourly data, duplicate or
off-grid observations, invalid prices/volumes, and intervals not yet closed at
retrieval. Windows are bounded to seven days per item and 20 selected items.

Existing output directories are never overwritten. To reproduce the dataset in a
new directory, or select already-cached items:

```sh
python tools/ge-data/pilot.py --output tools/ge-data/output/pilot-replay
python tools/ge-data/pilot.py --items 4151 561 --output tools/ge-data/output/two-items
```

Missing/corrupt inputs or an existing output directory cause a nonzero exit. All
inputs are validated before export starts. If writing fails, a partial output
directory may remain; do not treat it as a successful dataset.

The initial run produced **504 hourly rows** (168 per item) for 2026-10-26 20:00
through 2026-11-02 20:00 UTC, end exclusive. There were no missing buckets and one
null sell-side price for twisted bow: **503 rows have both price sides**. This
validates the pipeline, not prediction accuracy or a profitable trading strategy.

## Run the Chronos-2 experiment

This optional experiment uses [Amazon Chronos-2](https://huggingface.co/amazon/chronos-2)
(120M parameters, Apache-2.0) for **zero-shot local CPU inference**, not training from
scratch. Weights are pinned to revision
`29ec3766d36d6f73f0696f85560a422f50e8498c`. No RuneLite/Gradle dependencies change.

Fresh Windows setup (Python 3.12; commands work in PowerShell or Git Bash):

```sh
python -m venv tools/ge-data/.venv
tools/ge-data/.venv/Scripts/python.exe -m pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
tools/ge-data/.venv/Scripts/python.exe -m pip install -r tools/ge-data/requirements-forecast-lock.txt
tools/ge-data/.venv/Scripts/python.exe -m pip check
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/benchmark.py
```

`requirements-forecast.txt` records the direct dependencies; the lock records the
resolved Windows/Python 3.12 environment, including CPU PyTorch. Do not use the
platform-specific lock as a generic CUDA or Linux installation recipe. The local
`.venv/` and all runtime outputs/caches are git-ignored.

The first benchmark run downloads roughly 478 MB of safetensors weights plus a
configuration file from Hugging Face into `output/models/`. No remote model code is
trusted and no market data is uploaded. Telemetry is disabled for the model loader.
Windows may warn that symlinks are unavailable; ordinary cached copies work without
administrator privileges. Several GB of disk space should be reserved for the
complete environment and caches.

After the weights are cached, replay offline to a new output directory:

```sh
tools/ge-data/.venv/Scripts/python.exe tools/ge-data/benchmark.py --offline --output tools/ge-data/output/benchmark-replay
tools/ge-data/.venv/Scripts/python.exe -m unittest discover -s tools/ge-data -p 'test_*.py' -v
```

Existing result directories are never overwritten. The benchmark checks the pilot
CSV checksum, hourly alignment, explicit gaps, common item windows, and minimum
context length before loading the model. Base-Python tests still work, but skip the
adapter tests that require NumPy/PyTorch. Unit tests never download model weights.

### Fixed evaluation protocol

- Target: next-hour instant-buy and instant-sell **average prices**, not trade profit.
- Hold out the final **48 hours**, with walk-forward forecasts and no fine-tuning.
- At target hour `T`, inputs end at `T-1h` (exclusive); the bucket starting at `T-1h`
  is withheld to allow one hour of publication delay. The model predicts two steps
  after its last context bucket; only the second is scored against the hour at `T`.
  This delay is an assumption, not measured historical availability.
- Use at most **120 prior hours**. Previous holdout observations can enter later
  contexts only when the publication-gap condition is satisfied.
- The two prices are joint targets. Historical buy/sell volumes are **past-only**
  covariates. Missing inputs stay NaN; future prices/volumes are never supplied.
- Each item/origin is a separate task. `cross_learning=False` prevents attention
  across forecast origins (or items); batching cannot expose later-origin history
  to earlier predictions. Cross-item learning is not part of this experiment.
- Compare against last-observed-price persistence and the price at the same UTC
  hour the previous day. Use an identical valid-observation mask for all models;
  missing actuals or baseline references are explicitly listed as skipped.
- Report MAE/RMSE in GP and WAPE per item/price side, with **macro WAPE** giving each
  series equal weight. Also report Chronos 10th/50th/90th quantile loss, nominal 80%
  interval coverage, and interval width. Never pool raw GP error across differently
  priced items as the headline metric.

Outputs under `output/benchmark/`:

- `forecasts.csv`: every paired forecast, outcome, and context cutoff.
- `metrics.json`: protocol, per-series metrics, exclusions, full dataset manifest,
  dependency versions, model revision, device, seed, and inference timing.
- `report.md`: readable comparison and limitations.

This small holdout is a smoke test. Do not repeatedly tune against it or interpret
better price error as profitable flips. Tax, spreads, partial fills, queue position,
and capital/slot constraints are not simulated. The fixed pretraining dataset's
relationship to OSRS data has not been independently audited.

## Expanded cohort and local offer recorder

The next stage is available in [EXPANDED_RESEARCH.md](EXPANDED_RESEARCH.md): a frozen
50-item hourly cohort, paired evaluation, and a one-bucket forward collector. The
30-day API route was verified to return six-hour data, so this stage deliberately
does not claim a 30-day hourly backtest.

The opt-in [GE Offer Recorder](OFFER_RECORDER.md) is a separate built-in plugin in
this source checkout. It records local observations of manual offers, with explicit
gaps and bounded asynchronous JSONL storage. It neither uploads data nor trades.
It is disabled by default and still needs user-run live verification.

## Price-only versus price-plus-volume

[VOLUME_ABLATION.md](VOLUME_ABLATION.md) supports an immediate retrospective
comparison on the existing cohort with `ablation.py retrospective`, using unchanged
local weights. Results are explicitly exploratory and stored separately from the
original benchmark. The frozen future-period test remains a separate optional
experiment; its date gates do not block historical backtesting. No scheduler or
retraining is introduced. [VOLUME_FINDINGS.md](VOLUME_FINDINGS.md) records the
completed retrospective comparison and its mixed primary/secondary results.

## 30-minute planner: 10m GP and six slots

[SESSION30.md](SESSION30.md) covers bounded five-minute collection, a 30-minute historical
strategy comparison, and the disabled-by-default **GE Flip Planner** sidebar. The replay
tracks cash reservations, partial fills, sell slots, tax and unsold inventory under five
explicit fill hypotheses. Python exports a local JSON plan; the sidebar reads it only on
manual refresh and never trades. Historical plans are non-actionable; snapshot plans expire.

[SESSION30_FINDINGS.md](SESSION30_FINDINGS.md) records the completed comparison. The generic
cohort barely deploys the bankroll, and no trading edge is established. Simulated fills
are assumptions, not observed executions or calibrated probabilities.

## Budget-specific selection

[BUDGET_SELECTION.md](BUDGET_SELECTION.md) documents the frozen, past-only budget screen
and same-period cohort comparison. The capture selected 20 items, but the new Chronos
benchmark stopped on crossed quantiles; no completed budget strategy result exists.
[HANDOFF.md](HANDOFF.md) records the diagnostic and the exact stopping point.

## Recommended next step

Separate baseline-only evaluation from the model-output blocker, then decide and test an
explicit quantile-crossing policy without silently dropping cases. Keep the frozen evidence
and identify changed policies separately. Measure manual execution before increasing assumed
participation or tuning weights. Historical testing does not require waiting for future data,
but do not optimise and claim validation on inspected periods. Keep guide prices separate,
avoid bulk crawls, and retain publication-delay and source-regime caveats.
