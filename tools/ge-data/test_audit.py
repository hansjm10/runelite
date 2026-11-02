import contextlib
from datetime import datetime, timezone
from email.message import Message
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import audit


EPOCH = 1762041600


def tick(epoch, **changes):
    return {"timestamp": epoch, "avgHighPrice": 100.25, "avgLowPrice": 99,
            "highPriceVolume": 10, "lowPriceVolume": 0, **changes}


def series(rows, step=3600):
    return {"data": rows, "itemId": 4151, "timestep": step}


class SummaryTests(unittest.TestCase):
    def test_live_guide_objects_preserve_milliseconds_and_missing_volume(self):
        payload = {"4151": [
            {"timestamp": (EPOCH + 86400) * 1000, "price": 101, "volume": 5},
            {"timestamp": EPOCH * 1000, "price": 100, "volume": None},
        ]}
        result = audit.summarize(payload, {"kind": "guide", "item": 4151})
        self.assertEqual(result["records"], 2)
        self.assertEqual(result["first"], audit.iso(EPOCH))
        self.assertEqual(result["first_volume_at"], audit.iso(EPOCH + 86400))
        self.assertEqual(result["missing_fields"], {"price": 0, "volume": 1})
        self.assertIsNone(result["interval_seconds"])

    def test_documented_legacy_guide_arrays(self):
        rows = audit.observations({"4151": [[EPOCH, 100], [(EPOCH + 86400) * 1000, 101, 0]]}, "guide", 4151)
        self.assertIsNone(rows[0]["volume"])
        self.assertEqual(rows[1]["volume"], 0)
        self.assertEqual(rows[1]["timestamp"], EPOCH + 86400)

    def test_actual_timeseries_resolution_gaps_and_duplicates(self):
        result = audit.summarize(series([
            tick(EPOCH + 10800), tick(EPOCH, avgLowPrice=None), tick(EPOCH), tick(EPOCH + 3600)
        ]), {"kind": "timeseries", "item": 4151})
        self.assertEqual(result["interval_seconds"], 3600)
        self.assertEqual(result["gaps_larger_than_interval"], 1)
        self.assertEqual(result["duplicate_timestamps"], 1)
        self.assertEqual(result["missing_fields"]["avgLowPrice"], 1)
        self.assertEqual(result["missing_fields"]["lowPriceVolume"], 0)

    def test_one_year_query_can_return_daily_data(self):
        result = audit.summarize(series([tick(EPOCH), tick(EPOCH + 86400)], step=86400),
                                 {"kind": "timeseries", "item": 4151})
        self.assertEqual(result["interval_seconds"], 86400)
        self.assertEqual(result["gaps_larger_than_interval"], 0)

    def test_empty_is_not_zero_priced_data(self):
        result = audit.summarize(series([]), {"kind": "timeseries", "item": 4151})
        self.assertEqual(result, {"state": "empty", "records": 0})

    def test_bucket_must_match_requested_timestamp(self):
        result = audit.summarize({"timestamp": EPOCH + 3600, "data": {"4151": tick(EPOCH)}},
                                 {"kind": "bucket", "timestamp": EPOCH, "interval_seconds": 3600,
                                  "items": [4151, 561]})
        self.assertEqual(result["state"], "timestamp_mismatch")
        self.assertIsNone(result["sample_items"]["561"])

    def test_schema_and_item_mismatches_are_rejected(self):
        for payload in ({"success": False, "error": "no data"},
                        {"data": [], "itemId": 561},
                        series([{"timestamp": EPOCH}]),
                        series([tick(EPOCH)], step=0)):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                audit.summarize(payload, {"kind": "timeseries", "item": 4151})

    def test_invalid_timestamps_are_rejected(self):
        for value in (True, "1762041600", 123, float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.timestamp(value)


class FetchTests(unittest.TestCase):
    def test_successful_response_is_cached_and_replayed_offline(self):
        class Response(io.BytesIO):
            status = 200
            headers = {"Date": "test date"}
        with tempfile.TemporaryDirectory() as directory:
            response = Response(json.dumps(series([tick(EPOCH)])).encode())
            with patch("audit.urlopen", return_value=response) as opener:
                live = audit.Client(directory).get("https://example.test/data")
                request = opener.call_args.args[0]
                self.assertEqual(request.get_header("User-agent"), audit.USER_AGENT)
            with patch("audit.urlopen", side_effect=AssertionError("Offline must not use network")):
                cached = audit.Client(directory, offline=True).get("https://example.test/data")
            self.assertFalse(live["cached"])
            self.assertTrue(cached["cached"])
            self.assertEqual(live["payload"], cached["payload"])
            self.assertEqual(live["fetched_at"], cached["fetched_at"])

    def test_offline_miss_does_not_use_network(self):
        with tempfile.TemporaryDirectory() as directory, patch("audit.urlopen") as opener:
            result = audit.Client(directory, offline=True).get("https://example.test/missing")
            opener.assert_not_called()
            self.assertEqual(result["error"], "Not cached; offline mode")

    def test_requests_are_spaced(self):
        with tempfile.TemporaryDirectory() as directory:
            client = audit.Client(directory)
            client.last_request = 10.0
            with patch("audit.time.monotonic", return_value=10.5), patch("audit.time.sleep") as sleep, \
                    patch("audit.urlopen", side_effect=TimeoutError("test timeout")):
                client.get("https://example.test/data")
            sleep.assert_called_once_with(1.5)

    def test_rate_limit_stops_audit_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            probes = audit.make_probes([4151], [])
            headers = Message()
            headers["Retry-After"] = "120"
            error = HTTPError(probes[0]["url"], 429, "rate limit", headers, None)
            with patch("audit.urlopen", side_effect=error) as opener, contextlib.redirect_stdout(io.StringIO()):
                report = audit.run_audit(audit.Client(directory), probes)
            self.assertEqual(opener.call_count, 1)
            self.assertEqual(report["completed_probes"], 1)
            self.assertIsNotNone(report["stopped_reason"])
            self.assertEqual(report["results"][0]["retry_after"], "120")
            self.assertFalse(list(Path(directory).glob("*.json")))

    def test_404_is_an_unavailable_probe_not_a_claim_about_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            probe = audit.make_probes([], [datetime(2021, 2, 1, tzinfo=timezone.utc)])[0]
            error = HTTPError(probe["url"], 404, "not found", Message(), None)
            with patch("audit.urlopen", side_effect=error), contextlib.redirect_stdout(io.StringIO()):
                report = audit.run_audit(audit.Client(directory), [probe])
            self.assertEqual(report["results"][0]["state"], "unavailable")
            self.assertIsNone(report["stopped_reason"])

    def test_schema_failure_is_recorded(self):
        class StubClient:
            def get(self, url):
                return {"url": url, "status": 200, "cached": False, "payload": {"success": False}}
        with contextlib.redirect_stdout(io.StringIO()):
            report = audit.run_audit(StubClient(), audit.make_probes([4151], [])[:1])
        self.assertEqual(report["results"][0]["state"], "schema_error")


class CliTests(unittest.TestCase):
    def test_offline_failure_writes_reports_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            result = audit.main(["--offline", "--items", "4151", "--dates", "2021-04-01", "--output", directory])
            report = json.loads((Path(directory) / "report.json").read_text(encoding="utf-8"))
            text = (Path(directory) / "report.md").read_text(encoding="utf-8")
        self.assertEqual(result, 1)
        self.assertEqual(report["completed_probes"], 5)
        self.assertIn("Interpretation limits", text)

    def test_probe_count_is_bounded_before_network_access(self):
        with patch("audit.urlopen") as opener, contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.main(["--items", *map(str, range(1, 20))])
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
