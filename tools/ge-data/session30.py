#!/usr/bin/env python3
"""Bounded five-minute collection, hypothetical 30-minute replay, and local manual plan export."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
from urllib.parse import urlencode

import audit
import benchmark
import budget_selection
import chronos_backend
import expanded
import pilot
import session_engine as engine


TEST_STEPS = 144  # 24 independent, non-overlapping 30-minute sessions over the final 12 hours.
LIMITS = [
    "RESEARCH ONLY: all fills and profits below are simulated counterfactual scenarios, never observed executions.",
    "Five-minute transaction averages and volumes reveal neither quotes, queue position, nor your fill probability.",
    "Participation shares are uncalibrated assumptions; no-fill and buy-only stress scenarios are included.",
    "The five-minute publication gap is assumed, not measured. Retrospective histories may contain revisions.",
    "Each 30-minute session independently starts with 10m GP, empty inventory and assumed unused buy limits. Do not sum these into daily earnings.",
    "Current mapping limits and inferred variant families are assumptions, not verified historical or personal/shared account limits.",
    "Sales pay current per-item tax. The replay is restricted to the current post-2026-09-30 source regime.",
    "Residual inventory is NOT sold automatically: its hypothetical mark uses a 3% haircut and tax; missing exit prices remain unpriced.",
    "The no-inventory-value cash floor is reported for every session. Marked means use a common priced-session mask across both policies per scenario.",
    "Chronos quantiles are a price-risk veto, not calibrated confidence or a learned fill-time model. No model training occurs.",
    "The frozen cohort and nearby hourly period were previously inspected. This finer-horizon replay is exploratory, not independent validation.",
]
PANEL_FIELDS = ("itemId", "name", "buyPrice", "sellPrice", "quantity", "capitalGp", "taxPerItemGp", "netMarginPerItemGp")


def stamp(value):
    result = audit.timestamp(value)
    if result % engine.STEP:
        raise ValueError("Expected a five-minute aligned timestamp")
    return int(result)


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def date_time(value):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.utcoffset() is None:
        raise ValueError("Expected timezone-aware retrieval time")
    return date


def normalize(record, item):
    payload = record["payload"]
    if str(payload.get("itemId")) != str(item) or payload.get("timestep") != engine.STEP:
        raise ValueError("Expected the requested item at actual five-minute resolution; no interpolation")
    start, end = stamp(payload["startTimestamp"]), stamp(payload["endTimestamp"])
    if not 1 <= (end - start) // engine.STEP <= 288 or end > date_time(record["fetched_at"]).timestamp():
        raise ValueError("Expected a closed, bounded 24-hour window")
    if start < pilot.SOURCE_CHANGE:
        raise ValueError("Current tax/mapping assumptions support only the post-2026-09-30 source regime")
    found = {}
    for observation in audit.observations(payload, "timeseries", item):
        timestamp = stamp(observation["timestamp"])
        if not start <= timestamp < end or timestamp in found:
            raise ValueError("Duplicate or out-of-window five-minute observation")
        for field, api_field in pilot.VALUES.items():
            pilot.validate_value(observation[api_field], field)
        found[timestamp] = observation
    rows = [{"timestamp": timestamp, "record_present": timestamp in found,
             **{field: found[timestamp][api_field] if timestamp in found else None
                for field, api_field in pilot.VALUES.items()}}
            for timestamp in range(start, end, engine.STEP)]
    return rows, {"item_id": item, "url": record["url"], "retrieved_at": record["fetched_at"],
                  "start": start, "end": end, "payload_sha256": expanded.digest(payload),
                  "source_regime": "jagex_all_clients"}


def build_catalog(payload, ids):
    if not isinstance(payload, list):
        raise ValueError("Expected item mapping list")
    catalog = {}
    for row in payload:
        item = row["id"]
        if item not in ids:
            continue
        name, limit = row["name"], row.get("limit")
        if item in catalog or not isinstance(name, str) or not 1 <= len(name) <= 120 or any(ord(c) < 32 for c in name):
            raise ValueError("Invalid/duplicate item name or mapping")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2_147_483_647):
            raise ValueError("Invalid mapping buy limit")
        catalog[item] = {"name": name, "limit": limit, "group": engine.limit_family(name)}
    if set(catalog) != set(ids):
        raise ValueError("Mapping is missing a frozen-cohort item")
    for meta in catalog.values():
        limits = [m["limit"] for m in catalog.values() if m["group"] == meta["group"] and m["limit"] is not None]
        meta["group_limit"] = min(limits) if limits else 0
    return catalog


def validate_cohort(cohort):
    if cohort.get("algorithm") == budget_selection.ALGORITHM:
        return budget_selection.validate_cohort(cohort)
    return expanded.validate_cohort(cohort)


def collect(client, cohort):
    ids = validate_cohort(cohort)
    if len(ids) > 50:
        raise ValueError("This experiment is limited to 50 item histories, not a bulk crawl")
    mapping = expanded.response(client, audit.WIKI + "/mapping")
    catalog = build_catalog(mapping["payload"], ids)
    if cohort["algorithm"] == budget_selection.ALGORITHM:
        if expanded.digest(mapping["payload"]) != cohort["mapping_source"]["payload_sha256"]:
            raise ValueError("Mapping changed since budget selection")
        for row in cohort["items"]:
            catalog[row["item_id"]]["group_limit"] = min(catalog[row["item_id"]]["group_limit"], row["group_limit"])
    items, sources = {}, []
    for index, item in enumerate(ids, 1):
        record = expanded.response(client, audit.WIKI + "/timeseries?" + urlencode({"id": item, "lookback": "24h"}))
        items[item], source = normalize(record, item)
        sources.append(source)
        print(f"Validated {index}/{len(ids)} five-minute histories (cached={record['cached']})", flush=True)
    start, end = max(source["start"] for source in sources), min(source["end"] for source in sources)
    if cohort["algorithm"] == budget_selection.ALGORITHM:
        if end < cohort["anchor_end"]:
            raise ValueError("Histories do not cover the frozen budget replay end")
        start, end = max(start, cohort["anchor_start"]), cohort["anchor_end"]
    if end - start < (TEST_STEPS + engine.CONTEXT + engine.GAP) * engine.STEP:
        raise ValueError("Insufficient shared five-minute history for the fixed 12-hour test and context")
    if cohort["selection_end_exclusive"] > end - (TEST_STEPS + engine.GAP) * engine.STEP:
        raise ValueError("Cohort selection overlaps the new replay")
    items = {item: [row for row in rows if start <= row["timestamp"] < end] for item, rows in items.items()}
    latest = expanded.response(client, audit.WIKI + "/latest")
    if not isinstance(latest["payload"].get("data"), dict):
        raise ValueError("Invalid latest-price response")
    return {"schema_version": 1, "interval_seconds": engine.STEP, "start": start, "end": end,
            "cohort": cohort, "cohort_sha256": expanded.digest(cohort), "items": items, "catalog": catalog,
            "sources": sources, "mapping_source": {"url": mapping["url"], "retrieved_at": mapping["fetched_at"],
                                                     "payload_sha256": expanded.digest(mapping["payload"])},
            "latest": {str(item): latest["payload"]["data"].get(str(item)) for item in ids},
            "latest_source": {"url": latest["url"], "retrieved_at": latest["fetched_at"],
                              "payload_sha256": expanded.digest(latest["payload"])},
            "limitations": LIMITS}


def export_dataset(data, folder):
    folder.mkdir(parents=True, exist_ok=False)
    path = folder / "data.json"
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (folder / "manifest.json").write_text(json.dumps({"schema_version": 1, "generated_at": audit.utc_now(),
        "data_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "interval_seconds": engine.STEP,
        "items": len(data["items"]), "start": data["start"], "end": data["end"],
        "missing_buckets": sum(not row["record_present"] for rows in data["items"].values() for row in rows)}, indent=2) + "\n", encoding="utf-8")


def load_dataset(folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    raw = (folder / "data.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["data_sha256"]:
        raise ValueError("Dataset checksum mismatch")
    data = json.loads(raw)
    if data.get("schema_version") != 1 or data.get("interval_seconds") != engine.STEP:
        raise ValueError("Expected version-1 five-minute dataset")
    if data["cohort_sha256"] != expanded.digest(data["cohort"]):
        raise ValueError("Cohort checksum mismatch")
    ids = validate_cohort(data["cohort"])
    if data["cohort"]["algorithm"] == budget_selection.ALGORITHM and (
            data["end"] != data["cohort"]["anchor_end"] or data["start"] < data["cohort"]["anchor_start"]):
        raise ValueError("Dataset moved outside frozen budget window")
    data["items"] = {int(item): rows for item, rows in data["items"].items()}
    data["catalog"] = {int(item): meta for item, meta in data["catalog"].items()}
    if sorted(data["items"]) != sorted(ids) or sorted(data["catalog"]) != sorted(ids):
        raise ValueError("Changed frozen item universe")
    start, end = stamp(data["start"]), stamp(data["end"])
    if start < pilot.SOURCE_CHANGE or end - start < (TEST_STEPS + engine.CONTEXT + engine.GAP) * engine.STEP:
        raise ValueError("Unsupported/insufficient dataset window")
    if data["cohort"]["selection_end_exclusive"] > end - (TEST_STEPS + engine.GAP) * engine.STEP:
        raise ValueError("Cohort selection overlaps replay")
    for rows in data["items"].values():
        if [row["timestamp"] for row in rows] != list(range(start, end, engine.STEP)):
            raise ValueError("Missing/non-unique timestamp grid; gaps must be explicit")
        for row in rows:
            if type(row["record_present"]) is not bool:
                raise ValueError("Invalid record presence flag")
            for field in pilot.VALUES:
                pilot.validate_value(row[field], field)
                if not row["record_present"] and row[field] is not None:
                    raise ValueError("Missing bucket contains observations")
    return data, manifest["data_sha256"]


def make_rankings(data, model_cache):
    """Freeze inputs for every origin from its available prefix; labels never enter model tasks."""
    end = data["end"]
    starts = list(range(end - TEST_STEPS * engine.STEP, end, engine.HORIZON * engine.STEP))
    rankings, inputs, metadata, contexts_at_origin = {}, [], [], {}
    for start in starts:
        for step in range(4):
            origin = start + step * engine.STEP
            contexts = {item: engine.context_at(rows, origin) for item, rows in data["items"].items()}
            baseline = engine.rank_candidates(contexts, data["catalog"], engine.HORIZON - step, "liquidity_margin")
            rankings[("liquidity_margin", origin)] = baseline
            eligible = {row["itemId"] for row in baseline}
            contexts_at_origin[origin] = {item: contexts[item] for item in eligible}
            for item in sorted(eligible):
                inputs.append(benchmark.ForecastInput(item, origin, contexts[item]))
                metadata.append((item, origin))
    started = time.monotonic()
    if inputs:
        model = chronos_backend.ChronosForecaster(model_cache, offline=True)
        forecasts = model.predict_paths(inputs, prediction_length=engine.GAP + engine.HORIZON, context_length=engine.CONTEXT)
        provenance = model.provenance()
    else:
        forecasts, provenance = [], {"inference": "not run; no eligible baseline candidates"}
    elapsed = time.monotonic() - started
    if len(forecasts) != len(inputs):
        raise ValueError("Wrong forecast count")
    forecast_lookup = defaultdict(dict)
    saved = []
    for (item, origin), paths, case in zip(metadata, forecasts, inputs):
        engine.validate_paths(paths)
        forecast_lookup[origin][item] = paths
        saved.append({"item_id": item, "origin": origin, "context_end_exclusive": case.context[-1]["timestamp"] + engine.STEP,
                      "quantiles": paths})
    for start in starts:
        for step in range(4):
            origin = start + step * engine.STEP
            rankings[("chronos_guard", origin)] = engine.rank_candidates(
                contexts_at_origin[origin], data["catalog"], engine.HORIZON - step, "chronos_guard", forecast_lookup[origin])
    return starts, rankings, saved, provenance, elapsed


def summarize(sessions):
    paired_priced = {}
    for scenario in engine.SCENARIOS:
        masks = [{row["session_start"] for row in sessions if row["scenario"] == scenario
                  and row["policy"] == policy and row["scenario_equity_change_gp"] is not None}
                 for policy in engine.POLICIES]
        paired_priced[scenario] = set.intersection(*masks)
    summaries = []
    for policy in engine.POLICIES:
        for scenario in engine.SCENARIOS:
            rows = [row for row in sessions if row["policy"] == policy and row["scenario"] == scenario]
            priced = [row for row in rows if row["session_start"] in paired_priced[scenario]]
            summaries.append({"policy": policy, "scenario": scenario, "sessions": len(rows),
                "no_buy_fill_sessions": sum(row["bought_quantity"] == 0 for row in rows),
                "unpriced_inventory_sessions": sum(row["scenario_equity_change_gp"] is None for row in rows),
                "paired_marked_sessions": len(priced),
                "mean_simulated_realized_gp": statistics.mean(row["simulated_realized_gp"] for row in rows),
                "mean_scenario_equity_change_gp": statistics.mean(row["scenario_equity_change_gp"] for row in priced) if priced else None,
                "mean_cash_at_deadline_gp": statistics.mean(row["cash_at_deadline_gp"] for row in rows),
                "worst_zero_inventory_value_floor_gp": min(row["inventory_zero_value_floor_gp"] for row in rows),
                "flat_sessions_pct": 100 * statistics.mean(row["flat_at_deadline"] for row in rows),
                "mean_inventory_cost_gp": statistics.mean(row["inventory_cost_gp"] for row in rows),
                "mean_slot_minutes": statistics.mean(row["slot_minutes"] for row in rows),
                "mean_capital_minutes_gp": statistics.mean(row["capital_minutes_gp"] for row in rows)})
    return summaries


def panel_plan(candidates, as_of, now, mode="historical", policy="chronos_guard"):
    if mode not in ("historical", "snapshot") or policy not in engine.POLICIES:
        raise ValueError("Invalid panel mode/policy")
    if now.utcoffset() is None or as_of > now.timestamp():
        raise ValueError("Cannot export a future/naive plan")
    expires = None
    if mode == "snapshot":
        expiry = min(now.timestamp() + 300, as_of + 900)
        if expiry <= now.timestamp():
            raise ValueError("Snapshot is stale; collect into a fresh root, do not relabel old data")
        expires = iso(expiry)
    return {"schemaVersion": 1, "mode": mode, "generatedAt": iso(now.timestamp()), "asOf": iso(as_of),
            "expiresAt": expires, "bankrollGp": engine.BANKROLL, "cashReserveGp": engine.RESERVE,
            "availableSlots": engine.SLOTS, "sessionMinutes": 30, "policy": policy, "accountLimitsVerified": False,
            "warnings": ["Unvalidated execution assumptions; quotes are not guaranteed fills or expected profit.",
                         "Verify actual cash, free slots, tax exemptions and remaining personal/shared buy limits yourself.",
                         "This is an initial allocation only, not automatic live replanning or order management."],
            "candidates": [{key: row[key] for key in PANEL_FIELDS} for row in engine.starting_plan(candidates)]}


def snapshot_plan(data, model_cache, now, policy="chronos_guard"):
    if now.utcoffset() is None or not 0 <= now.timestamp() - data["end"] < 900:
        raise ValueError("Five-minute history is stale/future; collect a fresh dataset")
    retrieved = date_time(data["latest_source"]["retrieved_at"]).timestamp()
    if not 0 <= now.timestamp() - retrieved <= 300:
        raise ValueError("Latest-price snapshot is stale/future")
    origin = (int(now.timestamp()) // engine.STEP + 1) * engine.STEP
    gap = (origin - data["end"]) // engine.STEP
    contexts, quotes = {}, {}
    for item, rows in data["items"].items():
        latest = data["latest"].get(str(item))
        if not isinstance(latest, dict):
            continue
        valid = True
        for side in ("high", "low"):
            price, seen = latest.get(side), latest.get(side + "Time")
            if price is None or seen is None:
                valid = False
                break
            pilot.validate_value(price, "avg_high_price")
            seen = audit.timestamp(seen)
            # Cache retrieval timestamps mark request start; a trade can occur while the response is in flight.
            if not 0 <= now.timestamp() - seen <= 300:
                valid = False
        if valid:
            contexts[item] = rows[-engine.CONTEXT:]
            quotes[item] = latest
    baseline = engine.rank_candidates(contexts, data["catalog"], engine.HORIZON, "liquidity_margin", quotes=quotes)
    if policy == "liquidity_margin" or not baseline:
        candidates = baseline
    else:
        contexts = {row["itemId"]: contexts[row["itemId"]] for row in baseline}
        cases = [benchmark.ForecastInput(item, origin, rows) for item, rows in sorted(contexts.items())]
        model = chronos_backend.ChronosForecaster(model_cache, offline=True)
        paths = model.predict_paths(cases, prediction_length=gap + engine.HORIZON, context_length=engine.CONTEXT)
        if len(paths) != len(cases):
            raise ValueError("Wrong snapshot forecast count")
        candidates = engine.rank_candidates(contexts, data["catalog"], engine.HORIZON, "chronos_guard",
            {case.item_id: path for case, path in zip(cases, paths)}, forecast_gap=gap, quotes=quotes)
    # Expiry is checked again after real inference by the caller before writing.
    return panel_plan(candidates, data["end"], now, "snapshot", policy)


def report(result):
    lines = ["# 30-minute hypothetical execution benchmark", "", "NOT REALISED GP / NOT AN EXECUTION-VALIDATED BACKTEST", "",
             f"Generated: {result['generated_at']}", f"Independent sessions per policy/scenario: {result['session_count']}",
             "Each starts with 10m GP, six available slots and assumed unused limits; 2m stays in cash.", "",
             "Marked equity uses hypothetical residual inventory values, NOT sales or cash proceeds.", "",
             "| Policy | Assumed fills | Mean simulated realised GP | Mean marked equity change GP* | Flat sessions % | No-buy sessions | Unpriced sessions | Paired marked sessions |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in result["summary"]:
        marked = row["mean_scenario_equity_change_gp"]
        mark_text = "unknown" if marked is None else f"{marked:.1f}"
        lines.append(f"| {row['policy']} | {row['scenario']} | {row['mean_simulated_realized_gp']:.1f} | {mark_text} | "
                     f"{row['flat_sessions_pct']:.1f} | {row['no_buy_fill_sessions']} | {row['unpriced_inventory_sessions']} | {row['paired_marked_sessions']} |")
    lines.extend(["", "*Marked means use the same priced-session mask for both policies in each scenario. JSON also includes cash, inventory cost,",
                  "capital/slot time and a zero-inventory-value floor for every session. No-fill is not profitable trading.",
                  "", "## Limitations", "", *["- " + note for note in LIMITS], ""])
    return "\n".join(lines)


def run_benchmark(data, checksum, output, model_cache):
    if output.exists():
        raise ValueError("Results exist; preserve this fixed experiment rather than tune/rerun it")
    starts, rankings, forecasts, provenance, elapsed = make_rankings(data, model_cache)
    sessions = [engine.simulate(data["items"], data["catalog"], rankings, start, policy, scenario)
                for start in starts for policy in engine.POLICIES for scenario in engine.SCENARIOS]
    result = {"schema_version": 1, "generated_at": audit.utc_now(), "evaluation_mode": "hypothetical_retrospective",
              "dataset_sha256": checksum, "session_count": len(starts), "test_start": starts[0], "test_end": data["end"],
              "settings": {"bankroll_gp": engine.BANKROLL, "reserve_gp": engine.RESERVE, "per_item_cap_gp": engine.PER_ITEM,
                           "slots": engine.SLOTS, "session_minutes": 30, "interval_seconds": engine.STEP,
                           "gap_steps": engine.GAP, "context_steps": engine.CONTEXT, "participation_bps": engine.SCENARIOS,
                           "buy_timeout_minutes": 10, "no_new_buys_after_minutes": 20,
                           "inventory_mark_haircut_pct": 3, "tax_source": engine.TAX_SOURCE},
              "model": provenance, "model_inference_seconds_including_load": elapsed,
              "forecast_task_count": len(forecasts), "summary": summarize(sessions), "limitations": LIMITS}
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("metrics.json", result), ("sessions.json", sessions), ("forecasts.json", forecasts)):
        (output / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output / "report.md").write_text(report(result), encoding="utf-8")
    preview = panel_plan(rankings[("chronos_guard", starts[0])], starts[0] - engine.GAP * engine.STEP,
                         datetime.now(audit.UTC))
    (output / "historical-plan.json").write_text(json.dumps(preview, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    base = Path(__file__).resolve().parent / "output"
    parser.add_argument("command", choices=("collect", "benchmark", "snapshot"))
    parser.add_argument("--root", type=Path, default=base / "session30")
    parser.add_argument("--cohort", type=Path, default=base / "expanded" / "cohort.json")
    parser.add_argument("--model-cache", type=Path, default=base / "models")
    parser.add_argument("--offline", action="store_true", help="Collection cache only; all model inference is always offline")
    parser.add_argument("--policy", choices=engine.POLICIES, default="chronos_guard", help="Snapshot policy only")
    parser.add_argument("--plan-output", type=Path, help="Snapshot output, must not already exist; copy it to the sidebar manually")
    args = parser.parse_args(argv)
    try:
        if args.command == "collect":
            folder = args.root / "dataset"
            if folder.exists():
                raise ValueError("Dataset already exists; use a new root for an intentional fresh snapshot")
            cohort = json.loads(args.cohort.read_text(encoding="utf-8"))
            data = collect(audit.Client(args.root / "cache", offline=args.offline), cohort)
            export_dataset(data, folder)
            print(f"Dataset: {folder}; no scheduler was installed")
        else:
            data, checksum = load_dataset(args.root / "dataset")
            if args.command == "benchmark":
                result = run_benchmark(data, checksum, args.root / "results", args.model_cache)
                print(f"Simulated {result['session_count']} independent sessions under {len(engine.SCENARIOS)} hypotheses; NOT observed profit")
                print(f"Report: {args.root / 'results' / 'report.md'}")
            else:
                path = args.plan_output or args.root / "snapshot-plan.json"
                if path.exists():
                    raise ValueError("Plan output exists; preserve it and choose an unused path")
                plan = snapshot_plan(data, args.model_cache, datetime.now(audit.UTC), args.policy)
                if date_time(plan["expiresAt"]).timestamp() <= datetime.now(audit.UTC).timestamp():
                    raise ValueError("Snapshot expired during inference; no plan exported")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(plan, indent=2, allow_nan=False) + "\n")
                print(f"Experimental manual plan: {path}; expires {plan['expiresAt']}; limits unverified")
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError, OverflowError) as error:
        print(f"30-minute experiment failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
