# Chronos-2 experiment — 2026-11-02

## Outcome

The pinned model runs successfully on this machine's CPU. In this small, fixed
48-hour evaluation, Chronos-2 modestly outperformed last-observed-price persistence
on average, but not on every item/side. This warrants a larger independent test;
it does not establish a trading edge or statistical significance.

| Model | Macro WAPE (%) — lower is better |
| --- | ---: |
| Last-observed-price persistence | 0.576106 |
| Same UTC hour the previous day | 1.904788 |
| Chronos-2, zero-shot | 0.544206 |

The relative macro WAPE reduction against persistence was **5.54%**, not 5.54
percentage points. Chronos improved four of the six item/price-side series; whip
instant-buy and twisted-bow instant-sell averages were slightly worse. Macro WAPE
weights the six series equally rather than letting the twisted bow's GP price
dominate the headline metric.

Nominal 80% interval coverage ranged from **70.83% to 81.25%** across the six series.
Do not treat these as calibrated confidence guarantees. Each coverage estimate
uses only 48 temporally dependent observations.

## What ran

- Dataset: 504 hourly rows for nature rune, Abyssal whip, and twisted bow.
- Dataset SHA-256: `f1b2c29dface4bc01f0625a779862a1f921aa8c7499bb946c6cdbbc2dbcab93d`.
- Test interval: **2026-10-31 20:00 UTC through 2026-11-02 20:00 UTC**, end exclusive.
- 144 item/origin tasks, jointly predicting two price sides; **288 scored outcomes**
  per model, with no excluded outcomes in this holdout. Missing historical prices
  remained NaN rather than being forward-filled.
- At each origin, at most 120 context hours, with a one-hour publication-gap
  assumption. No future prices or volumes were supplied. Tasks did not share
  attention across items or origins.
- No fine-tuning, parameter search, order execution, fee simulation, or profit claims.
- Model: [`amazon/chronos-2`](https://huggingface.co/amazon/chronos-2), revision
  `29ec3766d36d6f73f0696f85560a422f50e8498c`, safetensors, local CPU float32, four threads.
- Chronos package 2.3.2; PyTorch 2.15.0+cpu; complete environment pins in
  `requirements-forecast-lock.txt`.
- Forecast generation took **4.92 seconds**, excluding package installation, model
  download and loading. This is one measured run, not a latency benchmark.
- The actual evaluation ran with `--offline` after the weights were downloaded.

## Verification and artifacts

- 40 tests passed in the isolated environment, including temporal isolation,
  missing-value handling, paired evaluation masks, and the backend's horizon/batch contract.
- Pyright passed for the new benchmark, backend, and tests.
- `pip check` passed; every runtime dependency lock entry matches the installation.
- Runtime artifacts are local and git-ignored: `output/benchmark/report.md`,
  `output/benchmark/metrics.json`, and `output/benchmark/forecasts.csv`.
- Full rerun/setup instructions are in [README.md](README.md).

## Next decision

Keep this model/configuration fixed and evaluate on a larger, newly held-out period
and a broader preselected item universe before tuning. Actual publication times,
historical revisions, fill probability, taxes, and capital/slot constraints remain
unresolved for trading evaluation. Do not infer profitability from this result.
