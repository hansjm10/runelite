#!/usr/bin/env python3
"""Small, read-only OSRS historical data audit. Python 3.10+, standard library only."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


UTC = timezone.utc
WIKI = "https://prices.runescape.wiki/api/v2/osrs"
GUIDE = "https://api.weirdgloop.org/exchange/history/osrs/all"
DEFAULT_ITEMS = (4151, 561, 20997)  # Abyssal whip, nature rune, twisted bow
USER_AGENT = "runelite-ge-data-coverage-audit/0.1 (manual research; no bulk collection)"
NOTES = [
    "Sparse probes establish availability only at the sampled dates, not continuous retention.",
    "Guide prices and real-time transaction averages are separate series; do not splice them together.",
    "High/low mean instant-buy/instant-sell sides, not maximum/minimum prices or live order-book quotes.",
    "Missing records are not zero volume, and historical averages do not prove an offer would fill.",
    "A bucket is only observable after its interval ends, plus publication delay; avoid look-ahead leakage.",
    "The Wiki documents a RuneLite-to-Jagex data-source change on 2026-09-30; preserve that boundary.",
    "Guide-price volume covers a GE update period, which is not necessarily exactly 24 hours.",
    "Cached responses retain their original fetched_at; use a new output directory for a fresh audit.",
]


def timestamp(value):
    """Normalize API epoch seconds or milliseconds to seconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a numeric epoch timestamp")
    seconds = value / 1000 if value >= 100_000_000_000 else value
    # Validate that a broken timestamp cannot masquerade as a historical observation.
    date = datetime.fromtimestamp(seconds, UTC)
    if date.year < 2000 or date.year > 2100:
        raise ValueError("Timestamp outside the supported audit range")
    return seconds


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat()


def utc_now():
    return datetime.now(UTC).isoformat()


