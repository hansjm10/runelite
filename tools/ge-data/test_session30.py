import contextlib
import copy
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import audit
import expanded
import pilot
import session30 as session
import session_engine as engine
from test_expanded import END, FakeClient


START = END
FINISH = START + 288 * engine.STEP


class FiveMinuteClient:
    def __init__(self, ids):
        self.ids = ids
        self.urls = []
        self.failure: int | None = None
        self.shift_item: int | None = None

    def get(self, url):
        self.urls.append(url)
        if self.failure:
            return {"url": url, "status": self.failure, "error": "test failure"}
        route = urlparse(url).path
        if route.endswith("/mapping"):
            payload = [{"id": item, "name": f"Item {item}", "limit": 1000} for item in self.ids]
        elif route.endswith("/latest"):
            payload = {"data": {str(item): {"high": 103000, "low": 100000,
                                           "highTime": FINISH + 300, "lowTime": FINISH + 300} for item in self.ids}}
        else:
            item = int(parse_qs(urlparse(url).query)["id"][0])
            start = START + (engine.STEP if item == self.shift_item else 0)
            payload = {"itemId": item, "timestep": engine.STEP, "startTimestamp": start,
                       "endTimestamp": start + 288 * engine.STEP,
                       "data": [{"timestamp": start + i * engine.STEP, "avgHighPrice": 103000,
                                 "avgLowPrice": None if i == 30 else 100000,
                                 "highPriceVolume": 10000, "lowPriceVolume": 0 if i == 30 else 10000}
                                for i in range(288) if i != 31]}
        return {"url": url, "status": 200, "cached": True, "fetched_at": audit.iso(FINISH + 300), "payload": payload}


def fixture(count=3):
    cohort = expanded.freeze_cohort(FakeClient(), count)
    client = FiveMinuteClient(expanded.validate_cohort(cohort))
    with contextlib.redirect_stdout(io.StringIO()):
        data = session.collect(client, cohort)
    return data, client


def fake_paths(cases, prediction_length=7, **kwargs):
    return [{"avg_high_price": [[102900., 103000., 104000.] for _ in range(prediction_length)],
             "avg_low_price": [[99000., 100000., 101000.] for _ in range(prediction_length)]} for _ in cases]


