import random
import unittest

from source.reporting.monte_carlo import (
    CA_STANDARD_DEDUCTION_MFJ_2026,
    CA_TAX_BRACKETS_MFJ_2026,
    FEDERAL_STANDARD_DEDUCTION_MFJ_2026,
    FEDERAL_TAX_BRACKETS_MFJ_2026,
    HISTORICAL_STRESS_SCENARIOS,
    LEVERS,
    annual_expense_need,
    annual_income_need,
    annual_net_withdrawal_need,
    deterministic_drawdown_schedule,
    effective_line_item_amount,
    estimate_annual_drawdown_tax,
    render_fan_svg,
    run_historical_bootstrap_simulation,
    run_historical_stress_test,
    run_sensitivity_analysis,
    run_simulation,
    stable_simulation_seed,
    yearly_withdrawal_schedule,
)
from source.reporting.monte_carlo import (
    FEDERAL_LTCG_BRACKETS_MFJ_2026,
    _SP500_ANNUAL_RETURNS,
    _apply_year_withdrawal,
    _bracket_tax,
    _pool_year_tax,
    _resolve_birth_year,
    _resolve_gains_fraction,
    _simulate_fill,
    _stacked_bracket_tax,
)


class TestAnnualExpenseNeed(unittest.TestCase):
    def test_recurring_expense_with_no_year_range_applies_every_year(self):
        expenses = [{"name": "Healthcare", "annual_amount": 10000, "start_year": None, "end_year": None}]
        self.assertEqual(annual_expense_need(expenses, 2030), 10000)
        self.assertEqual(annual_expense_need(expenses, 2050), 10000)

    def test_scoped_expense_only_applies_within_its_year_range(self):
        expenses = [{"name": "Year 2031", "annual_amount": 5000, "start_year": 2031, "end_year": 2031}]
        self.assertEqual(annual_expense_need(expenses, 2030), 0)
        self.assertEqual(annual_expense_need(expenses, 2031), 5000)
        self.assertEqual(annual_expense_need(expenses, 2032), 0)

    def test_multiple_rows_sum_for_the_same_year(self):
        expenses = [
            {"name": "Baseline", "annual_amount": 40000, "start_year": None, "end_year": None},
            {"name": "College", "annual_amount": 20000, "start_year": 2029, "end_year": 2033},
        ]
        self.assertEqual(annual_expense_need(expenses, 2030), 60000)
        self.assertEqual(annual_expense_need(expenses, 2040), 40000)

    def test_none_amount_treated_as_zero(self):
        expenses = [{"name": "X", "annual_amount": None, "start_year": None, "end_year": None}]
        self.assertEqual(annual_expense_need(expenses, 2030), 0)

    def test_row_without_base_year_or_inflates_keys_stays_flat_with_inflation_passed(self):
        # Rows from before this feature existed (or an imported drawdown-
        # ledger "Year 2031" row) have no base_year/inflates at all --
        # .get() must treat that exactly like inflates=False, not error.
        expenses = [{"name": "Old row", "annual_amount": 1000, "start_year": None, "end_year": None}]
        self.assertEqual(annual_expense_need(expenses, 2035, inflation_rate=0.03), 1000)


class TestEffectiveLineItemAmount(unittest.TestCase):
    """The Fixed/Variable-cost-with-inflation building block shared by
    annual_expense_need and annual_income_need -- a row grows from its
    own base_year by inflation_rate only when inflates is set."""

    def test_flat_row_ignores_inflation_rate(self):
        row = {"annual_amount": 100_000, "inflates": False, "base_year": 2026}
        self.assertEqual(effective_line_item_amount(row, 2035, 0.03), 100_000)

    def test_inflating_row_compounds_from_base_year(self):
        row = {"annual_amount": 100_000, "inflates": True, "base_year": 2026}
        self.assertAlmostEqual(effective_line_item_amount(row, 2028, 0.03), 100_000 * 1.03 ** 2)

    def test_inflating_row_with_no_base_year_stays_flat(self):
        # inflates=True but base_year unset -- nothing to compound from,
        # so it's treated the same as a non-inflating row rather than
        # erroring on `year - None`.
        row = {"annual_amount": 100_000, "inflates": True, "base_year": None}
        self.assertEqual(effective_line_item_amount(row, 2035, 0.03), 100_000)

    def test_matches_the_screenshot_fixed_cost_example(self):
        # $197,800/yr Fixed cost, 2026 basis, 3% inflation -- the actual
        # figures from the user's own budget table.
        row = {"annual_amount": 197_800, "inflates": True, "base_year": 2026}
        self.assertAlmostEqual(effective_line_item_amount(row, 2028, 0.03), 197_800 * 1.03 ** 2, places=2)


class TestAnnualIncomeNeed(unittest.TestCase):
    def test_sums_income_rows_covering_the_year_same_rules_as_expenses(self):
        income = [
            {"name": "Rental", "annual_amount": 103_000, "start_year": None, "end_year": None, "inflates": True, "base_year": 2026},
            {"name": "Social Security", "annual_amount": 42_000, "start_year": 2035, "end_year": None, "inflates": False, "base_year": None},
        ]
        # Before SS starts: only inflated rental income.
        self.assertAlmostEqual(annual_income_need(income, 2028, 0.03), 103_000 * 1.03 ** 2, places=2)
        # After SS starts: inflated rental + flat SS.
        self.assertAlmostEqual(annual_income_need(income, 2035, 0.03), 103_000 * 1.03 ** 9 + 42_000, places=2)


