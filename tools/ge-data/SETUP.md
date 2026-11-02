# Set up GE research development on a new system

Start with [HANDOFF.md](HANDOFF.md) for the current checkpoint. **Budget selection works,
but its first Chronos comparison is blocked by crossed forecast quantiles.** Installing
successfully will not resolve that model-output issue or establish a trading edge.

The tested path is **Windows, Temurin JDK 17 and Python 3.12.10 on CPU**. No GPU, paid
model API, game login or Hugging Face token is needed. This guide does not automatically
launch the game, enable plugins, place offers or start collectors.

## 1. Prerequisites and checkout

Install Git, a full **JDK 17** (not just a JRE), and Python **3.12** if working on the research
tools. Configure `JAVA_HOME`/`PATH` for that JDK. Gradle 8.8 is provided by the wrapper;
do not install or upgrade Gradle separately. Java compilation targets release 11 and
upstream CI uses JDK 11; JDK 17 is the environment verified for this checkpoint.

Check in PowerShell:

```powershell
git --version
java -version
javac -version
py -3.12 --version
```

After the feature branch has been pushed, clone it:

```powershell
git clone --config core.autocrlf=false --branch feature/ge-budget-planner https://github.com/hansjm10/runelite.git runelite
Set-Location runelite
```

The local clone setting preserves LF source bytes for frozen simulator hashes; it does
not change your global Git configuration. If using an existing checkout instead, fetch
and switch branches without overwriting local work:

```powershell
git fetch origin
git switch --track origin/feature/ge-budget-planner
```

If that local branch already exists, use `git switch feature/ge-budget-planner`. A failed
push on the original machine means the branch is not available remotely yet. Network/DNS
or repository-access errors must be resolved before fetching it; do not put credentials
in repository files or change to an unrelated remote.

All remaining commands run from the repository root.

## 2. Build and test the Java plugins

You can do Java/plugin development without installing any Python ML packages.

```powershell
.\gradlew.bat :client:test --tests 'net.runelite.client.plugins.geflipplanner.*' --tests 'net.runelite.client.plugins.geofferrecorder.*' :client:checkstyleMain :client:checkstyleTest :client:shadowJar --console=plain
```

Git Bash/Linux/macOS use `./gradlew` instead of `.\gradlew.bat`. The first build needs
network access for the wrapper and the project's existing dependencies, including RuneLite
artifacts. `--offline` is appropriate only after those dependencies have been cached.
Do not change project versions/dependencies to work around a missing artifact without
first understanding the failure.

At this checkpoint, the artifact is:

`runelite-client/build/libs/client-1.13.6-SNAPSHOT-shaded.jar`

It is a source-built client, not a Plugin Hub package or an automatic update to an installed
RuneLite launcher. **GE Offer Recorder** and **GE Flip Planner** remain disabled by default.
Build/test success does not verify live startup or game behavior. Manual verification, if
you choose to perform it, is documented in [OFFER_RECORDER.md](OFFER_RECORDER.md) and
[SESSION30.md](SESSION30.md); no game launch is needed for the tests above.

## 3. Create an isolated Python environment

Use an explicit Python 3.12 interpreter. Avoid activating the environment or changing
PowerShell execution policy; invoke its interpreter directly:

```powershell
py -3.12 -m venv tools/ge-data/.venv
$PY = Join-Path (Get-Location) 'tools/ge-data/.venv/Scripts/python.exe'
& $PY --version
& $PY -m unittest discover -s tools/ge-data -p 'test_*.py' -v
```

The standard-library tools/tests can run without ML packages. Optional NumPy/PyTorch backend
tests will be skipped at this point. Unit tests use synthetic fixtures/mocked responses;
they do not require real market data or download model weights.

If the `py` launcher is unavailable, substitute a verified Python 3.12 executable. Do not
copy `.venv/` from another machine; virtual environments are not portable installations.

## 4. Optional CPU forecasting dependencies

For Chronos inference and the complete backend test suite:

```powershell
& $PY -m pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
& $PY -m pip install -r tools/ge-data/requirements-forecast-lock.txt
& $PY -m pip check
& $PY -m unittest discover -s tools/ge-data -p 'test_*.py' -v
```

This installs only into `.venv/`. Do not install globally or add ML libraries to Gradle.
`requirements-forecast-lock.txt` records the tested **Windows/Python 3.12 CPU environment**;
it is not a universal lock. `requirements-forecast.txt` lists direct package pins.
If a pinned version is unavailable, stop and investigate rather than silently installing
newer packages and calling the experiment reproduced.

The latest checkpoint passed 96 Python tests with the optional backend dependencies
installed. Pyright is an optional development tool, not a runtime dependency; if available,
the scoped check used was:

```powershell
pyright --pythonpath tools/ge-data/.venv/Scripts/python.exe tools/ge-data/budget_selection.py tools/ge-data/budget30.py tools/ge-data/test_budget30.py tools/ge-data/session30.py
```

