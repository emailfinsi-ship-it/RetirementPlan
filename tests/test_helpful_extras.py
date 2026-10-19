"""Safe spending, independence progress, since-last-month card, portfolio
check-up, scenario comparison cards and the hover-help glossary."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from source.common import db, demo_data
from source.reporting import portfolio_checkup as pc
from source.reporting import progress, what_if
from source.reporting.aggregate import build_summary
from tests.test_dashboard import DashboardTestCase


class TestProgressFunctions(unittest.TestCase):
    def test_independence_progress_reached_and_year(self):
        s = {"next_year_expense_need": 100_000, "net_liquid_asset": 1_250_000, "this_year": 2026,
             "assumptions": {"expected_return": 0.06, "inflation_rate": 0.03}}
        p = progress.independence_progress(s)
        self.assertAlmostEqual(p["pct"], 50.0)
        self.assertFalse(p["reached"])
        self.assertGreater(p["year"], 2026)
        s["net_liquid_asset"] = 2_600_000
        self.assertTrue(progress.independence_progress(s)["reached"])
        s["next_year_expense_need"] = 0
        self.assertIsNone(progress.independence_progress(s))

    def test_independence_counts_income_that_has_started_and_keeps_home_equity_separate(self):
        income = [{"name": "Rent", "annual_amount": 60_000, "start_year": 2026, "end_year": None, "inflates": 0,
                   "base_year": None, "include_in_monte_carlo": 1},
                  {"name": "Social Security", "annual_amount": 30_000, "start_year": 2035, "end_year": None, "inflates": 0,
                   "base_year": None, "include_in_monte_carlo": 1}]
        s = {"next_year_expense_need": 100_000, "net_liquid_asset": 1_000_000, "this_year": 2026,
             "income_for_simulation": income, "real_estate_equity_total": 500_000,
             "assumptions": {"expected_return": 0.06, "inflation_rate": 0.03}}
        p = progress.independence_progress(s)
        self.assertAlmostEqual(p["income"], 60_000)       # rent counts, Social Security (starts 2035) does not yet
        self.assertAlmostEqual(p["need"], 40_000)
        self.assertAlmostEqual(p["target"], 1_000_000)    # 25 x the part income does not cover
        self.assertAlmostEqual(p["pct"], 100.0)
        self.assertEqual(p["equity"], 500_000)            # reported, never added to savings
        s["income_for_simulation"][0]["annual_amount"] = 150_000  # income above spending
        p = progress.independence_progress(s)
        self.assertEqual(p["need"], 0)
        self.assertTrue(p["reached"])
        self.assertEqual(p["pct"], 100.0)

    def test_since_then_breaks_down_the_change(self):
        today = date(2026, 10, 18)
        snaps = [{"snapshot_date": "2026-09-10", "net_worth": 1_000_000, "retirement_liquid_total": 600_000,
                  "real_estate_equity_total": 300_000, "liability_total": 20_000}]
        now = {"net_worth": 1_080_000, "retirement_liquid_total": 650_000, "real_estate_equity_total": 310_000,
               "liability_total": 10_000}
        r = progress.since_then(snaps, now, {"2026-09-10": 0.9}, today)
        self.assertAlmostEqual(r["net_change"], 80_000)
        names = [n for n, _ in r["parts"]]
        self.assertEqual(names[0], "Investments & savings")
        self.assertEqual(r["rate_then"], 0.9)
        self.assertIsNone(progress.since_then([], now, {}, today))
        # a snapshot from today or yesterday is too recent to compare with
        self.assertIsNone(progress.since_then([{**snaps[0], "snapshot_date": "2026-10-17"}], now, {}, today))

    def test_portfolio_checkup_flags(self):
        rows = [
            {"market_value": 60_000, "ticker": "AAPL", "security_type": "Equity", "institution": "Fid", "industry": "Tech", "sector": "Technology"},
            {"market_value": 25_000, "ticker": "CASH", "security_type": "Cash", "institution": "Fid", "industry": "", "sector": ""},
            {"market_value": 15_000, "ticker": "VTI", "security_type": "Etf", "institution": "Fid", "industry": "", "sector": ""},
        ]
        text = " ".join(f["text"] for f in pc.portfolio_checkup(rows)["findings"])
        self.assertIn("AAPL is 60%", text)
        self.assertIn("Technology makes up 100%", text)
        self.assertIn("sitting in cash", text)
        calm = [{"market_value": 10_000, "ticker": f"T{i}", "security_type": "Equity", "institution": f"F{i % 3}",
                 "industry": f"I{i % 5}", "sector": f"S{i % 5}"} for i in range(20)]
        self.assertEqual(pc.portfolio_checkup(calm)["findings"][0]["level"], "ok")
        self.assertEqual(pc.portfolio_checkup([])["findings"], [])


class TestSafeSpending(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household()

    def tearDown(self):
        demo_data.remove_sample_data()

    def test_higher_confidence_means_lower_safe_spending(self):
        s = build_summary()
        low = what_if.find_safe_spending(s, 0.8)
        high = what_if.find_safe_spending(s, 0.95)
        self.assertGreaterEqual(low["safe_spending"], high["safe_spending"])
        self.assertGreater(low["safe_spending"], 0)

    def test_endpoint_and_validation(self):
        status, d = self._post("/api/safe-spending", {"target": 0.9})
        self.assertEqual(status, 200)
        self.assertTrue(d["ok"])
        self.assertIn("safe_spending", d)
        status, _ = self._post("/api/safe-spending", {"target": 0.2})
        self.assertEqual(status, 400)


class TestPagesShowTheExtras(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household()

    def tearDown(self):
        demo_data.remove_sample_data()
        db.delete_plaid_item("chk_item")

    def test_summary_where_you_stand_card(self):
        body = self._get("/summary.html").read().decode("utf-8")
        for needle in ("Where you stand", "Financial independence", "How much can I safely spend?", 'id="ss-text"', "Since last month"):
            self.assertIn(needle, body)
        # sits right after the hero, before the balance sheet
        self.assertLess(body.index("Where you stand"), body.index("What you own and owe"))

    def test_since_card_appears_with_history(self):
        db.record_snapshot(net_worth=1.0, manual_asset_total=1.0, linked_asset_total=0.0, liability_total=0.0,
                           real_estate_equity_total=0.0, retirement_liquid_total=1.0,
                           snapshot_date=(date.today() - timedelta(days=40)).isoformat())
        try:
            body = self._get("/summary.html").read().decode("utf-8")
            self.assertIn("Net worth is up", body)
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM net_worth_snapshots WHERE net_worth = 1.0")

    def test_monte_carlo_has_safe_spending_with_picker(self):
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn('id="ss-target"', body)
        self.assertIn('id="levers"', body)

    def test_scenario_compare_renders_cards(self):
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn("compare-card", body)
        self.assertIn("best odds", body)

    def test_glossary_is_wired_into_every_page(self):
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("rpApplyGlossary", body)
        self.assertIn("required minimum distributions", body)

    def test_portfolio_checkup_card_on_positions_page(self):
        db.upsert_plaid_item(item_key="chk_item", plaid_item_id="p", institution_id="i", institution_name="Brokerage",
                             products=["investments"], environment="sandbox", linked_at="now")
        db.upsert_plaid_account(item_key="chk_item", account={"account_id": "a1", "name": "Brokerage", "type": "investment",
                                                              "subtype": "brokerage", "balances": {"current": 100000}})
        db.upsert_plaid_holding(item_key="chk_item", holding={
            "account_id": "a1", "security_id": "s1", "ticker_symbol": "ZZZ", "security_name": "Zed Corp",
            "security_type": "equity", "quantity": 1, "institution_price": 90000, "institution_value": 90000})
        db.upsert_plaid_holding(item_key="chk_item", holding={
            "account_id": "a1", "security_id": "s2", "ticker_symbol": "CUR", "security_name": "Cash",
            "security_type": "cash", "quantity": 1, "institution_price": 10000, "institution_value": 10000})
        body = self._get("/linked-positions.html").read().decode("utf-8")
        self.assertIn("Portfolio check-up", body)
        self.assertIn("ZZZ is 90%", body)


if __name__ == "__main__":
    unittest.main()
