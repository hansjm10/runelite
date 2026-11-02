"""Optional local Chronos-2 backend. Heavy imports are deferred until inference."""

from importlib import metadata
import os
from pathlib import Path
import platform

from benchmark import CONTEXT_HOURS, GAP_HOURS, QUANTILES, TARGETS


MODEL_ID = "amazon/chronos-2"
MODEL_REVISION = "29ec3766d36d6f73f0696f85560a422f50e8498c"
CPU_THREADS = 4
TASKS_PER_BATCH = 12  # Each task has two targets and two past-only covariates.


def model_input(case, numpy, include_volume=True):
    """No labels or future covariates; missing historical observations remain NaN."""
    def array(field):
        return numpy.array([row[field] if row[field] is not None else numpy.nan for row in case.context],
                           dtype=numpy.float32)
    task: dict = {"target": numpy.stack([array(field) for field in TARGETS])}
    if include_volume:
        task["past_covariates"] = {field: array(field) for field in ("high_price_volume", "low_price_volume")}
    return task


class ChronosForecaster:
    def __init__(self, cache, offline=False):
        cache = Path(cache).resolve()
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["DO_NOT_TRACK"] = "1"
        os.environ["HF_XET_CACHE"] = str(cache.parent / "xet-cache")
        import numpy
        import torch
        from chronos import Chronos2Pipeline
        from huggingface_hub import snapshot_download

        self.numpy = numpy
        self.torch = torch
        torch.set_num_threads(CPU_THREADS)
        torch.manual_seed(0)
        print(f"Loading {MODEL_ID}@{MODEL_REVISION} on CPU (offline={offline})", flush=True)
        # Load a pinned local snapshot so even adapter discovery cannot query an unpinned remote branch.
        snapshot = snapshot_download(
            MODEL_ID, revision=MODEL_REVISION, cache_dir=str(cache), local_files_only=offline,
            token=False, allow_patterns=["config.json", "*.safetensors", "*.safetensors.index.json"],
        )
        self.pipeline = Chronos2Pipeline.from_pretrained(
            snapshot, device_map="cpu", dtype=torch.float32, trust_remote_code=False,
            local_files_only=True, use_safetensors=True,
        )
        self.pipeline.model.eval()

    def predict(self, cases, include_volume=True):
        paths = self.predict_paths(cases, prediction_length=GAP_HOURS + 1, include_volume=include_volume)
        return [{field: values[field][GAP_HOURS] for field in TARGETS} for values in paths]

    def predict_paths(self, cases, prediction_length=7, context_length=CONTEXT_HOURS, include_volume=True):
        """Full quantile paths; steps are observations, not hard-coded wall-clock hours."""
        if not 1 <= prediction_length <= 32 or not 1 <= context_length <= 8192:
            raise ValueError("Unsupported bounded forecast/context length")
        output = []
        for start in range(0, len(cases), TASKS_PER_BATCH):
            chunk = cases[start:start + TASKS_PER_BATCH]
            tasks = [model_input(case, self.numpy, include_volume=include_volume) for case in chunk]
            with self.torch.inference_mode():
                quantiles, _ = self.pipeline.predict_quantiles(
                    tasks, prediction_length=prediction_length, quantile_levels=list(QUANTILES),
                    context_length=context_length, batch_size=TASKS_PER_BATCH * 4,
                    cross_learning=False,
                )
            if len(quantiles) != len(chunk):
                raise ValueError("Chronos returned the wrong number of tasks")
            for values in quantiles:
                if tuple(values.shape) != (len(TARGETS), prediction_length, len(QUANTILES)):
                    raise ValueError(f"Unexpected quantile output shape: {values.shape}")
                output.append({field: values[index, :, :].tolist() for index, field in enumerate(TARGETS)})
            print(f"Forecasted {len(output)}/{len(cases)} item/origin tasks", flush=True)
        return output

    def provenance(self):
        return {
            "id": MODEL_ID, "revision": MODEL_REVISION, "device": "cpu", "dtype": "float32",
            "cpu_threads": CPU_THREADS, "tasks_per_batch": TASKS_PER_BATCH,
            "seed": 0, "trust_remote_code": False, "weights_format": "safetensors",
            "python": platform.python_version(), "platform": platform.platform(),
            "packages": {dist.metadata["Name"]: dist.version for dist in metadata.distributions()},
        }
