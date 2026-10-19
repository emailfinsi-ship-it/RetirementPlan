"""Which account to take this year's money from."""

from __future__ import annotations

import unittest

from source.reporting.withdrawal_order import best_split_this_year
from tests.test_dashboard import DashboardTestCase

A = {"inflation_rate": "0.03", "expected_return": "0.06", "current_year": "2026", "birth_year": "1966",
     "apply_drawdown_tax": "1", "retirement_year": "2026"}
POOLS = {"tax_deferred": 2_000_000, "roth": 300_000, "taxable": 1_500_000}


class TestBestSplit(unittest.TestCase):
    def test_never_costs_more_and_covers_the_need(self):
        r = best_split_this_year(pools=POOLS, expenses=[{"annual_amount": 420_000}], income=[], assumptions=A)
        self.assertLessEqual(r["best"]["tax"], r["usual"]["tax"])
        self.assertGreater(r["saved"], 0)
        for s in (r["usual"], r["best"]):
            self.assertAlmostEqual(s["tax_deferred"] + s["taxable"] + s["roth"] + r["rmd"], r["need"] + s["tax"], delta=2.0)

    def test_nothing_to_take_out(self):
        self.assertIsNone(best_split_this_year(pools=POOLS, expenses=[{"annual_amount": 10_000}],
                                               income=[{"name": "Pay", "annual_amount": 50_000}], assumptions={**A, "birth_year": "1990"}))

    def test_rmd_is_forced_from_tax_deferred(self):
        r = best_split_this_year(pools=POOLS, expenses=[{"annual_amount": 150_000}], income=[],
                                 assumptions={**A, "birth_year": "1950"})
        self.assertGreater(r["rmd"], 0)

    def test_tax_off_means_no_difference(self):
        r = best_split_this_year(pools=POOLS, expenses=[{"annual_amount": 200_000}], income=[], assumptions={**A, "apply_drawdown_tax": "0"})
        self.assertEqual(r["saved"], 0.0)


class TestCard(DashboardTestCase):
    def test_card_on_drawdown_page(self):
        self._post("/api/sample-data", {"with_linked": True})
        try:
            body = self._get("/drawdown-planning.html").read().decode("utf-8")
            self.assertIn('id="withdrawal-order"', body)
            self.assertIn("Which account should I take it from", body)
        finally:
            self._post("/api/sample-data", {"action": "remove"})


if __name__ == "__main__":
    unittest.main()
