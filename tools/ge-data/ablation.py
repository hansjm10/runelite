#!/usr/bin/env python3
"""Compare unchanged Chronos-2 with/without volume on a fresh holdout or explicit retrospective test."""

import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlencode

import audit
import benchmark as bench
import chronos_backend
import expanded
import pilot


VARIANTS = {"prices_only": False, "prices_and_volume": True}
LIMITATIONS = [
    "This is a predeclared new calendar holdout, not forecasts saved before their outcomes occurred.",
    "Historical snapshots may contain revisions; actual publication delays are unknown. The one-hour gap is assumed.",
    "Both variants predict both price sides jointly. Only the two historical volume covariates are removed.",
    "Missing prices/volumes remain missing; real zero volume remains zero. No future covariates are supplied.",
    "All four methods share one valid-observation mask. Invalid model outputs fail the whole comparison.",
    "Earlier holdout outcomes enter later contexts only after the publication gap. Attention groups isolate origins/items.",
    "One 48-hour holdout cannot establish statistical significance, calibrated confidence, or trading profitability.",
    "No training, parameter tuning, trade execution, fill probabilities, fees, or GP profit are modelled.",
]


def settings():
    return {"holdout_hours": bench.HOLDOUT_HOURS, "gap_hours": bench.GAP_HOURS,
            "max_context_hours": bench.CONTEXT_HOURS, "quantiles": list(bench.QUANTILES),
            "model_id": chronos_backend.MODEL_ID, "model_revision": chronos_backend.MODEL_REVISION,
            "variants": VARIANTS, "primary_metric": "macro_wape_pct", "cross_learning": False,
            "refit": False}


