#!/usr/bin/env python3
"""Freeze a pre-test item cohort, collect a bounded hourly sample, or capture one new bucket."""

import argparse
from collections import defaultdict
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import statistics
import sys
from urllib.parse import urlencode

import audit
import pilot


EXCLUDED_SMOKE_ITEMS = (4151, 561, 20997)
SELECTION_SEED = "ge-hourly-cohort-v1"


def digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def response(client, url):
    record = client.get(url)
    if record.get("status") != 200 or "payload" not in record or "error" in record:
        raise ValueError(f"{url}: {record.get('error', 'unsuccessful response')}")
    return record


def bucket_data(record, expected):
    data = record["payload"]
    if audit.timestamp(data["timestamp"]) != expected or not isinstance(data["data"], dict):
        raise ValueError("Market bucket did not match its requested timestamp/schema")
    return data["data"]


def select_items(buckets, count):
    """Use only four early hourly buckets; stratify by price and within-band liquidity."""
    candidates = defaultdict(list)
    for data in buckets:
        for item_text, values in data.items():
            item = int(item_text)
            if item <= 0 or item in EXCLUDED_SMOKE_ITEMS:
                continue
            if any(values.get(field) is None for field in pilot.VALUES.values()):
                continue
            for column, field in pilot.VALUES.items():
                pilot.validate_value(values[field], column)
            price = (values["avgHighPrice"] + values["avgLowPrice"]) / 2
            volume = values["highPriceVolume"] + values["lowPriceVolume"]
            candidates[item].append((price, volume))
    price_groups = defaultdict(list)
    for item, values in candidates.items():
        # Require presence in at least three snapshots and some activity on the selection day.
        volume = sum(value[1] for value in values)
        if len(values) < 3 or volume < 20:
            continue
        price = statistics.median(value[0] for value in values)
        band = sum(price >= boundary for boundary in (1000, 100000, 10000000))
        price_groups[band].append({"item_id": item, "selection_price_gp": price,
                                   "sampled_volume": volume, "price_band": band})
    strata = defaultdict(list)
    for band, group in sorted(price_groups.items()):
        group.sort(key=lambda item: (item["sampled_volume"], item["item_id"]))
        for index, item in enumerate(group):
            tier = min(2, 3 * index // len(group))
            item["liquidity_tier"] = tier
            strata[(band, tier)].append(item)
    for group in strata.values():
        group.sort(key=lambda item: hashlib.sha256(f"{SELECTION_SEED}:{item['item_id']}".encode()).hexdigest())
    chosen = []
    while len(chosen) < count:
        added = False
        for key in sorted(strata):
            if strata[key] and len(chosen) < count:
                chosen.append(strata[key].pop(0))
                added = True
        if not added:
            raise ValueError(f"Only {len(chosen)} eligible pre-test items; requested {count}")
    return chosen


def freeze_cohort(client, count):
    reference = response(client, audit.WIKI + "/timeseries?id=4151&lookback=7d")
    payload = reference["payload"]
    if payload.get("timestep") != pilot.HOUR:
        raise ValueError("Seven-day route no longer returns hourly data; refusing to substitute resolution")
    start = pilot.hourly_epoch(payload["startTimestamp"])
    end = pilot.hourly_epoch(payload["endTimestamp"])
    if end - start != 168 * pilot.HOUR:
        raise ValueError("Expected a seven-day reference window")
    sources, buckets = [], []
    for offset in (0, 6, 12, 18):
        stamp = start + offset * pilot.HOUR
        url = audit.WIKI + "/1h?" + urlencode({"timestamp": stamp})
        record = response(client, url)
        buckets.append(bucket_data(record, stamp))
        sources.append({"url": url, "timestamp": stamp, "retrieved_at": record["fetched_at"],
                        "payload_sha256": digest(record["payload"])})
    items = select_items(buckets, count)
    return {
        "schema_version": 1, "created_at": audit.utc_now(), "algorithm": SELECTION_SEED,
        "anchor_start": start, "anchor_end": end,
        "selection_end_exclusive": start + 19 * pilot.HOUR,
        "excluded_smoke_items": EXCLUDED_SMOKE_ITEMS, "selection_sources": sources,
        "items": items,
        "limits": ["Selection uses four hourly snapshots, not complete daily volume.",
                   "Historical selection data was downloaded retrospectively; revisions are unknown.",
                   "This expands the item universe, not the length or independence of the test period."],
    }


def validate_cohort(cohort):
    if cohort.get("schema_version") != 1 or cohort.get("algorithm") != SELECTION_SEED:
        raise ValueError("Unsupported cohort manifest")
    ids = [item["item_id"] for item in cohort["items"]]
    if not 1 <= len(ids) <= 100 or len(set(ids)) != len(ids) or any(item <= 0 for item in ids):
        raise ValueError("Expected 1–100 unique positive item IDs")
    start, end = (pilot.hourly_epoch(cohort[key]) for key in ("anchor_start", "anchor_end"))
    selection_end = pilot.hourly_epoch(cohort["selection_end_exclusive"])
    if end - start != 168 * pilot.HOUR or not start < selection_end <= end - 49 * pilot.HOUR:
        raise ValueError("Cohort selection does not precede the test window")
    return ids


def collect_dataset(client, cohort):
    ids = validate_cohort(cohort)
    all_rows, sources = [], []
    for index, item in enumerate(ids, 1):
        url = audit.WIKI + "/timeseries?" + urlencode({"id": item, "lookback": "7d"})
        record = response(client, url)
        rows, info = pilot.normalize(record, item)
        all_rows.extend(rows)
        sources.append(info)
        print(f"Collected {index}/{len(ids)} items (cached={record['cached']})", flush=True)
    # Requests may straddle an hour boundary. Use their shared historical window, never shift rows.
    start = max(cohort["anchor_start"], max(int(datetime.fromisoformat(info["start_inclusive_utc"]).timestamp()) for info in sources))
    end = min(cohort["anchor_end"], min(int(datetime.fromisoformat(info["end_exclusive_utc"]).timestamp()) for info in sources))
    if end - start < 97 * pilot.HOUR or cohort["selection_end_exclusive"] > end - 49 * pilot.HOUR:
        raise ValueError("Insufficient shared hourly history after cohort selection")
    first, last = audit.iso(start), audit.iso(end)
    rows = sorted((row for row in all_rows if first <= row["interval_start_utc"] < last),
                  key=lambda row: (row["interval_start_utc"], row["item_id"]))
    coverage = []
    for item in ids:
        selected = [row for row in rows if row["item_id"] == item]
        coverage.append({"item_id": item, "expected_buckets": len(selected),
                         "observed_buckets": sum(row["record_present"] for row in selected),
                         "missing_buckets": [row["interval_start_utc"] for row in selected if not row["record_present"]],
                         "null_fields_in_observed_buckets": {
                             field: sum(row["record_present"] and row[field] is None for row in selected)
                             for field in pilot.VALUES}})
    manifest = {"schema_version": 1, "generated_at": audit.utc_now(), "interval_seconds": pilot.HOUR,
                "rows": len(rows), "start_inclusive_utc": first, "end_exclusive_utc": last,
                "cohort": cohort, "cohort_sha256": digest(cohort), "sources": sources, "coverage": coverage,
                "missing_buckets": sum(not row["record_present"] for row in rows),
                "complete_price_buckets": sum(row["avg_high_price"] is not None and row["avg_low_price"] is not None for row in rows),
                "limitations": cohort["limits"] + pilot.LIMITS[:-1]}
    return rows, manifest


def export_dataset(rows, manifest, output):
    output.mkdir(parents=True, exist_ok=False)
    path = output / "hourly.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=pilot.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    manifest["csv_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# Expanded hourly cohort", "", f"Items: {len(manifest['cohort']['items'])}; rows: {len(rows)}.",
             f"Window: {manifest['start_inclusive_utc']} to {manifest['end_exclusive_utc']} (end exclusive).",
             f"Missing buckets: {manifest['missing_buckets']}; both price sides: {manifest['complete_price_buckets']}.", "",
             "The 30-day API route was observed to return six-hour data. This dataset remains hourly",
             "and spans only the shared seven-day lookback, not 30 days. No bulk backfill was run.", "",
             "Cohort selection used only early pre-test snapshots. The three original smoke-test items",
             "were excluded. This is a broader cross-item test, not an independent future-period test.", "",
             "See manifest.json for source hashes, cohort rules, and per-item gaps/null counts.", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def capture(client, cohort, output, now):
    """One immutable all-item request per hourly invocation, with one hour of publication slack."""
    ids = validate_cohort(cohort)
    stamp = int(now.timestamp()) // pilot.HOUR * pilot.HOUR - 2 * pilot.HOUR
    if stamp < cohort["selection_end_exclusive"]:
        raise ValueError("Capture time predates the frozen cohort")
    cohort_hash = digest(cohort)
    folder = output / cohort_hash
    path = folder / f"{stamp}.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing["cohort_sha256"] != cohort_hash or existing["interval_start"] != stamp:
            raise ValueError("Existing capture does not match its cohort/hour")
        return path
    url = audit.WIKI + "/1h?" + urlencode({"timestamp": stamp})
    record = response(client, url)
    values = bucket_data(record, stamp)
    rows = {}
    for item in ids:
        observation = values.get(str(item))
        if observation is not None:
            for column, field in pilot.VALUES.items():
                if field not in observation:
                    raise ValueError("Incomplete captured bucket schema")
                pilot.validate_value(observation[field], column)
        rows[str(item)] = observation
    saved = {"schema_version": 1, "cohort_sha256": cohort_hash, "interval_start": stamp,
             "interval_end": stamp + pilot.HOUR, "retrieved_at": record["fetched_at"], "url": url,
             "payload_sha256": digest(record["payload"]), "items": rows,
             "note": "First retrieved snapshot; absent items are unknown, not zero volume. No automatic catch-up."}
    folder.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(saved, indent=2, allow_nan=False) + "\n")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "capture"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent / "output" / "expanded")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 100:
        parser.error("Select 1–100 items; this tool is not a bulk historical crawler")
    try:
        root = args.root
        cohort_path = root / "cohort.json"
        client = audit.Client(root / "cache", offline=args.offline)
        if args.command == "collect":
            if (root / "dataset").exists():
                raise ValueError("Dataset already exists; preserve it and use capture for new hourly observations")
            if cohort_path.exists():
                cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
                if len(cohort["items"]) != args.count:
                    raise ValueError("Count differs from the frozen cohort; use a new root for a different experiment")
            else:
                cohort = freeze_cohort(client, args.count)
                root.mkdir(parents=True, exist_ok=True)
                with cohort_path.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(cohort, indent=2, allow_nan=False) + "\n")
            rows, manifest = collect_dataset(client, cohort)
            export_dataset(rows, manifest, root / "dataset")
            print(f"Dataset: {root / 'dataset'} ({len(rows)} hourly rows)")
        else:
            cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
            path = capture(client, cohort, root / "forward", datetime.now(audit.UTC))
            print(f"Captured hourly observation: {path}")
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as error:
        print(f"Expanded data collection failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
