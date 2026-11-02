import contextlib
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import audit
import pilot


START = int(audit.date_argument("2026-10-01").timestamp())


def observation(stamp, **changes):
    return {"timestamp": stamp, "avgHighPrice": 123.45, "avgLowPrice": 122,
            "highPriceVolume": 10, "lowPriceVolume": 5, **changes}


def snapshot(item=4151, rows=None, start=START, hours=3):
    return {
        "url": audit.WIKI + "/timeseries?" + urlencode({"id": item, "lookback": "7d"}),
        "status": 200,
        "fetched_at": audit.iso(start + hours * pilot.HOUR + 60),
        "payload": {"itemId": item, "timestep": pilot.HOUR,
                    "startTimestamp": start, "endTimestamp": start + hours * pilot.HOUR,
                    "data": [observation(start + i * pilot.HOUR) for i in range(hours)] if rows is None else rows},
    }


def cache_snapshot(cache, value):
    path = cache / (hashlib.sha256(value["url"].encode()).hexdigest() + ".json")
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class PilotTests(unittest.TestCase):
    def setUp(self):
        # Every test, including the CLI integration tests, must remain offline.
        network = patch("audit.urlopen", side_effect=AssertionError("Pilot must never access network"))
        self.opener = network.start()
        self.addCleanup(network.stop)

    def test_missing_edge_buckets_nulls_and_zero_volume_are_distinct(self):
        value = snapshot(rows=[observation(START + pilot.HOUR, avgLowPrice=None, lowPriceVolume=0)])
        rows, info = pilot.normalize(value, 4151)
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["record_present"] for row in rows], [0, 1, 0])
        self.assertIsNone(rows[0]["low_price_volume"])
        self.assertEqual(rows[1]["low_price_volume"], 0)
        self.assertIsNone(rows[1]["avg_low_price"])
        self.assertEqual(rows[1]["avg_high_price"], 123.45)
        self.assertEqual(info["missing_buckets"], [audit.iso(START), audit.iso(START + 2 * pilot.HOUR)])
        self.assertEqual(info["null_fields_in_observed_buckets"]["avg_low_price"], 1)
        self.assertEqual(info["null_fields_in_observed_buckets"]["low_price_volume"], 0)
        self.assertEqual(info["complete_price_buckets"], 0)

    def test_grid_end_is_exclusive_and_rows_have_provenance(self):
        value = snapshot(rows=[observation(START + pilot.HOUR), observation(START)], hours=2)
        rows, info = pilot.normalize(value, 4151)
        self.assertEqual(rows[0]["interval_start_utc"], audit.iso(START))
        self.assertEqual(rows[-1]["interval_end_utc"], info["end_exclusive_utc"])
        self.assertEqual(rows[0]["retrieved_at"], value["fetched_at"])
        self.assertEqual(rows[0]["source"], "osrs_wiki_realtime_v2")
        self.assertEqual(rows[0]["source_regime"], "jagex_all_clients")
        self.assertEqual(len(info["payload_sha256"]), 64)

    def test_source_change_is_tagged_without_mixing_sources(self):
        start = pilot.SOURCE_CHANGE - pilot.HOUR
        rows, _ = pilot.normalize(snapshot(start=start, hours=2), 4151)
        self.assertEqual([row["source_regime"] for row in rows], ["runelite_only", "jagex_all_clients"])

    def test_wrong_item_interval_and_window_are_rejected(self):
        for key, value in (("itemId", 561), ("timestep", 86400), ("startTimestamp", START + 1),
                           ("endTimestamp", START), ("endTimestamp", START + 169 * pilot.HOUR)):
            item = snapshot()
            item["payload"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                pilot.normalize(item, 4151)

    def test_duplicates_outside_bounds_and_off_grid_records_are_rejected(self):
        for rows in ([observation(START), observation(START)], [observation(START - pilot.HOUR)],
                     [observation(START + 3 * pilot.HOUR)], [observation(START + 1)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                pilot.normalize(snapshot(rows=rows), 4151)

    def test_bad_numeric_observations_are_rejected(self):
        for field, value in (("avgHighPrice", 0), ("avgLowPrice", -1), ("avgHighPrice", True),
                             ("avgLowPrice", float("nan")), ("highPriceVolume", float("inf")),
                             ("lowPriceVolume", -1), ("highPriceVolume", 1.5), ("avgHighPrice", "123")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                pilot.normalize(snapshot(rows=[observation(START, **{field: value})]), 4151)

    def test_incomplete_intervals_and_naive_retrieval_dates_are_rejected(self):
        for fetched in (audit.iso(START), "2026-10-02T00:00:00"):
            value = snapshot()
            value["fetched_at"] = fetched
            with self.subTest(fetched=fetched), self.assertRaises(ValueError):
                pilot.normalize(value, 4151)

    def test_csv_round_trip_manifest_and_replay_are_reproducible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            cache_snapshot(cache, snapshot())
            cache_snapshot(cache, snapshot(item=561, rows=[observation(START, avgLowPrice=None, lowPriceVolume=0)]))
            rows, manifest = pilot.build_pilot(cache, [4151, 561])
            pilot.export_pilot(rows, manifest, root / "first")
            with (root / "first/hourly.csv").open(encoding="utf-8", newline="") as stream:
                saved = list(csv.DictReader(stream))
            self.assertEqual(len(saved), 6)
            self.assertEqual(saved[0]["item_id"], "561")
            self.assertEqual(saved[0]["avg_low_price"], "")
            self.assertEqual(saved[0]["low_price_volume"], "0")
            self.assertEqual(saved[2]["record_present"], "0")
            self.assertEqual(saved[2]["low_price_volume"], "")
            on_disk = json.loads((root / "first/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk["missing_buckets"], 2)
            self.assertEqual(on_disk["complete_price_buckets"], 3)
            self.assertEqual(on_disk["network_requests"], 0)
            replay_rows, replay_manifest = pilot.build_pilot(cache, [561, 4151])
            pilot.export_pilot(replay_rows, replay_manifest, root / "second")
            self.assertEqual(on_disk["csv_sha256"], replay_manifest["csv_sha256"])
            self.opener.assert_not_called()

    def test_empty_selected_samples_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_snapshot(Path(directory), snapshot(rows=[]))
            with self.assertRaisesRegex(ValueError, "No observed data"):
                pilot.build_pilot(directory, [4151])

    def test_cli_missing_cache_fails_without_writing_output(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stderr(io.StringIO()):
            root = Path(directory)
            code = pilot.main(["--cache", str(root / "missing"), "--output", str(root / "dataset")])
            self.assertEqual(code, 1)
            self.assertFalse((root / "dataset").exists())
            self.opener.assert_not_called()

    def test_cli_does_not_overwrite_existing_dataset(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            root = Path(directory)
            cache_snapshot(root / "cache", snapshot())
            args = ["--cache", str(root / "cache"), "--items", "4151", "--output", str(root / "dataset")]
            self.assertEqual(pilot.main(args), 0)
            original = (root / "dataset/manifest.json").read_bytes()
            self.assertEqual(pilot.main(args), 1)
            self.assertEqual((root / "dataset/manifest.json").read_bytes(), original)

    def test_malformed_price_fields_are_not_silently_interpreted_as_missing(self):
        value = copy.deepcopy(snapshot())
        del value["payload"]["data"][0]["avgLowPrice"]
        with self.assertRaises(ValueError):
            pilot.normalize(value, 4151)


if __name__ == "__main__":
    unittest.main()
