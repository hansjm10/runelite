"""Deterministic 30-minute paper planner. Market aggregates never constitute observed fills."""

from dataclasses import dataclass
import math
import re


STEP = 300
HORIZON = 6
GAP = 1
CONTEXT = 120
BANKROLL = 10_000_000
RESERVE = 2_000_000
PER_ITEM = 2_000_000
SLOTS = 6
RESERVED_EXIT_SLOTS = 2
POLICIES = ("liquidity_margin", "chronos_guard")
# Participation basis points are explicit, uncalibrated hypotheses, not probabilities.
SCENARIOS = {"no_fills": (0, 0), "buy_only_stress": (100, 0),
             "thin_0.1pct": (10, 10), "reference_1pct": (100, 100), "optimistic_5pct": (500, 500)}
TAX_SOURCE = "https://oldschool.runescape.wiki/w/Grand_Exchange#Convenience_fee_and_item_sink"
TAX_FREE = {
    "old school bond", "bronze arrow", "bronze dart", "iron arrow", "iron dart", "mind rune",
    "steel arrow", "steel dart", "bass", "bread", "cake", "cooked chicken", "cooked meat", "herring",
    "lobster", "mackerel", "meat pie", "pike", "salmon", "shrimps", "tuna", "ardougne teleport",
    "camelot teleport", "civitas illa fortis teleport", "falador teleport", "games necklace(8)",
    "kourend castle teleport", "lumbridge teleport", "ring of dueling(8)", "teleport to house",
    "varrock teleport", "chisel", "gardening trowel", "glassblowing pipe", "hammer", "needle",
    "pestle and mortar", "rake", "saw", "secateurs", "seed dibber", "shears", "spade", "watering can",
    *(f"energy potion({dose})" for dose in range(1, 5)),
}


