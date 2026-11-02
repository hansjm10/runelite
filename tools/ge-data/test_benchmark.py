import contextlib
import copy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audit
import benchmark as bench
import chronos_backend
import pilot


START = int(audit.date_argument("2026-10-01").timestamp())


def market(hours=168):
    return {4151: [{"timestamp": START + i * pilot.HOUR, "avg_high_price": 100.0 + i,
                    "avg_low_price": 90.0 + i, "high_price_volume": 1000.0 + i,
                    "low_price_volume": 500.0 + i} for i in range(hours)]}


def predictions(cases):
    return [{target: [200.0, 250.0, 300.0] for target in bench.TARGETS} for _ in cases]


def save_dataset(root, items):
    columns = ["item_id", "interval_start_utc", "interval_end_utc", "record_present", *pilot.VALUES]
    with (root / "hourly.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for item, rows in items.items():
            for row in rows:
                writer.writerow({"item_id": item, "interval_start_utc": audit.iso(row["timestamp"]),
                                 "interval_end_utc": audit.iso(row["timestamp"] + pilot.HOUR),
                                 "record_present": 1, **{field: row[field] for field in pilot.VALUES}})
    manifest = {"schema_version": 1, "interval_seconds": pilot.HOUR,
                "rows": sum(map(len, items.values())),
                "csv_sha256": hashlib.sha256((root / "hourly.csv").read_bytes()).hexdigest()}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class EvaluationTests(unittest.TestCase):
    def test_holdout_and_gap_are_chronological(self):
        inputs = bench.make_inputs(market())
        self.assertEqual(len(inputs), 48)
        self.assertEqual(inputs[0].target_start, START + 120 * pilot.HOUR)
        for case in inputs:
            self.assertLessEqual(len(case.context), 120)
            self.assertEqual(case.context[-1]["timestamp"], case.target_start - 2 * pilot.HOUR)

    def test_future_and_gap_prices_and_volumes_cannot_enter_first_forecast(self):
        original = market()
        changed = copy.deepcopy(original)
        for row in changed[4151][119:]:
            for field in pilot.VALUES:
                row[field] = 999999999.0
        self.assertEqual(bench.make_inputs(original)[0], bench.make_inputs(changed)[0])

    def test_earlier_holdout_labels_enter_context_only_after_gap(self):
        inputs = bench.make_inputs(market())
        first_test = inputs[0].target_start
        self.assertNotIn(first_test, [row["timestamp"] for row in inputs[1].context])
        self.assertIn(first_test, [row["timestamp"] for row in inputs[2].context])

    def test_baselines_use_only_available_data(self):
        items = market()
        items[4151][118]["avg_high_price"] = None
        items[4151][119]["avg_high_price"] = 1000000.0  # Unavailable bucket, not persistence.
        cases = bench.make_inputs(items)
        records, _ = bench.evaluate(items, cases[:1], predictions(cases[:1]))
        first = {row["model"]: row for row in records if row["target"] == "avg_high_price"}
        self.assertEqual(first["persistence"]["prediction"], 217.0)
        self.assertEqual(first["seasonal_24h"]["prediction"], 196.0)
        self.assertEqual(first["chronos2"]["actual"], 220.0)

    def test_missing_outcomes_and_baselines_use_one_paired_mask(self):
        items = market()
        items[4151][120]["avg_high_price"] = None
        items[4151][97]["avg_low_price"] = None  # Missing seasonal value for hour 121.
        cases = bench.make_inputs(items)
        records, skipped = bench.evaluate(items, cases, predictions(cases))
        self.assertTrue(any(row["reason"] == "missing_actual" for row in skipped))
        self.assertTrue(any(row["reason"] == "missing_seasonal" for row in skipped))
        masks = [{(row["item_id"], row["target"], row["target_start_utc"]) for row in records if row["model"] == model}
                 for model in ("persistence", "seasonal_24h", "chronos2")]
        self.assertEqual(masks[0], masks[1])
        self.assertEqual(masks[0], masks[2])
        # The missing holdout actual also becomes a missing seasonal reference 24 hours later.
        self.assertEqual(len(skipped), 3)

    def test_invalid_model_outputs_fail_instead_of_selectively_dropping_errors(self):
        items = market()
        cases = bench.make_inputs(items)[:1]
        for output in ([], [{target: [3.0, 2.0, 1.0] for target in bench.TARGETS}],
                       [{target: [1.0, float("nan"), 3.0] for target in bench.TARGETS}]):
            with self.subTest(output=output), self.assertRaises(ValueError):
                bench.evaluate(items, cases, output)

    def test_metrics_and_quantile_loss_have_known_values(self):
        rows = [{"item_id": 4151, "target": "avg_high_price", "actual": 100.0,
                 "model": model, "prediction": 110.0, "q10": 90.0, "q90": 120.0}
                for model in ("persistence", "seasonal_24h", "chronos2")]
        result = bench.metrics(rows)
        row = next(row for row in result["per_series"] if row["model"] == "chronos2")
        self.assertEqual(row["mae_gp"], 10)
        self.assertEqual(row["rmse_gp"], 10)
        self.assertEqual(row["wape_pct"], 10)
        self.assertEqual(row["coverage_80_pct"], 100)
        self.assertEqual(row["interval_width_pct"], 30)
        self.assertAlmostEqual(row["weighted_quantile_loss_pct"], 16 / 3)

    def test_macro_metric_does_not_weight_expensive_items_more(self):
        rows = [{"item_id": item, "target": "avg_high_price", "actual": actual,
                 "model": model, "prediction": predicted, "q10": actual, "q90": predicted}
                for item, actual, predicted in ((1, 100.0, 110.0), (2, 1000000.0, 1000000.0))
                for model in ("persistence", "seasonal_24h", "chronos2")]
        self.assertEqual(bench.metrics(rows)["macro_wape_pct"]["chronos2"], 5)

    def test_dataset_manifest_and_dense_grid_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            items = market()
            save_dataset(root, items)
            loaded, _ = bench.load_dataset(root)
            self.assertEqual(loaded, items)
            with (root / "hourly.csv").open("a", encoding="utf-8") as stream:
                stream.write("\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                bench.load_dataset(root)
            for broken in (market(90), {4151: items[4151][:60] + items[4151][61:]},
                           {4151: items[4151] + [items[4151][-1]]}):
                save_dataset(root, broken)
                with self.assertRaises(ValueError):
                    bench.load_dataset(root)

    def test_output_overwrite_is_rejected_before_loading_the_model(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bench.main(["--output", directory]), 1)


@unittest.skipUnless(importlib.util.find_spec("torch") and importlib.util.find_spec("numpy"),
                     "Optional backend tests require the isolated ML environment")
class BackendTests(unittest.TestCase):
    def test_context_only_covariates_preserve_missing_values(self):
        import numpy as np
        case = bench.make_inputs(market())[0]
        case.context[0]["avg_low_price"] = None
        values = chronos_backend.model_input(case, np)
        self.assertEqual(set(values), {"target", "past_covariates"})
        self.assertEqual(values["target"].shape, (2, len(case.context)))
        self.assertTrue(np.isnan(values["target"][1, 0]))
        self.assertEqual(values["past_covariates"]["high_price_volume"][-1], 1118)

    def test_price_only_removes_covariates_without_changing_prices(self):
        import numpy as np
        case = bench.make_inputs(market())[0]
        case.context[0]["avg_low_price"] = None
        case.context[0]["high_price_volume"] = 0
        case.context[1]["high_price_volume"] = None
        with_volume = chronos_backend.model_input(case, np)
        prices_only = chronos_backend.model_input(case, np, include_volume=False)
        self.assertEqual(set(prices_only), {"target"})
        np.testing.assert_equal(prices_only["target"], with_volume["target"])
        self.assertEqual(with_volume["past_covariates"]["high_price_volume"][0], 0)
        self.assertTrue(np.isnan(with_volume["past_covariates"]["high_price_volume"][1]))
        for row in case.context:
            row["high_price_volume"] = 999999999
            row["low_price_volume"] = 999999999
        np.testing.assert_equal(prices_only["target"],
                                chronos_backend.model_input(case, np, include_volume=False)["target"])

    def test_full_paths_preserve_seven_steps_and_origin_isolation(self):
        import numpy as np
        import torch
        calls = []

        class FakePipeline:
            def predict_quantiles(self, tasks, **kwargs):
                calls.append(kwargs)
                return [torch.arange(42, dtype=torch.float32).reshape(2, 7, 3) for _ in tasks], []

        model = object.__new__(chronos_backend.ChronosForecaster)
        with patch.object(model, "numpy", np, create=True), patch.object(model, "torch", torch, create=True), \
                patch.object(model, "pipeline", FakePipeline(), create=True), contextlib.redirect_stdout(io.StringIO()):
            result = model.predict_paths(bench.make_inputs(market())[:1], prediction_length=7, context_length=120)
            for length in (0, 33):
                with self.assertRaises(ValueError):
                    model.predict_paths([], prediction_length=length)
        self.assertEqual(result[0]["avg_high_price"][0], [0, 1, 2])
        self.assertEqual(result[0]["avg_high_price"][-1], [18, 19, 20])
        self.assertEqual(result[0]["avg_low_price"][-1], [39, 40, 41])
        self.assertFalse(calls[0]["cross_learning"])
        self.assertEqual(calls[0]["prediction_length"], 7)

    def test_adapter_isolates_origins_and_selects_second_forecast_step(self):
        import numpy as np
        import torch
        calls = []

        class FakePipeline:
            def predict_quantiles(self, tasks, **kwargs):
                calls.append((tasks, kwargs))
                tensor = torch.tensor([[[1., 2., 3.], [4., 5., 6.]], [[7., 8., 9.], [10., 11., 12.]]])
                return [tensor.clone() for _ in tasks], []

        model = object.__new__(chronos_backend.ChronosForecaster)
        with patch.object(model, "numpy", np, create=True), patch.object(model, "torch", torch, create=True), \
                patch.object(model, "pipeline", FakePipeline(), create=True), contextlib.redirect_stdout(io.StringIO()):
            cases = bench.make_inputs(market())[:13]
            result = model.predict(cases)
            prices_only = model.predict(cases, include_volume=False)
        self.assertEqual(result, prices_only)
        self.assertEqual(len(result), 13)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all("past_covariates" in task for tasks, _ in calls[:2] for task in tasks))
        self.assertTrue(all(set(task) == {"target"} for tasks, _ in calls[2:] for task in tasks))
        self.assertEqual(result[0]["avg_high_price"], [4, 5, 6])
        self.assertEqual(result[0]["avg_low_price"], [10, 11, 12])
        for _, kwargs in calls:
            self.assertIs(kwargs["cross_learning"], False)
            self.assertEqual(kwargs["prediction_length"], 2)
            self.assertEqual(kwargs["quantile_levels"], [0.1, 0.5, 0.9])


if __name__ == "__main__":
    unittest.main()