class DataTests(unittest.TestCase):
    def test_collection_is_bounded_shared_window_preserves_gaps_null_zero_and_provenance(self):
        cohort = expanded.freeze_cohort(FakeClient(), 3)
        client = FiveMinuteClient(expanded.validate_cohort(cohort))
        client.shift_item = client.ids[1]
        with contextlib.redirect_stdout(io.StringIO()):
            data = session.collect(client, cohort)
        self.assertEqual(len(client.urls), 5)  # mapping + 3 histories + one latest snapshot
        self.assertEqual(data["start"], START + engine.STEP)
        self.assertEqual(data["end"], FINISH)
        self.assertTrue(all(len(rows) == 287 for rows in data["items"].values()))
        rows = next(iter(data["items"].values()))
        self.assertTrue(any(row["record_present"] and row["avg_low_price"] is None and row["low_price_volume"] == 0 for row in rows))
        self.assertTrue(any(not row["record_present"] and row["low_price_volume"] is None for row in rows))
        self.assertTrue(all(source["retrieved_at"] == audit.iso(FINISH + 300) and source["payload_sha256"] for source in data["sources"]))
        self.assertEqual(data["cohort"], cohort)

    def test_bad_resolution_duplicates_incomplete_and_invalid_values_rejected(self):
        client = FiveMinuteClient([1])
        original = client.get(audit.WIKI + "/timeseries?id=1&lookback=24h")
        variants = []
        wrong = copy.deepcopy(original)
        wrong["payload"]["timestep"] = 3600
        variants.append(wrong)
        duplicate = copy.deepcopy(original)
        duplicate["payload"]["data"].append(duplicate["payload"]["data"][0])
        variants.append(duplicate)
        incomplete = copy.deepcopy(original)
        incomplete["fetched_at"] = audit.iso(FINISH - 1)
        variants.append(incomplete)
        bad = copy.deepcopy(original)
        bad["payload"]["data"][0]["avgLowPrice"] = -1
        variants.append(bad)
        for record in variants:
            with self.assertRaises(ValueError):
                session.normalize(record, 1)

    def test_failed_collection_stops_and_missing_limits_are_not_invented(self):
        cohort = expanded.freeze_cohort(FakeClient(), 3)
        client = FiveMinuteClient(expanded.validate_cohort(cohort))
        client.failure = 429
        with self.assertRaises(ValueError):
            session.collect(client, cohort)
        self.assertEqual(len(client.urls), 1)
        catalog = session.build_catalog([{"id": 1, "name": "Unknown limit"}], [1])
        self.assertIsNone(catalog[1]["limit"])
        self.assertEqual(catalog[1]["group_limit"], 0)

    def test_export_load_checksum_grid_and_cohort_binding(self):
        data, _ = fixture()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "dataset"
            session.export_dataset(data, folder)
            loaded, _ = session.load_dataset(folder)
            self.assertEqual(loaded["items"], data["items"])
            self.assertEqual(loaded["latest"], data["latest"])
            with self.assertRaises(FileExistsError):
                session.export_dataset(data, folder)
            with (folder / "data.json").open("a", encoding="utf-8") as stream:
                stream.write(" ")
            with self.assertRaisesRegex(ValueError, "checksum"):
                session.load_dataset(folder)

    def test_context_and_first_decision_cannot_see_gap_or_future_rows(self):
        data, _ = fixture()
        origin = FINISH - session.TEST_STEPS * engine.STEP
        original = {item: engine.context_at(rows, origin) for item, rows in data["items"].items()}
        mutated = copy.deepcopy(data)
        for rows in mutated["items"].values():
            for row in rows:
                if row["timestamp"] >= origin - engine.STEP:
                    for field in pilot.VALUES:
                        row[field] = 999999999
        changed = {item: engine.context_at(rows, origin) for item, rows in mutated["items"].items()}
        self.assertEqual(original, changed)
        self.assertEqual(engine.rank_candidates(original, data["catalog"], 6, "liquidity_margin"),
                         engine.rank_candidates(changed, data["catalog"], 6, "liquidity_margin"))
        for rows in original.values():
            self.assertEqual(rows[-1]["timestamp"], origin - 2 * engine.STEP)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.data, _ = fixture(6)
        self.start = FINISH - session.TEST_STEPS * engine.STEP
        self.rankings = {}
        for step in range(4):
            origin = self.start + step * engine.STEP
            contexts = {item: engine.context_at(rows, origin) for item, rows in self.data["items"].items()}
            self.rankings[("liquidity_margin", origin)] = engine.rank_candidates(contexts, self.data["catalog"], 6 - step, "liquidity_margin")

    def simulate(self, scenario):
        return engine.simulate(self.data["items"], self.data["catalog"], self.rankings, self.start, "liquidity_margin", scenario)

    def test_tax_per_item_rounding_cap_and_exemptions(self):
        self.assertEqual(engine.tax(49, "Example"), 0)
        self.assertEqual(engine.tax(50, "Example"), 1)
        self.assertEqual(engine.tax(103000, "Example"), 2060)
        self.assertEqual(engine.tax(1_000_000_000, "Example"), 5_000_000)
        self.assertEqual(engine.tax(100, "Mind rune"), 0)
        self.assertEqual(engine.tax(1000, "Energy potion(4)"), 0)
        with self.assertRaises(ValueError):
            engine.tax(True, "Example")

    def test_initial_plan_cash_item_slot_and_shared_group_caps(self):
        candidates = self.rankings[("liquidity_margin", self.start)]
        plan = engine.starting_plan(candidates)
        self.assertEqual(len(plan), 4)
        self.assertLessEqual(sum(row["capitalGp"] for row in plan), 8_000_000)
        self.assertTrue(all(row["capitalGp"] <= 2_000_000 for row in plan))
        grouped = [{**row, "group": "shared", "groupLimit": 25} for row in candidates]
        self.assertEqual(sum(row["quantity"] for row in engine.starting_plan(grouped)), 25)

    def test_no_fills_means_no_profit_not_invented_market_execution(self):
        result = self.simulate("no_fills")
        self.assertEqual(result["cash_at_deadline_gp"], 10_000_000)
        self.assertEqual(result["simulated_realized_gp"], 0)
        self.assertEqual(result["bought_quantity"], 0)
        self.assertEqual(result["scenario_equity_change_gp"], 0)
        self.assertGreater(result["slot_minutes"], 0)

    def test_buys_without_sales_remain_inventory_not_cash_profit(self):
        result = self.simulate("buy_only_stress")
        self.assertGreater(result["bought_quantity"], 0)
        self.assertEqual(result["sold_quantity"], 0)
        self.assertEqual(result["simulated_realized_gp"], 0)
        self.assertGreater(result["inventory_cost_gp"], 0)
        self.assertLess(result["scenario_equity_change_gp"], 0)
        self.assertEqual(result["cash_at_deadline_gp"] + result["inventory_cost_gp"], 10_000_000)
        self.assertFalse(result["flat_at_deadline"])

    def test_cash_conservation_no_same_bucket_roundtrip_and_slot_bound(self):
        before = copy.deepcopy(self.rankings)
        result = self.simulate("reference_1pct")
        self.assertEqual(result["cash_at_deadline_gp"] + result["inventory_cost_gp"],
                         10_000_000 + result["simulated_realized_gp"])
        self.assertLessEqual(result["max_slots"], 6)
        self.assertTrue(result["flat_at_deadline"])
        self.assertGreater(result["simulated_realized_gp"], 0)
        for item in self.data["items"]:
            buys = [row["timestamp"] for row in result["events"] if row["item_id"] == item and row["type"] == "assumed_buy_fill"]
            sells = [row["timestamp"] for row in result["events"] if row["item_id"] == item and row["type"] == "assumed_sell_fill"]
            if sells:
                self.assertGreater(min(sells), min(buys))
        self.assertEqual(self.rankings, before)

    def test_partial_fills_compete_for_exit_slots_and_shared_limits_do_not_reset(self):
        for rows in self.data["items"].values():
            for row in rows:
                row["low_price_volume"] = 1000
                row["high_price_volume"] = 1000
        result = self.simulate("reference_1pct")
        self.assertEqual(result["max_slots"], 6)
        self.assertGreater(result["bought_quantity"], 0)
        for candidates in self.rankings.values():
            for row in candidates:
                row["group"], row["groupLimit"] = "one-family", 25
        limited = self.simulate("reference_1pct")
        self.assertLessEqual(limited["bought_quantity"], 25)

    def test_deadline_exit_can_realize_a_loss_and_uses_past_prices(self):
        for rows in self.data["items"].values():
            for row in rows:
                if row["timestamp"] >= self.start:
                    row["avg_low_price"] = 90000
                    row["avg_high_price"] = 90000
        result = self.simulate("reference_1pct")
        self.assertLess(result["simulated_realized_gp"], 0)
        self.assertTrue(result["flat_at_deadline"])
        sales = [row for row in result["events"] if row["type"] == "assumed_sell_fill"]
        self.assertTrue(sales)
        self.assertTrue(all(row["price"] == 90000 and row["timestamp"] >= self.start + 5 * engine.STEP for row in sales))

    def test_unobserved_exit_price_stays_unknown_not_fake_liquidation(self):
        deadline_context_stamp = self.start + 4 * engine.STEP
        for rows in self.data["items"].values():
            for row in rows:
                if row["timestamp"] == deadline_context_stamp:
                    row["avg_low_price"] = None
        result = self.simulate("buy_only_stress")
        self.assertGreater(result["unpriced_inventory_quantity"], 0)
        self.assertIsNone(result["scenario_equity_change_gp"])
        self.assertIsNone(result["scenario_inventory_mark_gp"])
        self.assertEqual(result["inventory_zero_value_floor_gp"], result["cash_at_deadline_gp"] - 10_000_000)

    def test_model_is_only_a_price_guard_not_a_fill_probability(self):
        contexts = {item: engine.context_at(rows, self.start) for item, rows in self.data["items"].items()}
        forecasts = {item: fake_paths([None])[0] for item in contexts}
        for paths in forecasts.values():
            paths["avg_high_price"][0] = [-300., -200., -100.]  # Withheld publication-gap step, not the target horizon.
        guarded = engine.rank_candidates(contexts, self.data["catalog"], 6, "chronos_guard", forecasts)
        self.assertTrue(guarded)
        self.assertTrue(all(row["sellPrice"] == 102900 for row in guarded))
        for paths in forecasts.values():
            paths["avg_high_price"] = [[99000, 100000, 101000]] * 7
        self.assertEqual(engine.rank_candidates(contexts, self.data["catalog"], 6, "chronos_guard", forecasts), [])
        forecasts[next(iter(forecasts))]["avg_high_price"][0] = [1, float("nan"), 3]
        with self.assertRaises(ValueError):
            engine.rank_candidates(contexts, self.data["catalog"], 6, "chronos_guard", forecasts)


