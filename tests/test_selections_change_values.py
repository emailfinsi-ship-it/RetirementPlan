"""Every switch the owner can flip must actually change the numbers.

Each test flips ONE selection through the same HTTP endpoints the pages use
("In the plan?" ticks, tax treatment, owner, "Inflates?", income in the
simulation, assumptions, dollars mode, risk level, asset-group override) and
checks that the figures that should move do move, that the ones that should
not move stay put, and that flipping it back restores the original exactly.
A final group runs with the simulation memory switched on, as in the real
app, to prove it never serves a stale answer after a change.
"""

from __future__ import annotations

import random
import re
import unittest

from source.common import db, demo_data
from source.reporting import rebalance
from source.reporting.aggregate import build_summary
from source.reporting.monte_carlo import run_simulation, stable_simulation_seed
from source.reporting.monte_carlo import simulation as sim
from tests.test_dashboard import DashboardTestCase


def money(text: str) -> float:
    return float(text.replace("$", "").replace(",", ""))


def tile(page: str, label: str) -> float:
    m = re.search(r'<div class="label">' + re.escape(label) + r'[^<]*(?:<[^>]*>[^<]*)*?</div><div class="value">(-?\$?[\d,]+)', page)
    assert m, f"tile {label!r} not found"
    return money(m.group(1))


