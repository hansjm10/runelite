import copy
import csv
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

import audit
import benchmark
import expanded
import pilot


START = int(audit.date_argument("2026-10-01").timestamp())
END = START + 168 * pilot.HOUR


def catalog():
    result = {}
    for band, price in enumerate((100, 10000, 1000000, 100000000)):
        for index in range(30):
            result[str(1000 + band * 100 + index)] = {
                "avgHighPrice": price + 1, "avgLowPrice": price,
                "highPriceVolume": 10 + index * 10, "lowPriceVolume": 20 + index * 10,
            }
    for item in expanded.EXCLUDED_SMOKE_ITEMS:
        result[str(item)] = dict(result["1000"])
    return result


class FakeClient:
    def __init__(self):
        self.urls = []
        self.shift_item: int | None = None
        self.failure: int | None = None

    def get(self, url):
        self.urls.append(url)
        if self.failure:
            return {"url": url, "status": self.failure, "error": "test refusal", "cached": False}
        query = parse_qs(urlparse(url).query)
        if urlparse(url).path.endswith("/1h"):
            payload = {"timestamp": int(query["timestamp"][0]), "data": catalog()}
        else:
            item = int(query["id"][0])
            start = START + (pilot.HOUR if item == self.shift_item else 0)
            payload = {"itemId": item, "timestep": pilot.HOUR,
                       "startTimestamp": start, "endTimestamp": start + 168 * pilot.HOUR,
                       "data": [{"timestamp": start + i * pilot.HOUR, "avgHighPrice": 100.5,
                                 "avgLowPrice": None if i == 30 else 100.0,
                                 "highPriceVolume": 10, "lowPriceVolume": 0 if i == 30 else 20}
                                for i in range(168) if i != 31]}
        return {"url": url, "status": 200, "cached": True, "fetched_at": audit.iso(END + 2 * pilot.HOUR),
                "payload": payload}