class IntegrationTests(unittest.TestCase):
    def test_panel_export_matches_java_contract_fixtures(self):
        root = Path(__file__).resolve().parents[2] / "runelite-client/src/test/resources/net/runelite/client/plugins/geflipplanner"
        quote = {"itemId": 1, "name": "Synthetic contract item", "buyPrice": 100000, "sellPrice": 103000,
                 "quantity": 10, "capitalGp": 1000000, "taxPerItemGp": 2060, "netMarginPerItemGp": 940,
                 "group": "synthetic", "groupLimit": 70}
        now = datetime.fromisoformat("2026-11-02T21:00:00+00:00")
        as_of = datetime.fromisoformat("2026-11-02T20:59:00+00:00").timestamp()
        for mode in ("historical", "snapshot"):
            expected = json.loads((root / f"producer-{mode}-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(session.panel_plan([quote], as_of, now, mode), expected)

    def test_offline_model_and_identical_session_scenarios_without_latest_leakage(self):
        data, _ = fixture()
        for row in data["latest"].values():
            row["high"], row["low"] = 999999999, 888888888
        with tempfile.TemporaryDirectory() as temp, patch.object(session.chronos_backend, "ChronosForecaster") as model:
            model.return_value.predict_paths.side_effect = fake_paths
            model.return_value.provenance.return_value = {"synthetic_test": True}
            output = Path(temp) / "results"
            result = session.run_benchmark(data, "fixture-checksum", output, Path(temp) / "models")
            model.assert_called_once_with(Path(temp) / "models", offline=True)
            self.assertEqual(result["session_count"], 24)
            self.assertEqual(len(result["summary"]), 10)
            cases = model.return_value.predict_paths.call_args.args[0]
            for case in cases:
                self.assertEqual(case.context[-1]["timestamp"], case.target_start - 600)
                self.assertEqual(case.context[-1]["avg_high_price"], 103000)
            self.assertEqual(model.return_value.predict_paths.call_args.kwargs["prediction_length"], 7)
            sessions = json.loads((output / "sessions.json").read_text())
            masks = [{row["session_start"] for row in sessions if row["policy"] == policy and row["scenario"] == scenario}
                     for policy in engine.POLICIES for scenario in engine.SCENARIOS]
            self.assertTrue(all(mask == masks[0] for mask in masks))
            missing = next(row for row in sessions if row["policy"] == "liquidity_margin" and row["scenario"] == "reference_1pct")
            missing["scenario_equity_change_gp"] = None
            paired = [row for row in session.summarize(sessions) if row["scenario"] == "reference_1pct"]
            self.assertEqual([row["paired_marked_sessions"] for row in paired], [23, 23])
            self.assertEqual([row["unpriced_inventory_sessions"] for row in paired], [1, 0])
            plan = json.loads((output / "historical-plan.json").read_text())
            self.assertEqual(plan["mode"], "historical")
            self.assertFalse(plan["accountLimitsVerified"])
            self.assertIsNone(plan["expiresAt"])
            with self.assertRaisesRegex(ValueError, "Results exist"):
                session.run_benchmark(data, "fixture-checksum", output, Path(temp) / "models")
            self.assertEqual(model.call_count, 1)

    def test_snapshot_timestamp_expiry_and_stale_inputs_fail_before_model_load(self):
        data, _ = fixture()
        now = datetime.fromtimestamp(FINISH + 360, audit.UTC)
        with patch.object(session.chronos_backend, "ChronosForecaster") as model:
            model.return_value.predict_paths.side_effect = fake_paths
            plan = session.snapshot_plan(data, Path("models"), now)
            self.assertEqual(plan["mode"], "snapshot")
            self.assertTrue(plan["generatedAt"].endswith("Z"))
            self.assertTrue(plan["asOf"].endswith("Z"))
            self.assertGreater(session.date_time(plan["expiresAt"]), now)
            self.assertLessEqual(session.date_time(plan["expiresAt"]).timestamp(), FINISH + 900)
            self.assertFalse(plan["accountLimitsVerified"])
            self.assertLessEqual(sum(row["capitalGp"] for row in plan["candidates"]), 8_000_000)
            self.assertEqual(model.return_value.predict_paths.call_args.kwargs["prediction_length"], 8)
        with patch.object(session.chronos_backend, "ChronosForecaster") as model:
            with self.assertRaisesRegex(ValueError, "stale"):
                session.snapshot_plan(data, Path("models"), datetime.fromtimestamp(FINISH + 900, audit.UTC))
            changed = copy.deepcopy(data)
            changed["latest_source"]["retrieved_at"] = audit.iso(FINISH)
            with self.assertRaisesRegex(ValueError, "Latest-price"):
                session.snapshot_plan(changed, Path("models"), now)
            model.assert_not_called()

    def test_stale_per_item_latest_prices_produce_no_trade_and_no_model_load(self):
        data, _ = fixture()
        for row in data["latest"].values():
            row["lowTime"] = FINISH - 300
        with patch.object(session.chronos_backend, "ChronosForecaster") as model:
            plan = session.snapshot_plan(data, Path("models"), datetime.fromtimestamp(FINISH + 360, audit.UTC))
            self.assertEqual(plan["candidates"], [])
            model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
