import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audit
import budget30
import budget_selection as selection
import expanded
import session30 as session
import session_engine as engine
from test_session30 import FINISH, START, FiveMinuteClient, fake_paths, fixture


def observation(low: float = 100000, high: float = 110000, volume: float = 10000) -> dict[str, float | None]:
    return {"avgLowPrice": low, "avgHighPrice": high, "lowPriceVolume": volume, "highPriceVolume": volume}


def inputs():
    mapping = [{"id": 1, "name": "Liquid item", "limit": 1000},
               {"id": 2, "name": "Wide but thin", "limit": 1000}]
    buckets = [{"1": observation(), "2": observation(100, 200, 50)} for _ in range(6)]
    return buckets, mapping


def control_fixture(root):
    data, client = fixture()
    session.export_dataset(data, root / "dataset")
    _, checksum = session.load_dataset(root / "dataset")
    for url in list(client.urls):
        name = hashlib.sha256(url.encode()).hexdigest() + ".json"
        budget30.save(root / "cache" / name, client.get(url))
    with patch.object(session.chronos_backend, "ChronosForecaster") as model:
        model.return_value.predict_paths.side_effect = fake_paths
        model.return_value.provenance.return_value = {"synthetic_test": True}
        session.run_benchmark(data, checksum, root / "results", root / "models")
    return data


