"""Ticking "In the plan?" on a property shows up on the Summary."""

from __future__ import annotations

import unittest

from source.common import db, demo_data
from source.reporting import progress
from tests.test_dashboard import DashboardTestCase


def summary(equity_total, in_plan, liquid=1_000_000.0):
    return {
        "next_year_expense_need": 100_000.0, "net_liquid_asset": liquid, "this_year": 2026,
        "assumptions": {"inflation_rate": 0.03, "expected_return": 0.06},
        "income_for_simulation": [], "real_estate_equity_total": equity_total,
        "retirement_pools": {"real_estate": in_plan},
    }


class TestProgress(unittest.TestCase):
    def test_ticked_equity_counts_as_savings_and_leaves_the_cushion(self):
        none = progress.independence_progress(summary(500_000.0, 0.0))
        some = progress.independence_progress(summary(500_000.0, 300_000.0))
        self.assertEqual(none["savings"], 1_000_000.0)
        self.assertEqual(none["equity"], 500_000.0)
        self.assertEqual(some["savings"], 1_300_000.0)
        self.assertEqual(some["equity"], 200_000.0)
        self.assertEqual(some["in_plan_equity"], 300_000.0)
        self.assertGreater(some["pct"], none["pct"])


class TestSummaryShowsIt(DashboardTestCase):
    def tearDown(self):
        demo_data.remove_sample_data()

    def test_tick_then_summary_mentions_it(self):
        demo_data.seed_sample_household(with_linked=True)
        rows = db.list_line_items("real_estate")
        for r in rows:
            db.update_line_item("real_estate", r["id"], {"include_in_monte_carlo": 0})
        page = self._get("/summary.html").read().decode("utf-8")
        self.assertNotIn("In the plan?", page.split("Where you stand")[0])
        status, d = self._post("/api/line-item/update", {
            "section": "real_estate", "id": rows[0]["id"], "fields": {"include_in_monte_carlo": 1}})
        self.assertEqual(status, 200)
        page = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("of home equity you marked", page)
        self.assertGreaterEqual(page.count("In the plan?"), 2)   # the hero line and the FI card


if __name__ == "__main__":
    unittest.main()