def tax(price, name):
    """Current 2% per-item sell tax, rounded down and capped; not a historical tax calendar."""
    if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
        raise ValueError("Tax requires a positive integer sale price")
    return 0 if name.lower() in TAX_FREE else min(price // 50, 5_000_000)


def limit_family(name):
    """Conservative variant grouping, NOT authoritative proof of shared/account limits."""
    return re.sub(r"\s*\((?:[1-8]|uncharged|charged|p\+{0,2})\)", "", name.lower()).strip()


def context_at(rows, origin):
    return [dict(row) for row in rows if row["timestamp"] < origin - GAP * STEP][-CONTEXT:]


def validate_paths(paths, steps=HORIZON + GAP):
    if set(paths) != {"avg_high_price", "avg_low_price"}:
        raise ValueError("Expected both price targets")
    for values in paths.values():
        if len(values) != steps:
            raise ValueError("Wrong forecast horizon")
        for quantiles in values:
            if len(quantiles) != 3 or any(not math.isfinite(v) for v in quantiles) or quantiles != sorted(quantiles):
                raise ValueError("Invalid forecast quantiles; do not selectively discard bad predictions")


def rank_candidates(contexts, catalog, steps_left, policy, forecasts=None, forecast_gap=GAP, quotes=None):
    if policy not in POLICIES or not 1 <= steps_left <= HORIZON:
        raise ValueError("Invalid policy or horizon")
    ranked = []
    for item, rows in sorted(contexts.items()):
        meta = catalog[item]
        if policy == "chronos_guard":
            if forecasts is None or item not in forecasts:
                raise ValueError("Missing model forecast")
            validate_paths(forecasts[item], HORIZON + forecast_gap)
        if (len(rows) < 24 or any(sum(row[field] is not None for row in rows) < 24
                                  for field in ("avg_high_price", "avg_low_price"))
                or meta["limit"] is None or "bond" in meta["name"].lower()):
            continue
        recent, last = rows[-6:], rows[-1]
        if last["avg_high_price"] is None or last["avg_low_price"] is None:
            continue
        if any(row[field] is None for row in recent for field in ("high_price_volume", "low_price_volume")):
            continue
        low = quotes[item]["low"] if quotes is not None else last["avg_low_price"]
        high = quotes[item]["high"] if quotes is not None else last["avg_high_price"]
        buy, sell = math.ceil(low), math.floor(high)
        if policy == "chronos_guard":
            assert forecasts is not None
            # Quantiles are NOT calibrated execution probabilities. This is only a price-risk veto.
            sell = min(sell, math.floor(min(q[0] for q in forecasts[item]["avg_high_price"][forecast_gap:forecast_gap + steps_left])))
        if buy <= 0 or sell <= 0 or buy > PER_ITEM:
            continue
        fee = tax(sell, meta["name"])
        margin = sell - fee - buy
        # At most 1% of two five-minute buckets' activity, estimated from the last six buckets.
        volume_cap = min(sum(row[field] for row in recent) for field in ("high_price_volume", "low_price_volume")) * 2 // 600
        quantity = min(PER_ITEM // buy, meta["group_limit"], volume_cap)
        if margin <= 0 or quantity < 1:
            continue
        ranked.append({"itemId": item, "name": meta["name"], "buyPrice": buy, "sellPrice": sell,
                       "quantity": int(quantity), "capitalGp": int(quantity) * buy,
                       "taxPerItemGp": fee, "netMarginPerItemGp": margin,
                       "group": meta["group"], "groupLimit": meta["group_limit"], "score": margin * quantity})
    return sorted(ranked, key=lambda row: (-row["score"], row["itemId"]))


def starting_plan(candidates):
    cash, groups, selected = BANKROLL, {}, []
    for row in candidates:
        if len(selected) >= SLOTS - RESERVED_EXIT_SLOTS:
            break
        quantity = min(row["quantity"], (cash - RESERVE) // row["buyPrice"],
                       row["groupLimit"] - groups.get(row["group"], 0))
        if quantity <= 0:
            continue
        selected.append({**row, "quantity": quantity, "capitalGp": quantity * row["buyPrice"]})
        cash -= quantity * row["buyPrice"]
        groups[row["group"]] = groups.get(row["group"], 0) + quantity
    return selected


@dataclass
class Position:
    quote: dict
    opened_step: int
    remaining: int
    buying: bool = True
    selling: bool = False
    inventory: int = 0
    bought: int = 0
    sold: int = 0
    exiting: bool = False


def simulate(items, catalog, rankings, start, policy, scenario):
    """Replay hypothetical fills at bucket end; acquired units cannot sell in the same bucket."""
    buy_share, sell_share = SCENARIOS[scenario]
    lookup = {item: {row["timestamp"]: row for row in rows} for item, rows in items.items()}
    cash, realized = BANKROLL, 0
    positions, events, seen, bought_by_group = [], [], set(), {}
    slot_minutes = capital_minutes = max_slots = 0

    def slots():
        return sum(int(p.buying) + int(p.selling) for p in positions)

    def cancel_buy(p, stamp):
        nonlocal cash
        if p.buying:
            cash += p.remaining * p.quote["buyPrice"]
            events.append({"timestamp": stamp, "item_id": p.quote["itemId"], "type": "assumed_cancel_buy", "quantity": p.remaining})
            p.remaining, p.buying = 0, False

    for step in range(HORIZON):
        stamp = start + step * STEP
        for p in positions:
            if step >= 4 or step - p.opened_step >= 2:
                cancel_buy(p, stamp)
            if p.inventory and not p.selling and slots() < SLOTS:
                p.selling = True
            if step >= 4 and p.selling:
                history = context_at(items[p.quote["itemId"]], stamp)
                low = history[-1]["avg_low_price"] if history else None
                if low is not None:
                    # Exit toward a recently observed instant-sell average, never a guaranteed executable bid.
                    p.quote["sellPrice"] = min(p.quote["sellPrice"], max(1, math.floor(low)))
                    p.exiting = True
        if step < 4:
            for row in rankings[(policy, stamp)]:
                if slots() >= SLOTS - RESERVED_EXIT_SLOTS:
                    break
                item, group = row["itemId"], row["group"]
                if item in seen:
                    continue
                reserved_limit = sum(p.remaining for p in positions if p.buying and p.quote["group"] == group)
                quantity = min(row["quantity"], (cash - RESERVE) // row["buyPrice"],
                               row["groupLimit"] - bought_by_group.get(group, 0) - reserved_limit)
                if quantity <= 0:
                    continue
                quote = {**row, "quantity": quantity, "capitalGp": quantity * row["buyPrice"]}
                positions.append(Position(quote, step, quantity))
                seen.add(item)
                cash -= quote["capitalGp"]
                events.append({"timestamp": stamp, "item_id": item, "type": "assumed_buy_order", "quantity": quantity})
        active_slots = slots()
        max_slots = max(max_slots, active_slots)
        slot_minutes += active_slots * 5
        capital_minutes += sum((p.inventory + p.remaining) * p.quote["buyPrice"] for p in positions) * 5
        for p in positions:
            item, name = p.quote["itemId"], p.quote["name"]
            observed = lookup[item].get(stamp)
            if observed is None:
                continue
            # Sell first, so same-bucket new buys can never become same-bucket sales.
            if p.selling:
                price_field = "avg_low_price" if p.exiting else "avg_high_price"
                volume_field = "low_price_volume" if p.exiting else "high_price_volume"
                price, volume = observed[price_field], observed[volume_field]
                if price is not None and volume is not None and price >= p.quote["sellPrice"]:
                    quantity = min(p.inventory, int(volume) * sell_share // 10000)
                    net = p.quote["sellPrice"] - tax(p.quote["sellPrice"], name)
                    cash += quantity * net
                    realized += quantity * (net - p.quote["buyPrice"])
                    p.inventory -= quantity
                    p.sold += quantity
                    if quantity:
                        events.append({"timestamp": stamp + STEP, "item_id": item, "type": "assumed_sell_fill", "quantity": quantity, "price": p.quote["sellPrice"]})
                    if not p.inventory:
                        p.selling = False
            if p.buying:
                price, volume = observed["avg_low_price"], observed["low_price_volume"]
                if price is not None and volume is not None and price <= p.quote["buyPrice"]:
                    quantity = min(p.remaining, int(volume) * buy_share // 10000)
                    p.remaining -= quantity
                    p.inventory += quantity
                    p.bought += quantity
                    group = p.quote["group"]
                    bought_by_group[group] = bought_by_group.get(group, 0) + quantity
                    if quantity:
                        events.append({"timestamp": stamp + STEP, "item_id": item, "type": "assumed_buy_fill", "quantity": quantity, "price": p.quote["buyPrice"]})
                    if not p.remaining:
                        p.buying = False
        assert cash >= RESERVE and slots() <= SLOTS
        assert cash + sum((p.remaining + p.inventory) * p.quote["buyPrice"] for p in positions) == BANKROLL + realized
    deadline = start + HORIZON * STEP
    for p in positions:
        cancel_buy(p, deadline)
    inventory_cost = sum(p.inventory * p.quote["buyPrice"] for p in positions)
    marked_value, unpriced = 0, 0
    for p in positions:
        if not p.inventory:
            continue
        history = context_at(items[p.quote["itemId"]], deadline)
        low = history[-1]["avg_low_price"] if history else None
        if low is None:
            unpriced += p.inventory
        else:
            marked_price = max(1, math.floor(low * 0.97))
            marked_value += p.inventory * (marked_price - tax(marked_price, p.quote["name"]))
    bought, sold = sum(p.bought for p in positions), sum(p.sold for p in positions)
    return {"session_start": start, "policy": policy, "scenario": scenario,
            "cash_at_deadline_gp": cash, "simulated_realized_gp": realized,
            "inventory_cost_gp": inventory_cost, "unpriced_inventory_quantity": unpriced,
            "scenario_inventory_mark_gp": None if unpriced else marked_value,
            "scenario_equity_change_gp": None if unpriced else cash + marked_value - BANKROLL,
            "cash_change_gp": cash - BANKROLL, "inventory_zero_value_floor_gp": cash - BANKROLL,
            "bought_quantity": bought, "sold_quantity": sold,
            "sold_fraction_of_bought": sold / bought if bought else None,
            "flat_at_deadline": bought == sold, "buy_orders": len(positions),
            "completed_positions": sum(p.bought > 0 and p.inventory == 0 for p in positions),
            "slot_minutes": slot_minutes, "capital_minutes_gp": capital_minutes, "max_slots": max_slots,
            "events": events}
