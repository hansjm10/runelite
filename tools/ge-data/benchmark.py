#!/usr/bin/env python3
"""Chronological, paired price-forecast benchmark; not a trading backtest."""

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

import audit
import pilot


TARGETS = ("avg_high_price", "avg_low_price")
HOLDOUT_HOURS = 48
GAP_HOURS = 1
CONTEXT_HOURS = 120
QUANTILES = (0.1, 0.5, 0.9)


@dataclass
class ForecastInput:
    item_id: int
    target_start: int
    context: list


def parse_time(value):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.utcoffset() is None:
        raise ValueError("Expected a timezone-aware timestamp")
    return pilot.hourly_epoch(date.timestamp())


def load_dataset(directory, holdout_hours=HOLDOUT_HOURS):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    path = directory / "hourly.csv"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest.get("schema_version") != 1 or manifest.get("interval_seconds") != pilot.HOUR:
        raise ValueError("Expected a version-1 hourly pilot dataset")
    if digest != manifest["csv_sha256"]:
        raise ValueError("Dataset checksum does not match its manifest")
    items = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for record in csv.DictReader(stream):
            item = int(record["item_id"])
            stamp = parse_time(record["interval_start_utc"])
            if parse_time(record["interval_end_utc"]) != stamp + pilot.HOUR:
                raise ValueError("Dataset contains a non-hourly interval")
            if record["record_present"] not in ("0", "1"):
                raise ValueError("Invalid presence flag")
            row: dict = {"timestamp": stamp}
            for field in pilot.VALUES:
                value = float(record[field]) if record[field] else None
                pilot.validate_value(value, field)
                if record["record_present"] == "0" and value is not None:
                    raise ValueError("Missing bucket contains observed values")
                row[field] = value
            items.setdefault(item, []).append(row)
    if not items or sum(map(len, items.values())) != manifest["rows"]:
        raise ValueError("Dataset row count does not match its manifest")
    grids = []
    for rows in items.values():
        rows.sort(key=lambda row: row["timestamp"])
        grid = [row["timestamp"] for row in rows]
        if any(right - left != pilot.HOUR for left, right in zip(grid, grid[1:])):
            raise ValueError("Expected a dense, non-duplicated hourly grid with explicit missing rows")
        grids.append(grid)
    if any(grid != grids[0] for grid in grids[1:]):
        raise ValueError("This small benchmark requires identical time windows across items")
    if holdout_hours < 24 or len(grids[0]) < holdout_hours + 49:
        raise ValueError("Need a holdout of at least 24 hours and at least 49 pre-holdout hours")
    if "cohort" in manifest:
        cohort = manifest["cohort"]
        cohort_hash = hashlib.sha256(json.dumps(cohort, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if cohort_hash != manifest.get("cohort_sha256"):
            raise ValueError("Cohort checksum does not match its manifest")
        if sorted(item["item_id"] for item in cohort["items"]) != sorted(items):
            raise ValueError("Dataset item universe differs from its frozen cohort")
        if cohort["selection_end_exclusive"] > grids[0][-holdout_hours] - GAP_HOURS * pilot.HOUR:
            raise ValueError("Cohort selection overlaps the test window or publication gap")
    return items, digest


def make_inputs(items, holdout_hours=HOLDOUT_HOURS):
    """At target T, context ends at T-1h; the T-1h bucket itself is withheld."""
    inputs = []
    for item, rows in sorted(items.items()):
        for index in range(len(rows) - holdout_hours, len(rows)):
            stop = index - GAP_HOURS
            context = [dict(row) for row in rows[max(0, stop - CONTEXT_HOURS):stop]]
            inputs.append(ForecastInput(item, rows[index]["timestamp"], context))
    return inputs


def pinball(actual, prediction, quantile):
    error = actual - prediction
    return max(quantile * error, (quantile - 1) * error)


def evaluate(items, inputs, predictions):
    """All models are scored on exactly the same item/target/hour observations."""
    if len(predictions) != len(inputs):
        raise ValueError("Model returned the wrong number of forecasts")
    observations = {item: {row["timestamp"]: row for row in rows} for item, rows in items.items()}
    records, skipped = [], []
    for case, forecast in zip(inputs, predictions):
        for target in TARGETS:
            quantiles = forecast[target]
            if len(quantiles) != 3 or any(not math.isfinite(value) for value in quantiles):
                raise ValueError("Model returned invalid quantiles")
            if quantiles != sorted(quantiles):
                raise ValueError("Model returned crossed quantiles")
            actual = observations[case.item_id][case.target_start][target]
            recent = [row[target] for row in case.context if row[target] is not None]
            persistent = recent[-1] if recent else None
            seasonal = observations[case.item_id][case.target_start - 24 * pilot.HOUR][target]
            reason = ("missing_actual" if actual is None else
                      "missing_persistence" if persistent is None else
                      "missing_seasonal" if seasonal is None else None)
            if reason:
                skipped.append({"item_id": case.item_id, "target": target,
                                "target_start_utc": audit.iso(case.target_start), "reason": reason})
                continue
            assert actual is not None and persistent is not None and seasonal is not None
            common = {"item_id": case.item_id, "target": target, "actual": actual,
                      "target_start_utc": audit.iso(case.target_start),
                      "context_end_exclusive_utc": audit.iso(case.context[-1]["timestamp"] + pilot.HOUR)}
            for model, point in (("persistence", persistent), ("seasonal_24h", seasonal),
                                 ("chronos2", quantiles[1])):
                records.append({**common, "model": model, "prediction": point,
                                "reference_price": persistent,
                                "actual_change_bps": 10000 * (actual / persistent - 1),
                                "predicted_change_bps": 10000 * (point / persistent - 1),
                                "q10": quantiles[0] if model == "chronos2" else None,
                                "q90": quantiles[2] if model == "chronos2" else None})
    if not records:
        raise ValueError("No common observations available for evaluation")
    return records, skipped


def metrics(records):
    groups = {}
    for record in records:
        groups.setdefault((record["item_id"], record["target"], record["model"]), []).append(record)
    results = []
    for (item, target, model), rows in sorted(groups.items()):
        errors = [row["prediction"] - row["actual"] for row in rows]
        scale = sum(abs(row["actual"]) for row in rows)
        result = {"item_id": item, "target": target, "model": model, "n": len(rows),
                  "mae_gp": statistics.mean(abs(error) for error in errors),
                  "rmse_gp": math.sqrt(statistics.mean(error ** 2 for error in errors)),
                  "wape_pct": 100 * sum(abs(error) for error in errors) / scale}
        if all("actual_change_bps" in row for row in rows):
            result["change_mae_bps"] = statistics.mean(abs(row["predicted_change_bps"] - row["actual_change_bps"]) for row in rows)
            result["direction_accuracy_pct"] = 100 * statistics.mean(
                ((row["predicted_change_bps"] > 0) - (row["predicted_change_bps"] < 0)) ==
                ((row["actual_change_bps"] > 0) - (row["actual_change_bps"] < 0)) for row in rows)
        if model == "chronos2":
            result["coverage_80_pct"] = 100 * statistics.mean(row["q10"] <= row["actual"] <= row["q90"] for row in rows)
            result["interval_width_pct"] = 100 * sum(row["q90"] - row["q10"] for row in rows) / scale
            result["weighted_quantile_loss_pct"] = 200 * sum(
                pinball(row["actual"], value, q)
                for row in rows for q, value in zip(QUANTILES, (row["q10"], row["prediction"], row["q90"]))
            ) / (len(QUANTILES) * scale)
        results.append(result)
    persistence = {(row["item_id"], row["target"]): row["mae_gp"] for row in results if row["model"] == "persistence"}
    for row in results:
        baseline = persistence[(row["item_id"], row["target"])]
        row["mae_skill_vs_persistence"] = 1 - row["mae_gp"] / baseline if baseline else None
    macro = {model: statistics.mean(row["wape_pct"] for row in results if row["model"] == model)
             for model in ("persistence", "seasonal_24h", "chronos2")}
    return {"per_series": results, "macro_wape_pct": macro}


def weekly_metrics(records):
    groups = {}
    for row in records:
        date = datetime.fromisoformat(row["target_start_utc"])
        monday = (date - timedelta(days=date.weekday())).date().isoformat()
        groups.setdefault(monday, []).append(row)
    return [{"week_start_utc": week, "hours_observed": len({row["target_start_utc"] for row in rows}),
             "macro_wape_pct": metrics(rows)["macro_wape_pct"]} for week, rows in sorted(groups.items())]


def report_text(result):
    holdout = result["protocol"]["holdout_hours"]
    lines = ["# Chronos-2 forecasting benchmark", "", f"Generated: {result['generated_at']}", "",
             "Zero-shot inference only. No fine-tuning, trade execution, or simulated GP profit.", "",
             f"Test: final {holdout} hours; {GAP_HOURS}-hour publication-gap assumption; "
             f"up to {CONTEXT_HOURS} historical hours per forecast.",
             f"Skipped item/side/hour observations: {len(result['skipped'])} (same mask for every model).", "",
             "## Macro average WAPE across item/price-side series", "",
             "| Model | WAPE (%) |", "| --- | ---: |"]
    for model, value in result["metrics"]["macro_wape_pct"].items():
        lines.append(f"| {model} | {value:.4f} |")
    lines.extend(["", "## Per-series results", "",
                  "| Item | Side | Model | N | MAE (GP) | WAPE (%) | 80% coverage (%) |",
                  "| --- | --- | --- | ---: | ---: | ---: | ---: |"])
    for row in result["metrics"]["per_series"]:
        coverage = f"{row['coverage_80_pct']:.2f}" if "coverage_80_pct" in row else "—"
        lines.append(f"| {row['item_id']} | {row['target']} | {row['model']} | {row['n']} | "
                     f"{row['mae_gp']:.3f} | {row['wape_pct']:.4f} | {coverage} |")
    lines.extend(["", "## Calendar-week breakdown (partial weeks are not independent full-week tests)", "",
                  "| Week starting UTC | Hours | Persistence WAPE (%) | Seasonal WAPE (%) | Chronos WAPE (%) |",
                  "| --- | ---: | ---: | ---: | ---: |"])
    for week in result.get("weekly_metrics", []):
        scores = week["macro_wape_pct"]
        lines.append(f"| {week['week_start_utc']} | {week['hours_observed']} | {scores['persistence']:.4f} | "
                     f"{scores['seasonal_24h']:.4f} | {scores['chronos2']:.4f} |")
    lines.extend(["", "## Limits", ""] + ["- " + note for note in result["limitations"]])
    lines.extend(["", "See metrics.json for provenance, settings, losses, widths and skipped observations;",
                  "forecasts.csv contains paired forecasts and their actual outcomes.", ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path(__file__).resolve().parent / "output"
    parser.add_argument("--dataset", type=Path, default=base / "pilot")
    parser.add_argument("--output", type=Path, default=base / "benchmark")
    parser.add_argument("--model-cache", type=Path, default=base / "models")
    parser.add_argument("--offline", action="store_true", help="Require previously downloaded model weights")
    parser.add_argument("--holdout-hours", type=int, default=HOLDOUT_HOURS, help="Final test window; choose before inspecting outcomes")
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise ValueError("Output already exists; choose a new directory to preserve prior results")
        items, digest = load_dataset(args.dataset, args.holdout_hours)
        inputs = make_inputs(items, args.holdout_hours)
        from chronos_backend import ChronosForecaster
        forecaster = ChronosForecaster(args.model_cache, offline=args.offline)
        started = time.monotonic()
        predictions = forecaster.predict(inputs)
        elapsed = time.monotonic() - started
        records, skipped = evaluate(items, inputs, predictions)
        result = {
            "generated_at": audit.utc_now(), "dataset_sha256": digest,
            "dataset_manifest": json.loads((args.dataset / "manifest.json").read_text(encoding="utf-8")),
            "model": forecaster.provenance(), "inference_seconds": elapsed,
            "protocol": {"holdout_hours": args.holdout_hours, "gap_hours": GAP_HOURS,
                         "max_context_hours": CONTEXT_HOURS, "quantiles": QUANTILES,
                         "forecast_steps_from_context": GAP_HOURS + 1,
                         "test_start_utc": audit.iso(min(case.target_start for case in inputs)),
                         "test_end_exclusive_utc": audit.iso(max(case.target_start for case in inputs) + pilot.HOUR),
                         "refit": False, "cross_learning_between_cases": False},
            "metrics": metrics(records), "weekly_metrics": weekly_metrics(records), "skipped": skipped,
            "limitations": [
                f"This experiment covers {len(items)} items and {args.holdout_hours} test hours; no reliable trading edge is established.",
                "Expanding the item universe does not create an independent future-period test or establish statistical significance.",
                "Price-change error is measured in basis points relative to the last observed context price; direction treats zero as a separate outcome.",
                "The gap assumes publication within one hour. Historical revisions and actual availability are unknown.",
                "At each origin only earlier buckets are inputs; earlier holdout outcomes become context only after the gap.",
                "Price targets are predicted jointly with historical volume covariates. Future prices and volumes are never inputs.",
                "Items and forecast origins do not share attention groups, preventing later origins leaking into earlier ones.",
                "Persistence uses the last observed context price; seasonal uses the target hour 24 hours earlier.",
                "All metrics use a shared complete-case mask. Macro WAPE weights each item/price-side equally, not by GP size.",
                "The 10th–90th quantiles have nominal 80% coverage, not a guaranteed or calibrated confidence level.",
                "No hyperparameters were selected using this holdout. Do not repeatedly tune against it.",
                "No fees, fill probabilities, orders or profits are modelled; price accuracy is not trading profitability.",
            ],
        }
        args.output.mkdir(parents=True, exist_ok=False)
        with (args.output / "forecasts.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        (args.output / "metrics.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (args.output / "report.md").write_text(report_text(result), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, ImportError, RuntimeError) as error:
        print(f"Benchmark failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result["metrics"]["macro_wape_pct"], indent=2))
    print(f"Report: {args.output / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