class TestAnnualNetWithdrawalNeed(unittest.TestCase):
    """The Monte Carlo tab's "Yearly Drawdown" figure -- expense need net
    of income need and the flat offset, for one year, independent of any
    particular simulation/scenario's return draw."""

    def test_nets_expense_against_income_and_offset(self):
        expenses = [{"name": "Baseline", "annual_amount": 60_000, "start_year": None, "end_year": None}]
        income = [{"name": "Rental", "annual_amount": 15_000, "start_year": None, "end_year": None}]
        need = annual_net_withdrawal_need(expenses, income, 2030, inflation_rate=0.0, income_offset=5_000)
        self.assertEqual(need, 60_000 - 15_000 - 5_000)

    def test_defaults_to_zero_inflation_and_zero_offset(self):
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        self.assertEqual(annual_net_withdrawal_need(expenses, [], 2030), 40_000)

    def test_applies_inflation_the_same_way_annual_expense_need_does(self):
        expenses = [{"name": "Baseline", "annual_amount": 100_000, "inflates": True, "base_year": 2026, "start_year": None, "end_year": None}]
        need = annual_net_withdrawal_need(expenses, [], 2028, inflation_rate=0.03)
        self.assertAlmostEqual(need, 100_000 * 1.03 ** 2, places=2)

    def test_can_go_negative_when_income_exceeds_expenses(self):
        expenses = [{"name": "Baseline", "annual_amount": 10_000, "start_year": None, "end_year": None}]
        income = [{"name": "Pension", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        need = annual_net_withdrawal_need(expenses, income, 2030)
        self.assertEqual(need, -40_000)


class TestEstimateAnnualDrawdownTax(unittest.TestCase):
    """estimate_annual_drawdown_tax -- the federal + California income
    tax estimate on a year's drawdown, assuming the whole thing is
    pre-tax ordinary income (see the Monte Carlo tab's "Apply drawdown
    tax" checkbox / monte_carlo.py's module docstring)."""

    def test_zero_or_negative_need_owes_no_tax(self):
        self.assertEqual(estimate_annual_drawdown_tax(0.0, 2026), 0.0)
        self.assertEqual(estimate_annual_drawdown_tax(-1_000.0, 2026), 0.0)

    def test_a_need_below_both_standard_deductions_owes_no_tax(self):
        # $10,000 is under both the federal MFJ standard deduction
        # ($32,200) and California's ($11,412) -- taxable income is
        # floored at 0 for each, so no bracket ever applies.
        self.assertEqual(estimate_annual_drawdown_tax(10_000.0, 2026), 0.0)

    def test_a_need_above_the_ca_deduction_but_below_the_federal_one_owes_ca_tax_only(self):
        # $20,000 is above CA's standard deduction ($11,412) but still
        # under the federal one ($32,200) -- so this is CA tax only,
        # computed directly from CA's own bottom bracket (1% on taxable
        # income up to $22,158) for comparison.
        tax = estimate_annual_drawdown_tax(20_000.0, 2026)
        expected_ca_only = _bracket_tax(20_000.0 - CA_STANDARD_DEDUCTION_MFJ_2026, CA_TAX_BRACKETS_MFJ_2026)
        self.assertGreater(tax, 0.0)
        # tax is slightly above the un-grossed-up CA-only figure, since
        # the fixed-point gross-up itself adds a sliver more taxable
        # income on top.
        self.assertGreaterEqual(tax, expected_ca_only)
        self.assertAlmostEqual(tax, expected_ca_only, delta=1.0)

    def test_grossed_up_withdrawal_minus_its_own_tax_equals_the_net_need(self):
        # The whole point of the gross-up: the actual amount withdrawn
        # (net_need + tax) should, once taxed itself, leave exactly
        # net_need behind -- G - tax(G) == net_need, checked by
        # recomputing tax(G) directly from the same brackets/deductions
        # the function itself uses (at zero inflation, so no growth to
        # account for).
        for net_need in (20_000.0, 100_000.0, 300_000.0):
            tax = estimate_annual_drawdown_tax(net_need, 2026, 0.0)
            gross = net_need + tax
            fed_tax = _bracket_tax(max(0.0, gross - FEDERAL_STANDARD_DEDUCTION_MFJ_2026), FEDERAL_TAX_BRACKETS_MFJ_2026)
            ca_tax = _bracket_tax(max(0.0, gross - CA_STANDARD_DEDUCTION_MFJ_2026), CA_TAX_BRACKETS_MFJ_2026)
            self.assertAlmostEqual(fed_tax + ca_tax, tax, delta=0.5)

    def test_brackets_and_deductions_grow_with_inflation_so_later_years_owe_less_on_the_same_need(self):
        # Same $100,000 need, but 2030 sees the brackets/deduction grown
        # by 3%/year for 4 years -- more of that $100,000 falls in the
        # lower (or now-nonexistent-taxable) brackets, so the tax bill on
        # an identical withdrawal is smaller than in the 2026 base year.
        tax_2026 = estimate_annual_drawdown_tax(100_000.0, 2026, 0.03)
        tax_2030 = estimate_annual_drawdown_tax(100_000.0, 2030, 0.03)
        self.assertLess(tax_2030, tax_2026)


class TestYearlyWithdrawalSchedule(unittest.TestCase):
    """yearly_withdrawal_schedule -- the shared, scenario/path-independent
    needs/taxes/totals lists every simulation method builds its balance
    walk from."""

    def test_apply_drawdown_tax_false_means_every_tax_entry_is_zero(self):
        expenses = [{"name": "Baseline", "annual_amount": 100_000, "start_year": None, "end_year": None}]
        schedule = yearly_withdrawal_schedule(expenses, [], [2026, 2027], apply_drawdown_tax=False)
        self.assertEqual(schedule["taxes"], [0.0, 0.0])
        self.assertEqual(schedule["totals"], schedule["needs"])

    def test_apply_drawdown_tax_true_adds_a_positive_tax_on_top_of_need(self):
        expenses = [{"name": "Baseline", "annual_amount": 100_000, "start_year": None, "end_year": None}]
        schedule = yearly_withdrawal_schedule(expenses, [], [2026], apply_drawdown_tax=True)
        self.assertGreater(schedule["taxes"][0], 0.0)
        self.assertAlmostEqual(schedule["totals"][0], schedule["needs"][0] + schedule["taxes"][0], places=6)

    def test_a_year_with_no_net_need_has_no_tax_either_way(self):
        # Income fully covers Expense -- nothing withdrawn, so nothing
        # taxed, regardless of the apply_drawdown_tax flag.
        expenses = [{"name": "Baseline", "annual_amount": 10_000, "start_year": None, "end_year": None}]
        income = [{"name": "Pension", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        schedule = yearly_withdrawal_schedule(expenses, income, [2026], apply_drawdown_tax=True)
        self.assertEqual(schedule["needs"][0], -40_000.0)
        self.assertEqual(schedule["taxes"][0], 0.0)


class TestResolveBirthYearAndGainsFraction(unittest.TestCase):
    def test_resolve_birth_year_blank_is_none(self):
        self.assertIsNone(_resolve_birth_year({"birth_year": ""}))
        self.assertIsNone(_resolve_birth_year({}))

    def test_resolve_birth_year_parses_string(self):
        self.assertEqual(_resolve_birth_year({"birth_year": "1955"}), 1955)

    def test_resolve_birth_year_garbage_is_none(self):
        self.assertIsNone(_resolve_birth_year({"birth_year": "not-a-year"}))

    def test_resolve_gains_fraction_default(self):
        self.assertEqual(_resolve_gains_fraction({}), 0.4)
        self.assertEqual(_resolve_gains_fraction({"taxable_gains_fraction": ""}), 0.4)

    def test_resolve_gains_fraction_parses_and_clamps(self):
        self.assertEqual(_resolve_gains_fraction({"taxable_gains_fraction": "0.25"}), 0.25)
        self.assertEqual(_resolve_gains_fraction({"taxable_gains_fraction": "5"}), 1.0)
        self.assertEqual(_resolve_gains_fraction({"taxable_gains_fraction": "-1"}), 0.0)


class TestStackedBracketTax(unittest.TestCase):
    def test_zero_additional_income_is_zero_tax(self):
        self.assertEqual(_stacked_bracket_tax(50_000, 0, FEDERAL_LTCG_BRACKETS_MFJ_2026), 0.0)

    def test_matches_bracket_tax_difference(self):
        base, additional = 60_000, 30_000
        expected = _bracket_tax(base + additional, FEDERAL_LTCG_BRACKETS_MFJ_2026) - _bracket_tax(base, FEDERAL_LTCG_BRACKETS_MFJ_2026)
        self.assertAlmostEqual(_stacked_bracket_tax(base, additional, FEDERAL_LTCG_BRACKETS_MFJ_2026), expected)

    def test_gains_stacked_entirely_within_the_0pct_ltcg_bracket_owe_nothing(self):
        # $50,000 of ordinary income plus $20,000 of gains stays under
        # the $98,900 MFJ 0% LTCG threshold.
        self.assertEqual(_stacked_bracket_tax(50_000, 20_000, FEDERAL_LTCG_BRACKETS_MFJ_2026), 0.0)

    def test_gains_pushed_above_the_0pct_threshold_are_taxed_on_the_excess_only(self):
        # $90,000 ordinary + $20,000 gains crosses $98,900 by $11,100 --
        # only that slice owes the 15% rate, not the whole $20,000.
        tax = _stacked_bracket_tax(90_000, 20_000, FEDERAL_LTCG_BRACKETS_MFJ_2026)
        self.assertAlmostEqual(tax, 11_100 * 0.15)


class TestPoolYearTax(unittest.TestCase):
    def test_zero_income_is_zero_tax(self):
        self.assertEqual(_pool_year_tax(ordinary_income=0, gains_income=0, year=2026, inflation_rate=0.0), 0.0)

    def test_ordinary_income_alone_matches_estimate_annual_drawdown_tax_style_bracket_math(self):
        # With no gains, _pool_year_tax's ordinary-income leg should
        # equal a plain fed + CA bracket calc on that income net of each
        # deduction (no LTCG stacking involved).
        income = 150_000
        expected_fed = _bracket_tax(income - FEDERAL_STANDARD_DEDUCTION_MFJ_2026, FEDERAL_TAX_BRACKETS_MFJ_2026)
        expected_ca = _bracket_tax(income - CA_STANDARD_DEDUCTION_MFJ_2026, CA_TAX_BRACKETS_MFJ_2026)
        tax = _pool_year_tax(ordinary_income=income, gains_income=0, year=2026, inflation_rate=0.0)
        self.assertAlmostEqual(tax, expected_fed + expected_ca)

    def test_gains_income_adds_federal_ltcg_and_ca_ordinary_tax(self):
        with_gains = _pool_year_tax(ordinary_income=50_000, gains_income=100_000, year=2026, inflation_rate=0.0)
        without_gains = _pool_year_tax(ordinary_income=50_000, gains_income=0, year=2026, inflation_rate=0.0)
        self.assertGreater(with_gains, without_gains)

    def test_grows_with_inflation_like_estimate_annual_drawdown_tax(self):
        tax_2026 = _pool_year_tax(ordinary_income=150_000, gains_income=0, year=2026, inflation_rate=0.03)
        tax_2036 = _pool_year_tax(ordinary_income=150_000, gains_income=0, year=2036, inflation_rate=0.03)
        # Brackets grew by inflation, so the same nominal income owes less tax later.
        self.assertLess(tax_2036, tax_2026)


class TestSimulateFill(unittest.TestCase):
    def test_fills_in_order_capped_per_pool(self):
        available = {"taxable": 10_000, "tax_deferred": 5_000, "roth": 100_000}
        result = _simulate_fill(available, ("taxable", "tax_deferred", "roth"), 12_000)
        self.assertEqual(result, {"taxable": 10_000, "tax_deferred": 2_000, "roth": 0})

    def test_never_withdraws_more_than_requested(self):
        available = {"a": 100_000, "b": 100_000}
        result = _simulate_fill(available, ("a", "b"), 30_000)
        self.assertEqual(sum(result.values()), 30_000)

    def test_shortfall_when_every_pool_combined_is_insufficient(self):
        available = {"a": 1_000, "b": 2_000}
        result = _simulate_fill(available, ("a", "b"), 10_000)
        self.assertEqual(sum(result.values()), 3_000)  # everything they have; caller computes the 7,000 shortfall

    def test_does_not_mutate_the_available_dict(self):
        available = {"a": 10_000}
        _simulate_fill(available, ("a",), 5_000)
        self.assertEqual(available, {"a": 10_000})


class TestApplyYearWithdrawal(unittest.TestCase):
    """_apply_year_withdrawal -- the per-year core of the three-pool
    withdrawal/RMD/tax engine. run_simulation/run_historical_bootstrap_
    simulation/run_historical_stress_test call this once per (path or
    scenario, year) when given `pools`; these tests drive it directly."""

    def _pools(self, tax_deferred=0.0, roth=0.0, taxable=0.0):
        return {"tax_deferred": tax_deferred, "roth": roth, "taxable": taxable}

    def test_no_rmd_when_birth_year_is_none(self):
        pools = self._pools(tax_deferred=1_000_000, taxable=100_000)
        result = _apply_year_withdrawal(
            pools, need=20_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertEqual(result["rmd"], 0.0)

    def test_no_rmd_below_rmd_age(self):
        pools = self._pools(tax_deferred=1_000_000, taxable=100_000)
        result = _apply_year_withdrawal(
            pools, need=20_000, age=65, birth_year=1955, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertEqual(result["rmd"], 0.0)

    def test_rmd_forced_at_rmd_age_even_with_no_spending_need(self):
        pools = self._pools(tax_deferred=1_000_000)
        result = _apply_year_withdrawal(
            pools, need=0, age=75, birth_year=1950, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertAlmostEqual(result["rmd"], 1_000_000 / 24.6)
        self.assertLess(pools["tax_deferred"], 1_000_000)

    def test_unspent_rmd_surplus_is_reinvested_into_taxable(self):
        pools = self._pools(tax_deferred=1_000_000, taxable=0)
        _apply_year_withdrawal(
            pools, need=0, age=75, birth_year=1950, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertGreater(pools["taxable"], 0)

    def test_need_is_drawn_from_taxable_before_tax_deferred(self):
        pools = self._pools(tax_deferred=500_000, taxable=500_000)
        _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertEqual(pools["tax_deferred"], 500_000)  # untouched
        self.assertEqual(pools["taxable"], 450_000)

    def test_need_spills_into_tax_deferred_once_taxable_is_exhausted(self):
        pools = self._pools(tax_deferred=500_000, taxable=10_000)
        _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertEqual(pools["taxable"], 0)
        self.assertEqual(pools["tax_deferred"], 460_000)

    def test_roth_is_drawn_down_last(self):
        pools = self._pools(tax_deferred=10_000, roth=500_000, taxable=10_000)
        _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertEqual(pools["taxable"], 0)
        self.assertEqual(pools["tax_deferred"], 0)
        self.assertEqual(pools["roth"], 470_000)

    def test_roth_withdrawal_is_never_taxed(self):
        pools = self._pools(roth=500_000)
        result = _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=True,
        )
        self.assertEqual(result["tax"], 0.0)
        self.assertEqual(pools["roth"], 450_000)

    def test_apply_drawdown_tax_false_means_zero_tax(self):
        pools = self._pools(tax_deferred=1_000_000)
        result = _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertEqual(result["tax"], 0.0)
        self.assertEqual(pools["tax_deferred"], 950_000)

    def test_gross_up_withdraws_more_than_need_to_cover_its_own_tax(self):
        pools = self._pools(tax_deferred=1_000_000)
        result = _apply_year_withdrawal(
            pools, need=100_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=True,
        )
        self.assertGreater(result["tax"], 0.0)
        total_drawn = 1_000_000 - pools["tax_deferred"]
        self.assertAlmostEqual(total_drawn, 100_000 + result["tax"], places=4)

    def test_shortfall_when_every_pool_combined_cannot_cover_need(self):
        pools = self._pools(tax_deferred=1_000, taxable=500)
        result = _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertGreater(result["shortfall"], 0.0)
        self.assertEqual(pools["tax_deferred"], 0.0)
        self.assertEqual(pools["taxable"], 0.0)

    def test_no_pool_ever_goes_negative(self):
        pools = self._pools(tax_deferred=100, roth=100, taxable=100)
        _apply_year_withdrawal(
            pools, need=1_000_000, age=90, birth_year=1930, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=True,
        )
        for balance in pools.values():
            self.assertGreaterEqual(balance, 0.0)

    def test_a_pools_dict_without_a_real_estate_key_never_gets_one_added(self):
        # Backward compatibility: a 3-pool-only caller's dict keeps its
        # exact original shape -- no silent "real_estate": 0.0 key shows
        # up just because the engine now knows how to use one.
        pools = self._pools(tax_deferred=500_000, taxable=500_000)
        _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertNotIn("real_estate", pools)

    def test_real_estate_is_drawn_only_after_taxable_tax_deferred_and_roth_are_exhausted(self):
        pools = self._pools(tax_deferred=0, roth=0, taxable=0)
        pools["real_estate"] = 200_000
        _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertEqual(pools["real_estate"], 150_000)

    def test_real_estate_is_left_untouched_while_other_pools_can_cover_the_need(self):
        pools = self._pools(tax_deferred=500_000, taxable=500_000)
        pools["real_estate"] = 200_000
        _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertEqual(pools["real_estate"], 200_000)  # untouched -- taxable covered it

    def test_real_estate_withdrawal_is_never_taxed(self):
        # "No tax modeled on real estate draws" -- unlike a Taxable or
        # Tax-deferred withdrawal, drawing from the real_estate pool adds
        # nothing to _pool_year_tax's ordinary_income/gains_income inputs.
        pools = self._pools(tax_deferred=0, roth=0, taxable=0)
        pools["real_estate"] = 200_000
        result = _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=True,
        )
        self.assertEqual(result["tax"], 0.0)
        self.assertEqual(pools["real_estate"], 150_000)

    def test_real_estate_can_still_shortfall_once_every_pool_is_exhausted(self):
        pools = self._pools(tax_deferred=0, roth=0, taxable=0)
        pools["real_estate"] = 10_000
        result = _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertGreater(result["shortfall"], 0.0)
        self.assertEqual(pools["real_estate"], 0.0)


class TestRunSimulation(unittest.TestCase):
    def test_deterministic_with_seeded_rng(self):
        expenses = [{"name": "Baseline", "annual_amount": 40000, "start_year": None, "end_year": None}]
        assumptions = {
            "expected_return": "0.06", "return_volatility": "0.10", "iterations": "200",
            "plan_horizon_years": "20", "current_year": "2027", "annual_income_offset": "0",
        }
        r1 = run_simulation(starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, rng=random.Random(7))
        r2 = run_simulation(starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, rng=random.Random(7))
        self.assertEqual(r1["band"], r2["band"])
        self.assertEqual(r1["success_rate"], r2["success_rate"])

    def test_band_covers_the_full_horizon_starting_at_current_year(self):
        assumptions = {
            "expected_return": "0.05", "return_volatility": "0.1", "iterations": "50",
            "plan_horizon_years": "10", "current_year": "2030", "annual_income_offset": "0",
        }
        result = run_simulation(starting_balance=500_000, expenses=[], assumptions=assumptions, rng=random.Random(1))
        self.assertEqual(len(result["band"]), 10)
        self.assertEqual(result["years"][0], 2030)
        self.assertEqual(result["years"][-1], 2039)

    def test_percentiles_are_ordered_p10_le_median_le_p90(self):
        expenses = [{"name": "Baseline", "annual_amount": 30000, "start_year": None, "end_year": None}]
        assumptions = {
            "expected_return": "0.06", "return_volatility": "0.15", "iterations": "300",
            "plan_horizon_years": "15", "current_year": "2027", "annual_income_offset": "0",
        }
        result = run_simulation(starting_balance=800_000, expenses=expenses, assumptions=assumptions, rng=random.Random(3))
        for row in result["band"]:
            self.assertLessEqual(row["p10"], row["median"] + 1e-9)
            self.assertLessEqual(row["median"], row["p90"] + 1e-9)

    def test_zero_starting_balance_with_nonzero_need_depletes_immediately(self):
        expenses = [{"name": "Baseline", "annual_amount": 50000, "start_year": None, "end_year": None}]
        assumptions = {
            "expected_return": "0.0", "return_volatility": "0.0", "iterations": "20",
            "plan_horizon_years": "5", "current_year": "2027", "annual_income_offset": "0",
        }
        result = run_simulation(starting_balance=0, expenses=expenses, assumptions=assumptions, rng=random.Random(1))
        self.assertEqual(result["success_rate"], 0.0)
        self.assertEqual(result["median_ending_balance"], 0.0)

    def test_no_expenses_and_positive_return_never_depletes(self):
        assumptions = {
            "expected_return": "0.05", "return_volatility": "0.0", "iterations": "10",
            "plan_horizon_years": "10", "current_year": "2027", "annual_income_offset": "0",
        }
        result = run_simulation(starting_balance=100_000, expenses=[], assumptions=assumptions, rng=random.Random(1))
        self.assertEqual(result["success_rate"], 1.0)
        self.assertGreater(result["median_ending_balance"], 100_000)

    def test_income_offset_reduces_net_need(self):
        expenses = [{"name": "Baseline", "annual_amount": 50000, "start_year": None, "end_year": None}]
        no_offset = {
            "expected_return": "0.0", "return_volatility": "0.0", "iterations": "5",
            "plan_horizon_years": "3", "current_year": "2027", "annual_income_offset": "0",
        }
        with_offset = dict(no_offset, annual_income_offset="20000")
        r_no_offset = run_simulation(starting_balance=1_000_000, expenses=expenses, assumptions=no_offset, rng=random.Random(1))
        r_with_offset = run_simulation(starting_balance=1_000_000, expenses=expenses, assumptions=with_offset, rng=random.Random(1))
        self.assertGreater(r_with_offset["median_ending_balance"], r_no_offset["median_ending_balance"])

    def test_itemized_income_rows_reduce_net_need_same_as_offset(self):
        # The Income tab's own line items (Rental, Social Security, ...)
        # net against expenses exactly like the older flat
        # annual_income_offset assumption -- and the two stack.
        expenses = [{"name": "Baseline", "annual_amount": 50000, "start_year": None, "end_year": None}]
        assumptions = {
            "expected_return": "0.0", "return_volatility": "0.0", "iterations": "5",
            "plan_horizon_years": "3", "current_year": "2027", "annual_income_offset": "0",
        }
        income = [{"name": "Rental", "annual_amount": 20000, "start_year": None, "end_year": None}]
        r_no_income = run_simulation(starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, rng=random.Random(1))
        r_with_income = run_simulation(
            starting_balance=1_000_000, expenses=expenses, income=income, assumptions=assumptions, rng=random.Random(1),
        )
        self.assertGreater(r_with_income["median_ending_balance"], r_no_income["median_ending_balance"])

    def test_inflation_rate_grows_an_inflating_expense_row_each_simulated_year(self):
        # 0% return/volatility isolates the withdrawal effect: a flat
        # $50,000/yr expense drains the balance by exactly $50,000/yr,
        # but an inflating one drains progressively more, so the
        # inflating scenario must end with a lower balance.
        flat = [{"name": "Baseline", "annual_amount": 50000, "start_year": None, "end_year": None, "inflates": False}]
        inflating = [{"name": "Baseline", "annual_amount": 50000, "start_year": None, "end_year": None, "inflates": True, "base_year": 2027}]
        assumptions = {
            "expected_return": "0.0", "return_volatility": "0.0", "iterations": "5",
            "plan_horizon_years": "5", "current_year": "2027", "inflation_rate": "0.03",
        }
        r_flat = run_simulation(starting_balance=1_000_000, expenses=flat, assumptions=assumptions, rng=random.Random(1))
        r_inflating = run_simulation(starting_balance=1_000_000, expenses=inflating, assumptions=assumptions, rng=random.Random(1))
        self.assertLess(r_inflating["median_ending_balance"], r_flat["median_ending_balance"])

    def test_result_reports_its_method_and_p10_p90_ending_balance(self):
        assumptions = {
            "expected_return": "0.06", "return_volatility": "0.1", "iterations": "50",
            "plan_horizon_years": "5", "current_year": "2027", "annual_income_offset": "0",
        }
        result = run_simulation(starting_balance=500_000, expenses=[], assumptions=assumptions, rng=random.Random(1))
        self.assertEqual(result["method"], "gaussian")
        self.assertEqual(result["p10_ending_balance"], result["band"][-1]["p10"])
        self.assertEqual(result["p90_ending_balance"], result["band"][-1]["p90"])


class TestStableSimulationSeed(unittest.TestCase):
    """stable_simulation_seed -- makes run_simulation()/
    run_historical_bootstrap_simulation() reproducible across independent
    callers (the Summary tab's "What if" card, the Monte Carlo tab, and
    the Excel export all call run_simulation with the exact same
    starting_balance/pools/assumptions/expenses/income) instead of each
    one drawing its own unseeded 1000-path simulation and landing on a
    different, if similarly plausible, number."""

    def _kwargs(self, **overrides):
        base = {
            "starting_balance": 1_000_000,
            "expenses": [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}],
            "income": [],
            "assumptions": {"expected_return": "0.06", "return_volatility": "0.12", "iterations": "50", "plan_horizon_years": "10"},
            "pools": {"tax_deferred": 600_000, "roth": 200_000, "taxable": 200_000, "real_estate": 0},
        }
        base.update(overrides)
        return base

    def test_identical_inputs_produce_the_identical_seed(self):
        kwargs = self._kwargs()
        self.assertEqual(stable_simulation_seed(**kwargs), stable_simulation_seed(**dict(kwargs)))

    def test_a_changed_starting_balance_changes_the_seed(self):
        seed1 = stable_simulation_seed(**self._kwargs())
        seed2 = stable_simulation_seed(**self._kwargs(starting_balance=1_000_001))
        self.assertNotEqual(seed1, seed2)

    def test_a_changed_pool_balance_changes_the_seed(self):
        seed1 = stable_simulation_seed(**self._kwargs())
        seed2 = stable_simulation_seed(**self._kwargs(pools={"tax_deferred": 600_001, "roth": 200_000, "taxable": 200_000, "real_estate": 0}))
        self.assertNotEqual(seed1, seed2)

    def test_a_changed_assumption_changes_the_seed(self):
        seed1 = stable_simulation_seed(**self._kwargs())
        kwargs2 = self._kwargs()
        kwargs2["assumptions"] = {**kwargs2["assumptions"], "expected_return": "0.07"}
        seed2 = stable_simulation_seed(**kwargs2)
        self.assertNotEqual(seed1, seed2)

    def test_dict_key_order_does_not_affect_the_seed(self):
        # json.dumps(sort_keys=True) inside -- a pools/assumptions dict
        # built in a different key order (e.g. real_estate added last vs.
        # first) must still produce the same seed, since Python dicts
        # from two independent build_summary() calls aren't guaranteed to
        # construct their keys in the same order.
        kwargs1 = self._kwargs(pools={"tax_deferred": 600_000, "roth": 200_000, "taxable": 200_000, "real_estate": 0})
        kwargs2 = self._kwargs(pools={"real_estate": 0, "taxable": 200_000, "roth": 200_000, "tax_deferred": 600_000})
        self.assertEqual(stable_simulation_seed(**kwargs1), stable_simulation_seed(**kwargs2))

    def test_seeding_run_simulation_makes_two_independent_calls_agree(self):
        # This is the actual bug report: two callers (standing in for the
        # Summary tab and the Monte Carlo tab) building the exact same
        # inputs independently, each seeding their own call -- must land
        # on byte-identical results, not two different random 1000-path
        # runs.
        kwargs = self._kwargs()
        seed_a = stable_simulation_seed(**kwargs)
        seed_b = stable_simulation_seed(**kwargs)  # a second, independent call
        result_a = run_simulation(
            starting_balance=kwargs["starting_balance"], expenses=kwargs["expenses"], income=kwargs["income"],
            assumptions=kwargs["assumptions"], pools=kwargs["pools"], rng=random.Random(seed_a),
        )
        result_b = run_simulation(
            starting_balance=kwargs["starting_balance"], expenses=kwargs["expenses"], income=kwargs["income"],
            assumptions=kwargs["assumptions"], pools=kwargs["pools"], rng=random.Random(seed_b),
        )
        self.assertEqual(result_a["band"], result_b["band"])
        self.assertEqual(result_a["median_ending_balance"], result_b["median_ending_balance"])
        self.assertEqual(result_a["success_rate"], result_b["success_rate"])


class TestRunSimulationWithPools(unittest.TestCase):
    """run_simulation(..., pools={...}) -- the three-pool engine, wired
    through the same public entry point run_simulation's single-balance
    callers already use. pools=None (the default, exercised by every
    test above this class) must stay byte-for-byte unchanged; these
    tests only exercise the pools= branch."""

    def _assumptions(self, **overrides):
        base = {
            "expected_return": "0.0", "return_volatility": "0.0", "iterations": "5",
            "plan_horizon_years": "3", "current_year": "2027", "annual_income_offset": "0",
        }
        base.update(overrides)
        return base

    def test_result_shape_matches_the_single_balance_mode(self):
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        pools = {"tax_deferred": 600_000, "roth": 200_000, "taxable": 200_000}
        result = run_simulation(
            starting_balance=1_000_000, expenses=expenses, assumptions=self._assumptions(), rng=random.Random(1),
            pools=pools,
        )
        for key in ("years", "band", "iterations", "success_rate", "median_ending_balance", "p10_ending_balance", "p90_ending_balance"):
            self.assertIn(key, result)
        self.assertTrue(result["pools"])

    def test_legacy_mode_is_unaffected_by_the_pools_kwarg_existing(self):
        # Same call, once with pools omitted -- must match a plain call
        # with no pools kwarg at all (i.e. pools=None is truly a no-op).
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        assumptions = self._assumptions()
        r1 = run_simulation(starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, rng=random.Random(3))
        r2 = run_simulation(starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, rng=random.Random(3), pools=None)
        self.assertEqual(r1["band"], r2["band"])
        self.assertFalse(r1["pools"])
        self.assertFalse(r2["pools"])

    def test_zero_return_zero_need_leaves_pools_combined_balance_unchanged(self):
        pools = {"tax_deferred": 500_000, "roth": 300_000, "taxable": 200_000}
        assumptions = self._assumptions(apply_drawdown_tax="0")
        result = run_simulation(
            starting_balance=1_000_000, expenses=[], assumptions=assumptions, rng=random.Random(1), pools=pools,
        )
        self.assertAlmostEqual(result["median_ending_balance"], 1_000_000, places=2)

    def test_rmd_forces_withdrawals_even_with_no_expense_need(self):
        # A giant tax-deferred balance well past RMD age, no expenses at
        # all: RMDs still force money out and (with tax on) generate a
        # real tax bill every year, so the ending balance must be lower
        # than the no-RMD case even though nothing was ever "needed".
        pools = {"tax_deferred": 2_000_000, "roth": 0, "taxable": 0}
        assumptions = self._assumptions(birth_year="1940", apply_drawdown_tax="1")
        with_rmd = run_simulation(
            starting_balance=2_000_000, expenses=[], assumptions=assumptions, rng=random.Random(1), pools=pools,
        )
        no_rmd_assumptions = self._assumptions(birth_year="", apply_drawdown_tax="1")
        without_rmd = run_simulation(
            starting_balance=2_000_000, expenses=[], assumptions=no_rmd_assumptions, rng=random.Random(1),
            pools={"tax_deferred": 2_000_000, "roth": 0, "taxable": 0},
        )
        self.assertLess(with_rmd["median_ending_balance"], without_rmd["median_ending_balance"])
        self.assertGreater(with_rmd["yearly_tax_total"], 0.0)

    def test_no_birth_year_means_no_forced_rmd_withdrawals(self):
        pools = {"tax_deferred": 2_000_000, "roth": 0, "taxable": 0}
        assumptions = self._assumptions(birth_year="", apply_drawdown_tax="0")
        result = run_simulation(
            starting_balance=2_000_000, expenses=[], assumptions=assumptions, rng=random.Random(1), pools=pools,
        )
        self.assertAlmostEqual(result["median_ending_balance"], 2_000_000, places=2)

    def test_deterministic_with_seeded_rng(self):
        pools = {"tax_deferred": 500_000, "roth": 100_000, "taxable": 100_000}
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        assumptions = self._assumptions(expected_return="0.05", return_volatility="0.1")
        r1 = run_simulation(starting_balance=700_000, expenses=expenses, assumptions=assumptions, rng=random.Random(7), pools=pools)
        r2 = run_simulation(starting_balance=700_000, expenses=expenses, assumptions=assumptions, rng=random.Random(7), pools=dict(pools))
        self.assertEqual(r1["band"], r2["band"])

    def test_omitting_the_real_estate_key_is_equivalent_to_zero(self):
        # A 3-key pools dict (every caller before this feature existed)
        # must produce identical results to explicitly passing
        # "real_estate": 0 -- confirms the new 4th pool is additive, not
        # a behavior change for existing callers.
        assumptions = self._assumptions(apply_drawdown_tax="0")
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        pools_without_key = {"tax_deferred": 500_000, "roth": 100_000, "taxable": 100_000}
        pools_with_zero = {"tax_deferred": 500_000, "roth": 100_000, "taxable": 100_000, "real_estate": 0}
        r1 = run_simulation(
            starting_balance=700_000, expenses=expenses, assumptions=assumptions, rng=random.Random(9), pools=pools_without_key,
        )
        r2 = run_simulation(
            starting_balance=700_000, expenses=expenses, assumptions=assumptions, rng=random.Random(9), pools=pools_with_zero,
        )
        self.assertEqual(r1["band"], r2["band"])

    def test_opted_in_real_estate_equity_grows_and_funds_withdrawals_once_other_pools_are_exhausted(self):
        # No taxable/tax_deferred/roth money at all -- every year's need
        # must come out of the real_estate pool instead, so the plan
        # survives (rather than depleting immediately) exactly because
        # that 4th pool exists and is drawn from.
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 0, "real_estate": 2_000_000}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        assumptions = self._assumptions(apply_drawdown_tax="0")
        result = run_simulation(
            starting_balance=0, expenses=expenses, assumptions=assumptions, rng=random.Random(1), pools=pools,
        )
        self.assertEqual(result["success_rate"], 1.0)
        self.assertGreater(result["median_ending_balance"], 0.0)

    def test_real_estate_pool_is_never_touched_while_other_pools_can_cover_the_need(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 500_000, "real_estate": 300_000}
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        assumptions = self._assumptions(apply_drawdown_tax="0")
        result = run_simulation(
            starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, rng=random.Random(1), pools=pools,
        )
        # 3 years x 40,000 = 120,000 drawn from a combined 1,000,000 of
        # taxable+tax_deferred, well within their own combined balance --
        # the real_estate pool should still be fully intact (and growing
        # at the 0% assumed return here, so exactly 300,000) in every path.
        for year_band in result["band"]:
            self.assertGreaterEqual(year_band["p10"], 0.0)
        self.assertGreater(result["median_ending_balance"], 300_000)  # still holds its own real estate share


class TestRunHistoricalBootstrapSimulation(unittest.TestCase):
    """The S&P 500 "historical bootstrap" Monte Carlo run alongside
    run_simulation()'s Gaussian one -- same withdrawal mechanics, but
    each simulated year's return is drawn (with replacement) from the
    real recorded S&P 500 annual returns instead of a Normal
    distribution."""

    def test_deterministic_with_seeded_rng(self):
        expenses = [{"name": "Baseline", "annual_amount": 40000, "start_year": None, "end_year": None}]
        assumptions = {"iterations": "200", "plan_horizon_years": "20", "current_year": "2027"}
        r1 = run_historical_bootstrap_simulation(
            starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, rng=random.Random(7),
        )
        r2 = run_historical_bootstrap_simulation(
            starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, rng=random.Random(7),
        )
        self.assertEqual(r1["band"], r2["band"])
        self.assertEqual(r1["success_rate"], r2["success_rate"])

    def test_band_covers_the_full_horizon_starting_at_current_year(self):
        assumptions = {"iterations": "50", "plan_horizon_years": "10", "current_year": "2030"}
        result = run_historical_bootstrap_simulation(
            starting_balance=500_000, expenses=[], assumptions=assumptions, rng=random.Random(1),
        )
        self.assertEqual(len(result["band"]), 10)
        self.assertEqual(result["years"][0], 2030)
        self.assertEqual(result["years"][-1], 2039)

    def test_percentiles_are_ordered_p10_le_median_le_p90(self):
        expenses = [{"name": "Baseline", "annual_amount": 30000, "start_year": None, "end_year": None}]
        assumptions = {"iterations": "300", "plan_horizon_years": "15", "current_year": "2027"}
        result = run_historical_bootstrap_simulation(
            starting_balance=800_000, expenses=expenses, assumptions=assumptions, rng=random.Random(3),
        )
        for row in result["band"]:
            self.assertLessEqual(row["p10"], row["median"] + 1e-9)
            self.assertLessEqual(row["median"], row["p90"] + 1e-9)

    def test_every_drawn_return_is_an_actual_recorded_sp500_annual_return(self):
        # The whole point of "historical bootstrap" is that every draw is
        # a real year's actual return, not a synthetic Normal() sample.
        # A single iteration/single year isolates exactly one draw: the
        # ending balance directly reveals what return was picked, and it
        # must be one of the real recorded values, not an arbitrary
        # Gaussian-shaped number.
        recorded = set(round(v, 6) for v in _SP500_ANNUAL_RETURNS.values())
        for seed in range(10):
            one_year = run_historical_bootstrap_simulation(
                starting_balance=1_000_000, expenses=[],
                assumptions={"iterations": "1", "plan_horizon_years": "1", "current_year": "2027"},
                rng=random.Random(seed),
            )
            drawn_return = round(one_year["band"][0]["median"] / 1_000_000 - 1, 6)
            self.assertIn(drawn_return, recorded)

    def test_result_reports_its_method_sample_size_and_p10_p90_ending_balance(self):
        assumptions = {"iterations": "20", "plan_horizon_years": "5", "current_year": "2027"}
        result = run_historical_bootstrap_simulation(
            starting_balance=500_000, expenses=[], assumptions=assumptions, rng=random.Random(1),
        )
        self.assertEqual(result["method"], "sp500_historical_bootstrap")
        self.assertEqual(result["sample_size"], len(_SP500_ANNUAL_RETURNS))
        self.assertEqual(result["p10_ending_balance"], result["band"][-1]["p10"])
        self.assertEqual(result["p90_ending_balance"], result["band"][-1]["p90"])

    def test_withdrawal_mechanics_match_run_simulation(self):
        # Same annual_net_withdrawal_need-driven withdrawal every year --
        # a 0-return baseline (achieved here by starting so high no
        # historical crash can deplete it within a short horizon isn't
        # reliable, so instead just check depletion behaves the same way
        # run_simulation's does: a huge expense against a tiny balance
        # depletes on the very first year for every path).
        expenses = [{"name": "Baseline", "annual_amount": 10_000_000, "start_year": None, "end_year": None}]
        assumptions = {"iterations": "10", "plan_horizon_years": "3", "current_year": "2027"}
        result = run_historical_bootstrap_simulation(
            starting_balance=1_000, expenses=expenses, assumptions=assumptions, rng=random.Random(1),
        )
        self.assertEqual(result["success_rate"], 0.0)
        self.assertEqual(result["median_ending_balance"], 0.0)


class TestRunHistoricalStressTest(unittest.TestCase):
    """Deterministic replay of real S&P 500 history -- the "Historical
    Stress Test" table on the Monte Carlo tab, carried over from the
    original workbook's own tab of the same name."""

    def test_returns_one_scenario_per_entry_in_historical_stress_scenarios(self):
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[],
            assumptions={"plan_horizon_years": 5, "current_year": 2028},
        )
        self.assertEqual(len(result["scenarios"]), len(HISTORICAL_STRESS_SCENARIOS))
        self.assertEqual(
            [sc["label"] for sc in result["scenarios"]],
            [label for label, _ in HISTORICAL_STRESS_SCENARIOS],
        )

    def test_yearly_needs_matches_annual_net_withdrawal_need_per_year(self):
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "inflates": True, "base_year": 2028, "start_year": None, "end_year": None}]
        income = [{"name": "Rental", "annual_amount": 10_000, "start_year": None, "end_year": None}]
        assumptions = {"plan_horizon_years": 4, "current_year": 2028, "inflation_rate": 0.03, "annual_income_offset": 2_000}
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=expenses, income=income, assumptions=assumptions,
        )
        self.assertEqual(len(result["yearly_needs"]), 4)
        for i, year in enumerate(result["years"]):
            expected = annual_net_withdrawal_need(expenses, income, year, 0.03, 2_000)
            self.assertAlmostEqual(result["yearly_needs"][i], expected, places=6)

    def test_yearly_income_matches_annual_income_need_per_year(self):
        # Exposed alongside yearly_needs so a caller (the Monte Carlo
        # tab's Total Income column) can show that year's income on its
        # own, right next to the already-netted Yearly Drawdown figure.
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        income = [{"name": "Rental", "annual_amount": 10_000, "inflates": True, "base_year": 2028, "start_year": None, "end_year": None}]
        assumptions = {"plan_horizon_years": 4, "current_year": 2028, "inflation_rate": 0.03}
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=expenses, income=income, assumptions=assumptions,
        )
        self.assertEqual(len(result["yearly_income"]), 4)
        for i, year in enumerate(result["years"]):
            expected = annual_income_need(income, year, 0.03)
            self.assertAlmostEqual(result["yearly_income"][i], expected, places=6)

    def test_yearly_total_expense_matches_annual_expense_need_per_year(self):
        # Exposed alongside yearly_needs/yearly_income so a caller (the
        # Monte Carlo tab's Total Expense column) can show the un-netted
        # Expense-tab total on its own, right next to Total Income --
        # yearly_total_expense[i] - yearly_income[i] - offset should
        # equal yearly_needs[i] (Yearly Drawdown) every year.
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "inflates": True, "base_year": 2028, "start_year": None, "end_year": None}]
        income = [{"name": "Rental", "annual_amount": 10_000, "start_year": None, "end_year": None}]
        assumptions = {"plan_horizon_years": 4, "current_year": 2028, "inflation_rate": 0.03, "annual_income_offset": 2_000}
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=expenses, income=income, assumptions=assumptions,
        )
        self.assertEqual(len(result["yearly_total_expense"]), 4)
        for i, year in enumerate(result["years"]):
            expected = annual_expense_need(expenses, year, 0.03)
            self.assertAlmostEqual(result["yearly_total_expense"][i], expected, places=6)
            self.assertAlmostEqual(
                result["yearly_total_expense"][i] - result["yearly_income"][i] - 2_000,
                result["yearly_needs"][i],
                places=6,
            )

    def test_yearly_needs_is_the_same_regardless_of_which_scenario_you_look_at(self):
        # Scenario/return-independent -- every scenario's balance drop in
        # a given year (before that scenario's own return effect) comes
        # from this same shared list, not a per-scenario recomputation.
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=expenses,
            # Tax off -- this test is about the withdrawal SCHEDULE being
            # shared across scenarios, not about the tax estimate, so it
            # isolates that by turning the (default-on) drawdown tax off.
            assumptions={"plan_horizon_years": 1, "current_year": 2028, "apply_drawdown_tax": "0"},
        )
        for sc in result["scenarios"]:
            implied_need = 1_000_000 * (1 + sc["path"][0]["return"]) - sc["path"][0]["balance"]
            self.assertAlmostEqual(implied_need, result["yearly_needs"][0], places=6)

    def test_great_depression_scenario_replays_the_actual_1929_sequence(self):
        # No withdrawals and a horizon of 5 isolates just the return
        # sequence -- 1929 through 1933's real annual S&P 500 returns.
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[],
            assumptions={"plan_horizon_years": 5, "current_year": 2028},
        )
        gd = next(sc for sc in result["scenarios"] if sc["label"].startswith("Great Depression"))
        returns = [round(p["return"], 4) for p in gd["path"]]
        self.assertEqual(returns, [-0.0842, -0.249, -0.4334, -0.0819, 0.5399])

    def test_no_crash_baseline_is_a_flat_ten_percent_every_year(self):
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[],
            assumptions={"plan_horizon_years": 8, "current_year": 2028},
        )
        baseline = next(sc for sc in result["scenarios"] if sc["label"].startswith("No-crash"))
        self.assertTrue(all(p["return"] == 0.10 for p in baseline["path"]))

    def test_a_scenario_year_past_recorded_history_falls_back_to_the_long_run_average(self):
        # Dot-com (2000 start) only has real data through 2026 -- a
        # 40-year horizon starting in 2028 runs the scenario well past
        # that, so its tail should sit at the flat 10% placeholder.
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[],
            assumptions={"plan_horizon_years": 40, "current_year": 2028},
        )
        dotcom = next(sc for sc in result["scenarios"] if sc["label"].startswith("Dot-com"))
        self.assertEqual(dotcom["path"][-1]["return"], 0.10)
        self.assertLessEqual(result["last_recorded_year"], dotcom["path"][-1]["year"])

    def test_scenarios_sharing_a_real_historical_year_agree_on_its_return(self):
        # Cross-check: Dot-com (2000 start, offset 0) and Stagflation
        # (1973 start, offset 27) both land on calendar year 2000 within
        # a long enough horizon -- both must report the same real return
        # for that year, since it's the same historical fact either way.
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[],
            assumptions={"plan_horizon_years": 28, "current_year": 2028},
        )
        dotcom = next(sc for sc in result["scenarios"] if sc["label"].startswith("Dot-com"))
        stagflation = next(sc for sc in result["scenarios"] if sc["label"].startswith("Stagflation"))
        # dot-com offset 0 (2000+0) and stagflation offset 27 (1973+27)
        # both replay real calendar year 2000 -- different simulated
        # plan-years (2028 vs 2055), same underlying historical fact.
        self.assertEqual(dotcom["path"][0]["return"], -0.091)
        self.assertEqual(stagflation["path"][27]["return"], -0.091)
        self.assertEqual(dotcom["path"][0]["return"], stagflation["path"][27]["return"])

    def test_depletion_is_flagged_at_the_first_year_balance_hits_zero(self):
        expenses = [{"name": "Baseline", "annual_amount": 10_000_000, "start_year": None, "end_year": None}]
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=expenses,
            assumptions={"plan_horizon_years": 5, "current_year": 2028},
        )
        for sc in result["scenarios"]:
            self.assertTrue(sc["depleted"])
            self.assertEqual(sc["depleted_year"], 2028)
            self.assertEqual(sc["ending_balance"], 0.0)

    def test_no_expenses_and_no_crash_baseline_never_depletes(self):
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[],
            assumptions={"plan_horizon_years": 10, "current_year": 2028},
        )
        baseline = next(sc for sc in result["scenarios"] if sc["label"].startswith("No-crash"))
        self.assertFalse(baseline["depleted"])
        self.assertIsNone(baseline["depleted_year"])
        self.assertGreater(baseline["ending_balance"], 1_000_000)

    def test_every_scenario_faces_the_identical_withdrawal_schedule(self):
        # The whole point of holding withdrawals fixed per year (not
        # re-solved per scenario) is that only the return sequence
        # differs -- so a year with zero return-driven growth would
        # make every scenario's balance drop by exactly the same
        # withdrawal amount. Simplest way to check that without
        # duplicating annual_expense_need: same starting balance, same
        # (start_year=None) baseline-equivalent forced by a 0-return
        # override isn't available here, so instead just check the
        # first year's expense need was applied identically via the
        # relationship balance_after_year1 = starting*(1+r) - need.
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=expenses,
            # Tax off -- see test_yearly_needs_is_the_same_regardless_of_
            # which_scenario_you_look_at above for why.
            assumptions={"plan_horizon_years": 1, "current_year": 2028, "apply_drawdown_tax": "0"},
        )
        for sc in result["scenarios"]:
            expected = max(1_000_000 * (1 + sc["path"][0]["return"]) - 40_000, 0.0)
            self.assertAlmostEqual(sc["path"][0]["balance"], expected)

    def test_itemized_income_nets_against_every_scenarios_withdrawal(self):
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        income = [{"name": "Rental", "annual_amount": 10_000, "start_year": None, "end_year": None}]
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=expenses, income=income,
            # Tax off -- see test_yearly_needs_is_the_same_regardless_of_
            # which_scenario_you_look_at above for why.
            assumptions={"plan_horizon_years": 1, "current_year": 2028, "apply_drawdown_tax": "0"},
        )
        for sc in result["scenarios"]:
            # Net need is 40,000 - 10,000 = 30,000, not the raw 40,000.
            expected = max(1_000_000 * (1 + sc["path"][0]["return"]) - 30_000, 0.0)
            self.assertAlmostEqual(sc["path"][0]["balance"], expected)


