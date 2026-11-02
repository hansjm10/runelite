#!/usr/bin/env python3
"""One bounded, predeclared budget-cohort comparison; no tuning, scheduling or live trades."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys

import audit
import budget_selection as selection
import expanded
import session30 as session
import session_engine as engine


BASE = Path(__file__).resolve().parent / "output"


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def control_inputs(root):
    data, checksum = session.load_dataset(root / "dataset")
    if data["cohort"]["algorithm"] != expanded.SELECTION_SEED:
        raise ValueError("Control must be the original generic cohort")
    results = root / ("results-paired" if (root / "results-paired").exists() else "results")
    metrics = json.loads((results / "metrics.json").read_text(encoding="utf-8"))
    if metrics["dataset_sha256"] != checksum or metrics["test_end"] != data["end"]:
        raise ValueError("Control results do not match the source dataset")
    return data, checksum, results


def seed_cache(source, destination, urls):
    """Reuse exact response bytes and original retrieval times; never refresh cached history."""
    destination.mkdir(parents=True, exist_ok=True)
    for url in urls:
        name = hashlib.sha256(url.encode()).hexdigest() + ".json"
        original, target = source / name, destination / name
        if original.exists():
            if target.exists():
                if target.read_bytes() != original.read_bytes():
                    raise ValueError("Cache collision; refusing to replace an observation")
            else:
                with target.open("xb") as stream:
                    stream.write(original.read_bytes())


def bound_plan(root, control_root):
    control, checksum, results = control_inputs(control_root)
    path = root / "plan.json"
    bindings = {"engine_sha256": file_hash(Path(engine.__file__)),
                "control_result_hashes": {name: file_hash(results / name)
                    for name in ("metrics.json", "sessions.json", "forecasts.json")}}
    if path.exists():
        plan = json.loads(path.read_text(encoding="utf-8"))
        selection.validate_plan(plan)
        if plan["control_dataset_sha256"] != checksum or any(plan.get(k) != v for k, v in bindings.items()):
            raise ValueError("Frozen control or engine changed; do not silently rebase the experiment")
    else:
        plan = {**selection.make_plan(control, checksum), **bindings}
        save(path, plan)  # Freeze rules and historical window BEFORE requesting any selection prices.
    return plan, control, results


def selection_report(cohort):
    quotes = [{"itemId": row["item_id"], "name": row["name"], "buyPrice": row["buy_price"],
               "sellPrice": row["sell_price"], "quantity": row["quantity"], "capitalGp": row["capital_gp"],
               "group": row["group"], "groupLimit": row["group_limit"],
               "netMarginPerItemGp": row["net_margin_per_item_gp"]} for row in cohort["items"]]
    allocation = engine.starting_plan(quotes)
    capacity = sum(row["quantity"] * row["netMarginPerItemGp"] for row in allocation)
    lines = ["# Frozen budget-specific item selection", "", "RESEARCH ONLY — quoted capacity is NOT expected profit.", "",
             f"Selection ends: {session.iso(cohort['selection_end_exclusive'])}; test starts: {session.iso(cohort['plan']['test_start'])}.",
             f"Selected {len(quotes)} of {cohort['diagnostics']['market_items']} sampled market items; no padding to 50.",
             "Six complete pre-test buckets; both sides active; conservative persistent spread after tax.",
             "Original 2m/item cap, 2m reserve and uncalibrated 1% activity cap are unchanged.", "",
             f"Initial quote-based allocation: {sum(row['capitalGp'] for row in allocation):,} GP across {len(allocation)} buys.",
             f"One fully filled round trip at these quotes: {capacity:,} GP ({100 * capacity / engine.BANKROLL:.3f}% of 10m).",
             "This arithmetic assumes every selected unit buys and sells at its quoted price; it is not a forecast or execution upper bound.",
             "4–5% of the account is 400,000–500,000 GP; target returns do not affect ranking or fill assumptions.", "",
             "| Item | Quantity cap | Capital GP | Quoted net GP capacity |", "| --- | ---: | ---: | ---: |"]
    for row in cohort["items"]:
        name = row["name"].replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f"| {name} ({row['item_id']}) | {row['quantity']} | {row['capital_gp']} | {row['quoted_net_capacity_gp']} |")
    lines.extend(["", "Exclusions: " + json.dumps(cohort["diagnostics"]["rejected"], sort_keys=True), "",
                  "Mapping and shared families are assumptions, not verified personal limits. No live recommendations are installed.", ""])
    return "\n".join(lines)


def collect(root, control_root, offline=False):
    if (root / "dataset").exists():
        raise ValueError("Budget dataset already exists; preserve this experiment")
    plan, control, _ = bound_plan(root, control_root)
    cache = root / "cache"
    seed_cache(control_root / "cache", cache, [audit.WIKI + "/mapping", audit.WIKI + "/latest"])
    client = audit.Client(cache, offline=offline)
    mapping = expanded.response(audit.Client(cache, offline=True), audit.WIKI + "/mapping")
    if expanded.digest(mapping["payload"]) != control["mapping_source"]["payload_sha256"]:
        raise ValueError("Control mapping cache does not match the original dataset")
    path = root / "cohort.json"
    if path.exists():
        cohort = json.loads(path.read_text(encoding="utf-8"))
        if cohort["plan"] != plan:
            raise ValueError("Budget cohort does not match frozen plan")
    else:
        cohort = selection.freeze_cohort(client, plan, mapping)
        save(path, cohort)
        with (root / "selection-report.md").open("x", encoding="utf-8") as stream:
            stream.write(selection_report(cohort))
    if not cohort["items"]:
        print("No eligible budget items; selection report saved. No histories requested or model loaded.")
        return
    ids = selection.validate_cohort(cohort)
    seed_cache(control_root / "cache", cache, [audit.WIKI + f"/timeseries?id={item}&lookback=24h" for item in ids])
    data = session.collect(client, cohort)
    session.export_dataset(data, root / "dataset")
    print(f"Frozen {len(ids)} budget items; dataset: {root / 'dataset'}")


def replay_control(data, results):
    """Check the unchanged engine against saved forecasts; no inference or network access."""
    saved = json.loads((results / "forecasts.json").read_text(encoding="utf-8"))
    lookup = {(row["item_id"], row["origin"]): row for row in saved}
    rankings = {}
    starts = list(range(data["end"] - session.TEST_STEPS * engine.STEP, data["end"], engine.HORIZON * engine.STEP))
    for start in starts:
        for step in range(4):
            origin = start + step * engine.STEP
            contexts = {item: engine.context_at(rows, origin) for item, rows in data["items"].items()}
            baseline = engine.rank_candidates(contexts, data["catalog"], 6 - step, "liquidity_margin")
            rankings[("liquidity_margin", origin)] = baseline
            contexts = {row["itemId"]: contexts[row["itemId"]] for row in baseline}
            for item, rows in contexts.items():
                if lookup[(item, origin)]["context_end_exclusive"] != rows[-1]["timestamp"] + engine.STEP:
                    raise ValueError("Saved control forecast cutoff changed")
            rankings[("chronos_guard", origin)] = engine.rank_candidates(contexts, data["catalog"], 6 - step,
                "chronos_guard", {item: lookup[(item, origin)]["quantiles"] for item in contexts})
    replayed = [engine.simulate(data["items"], data["catalog"], rankings, start, policy, scenario)
                for start in starts for policy in engine.POLICIES for scenario in engine.SCENARIOS]
    original = json.loads((results / "sessions.json").read_text(encoding="utf-8"))
    if replayed != original:
        raise ValueError("Engine no longer reproduces original control sessions; comparison stopped")
    return original


def compare(cohorts, plan):
    """Paired valuation across BOTH cohorts and policies; target hits require flat inventory."""
    selection.validate_plan(plan)
    starts = set(range(plan["test_start"], plan["anchor_end"], engine.HORIZON * engine.STEP))
    groups = {}
    for cohort, sessions in cohorts.items():
        expected = {(start, policy, scenario) for start in starts for policy in engine.POLICIES for scenario in engine.SCENARIOS}
        keys = [(row["session_start"], row["policy"], row["scenario"]) for row in sessions]
        if len(set(keys)) != len(keys) or set(keys) != expected:
            raise ValueError("Comparison requires identical complete session/scenario grids")
        for policy in engine.POLICIES:
            for scenario in engine.SCENARIOS:
                groups[(cohort, policy, scenario)] = [row for row in sessions if row["policy"] == policy and row["scenario"] == scenario]
    summaries = []
    for (cohort, policy, scenario), rows in groups.items():
        masks = [{row["session_start"] for row in values if row["scenario_equity_change_gp"] is not None}
                 for key, values in groups.items() if key[2] == scenario]
        common = set.intersection(*masks)
        priced = [row for row in rows if row["session_start"] in common]
        summaries.append({"cohort": cohort, "policy": policy, "scenario": scenario, "sessions": len(rows),
            "paired_marked_sessions": len(priced), "unpriced_sessions": sum(row["scenario_equity_change_gp"] is None for row in rows),
            "mean_simulated_realized_gp": statistics.mean(row["simulated_realized_gp"] for row in rows),
            "mean_paired_marked_change_gp": statistics.mean(row["scenario_equity_change_gp"] for row in priced) if priced else None,
            "mean_committed_capital_gp": statistics.mean(row["capital_minutes_gp"] / 30 for row in rows),
            "mean_inventory_cost_gp": statistics.mean(row["inventory_cost_gp"] for row in rows),
            "mean_cash_change_gp": statistics.mean(row["cash_change_gp"] for row in rows),
            "worst_cash_floor_gp": min(row["inventory_zero_value_floor_gp"] for row in rows),
            "flat_sessions": sum(row["flat_at_deadline"] for row in rows),
            "no_buy_sessions": sum(row["bought_quantity"] == 0 for row in rows),
            "fully_exited_target_sessions": {str(bps): sum(row["flat_at_deadline"] and row["cash_change_gp"] >= engine.BANKROLL * bps // 10000
                                                         for row in rows) for bps in plan["target_return_bps"]}})
    return {"schema_version": 1, "generated_at": audit.utc_now(), "evaluation_mode": "exploratory_hypothetical_retrospective",
            "plan_sha256": expanded.digest(plan), "summary": summaries,
            "limitations": session.LIMITS + ["Selection compares cohorts on an already-inspected historical period, not a new independent holdout.",
                "The 4–5% targets are account-level after-tax goals, not expected returns; counts require hypothetical full exit.",
                "Marked means share one priced-session mask across all four cohort/policy combinations per scenario."]}


def comparison_report(result):
    lines = ["# Budget-specific cohort comparison", "", "HYPOTHETICAL FILLS — NOT OBSERVED PROFIT OR AN INDEPENDENT HOLDOUT", "",
             "| Cohort | Policy | Scenario | Mean realized GP | Paired marked GP | Priced n | Mean committed GP | Flat n | 4% / 5% fully exited n |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in result["summary"]:
        mark = row["mean_paired_marked_change_gp"]
        mark_text = "unknown" if mark is None else f"{mark:.2f}"
        target = row["fully_exited_target_sessions"]
        lines.append(f"| {row['cohort']} | {row['policy']} | {row['scenario']} | {row['mean_simulated_realized_gp']:.2f} | {mark_text} | "
                     f"{row['paired_marked_sessions']} | {row['mean_committed_capital_gp']:.2f} | {row['flat_sessions']} | {target['400']} / {target['500']} |")
    lines.extend(["", "All rows include 24 independent/reset sessions. Paired marked means can exclude inventory with unknown prices.",
                  "Cash floors and unpriced counts for ALL sessions remain in metrics.json. Flat rates include no-trade sessions.", "",
                  *["- " + note for note in result["limitations"]], ""])
    return "\n".join(lines)


def benchmark(root, control_root, model_cache):
    if (root / "results").exists() or (root / "comparison").exists():
        raise ValueError("Results already exist; do not tune/rerun this experiment")
    if not (root / "plan.json").exists():
        raise ValueError("Collect a frozen budget dataset first")
    plan, control, results = bound_plan(root, control_root)
    data, checksum = session.load_dataset(root / "dataset")
    if data["cohort"]["plan"] != plan:
        raise ValueError("Dataset changed from frozen selection plan")
    original = replay_control(control, results)
    new = session.run_benchmark(data, checksum, root / "results", model_cache)
    old_metrics = json.loads((results / "metrics.json").read_text(encoding="utf-8"))
    if new["settings"] != old_metrics["settings"]:
        # JSON represents tuples as arrays; compare canonical JSON rather than Python container types.
        if expanded.digest(new["settings"]) != expanded.digest(old_metrics["settings"]):
            raise ValueError("Strategy settings differ from the control; no comparison reported")
    selected = json.loads((root / "results" / "sessions.json").read_text(encoding="utf-8"))
    result = compare({"generic": original, "budget": selected}, plan)
    result["dataset_sha256"] = {"generic": plan["control_dataset_sha256"], "budget": checksum}
    result["control_result_hashes"] = plan["control_result_hashes"]
    save(root / "comparison" / "metrics.json", result)
    with (root / "comparison" / "report.md").open("x", encoding="utf-8") as stream:
        stream.write(comparison_report(result))
    print(f"Comparison: {root / 'comparison' / 'report.md'}; no live offers placed")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "benchmark"))
    parser.add_argument("--root", type=Path, default=BASE / "budget30")
    parser.add_argument("--control-root", type=Path, default=BASE / "session30")
    parser.add_argument("--model-cache", type=Path, default=BASE / "models")
    parser.add_argument("--offline", action="store_true", help="Collection cache only; model inference is always offline")
    args = parser.parse_args(argv)
    try:
        if args.command == "collect":
            collect(args.root, args.control_root, args.offline)
        else:
            benchmark(args.root, args.control_root, args.model_cache)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError, OverflowError) as error:
        print(f"Budget experiment stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
