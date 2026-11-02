#!/usr/bin/env python3
"""Export a bounded hourly dataset from the audit cache, without network access."""

import argparse
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlencode

import audit


HOUR = 3600
MAX_HOURS = 7 * 24
SOURCE_CHANGE = int(audit.date_argument("2026-09-30").timestamp())
VALUES = {
    "avg_high_price": "avgHighPrice",
    "avg_low_price": "avgLowPrice",
    "high_price_volume": "highPriceVolume",
    "low_price_volume": "lowPriceVolume",
}
COLUMNS = ["item_id", "interval_start_utc", "interval_end_utc", "record_present",
           *VALUES, "source", "source_regime", "retrieved_at"]
LIMITS = [
    "This is a data-pipeline pilot, not a trained model or profitability backtest.",
    "Blank CSV values are missing, not zero. record_present=0 identifies a missing bucket.",
    "Zero volumes are retained. No prices or volumes are imputed or forward-filled.",
    "Interval end is only a lower bound on availability; actual historical publication delay is unknown.",
    "retrieved_at records when this snapshot was downloaded, not when each bucket first became public.",
    "Historical revisions cannot be reconstructed from these snapshots; this is not point-in-time data.",
    "The documented 2026-09-30 source transition is tagged using midnight UTC as a date-level assumption.",
    "Transaction-side averages are not executable quotes and do not contain order fill-time labels.",
    "Three items over one week are insufficient to establish generalisation across market conditions.",
]


def hourly_epoch(value):
    seconds = audit.timestamp(value)
    if seconds % HOUR:
        raise ValueError("Expected an hour-aligned timestamp")
    return int(seconds)


def validate_value(value, field):
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Invalid numeric value for {field}")
    if field.endswith("volume"):
        if value < 0 or int(value) != value:
            raise ValueError(f"Expected a non-negative integral volume for {field}")
    elif value <= 0:
        raise ValueError(f"Expected a positive price for {field}")


def normalize(snapshot, item):
    """Use reported [start, end) bounds, including leading and trailing missing hours."""
    if snapshot.get("status") != 200 or "error" in snapshot:
        raise ValueError(f"Item {item}: {snapshot.get('error', 'no successful cached response')}")
    payload = snapshot["payload"]
    if str(payload.get("itemId")) != str(item):
        raise ValueError(f"Item {item}: response itemId mismatch")
    if payload.get("timestep") != HOUR:
        raise ValueError(f"Item {item}: expected hourly data; received timestep={payload.get('timestep')}")
    start = hourly_epoch(payload["startTimestamp"])
    end = hourly_epoch(payload["endTimestamp"])
    hours = (end - start) // HOUR
    if not 1 <= hours <= MAX_HOURS:
        raise ValueError(f"Item {item}: expected a bounded window of 1 to {MAX_HOURS} hours")
    fetched = datetime.fromisoformat(snapshot["fetched_at"].replace("Z", "+00:00"))
    if fetched.utcoffset() is None or end > fetched.timestamp():
        raise ValueError(f"Item {item}: snapshot must be retrieved after all reported intervals close")
    by_time = {}
    for observation in audit.observations(payload, "timeseries", item):
        stamp = hourly_epoch(observation["timestamp"])
        if not start <= stamp < end:
            raise ValueError(f"Item {item}: observation outside reported [start, end) bounds")
        if stamp in by_time:
            raise ValueError(f"Item {item}: duplicate observation timestamp")
        for column, field in VALUES.items():
            validate_value(observation[field], column)
        by_time[stamp] = observation
    rows = []
    for stamp in range(start, end, HOUR):
        observed = by_time.get(stamp)
        rows.append({
            "item_id": item,
            "interval_start_utc": audit.iso(stamp),
            "interval_end_utc": audit.iso(stamp + HOUR),
            "record_present": int(observed is not None),
            **{column: observed[field] if observed is not None else None for column, field in VALUES.items()},
            "source": "osrs_wiki_realtime_v2",
            "source_regime": "jagex_all_clients" if stamp >= SOURCE_CHANGE else "runelite_only",
            "retrieved_at": snapshot["fetched_at"],
        })
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    info = {
        "item_id": item, "source_url": snapshot["url"], "retrieved_at": snapshot["fetched_at"],
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "start_inclusive_utc": audit.iso(start), "end_exclusive_utc": audit.iso(end),
        "expected_buckets": hours, "observed_buckets": len(by_time),
        "missing_buckets": [row["interval_start_utc"] for row in rows if not row["record_present"]],
        "null_fields_in_observed_buckets": {
            column: sum(observation[field] is None for observation in by_time.values())
            for column, field in VALUES.items()
        },
        "complete_price_buckets": sum(row["avg_high_price"] is not None and row["avg_low_price"] is not None
                                      for row in rows),
    }
    return rows, info