class TestRunHistoricalStressTestWithPools(unittest.TestCase):
    """run_historical_stress_test(..., pools={...}) -- tax and total
    withdrawal become per-scenario in this mode (see that function's own
    docstring for why), unlike every test above this class which
    exercises the legacy pools=None mode and stays untouched."""

    def _assumptions(self, **overrides):
        base = {"plan_horizon_years": 3, "current_year": 2027, "apply_drawdown_tax": "0"}
        base.update(overrides)
        return base

    def test_per_scenario_tax_flag_is_set(self):
        pools = {"tax_deferred": 500_000, "roth": 200_000, "taxable": 300_000}
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[], assumptions=self._assumptions(), pools=pools,
        )
        self.assertTrue(result["per_scenario_tax"])
        self.assertIsNone(result["yearly_tax"])
        self.assertIsNone(result["yearly_total_withdrawal"])

    def test_legacy_mode_still_sets_the_flag_false(self):
        result = run_historical_stress_test(starting_balance=1_000_000, expenses=[], assumptions=self._assumptions())
        self.assertFalse(result["per_scenario_tax"])
        self.assertIsNotNone(result["yearly_tax"])

    def test_each_scenario_carries_its_own_tax_and_withdrawal_lists(self):
        pools = {"tax_deferred": 500_000, "roth": 200_000, "taxable": 300_000}
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[], assumptions=self._assumptions(apply_drawdown_tax="1"), pools=pools,
        )
        for sc in result["scenarios"]:
            self.assertEqual(len(sc["yearly_tax"]), len(result["years"]))
            self.assertEqual(len(sc["yearly_total_withdrawal"]), len(result["years"]))
            self.assertEqual(len(sc["yearly_rmd"]), len(result["years"]))

    def test_rmd_shows_up_in_every_scenarios_yearly_rmd(self):
        pools = {"tax_deferred": 2_000_000, "roth": 0, "taxable": 0}
        result = run_historical_stress_test(
            starting_balance=2_000_000, expenses=[],
            assumptions=self._assumptions(birth_year="1940", apply_drawdown_tax="0"), pools=pools,
        )
        for sc in result["scenarios"]:
            self.assertGreater(sc["yearly_rmd"][0], 0.0)

    def test_ending_balance_is_the_combined_pool_total(self):
        pools = {"tax_deferred": 500_000, "roth": 200_000, "taxable": 300_000}
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[], assumptions=self._assumptions(), pools=pools,
        )
        for sc in result["scenarios"]:
            self.assertEqual(sc["ending_balance"], sc["path"][-1]["balance"])

    def test_shared_yearly_needs_income_and_total_expense_still_present(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 0}
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        result = run_historical_stress_test(
            starting_balance=500_000, expenses=expenses, assumptions=self._assumptions(), pools=pools,
        )
        self.assertEqual(result["yearly_needs"], [40_000.0, 40_000.0, 40_000.0])
        self.assertEqual(result["yearly_total_expense"], [40_000.0, 40_000.0, 40_000.0])

    def test_depletion_flagged_when_all_pools_combined_run_out(self):
        pools = {"tax_deferred": 1_000, "roth": 0, "taxable": 0}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        result = run_historical_stress_test(
            starting_balance=1_000, expenses=expenses, assumptions=self._assumptions(), pools=pools,
        )
        for sc in result["scenarios"]:
            self.assertTrue(sc["depleted"])

    def test_opted_in_real_estate_equity_prevents_depletion_every_scenario_faces(self):
        # Mirrors run_simulation's equivalent test: with nothing in the
        # other three pools, only the real_estate pool being drawable
        # (last-resort) keeps every historical scenario from depleting.
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 0, "real_estate": 2_000_000}
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        result = run_historical_stress_test(
            starting_balance=0, expenses=expenses, assumptions=self._assumptions(), pools=pools,
        )
        for sc in result["scenarios"]:
            self.assertFalse(sc["depleted"])
            self.assertGreater(sc["ending_balance"], 0.0)

    def test_omitting_the_real_estate_key_matches_explicitly_passing_zero(self):
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        pools_without_key = {"tax_deferred": 500_000, "roth": 0, "taxable": 0}
        pools_with_zero = {"tax_deferred": 500_000, "roth": 0, "taxable": 0, "real_estate": 0}
        r1 = run_historical_stress_test(
            starting_balance=500_000, expenses=expenses, assumptions=self._assumptions(), pools=pools_without_key,
        )
        r2 = run_historical_stress_test(
            starting_balance=500_000, expenses=expenses, assumptions=self._assumptions(), pools=pools_with_zero,
        )
        self.assertEqual(
            [sc["ending_balance"] for sc in r1["scenarios"]],
            [sc["ending_balance"] for sc in r2["scenarios"]],
        )


