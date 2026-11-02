# Development handoff — 2026-11-02

Branch: `feature/ge-budget-planner`.

This is a research checkpoint, **not a validated profitable trading system**. Plugins
are disabled by default. There are no automatic game inputs, offer actions, logins,
private-data uploads or scheduled collectors.

## Completed

- Historical API coverage tooling, hourly datasets, pinned local Chronos-2 inference,
  paired price benchmarks and the retrospective volume ablation.
- Opt-in local **GE Offer Recorder** and manual-file **GE Flip Planner** sidebar, including
  defensive parsing, expiry handling and shared Python/Java contract fixtures.
- Five-minute / 30-minute simulation for 10m GP and six slots: 2m reserve, 2m/item cap,
  partial fills, cash reservations, tax, buy timeouts, exit slots and unsold inventory.
- Budget-specific selection rules frozen before new selection requests. The completed
  capture selected **20 of 2,607 sampled items**, using six pre-test market buckets.
  It made 26 new public requests (six buckets plus 20 histories), reusing mapping/latest
  metadata from the original control cache. No parameters were tuned after selection.
- A zero buy limit in the full mapping is now treated as valid but ineligible. This
  parser correction resumed the same frozen capture; it did not change the selection rule.

See [README.md](README.md), [SESSION30.md](SESSION30.md),
[SESSION30_FINDINGS.md](SESSION30_FINDINGS.md) and [BUDGET_SELECTION.md](BUDGET_SELECTION.md).

## Exact stopping point / blocker

**The new budget-cohort strategy comparison did not finish.** Original control sessions
were successfully reproduced from saved forecasts without new control inference. New
Chronos inference returned 1,468 eligible item/origin paths, but strict quantile validation
stopped the benchmark before simulation results or a historical plan were exported.

A separate offline diagnostic replay reproduced **eight crossed quantile triplets across
seven item/origin tasks**. These were finite values with the predicted median above the
90th percentile, not NaNs or infinities. Raw forecasts were preserved locally. No weights
were changed, quantiles sorted/clamped, cases dropped or validation checks weakened.
The crossing is an output-validity issue; it does not establish damaged model weights.

Local-only evidence (ignored by Git):

- `output/budget30/plan.json`, `cohort.json`, `selection-report.md`
- `output/budget30/dataset/`, `cache/`
- `output/budget30/diagnostics/raw-forecasts.json`
- `output/budget30/diagnostics/invalid-quantiles.json`
- Control: `output/session30/dataset/`, `cache/`, `results-paired/`

There is **no completed `output/budget30/comparison/`**. A baseline-only comparison was
identified as a useful way to isolate selection from the model failure, but implementation
was paused for this handoff. Do not report the failed model run as a successful backtest.

The selection screen's first four buys allocated only 43,560 GP. Their combined quoted
after-tax capacity was 11,546 GP if every unit bought and sold at its screening prices;
that is arithmetic, not an observed or expected return. The user's 4–5% target is interpreted
as **400–500k GP per 30 minutes on the full 10m account**. Current evidence does not support
that target. Participation assumptions remain uncalibrated and most capital remains idle.

## Validation at this checkpoint

- **96 Python tests passed**, including 14 budget-selection/workflow tests.
- Scoped Pyright passed for `budget_selection.py`, `budget30.py`, `test_budget30.py` and
  the modified `session30.py`.
- Earlier in the same milestone: **45 planner + 13 recorder Java tests**, client main/test
  Checkstyle and `:client:shadowJar` passed. Java code was not changed by budget selection.
- Both plugins were confirmed in the built shaded JAR. Live client startup/UI and game
  behavior have not been tested. No fresh live snapshot plan was exported or installed.

Useful commands after environment setup:

```sh
tools/ge-data/.venv/Scripts/python.exe -m unittest discover -s tools/ge-data -p 'test_*.py' -v
./gradlew :client:test --tests 'net.runelite.client.plugins.geflipplanner.*' --tests 'net.runelite.client.plugins.geofferrecorder.*' :client:checkstyleMain :client:checkstyleTest :client:shadowJar --console=plain
```

The Java command was validated with `--offline` on this machine; a fresh checkout may
need Gradle to download its existing dependencies. Base-Python tests can run without the
ML environment, but adapter tests requiring NumPy/PyTorch will be skipped.

## Continuing at home

Follow [SETUP.md](SETUP.md) for verified prerequisites, isolated Python/model setup,
build/test commands and exact-artifact versus fresh-capture workflows. The root
[AGENTS.md](../../AGENTS.md) links the same guides for future coding sessions.

After the branch has been pushed:

```sh
git fetch origin
git switch --track origin/feature/ge-budget-planner
```

Git contains source, tests, synthetic contract fixtures and documentation only. It does
**not** contain `.venv/`, model weights, market response caches/datasets, runtime results,
private offer logs, `client.log` or the built JAR. Follow the README for isolated Python
setup and pinned model download; the recorded lock targets Windows/Python 3.12.

For exact reproduction of this historical experiment, privately copy the ignored control
and budget artifact directories listed above, and `output/expanded/cohort.json`. Model
weights may be copied separately from `output/models/` or downloaded at the pinned revision.
Do not upload these artifacts or offer logs just to make a fresh checkout convenient.
Plans bind input hashes and simulator file bytes; preserve original files and inspect any
line-ending/hash mismatch rather than silently rebasing a frozen experiment.

Without those local artifacts, a fresh checkout cannot reconstruct this exact rolling
24-hour capture later. The source and tests remain usable, but a new experiment needs a
newly declared historical window and its own control capture. Do not relabel current API
observations as the old data.

## First development steps

1. Separate the deterministic baseline comparison from the Chronos failure, without
   changing item selection, cash/slot limits or participation shares.
2. Decide and test an explicit quantile-crossing policy for a separately documented model
   variant. Preserve raw outputs, avoid selective case removal, and do not weaken tests
   merely to accept these forecasts. Reuse the saved diagnostics for investigation.
3. Evaluate allocation and observed manual fills before increasing assumed participation
   or fine-tuning weights. Any new experiment must retain clear retrospective labels;
   no future-date wait is required when genuine historical data is available.

Do not launch the game, place/cancel offers, install a scheduler or change model weights
as an implicit continuation of this checkpoint.
