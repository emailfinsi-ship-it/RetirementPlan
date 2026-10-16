"""The "what if I sold my real estate" Keep-vs-Sell what-if -- source.reporting.
monte_carlo.real_estate_sale / real_estate_sale_compare and the cards that show it."""

import unittest

from source.common import db
from source.reporting.monte_carlo import deterministic_drawdown_schedule
from source.reporting.monte_carlo.assumptions import _resolve_taxable_deposit
from source.reporting.monte_carlo.real_estate_sale import (
    apply_sale,
    estimate_real_estate_sale,
    income_after_sale,
    property_equity_at,
    sale_settings,
)
from source.reporting.monte_carlo.real_estate_sale_compare import (
    drawdown_sale_comparison,
    legacy_sale_comparison,
    monte_carlo_sale_comparison,
)
from source.reporting.monte_carlo import compare_roth_conversion_strategies, run_simulation
from tests.test_dashboard import DashboardTestCase

PROPERTY = {
    "id": 1, "name": "Moorpark", "ownership_pct": 100, "current_value": 1_500_000, "purchase_price": 1_290_000,
    "loan_balance": 500_000, "loan_end_year": None, "include_in_monte_carlo": 0,
}
RENT = {"name": "Rental income", "category": "Rental", "annual_amount": 100_000}
SS = {"name": "Social Security", "category": "Social Security", "annual_amount": 40_000}


def _assumptions(**overrides):
    base = {
        "current_year": "2026", "inflation_rate": "0.0", "expected_return": "0.0", "plan_horizon_years": "5",
        "annual_income_offset": "0", "apply_drawdown_tax": "0", "re_selling_cost": "0.06",
    }
    base.update(overrides)
    return base


class TestSaleSettings(unittest.TestCase):
    def test_blank_sale_year_means_this_year_and_a_past_year_is_clamped(self):
        self.assertEqual(sale_settings(_assumptions())["sale_year"], 2026)
        self.assertEqual(sale_settings(_assumptions(re_sale_year="2020"))["sale_year"], 2026)
        self.assertEqual(sale_settings(_assumptions(re_sale_year="2031"))["sale_year"], 2031)

    def test_appreciation_defaults_to_inflation(self):
        self.assertEqual(sale_settings(_assumptions(inflation_rate="0.03"))["appreciation"], 0.03)
        self.assertEqual(sale_settings(_assumptions(inflation_rate="0.03", re_appreciation="0.05"))["appreciation"], 0.05)


class TestEstimateRealEstateSale(unittest.TestCase):
    def _sale(self, prop=PROPERTY, **assumption_overrides):
        return estimate_real_estate_sale(
            real_estate=[prop], loan_balances={prop["id"]: prop["loan_balance"]},
            assumptions=_assumptions(**assumption_overrides), income=[RENT],
        )

    def test_proceeds_are_value_less_loan_costs_and_tax(self):
        sale = self._sale()
        self.assertEqual(sale["gross_value"], 1_500_000)
        self.assertEqual(sale["loan_payoff"], 500_000)
        self.assertEqual(sale["selling_costs"], 90_000)
        self.assertEqual(sale["gain"], 1_500_000 - 90_000 - 1_290_000)
        self.assertGreater(sale["gains_tax"], 0)
        self.assertAlmostEqual(sale["net_proceeds"], 1_500_000 - 500_000 - 90_000 - sale["gains_tax"])
        self.assertEqual(sale["rent_lost"], 100_000)

    def test_no_purchase_price_means_no_gain_tax_and_is_reported(self):
        sale = self._sale({**PROPERTY, "purchase_price": 0})
        self.assertEqual(sale["gains_tax"], 0)
        self.assertEqual(sale["missing_purchase_price"], ["Moorpark"])

    def test_ownership_share_scales_everything(self):
        sale = self._sale({**PROPERTY, "ownership_pct": 50})
        self.assertEqual(sale["gross_value"], 750_000)
        self.assertEqual(sale["loan_payoff"], 250_000)

    def test_loan_pays_down_to_its_end_year(self):
        prop = {**PROPERTY, "loan_end_year": 2036}
        sale = self._sale(prop, re_sale_year="2031")        # halfway through a 10-year payoff
        self.assertAlmostEqual(sale["loan_payoff"], 250_000)
        after = self._sale(prop, re_sale_year="2040")
        self.assertEqual(after["loan_payoff"], 0)

    def test_appreciation_grows_the_sale_price(self):
        sale = self._sale(re_sale_year="2028", re_appreciation="0.10")
        self.assertAlmostEqual(sale["gross_value"], 1_500_000 * 1.1 ** 2)

    def test_net_proceeds_never_go_negative(self):
        sale = self._sale({**PROPERTY, "loan_balance": 5_000_000})
        self.assertEqual(sale["net_proceeds"], 0.0)

    def test_property_equity_if_kept(self):
        equity = property_equity_at([PROPERTY], {1: 500_000}, _assumptions(), 2030)
        self.assertEqual(equity[0]["equity"], 1_000_000)
        self.assertFalse(equity[0]["opted_in"])


