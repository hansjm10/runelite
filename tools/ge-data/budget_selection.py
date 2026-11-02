"""Frozen, past-only item screening for the existing 10m GP / six-slot simulator."""

from collections import Counter
from datetime import datetime
import math

import audit
import expanded
import pilot
import session_engine as engine


ALGORITHM = "ge-budget-cohort-v1"
RULES = {
    "bankroll_gp": 10_000_000, "reserve_gp": 2_000_000, "per_item_cap_gp": 2_000_000,
    "slots": 6, "reserved_exit_slots": 2, "max_items": 50, "selection_buckets": 6,
    "interval_seconds": 300, "publication_gap_seconds": 300,
    "participation_bps": 100, "buy_window_buckets": 2,
    "prices": "ceil(max low), floor(min high) across all six buckets",
    "ranking": "descending net GP capacity, then capital, then ascending item ID",
    "families": "at most one variant per inferred family; smallest known mapping limit",
    "eligibility": "six complete buckets, positive activity on both sides, known limit, positive after-tax margin; exclude bonds",
}


def aligned(value):
    if isinstance(value, bool) or not isinstance(value, int) or audit.timestamp(value) != value or value % engine.STEP:
        raise ValueError("Expected an integer five-minute timestamp in seconds")
    return value


def make_plan(control, checksum):
    start, end = aligned(control["start"]), aligned(control["end"])
    test_start = end - 144 * engine.STEP
    stamps = list(range(test_start - 7 * engine.STEP, test_start - engine.STEP, engine.STEP))
    plan = {"schema_version": 1, "algorithm": ALGORITHM, "created_at": audit.utc_now(),
            "control_dataset_sha256": checksum, "anchor_start": start, "anchor_end": end,
            "test_start": test_start, "selection_stamps": stamps, "rules": dict(RULES),
            "target_return_bps": [400, 500],
            "evaluation": "exploratory same-period cohort comparison; target returns are not selection thresholds"}
    validate_plan(plan)
    return plan


def validate_plan(plan):
    if plan.get("schema_version") != 1 or plan.get("algorithm") != ALGORITHM or plan.get("rules") != RULES:
        raise ValueError("Unsupported/changed budget selection protocol")
    if plan.get("target_return_bps") != [400, 500]:
        raise ValueError("Target returns changed; they must not tune selection")
    start, end, test = (aligned(plan[key]) for key in ("anchor_start", "anchor_end", "test_start"))
    if start < pilot.SOURCE_CHANGE or not 265 * engine.STEP <= end - start <= 288 * engine.STEP:
        raise ValueError("Unsupported fixed historical window")
    expected = list(range(test - 7 * engine.STEP, test - engine.STEP, engine.STEP))
    if test != end - 144 * engine.STEP or plan["selection_stamps"] != expected:
        raise ValueError("Selection must precede the fixed test, including publication gap")
    checksum = plan.get("control_dataset_sha256", "")
    if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise ValueError("Missing control dataset binding")
    if (engine.BANKROLL, engine.RESERVE, engine.PER_ITEM, engine.SLOTS, engine.RESERVED_EXIT_SLOTS) != (10_000_000, 2_000_000, 2_000_000, 6, 2):
        raise ValueError("Planner constraints changed; declare a new experiment")