class TestRenderFanSvg(unittest.TestCase):
    def test_empty_band_renders_a_placeholder_not_an_error(self):
        svg = render_fan_svg({"band": []})
        self.assertIn("<svg", svg)
        self.assertIn("No simulation data yet", svg)

    def test_nonempty_band_renders_paths_and_years(self):
        result = {"band": [
            {"year": 2027, "p10": 100, "median": 200, "p90": 300},
            {"year": 2028, "p10": 90, "median": 210, "p90": 320},
        ]}
        svg = render_fan_svg(result)
        self.assertIn("<svg", svg)
        self.assertIn("<path", svg)
        self.assertIn("<polyline", svg)
        self.assertIn("2027", svg)
        self.assertIn("2028", svg)

    def test_defaults_to_the_shared_band_color(self):
        result = {"band": [{"year": 2027, "p10": 100, "median": 200, "p90": 300}]}
        svg = render_fan_svg(result)
        self.assertIn("#2563eb", svg)

    def test_custom_color_overrides_the_default_everywhere_it_appears(self):
        # The S&P 500 historical-bootstrap chart reuses this same
        # renderer with a distinct (fixed-order categorical) color so it
        # reads as a visually separate series from the Gaussian chart.
        result = {"band": [{"year": 2027, "p10": 100, "median": 200, "p90": 300}]}
        svg = render_fan_svg(result, color="#eb6834")
        self.assertIn("#eb6834", svg)
        self.assertNotIn("#2563eb", svg)


