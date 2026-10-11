"""Behavioral tests: temporal integrity and physical/financial feasibility."""
import csv
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from apps.api.engine import forecast, history_coverage, procurement, validate_forecast_history


def historical_sales(zero=False):
    first = date(2025, 1, 1)
    return [{"date": (first + timedelta(days=day)).isoformat(), "branch_id": "1",
             "meal_id": meal, "units_sold": 0 if zero else 20 + int(meal) * 3 + day % 7}
            for day in range(112) for meal in ("1", "2")]


class ForecastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = historical_sales()
        cls.origin = max(row["date"] for row in cls.rows)
        cls.baseline = forecast(cls.rows, "1", cls.origin)

    def test_common_temporal_test_and_honest_baseline_intervals(self):
        result = self.baseline
        self.assertEqual(result["metadata"]["test_observations"], 56)
        bounds = {(item["test_start"], item["test_end"], item["n_observations"])
                  for item in result["metrics"]}
        self.assertEqual(len(bounds), 1)
        self.assertLess(result["metadata"]["train_end"], result["metadata"]["test_start"])
        self.assertEqual(result["selected_model_metrics"]["mae"], 0)
        self.assertIsNone(result["selected_model_metrics"]["coverage"])
        for item in result["predictions"]:
            self.assertIsNone(item["p10"])
            self.assertIsNone(item["p50"])
            self.assertIsNone(item["p90"])

    def test_future_sales_and_oracle_columns_cannot_change_historical_run(self):
        poisoned = deepcopy(self.rows)
        for row in poisoned:
            row["latent_demand_ORACLE_ONLY"] = 9000000
            row["base_daily_demand"] = 8888888
            row["available_portions"] = 7777777
        poisoned += [{"date": "2025-12-31", "branch_id": "1", "meal_id": "1", "units_sold": 999999}]
        recomputed = forecast(poisoned, "1", self.origin)
        self.assertEqual(recomputed["predictions"], self.baseline["predictions"])
        self.assertEqual(recomputed["metrics"], self.baseline["metrics"])
        self.assertEqual(recomputed["metadata"]["data_hash"], self.baseline["metadata"]["data_hash"])
        self.assertFalse(any("oracle" in feature.lower() for feature in recomputed["metadata"]["features"]))

    def test_hgb_quantiles_are_nonnegative_and_ordered(self):
        result = forecast(self.rows, "1", self.origin, "hist_gradient_boosting")
        self.assertEqual(result["metadata"]["final_fit_end"], self.origin)
        for prediction in result["predictions"]:
            self.assertGreaterEqual(prediction["point_forecast"], 0)
            self.assertGreaterEqual(prediction["p10"], 0)
            self.assertLessEqual(prediction["p10"], prediction["p50"])
            self.assertLessEqual(prediction["p50"], prediction["p90"])
        self.assertEqual(result["selected_model_metrics"]["nominal_coverage"], 0.8)
        self.assertGreaterEqual(result["selected_model_metrics"]["crossing_rate"], 0)

    def test_zero_test_sales_has_null_wape(self):
        result = forecast(historical_sales(zero=True), "1", self.origin)
        for metric in result["metrics"]:
            self.assertIsNone(metric["wape"])
            self.assertIn("zero", metric["wape_notice"])

    def test_missing_dates_and_duplicates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing daily sales"):
            forecast(self.rows[:2] + self.rows[3:], "1", self.origin)
        with self.assertRaisesRegex(ValueError, "Duplicate sales"):
            forecast(self.rows + [self.rows[0]], "1", self.origin)


