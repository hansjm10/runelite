import contextlib
import copy
import csv
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import ablation
import audit
import benchmark as bench
import expanded
import pilot
from test_expanded import END, FakeClient


class FutureClient:
    def __init__(self, plan):
        self.urls = []
        self.end = bench.parse_time(plan["collect_not_before_utc"])
        self.start = self.end - 168 * pilot.HOUR
        self.step = pilot.HOUR
        self.shift_item: int | None = None
        self.failure: int | None = None

    def get(self, url):
        self.urls.append(url)
        if self.failure:
            return {"url": url, "status": self.failure, "error": "test refusal", "cached": False}
        item = int(parse_qs(urlparse(url).query)["id"][0])
        start = self.start + (pilot.HOUR if item == self.shift_item else 0)
        end = self.end + (pilot.HOUR if item == self.shift_item else 0)
        return {"url": url, "status": 200, "cached": True, "fetched_at": audit.iso(end),
                "payload": {"itemId": item, "timestep": self.step,
                            "startTimestamp": start, "endTimestamp": end,
                            "data": [{"timestamp": stamp, "avgHighPrice": 100.0 + i,
                                      "avgLowPrice": None if i == 130 else 90.0 + i,
                                      "highPriceVolume": 10, "lowPriceVolume": 0 if i == 130 else 20}
                                     for i, stamp in enumerate(range(start, end, pilot.HOUR)) if i != 131]}}


def forecasts(items, cases, error):
    lookup = {item: {row["timestamp"]: row for row in rows} for item, rows in items.items()}
    return [{target: [(lookup[case.item_id][case.target_start][target] or 100) + error + delta
                      for delta in (-20, 0, 20)] for target in bench.TARGETS} for case in cases]


class AblationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "previous"
        client = FakeClient()
        cohort = expanded.freeze_cohort(client, 3)
        with contextlib.redirect_stdout(io.StringIO()):
            rows, manifest = expanded.collect_dataset(client, cohort)
        expanded.export_dataset(rows, manifest, self.source)
        self.created = datetime.fromtimestamp(END + 3 * pilot.HOUR + 600, audit.UTC)
        self.plan = ablation.make_plan(self.source, self.created)
        self.ready = datetime.fromisoformat(self.plan["collect_not_before_utc"])

    def dataset(self, client=None):
        client = client or FutureClient(self.plan)
        with contextlib.redirect_stdout(io.StringIO()):
            rows, manifest = ablation.collect_dataset(client, self.plan, self.ready)
        folder = self.root / "dataset"
        ablation.export_dataset(rows, manifest, folder)
        return ablation.load_inputs(folder, self.plan)

    def test_plan_freezes_new_time_period_and_same_cohort(self):
        ids, start, end, ready = ablation.validate_plan(self.plan)
        self.assertEqual(start, END + 4 * pilot.HOUR)
        self.assertEqual(end - start, 48 * pilot.HOUR)
        self.assertEqual(ready - end, pilot.HOUR)
        self.assertGreater(start, self.created.timestamp())
        self.assertEqual(len(ids), 3)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            args = ["init", "--root", str(self.root / "new-plan"), "--source-dataset", str(self.source)]
            self.assertEqual(ablation.main(args), 0)
            saved = (self.root / "new-plan" / "plan.json").read_bytes()
            self.assertEqual(ablation.main(args), 1)
            self.assertEqual((self.root / "new-plan" / "plan.json").read_bytes(), saved)

    def test_overlapping_holdout_changed_settings_and_cohort_are_rejected(self):
        for field, value in (("test_start_utc", audit.iso(END)),
                             ("created_at", self.plan["test_start_utc"]),
                             ("collect_not_before_utc", self.plan["test_end_exclusive_utc"]),
                             ("cohort_sha256", "bad")):
            changed = copy.deepcopy(self.plan)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                ablation.validate_plan(changed)
        changed = copy.deepcopy(self.plan)
        changed["settings"]["gap_hours"] = 0
        with self.assertRaisesRegex(ValueError, "settings"):
            ablation.validate_plan(changed)

    def test_early_collection_and_inference_make_no_requests_or_model_calls(self):
        client = FutureClient(self.plan)
        early = datetime.fromtimestamp(self.ready.timestamp() - 1, audit.UTC)
        with self.assertRaisesRegex(ValueError, "not ready"):
            ablation.collect_dataset(client, self.plan, early)
        self.assertEqual(client.urls, [])
        with patch.object(ablation.chronos_backend, "ChronosForecaster") as model:
            with self.assertRaisesRegex(ValueError, "not ready"):
                ablation.run_comparison(self.root, self.plan, self.root / "models", early)
            model.assert_not_called()
        self.assertFalse((self.root / "results").exists())

    def test_fixed_window_round_trip_preserves_missing_zero_and_provenance(self):
        client = FutureClient(self.plan)
        client.shift_item = self.plan["cohort"]["items"][1]["item_id"]
        items, cases, _, manifest = self.dataset(client)
        self.assertEqual(len(client.urls), 3)
        self.assertEqual(len(cases), 3 * 48)
        self.assertEqual(min(case.target_start for case in cases), bench.parse_time(self.plan["test_start_utc"]))
        self.assertEqual(max(case.target_start for case in cases) + pilot.HOUR,
                         bench.parse_time(self.plan["test_end_exclusive_utc"]))
        self.assertEqual(manifest["plan_sha256"], expanded.digest(self.plan))
        self.assertEqual(manifest["missing_buckets"], 3)
        self.assertTrue(all(source["payload_sha256"] and source["retrieved_at"] for source in manifest["sources"]))
        self.assertTrue(any(row["low_price_volume"] == 0 and row["avg_low_price"] is None
                            for rows in items.values() for row in rows))
        self.assertTrue(any(all(row[field] is None for field in pilot.VALUES)
                            for rows in items.values() for row in rows))
        for case in cases:
            self.assertEqual(case.context[-1]["timestamp"], case.target_start - 2 * pilot.HOUR)
            self.assertLessEqual(len(case.context), 120)

    def test_stale_short_coarse_and_failed_responses_stop_at_first_item(self):
        stale = FakeClient()
        short = FutureClient(self.plan)
        short.start = bench.parse_time(self.plan["test_start_utc"]) - 48 * pilot.HOUR
        coarse = FutureClient(self.plan)
        coarse.step = 21600
        denied = FutureClient(self.plan)
        denied.failure = 429
        for client in (stale, short, coarse, denied):
            with self.subTest(client=client), self.assertRaises(ValueError):
                ablation.collect_dataset(client, self.plan, self.ready)
            self.assertEqual(len(client.urls), 1)

    def test_old_dataset_and_changed_plan_binding_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "bound"):
            ablation.load_inputs(self.source, self.plan)
        manifest_path = self.source / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["plan_sha256"] = expanded.digest(self.plan)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fixed fresh holdout"):
            ablation.load_inputs(self.source, self.plan)
        self.dataset()
        changed = copy.deepcopy(self.plan)
        changed["previous_dataset_sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "bound"):
            ablation.load_inputs(self.root / "dataset", changed)

    def test_variants_and_baselines_share_mask_and_known_improvement(self):
        items, cases, _, _ = self.dataset()
        outputs = {"prices_only": forecasts(items, cases, 10), "prices_and_volume": forecasts(items, cases, 5)}
        result, records = ablation.compare(items, cases, outputs)
        self.assertAlmostEqual(result["volume_relative_wape_improvement_pct"], 50)
        self.assertGreater(result["volume_wape_improvement_percentage_points"], 0)
        self.assertTrue(result["skipped"])
        models = {row["model"] for row in records}
        self.assertEqual(models, {"prices_only", "prices_and_volume", "persistence", "seasonal_24h"})
        masks = [{(row["item_id"], row["target"], row["target_start_utc"]) for row in records if row["model"] == model}
                 for model in models]
        self.assertTrue(all(mask == masks[0] for mask in masks))
        for values in ([1, float("nan"), 3], [3, 2, 1]):
            broken = copy.deepcopy(outputs)
            broken["prices_and_volume"][0][bench.TARGETS[0]] = values
            with self.assertRaises(ValueError):
                ablation.compare(items, cases, broken)
        with self.assertRaisesRegex(ValueError, "Both"):
            ablation.compare(items, cases, {"prices_only": outputs["prices_only"]})

    def test_retrospective_runs_before_fresh_holdout_without_changing_sources_or_plan(self):
        items, checksum = bench.load_dataset(self.source)
        cases = bench.make_inputs(items)
        before = {path.name: path.read_bytes() for path in self.source.iterdir()}
        future = self.root / "fresh"
        future.mkdir()
        frozen = json.dumps(self.plan).encode()
        (future / "plan.json").write_bytes(frozen)
        output = self.root / "retrospective"
        self.assertLess(self.created, self.ready)
        with patch.object(ablation.chronos_backend, "ChronosForecaster") as model, \
                patch.object(ablation.audit, "Client") as client:
            model.return_value.predict.side_effect = [forecasts(items, cases, 10), forecasts(items, cases, 5)]
            model.return_value.provenance.return_value = {"revision": ablation.chronos_backend.MODEL_REVISION}
            result = ablation.run_retrospective(self.source, output, self.root / "models", self.created)
            model.assert_called_once_with(self.root / "models", offline=True)
            client.assert_not_called()
            calls = model.return_value.predict.call_args_list
            self.assertEqual(calls[0].args[0], cases)
            self.assertEqual(calls[1].args[0], cases)
            self.assertEqual([call.kwargs["include_volume"] for call in calls], [False, True])
            with self.assertRaisesRegex(ValueError, "already exists"):
                ablation.run_retrospective(self.source, output, self.root / "models", self.created)
            self.assertEqual(model.call_count, 1)
        self.assertEqual(result["evaluation_mode"], "retrospective_exploratory")
        self.assertEqual(result["dataset_sha256"], checksum)
        self.assertEqual(result["plan"]["created_at"], self.created.isoformat())
        self.assertEqual(result["plan"]["test_start_utc"], audit.iso(END - 48 * pilot.HOUR))
        self.assertEqual(result["plan"]["test_end_exclusive_utc"], audit.iso(END))
        self.assertAlmostEqual(result["volume_relative_wape_improvement_pct"], 50)
        self.assertIn("previously inspected", result["limitations"][0])
        report = (output / "results" / "report.md").read_text(encoding="utf-8")
        self.assertIn("retrospective_exploratory", report)
        self.assertNotIn("This is a predeclared new calendar holdout", report)
        self.assertEqual({path.name: path.read_bytes() for path in self.source.iterdir()}, before)
        self.assertEqual((future / "plan.json").read_bytes(), frozen)

    def test_retrospective_rejects_existing_root_corruption_and_unclosed_targets_before_model_load(self):
        with patch.object(ablation.chronos_backend, "ChronosForecaster") as model:
            with self.assertRaisesRegex(ValueError, "already exists"):
                ablation.run_retrospective(self.source, self.root, self.root / "models", self.created)
            early = datetime.fromtimestamp(END - 1, audit.UTC)
            with self.assertRaisesRegex(ValueError, "already have closed"):
                ablation.run_retrospective(self.source, self.root / "retro", self.root / "models", early)
            with (self.source / "hourly.csv").open("a", encoding="utf-8") as stream:
                stream.write("\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                ablation.run_retrospective(self.source, self.root / "retro", self.root / "models", self.created)
            model.assert_not_called()

    def test_retrospective_cli_uses_separate_default_root_and_no_market_client(self):
        with patch.object(ablation, "run_retrospective") as run, patch.object(ablation.audit, "Client") as client, \
                contextlib.redirect_stdout(io.StringIO()):
            run.return_value = {"volume_wape_improvement_percentage_points": 1.0}
            self.assertEqual(ablation.main(["retrospective", "--source-dataset", str(self.source)]), 0)
            self.assertEqual(run.call_args.args[0], self.source)
            self.assertEqual(run.call_args.args[1].name, "volume-ablation-retrospective")
            client.assert_not_called()

    def test_run_loads_one_offline_model_and_preserves_completed_results(self):
        items, cases, _, _ = self.dataset()
        with patch.object(ablation.chronos_backend, "ChronosForecaster") as model:
            model.return_value.predict.side_effect = [forecasts(items, cases, 10), forecasts(items, cases, 5)]
            model.return_value.provenance.return_value = {"revision": ablation.chronos_backend.MODEL_REVISION}
            result = ablation.run_comparison(self.root, self.plan, self.root / "models", self.ready)
            model.assert_called_once_with(self.root / "models", offline=True)
            calls = model.return_value.predict.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0].args[0], calls[1].args[0])
            self.assertEqual([call.kwargs["include_volume"] for call in calls], [False, True])
            self.assertAlmostEqual(result["volume_relative_wape_improvement_pct"], 50)
            saved = (self.root / "results" / "metrics.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "already exist"):
                ablation.run_comparison(self.root, self.plan, self.root / "models", self.ready)
            self.assertEqual((self.root / "results" / "metrics.json").read_bytes(), saved)
            self.assertEqual(model.call_count, 1)
        with (self.root / "results" / "forecasts.csv").open(encoding="utf-8", newline="") as stream:
            self.assertEqual({row["model"] for row in csv.DictReader(stream)},
                             {"prices_only", "prices_and_volume", "persistence", "seasonal_24h"})


if __name__ == "__main__":
    unittest.main()