class TestApplySale(unittest.TestCase):
    def test_immediate_sale_adds_proceeds_to_taxable_and_empties_the_real_estate_pool(self):
        sale = estimate_real_estate_sale(
            real_estate=[PROPERTY], loan_balances={1: 500_000}, assumptions=_assumptions(), income=[RENT],
        )
        pools = {"tax_deferred": 1, "roth": 2, "taxable": 3, "real_estate": 900_000}
        sell_pools, sell_income, sell_assumptions = apply_sale(pools=pools, income=[RENT, SS], assumptions=_assumptions(), sale=sale)
        self.assertEqual(sell_pools["real_estate"], 0.0)
        self.assertAlmostEqual(sell_pools["taxable"], 3 + sale["net_proceeds"])
        self.assertNotIn("taxable_deposits", sell_assumptions)
        self.assertEqual(pools["real_estate"], 900_000)             # inputs are not mutated
        self.assertEqual(income_after_sale([RENT, SS], 2026)[0]["end_year"], 2025)
        self.assertNotIn("end_year", income_after_sale([RENT, SS], 2026)[1])   # Social Security untouched

    def test_future_sale_becomes_a_one_time_deposit_in_that_year(self):
        a = _assumptions(re_sale_year="2029")
        sale = estimate_real_estate_sale(real_estate=[PROPERTY], loan_balances={1: 500_000}, assumptions=a, income=[RENT])
        sell_pools, _, sell_assumptions = apply_sale(pools={"taxable": 3}, income=[RENT], assumptions=a, sale=sale)
        self.assertEqual(sell_pools["taxable"], 3)
        self.assertAlmostEqual(_resolve_taxable_deposit(sell_assumptions, 2029), sale["net_proceeds"])
        self.assertEqual(_resolve_taxable_deposit(sell_assumptions, 2028), 0.0)

    def test_deposit_resolver_tolerates_garbage(self):
        for raw in ("", "nope", "[1,2]", None):
            self.assertEqual(_resolve_taxable_deposit({"taxable_deposits": raw}, 2029), 0.0)


class TestEnginesHonourTheDeposit(unittest.TestCase):
    def test_drawdown_schedule_deposits_into_taxable_in_the_sale_year(self):
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 100_000, "real_estate": 0}
        a = _assumptions(taxable_deposits='{"2028": 250000}')
        result = deterministic_drawdown_schedule(pools=pools, expenses=[], assumptions=a)
        totals = {r["year"]: r["total"] for r in result["rows"]}
        self.assertEqual(totals[2027], 100_000)
        self.assertEqual(totals[2028], 350_000)


