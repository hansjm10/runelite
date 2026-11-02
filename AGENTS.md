# Agent guidance

This RuneLite fork contains an experimental, local-only Grand Exchange research project.
Do not assume the prototype is profitable or production-ready.

## Start here

- [Fresh-system setup](tools/ge-data/SETUP.md)
- [Current checkpoint and known blockers](tools/ge-data/HANDOFF.md)
- [Research tools and experiment guides](tools/ge-data/README.md)
- Existing RuneLite conventions: [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md)

Read the relevant experiment guide before changing its behavior. `HANDOFF.md` describes
what actually completed, not just what the commands are intended to do.

## Scope and structure

The GE work is contained in:

- `tools/ge-data/`: Python collection, forecasting, simulation, tests and documentation.
- `runelite-client/src/main/java/net/runelite/client/plugins/geofferrecorder/`
- `runelite-client/src/main/java/net/runelite/client/plugins/geflipplanner/`
- Matching Java test packages and planner test resources.

Preserve RuneLite's existing architecture and style. Avoid unrelated client/API changes,
dependency upgrades, public protocol changes or generated-file churn. Python ML dependencies
belong in `tools/ge-data/.venv/`, not global Python or the Java build. Use the checked-in
Gradle wrapper. Prefer small changes with focused regression tests.

## Safety and data contracts

- No automated game inputs, offer placement/cancellation, account login or game launch
  without a separate explicit user request. The plugins are disabled by default.
- Market collection is deliberate and bounded. Do not install a scheduler, retry loop,
  bulk backfill or continuously running scraper as an implicit next step.
- Keep market datasets, model inference and private offer observations local. Do not upload
  raw data/logs to external services or commit them to make a checkout self-contained.
- Preserve original retrieval timestamps, source URLs/hashes, missing rows/nulls and true
  zero volumes. Never substitute guide prices, interpolate coarse data into fine data, or
  relabel current observations as historical observations.
- Retain the 2026-09-30 source-regime boundary and chronological publication-gap rules.
  Historical testing is allowed; do not impose a future-date wait when valid historical
  data is available.
- Transaction averages and volumes do not establish executable quotes, queues or fill
  probabilities. Simulated fills/GP and inventory marks must remain explicitly hypothetical.
- Recorder observations are not exact placement/fill timestamps. Cancellation is censoring;
  observation gaps are unknown. Do not infer away these distinctions.
- Mapping/name-inferred shared limits are not verified account limits. Plans must not claim
  otherwise. Historical plans are non-actionable; stale snapshot cards must clear.
- Never tune repeatedly against inspected results or present forecast accuracy as trading
  profitability. The 4–5% account-return goal is a target, not an assumption or guarantee.
- Preserve failed model outputs. Do not silently discard cases, weaken quantile checks or
  modify weights to make a benchmark pass. A changed postprocessing/decision policy needs
  explicit documentation, tests and a separately identified comparison.

## Verification

From the repository root, using the isolated environment when installed:

```sh
tools/ge-data/.venv/Scripts/python.exe -m unittest discover -s tools/ge-data -p 'test_*.py' -v
./gradlew :client:test --tests 'net.runelite.client.plugins.geflipplanner.*' --tests 'net.runelite.client.plugins.geofferrecorder.*' :client:checkstyleMain :client:checkstyleTest --console=plain
```

PowerShell uses `.\gradlew.bat`; Unix Python environments use `.venv/bin/python`.
See `SETUP.md` for prerequisites and optional ML setup. Unit tests do not need real market
captures or downloaded model weights. Base-Python runs skip optional backend tests.

Run relevant checks after code changes; do not repeatedly rebuild unchanged subsystems.
Use `:client:shadowJar` when packaging the client is needed. Live UI/game verification is
separate from unit tests/build success and must not be claimed unless actually performed.

## Handoff and version control

Update the handoff/setup documentation when workflow or known blockers change. Distinguish
completed work, failed validation and unimplemented follow-up work.

Commit/push only when requested. Stage scoped paths and inspect the staged diff. Never add
`client.log`, `tools/ge-data/output/`, `.venv/`, model weights, private offer logs, build outputs
or credentials. Preserve existing unrelated changes. Do not force-push or change remotes
without explicit authorization. Report push/network failures rather than claiming success.
