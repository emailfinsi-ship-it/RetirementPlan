"""Rebalancing suggestions: grouping holdings, drift, tax-aware sell order,
the target endpoints and the per-account Rebalance tab."""

from __future__ import annotations

import unittest

from source.common import db
from source.reporting import rebalance as rb
from tests.test_dashboard import DashboardTestCase


def pos(sid, value, kind="Equity", name="", ticker="", tax="taxable", basis=None, account="Acct"):
    return {"security_id": sid, "market_value": value, "security_type": kind, "security_name": name or sid,
            "ticker": ticker or sid, "tax_treatment": tax, "cost_basis": basis, "account": account}


class TestClassifyAndPlan(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(rb.classify(pos("a", 1, "Equity")), "Stocks")
        self.assertEqual(rb.classify(pos("b", 1, "Etf", name="Total Bond Market ETF")), "Bonds")
        self.assertEqual(rb.classify(pos("c", 1, "Etf", name="Total Stock Market ETF")), "Stocks")
        self.assertEqual(rb.classify(pos("d", 1, "Cash")), "Cash")
        self.assertEqual(rb.classify(pos("e", 1, "Fixed Income")), "Bonds")
        self.assertEqual(rb.classify(pos("f", 1, "Derivative")), "Other")
        self.assertEqual(rb.classify(pos("a", 1, "Equity"), {"a": "Other"}), "Other")

    def test_plan_sells_retirement_first_then_taxable(self):
        positions = [
            pos("ira", 40_000, tax="tax_deferred", account="IRA"),
            pos("tax", 40_000, tax="taxable", basis=10_000, account="Brokerage"),
            pos("bnd", 20_000, "Fixed Income"),
        ]
        plan = rb.build_plan(positions, {"Stocks": 60, "Bonds": 40, "Cash": 0, "Other": 0})
        self.assertTrue(plan["needs_action"])
        sell = next(t for t in plan["trades"] if t["action"] == "sell")
        self.assertEqual(sell["cls"], "Stocks")
        self.assertAlmostEqual(sell["amount"], 20_000)
        self.assertEqual(sell["picks"][0]["tax_treatment"], "tax_deferred")  # IRA first, no tax
        self.assertEqual(len(sell["picks"]), 1)
        buy = next(t for t in plan["trades"] if t["action"] == "buy")
        self.assertEqual(buy["cls"], "Bonds")
        self.assertEqual(buy["picks"][0]["label"], "bnd")

    def test_taxable_gain_estimate(self):
        positions = [pos("tax", 100_000, tax="taxable", basis=40_000), pos("c", 0.0)]
        plan = rb.build_plan(positions, {"Stocks": 50, "Bonds": 0, "Cash": 50, "Other": 0})
        sell = plan["trades"][0]
        self.assertAlmostEqual(sell["picks"][0]["est_gain"], 50_000 * 0.6)

    def test_on_target_needs_no_action(self):
        positions = [pos("s", 60_000), pos("b", 40_000, "Fixed Income")]
        plan = rb.build_plan(positions, {"Stocks": 60, "Bonds": 40, "Cash": 0, "Other": 0})
        self.assertFalse(plan["needs_action"])
        self.assertEqual(plan["trades"], [])
        self.assertEqual(rb.build_plan([], {})["total"], 0.0)

    def test_bond_funds_and_tags_are_recognised(self):
        self.assertEqual(rb.classify(pos("v", 1, "Mutual Fund", name="Vg Tot Bd Mkt Idx")), "Bonds")
        tagged = dict(pos("w", 1, "Mutual Fund", name="Some Fund"), industry="Bond")
        self.assertEqual(rb.classify(tagged), "Bonds")
        self.assertEqual(rb.classify(pos("l", 1, "Mutual Fund", name="Lifepath Idx 2050 A")), "Other")
        self.assertEqual(rb.classify(pos("s", 1, "Mutual Fund", name="Vg Inst 500 Idx")), "Stocks")

    def test_suggested_target_adds_to_100(self):
        for age in (None, 25, 60, 90):
            self.assertAlmostEqual(sum(rb.suggested_target(age).values()), 100.0)


class TestRebalanceCard(DashboardTestCase):
    def setUp(self):
        db.upsert_plaid_item(item_key="rb_item", plaid_item_id="p", institution_id="i", institution_name="Brokerage",
                             products=["investments"], environment="sandbox", linked_at="now")
        db.upsert_plaid_account(item_key="rb_item", account={"account_id": "r1", "name": "Roth IRA", "type": "investment",
                                                             "subtype": "roth", "balances": {"current": 80000}})
        for sid, tick, typ, val in (("s1", "STK", "equity", 80_000), ("b1", "BND", "fixed income", 5_000), ("c1", "CUR", "cash", 15_000)):
            db.upsert_plaid_holding(item_key="rb_item", holding={
                "account_id": "r1", "security_id": sid, "ticker_symbol": tick, "security_name": tick,
                "security_type": typ, "quantity": 1, "institution_price": val, "institution_value": val, "cost_basis": val / 2})

    def tearDown(self):
        db.delete_plaid_item("rb_item")
        db.set_meta("target_allocation", "")
        db.set_meta("asset_class_overrides", "")

    def test_page_shows_per_account_advice(self):
        body = self._get("/rebalance.html").read().decode("utf-8")
        self.assertIn("Risk &amp; suggestions", body)
        self.assertIn("How much risk are you comfortable with?", body)
        self.assertIn("Your mix today", body)
        self.assertIn("Your mix by institution", body)
        self.assertIn("Brokerage", body)
        for c in ("Stocks", "Bonds", "Cash", "Other"):
            self.assertIn(f"</span>{c}</div>", body)
        self.assertIn("Your goal:", body)
        self.assertIn("Roth IRA", body)
        self.assertIn("starting mix picked for your age", body)
        self.assertIn("Moderate is shown", body)
        status, _ = self._post("/api/target-allocation", {"Stocks": 60, "Bonds": 30, "Cash": 10, "Other": 0})
        self.assertEqual(status, 200)
        body = self._get("/rebalance.html").read().decode("utf-8")
        self.assertIn("You are using your own mix", body)
        self.assertIn("What to do", body)
        self.assertIn("<strong>Sell</strong>", body)
        self.assertIn("costs no tax", body)
        # On target -> nothing to do.
        self._post("/api/target-allocation", {"Stocks": 80, "Bonds": 5, "Cash": 15, "Other": 0})
        body = self._get("/rebalance.html").read().decode("utf-8")
        self.assertIn("Looks good", body)
        self.assertIn("Nothing to do here", body)

    def test_long_card_is_gone_from_positions_and_tab_is_in_subnav(self):
        body = self._get("/linked-positions.html").read().decode("utf-8")
        self.assertNotIn("Rebalancing suggestions", body)
        self.assertIn('href="/rebalance.html"', body)

    def test_one_card_per_account(self):
        db.upsert_plaid_account(item_key="rb_item", account={"account_id": "r2", "name": "Brokerage", "type": "investment",
                                                             "subtype": "brokerage", "balances": {"current": 1000}})
        db.upsert_plaid_holding(item_key="rb_item", holding={
            "account_id": "r2", "security_id": "s9", "ticker_symbol": "ZZZ", "security_name": "ZZZ",
            "security_type": "equity", "quantity": 1, "institution_price": 1000, "institution_value": 1000, "cost_basis": 500})
        body = self._get("/rebalance.html").read().decode("utf-8")
        self.assertIn("Roth IRA", body)
        self.assertIn("Brokerage", body)
        self.assertIn("taxable", body)

    def test_disclaimer_footer_on_every_page(self):
        for path in ("/summary.html", "/rebalance.html", "/linked-positions.html", "/expense.html", "/monte-carlo.html", "/setup.html", "/login.html"):
            with self.subTest(path=path):
                body = self._get(path).read().decode("utf-8")
                self.assertIn("Not financial, investment, tax or legal advice", body)

    def test_hide_balances_script_covers_late_content_and_tooltips(self):
        body = self._get("/rebalance.html").read().decode("utf-8")
        self.assertIn("new MutationObserver", body)  # figures filled in by scripts get hidden too
        self.assertIn("maskTitles", body)  # hover tooltips are masked as well
        self.assertIn("tagMoneyInputs", body)

    def test_zero_value_account_is_left_out(self):
        db.upsert_plaid_account(item_key="rb_item", account={"account_id": "z1", "name": "Empty Brokerage", "type": "investment",
                                                             "subtype": "brokerage", "balances": {"current": 0.2}})
        db.upsert_plaid_holding(item_key="rb_item", holding={
            "account_id": "z1", "security_id": "zc", "ticker_symbol": "CUR", "security_name": "Cash",
            "security_type": "cash", "quantity": 1, "institution_price": 0.2, "institution_value": 0.2, "cost_basis": 0.2})
        body = self._get("/rebalance.html").read().decode("utf-8")
        self.assertNotIn("Empty Brokerage", body)
        self.assertIn("Roth IRA", body)

    def test_risk_levels_set_the_goal(self):
        status, d = self._post("/api/risk-appetite", {"level": "conservative"})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(sum(d["target"].values()), 100.0)
        self.assertEqual(rb.get_risk(), "conservative")
        body = self._get("/rebalance.html").read().decode("utf-8")
        self.assertIn("You chose Conservative.", body)
        stocks = {k: rb.risk_target(k, 55)["Stocks"] for k in rb.RISK_LEVELS}
        self.assertTrue(stocks["conservative"] < stocks["moderate"] < stocks["growth"] < stocks["aggressive"])
        status, _ = self._post("/api/risk-appetite", {"level": "nope"})
        self.assertEqual(status, 400)

    def test_endpoints(self):
        status, _ = self._post("/api/target-allocation", {"Stocks": 60, "Bonds": 30, "Cash": 5, "Other": 0})
        self.assertEqual(status, 400)  # does not add to 100
        status, _ = self._post("/api/asset-class", {"security_id": "s1", "asset_class": "Bonds"})
        self.assertEqual(status, 200)
        self.assertEqual(rb.get_overrides(), {"s1": "Bonds"})
        self._post("/api/asset-class", {"security_id": "s1", "asset_class": "auto"})
        self.assertEqual(rb.get_overrides(), {})
        status, d = self._post("/api/target-allocation", {"use_suggested": True})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(sum(d["target"].values()), 100.0)


if __name__ == "__main__":
    unittest.main()