def make_plan(dataset, now):
    if now.utcoffset() is None:
        raise ValueError("Expected a timezone-aware creation time")
    items, checksum = bench.load_dataset(dataset)
    manifest = json.loads((Path(dataset) / "manifest.json").read_text(encoding="utf-8"))
    cohort = manifest["cohort"]
    expanded.validate_cohort(cohort)
    previous_end = max(rows[-1]["timestamp"] for rows in items.values()) + pilot.HOUR
    start = max((int(now.timestamp()) // pilot.HOUR + 1) * pilot.HOUR, previous_end)
    end = start + bench.HOLDOUT_HOURS * pilot.HOUR
    return {"schema_version": 1, "created_at": now.isoformat(), "settings": settings(),
            "previous_dataset_sha256": checksum, "previous_end_exclusive_utc": audit.iso(previous_end),
            "test_start_utc": audit.iso(start), "test_end_exclusive_utc": audit.iso(end),
            "collect_not_before_utc": audit.iso(end + bench.GAP_HOURS * pilot.HOUR),
            "cohort": cohort, "cohort_sha256": expanded.digest(cohort)}


def validate_plan(plan):
    if plan.get("schema_version") != 1 or plan["settings"] != settings():
        raise ValueError("Plan settings differ from the fixed experiment; do not silently change its protocol")
    ids = expanded.validate_cohort(plan["cohort"])
    if expanded.digest(plan["cohort"]) != plan["cohort_sha256"]:
        raise ValueError("Plan cohort checksum mismatch")
    created = datetime.fromisoformat(plan["created_at"])
    start, end, ready, previous = (bench.parse_time(plan[key]) for key in
                                  ("test_start_utc", "test_end_exclusive_utc", "collect_not_before_utc",
                                   "previous_end_exclusive_utc"))
    if created.utcoffset() is None or start <= created.timestamp() or start < previous:
        raise ValueError("Holdout must begin after plan creation and outside the previously inspected dataset")
    if end - start != bench.HOLDOUT_HOURS * pilot.HOUR or ready != end + bench.GAP_HOURS * pilot.HOUR:
        raise ValueError("Invalid fixed holdout/publication window")
    if plan["cohort"]["selection_end_exclusive"] > start - bench.GAP_HOURS * pilot.HOUR:
        raise ValueError("Cohort selection overlaps the new holdout")
    return ids, start, end, ready


def require_ready(plan, now):
    _, _, _, ready = validate_plan(plan)
    if now.utcoffset() is None or now.timestamp() < ready:
        raise ValueError(f"Fresh holdout is not ready; collect on or after {audit.iso(ready)}. No old holdout substitution.")


def collect_dataset(client, plan, now):
    """At most one seven-day request per frozen item; never shift the planned target window."""
    require_ready(plan, now)
    ids, test_start, test_end, ready = validate_plan(plan)
    all_rows, sources = [], []
    for index, item in enumerate(ids, 1):
        url = audit.WIKI + "/timeseries?" + urlencode({"id": item, "lookback": "7d"})
        record = expanded.response(client, url)
        rows, info = pilot.normalize(record, item)
        source_start = bench.parse_time(info["start_inclusive_utc"])
        source_end = bench.parse_time(info["end_exclusive_utc"])
        if (datetime.fromisoformat(info["retrieved_at"]).timestamp() < ready or source_end < test_end
                or source_start > test_start - 49 * pilot.HOUR):
            raise ValueError("Snapshot does not cover the fixed holdout and 49 pre-test hours; preserve the plan, do not move it")
        all_rows.extend(rows)
        sources.append(info)
        print(f"Collected {index}/{len(ids)} fixed-cohort items (cached={record['cached']})", flush=True)
    start = max(test_start - (bench.CONTEXT_HOURS + bench.GAP_HOURS) * pilot.HOUR,
                max(bench.parse_time(source["start_inclusive_utc"]) for source in sources))
    first, last = audit.iso(start), audit.iso(test_end)
    rows = sorted((row for row in all_rows if first <= row["interval_start_utc"] < last),
                  key=lambda row: (row["interval_start_utc"], row["item_id"]))
    manifest = {"schema_version": 1, "generated_at": audit.utc_now(), "interval_seconds": pilot.HOUR,
                "rows": len(rows), "start_inclusive_utc": first, "end_exclusive_utc": last,
                "observed_buckets": sum(row["record_present"] for row in rows),
                "missing_buckets": sum(not row["record_present"] for row in rows),
                "complete_price_buckets": sum(all(row[field] is not None for field in bench.TARGETS) for row in rows),
                "cohort": plan["cohort"], "cohort_sha256": plan["cohort_sha256"],
                "plan_sha256": expanded.digest(plan), "sources": sources, "limitations": LIMITATIONS}
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


def load_inputs(dataset, plan):
    ids, start, end, _ = validate_plan(plan)
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("plan_sha256") != expanded.digest(plan) or manifest.get("cohort_sha256") != plan["cohort_sha256"]:
        raise ValueError("Dataset is not bound to this frozen plan/cohort")
    items, checksum = bench.load_dataset(dataset)
    if sorted(items) != sorted(ids):
        raise ValueError("Dataset changed the frozen item universe")
    cases = bench.make_inputs(items)
    if min(case.target_start for case in cases) != start or max(case.target_start for case in cases) + pilot.HOUR != end:
        raise ValueError("Dataset does not match the fixed fresh holdout; old periods cannot be reused")
    return items, cases, checksum, manifest


def compare(items, cases, forecasts):
    if set(forecasts) != set(VARIANTS):
        raise ValueError("Both forecast variants are required")
    results, combined, common_skipped = {}, [], None
    for variant in VARIANTS:
        records, skipped = bench.evaluate(items, cases, forecasts[variant])
        if common_skipped is not None and skipped != common_skipped:
            raise ValueError("Variants do not share the same evaluation mask")
        common_skipped = skipped
        results[variant] = {"metrics": bench.metrics(records), "weekly_metrics": bench.weekly_metrics(records)}
        for row in records:
            if row["model"] == "chronos2":
                combined.append({**row, "model": variant})
            elif variant == "prices_only":
                combined.append(row)
    price_wape, volume_wape = (results[name]["metrics"]["macro_wape_pct"]["chronos2"] for name in VARIANTS)
    return {"variants": results, "skipped": common_skipped,
            "volume_wape_improvement_percentage_points": price_wape - volume_wape,
            "volume_relative_wape_improvement_pct": 100 * (1 - volume_wape / price_wape) if price_wape else None}, combined


def report_text(result):
    plan = result["plan"]
    lines = ["# Price-only versus price-plus-volume", "", f"Generated: {result['generated_at']}", "",
             f"Evaluation mode: {result['evaluation_mode']}.", "",
             f"Fixed holdout: {plan['test_start_utc']} to {plan['test_end_exclusive_utc']} (end exclusive).",
             "Same pretrained weights and two price targets; no fine-tuning.", "",
             "| Variant | Macro WAPE (%) |", "| --- | ---: |"]
    baseline = result["variants"]["prices_only"]["metrics"]["macro_wape_pct"]
    for model in ("persistence", "seasonal_24h"):
        lines.append(f"| {model} | {baseline[model]:.6f} |")
    for variant, scores in result["variants"].items():
        lines.append(f"| {variant} | {scores['metrics']['macro_wape_pct']['chronos2']:.6f} |")
    lines.extend(["", "Positive improvement means volume helped; negative means it hurt.",
                  f"Volume improvement: {result['volume_wape_improvement_percentage_points']:.6f} percentage points.",
                  f"Skipped outcomes: {len(result['skipped'])}, identical for all methods.", "",
                  "See metrics.json for per-series errors, quantile losses, coverage and partial-week breakdowns.",
                  "Partial weeks are not independent full-week tests.", "", "## Limits", ""])
    return "\n".join(lines + ["- " + note for note in result["limitations"]] + [""])


def infer_comparison(output, plan, model_cache, loaded):
    if output.exists():
        raise ValueError("Results already exist; preserve them rather than rerun/tune this holdout")
    items, cases, checksum, manifest = loaded
    # One local checkpoint instance for both variants; no downloads, training, or remote model code.
    forecaster = chronos_backend.ChronosForecaster(model_cache, offline=True)
    forecasts, elapsed = {}, {}
    for name, include_volume in VARIANTS.items():
        started = time.monotonic()
        forecasts[name] = forecaster.predict(cases, include_volume=include_volume)
        elapsed[name] = time.monotonic() - started
    comparison, records = compare(items, cases, forecasts)
    mode = plan.get("evaluation_mode", "predeclared_holdout")
    limitations = LIMITATIONS if mode == "predeclared_holdout" else [
        "Retrospective exploratory comparison on a previously inspected historical holdout; not fresh independent validation.",
        *LIMITATIONS[1:],
    ]
    result = {"generated_at": audit.utc_now(), "evaluation_mode": mode,
              "plan": plan, "plan_sha256": expanded.digest(plan),
              "dataset_sha256": checksum, "dataset_manifest": manifest, "model": forecaster.provenance(),
              "inference_seconds": elapsed, "limitations": limitations, **comparison}
    output.mkdir(parents=True, exist_ok=False)
    with (output / "forecasts.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    (output / "metrics.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output / "report.md").write_text(report_text(result), encoding="utf-8")
    return result


def run_comparison(root, plan, model_cache, now):
    if (root / "results").exists():
        raise ValueError("Results already exist; preserve them rather than rerun/tune this holdout")
    require_ready(plan, now)
    return infer_comparison(root / "results", plan, model_cache, load_inputs(root / "dataset", plan))


def run_retrospective(dataset, root, model_cache, now):
    """Reuse historical observations without changing their dates or the separate fresh-holdout plan."""
    if root.exists():
        raise ValueError("Retrospective output directory already exists; choose a separate unused directory")
    items, checksum = bench.load_dataset(dataset)
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    expanded.validate_cohort(manifest["cohort"])
    cases = bench.make_inputs(items)
    end = max(case.target_start for case in cases) + pilot.HOUR
    if now.utcoffset() is None or end > now.timestamp():
        raise ValueError("Retrospective targets must already have closed")
    experiment = {"schema_version": 1, "evaluation_mode": "retrospective_exploratory",
                  "created_at": now.isoformat(), "settings": settings(),
                  "source_dataset": str(dataset.resolve()), "source_dataset_sha256": checksum,
                  "test_start_utc": audit.iso(min(case.target_start for case in cases)),
                  "test_end_exclusive_utc": audit.iso(end),
                  "cohort": manifest["cohort"], "cohort_sha256": manifest["cohort_sha256"]}
    return infer_comparison(root / "results", experiment, model_cache, (items, cases, checksum, manifest))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path(__file__).resolve().parent / "output"
    parser.add_argument("command", choices=("init", "collect", "run", "retrospective"))
    parser.add_argument("--root", type=Path, help="Separate experiment directory; retrospective uses its own default")
    parser.add_argument("--source-dataset", type=Path, default=base / "expanded" / "dataset")
    parser.add_argument("--model-cache", type=Path, default=base / "models")
    parser.add_argument("--cache", type=Path, help="Market-response cache; defaults to ROOT/cache. Use a new path to preserve stale snapshots.")
    parser.add_argument("--offline", action="store_true", help="Require cached market responses; model inference is always offline")
    args = parser.parse_args(argv)
    if args.root is None:
        args.root = base / ("volume-ablation-retrospective" if args.command == "retrospective" else "volume-ablation")
    try:
        plan_path = args.root / "plan.json"
        now = datetime.now(audit.UTC)
        if args.command == "init":
            if plan_path.exists():
                raise ValueError("Plan already exists; preserve the predeclared window")
            plan = make_plan(args.source_dataset, now)
            validate_plan(plan)
            args.root.mkdir(parents=True, exist_ok=True)
            with plan_path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(plan, indent=2, allow_nan=False) + "\n")
            print(f"Frozen {len(plan['cohort']['items'])} items; collect on or after {plan['collect_not_before_utc']}")
            print(f"Plan: {plan_path}")
        elif args.command == "retrospective":
            result = run_retrospective(args.source_dataset, args.root, args.model_cache, now)
            print("Retrospective exploratory comparison; not a fresh independent holdout.")
            print(f"Volume WAPE improvement (percentage points): {result['volume_wape_improvement_percentage_points']:.6f}")
            print(f"Report: {args.root / 'results' / 'report.md'}")
        else:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            require_ready(plan, now)
            if args.command == "collect":
                output = args.root / "dataset"
                if output.exists():
                    raise ValueError("Dataset already exists; preserve the first collected snapshots")
                client = audit.Client(args.cache if args.cache is not None else args.root / "cache", offline=args.offline)
                rows, manifest = collect_dataset(client, plan, now)
                export_dataset(rows, manifest, output)
                print(f"Collected fixed holdout: {output}")
            else:
                result = run_comparison(args.root, plan, args.model_cache, now)
                print(f"Volume WAPE improvement (percentage points): {result['volume_wape_improvement_percentage_points']:.6f}")
                print(f"Report: {args.root / 'results' / 'report.md'}")
    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError, OverflowError) as error:
        print(f"Volume comparison blocked: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