class SelectionCase(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household(with_linked=True)
        sim.enable_memo(False)
        self._restore = []

    def tearDown(self):
        sim.enable_memo(False)
        demo_data.remove_sample_data()
        db.set_dollars_mode("today")
        db.set_meta("risk_appetite", "")

    # -- helpers
    def page(self, path):
        return self._get(path).read().decode("utf-8")

    def update(self, section, row_id, **fields):
        status, d = self._post("/api/line-item/update", {"section": section, "id": row_id, "fields": fields})
        self.assertEqual(status, 200, d)

    def asset(self, name):
        return next(r for r in db.list_line_items("assets") if r["name"] == name)

    def mc(self, summary=None):
        s = summary or build_summary()
        seed = stable_simulation_seed(
            starting_balance=s["net_liquid_asset"], expenses=s["expenses"], income=s["income_for_simulation"],
            assumptions=s["assumptions"], pools=s["retirement_pools"])
        return run_simulation(
            starting_balance=s["net_liquid_asset"], expenses=s["expenses"], income=s["income_for_simulation"],
            assumptions=s["assumptions"], pools=s["retirement_pools"], rng=random.Random(seed))


class TestAssetInPlan(SelectionCase):
    def test_unticking_an_asset_removes_it_everywhere_and_ticking_restores_it(self):
        before = build_summary()
        page_before = self.page("/summary.html")
        mc_page_before = self.page("/monte-carlo.html")
        a = self.asset("Joint brokerage")
        self.update("assets", a["id"], include_in_monte_carlo=0)
        after = build_summary()
        self.assertAlmostEqual(before["net_liquid_asset"] - after["net_liquid_asset"], a["balance"], places=2)
        self.assertAlmostEqual(before["retirement_pools"]["taxable"] - after["retirement_pools"]["taxable"], a["balance"], places=2)
        self.assertEqual(before["retirement_pools"]["roth"], after["retirement_pools"]["roth"])
        self.assertEqual(before["retirement_pools"]["tax_deferred"], after["retirement_pools"]["tax_deferred"])
        self.assertAlmostEqual(tile(page_before, "Investable savings") - tile(self.page("/summary.html"), "Investable savings"),
                               a["balance"], places=0)
        self.assertNotEqual(mc_page_before, self.page("/monte-carlo.html"))
        # the simulation itself gets worse with less money
        self.assertLess(self.mc(after)["median_ending_balance"], self.mc(before)["median_ending_balance"])
        # net worth still counts it: only the plan changes, not what you own
        self.assertAlmostEqual(before["net_worth"], after["net_worth"], places=2)
        self.update("assets", a["id"], include_in_monte_carlo=1)
        restored = build_summary()
        self.assertEqual(restored["retirement_pools"], before["retirement_pools"])
        self.assertEqual(self.page("/monte-carlo.html"), mc_page_before)

    def test_each_asset_moves_only_its_own_pool(self):
        base = build_summary()["retirement_pools"]
        for name, pool in (("Alex 401(k)", "tax_deferred"), ("Alex Roth IRA", "roth"), ("Savings", "taxable")):
            a = self.asset(name)
            self.update("assets", a["id"], include_in_monte_carlo=0)
            pools = build_summary()["retirement_pools"]
            self.assertLess(pools[pool], base[pool], name)
            for other in ("tax_deferred", "roth", "taxable"):
                if other != pool:
                    self.assertEqual(pools[other], base[other], f"{name} changed {other}")
            self.update("assets", a["id"], include_in_monte_carlo=1)
            self.assertEqual(build_summary()["retirement_pools"], base)


class TestTaxTreatmentAndOwner(SelectionCase):
    def test_changing_tax_treatment_moves_money_between_pools_without_changing_the_total(self):
        before = build_summary()
        a = self.asset("Alex 401(k)")
        self.update("assets", a["id"], tax_treatment="roth")
        after = build_summary()
        self.assertAlmostEqual(after["retirement_pools"]["tax_deferred"], before["retirement_pools"]["tax_deferred"] - a["balance"], places=2)
        self.assertAlmostEqual(after["retirement_pools"]["roth"], before["retirement_pools"]["roth"] + a["balance"], places=2)
        self.assertAlmostEqual(after["net_liquid_asset"], before["net_liquid_asset"], places=2)
        # Roth money is untaxed, so the plan pays less tax
        self.assertLess(self.mc(after)["yearly_tax_total"], self.mc(before)["yearly_tax_total"])

    def test_changing_owner_changes_the_spouse_share(self):
        before = build_summary()["assumptions"]["spouse_tax_deferred_share"]
        a = self.asset("Alex 401(k)")
        self.update("assets", a["id"], owner="spouse")
        after = build_summary()["assumptions"]["spouse_tax_deferred_share"]
        self.assertGreater(after, before)
        self.update("assets", a["id"], owner="self")
        self.assertAlmostEqual(build_summary()["assumptions"]["spouse_tax_deferred_share"], before, places=9)


class TestRealEstateInPlan(SelectionCase):
    def setUp(self):
        super().setUp()
        self.home = db.list_line_items("real_estate")[0]
        db.update_line_item("real_estate", self.home["id"], {"include_in_monte_carlo": 0})

    def test_ticking_a_property_adds_its_equity_to_the_plan_only(self):
        before = build_summary()
        self.assertEqual(before["retirement_pools"]["real_estate"], 0.0)
        mc_before = self.page("/monte-carlo.html")
        summary_page_before = self.page("/summary.html")
        self.update("real_estate", self.home["id"], include_in_monte_carlo=1)
        after = build_summary()
        equity = 1_250_000 - 310_000
        self.assertAlmostEqual(after["retirement_pools"]["real_estate"], equity, delta=1.0)
        # accounts-only savings and net worth do not move
        self.assertEqual(after["net_liquid_asset"], before["net_liquid_asset"])
        self.assertEqual(after["net_worth"], before["net_worth"])
        # the simulation's starting balance and the page do
        self.assertAlmostEqual(tile(self.page("/monte-carlo.html"), "Starting balance") - tile(mc_before, "Starting balance"), equity, delta=2.0)
        self.assertGreater(self.mc(after)["median_ending_balance"], self.mc(before)["median_ending_balance"])
        page = self.page("/summary.html")
        self.assertNotEqual(page, summary_page_before)
        self.assertIn("of home equity you marked", page)
        # the Real Estate tab's own total follows
        self.assertIn(f"${equity:,.0f}", self.page("/real-estate.html").split("Included in the plan")[1][:200])
        # and Drawdown lists it as a source
        self.assertIn("Real estate (opted in)", self.page("/drawdown-planning.html"))

    def test_independence_percentage_rises_and_the_cushion_shrinks(self):
        from source.reporting import progress

        off = progress.independence_progress(build_summary())
        self.update("real_estate", self.home["id"], include_in_monte_carlo=1)
        on = progress.independence_progress(build_summary())
        self.assertGreater(on["pct"], off["pct"])
        self.assertLess(on["equity"], off["equity"])
        self.assertGreater(on["in_plan_equity"], 0)
        self.assertEqual(off["in_plan_equity"], 0)
        self.update("real_estate", self.home["id"], include_in_monte_carlo=0)
        self.assertEqual(progress.independence_progress(build_summary())["pct"], off["pct"])


class TestIncomeAndExpenses(SelectionCase):
    def test_income_ticked_out_of_the_simulation_lowers_the_result(self):
        before = build_summary()
        row = next(r for r in db.list_line_items("income") if r["name"].startswith("Social Security (Alex)"))
        self.update("income", row["id"], include_in_monte_carlo=0)
        after = build_summary()
        self.assertEqual(len(after["income_for_simulation"]), len(before["income_for_simulation"]) - 1)
        self.assertLess(self.mc(after)["median_ending_balance"], self.mc(before)["median_ending_balance"])
        self.update("income", row["id"], include_in_monte_carlo=1)
        self.assertEqual(len(build_summary()["income_for_simulation"]), len(before["income_for_simulation"]))

    def test_inflates_checkbox_changes_next_years_spending(self):
        before = build_summary()["next_year_expense_need"]
        rows = db.list_line_items("expenses")
        for r in rows:
            self.update("expenses", r["id"], inflates=0)
        flat = build_summary()["next_year_expense_need"]
        self.assertLess(flat, before)
        for r in rows:
            self.update("expenses", r["id"], inflates=1)
        self.assertAlmostEqual(build_summary()["next_year_expense_need"], before, places=2)

    def test_changing_an_expense_amount_changes_the_summary_tile(self):
        row = db.list_line_items("expenses")[0]
        page_before = self.page("/summary.html")
        self.update("expenses", row["id"], annual_amount=row["annual_amount"] + 50_000)
        page_after = self.page("/summary.html")
        self.assertNotEqual(page_before, page_after)
        self.assertGreater(
            money(re.search(r"Yearly spending in \d{4}[^<]*</div><div class=\"value\">(\$[\d,]+)", page_after).group(1)),
            money(re.search(r"Yearly spending in \d{4}[^<]*</div><div class=\"value\">(\$[\d,]+)", page_before).group(1)),
        )


class TestSettings(SelectionCase):
    def test_expected_return_changes_the_chance_of_lasting(self):
        high = self.mc()["success_rate"]
        status, _ = self._post("/api/assumptions", {"expected_return_pct": 2.0})
        self.assertEqual(status, 200)
        low = self.mc()["success_rate"]
        self.assertLess(low, high)
        self._post("/api/assumptions", {"expected_return_pct": 6.0})
        self.assertEqual(self.mc()["success_rate"], high)

    def test_inflation_changes_spending_and_results(self):
        spend = build_summary()["next_year_expense_need"]
        self._post("/api/assumptions", {"inflation_rate_pct": 8.0})
        self.assertGreater(build_summary()["next_year_expense_need"], spend)
        self._post("/api/assumptions", {"inflation_rate_pct": 3.0})
        self.assertAlmostEqual(build_summary()["next_year_expense_need"], spend, places=2)

    def test_retirement_year_changes_the_simulation(self):
        first = self.mc()["median_ending_balance"]
        year = int(build_summary()["assumptions"]["retirement_year"])
        self._post("/api/assumptions", {"retirement_year": str(year + 10)})
        self.assertNotEqual(self.mc()["median_ending_balance"], first)

    def test_dollars_mode_changes_the_monte_carlo_page(self):
        today = self.page("/monte-carlo.html")
        status, d = self._post("/api/dollars-mode", {"mode": "future"})
        self.assertEqual(status, 200)
        future = self.page("/monte-carlo.html")
        self.assertNotEqual(today, future)
        self._post("/api/dollars-mode", {"mode": "today"})
        self.assertEqual(self.page("/monte-carlo.html"), today)


class TestRiskSelections(SelectionCase):
    def test_risk_level_changes_the_goal_mix(self):
        self._post("/api/risk-appetite", {"level": "conservative"})
        conservative = rebalance.get_target()
        page_c = self.page("/rebalance.html")
        self._post("/api/risk-appetite", {"level": "aggressive"})
        aggressive = rebalance.get_target()
        self.assertGreater(aggressive["Stocks"], conservative["Stocks"])
        self.assertLess(aggressive["Bonds"], conservative["Bonds"])
        self.assertNotEqual(page_c, self.page("/rebalance.html"))

    def test_asset_group_override_changes_the_mix(self):
        from source.common import linked_data

        positions = linked_data.read_linked_portfolio_positions()
        target = rebalance.risk_target("moderate", 58)
        base = rebalance.build_plan(positions, target, rebalance.get_overrides())
        stocks_before = next(r for r in base["rows"] if r["cls"] == "Stocks")["pct"]
        status, _ = self._post("/api/asset-class", {"security_id": "smp-sp500", "asset_class": "Bonds"})
        self.assertEqual(status, 200)
        moved = rebalance.build_plan(positions, target, rebalance.get_overrides())
        self.assertLess(next(r for r in moved["rows"] if r["cls"] == "Stocks")["pct"], stocks_before)
        self.assertGreater(next(r for r in moved["rows"] if r["cls"] == "Bonds")["pct"],
                           next(r for r in base["rows"] if r["cls"] == "Bonds")["pct"])
        self._post("/api/asset-class", {"security_id": "smp-sp500", "asset_class": "auto"})
        again = rebalance.build_plan(positions, target, rebalance.get_overrides())
        self.assertAlmostEqual(next(r for r in again["rows"] if r["cls"] == "Stocks")["pct"], stocks_before, places=6)


class TestNeverStale(SelectionCase):
    """Same checks with the simulation memory ON, as in the real app."""

    def setUp(self):
        super().setUp()
        sim.enable_memo(True)

    def test_every_toggle_gives_a_fresh_answer_and_coming_back_gives_the_first_one(self):
        base_page = self.page("/monte-carlo.html")
        base_cached = self.page("/monte-carlo.html")        # served from memory
        self.assertEqual(base_page, base_cached)
        a = self.asset("Joint brokerage")
        home = db.list_line_items("real_estate")[0]
        db.update_line_item("real_estate", home["id"], {"include_in_monte_carlo": 0})
        base_page = self.page("/monte-carlo.html")
        seen = {base_page}
        for section, row, field, off, on in (
            ("assets", a["id"], "include_in_monte_carlo", 0, 1),
            ("real_estate", home["id"], "include_in_monte_carlo", 1, 0),
            ("assets", self.asset("Alex 401(k)")["id"], "tax_treatment", "roth", "tax_deferred"),
        ):
            self.update(section, row, **{field: off})
            changed = self.page("/monte-carlo.html")
            self.assertNotIn(changed, seen, f"stale page after {field}={off}")
            seen.add(changed)
            self.update(section, row, **{field: on})
        self.assertEqual(self.page("/monte-carlo.html"), base_page)

    def _both(self):
        """The simulation result with the memory on, and recomputed from scratch."""
        s = build_summary()
        cached_run = self.mc(s)
        again = self.mc(s)                      # served from memory
        self.assertEqual(cached_run, again)
        sim._memo_on = False                    # bypass the memory but keep what it holds
        try:
            fresh = self.mc(s)
        finally:
            sim._memo_on = True
        return cached_run, fresh

    def test_remembered_results_always_equal_a_fresh_run_after_every_change(self):
        a = self.asset("Joint brokerage")
        home = db.list_line_items("real_estate")[0]
        db.update_line_item("real_estate", home["id"], {"include_in_monte_carlo": 0})
        seen = []
        steps = [
            lambda: self.update("assets", a["id"], include_in_monte_carlo=0),
            lambda: self.update("real_estate", home["id"], include_in_monte_carlo=1),
            lambda: self.update("assets", self.asset("Alex 401(k)")["id"], tax_treatment="roth"),
            lambda: self._post("/api/assumptions", {"expected_return_pct": 3.0}),
            lambda: self.update("expenses", db.list_line_items("expenses")[0]["id"], annual_amount=150_000),
        ]
        cached, fresh = self._both()
        self.assertEqual(cached, fresh)
        seen.append(cached["median_ending_balance"])
        for step in steps:
            step()
            cached, fresh = self._both()
            self.assertEqual(cached, fresh)
            self.assertNotIn(cached["median_ending_balance"], seen)    # it really changed
            seen.append(cached["median_ending_balance"])

    def test_memory_does_not_hide_an_assumption_change(self):
        first = self.page("/monte-carlo.html")
        self._post("/api/assumptions", {"expected_return_pct": 3.0})
        self.assertNotEqual(self.page("/monte-carlo.html"), first)
        self._post("/api/assumptions", {"expected_return_pct": 6.0})
        self.assertEqual(self.page("/monte-carlo.html"), first)


if __name__ == "__main__":
    unittest.main()