def select_items(buckets, mapping):
    """Capacity is a quote-based screening score, never expected profit or fill probability."""
    if len(buckets) != RULES["selection_buckets"] or not all(isinstance(b, dict) for b in buckets):
        raise ValueError("Expected exactly six pre-decision market buckets")
    if not isinstance(mapping, list):
        raise ValueError("Expected item mapping list")
    catalog, limits = {}, {}
    for row in mapping:
        item, name, limit = row["id"], row["name"], row.get("limit")
        if type(item) is not int or item <= 0 or item in catalog or not isinstance(name, str) or not 1 <= len(name) <= 120:
            raise ValueError("Invalid/duplicate mapping item")
        if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in name):
            raise ValueError("Invalid item name")
        if limit is not None and (type(limit) is not int or not 0 <= limit <= 2_147_483_647):
            raise ValueError("Invalid mapping limit")
        group = engine.limit_family(name)
        catalog[item] = {"name": name, "limit": limit, "group": group}
        if limit is not None:
            limits[group] = min(limits.get(group, limit), limit)
    ids = set()
    for bucket in buckets:
        for key in bucket:
            if not isinstance(key, str) or not key.isascii() or not key.isdigit() or str(int(key)) != key or int(key) <= 0:
                raise ValueError("Invalid market item ID")
            ids.add(int(key))
    rejected, candidates = Counter(), []
    for item in sorted(ids):
        meta = catalog.get(item)
        if meta is None or meta["limit"] in (None, 0):
            rejected["missing_mapping_or_limit"] += 1
            continue
        if "bond" in meta["name"].lower():
            rejected["bond"] += 1
            continue
        values = [bucket.get(str(item)) for bucket in buckets]
        complete = True
        for row in values:
            if row is None:
                complete = False
                continue
            if not isinstance(row, dict) or any(field not in row for field in pilot.VALUES.values()):
                raise ValueError("Malformed selection observation")
            for column, field in pilot.VALUES.items():
                pilot.validate_value(row[field], column)
                if row[field] is None or row[field] == 0:
                    complete = False
        if not complete:
            rejected["missing_null_or_inactive_bucket"] += 1
            continue
        buy = math.ceil(max(row["avgLowPrice"] for row in values))
        sell = math.floor(min(row["avgHighPrice"] for row in values))
        if buy > engine.PER_ITEM:
            rejected["over_item_budget"] += 1
            continue
        margin = sell - engine.tax(sell, meta["name"]) - buy
        if margin <= 0:
            rejected["no_persistent_net_spread"] += 1
            continue
        volume_cap = min(sum(row[field] for row in values) for field in ("highPriceVolume", "lowPriceVolume")) * 2 // 600
        quantity = int(min(engine.PER_ITEM // buy, limits[meta["group"]], volume_cap))
        if quantity < 1:
            rejected["insufficient_capacity"] += 1
            continue
        candidates.append({"item_id": item, "name": meta["name"], "group": meta["group"],
                           "group_limit": limits[meta["group"]], "buy_price": buy, "sell_price": sell,
                           "quantity": quantity, "capital_gp": quantity * buy,
                           "net_margin_per_item_gp": margin, "quoted_net_capacity_gp": margin * quantity})
    candidates.sort(key=lambda row: (-row["quoted_net_capacity_gp"], -row["capital_gp"], row["item_id"]))
    selected, groups = [], set()
    for row in candidates:
        if row["group"] in groups:
            rejected["duplicate_family"] += 1
        elif len(selected) >= RULES["max_items"]:
            rejected["outside_top_50"] += 1
        else:
            selected.append(row)
            groups.add(row["group"])
    return selected, {"market_items": len(ids), "eligible_before_family_cap": len(candidates),
                      "selected": len(selected), "rejected": dict(sorted(rejected.items()))}


def freeze_cohort(client, plan, mapping_record):
    validate_plan(plan)
    buckets, sources = [], []
    for stamp in plan["selection_stamps"]:
        record = expanded.response(client, audit.WIKI + f"/5m?timestamp={stamp}")
        bucket = expanded.bucket_data(record, stamp)
        retrieved = datetime.fromisoformat(record["fetched_at"].replace("Z", "+00:00"))
        if retrieved.utcoffset() is None or stamp + engine.STEP > retrieved.timestamp():
            raise ValueError("Selection bucket was not closed at retrieval")
        buckets.append(bucket)
        sources.append({"url": record["url"], "timestamp": stamp, "retrieved_at": record["fetched_at"],
                        "payload_sha256": expanded.digest(record["payload"])})
    items, diagnostics = select_items(buckets, mapping_record["payload"])
    return {"schema_version": 1, "algorithm": ALGORITHM, "plan": plan, "plan_sha256": expanded.digest(plan),
            "anchor_start": plan["anchor_start"], "anchor_end": plan["anchor_end"],
            "selection_end_exclusive": plan["test_start"] - engine.STEP,
            "selection_sources": sources, "mapping_source": {"url": mapping_record["url"],
                "retrieved_at": mapping_record["fetched_at"], "payload_sha256": expanded.digest(mapping_record["payload"])},
            "items": items, "diagnostics": diagnostics}


def validate_cohort(cohort):
    plan = cohort["plan"]
    validate_plan(plan)
    if (cohort.get("schema_version") != 1 or cohort.get("algorithm") != ALGORITHM
            or cohort["plan_sha256"] != expanded.digest(plan)
            or any(cohort[key] != plan[key] for key in ("anchor_start", "anchor_end"))
            or cohort["selection_end_exclusive"] != plan["test_start"] - engine.STEP
            or [source["timestamp"] for source in cohort["selection_sources"]] != plan["selection_stamps"]):
        raise ValueError("Budget cohort changed or crosses selection cutoff")
    for row in cohort["items"]:
        if (not isinstance(row["name"], str) or row["group"] != engine.limit_family(row["name"])
                or type(row["group_limit"]) is not int or not 1 <= row["group_limit"] <= 2_147_483_647):
            raise ValueError("Invalid frozen name/family limit")
    ids = [row["item_id"] for row in cohort["items"]]
    groups = [row["group"] for row in cohort["items"]]
    if (not 1 <= len(ids) <= 50 or len(set(ids)) != len(ids) or len(set(groups)) != len(groups)
            or any(type(item) is not int or item <= 0 for item in ids)):
        raise ValueError("Expected 1–50 distinct budget items and inferred families; no padding")
    return ids