class ExpandedTests(unittest.TestCase):
    def test_selection_is_deterministic_stratified_and_excludes_previous_items(self):
        buckets = [catalog() for _ in range(4)]
        selected = expanded.select_items(buckets, 50)
        reversed_buckets = [dict(reversed(list(bucket.items()))) for bucket in buckets]
        self.assertEqual(selected, expanded.select_items(reversed_buckets, 50))
        self.assertEqual(len({item["item_id"] for item in selected}), 50)
        self.assertEqual({item["price_band"] for item in selected}, {0, 1, 2, 3})
        self.assertEqual({item["liquidity_tier"] for item in selected}, {0, 1, 2})
        self.assertFalse(set(expanded.EXCLUDED_SMOKE_ITEMS) & {item["item_id"] for item in selected})

    def test_cohort_uses_only_four_pretest_market_buckets(self):
        client = FakeClient()
        cohort = expanded.freeze_cohort(client, 50)
        self.assertEqual(len(client.urls), 5)
        self.assertEqual([source["timestamp"] for source in cohort["selection_sources"]],
                         [START + i * pilot.HOUR for i in (0, 6, 12, 18)])
        self.assertLess(cohort["selection_end_exclusive"], END - 48 * pilot.HOUR)
        self.assertEqual(len(expanded.validate_cohort(cohort)), 50)

    def test_ineligible_candidates_are_not_filled_in_with_smoke_items(self):
        buckets = [{"4151": catalog()["4151"]} for _ in range(4)]
        with self.assertRaisesRegex(ValueError, "Only 0"):
            expanded.select_items(buckets, 1)

    def test_shifted_response_windows_preserve_shared_hours_and_missingness(self):
        client = FakeClient()
        cohort = expanded.freeze_cohort(client, 3)
        client.shift_item = cohort["items"][1]["item_id"]
        rows, manifest = expanded.collect_dataset(client, cohort)
        self.assertEqual(len(rows), 3 * 167)
        self.assertEqual(manifest["start_inclusive_utc"], audit.iso(START + pilot.HOUR))
        self.assertEqual(manifest["end_exclusive_utc"], audit.iso(END))
        self.assertEqual(manifest["missing_buckets"], 3)
        self.assertTrue(any(row["low_price_volume"] == 0 and row["avg_low_price"] is None for row in rows))
        self.assertTrue(any(row["record_present"] == 0 and row["low_price_volume"] is None for row in rows))

    def test_export_round_trips_through_benchmark_with_frozen_cohort(self):
        client = FakeClient()
        cohort = expanded.freeze_cohort(client, 3)
        rows, manifest = expanded.collect_dataset(client, cohort)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dataset"
            expanded.export_dataset(rows, manifest, output)
            items, _ = benchmark.load_dataset(output)
            self.assertEqual(set(items), set(expanded.validate_cohort(cohort)))
            self.assertEqual(len(benchmark.make_inputs(items)), 3 * 48)
            with (output / "hourly.csv").open(encoding="utf-8", newline="") as stream:
                saved = list(csv.DictReader(stream))
            self.assertEqual(len(saved), 504)
            self.assertTrue(any(row["record_present"] == "0" and row["avg_high_price"] == "" for row in saved))
            with self.assertRaises(FileExistsError):
                expanded.export_dataset(rows, manifest, output)

    def test_cohort_test_overlap_or_tampering_fails_before_model_inference(self):
        client = FakeClient()
        rows, manifest = expanded.collect_dataset(client, expanded.freeze_cohort(client, 3))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dataset"
            expanded.export_dataset(rows, manifest, output)
            original = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            for rehash in (False, True):
                changed = copy.deepcopy(original)
                changed["cohort"]["selection_end_exclusive"] = END - 24 * pilot.HOUR
                if rehash:
                    changed["cohort_sha256"] = expanded.digest(changed["cohort"])
                (output / "manifest.json").write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(ValueError):
                    benchmark.load_dataset(output)

    def test_capture_is_one_request_idempotent_and_records_absent_items(self):
        client = FakeClient()
        cohort = expanded.freeze_cohort(client, 3)
        cohort["items"][0]["item_id"] = 999999  # Absent item must remain unknown.
        before = len(client.urls)
        now = datetime.fromtimestamp(END + 3 * pilot.HOUR, audit.UTC)
        with tempfile.TemporaryDirectory() as directory:
            path = expanded.capture(client, cohort, Path(directory), now)
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["interval_start"], END + pilot.HOUR)
            self.assertIsNone(value["items"]["999999"])
            original = path.read_bytes()
            self.assertEqual(expanded.capture(client, cohort, Path(directory), now), path)
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(client.urls) - before, 1)

    def test_rate_limit_stops_at_the_failed_request(self):
        client = FakeClient()
        client.failure = 429
        with self.assertRaises(ValueError):
            expanded.freeze_cohort(client, 50)
        self.assertEqual(len(client.urls), 1)

    def test_bucket_substitution_is_rejected(self):
        value = {"payload": {"timestamp": START + pilot.HOUR, "data": catalog()}}
        with self.assertRaises(ValueError):
            expanded.bucket_data(value, START)

    def test_price_change_metrics_and_partial_week_breakdown(self):
        start = int(audit.date_argument("2026-09-29").timestamp())
        items = {1000: [{"timestamp": start + i * pilot.HOUR, "avg_high_price": 100.0 + i,
                         "avg_low_price": 90.0 + i, "high_price_volume": 10, "low_price_volume": 10}
                        for i in range(168)]}
        cases = benchmark.make_inputs(items)
        lookup = {row["timestamp"]: row for row in items[1000]}
        forecasts = [{field: [lookup[case.target_start][field] - 1, lookup[case.target_start][field],
                              lookup[case.target_start][field] + 1] for field in benchmark.TARGETS}
                     for case in cases]
        records, skipped = benchmark.evaluate(items, cases, forecasts)
        self.assertEqual(skipped, [])
        scores = benchmark.metrics(records)
        for row in scores["per_series"]:
            if row["model"] == "chronos2":
                self.assertEqual(row["change_mae_bps"], 0)
                self.assertEqual(row["direction_accuracy_pct"], 100)
        weeks = benchmark.weekly_metrics(records)
        self.assertEqual([week["hours_observed"] for week in weeks], [24, 24])
        self.assertTrue(all(week["macro_wape_pct"]["chronos2"] == 0 for week in weeks))

    def test_longer_holdout_is_explicit_and_never_uses_future_context(self):
        rows = [{"timestamp": START + i * pilot.HOUR, "avg_high_price": 1.0, "avg_low_price": 1.0,
                 "high_price_volume": 1, "low_price_volume": 1} for i in range(720)]
        cases = benchmark.make_inputs({1000: rows}, holdout_hours=336)
        self.assertEqual(len(cases), 336)
        self.assertEqual(cases[0].target_start, START + 384 * pilot.HOUR)
        self.assertEqual(cases[0].context[-1]["timestamp"], START + 382 * pilot.HOUR)


if __name__ == "__main__":
    unittest.main()