class SelectionTests(unittest.TestCase):
    def test_ranks_net_gp_capacity_not_percentage_and_is_order_independent(self):
        buckets, mapping = inputs()
        chosen, counts = selection.select_items(buckets, mapping)
        self.assertEqual([row["item_id"] for row in chosen], [1, 2])
        self.assertEqual(chosen[0]["quantity"], 20)
        self.assertEqual(chosen[0]["net_margin_per_item_gp"], 7800)
        self.assertEqual(chosen[0]["quoted_net_capacity_gp"], 156000)
        shuffled = [dict(reversed(list(bucket.items()))) for bucket in reversed(buckets)]
        self.assertEqual(selection.select_items(shuffled, list(reversed(mapping))), (chosen, counts))

    def test_spread_must_persist_and_rounding_and_tax_are_applied(self):
        buckets, mapping = inputs()
        buckets[0]["1"] = observation(109000, 120000)
        selected, counts = selection.select_items(buckets, mapping)
        self.assertEqual([row["item_id"] for row in selected], [2])
        self.assertEqual(counts["rejected"]["no_persistent_net_spread"], 1)
        buckets = [{"1": observation(100000.1, 102041.9)} for _ in range(6)]
        selected, _ = selection.select_items(buckets, mapping)
        self.assertEqual(selected, [])  # ceil low + floor high + per-item tax leaves no net margin.

    def test_missing_null_and_zero_do_not_become_liquidity(self):
        for change in ("absent", "null", "zero"):
            buckets, mapping = inputs()
            if change == "absent":
                del buckets[0]["1"]
            else:
                buckets[0]["1"]["highPriceVolume"] = None if change == "null" else 0
            chosen, counts = selection.select_items(buckets, mapping)
            self.assertEqual([row["item_id"] for row in chosen], [2])
            self.assertEqual(counts["rejected"]["missing_null_or_inactive_bucket"], 1)

    def test_budget_mapping_and_tax_filters_without_padding(self):
        buckets, mapping = inputs()
        mapping.extend([{"id": 3, "name": "Unknown"}, {"id": 4, "name": "Old school bond", "limit": 100}])
        for bucket in buckets:
            bucket["1"] = observation(2_000_001, 3_000_000)
            bucket["3"], bucket["4"] = observation(), observation()
        chosen, counts = selection.select_items(buckets, mapping)
        self.assertEqual([row["item_id"] for row in chosen], [2])
        self.assertEqual(counts["rejected"], {"bond": 1, "missing_mapping_or_limit": 1, "over_item_budget": 1})
        mapping[1]["name"] = "Mind rune"
        chosen, _ = selection.select_items(buckets, mapping)
        self.assertEqual(chosen[0]["net_margin_per_item_gp"], 100)  # Exemption is explicit, not tax-free for every item.

    def test_zero_mapping_limit_is_ineligible_not_invalid_or_invented(self):
        buckets, mapping = inputs()
        mapping[0]["limit"] = 0
        chosen, counts = selection.select_items(buckets, mapping)
        self.assertEqual([row["item_id"] for row in chosen], [2])
        self.assertEqual(counts["rejected"]["missing_mapping_or_limit"], 1)
        mapping[0]["limit"] = -1
        with self.assertRaisesRegex(ValueError, "Invalid mapping limit"):
            selection.select_items(buckets, mapping)

    def test_known_family_limit_uses_full_mapping_and_one_variant(self):
        mapping = [{"id": 1, "name": "Example potion(4)", "limit": 100},
                   {"id": 2, "name": "Example potion(3)", "limit": 100},
                   {"id": 3, "name": "Example potion(1)", "limit": 2}]
        buckets = [{"1": observation(), "2": observation(100000, 109000)} for _ in range(6)]
        chosen, counts = selection.select_items(buckets, mapping)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0]["item_id"], 1)
        self.assertEqual(chosen[0]["quantity"], 2)
        self.assertEqual(chosen[0]["group_limit"], 2)
        self.assertEqual(counts["rejected"]["duplicate_family"], 1)

    def test_top_50_bounded_and_capital_allocation_remains_unchanged(self):
        mapping = [{"id": i, "name": f"Item {i}", "limit": 100000} for i in range(1, 61)]
        buckets = [{str(i): observation(volume=100000) for i in range(1, 61)} for _ in range(6)]
        chosen, counts = selection.select_items(buckets, mapping)
        self.assertEqual([row["item_id"] for row in chosen], list(range(1, 51)))
        self.assertEqual(counts["rejected"]["outside_top_50"], 10)
        self.assertTrue(all(row["capital_gp"] == 2000000 for row in chosen))

    def test_bad_values_schema_and_ids_fail_not_silently_drop(self):
        for value in (-1, float("nan"), True):
            buckets, mapping = inputs()
            buckets[0]["1"]["lowPriceVolume"] = value
            with self.assertRaises(ValueError):
                selection.select_items(buckets, mapping)
        buckets, mapping = inputs()
        del buckets[0]["1"]["avgLowPrice"]
        with self.assertRaises(ValueError):
            selection.select_items(buckets, mapping)
        buckets, mapping = inputs()
        buckets[0]["01"] = observation()
        with self.assertRaises(ValueError):
            selection.select_items(buckets, mapping)

    def test_frozen_plan_binds_cutoff_parameters_and_targets(self):
        data, _ = fixture()
        plan = selection.make_plan(data, "a" * 64)
        self.assertEqual(plan["selection_stamps"][-1] + 2 * engine.STEP, plan["test_start"])
        for field, value in (("test_start", plan["test_start"] + 300), ("target_return_bps", [1000]),
                             ("selection_stamps", list(range(6))), ("control_dataset_sha256", "wrong")):
            changed = {**plan, field: value}
            with self.assertRaises(ValueError):
                selection.validate_plan(changed)
        changed = copy.deepcopy(plan)
        changed["rules"]["participation_bps"] = 500
        with self.assertRaises(ValueError):
            selection.validate_plan(changed)

    def test_bucket_substitution_future_retrieval_and_rate_limit_stop(self):
        data, _ = fixture()
        plan = selection.make_plan(data, "a" * 64)
        buckets, mapping = inputs()
        mapping_record = {"url": "mapping", "fetched_at": audit.iso(FINISH), "payload": mapping}
        for failure in ("substitution", "early", "429"):
            calls = []

            class Client:
                def get(self, url):
                    calls.append(url)
                    if failure == "429":
                        return {"status": 429, "error": "rate limited"}
                    stamp = int(url.split("=")[-1])
                    return {"url": url, "status": 200, "fetched_at": audit.iso(stamp if failure == "early" else FINISH),
                            "payload": {"timestamp": stamp + (300 if failure == "substitution" else 0), "data": buckets[0]}}

            with self.assertRaises(ValueError):
                selection.freeze_cohort(Client(), plan, mapping_record)
            self.assertEqual(len(calls), 1)