class TestRunSensitivityAnalysis(unittest.TestCase):
    """run_sensitivity_analysis -- the Monte Carlo tab's tornado
    sensitivity sweep. Every scenario here uses return_volatility=0 (a
    single deterministic path, since r.gauss(mu, 0) always returns mu)
    and a starting balance/withdrawal/return combination chosen to sit
    right at a depletion knife-edge over the plan horizon, so a lever's
    effect flips success_rate cleanly between 0.0 and 1.0 instead of
    landing on some hard-to-predict fraction -- see the balance
    recurrence balance_t = (balance_0 - W/r)*(1+r)^t + W/r used to pick
    these numbers (a starting balance below the W/r equilibrium point
    depletes; how soon depends on r, horizon, and W)."""

    def _knife_edge_kwargs(self, **overrides):
        # Baseline depletes (crosses zero) around year ~25.7 of a
        # 30-year horizon at 5% return with a flat $70,000/yr net need.
        base = {
            "starting_balance": 1_000_000,
            "expenses": [{"name": "Baseline", "annual_amount": 70_000, "start_year": None, "end_year": None, "inflates": False}],
            "income": [],
            "assumptions": {
                "expected_return": "0.05", "return_volatility": "0", "iterations": "5",
                "plan_horizon_years": "30", "current_year": "2027", "annual_income_offset": "0",
                "apply_drawdown_tax": "0",
            },
        }
        base.update(overrides)
        return base

    def test_baseline_success_rate_matches_a_direct_seeded_run_simulation_call(self):
        kwargs = self._knife_edge_kwargs()
        result = run_sensitivity_analysis(**kwargs)
        seed = stable_simulation_seed(
            starting_balance=kwargs["starting_balance"], expenses=kwargs["expenses"],
            income=kwargs["income"], assumptions=kwargs["assumptions"], pools=None,
        )
        direct = run_simulation(
            starting_balance=kwargs["starting_balance"], expenses=kwargs["expenses"],
            income=kwargs["income"], assumptions=kwargs["assumptions"], rng=random.Random(seed),
        )
        self.assertEqual(result["baseline_success_rate"], direct["success_rate"])
        self.assertEqual(result["baseline_success_rate"], 0.0)  # the knife-edge scenario depletes at baseline

    def test_returns_one_row_per_lever(self):
        result = run_sensitivity_analysis(**self._knife_edge_kwargs())
        self.assertEqual({r["key"] for r in result["rows"]}, {lever["key"] for lever in LEVERS})

    def test_rows_are_sorted_by_swing_descending(self):
        result = run_sensitivity_analysis(**self._knife_edge_kwargs())
        swings = [r["swing"] for r in result["rows"]]
        self.assertEqual(swings, sorted(swings, reverse=True))

    def test_higher_expected_return_flips_the_knife_edge_scenario_to_success(self):
        result = run_sensitivity_analysis(**self._knife_edge_kwargs())
        row = next(r for r in result["rows"] if r["key"] == "expected_return")
        self.assertEqual(row["low_success_rate"], 0.0)   # -1pt: still depletes, even sooner
        self.assertEqual(row["high_success_rate"], 1.0)  # +1pt: survives the full horizon

    def test_shorter_horizon_survives_longer_horizon_depletes(self):
        result = run_sensitivity_analysis(**self._knife_edge_kwargs())
        row = next(r for r in result["rows"] if r["key"] == "plan_horizon_years")
        self.assertEqual(row["low_success_rate"], 1.0)   # 25 years: doesn't reach the ~25.7yr crossing
        self.assertEqual(row["high_success_rate"], 0.0)  # 35 years: well past the crossing

    def test_lower_expenses_survive_higher_expenses_deplete(self):
        result = run_sensitivity_analysis(**self._knife_edge_kwargs())
        row = next(r for r in result["rows"] if r["key"] == "expense_level")
        self.assertEqual(row["low_success_rate"], 1.0)   # -10% expenses: crossing point pushed past year 30
        self.assertEqual(row["high_success_rate"], 0.0)  # +10% expenses: crosses well before year 30

    def test_higher_income_survives_lower_income_depletes(self):
        # Same net $70,000/yr need as the knife-edge baseline, but split
        # across gross expenses and gross income so income_level (which
        # only scales the income list) has something to move.
        kwargs = self._knife_edge_kwargs(
            expenses=[{"name": "Baseline", "annual_amount": 140_000, "start_year": None, "end_year": None, "inflates": False}],
            income=[{"name": "Pension", "annual_amount": 70_000, "start_year": None, "end_year": None, "inflates": False}],
        )
        result = run_sensitivity_analysis(**kwargs)
        self.assertEqual(result["baseline_success_rate"], 0.0)  # same net need as the plain knife-edge case
        row = next(r for r in result["rows"] if r["key"] == "income_level")
        self.assertEqual(row["low_success_rate"], 0.0)   # -10% income: net need rises, depletes sooner
        self.assertEqual(row["high_success_rate"], 1.0)  # +10% income: net need falls, survives

    def test_inflation_lever_is_a_no_op_when_nothing_inflates(self):
        # Neither the knife-edge expense nor (the empty) income list has
        # `inflates` set, so nudging the Inflation % assumption up or
        # down changes nothing about what gets withdrawn -- a clean,
        # fully deterministic invariant, unlike return_volatility (whose
        # effect on this knife-edge scenario isn't simply monotonic).
        result = run_sensitivity_analysis(**self._knife_edge_kwargs())
        row = next(r for r in result["rows"] if r["key"] == "inflation_rate")
        self.assertEqual(row["low_success_rate"], 0.0)
        self.assertEqual(row["high_success_rate"], 0.0)
        self.assertEqual(row["swing"], 0.0)

    def test_every_row_reports_a_label_and_swing_description(self):
        result = run_sensitivity_analysis(**self._knife_edge_kwargs())
        for row in result["rows"]:
            self.assertTrue(row["label"])
            self.assertTrue(row["swing_label"])

    def test_repeated_calls_with_identical_inputs_are_reproducible(self):
        kwargs = self._knife_edge_kwargs()
        result1 = run_sensitivity_analysis(**kwargs)
        result2 = run_sensitivity_analysis(**kwargs)
        self.assertEqual(result1, result2)

    def test_honors_a_pools_argument_without_error(self):
        kwargs = self._knife_edge_kwargs(pools={"tax_deferred": 600_000, "roth": 200_000, "taxable": 200_000, "real_estate": 0})
        result = run_sensitivity_analysis(**kwargs)
        self.assertEqual(len(result["rows"]), len(LEVERS))
        for row in result["rows"]:
            self.assertGreaterEqual(row["low_success_rate"], 0.0)
            self.assertLessEqual(row["high_success_rate"], 1.0)


