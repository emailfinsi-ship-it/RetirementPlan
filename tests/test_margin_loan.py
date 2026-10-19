"""A negative holding can be tagged as a margin loan instead of nagging."""

from __future__ import annotations

import unittest

from source.common import demo_data, linked_data
from source.reporting import data_check as dc
from source.reporting import rebalance
from tests.test_dashboard import DashboardTestCase
from tests.test_data_check import pos


class TestMarginLoanLogic(unittest.TestCase):
    def setUp(self):
        self.positions = [
            pos("a", 300_000, "equity"),
            pos("b", 100_000, "etf"),
            pos("loan", -100_000, "cash", manual_sector="Margin loan"),
        ]

    def test_summary(self):
        s = rebalance.margin_loan_summary(self.positions)
        self.assertEqual(s["loan"], 100_000)
        self.assertEqual(s["holdings"], 400_000)
        self.assertEqual(s["net"], 300_000)
        self.assertAlmostEqual(s["pct_of_holdings"], 25.0)

    def test_none_when_untagged(self):
        self.assertIsNone(rebalance.margin_loan_summary([pos("a", 5, "equity"), pos("c", -5, "cash")]))

    def test_tagged_loan_is_not_a_warning_but_gets_an_info_line(self):
        ids = {i["id"]: i for i in dc.check_positions(self.positions)}
        self.assertNotIn("negative-holdings", ids)
        self.assertEqual(ids["margin-loan"]["level"], "info")
        self.assertIn("$300,000", ids["margin-loan"]["detail"])

    def test_untagged_negative_still_flagged_and_points_to_the_button(self):
        issues = dc.check_positions([pos("a", 100), pos("c", -50, "cash")])
        neg = next(i for i in issues if i["id"] == "negative-holdings")
        self.assertIn("Mark as margin loan", neg["detail"])

    def test_mix_ignores_the_loan(self):
        plan = rebalance.build_plan(self.positions, rebalance.risk_target("moderate", 50))
        self.assertEqual(plan["total"], 400_000)


class TestMarginLoanPages(DashboardTestCase):
    def tearDown(self):
        demo_data.remove_sample_data()

    def test_button_then_tagged_everywhere(self):
        demo_data.seed_sample_household(with_linked=True)
        neg = next(p for p in linked_data.read_linked_portfolio_positions() if p["market_value"] < 0)
        body = self._get("/linked-positions.html").read().decode("utf-8")
        self.assertIn("Mark as margin loan", body)
        status, d = self._post("/api/classify-sector", {
            "items": [{"security_id": neg["security_id"], "ticker": neg["ticker"]}], "sector": "Margin loan"})
        self.assertEqual(status, 200)
        body = self._get("/linked-positions.html").read().decode("utf-8")
        self.assertNotIn("Mark as margin loan</button>", body)
        self.assertIn("Margin loan</span>", body)
        summary = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("Margin loan tagged", summary)
        self.assertNotIn("holding with a negative value", summary)
        page = self._get("/rebalance.html").read().decode("utf-8")
        self.assertIn('id="margin-loan"', page)
        self.assertIn("borrowed", page)


if __name__ == "__main__":
    unittest.main()