class HistoryCoverageTests(unittest.TestCase):
    """Diagnostics explain a refusal; validate_forecast_history stays the only rule."""

    def rows(self, meal, days, *, origin=date(2025, 6, 30), skip=(), branch="1"):
        return [{"date": (origin - timedelta(days=offset)).isoformat(), "branch_id": branch, "meal_id": meal,
                 "units_sold": 3} for offset in range(days) if offset not in skip]

    def test_each_meal_reports_its_first_problem_without_inventing_zero_days(self):
        origin = date(2025, 6, 30)
        sales = (self.rows("ready", 90) + self.rows("new", 30) + self.rows("gap", 100, skip={60})
                 + [row for row in self.rows("ended", 120) if row["date"] <= "2025-06-25"]
                 + self.rows("ready", 90, branch="2") + [{"date": "2025-07-01", "branch_id": "1", "meal_id": "ready", "units_sold": 9}])
        with self.assertRaises(ValueError):
            validate_forecast_history(sales, "1", origin.isoformat())
        coverage = history_coverage(sales, "1", origin.isoformat())
        meals = {item["meal_id"]: item for item in coverage["meals"]}
        self.assertEqual((coverage["origin"], coverage["required_days"], coverage["ready_meals"]), ("2025-06-30", 84, 1))
        self.assertEqual(list(meals), ["ended", "gap", "new", "ready"])
        self.assertEqual({key: item["status"] for key, item in meals.items()},
                         {"ready": "ready", "new": "too_short", "gap": "gap", "ended": "ended"})
        self.assertEqual((meals["ready"]["observed_days"], meals["ready"]["last_date"]), (90, "2025-06-30"))
        self.assertEqual(meals["new"]["continuous_days_through_origin"], 30)
        self.assertEqual((meals["gap"]["first_missing_date"], meals["gap"]["missing_days"], meals["gap"]["observed_days"]),
                         ((origin - timedelta(days=60)).isoformat(), 1, 99))
        self.assertEqual(meals["gap"]["continuous_days_through_origin"], 60)
        self.assertEqual((meals["ended"]["last_date"], meals["ended"]["first_missing_date"],
                          meals["ended"]["continuous_days_through_origin"]), ("2025-06-25", "2025-06-26", 0))

    def test_ready_coverage_matches_the_validation_rule(self):
        sales = self.rows("1", 84) + self.rows("2", 120)
        self.assertEqual(validate_forecast_history(sales, "1", "2025-06-30")["meal_count"], 2)
        coverage = history_coverage(sales, "1", "2025-06-30")
        self.assertEqual(coverage["ready_meals"], 2)
        self.assertTrue(all(item["status"] == "ready" and item["missing_days"] == 0 for item in coverage["meals"]))
        short = self.rows("1", 83)
        with self.assertRaises(ValueError):
            validate_forecast_history(short, "1", "2025-06-30")
        self.assertEqual(history_coverage(short, "1", "2025-06-30")["meals"][0]["status"], "too_short")