def build_pilot(cache, items):
    client = audit.Client(cache, offline=True)
    rows, sources = [], []
    for item in items:
        url = audit.WIKI + "/timeseries?" + urlencode({"id": item, "lookback": "7d"})
        item_rows, info = normalize(client.get(url), item)
        rows.extend(item_rows)
        sources.append(info)
    if not any(row["record_present"] for row in rows):
        raise ValueError("No observed data in the selected cached samples")
    rows.sort(key=lambda row: (row["interval_start_utc"], row["item_id"]))
    manifest = {
        "schema_version": 1, "generated_at": audit.utc_now(), "input_cache": str(Path(cache).resolve()),
        "network_requests": 0, "interval_seconds": HOUR, "rows": len(rows),
        "observed_buckets": sum(row["record_present"] for row in rows),
        "missing_buckets": sum(not row["record_present"] for row in rows),
        "complete_price_buckets": sum(info["complete_price_buckets"] for info in sources),
        "sources": sources, "limitations": LIMITS,
    }
    return rows, manifest


def report_text(manifest):
    lines = ["# Hourly data pilot", "", f"Generated: {manifest['generated_at']}", "",
             f"Rows: {manifest['rows']}; observed buckets: {manifest['observed_buckets']}; "
             f"missing buckets: {manifest['missing_buckets']}; "
             f"buckets with both prices: {manifest['complete_price_buckets']}.",
             "Network requests: 0 (cached snapshots only).", "",
             "| Item ID | Start UTC (inclusive) | End UTC (exclusive) | Observed / expected | Both prices |",
             "| --- | --- | --- | ---: | ---: |"]
    for source in manifest["sources"]:
        lines.append(f"| {source['item_id']} | {source['start_inclusive_utc']} | {source['end_exclusive_utc']} | "
                     f"{source['observed_buckets']} / {source['expected_buckets']} | {source['complete_price_buckets']} |")
    lines.extend(["", "## Limits", ""] + ["- " + line for line in manifest["limitations"]])
    lines.extend(["", "hourly.csv contains the normalized data. manifest.json contains missing-bucket lists,",
                  "null counts, source URLs, retrieval times, payload hashes, and the CSV SHA-256.", ""])
    return "\n".join(lines)


def export_pilot(rows, manifest, output):
    # Do not overwrite an existing dataset or its provenance on repeated runs.
    output.mkdir(parents=True, exist_ok=False)
    csv_path = output / "hourly.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    manifest["csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output / "report.md").write_text(report_text(manifest), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path(__file__).resolve().parent / "output"
    parser.add_argument("--cache", type=Path, default=base / "cache")
    parser.add_argument("--output", type=Path, default=base / "pilot")
    parser.add_argument("--items", type=int, nargs="+", default=audit.DEFAULT_ITEMS)
    args = parser.parse_args(argv)
    items = list(dict.fromkeys(args.items))
    if any(item <= 0 for item in items) or len(items) > 20:
        parser.error("Select between 1 and 20 positive item IDs")
    try:
        rows, manifest = build_pilot(args.cache, items)
        export_pilot(rows, manifest, args.output)
    except (KeyError, TypeError, ValueError, OSError, OverflowError) as error:
        print(f"Pilot failed: {error}", file=sys.stderr)
        return 1
    print(f"Exported {manifest['rows']} hourly rows for {len(items)} items; "
          f"{manifest['missing_buckets']} missing buckets; "
          f"{manifest['complete_price_buckets']} buckets with both prices; no network requests.")
    print(f"Dataset: {args.output / 'hourly.csv'}")
    print(f"Report: {args.output / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
