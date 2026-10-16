import unittest

from source.common import db
from source.reporting import scenarios
from source.reporting.aggregate import build_summary
from tests.testing_utils import TempConfigTestCase


class TestScenarioStorage(TempConfigTestCase):
    def test_save_overwrites_by_name_and_round_trips(self):
        first = db.save_scenario("Retire at 60", {"retirement_year": "2030"})
        second = db.save_scenario("Retire at 60", {"retirement_year": "2031"})
        self.assertEqual(first, second)
        rows = db.list_scenarios()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["assumptions"], {"retirement_year": "2031"})

    def test_blank_name_is_rejected(self):
        with self.assertRaises(ValueError):
            db.save_scenario("  ", {})

    def test_delete(self):
        sid = db.save_scenario("A", {})
        self.assertTrue(db.delete_scenario(sid))
        self.assertFalse(db.delete_scenario(sid))
        self.assertEqual(db.list_scenarios(), [])

    def test_snapshot_keeps_only_scenario_keys_that_are_set(self):
        snap = scenarios.snapshot_assumptions(
            {"expected_return": 0.05, "retirement_year": "", "rental_taxable_schedule": "[]", "current_year": 2026}
        )
        self.assertEqual(snap, {"expected_return": 0.05})

    def test_restore_sets_saved_values_and_clears_the_rest(self):
        db.set_assumptions({"retirement_year": "2040", "expected_return": 0.07})
        sid = db.save_scenario("Early", {"retirement_year": "2030"})
        self.assertTrue(scenarios.restore_scenario(sid))
        a = db.get_assumptions()
        self.assertEqual(str(a["retirement_year"]), "2030")
        self.assertEqual(a["expected_return"], "")
        self.assertFalse(scenarios.restore_scenario(9999))


class TestCompare(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "401k", "balance": 1_000_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Living", "annual_amount": 60_000})
        db.set_assumptions({"iterations": 200, "plan_horizon_years": 30})

    def test_current_plan_comes_first_and_a_worse_scenario_has_lower_success(self):
        db.save_scenario("Poor returns", {"expected_return": "0.0", "iterations": "200"})
        results = scenarios.compare_scenarios(build_summary(), db.list_scenarios())
        self.assertEqual([r["name"] for r in results], ["Current plan", "Poor returns"])
        self.assertTrue(results[0]["current"])
        for r in results:
            for key in ("success_rate", "median_ending_balance", "p10_ending_balance", "drawdown_ending_total"):
                self.assertIn(key, r)
        self.assertLessEqual(results[1]["success_rate"], results[0]["success_rate"])
        self.assertLessEqual(results[1]["median_ending_balance"], results[0]["median_ending_balance"])
        self.assertIsNotNone(results[1]["drawdown_depleted_year"])

    def test_comparison_is_repeatable(self):
        db.save_scenario("X", {"expected_return": "0.04"})
        a = scenarios.compare_scenarios(build_summary(), db.list_scenarios())
        b = scenarios.compare_scenarios(build_summary(), db.list_scenarios())
        self.assertEqual(a[1]["success_rate"], b[1]["success_rate"])
        self.assertEqual(a[1]["median_ending_balance"], b[1]["median_ending_balance"])


if __name__ == "__main__":
    unittest.main()