On Linux/macOS, create a local environment and use `.venv/bin/python`. The standard-library
scripts are portable, but this ML lock/platform combination has not been validated there.
Use a platform-compatible CPU PyTorch build and record any newly resolved environment
separately; do not overwrite the Windows lock or assume identical numerical results.

## 5. Download the pinned model separately from market collection

Model: `amazon/chronos-2`, revision
`29ec3766d36d6f73f0696f85560a422f50e8498c`.

This explicit command downloads/loads the pinned model without fetching market data:

```powershell
& $PY -c "import sys; from pathlib import Path; sys.path.insert(0, 'tools/ge-data'); from chronos_backend import ChronosForecaster; ChronosForecaster(Path('tools/ge-data/output/models'), offline=False)"
```

It uses local CPU float32 inference, safetensors and `trust_remote_code=False`; telemetry
is disabled by the loader. The weight file is roughly 478 MB. Allow several GB for the
complete environment and caches. On Windows, a Hugging Face symlink warning is not a reason
to elevate privileges or change system settings; ordinary cached copies work.

Verify the cached model can load without network access:

```powershell
& $PY -c "import sys; from pathlib import Path; sys.path.insert(0, 'tools/ge-data'); from chronos_backend import ChronosForecaster; ChronosForecaster(Path('tools/ge-data/output/models'), offline=True)"
```

The 30-minute and budget benchmark commands always load weights offline. They will not
silently download missing weights. Unit tests do not need this download.

## 6. Choose exact reproduction or a new historical experiment

### Continue the exact local experiment

The repository intentionally excludes raw market caches, datasets, inference outputs,
model weights, private offer logs and client logs. Git alone cannot reproduce the saved
24-hour capture after the public rolling window has moved on.

For exact continuation, privately transfer these directories from the original machine
without altering their contents:

- `tools/ge-data/output/session30/` — control cache, dataset and original/corrected results.
- `tools/ge-data/output/budget30/` — frozen plan, selected cohort, cache, dataset and diagnostics.
- `tools/ge-data/output/expanded/cohort.json` — original generic cohort manifest.
- Optionally `tools/ge-data/output/models/` — pinned model cache instead of downloading it.

No RuneLite account credentials or private offer logs are needed. Do not upload these
artifacts to Git, and do not transfer `.venv/`. Preserve source line endings as described
above: the budget plan binds simulator file bytes as well as dataset/result hashes.
A mismatch should be investigated, not bypassed by editing a saved plan.

Read the saved diagnostic files and [HANDOFF.md](HANDOFF.md) before retrying inference.
The budget comparison failed closed and has no completed result directory. The planned
baseline-only path and an explicit quantile-crossing policy are follow-up work, not already
implemented fixes. Do not re-collect and pretend a new capture is the old experiment.

### Start a separate, explicitly declared historical capture

This is optional and makes public API requests. It is **not** required to edit code or
run unit tests. Use unused directories and keep the resulting experiment separate:

```powershell
& $PY tools/ge-data/expanded.py collect --root tools/ge-data/output/expanded-home
& $PY tools/ge-data/session30.py collect --cohort tools/ge-data/output/expanded-home/cohort.json --root tools/ge-data/output/session30-home
& $PY tools/ge-data/session30.py benchmark --root tools/ge-data/output/session30-home
```

Only after that control benchmark succeeds:

```powershell
& $PY tools/ge-data/budget30.py collect --control-root tools/ge-data/output/session30-home --root tools/ge-data/output/budget30-home
& $PY tools/ge-data/budget30.py benchmark --control-root tools/ge-data/output/session30-home --root tools/ge-data/output/budget30-home
```

These are bounded, manually invoked collections, not a scheduler or bulk crawl. Defaults
permit up to 55 requests for the expanded cohort, 52 for the five-minute control, and six
selection buckets plus at most 50 selected histories for budget selection. Cached overlap
reduces new requests. Rate limits, incompatible resolutions or insufficient genuine history
stop the run. Do not automatically retry or replace missing historical data with current data.

Chronos quantile validation can still stop a new benchmark. Do not skip invalid cases or
relax checks just to obtain a report. Price forecasts, assumed fills and inventory marks
are not evidence of realized profits.

## 7. Manual sidebar handoff, when appropriate

Python and RuneLite communicate through a local JSON file, not a service. The default
sidebar path is `~/.runelite/ge-flip-planner/plan.json`; reading requires manual **Refresh**.
Nothing is copied there during setup. Historical plans remain non-actionable and snapshot
plans expire. The sidebar does not read your account's remaining buy limits or place orders.
Follow [SESSION30.md](SESSION30.md) rather than editing timestamps to make a stale plan fresh.

Before committing, inspect `git status` and the staged paths. Keep `.venv/`, `output/`,
weights, private observations, `client.log` and built artifacts out of Git. See the root
[AGENTS.md](../../AGENTS.md) for the project's coding-agent guardrails.