class ProcurementTests(unittest.TestCase):
    def setUp(self):
        self.prediction = {"branch_id": "1", "target_date": "2026-01-01", "predictions": [
            {"meal_id": "1", "point_forecast": 10, "p10": None, "p50": None, "p90": None}]}
        self.ingredients = [{"ingredient_id": "1", "ingredient_name": "Rice", "unit": "kg",
                             "yield_factor": "0.5", "storage_capacity": "30"}]
        self.recipes = [{"meal_id": "1", "ingredient_id": "1", "net_qty_per_portion": "0.25"}]
        self.inventory = [{"branch_id": "1", "ingredient_id": "1", "lot_id": "usable",
                           "snapshot_date": "2026-01-01", "expiry_date": "2026-01-01",
                           "on_hand_qty": "1", "unit": "kg"},
                          {"branch_id": "1", "ingredient_id": "1", "lot_id": "expired",
                           "snapshot_date": "2026-01-01", "expiry_date": "2025-12-31",
                           "on_hand_qty": "100", "unit": "kg"}]
        self.suppliers = [{"supplier_id": "1", "supplier_name": "A", "lead_time_days": 9},
                          {"supplier_id": "2", "supplier_name": "B", "lead_time_days": 0}]
        self.offers = [{"supplier_id": "1", "ingredient_id": "1", "pack_qty": "2",
                        "unit_cost_kzt": "3.25", "min_packs": 2, "max_packs": 10, "lead_time_days": 0},
                       {"supplier_id": "2", "ingredient_id": "1", "pack_qty": "10",
                        "unit_cost_kzt": "0.01", "min_packs": 1, "max_packs": 10, "lead_time_days": 1}]

    def plan(self, budget="100", **overrides):
        arguments = dict(forecast_result=self.prediction, ingredients=self.ingredients,
                         recipes=self.recipes, inventory=self.inventory, offers=self.offers,
                         suppliers=self.suppliers, branch_id="1", target_date="2026-01-01",
                         budget=budget, strategy="point")
        arguments.update(overrides)
        return procurement(**arguments)

    def test_yield_once_expiry_boundary_moq_unit_price_and_offer_lead_time(self):
        result = self.plan()
        requirement = result["requirements"][0]
        self.assertEqual(Decimal(requirement["net_required"]), Decimal("2.5"))
        self.assertEqual(Decimal(requirement["gross_required"]), Decimal("5"))
        self.assertEqual(Decimal(requirement["usable_stock"]), Decimal("1"))
        self.assertEqual(Decimal(requirement["required_purchase"]), Decimal("4"))
        self.assertEqual(result["expired_lot_ids"], ["expired"])
        self.assertEqual(result["lines"][0]["supplier_id"], "1")
        self.assertEqual(result["lines"][0]["packs"], 2)
        self.assertEqual(Decimal(result["total_cost"]), Decimal("13.00"))
        self.assertEqual(result["shortage_count"], 0)
        self.assertEqual(result["solver_status"], "optimal")
        self.assertTrue(result["constraints_valid"])

    def test_zero_budget_is_a_valid_explicit_shortage(self):
        result = self.plan(budget="0")
        self.assertEqual(Decimal(result["total_cost"]), 0)
        self.assertEqual(result["lines"], [])
        self.assertEqual(result["shortage_count"], 1)
        self.assertEqual(Decimal(result["requirements"][0]["shortage_qty"]), 4)
        self.assertTrue(result["constraints_valid"])
        self.assertTrue(any("zero" in warning for warning in result["warnings"]))

    def test_capacity_and_moq_cannot_be_violated_to_hide_shortage(self):
        self.ingredients[0]["storage_capacity"] = "4"
        result = self.plan()
        self.assertEqual(result["lines"], [])  # MOQ of 2 packs would require 1 + 4 > 4 kg.
        self.assertEqual(result["shortage_count"], 1)
        self.assertTrue(result["constraints_valid"])

    def test_budget_below_moq_cost_retains_shortage(self):
        result = self.plan(budget="12.99")
        self.assertEqual(result["lines"], [])
        self.assertEqual(Decimal(result["remaining_budget"]), Decimal("12.99"))
        self.assertEqual(result["shortage_count"], 1)

    def test_missing_supplier_and_no_eligible_offers_are_visible(self):
        result = self.plan(suppliers=[])
        self.assertEqual(result["solver_status"], "no_eligible_offers")
        self.assertEqual(result["shortage_count"], 1)
        self.assertTrue(all(item["reason"] == "unknown_supplier" for item in result["excluded_offers"]))

    def test_snapshot_mismatch_and_baseline_quantile_strategy_rejected(self):
        stale = deepcopy(self.inventory)
        for row in stale:
            row["snapshot_date"] = "2025-12-31"
        with self.assertRaisesRegex(ValueError, "No inventory snapshot"):
            self.plan(inventory=stale)
        with self.assertRaisesRegex(ValueError, "requires available model quantiles"):
            self.plan(strategy="p90_stress")

    def test_time_limit_valid_incumbent_and_invalid_incumbent_fallback(self):
        feasible = SimpleNamespace(x=np.array([2.0, 1.0, 0.0]), status=1, message="Time limit reached")
        with patch("apps.api.engine.milp", return_value=feasible):
            result = self.plan()
        self.assertEqual(result["solver_status"], "feasible_time_limit")
        self.assertEqual(Decimal(result["total_cost"]), 13)
        fractional = SimpleNamespace(x=np.array([1.5, 1.0, 1.0]), status=1, message="Time limit reached")
        with patch("apps.api.engine.milp", return_value=fractional):
            fallback = self.plan()
        self.assertEqual(fallback["solver_status"], "fallback_no_valid_incumbent")
        self.assertTrue(fallback["constraints_valid"])
        self.assertEqual(fallback["shortage_count"], 1)
        self.assertEqual(fallback["lines"], [])

    def test_bad_solver_budget_incumbent_is_independently_rejected(self):
        expensive = SimpleNamespace(x=np.array([2.0, 1.0, 0.0]), status=0, message="Optimal")
        with patch("apps.api.engine.milp", return_value=expensive):
            result = self.plan(budget="12.99")
        self.assertEqual(result["solver_status"], "fallback_no_valid_incumbent")
        self.assertEqual(Decimal(result["total_cost"]), 0)
        self.assertIn("Exact decimal total exceeds the budget", result["solver"]["incumbent_errors"])

    def test_full_synthetic_data_forecast_and_plan_are_feasible(self):
        root = Path(__file__).resolve().parents[1] / "data" / "raw"
        def read(name):
            with (root / f"{name}.csv").open(encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))
        prediction = forecast(read("daily_sales"), "1")
        result = procurement(prediction, read("ingredients"), read("recipes"),
                             read("inventory_lots"), read("supplier_offers"),
                             read("suppliers"), "1", "2026-01-01", "200000")
        self.assertEqual(len(prediction["predictions"]), 12)
        self.assertEqual(prediction["metadata"]["test_observations"], 336)
        self.assertEqual({row["unit"] for row in result["requirements"]}, {"kg", "L"})
        self.assertTrue(result["constraints_valid"])
        self.assertLessEqual(Decimal(result["total_cost"]), Decimal("200000"))
        self.assertEqual(sum(Decimal(line["line_cost_kzt"]) for line in result["lines"]),
                         Decimal(result["total_cost"]))
        for row in result["requirements"]:
            self.assertLessEqual(Decimal(row["usable_stock"]) + Decimal(row["purchased_qty"]),
                                 Decimal(row["storage_capacity"]))
        for line in result["lines"]:
            self.assertEqual(line["lead_time_days"], 0)
            self.assertIsInstance(line["packs"], int)
            self.assertGreaterEqual(line["packs"], line["min_packs"])
            self.assertLessEqual(line["packs"], line["max_packs"])


if __name__ == "__main__":
    unittest.main()