class TestComparisons(unittest.TestCase):
    pools = {"tax_deferred": 800_000, "roth": 100_000, "taxable": 100_000, "real_estate": 0}
    expenses = [{"name": "Living", "annual_amount": 120_000}]
    income = [RENT]

    def _sale(self, assumptions):
        return estimate_real_estate_sale(
            real_estate=[PROPERTY], loan_balances={1: 500_000}, assumptions=assumptions, income=self.income,
        )

    def test_drawdown_rows_show_proceeds_lost_rent_and_the_property_equity_on_the_keep_side(self):
        a = _assumptions(plan_horizon_years="3")
        sale = self._sale(a)
        keep = deterministic_drawdown_schedule(pools=self.pools, expenses=self.expenses, income=self.income, assumptions=a)
        rows = {r["label"]: r for r in drawdown_sale_comparison(
            keep_schedule=keep, pools=self.pools, expenses=self.expenses, income=self.income, assumptions=a, sale=sale,
            real_estate=[PROPERTY], loan_balances={1: 500_000},
        )}
        today = rows["Liquid savings today"]
        self.assertEqual(today["keep"], 1_000_000)
        self.assertAlmostEqual(today["sell"], 1_000_000 + sale["net_proceeds"])
        total_today = rows["Total savings today incl. property"]
        self.assertEqual(total_today["keep"], 1_000_000 + 1_000_000)            # + the property's equity
        self.assertAlmostEqual(total_today["sell"], 1_000_000 + sale["net_proceeds"])
        self.assertIn("100,000", rows["Rental income lost per year from 2026"]["sell"])
        # Zero returns, 3 years: Keep draws only the 20k/yr rent doesn't cover; Sell draws the full 120k/yr.
        end = rows["Liquid balance at the end (2028)"]
        self.assertAlmostEqual(end["keep"], 1_000_000 - 3 * 20_000)
        self.assertAlmostEqual(end["sell"], 1_000_000 + sale["net_proceeds"] - 3 * 120_000)

    def test_legacy_rows_compare_the_baseline_and_add_kept_equity(self):
        a = _assumptions(plan_horizon_years="3")
        sale = self._sale(a)
        keep = compare_roth_conversion_strategies(pools=self.pools, expenses=self.expenses, assumptions=a, income=self.income)
        rows = {r["label"]: r for r in legacy_sale_comparison(
            keep_result=keep, pools=self.pools, expenses=self.expenses, income=self.income, assumptions=a, sale=sale,
            real_estate=[PROPERTY], loan_balances={1: 500_000},
        )}
        total = next(r for label, r in rows.items() if label.startswith("Total legacy"))
        liquid = rows["After-tax liquid legacy"]
        self.assertAlmostEqual(total["keep"], liquid["keep"] + 1_000_000)
        self.assertAlmostEqual(total["sell"], liquid["sell"])

    def test_monte_carlo_rows_use_the_same_seed_so_no_sale_means_no_difference(self):
        import random
        a = _assumptions(plan_horizon_years="3", iterations="50", return_volatility="0.1", expected_return="0.05")
        sale = self._sale(a)
        sale = {**sale, "net_proceeds": 0.0, "rent_lost": 0.0}                 # a sale that changes nothing
        keep = run_simulation(
            starting_balance=1_000_000, expenses=self.expenses, assumptions=a, income=[], rng=random.Random(7),
            pools=self.pools,
        )
        rows = {r["label"]: r for r in monte_carlo_sale_comparison(
            keep=keep, keep_bootstrap=None, starting_balance=1_000_000, expenses=self.expenses, income=[],
            assumptions=a, pools=self.pools, sale=sale, real_estate=[PROPERTY], loan_balances={1: 500_000}, seed=7,
        )}
        success = rows["Success rate (random returns)"]
        self.assertEqual(success["keep"], success["sell"])
        median = rows["Median ending liquid balance"]
        self.assertAlmostEqual(median["keep"], median["sell"])


class TestSaleCardsOnThePages(DashboardTestCase):
    def setUp(self):
        db.add_line_item("real_estate", {
            "name": "Moorpark", "current_value": 1_500_000, "purchase_price": 1_290_000, "loan_balance": 500_000,
            "ownership_pct": 100, "annual_income": 100_000,
        })
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Brokerage", "balance": 900_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Living", "annual_amount": 90_000})
        db.add_line_item("income", {"name": "Rental income", "category": "Rental", "annual_amount": 100_000})

    def tearDown(self):
        for section in ("real_estate", "assets", "expenses", "income"):
            db.clear_section(section)
        db.set_assumptions({"re_sale_year": "2030", "re_selling_cost": "0.06"})

    def test_real_estate_tab_has_the_form_and_a_proceeds_table(self):
        body = self._get("/real-estate.html").read().decode("utf-8")
        self.assertIn("What if I sold?", body)
        self.assertIn('name="re_sale_year"', body)
        self.assertIn('name="re_selling_cost_pct"', body)
        self.assertIn("Net proceeds", body)

    def test_each_tab_shows_a_keep_vs_sell_card(self):
        for path, marker in (
            ("/monte-carlo.html", "Success rate (random returns)"),
            ("/drawdown-planning.html", "Total savings at the end incl. property"),
            ("/legacy-planning.html", "Total legacy incl. property"),
        ):
            body = self._get(path).read().decode("utf-8")
            self.assertIn("If you sold your real estate", body, path)
            self.assertIn(marker, body, path)

    def test_no_card_without_properties(self):
        db.clear_section("real_estate")
        for path in ("/monte-carlo.html", "/drawdown-planning.html", "/legacy-planning.html"):
            self.assertNotIn("If you sold your real estate", self._get(path).read().decode("utf-8"), path)

    def test_saving_the_form_values_persists_them(self):
        status, _ = self._post("/api/assumptions", {"re_sale_year": "2031", "re_selling_cost_pct": "5", "re_appreciation_pct": "2"})
        self.assertEqual(status, 200)
        body = self._get("/real-estate.html").read().decode("utf-8")
        self.assertIn('value="2031"', body)
        self.assertIn("in 2031", self._get("/drawdown-planning.html").read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