def date_argument(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected a UTC date: YYYY-MM-DD") from error


class Client:
    """URL-addressed response cache; at least two seconds between network requests."""

    def __init__(self, cache, user_agent=USER_AGENT, offline=False):
        self.cache = Path(cache)
        self.user_agent = user_agent
        self.offline = offline
        self.last_request = None

    def get(self, url):
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["url"] != url:
                raise ValueError("Cache URL mismatch")
            return dict(record, cached=True)
        if self.offline:
            return {"url": url, "status": None, "error": "Not cached; offline mode", "cached": False}
        if self.last_request is not None:
            time.sleep(max(0, 2 - (time.monotonic() - self.last_request)))
        record = {"url": url, "fetched_at": utc_now(), "status": None}
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                record["status"] = response.status
                record["server_date"] = response.headers.get("Date")
                record["payload"] = json.load(response)
        except HTTPError as error:
            record.update(status=error.code, error=f"HTTP {error.code}")
            record["retry_after"] = error.headers.get("Retry-After")
        except (URLError, TimeoutError, ValueError) as error:
            record["error"] = str(error)
        finally:
            self.last_request = time.monotonic()
        if "payload" in record:
            self.cache.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return dict(record, cached=False)


def observations(payload, kind, item):
    """Accept the live guide object format and the documented legacy array format."""
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise ValueError("API did not return a successful object response")
    values = payload.get(str(item), []) if kind == "guide" else payload["data"]
    if not isinstance(values, list):
        raise ValueError("Expected a list of observations")
    rows = []
    for value in values:
        if kind == "guide" and isinstance(value, list):
            if len(value) not in (2, 3):
                raise ValueError("Unexpected guide-price array shape")
            value = {"timestamp": value[0], "price": value[1], "volume": value[2] if len(value) == 3 else None}
        row = dict(value)
        row["timestamp"] = timestamp(row["timestamp"])
        fields = ("price",) if kind == "guide" else (
            "avgHighPrice", "avgLowPrice", "highPriceVolume", "lowPriceVolume"
        )
        if any(field not in row for field in fields):
            raise ValueError("Observation is missing required price/volume fields")
        rows.append(row)
    return sorted(rows, key=lambda row: row["timestamp"])


def summarize(payload, probe):
    kind = probe["kind"]
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise ValueError("API did not return a successful object response")
    if kind == "bucket":
        actual = timestamp(payload["timestamp"])
        data = payload["data"]
        if not isinstance(data, dict):
            raise ValueError("Expected a mapping of item IDs to bucket observations")
        matches = actual == probe["timestamp"]
        return {
            "state": "timestamp_mismatch" if not matches else ("available" if data else "empty"),
            "records": len(data), "first": iso(actual), "last": iso(actual),
            "interval_seconds": probe["interval_seconds"],
            "requested_timestamp": probe["timestamp"], "returned_timestamp": actual,
            "sample_items": {str(item): data.get(str(item)) for item in probe["items"]},
        }
    if kind == "timeseries" and str(payload.get("itemId")) != str(probe["item"]):
        raise ValueError("Response itemId differs from the requested item")
    rows = observations(payload, kind, probe["item"])
    if not rows:
        return {"state": "empty", "records": 0}
    stamps = [row["timestamp"] for row in rows]
    differences = [right - left for left, right in zip(stamps, stamps[1:])]
    step = payload.get("timestep") if kind == "timeseries" else None
    if kind == "timeseries" and (isinstance(step, bool) or not isinstance(step, (int, float)) or step <= 0):
        raise ValueError("Expected a positive timestep in the v2 response")
    fields = ("price", "volume") if kind == "guide" else (
        "avgHighPrice", "avgLowPrice", "highPriceVolume", "lowPriceVolume"
    )
    summary = {
        "state": "available", "records": len(rows), "first": iso(stamps[0]), "last": iso(stamps[-1]),
        "interval_seconds": step,
        "median_spacing_seconds": statistics.median(differences) if differences else None,
        "max_spacing_seconds": max(differences) if differences else None,
        "duplicate_timestamps": len(stamps) - len(set(stamps)),
        "missing_fields": {field: sum(row.get(field) is None for row in rows) for field in fields},
    }
    if step:
        summary["gaps_larger_than_interval"] = sum(delta > step for delta in differences)
        summary["irregular_spacing_count"] = sum(delta != step for delta in differences)
        summary["reported_start"] = payload.get("startTimestamp")
        summary["reported_end"] = payload.get("endTimestamp")
    else:
        volumes = [row["timestamp"] for row in rows if row.get("volume") is not None]
        summary["first_volume_at"] = iso(volumes[0]) if volumes else None
    return summary


def make_probes(items, dates):
    probes = []
    for item in items:
        probes.append({"label": f"Guide / {item}", "kind": "guide", "item": item,
                       "url": GUIDE + "?" + urlencode({"id": item})})
        for lookback in ("7d", "1y"):
            probes.append({"label": f"Real-time / {item} / {lookback}", "kind": "timeseries", "item": item,
                           "url": WIKI + "/timeseries?" + urlencode({"id": item, "lookback": lookback})})
    for date in dates:
        epoch = int(date.timestamp())
        for route, interval in (("5m", 300), ("1h", 3600)):
            probes.append({"label": f"Bucket / {route} / {date.date()}", "kind": "bucket",
                           "items": list(items), "timestamp": epoch, "interval_seconds": interval,
                           "url": WIKI + f"/{route}?" + urlencode({"timestamp": epoch})})
    return probes


def run_audit(client, probes):
    results = []
    stopped = None
    for probe in probes:
        response = client.get(probe["url"])
        result = {**probe, **{key: value for key, value in response.items() if key != "payload"}}
        if "error" in response:
            # A 404 is an unavailable probe, not proof of a universal retention boundary.
            result["state"] = "unavailable" if response["status"] == 404 else "error"
        else:
            try:
                result.update(summarize(response["payload"], probe))
            except (KeyError, TypeError, ValueError, OverflowError, OSError) as error:
                result.update(state="schema_error", error=str(error))
        results.append(result)
        print(f"{result['state']:20} {probe['label']} ({'cached' if response['cached'] else 'network'})", flush=True)
        if response["status"] in (403, 429):
            stopped = f"Stopped after HTTP {response['status']}; no retries or further requests."
            break
    return {"generated_at": utc_now(), "planned_probes": len(probes), "completed_probes": len(results),
            "stopped_reason": stopped, "notes": NOTES, "results": results}


def markdown(report):
    lines = ["# GE data coverage audit", "", f"Generated: {report['generated_at']}", "",
             f"Completed probes: {report['completed_probes']}/{report['planned_probes']}", "",
             "Counts are observations for item histories and item IDs for market buckets.", "",
             "| Probe | State | Records | First UTC | Last UTC | Interval (seconds) |",
             "| --- | --- | ---: | --- | --- | ---: |"]
    for result in report["results"]:
        lines.append("| " + " | ".join(str(result.get(key) if result.get(key) is not None else "—")
                                     for key in ("label", "state", "records", "first", "last", "interval_seconds")) + " |")
    if report["stopped_reason"]:
        lines.extend(["", report["stopped_reason"]])
    lines.extend(["", "## Interpretation limits", ""] + ["- " + note for note in report["notes"]])
    lines.extend(["", "See report.json for request URLs, original fetch times, cache use, gaps, missing fields,",
                  "and the sampled items within each historical market bucket.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=int, nargs="+", default=DEFAULT_ITEMS)
    parser.add_argument("--dates", type=date_argument, nargs="+", help="Sparse UTC bucket dates (YYYY-MM-DD)")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "output")
    parser.add_argument("--user-agent", default=USER_AGENT, help="Descriptive application name; contact info is optional")
    parser.add_argument("--offline", action="store_true", help="Only replay previously cached responses")
    args = parser.parse_args(argv)
    if any(item <= 0 for item in args.items) or not args.user_agent.strip():
        parser.error("Item IDs must be positive and User-Agent must not be empty")
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    dates = args.dates or [today - timedelta(days=1)] + [date_argument(value) for value in (
        "2025-01-01", "2023-01-01", "2021-04-01", "2021-02-01"
    )]
    if any(date >= today for date in dates):
        parser.error("Use completed historical UTC dates, before today")
    probes = make_probes(list(dict.fromkeys(args.items)), sorted(set(dates), reverse=True))
    if len(probes) > 40:
        parser.error("This is a small audit, limited to 40 probes; arrange bulk access separately")
    report = run_audit(Client(args.output / "cache", args.user_agent, args.offline), probes)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.output / "report.md").write_text(markdown(report), encoding="utf-8")
    print(f"Reports: {args.output / 'report.json'} and {args.output / 'report.md'}")
    failures = {"error", "schema_error", "timestamp_mismatch"}
    return int(bool(report["stopped_reason"]) or any(result["state"] in failures for result in report["results"]))


if __name__ == "__main__":
    raise SystemExit(main())