class WorkflowTests(unittest.TestCase):
    def test_collect_freezes_before_network_reuses_control_cache_and_offline_benchmark(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            control, root = Path(temp) / "control", Path(temp) / "budget"
            data = control_fixture(control)
            real_client = audit.Client
            urls = []

            class Client(real_client):
                def get(self, url):
                    if "/5m?" not in url:
                        return super().get(url)
                    self_plan = json.loads((root / "plan.json").read_text())
                    selection.validate_plan(self_plan)  # Rules are on disk before the first new price request.
                    urls.append(url)
                    stamp = int(url.split("=")[-1])
                    return {"url": url, "status": 200, "cached": True, "fetched_at": audit.iso(FINISH + 300),
                            "payload": {"timestamp": stamp, "data": {str(item): observation() for item in data["items"]}}}

            with patch.object(audit, "Client", Client):
                budget30.collect(root, control, offline=True)
            self.assertEqual(len(urls), 6)
            chosen, checksum = session.load_dataset(root / "dataset")
            self.assertEqual(chosen["end"], data["end"])
            self.assertEqual(chosen["sources"], [next(s for s in data["sources"] if s["item_id"] == i) for i in chosen["items"]])
            with self.assertRaisesRegex(ValueError, "already exists"):
                budget30.collect(root, control)
            with patch.object(session.chronos_backend, "ChronosForecaster") as model:
                model.return_value.predict_paths.side_effect = fake_paths
                model.return_value.provenance.return_value = {"synthetic_test": True}
                result = budget30.benchmark(root, control, root / "models")
                model.assert_called_once_with(root / "models", offline=True)
                self.assertEqual(result["dataset_sha256"]["budget"], checksum)
                self.assertEqual(len(result["summary"]), 20)
                with self.assertRaisesRegex(ValueError, "already exist"):
                    budget30.benchmark(root, control, root / "models")
                self.assertEqual(model.call_count, 1)

    def test_control_changes_block_before_collection_or_inference(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            control, root = Path(temp) / "control", Path(temp) / "budget"
            control_fixture(control)
            budget30.bound_plan(root, control)
            path = control / "results" / "sessions.json"
            path.write_text(path.read_text() + " ")
            with patch.object(audit.Client, "get") as fetch, patch.object(session.chronos_backend, "ChronosForecaster") as model:
                with self.assertRaisesRegex(ValueError, "changed"):
                    budget30.collect(root, control)
                fetch.assert_not_called()
                model.assert_not_called()

    def test_new_histories_trim_to_fixed_end_without_relabelling_or_limit_inflation(self):
        data, _ = fixture()
        ids = list(data["items"])
        plan = selection.make_plan(data, "a" * 64)
        base_client = FiveMinuteClient(ids)
        mapping = base_client.get(audit.WIKI + "/mapping")
        mapping["payload"].append({"id": 999999, "name": f"Item {ids[0]}(1)", "limit": 2})

        class Buckets:
            def get(self, url):
                return {"url": url, "status": 200, "fetched_at": audit.iso(FINISH + 900),
                        "payload": {"timestamp": int(url.split("=")[-1]), "data": {str(i): observation() for i in ids}}}

        cohort = selection.freeze_cohort(Buckets(), plan, mapping)

        class LaterClient(FiveMinuteClient):
            def get(self, url):
                if url.endswith("/mapping"):
                    return mapping
                record = super().get(url)
                if "timeseries" in url:
                    record["fetched_at"] = audit.iso(FINISH + 900)
                    record["payload"]["startTimestamp"] += 600
                    record["payload"]["endTimestamp"] += 600
                    for row in record["payload"]["data"]:
                        row["timestamp"] += 600
                return record

        with contextlib.redirect_stdout(io.StringIO()):
            selected = session.collect(LaterClient(ids), cohort)
        self.assertEqual(selected["start"], START + 600)
        self.assertEqual(selected["end"], FINISH)
        self.assertEqual(selected["catalog"][ids[0]]["group_limit"], 2)
        self.assertTrue(all(rows[-1]["timestamp"] == FINISH - 300 for rows in selected["items"].values()))

    def test_comparison_pairs_all_four_arms_and_targets_require_full_exit(self):
        data, _ = fixture()
        plan = selection.make_plan(data, "a" * 64)
        rows = []
        for start in range(plan["test_start"], plan["anchor_end"], 1800):
            for policy in engine.POLICIES:
                for scenario in engine.SCENARIOS:
                    rows.append({"session_start": start, "policy": policy, "scenario": scenario,
                                 "scenario_equity_change_gp": 500000, "simulated_realized_gp": 500000,
                                 "capital_minutes_gp": 240000000, "inventory_cost_gp": 0, "cash_change_gp": 500000,
                                 "inventory_zero_value_floor_gp": 500000, "flat_at_deadline": True, "bought_quantity": 10})
        budget = copy.deepcopy(rows)
        affected = next(row for row in budget if row["policy"] == "chronos_guard" and row["scenario"] == "reference_1pct")
        affected.update(scenario_equity_change_gp=None, flat_at_deadline=False, inventory_cost_gp=1000000)
        result = budget30.compare({"generic": rows, "budget": budget}, plan)
        reference = [row for row in result["summary"] if row["scenario"] == "reference_1pct"]
        self.assertEqual([row["paired_marked_sessions"] for row in reference], [23] * 4)
        self.assertEqual([row["fully_exited_target_sessions"]["500"] for row in reference], [24, 24, 24, 23])
        with self.assertRaisesRegex(ValueError, "identical complete"):
            budget30.compare({"generic": rows, "budget": budget[:-1]}, plan)


if __name__ == "__main__":
    unittest.main()