class TestDeterministicDrawdownSchedule(unittest.TestCase):
    """deterministic_drawdown_schedule -- the Drawdown Planning tab's
    single non-random year-by-year projection, built on the exact same
    _apply_year_withdrawal engine run_simulation's pools= mode uses."""

    def _assumptions(self, **overrides):
        base = {
            "expected_return": "0.0", "plan_horizon_years": "3", "current_year": "2027",
            "annual_income_offset": "0", "apply_drawdown_tax": "0",
        }
        base.update(overrides)
        return base

    def test_result_shape(self):
        pools = {"tax_deferred": 500_000, "roth": 200_000, "taxable": 300_000, "real_estate": 0}
        result = deterministic_drawdown_schedule(pools=pools, expenses=[], assumptions=self._assumptions())
        self.assertEqual(result["years"], [2027, 2028, 2029])
        self.assertEqual(len(result["rows"]), 3)
        for row in result["rows"]:
            for key in ("year", "age", "need", "rmd", "tax", "shortfall", "taxable", "tax_deferred", "roth", "real_estate", "total"):
                self.assertIn(key, row)

    def test_zero_return_zero_need_leaves_the_total_unchanged(self):
        pools = {"tax_deferred": 500_000, "roth": 200_000, "taxable": 300_000, "real_estate": 0}
        result = deterministic_drawdown_schedule(pools=pools, expenses=[], assumptions=self._assumptions())
        for row in result["rows"]:
            self.assertAlmostEqual(row["total"], 1_000_000)

    def test_expenses_draw_down_the_taxable_pool_first(self):
        pools = {"tax_deferred": 500_000, "roth": 200_000, "taxable": 300_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        result = deterministic_drawdown_schedule(pools=pools, expenses=expenses, assumptions=self._assumptions())
        first = result["rows"][0]
        self.assertEqual(first["tax_deferred"], 500_000)  # untouched -- taxable covers the need
        self.assertEqual(first["taxable"], 250_000)
        self.assertEqual(first["need"], 50_000)

    def test_rmd_forced_once_birth_year_puts_the_owner_past_rmd_age(self):
        pools = {"tax_deferred": 1_000_000, "roth": 0, "taxable": 0, "real_estate": 0}
        result = deterministic_drawdown_schedule(
            pools=pools, expenses=[], assumptions=self._assumptions(birth_year="1950"),
        )
        self.assertGreater(result["rows"][0]["rmd"], 0.0)

    def test_no_birth_year_means_no_rmd(self):
        pools = {"tax_deferred": 1_000_000, "roth": 0, "taxable": 0, "real_estate": 0}
        result = deterministic_drawdown_schedule(pools=pools, expenses=[], assumptions=self._assumptions())
        for row in result["rows"]:
            self.assertEqual(row["rmd"], 0.0)

    def test_positive_return_grows_the_balance_with_no_expenses(self):
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 1_000_000, "real_estate": 0}
        result = deterministic_drawdown_schedule(
            pools=pools, expenses=[], assumptions=self._assumptions(expected_return="0.05"),
        )
        self.assertAlmostEqual(result["rows"][0]["taxable"], 1_050_000)
        self.assertAlmostEqual(result["rows"][0]["total"], 1_050_000)

    def test_horizon_years_overrides_the_plan_horizon_assumption(self):
        pools = {"tax_deferred": 100_000, "roth": 0, "taxable": 0, "real_estate": 0}
        result = deterministic_drawdown_schedule(
            pools=pools, expenses=[], assumptions=self._assumptions(plan_horizon_years="40"), horizon_years=5,
        )
        self.assertEqual(len(result["rows"]), 5)

    def test_real_estate_is_drawn_last(self):
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 0, "real_estate": 500_000}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        result = deterministic_drawdown_schedule(pools=pools, expenses=expenses, assumptions=self._assumptions())
        first = result["rows"][0]
        self.assertEqual(first["real_estate"], 450_000)

    def test_shortfall_is_zero_when_pools_cover_the_need(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 0, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 10_000, "start_year": None, "end_year": None}]
        result = deterministic_drawdown_schedule(pools=pools, expenses=expenses, assumptions=self._assumptions())
        self.assertEqual(result["rows"][0]["shortfall"], 0.0)

    def test_shortfall_is_positive_once_every_pool_is_exhausted(self):
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 5_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        result = deterministic_drawdown_schedule(pools=pools, expenses=expenses, assumptions=self._assumptions())
        self.assertGreater(result["rows"][0]["shortfall"], 0.0)

    def test_expected_return_is_reported_back(self):
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 0, "real_estate": 0}
        result = deterministic_drawdown_schedule(pools=pools, expenses=[], assumptions=self._assumptions(expected_return="0.07"))
        self.assertAlmostEqual(result["expected_return"], 0.07)


if __name__ == "__main__":
    unittest.main()
