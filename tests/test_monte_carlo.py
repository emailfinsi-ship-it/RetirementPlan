import random
import re
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
    EARLY_TAX_DEFERRED_SPENDING_STRATEGIES,
    FEDERAL_LTCG_BRACKETS_MFJ_2026,
    ROTH_CONVERSION_STRATEGIES,
    _SP500_ANNUAL_RETURNS,
    _apply_year_withdrawal,
    _bracket_tax,
    _pool_year_tax,
    _resolve_birth_year,
    _resolve_early_tax_deferred_age,
    _resolve_gains_fraction,
    _resolve_retirement_year,
    _simulate_fill,
    _stacked_bracket_tax,
    compare_roth_conversion_strategies,
    estimate_default_heir_base_income,
    estimate_heir_tax_on_tax_deferred,
)
from source.reporting.monte_carlo.legacy_planning import (
    _DEFAULT_HEIR_SPREAD_YEARS,
    _cap_conversion_by_affordability,
    _combined_marginal_rate,
    _federal_bracket_ceiling,
    _resolve_heir_spread_years,
    _run_conversion_schedule,
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

    def test_retirement_year_omitted_means_no_gating(self):
        # Default (no retirement_year kwarg at all) -- every pre-existing
        # caller/test above this one must keep computing the need
        # exactly as before this parameter existed.
        expenses = [{"name": "Baseline", "annual_amount": 60_000, "start_year": None, "end_year": None}]
        self.assertEqual(annual_net_withdrawal_need(expenses, [], 2030), 60_000)

    def test_year_before_retirement_year_needs_nothing(self):
        expenses = [{"name": "Baseline", "annual_amount": 60_000, "start_year": None, "end_year": None}]
        need = annual_net_withdrawal_need(expenses, [], 2030, retirement_year=2035)
        self.assertEqual(need, 0.0)

    def test_year_at_or_after_retirement_year_needs_the_usual_amount(self):
        expenses = [{"name": "Baseline", "annual_amount": 60_000, "start_year": None, "end_year": None}]
        self.assertEqual(annual_net_withdrawal_need(expenses, [], 2035, retirement_year=2035), 60_000)
        self.assertEqual(annual_net_withdrawal_need(expenses, [], 2040, retirement_year=2035), 60_000)

    def test_retirement_year_none_means_no_gating_explicitly(self):
        expenses = [{"name": "Baseline", "annual_amount": 60_000, "start_year": None, "end_year": None}]
        need = annual_net_withdrawal_need(expenses, [], 2000, retirement_year=None)
        self.assertEqual(need, 60_000)


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

    def test_retirement_year_omitted_means_no_gating(self):
        expenses = [{"name": "Baseline", "annual_amount": 100_000, "start_year": None, "end_year": None}]
        schedule = yearly_withdrawal_schedule(expenses, [], [2026, 2027], apply_drawdown_tax=False)
        self.assertEqual(schedule["needs"], [100_000.0, 100_000.0])

    def test_retirement_year_zeroes_needs_and_taxes_before_it(self):
        expenses = [{"name": "Baseline", "annual_amount": 100_000, "start_year": None, "end_year": None}]
        schedule = yearly_withdrawal_schedule(
            expenses, [], [2026, 2027, 2028], apply_drawdown_tax=True, retirement_year=2028,
        )
        self.assertEqual(schedule["needs"], [0.0, 0.0, 100_000.0])
        self.assertEqual(schedule["taxes"][0], 0.0)
        self.assertEqual(schedule["taxes"][1], 0.0)
        self.assertGreater(schedule["taxes"][2], 0.0)
        self.assertEqual(schedule["totals"][0], 0.0)


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


class TestResolveRetirementYear(unittest.TestCase):
    """_resolve_retirement_year -- same blank/garbage-is-None parsing
    convention as _resolve_birth_year above, for the "Retirement year"
    assumption that gates annual_net_withdrawal_need."""

    def test_blank_or_missing_is_none(self):
        self.assertIsNone(_resolve_retirement_year({"retirement_year": ""}))
        self.assertIsNone(_resolve_retirement_year({}))

    def test_parses_string(self):
        self.assertEqual(_resolve_retirement_year({"retirement_year": "2035"}), 2035)

    def test_garbage_is_none(self):
        self.assertIsNone(_resolve_retirement_year({"retirement_year": "not-a-year"}))


class TestResolveEarlyTaxDeferredAge(unittest.TestCase):
    """_resolve_early_tax_deferred_age -- same blank/garbage-is-None
    parsing convention as _resolve_birth_year/_resolve_retirement_year
    above, for the "Start drawing Tax-deferred at age" assumption on the
    Drawdown Planning tab."""

    def test_blank_or_missing_is_none(self):
        self.assertIsNone(_resolve_early_tax_deferred_age({"early_tax_deferred_age": ""}))
        self.assertIsNone(_resolve_early_tax_deferred_age({}))

    def test_parses_string(self):
        self.assertEqual(_resolve_early_tax_deferred_age({"early_tax_deferred_age": "60"}), 60)

    def test_garbage_is_none(self):
        self.assertIsNone(_resolve_early_tax_deferred_age({"early_tax_deferred_age": "not-an-age"}))


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


class TestPoolYearTaxWithBaseIncome(unittest.TestCase):
    def test_base_income_makes_the_same_withdrawal_cost_more_tax(self):
        alone = _pool_year_tax(ordinary_income=100_000, gains_income=0, year=2026, inflation_rate=0.0)
        stacked = _pool_year_tax(
            ordinary_income=100_000, gains_income=0, year=2026, inflation_rate=0.0, base_ordinary_income=150_000,
        )
        self.assertGreater(stacked, alone)

    def test_stacked_tax_is_the_incremental_tax_on_top_of_the_base(self):
        base, extra = 150_000, 100_000
        expected = (
            _pool_year_tax(ordinary_income=base + extra, gains_income=0, year=2026, inflation_rate=0.0)
            - _pool_year_tax(ordinary_income=base, gains_income=0, year=2026, inflation_rate=0.0)
        )
        got = _pool_year_tax(
            ordinary_income=extra, gains_income=0, year=2026, inflation_rate=0.0, base_ordinary_income=base,
        )
        self.assertAlmostEqual(got, expected)

    def test_zero_base_is_exactly_the_original_behavior(self):
        self.assertEqual(
            _pool_year_tax(ordinary_income=80_000, gains_income=20_000, year=2030, inflation_rate=0.03),
            _pool_year_tax(ordinary_income=80_000, gains_income=20_000, year=2030, inflation_rate=0.03, base_ordinary_income=0.0),
        )

    def test_gains_stack_above_base_income_in_the_federal_ltcg_brackets(self):
        # Base income already fills the 0% LTCG bracket, so the gains pay 15%.
        no_base = _pool_year_tax(ordinary_income=0, gains_income=50_000, year=2026, inflation_rate=0.0)
        with_base = _pool_year_tax(
            ordinary_income=0, gains_income=50_000, year=2026, inflation_rate=0.0, base_ordinary_income=200_000,
        )
        self.assertGreater(with_base, no_base)


class TestAnnualTaxableIncome(unittest.TestCase):
    def test_rental_counts_in_full_and_social_security_at_85_percent(self):
        from source.reporting.monte_carlo import annual_taxable_income
        income = [
            {"category": "Rental", "annual_amount": 40_000, "start_year": None, "end_year": None},
            {"category": "Social Security", "annual_amount": 30_000, "start_year": None, "end_year": None},
        ]
        self.assertAlmostEqual(annual_taxable_income(income, 2030), 40_000 + 30_000 * 0.85)

    def test_honors_each_rows_year_range_and_inflation(self):
        from source.reporting.monte_carlo import annual_taxable_income
        income = [
            {"category": "Rental", "annual_amount": 10_000, "start_year": 2030, "end_year": 2031,
             "base_year": 2026, "inflates": 1},
        ]
        self.assertEqual(annual_taxable_income(income, 2029, 0.03), 0.0)
        self.assertAlmostEqual(annual_taxable_income(income, 2030, 0.03), 10_000 * 1.03 ** 4)
        self.assertEqual(annual_taxable_income(income, 2032, 0.03), 0.0)

    def test_total_income_need_is_unchanged_by_the_taxability_split(self):
        from source.reporting.monte_carlo import annual_income_need
        income = [{"category": "Social Security", "annual_amount": 30_000, "start_year": None, "end_year": None}]
        self.assertEqual(annual_income_need(income, 2030), 30_000)


class TestRentalTaxableFraction(unittest.TestCase):
    def test_blank_or_garbage_schedule_means_fully_taxable(self):
        from source.reporting.monte_carlo.assumptions import _resolve_rental_taxable_fraction as f
        self.assertEqual(f({}, 2030), 1.0)
        self.assertEqual(f({"rental_taxable_schedule": ""}, 2030), 1.0)
        self.assertEqual(f({"rental_taxable_schedule": "not json"}, 2030), 1.0)

    def test_rent_is_taxable_only_after_the_loan_end_year(self):
        from source.reporting.monte_carlo.assumptions import _resolve_rental_taxable_fraction as f
        a = {"rental_taxable_schedule": "[[2051, 60000.0]]"}
        self.assertEqual(f(a, 2051), 0.0)
        self.assertEqual(f(a, 2052), 1.0)

    def test_several_properties_are_weighted_by_their_income(self):
        from source.reporting.monte_carlo.assumptions import _resolve_rental_taxable_fraction as f
        a = {"rental_taxable_schedule": "[[2040, 30000], [2051, 10000], [null, 10000]]"}
        self.assertAlmostEqual(f(a, 2035), 10_000 / 50_000)   # only the no-loan property
        self.assertAlmostEqual(f(a, 2041), 40_000 / 50_000)
        self.assertAlmostEqual(f(a, 2052), 1.0)

    def test_annual_taxable_income_scales_only_rental_rows(self):
        from source.reporting.monte_carlo import annual_taxable_income
        income = [
            {"category": "Rental", "annual_amount": 40_000},
            {"category": "Social Security", "annual_amount": 30_000},
            {"category": "Pension", "annual_amount": 10_000},
        ]
        self.assertAlmostEqual(annual_taxable_income(income, 2030, 0.0, 0.0), 30_000 * 0.85 + 10_000)
        self.assertAlmostEqual(annual_taxable_income(income, 2030, 0.0, 0.5), 20_000 + 30_000 * 0.85 + 10_000)

    def test_drawdown_schedule_taxes_less_while_the_loan_runs(self):
        pools = {"tax_deferred": 3_000_000, "roth": 0, "taxable": 0, "real_estate": 0}
        income = [{"name": "Rental income", "category": "Rental", "annual_amount": 80_000}]
        expenses = [{"name": "Living", "annual_amount": 200_000}]
        base = {"expected_return": "0.0", "plan_horizon_years": "2", "current_year": "2050",
                "annual_income_offset": "0", "apply_drawdown_tax": "1", "inflation_rate": "0"}
        taxed = deterministic_drawdown_schedule(pools=dict(pools), expenses=expenses, income=income, assumptions=base)
        sheltered = deterministic_drawdown_schedule(
            pools=dict(pools), expenses=expenses, income=income,
            assumptions={**base, "rental_taxable_schedule": "[[2051, 80000]]"},
        )
        self.assertLess(sheltered["rows"][0]["tax"], taxed["rows"][0]["tax"])   # 2050: rent sheltered
        self.assertLess(sheltered["rows"][1]["tax"], taxed["rows"][1]["tax"])  # 2051: still sheltered
        # Same year-by-year need either way -- only the tax changes.
        self.assertEqual(sheltered["rows"][0]["need"], taxed["rows"][0]["need"])


class TestAnnualIncomeBreakdown(unittest.TestCase):
    def test_splits_rental_social_security_and_other(self):
        from source.reporting.monte_carlo import annual_income_breakdown, annual_income_need
        income = [
            {"name": "Rental income", "category": "Rental", "annual_amount": 40_000},
            {"name": "Social Security", "category": "", "annual_amount": 30_000, "start_year": 2030},
            {"name": "Pension", "category": "Pension", "annual_amount": 5_000},
        ]
        before = annual_income_breakdown(income, 2029)
        self.assertEqual(before, {"rental": 40_000, "social_security": 0.0, "other": 5_000})
        after = annual_income_breakdown(income, 2030)
        self.assertEqual(after, {"rental": 40_000, "social_security": 30_000, "other": 5_000})
        self.assertEqual(sum(after.values()), annual_income_need(income, 2030))


class TestBaseIncomeInTheEngine(unittest.TestCase):
    def _pools(self):
        return {"tax_deferred": 2_000_000, "roth": 0, "taxable": 0, "real_estate": 0}

    def test_the_same_withdrawal_owes_more_tax_when_rent_is_also_coming_in(self):
        kwargs = dict(
            need=100_000, age=60, birth_year=1966, gains_fraction=0.5, year=2030, inflation_rate=0.0,
            apply_drawdown_tax=True,
        )
        alone = _apply_year_withdrawal(self._pools(), **kwargs)
        with_rent = _apply_year_withdrawal(self._pools(), base_ordinary_income=150_000, **kwargs)
        self.assertGreater(with_rent["tax"], alone["tax"])

    def test_drawdown_schedule_taxes_withdrawals_on_top_of_income(self):
        pools = {"tax_deferred": 3_000_000, "roth": 0, "taxable": 0, "real_estate": 0}
        expenses = [{"name": "Living", "category": "Fixed", "annual_amount": 200_000, "start_year": None, "end_year": None}]
        assumptions = {"expected_return": "0.0", "plan_horizon_years": "1", "current_year": "2030",
                       "annual_income_offset": "0", "apply_drawdown_tax": "1", "birth_year": "1970"}
        no_income = deterministic_drawdown_schedule(pools=pools, expenses=expenses, assumptions=assumptions)
        rent = [{"category": "Rental", "annual_amount": 120_000, "start_year": None, "end_year": None}]
        with_income = deterministic_drawdown_schedule(pools=pools, expenses=expenses, income=rent, assumptions=assumptions)
        # With rent the withdrawal is smaller (need 80K vs 200K) yet taxed in higher brackets: the
        # per-dollar tax rate on the withdrawal rises.
        rate_alone = no_income["rows"][0]["tax"] / no_income["rows"][0]["need"]
        rate_stacked = with_income["rows"][0]["tax"] / with_income["rows"][0]["need"]
        self.assertGreater(rate_stacked, rate_alone)


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

    def test_withdrawn_breaks_down_the_extra_draw_by_pool(self):
        pools = self._pools(tax_deferred=500_000, taxable=10_000)
        result = _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertAlmostEqual(result["withdrawn"]["taxable"], 10_000)
        self.assertAlmostEqual(result["withdrawn"]["tax_deferred"], 40_000)
        self.assertEqual(result["withdrawn"]["roth"], 0.0)
        self.assertEqual(result["withdrawn"]["real_estate"], 0.0)

    def test_order_override_changes_which_pool_is_drawn_first(self):
        pools = self._pools(tax_deferred=500_000, taxable=500_000)
        _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
            order=("tax_deferred", "taxable", "roth", "real_estate"),
        )
        self.assertEqual(pools["tax_deferred"], 450_000)
        self.assertEqual(pools["taxable"], 500_000)  # untouched -- tax_deferred covered it first

    def test_order_none_falls_back_to_the_default_order(self):
        pools = self._pools(tax_deferred=500_000, taxable=500_000)
        _apply_year_withdrawal(
            pools, need=50_000, age=None, birth_year=None, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False, order=None,
        )
        self.assertEqual(pools["taxable"], 450_000)  # default order -- taxable first
        self.assertEqual(pools["tax_deferred"], 500_000)

    def test_withdrawn_tax_deferred_excludes_the_rmd_itself(self):
        # The RMD is reported separately as result["rmd"] -- withdrawn["tax_deferred"]
        # is only the ADDITIONAL amount drawn beyond it, so a caller that
        # wants the whole pool movement has to add the two together itself
        # (see deterministic_drawdown_schedule's own "drawn_tax_deferred").
        pools = self._pools(tax_deferred=1_000_000)
        result = _apply_year_withdrawal(
            pools, need=0, age=75, birth_year=1950, gains_fraction=0.4,
            year=2026, inflation_rate=0.0, apply_drawdown_tax=False,
        )
        self.assertGreater(result["rmd"], 0.0)
        self.assertEqual(result["withdrawn"]["tax_deferred"], 0.0)


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


class TestRetirementYearGatesRunSimulation(unittest.TestCase):
    """The "Retirement year" assumption plugged into run_simulation --
    both the single-balance (legacy) mode and the three-pool mode --
    zeroing out every simulated year's withdrawal before it."""

    def _assumptions(self, **overrides):
        base = {
            "expected_return": "0.0", "return_volatility": "0.0", "iterations": "5",
            "plan_horizon_years": "5", "current_year": "2026", "annual_income_offset": "0",
            "apply_drawdown_tax": "0",
        }
        base.update(overrides)
        return base

    def test_single_balance_mode_withdraws_nothing_before_retirement_year(self):
        expenses = [{"name": "Baseline", "annual_amount": 100_000, "start_year": None, "end_year": None}]
        assumptions = self._assumptions(retirement_year="2029")
        result = run_simulation(
            starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, rng=random.Random(1),
        )
        # 0% return, 0% volatility -- every path is identical. Years
        # 2026-2028 (before 2029) withdraw nothing; 2029 finally withdraws
        # 100,000.
        band = result["band"]
        self.assertEqual([row["median"] for row in band[:3]], [1_000_000.0, 1_000_000.0, 1_000_000.0])
        self.assertEqual(band[3]["median"], 900_000.0)

    def test_single_balance_mode_with_no_retirement_year_withdraws_from_year_one(self):
        expenses = [{"name": "Baseline", "annual_amount": 100_000, "start_year": None, "end_year": None}]
        assumptions = self._assumptions()
        result = run_simulation(
            starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, rng=random.Random(1),
        )
        self.assertEqual(result["band"][0]["median"], 900_000.0)

    def test_pools_mode_withdraws_nothing_before_retirement_year(self):
        expenses = [{"name": "Baseline", "annual_amount": 100_000, "start_year": None, "end_year": None}]
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 1_000_000, "real_estate": 0}
        assumptions = self._assumptions(retirement_year="2029")
        result = run_simulation(
            starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, rng=random.Random(1), pools=pools,
        )
        band = result["band"]
        self.assertEqual([row["median"] for row in band[:3]], [1_000_000.0, 1_000_000.0, 1_000_000.0])
        self.assertEqual(band[3]["median"], 900_000.0)

    def test_pools_mode_rmd_still_fires_before_retirement_year(self):
        # A giant tax-deferred balance well past RMD age, retirement year
        # still a few years off -- the IRS doesn't care whether you've
        # retired, so the RMD (and its tax, if a birth year forces one)
        # should still force money out before retirement_year even though
        # the plan's own spending need is gated to 0 until then.
        pools = {"tax_deferred": 2_000_000, "roth": 0, "taxable": 0, "real_estate": 0}
        assumptions = self._assumptions(retirement_year="2029", birth_year="1940", apply_drawdown_tax="1")
        result = run_simulation(
            starting_balance=2_000_000, expenses=[], assumptions=assumptions, rng=random.Random(1), pools=pools,
        )
        self.assertLess(result["band"][0]["median"], 2_000_000.0)
        self.assertGreater(result["first_year_tax"], 0.0)


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

    def test_returns_expected_return_first_then_the_crashes_then_the_sp500_average(self):
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[],
            assumptions={"plan_horizon_years": 5, "current_year": 2028},
        )
        labels = [sc["label"] for sc in result["scenarios"]]
        self.assertTrue(labels[0].startswith("Expected return ("))
        self.assertEqual(labels[1:1 + len(HISTORICAL_STRESS_SCENARIOS)], [label for label, _ in HISTORICAL_STRESS_SCENARIOS])
        self.assertEqual(len(labels), len(HISTORICAL_STRESS_SCENARIOS) + 2)
        self.assertTrue(labels[-1].startswith("S&P 500 last 5 years average ("))
        self.assertFalse(any(label.startswith("No-crash") for label in labels))

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

    def test_expected_return_scenario_is_the_plans_assumption_every_year(self):
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[],
            assumptions={"plan_horizon_years": 8, "current_year": 2028, "expected_return": 0.07},
        )
        sc = next(sc for sc in result["scenarios"] if sc["label"].startswith("Expected return"))
        self.assertEqual(sc["label"], "Expected return (7.0%/yr)")
        self.assertTrue(all(p["return"] == 0.07 for p in sc["path"]))

    def test_expected_return_scenario_defaults_to_six_percent(self):
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[], assumptions={"plan_horizon_years": 3, "current_year": 2028},
        )
        sc = next(sc for sc in result["scenarios"] if sc["label"].startswith("Expected return"))
        self.assertTrue(all(p["return"] == 0.06 for p in sc["path"]))

    def test_sp500_average_scenario_is_the_compound_average_of_the_last_horizon_years(self):
        from source.reporting.monte_carlo import _SP500_ANNUAL_RETURNS, sp500_average_return, sp500_lookback

        # All years on record when no count is given.
        avg_all = sp500_average_return()
        growth = 1.0
        for r in _SP500_ANNUAL_RETURNS.values():
            growth *= 1 + r
        self.assertAlmostEqual((1 + avg_all) ** len(_SP500_ANNUAL_RETURNS), growth, places=6)
        # The most recent N years when asked.
        last = sorted(_SP500_ANNUAL_RETURNS)[-4:]
        g4 = 1.0
        for y in last:
            g4 *= 1 + _SP500_ANNUAL_RETURNS[y]
        avg4 = sp500_average_return(4)
        self.assertAlmostEqual((1 + avg4) ** 4, g4, places=9)
        # The stress test uses the plan horizon as N.
        look = sp500_lookback({"plan_horizon_years": 4})
        self.assertEqual((look["years"], look["first_year"], look["last_year"]), (4, last[0], last[-1]))
        self.assertAlmostEqual(look["rate"], avg4)
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[], assumptions={"plan_horizon_years": 4, "current_year": 2028},
        )
        sc = next(sc for sc in result["scenarios"] if sc["label"].startswith("S&P 500 last 4 years average"))
        self.assertTrue(all(p["return"] == avg4 for p in sc["path"]))
        self.assertEqual(result["sp500_lookback"]["years"], 4)

    def test_lookback_is_capped_at_the_years_on_record_and_defaults_to_40(self):
        from source.reporting.monte_carlo import _SP500_ANNUAL_RETURNS, sp500_lookback

        self.assertEqual(sp500_lookback({"plan_horizon_years": 500})["years"], len(_SP500_ANNUAL_RETURNS))
        self.assertEqual(sp500_lookback({})["years"], 40)

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

    def test_no_expenses_and_the_flat_reference_lines_never_deplete(self):
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=[],
            assumptions={"plan_horizon_years": 10, "current_year": 2028},
        )
        for prefix in ("Expected return", "S&P 500 last"):
            baseline = next(sc for sc in result["scenarios"] if sc["label"].startswith(prefix))
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


class TestRetirementYearGatesHistoricalStressTest(unittest.TestCase):
    """Same "Retirement year" gating as run_simulation, plugged into
    run_historical_stress_test -- legacy (pools=None) mode's shared
    yearly_needs list and pools mode's per-scenario yearly_needs both
    zero out before the retirement year."""

    def test_legacy_mode_yearly_needs_are_zero_before_retirement_year(self):
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        assumptions = {"plan_horizon_years": 4, "current_year": 2026, "retirement_year": "2029"}
        result = run_historical_stress_test(starting_balance=1_000_000, expenses=expenses, assumptions=assumptions)
        self.assertEqual(result["yearly_needs"], [0.0, 0.0, 0.0, 40_000.0])
        # yearly_total_expense is un-netted (the raw Expense-tab total)
        # and must NOT be gated -- only the withdrawal need itself is.
        self.assertEqual(result["yearly_total_expense"], [40_000.0, 40_000.0, 40_000.0, 40_000.0])

    def test_pools_mode_yearly_needs_are_zero_before_retirement_year(self):
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 1_000_000}
        assumptions = {
            "plan_horizon_years": 4, "current_year": 2026, "retirement_year": "2029", "apply_drawdown_tax": "0",
        }
        result = run_historical_stress_test(
            starting_balance=1_000_000, expenses=expenses, assumptions=assumptions, pools=pools,
        )
        self.assertEqual(result["yearly_needs"], [0.0, 0.0, 0.0, 40_000.0])
        for sc in result["scenarios"]:
            # Balance shouldn't move (beyond that year's own return) in
            # the three gated years -- only the last year draws anything.
            self.assertEqual(sc["yearly_total_withdrawal"][0], 0.0)
            self.assertEqual(sc["yearly_total_withdrawal"][1], 0.0)
            self.assertEqual(sc["yearly_total_withdrawal"][2], 0.0)
            self.assertGreater(sc["yearly_total_withdrawal"][3], 0.0)


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

    def test_draws_dashed_90th_and_10th_percentile_lines_with_labels(self):
        result = {"band": [
            {"year": 2027, "p10": 100, "median": 200, "p90": 300},
            {"year": 2028, "p10": 90, "median": 210, "p90": 320},
        ]}
        svg = render_fan_svg(result)
        # median + p90 + p10 lines; the two percentile lines are dashed
        self.assertEqual(svg.count("<polyline"), 3)
        self.assertEqual(svg.count('stroke-dasharray="5 3"'), 2)
        for label in ("90th pct", "Median", "10th pct"):
            self.assertIn(label, svg)

    def test_end_labels_do_not_overlap_when_the_lines_end_together(self):
        result = {"band": [{"year": 2027, "p10": 100, "median": 100, "p90": 100}]}
        svg = render_fan_svg(result)
        ys = sorted(
            float(m) for m in re.findall(r'<text x="[\d.]+" y="([\d.]+)" font-size="10" font-weight', svg)
        )
        self.assertEqual(len(ys), 3)
        self.assertGreaterEqual(ys[1] - ys[0], 12.0 - 1e-6)
        self.assertGreaterEqual(ys[2] - ys[1], 12.0 - 1e-6)

    def test_defaults_to_the_shared_band_color(self):
        result = {"band": [{"year": 2027, "p10": 100, "median": 200, "p90": 300}]}
        svg = render_fan_svg(result)
        self.assertIn("#0071e3", svg)

    def test_custom_color_overrides_the_default_everywhere_it_appears(self):
        # The S&P 500 historical-bootstrap chart reuses this same
        # renderer with a distinct (fixed-order categorical) color so it
        # reads as a visually separate series from the Gaussian chart.
        result = {"band": [{"year": 2027, "p10": 100, "median": 200, "p90": 300}]}
        svg = render_fan_svg(result, color="#eb6834")
        self.assertIn("#eb6834", svg)
        self.assertNotIn("#0071e3", svg)


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
            for key in (
                "year", "age", "need", "expenses", "income_rental", "income_social_security", "income_other",
                "rmd", "tax", "shortfall",
                "drawn_taxable", "drawn_tax_deferred", "drawn_roth", "drawn_real_estate",
                "taxable", "tax_deferred", "roth", "real_estate", "total",
            ):
                self.assertIn(key, row)

    def test_drawn_taxable_reflects_what_actually_came_out_for_spending(self):
        pools = {"tax_deferred": 500_000, "roth": 200_000, "taxable": 300_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        result = deterministic_drawdown_schedule(pools=pools, expenses=expenses, assumptions=self._assumptions())
        first = result["rows"][0]
        self.assertAlmostEqual(first["drawn_taxable"], 50_000.0)
        self.assertEqual(first["drawn_tax_deferred"], 0.0)
        self.assertEqual(first["drawn_roth"], 0.0)
        self.assertEqual(first["drawn_real_estate"], 0.0)

    def test_drawn_tax_deferred_includes_the_rmd(self):
        pools = {"tax_deferred": 1_000_000, "roth": 0, "taxable": 0, "real_estate": 0}
        result = deterministic_drawdown_schedule(
            pools=pools, expenses=[], assumptions=self._assumptions(birth_year="1950"),
        )
        first = result["rows"][0]
        self.assertAlmostEqual(first["drawn_tax_deferred"], first["rmd"])
        self.assertGreater(first["drawn_tax_deferred"], 0.0)

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

    def test_retirement_year_is_reported_back(self):
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 0, "real_estate": 0}
        result = deterministic_drawdown_schedule(pools=pools, expenses=[], assumptions=self._assumptions(retirement_year="2029"))
        self.assertEqual(result["retirement_year"], 2029)

    def test_retirement_year_unset_reports_none(self):
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 0, "real_estate": 0}
        result = deterministic_drawdown_schedule(pools=pools, expenses=[], assumptions=self._assumptions())
        self.assertIsNone(result["retirement_year"])

    def test_no_withdrawal_before_the_retirement_year(self):
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 300_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        result = deterministic_drawdown_schedule(
            pools=pools, expenses=expenses, assumptions=self._assumptions(plan_horizon_years="4", retirement_year="2029"),
        )
        rows = result["rows"]
        # current_year=2027 -> years are 2027, 2028, 2029, 2030.
        self.assertEqual([r["need"] for r in rows], [0.0, 0.0, 50_000.0, 50_000.0])
        self.assertEqual(rows[0]["taxable"], 300_000.0)  # untouched -- 0% return, gated need
        self.assertEqual(rows[1]["taxable"], 300_000.0)
        self.assertEqual(rows[2]["taxable"], 250_000.0)

    def test_early_tax_deferred_age_is_reported_back(self):
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 0, "real_estate": 0}
        result = deterministic_drawdown_schedule(pools=pools, expenses=[], assumptions=self._assumptions(early_tax_deferred_age="60"))
        self.assertEqual(result["early_tax_deferred_age"], 60)

    def test_early_tax_deferred_age_unset_reports_none(self):
        pools = {"tax_deferred": 0, "roth": 0, "taxable": 0, "real_estate": 0}
        result = deterministic_drawdown_schedule(pools=pools, expenses=[], assumptions=self._assumptions())
        self.assertIsNone(result["early_tax_deferred_age"])

    def test_early_tax_deferred_age_draws_tax_deferred_before_taxable_once_reached(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 500_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        result = deterministic_drawdown_schedule(
            pools=pools, expenses=expenses, assumptions=self._assumptions(birth_year="1967", early_tax_deferred_age="60"),
        )
        # current_year=2027, birth_year=1967 -> age 60 in the very first row.
        first = result["rows"][0]
        self.assertEqual(first["age"], 60)
        self.assertAlmostEqual(first["drawn_tax_deferred"], 50_000.0)
        self.assertEqual(first["drawn_taxable"], 0.0)

    def test_early_tax_deferred_age_left_unset_keeps_the_default_taxable_first_order(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 500_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        result = deterministic_drawdown_schedule(
            pools=pools, expenses=expenses, assumptions=self._assumptions(birth_year="1967"),
        )
        first = result["rows"][0]
        self.assertAlmostEqual(first["drawn_taxable"], 50_000.0)
        self.assertEqual(first["drawn_tax_deferred"], 0.0)

    def test_early_tax_deferred_age_has_no_effect_before_the_threshold_is_reached(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 500_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        result = deterministic_drawdown_schedule(
            pools=pools, expenses=expenses, assumptions=self._assumptions(birth_year="1990", early_tax_deferred_age="60"),
        )
        # birth_year=1990, current_year=2027 -> age 37, nowhere near 60.
        first = result["rows"][0]
        self.assertAlmostEqual(first["drawn_taxable"], 50_000.0)
        self.assertEqual(first["drawn_tax_deferred"], 0.0)


class TestCombinedMarginalRate(unittest.TestCase):
    def test_zero_income_is_the_bottom_bracket_of_each_table(self):
        rate = _combined_marginal_rate(0.0, 2026, 0.0)
        self.assertAlmostEqual(rate, 0.10 + 0.01)

    def test_high_income_is_the_top_bracket_of_each_table(self):
        rate = _combined_marginal_rate(5_000_000.0, 2026, 0.0)
        self.assertAlmostEqual(rate, 0.37 + 0.133)

    def test_a_mid_bracket_income_lands_between_the_extremes(self):
        rate = _combined_marginal_rate(150_000.0, 2026, 0.0)
        self.assertGreater(rate, 0.10 + 0.01)
        self.assertLess(rate, 0.37 + 0.133)


class TestFederalBracketCeiling(unittest.TestCase):
    def test_matches_the_published_2026_bracket_table(self):
        self.assertAlmostEqual(_federal_bracket_ceiling(0.12, 2026, 0.0), 100_800.0)
        self.assertAlmostEqual(_federal_bracket_ceiling(0.22, 2026, 0.0), 211_400.0)

    def test_grows_with_inflation_in_a_later_year(self):
        ceiling_2026 = _federal_bracket_ceiling(0.12, 2026, 0.03)
        ceiling_2030 = _federal_bracket_ceiling(0.12, 2030, 0.03)
        self.assertGreater(ceiling_2030, ceiling_2026)

    def test_unmatched_rate_is_unbounded(self):
        self.assertEqual(_federal_bracket_ceiling(0.99, 2026, 0.0), float("inf"))


class TestCapConversionByAffordability(unittest.TestCase):
    def test_returns_full_candidate_when_taxable_easily_covers_the_tax(self):
        amount = _cap_conversion_by_affordability(10_000.0, 0.0, 1_000_000.0, 2026, 0.0)
        self.assertAlmostEqual(amount, 10_000.0)

    def test_zero_taxable_means_no_conversion_at_all(self):
        amount = _cap_conversion_by_affordability(50_000.0, 0.0, 0.0, 2026, 0.0)
        self.assertEqual(amount, 0.0)

    def test_shrinks_the_conversion_to_what_taxable_can_afford(self):
        amount = _cap_conversion_by_affordability(500_000.0, 0.0, 20_000.0, 2026, 0.0)
        self.assertLess(amount, 500_000.0)
        self.assertGreater(amount, 0.0)
        tax_on_it = _pool_year_tax(ordinary_income=amount, gains_income=0.0, year=2026, inflation_rate=0.0)
        self.assertLessEqual(tax_on_it, 20_000.0 + 1.0)  # within bisection tolerance

    def test_zero_or_negative_candidate_is_always_zero(self):
        self.assertEqual(_cap_conversion_by_affordability(0.0, 0.0, 100_000.0, 2026, 0.0), 0.0)
        self.assertEqual(_cap_conversion_by_affordability(-5.0, 0.0, 100_000.0, 2026, 0.0), 0.0)


class TestEstimateDefaultHeirBaseIncome(unittest.TestCase):
    def test_uses_the_current_years_net_withdrawal_need(self):
        expenses = [{"name": "Baseline", "annual_amount": 80_000, "start_year": None, "end_year": None}]
        income = [{"name": "SS", "annual_amount": 20_000, "start_year": None, "end_year": None}]
        assumptions = {"current_year": "2027", "inflation_rate": "0.0", "annual_income_offset": "0"}
        self.assertAlmostEqual(estimate_default_heir_base_income(assumptions, expenses, income), 60_000.0)

    def test_floors_at_zero_rather_than_going_negative(self):
        expenses = []
        income = [{"name": "Pension", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        assumptions = {"current_year": "2027", "inflation_rate": "0.0", "annual_income_offset": "0"}
        self.assertEqual(estimate_default_heir_base_income(assumptions, expenses, income), 0.0)

    def test_zero_before_retirement_year_matches_the_gating_rule(self):
        expenses = [{"name": "Baseline", "annual_amount": 80_000, "start_year": None, "end_year": None}]
        assumptions = {"current_year": "2027", "inflation_rate": "0.0", "annual_income_offset": "0", "retirement_year": "2030"}
        self.assertEqual(estimate_default_heir_base_income(assumptions, expenses, []), 0.0)


class TestEstimateHeirTaxOnTaxDeferred(unittest.TestCase):
    """estimate_heir_tax_on_tax_deferred -- unified math for both heir
    types now (see the function's own docstring): the balance is spread
    across `spread_years` even annual distributions regardless of
    heir_type. heir_type itself no longer changes the calculation
    directly -- see _resolve_heir_spread_years for how it drives the
    default spread_years a caller passes in instead."""

    def test_zero_balance_owes_no_tax(self):
        tax = estimate_heir_tax_on_tax_deferred(
            remaining_balance=0.0, heir_type="non_spouse", heir_base_income=0.0, year=2026, inflation_rate=0.0,
            spread_years=10,
        )
        self.assertEqual(tax, 0.0)

    def test_zero_spread_years_owes_no_tax(self):
        tax = estimate_heir_tax_on_tax_deferred(
            remaining_balance=1_000_000.0, heir_type="non_spouse", heir_base_income=0.0, year=2026, inflation_rate=0.0,
            spread_years=0,
        )
        self.assertEqual(tax, 0.0)

    def test_owes_some_tax_on_a_real_balance(self):
        tax = estimate_heir_tax_on_tax_deferred(
            remaining_balance=1_000_000.0, heir_type="non_spouse", heir_base_income=0.0, year=2026, inflation_rate=0.0,
            spread_years=10,
        )
        self.assertGreater(tax, 0.0)
        self.assertLess(tax, 1_000_000.0)

    def test_a_larger_balance_means_a_larger_tax_bill(self):
        small = estimate_heir_tax_on_tax_deferred(
            remaining_balance=200_000.0, heir_type="non_spouse", heir_base_income=0.0, year=2026, inflation_rate=0.0,
            spread_years=10,
        )
        large = estimate_heir_tax_on_tax_deferred(
            remaining_balance=2_000_000.0, heir_type="non_spouse", heir_base_income=0.0, year=2026, inflation_rate=0.0,
            spread_years=10,
        )
        self.assertGreater(large, small)

    def test_ten_year_spread_beats_dumping_it_all_in_one_year(self):
        # Splitting into 10 separate tax years should owe strictly less
        # than taxing the whole balance as one lump year at the same
        # base income, since progressive brackets reset each tax year.
        balance = 2_000_000.0
        spread_tax = estimate_heir_tax_on_tax_deferred(
            remaining_balance=balance, heir_type="non_spouse", heir_base_income=0.0, year=2026, inflation_rate=0.0,
            spread_years=10,
        )
        lump_tax = _pool_year_tax(ordinary_income=balance, gains_income=0.0, year=2026, inflation_rate=0.0)
        self.assertLess(spread_tax, lump_tax)

    def test_a_longer_spread_owes_strictly_less_tax_for_the_same_balance(self):
        balance = 2_000_000.0
        ten_year = estimate_heir_tax_on_tax_deferred(
            remaining_balance=balance, heir_type="non_spouse", heir_base_income=0.0, year=2026, inflation_rate=0.0,
            spread_years=10,
        )
        twenty_year = estimate_heir_tax_on_tax_deferred(
            remaining_balance=balance, heir_type="non_spouse", heir_base_income=0.0, year=2026, inflation_rate=0.0,
            spread_years=20,
        )
        self.assertLess(twenty_year, ten_year)

    def test_heir_type_no_longer_changes_the_math_once_spread_years_matches(self):
        spouse_tax = estimate_heir_tax_on_tax_deferred(
            remaining_balance=2_000_000.0, heir_type="spouse", heir_base_income=50_000.0, year=2026, inflation_rate=0.0,
            spread_years=10,
        )
        non_spouse_tax = estimate_heir_tax_on_tax_deferred(
            remaining_balance=2_000_000.0, heir_type="non_spouse", heir_base_income=50_000.0, year=2026, inflation_rate=0.0,
            spread_years=10,
        )
        self.assertAlmostEqual(spouse_tax, non_spouse_tax)

    def test_different_default_spread_years_give_different_answers_for_the_two_heir_types(self):
        # The observable difference between heir types now comes from
        # _resolve_heir_spread_years' own per-type default (10 vs. 20),
        # not from estimate_heir_tax_on_tax_deferred itself.
        spouse_tax = estimate_heir_tax_on_tax_deferred(
            remaining_balance=2_000_000.0, heir_type="spouse", heir_base_income=50_000.0, year=2026, inflation_rate=0.0,
            spread_years=_DEFAULT_HEIR_SPREAD_YEARS["spouse"],
        )
        non_spouse_tax = estimate_heir_tax_on_tax_deferred(
            remaining_balance=2_000_000.0, heir_type="non_spouse", heir_base_income=50_000.0, year=2026, inflation_rate=0.0,
            spread_years=_DEFAULT_HEIR_SPREAD_YEARS["non_spouse"],
        )
        self.assertNotAlmostEqual(spouse_tax, non_spouse_tax)


class TestResolveHeirSpreadYears(unittest.TestCase):
    def test_blank_falls_back_to_the_heir_type_default(self):
        self.assertEqual(_resolve_heir_spread_years({}, "non_spouse"), 10)
        self.assertEqual(_resolve_heir_spread_years({"heir_spread_years": ""}, "spouse"), 20)

    def test_explicit_value_is_honored(self):
        self.assertEqual(_resolve_heir_spread_years({"heir_spread_years": "15"}, "non_spouse"), 15)
        self.assertEqual(_resolve_heir_spread_years({"heir_spread_years": "5"}, "spouse"), 5)

    def test_garbage_falls_back_to_the_default(self):
        self.assertEqual(_resolve_heir_spread_years({"heir_spread_years": "not-a-number"}, "non_spouse"), 10)

    def test_zero_or_negative_falls_back_to_the_default(self):
        self.assertEqual(_resolve_heir_spread_years({"heir_spread_years": "0"}, "non_spouse"), 10)
        self.assertEqual(_resolve_heir_spread_years({"heir_spread_years": "-5"}, "spouse"), 20)


class TestRunConversionSchedule(unittest.TestCase):
    def _assumptions(self, **overrides):
        base = {
            "expected_return": "0.0", "plan_horizon_years": "3", "current_year": "2027",
            "annual_income_offset": "0", "apply_drawdown_tax": "1",
        }
        base.update(overrides)
        return base

    def test_no_conversions_matches_deterministic_drawdown_schedule_exactly(self):
        pools = {"tax_deferred": 500_000, "roth": 100_000, "taxable": 300_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 60_000, "start_year": None, "end_year": None}]
        assumptions = self._assumptions(birth_year="1950")
        baseline = deterministic_drawdown_schedule(pools=pools, expenses=expenses, assumptions=assumptions)
        schedule = _run_conversion_schedule(
            pools=pools, expenses=expenses, income=[], assumptions=assumptions, target_rate=None,
        )
        for base_row, row in zip(baseline["rows"], schedule["rows"]):
            self.assertAlmostEqual(base_row["taxable"], row["taxable"])
            self.assertAlmostEqual(base_row["tax_deferred"], row["tax_deferred"])
            self.assertAlmostEqual(base_row["roth"], row["roth"])
            self.assertAlmostEqual(base_row["tax"], row["tax"])
            self.assertEqual(row["conversion"], 0.0)
            self.assertEqual(row["conversion_tax"], 0.0)
        self.assertFalse(schedule["depletes"])
        self.assertEqual(schedule["total_converted"], 0.0)

    def test_fill_bracket_strategy_actually_converts_something(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 500_000, "real_estate": 0}
        schedule = _run_conversion_schedule(
            pools=pools, expenses=[], income=[], assumptions=self._assumptions(), target_rate=0.12,
        )
        self.assertGreater(schedule["total_converted"], 0.0)
        self.assertGreater(schedule["ending_roth"], 0.0)
        self.assertLess(schedule["ending_tax_deferred"], 500_000 * 3)  # some got converted away, not just grown

    def test_no_taxable_pool_means_no_conversion_regardless_of_target_rate(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 0, "real_estate": 0}
        schedule = _run_conversion_schedule(
            pools=pools, expenses=[], income=[], assumptions=self._assumptions(), target_rate=0.12,
        )
        self.assertEqual(schedule["total_converted"], 0.0)

    def test_aggressive_strategy_converts_more_than_a_bracket_capped_one(self):
        pools = {"tax_deferred": 2_000_000, "roth": 0, "taxable": 2_000_000, "real_estate": 0}
        assumptions = self._assumptions(plan_horizon_years="1")
        mild = _run_conversion_schedule(pools=pools, expenses=[], income=[], assumptions=assumptions, target_rate=0.12)
        aggressive = _run_conversion_schedule(pools=pools, expenses=[], income=[], assumptions=assumptions, target_rate="aggressive")
        self.assertGreater(aggressive["total_converted"], mild["total_converted"])

    def test_conversion_tax_is_included_in_total_lifetime_tax(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 500_000, "real_estate": 0}
        assumptions = self._assumptions(apply_drawdown_tax="0")  # isolate: no ordinary drawdown tax, only conversion tax
        schedule = _run_conversion_schedule(pools=pools, expenses=[], income=[], assumptions=assumptions, target_rate=0.12)
        self.assertGreater(schedule["total_converted"], 0.0)
        self.assertGreater(schedule["total_lifetime_tax"], 0.0)

    def test_rmd_is_still_forced_even_under_an_aggressive_conversion_strategy(self):
        pools = {"tax_deferred": 1_000_000, "roth": 0, "taxable": 500_000, "real_estate": 0}
        schedule = _run_conversion_schedule(
            pools=pools, expenses=[], income=[], assumptions=self._assumptions(birth_year="1945"), target_rate="aggressive",
        )
        self.assertGreater(schedule["rows"][0]["rmd"], 0.0)

    def test_early_spend_from_age_draws_tax_deferred_before_taxable_once_reached(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 500_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        schedule = _run_conversion_schedule(
            pools=pools, expenses=expenses, income=[], assumptions=self._assumptions(birth_year="1967", apply_drawdown_tax="0"),
            target_rate=None, early_spend_from_age=60,
        )
        # current_year=2027, birth_year=1967 -> age 60 in 2027, the very first row.
        first = schedule["rows"][0]
        self.assertEqual(first["age"], 60)
        self.assertAlmostEqual(first["drawn_tax_deferred"], 50_000.0)
        self.assertEqual(first["drawn_taxable"], 0.0)

    def test_early_spend_from_age_has_no_effect_before_the_threshold(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 500_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None}]
        with_threshold = _run_conversion_schedule(
            pools=pools, expenses=expenses, income=[], assumptions=self._assumptions(birth_year="1990", apply_drawdown_tax="0"),
            target_rate=None, early_spend_from_age=60,
        )
        without_threshold = _run_conversion_schedule(
            pools=pools, expenses=expenses, income=[], assumptions=self._assumptions(birth_year="1990", apply_drawdown_tax="0"),
            target_rate=None, early_spend_from_age=None,
        )
        # birth_year=1990, current_year=2027 -> age 37, nowhere near 60, so both should match exactly.
        self.assertAlmostEqual(with_threshold["rows"][0]["taxable"], without_threshold["rows"][0]["taxable"])
        self.assertAlmostEqual(with_threshold["rows"][0]["tax_deferred"], without_threshold["rows"][0]["tax_deferred"])

    def test_early_spend_from_age_does_not_change_the_rmd_itself(self):
        # The RMD is always forced from tax_deferred regardless of
        # ordering -- early_spend_from_age only changes which pool
        # DISCRETIONARY spending draws from, never the mandatory RMD math.
        pools = {"tax_deferred": 1_000_000, "roth": 0, "taxable": 0, "real_estate": 0}
        with_early_spend = _run_conversion_schedule(
            pools=pools, expenses=[], income=[], assumptions=self._assumptions(birth_year="1950"),
            target_rate=None, early_spend_from_age=60,
        )
        without_early_spend = _run_conversion_schedule(
            pools=pools, expenses=[], income=[], assumptions=self._assumptions(birth_year="1950"),
            target_rate=None, early_spend_from_age=None,
        )
        self.assertAlmostEqual(with_early_spend["rows"][0]["rmd"], without_early_spend["rows"][0]["rmd"])

    def test_rows_carry_the_same_drawn_by_pool_breakdown_as_the_deterministic_schedule(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 500_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 40_000, "start_year": None, "end_year": None}]
        schedule = _run_conversion_schedule(
            pools=pools, expenses=expenses, income=[], assumptions=self._assumptions(apply_drawdown_tax="0"), target_rate=None,
        )
        first = schedule["rows"][0]
        for key in ("drawn_taxable", "drawn_tax_deferred", "drawn_roth", "drawn_real_estate"):
            self.assertIn(key, first)
        self.assertAlmostEqual(first["drawn_taxable"], 40_000.0)


class TestCompareRothConversionStrategies(unittest.TestCase):
    def _assumptions(self, **overrides):
        base = {
            "expected_return": "0.0", "plan_horizon_years": "3", "current_year": "2027",
            "annual_income_offset": "0", "apply_drawdown_tax": "1",
        }
        base.update(overrides)
        return base

    def test_returns_one_result_per_named_strategy(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 300_000, "real_estate": 0}
        result = compare_roth_conversion_strategies(pools=pools, expenses=[], assumptions=self._assumptions())
        expected_count = len(ROTH_CONVERSION_STRATEGIES) + len(EARLY_TAX_DEFERRED_SPENDING_STRATEGIES)
        self.assertEqual(len(result["strategies"]), expected_count)
        keys = {s["key"] for s in result["strategies"]}
        expected_keys = {key for key, _, _ in ROTH_CONVERSION_STRATEGIES} | {key for key, _, _ in EARLY_TAX_DEFERRED_SPENDING_STRATEGIES}
        self.assertEqual(keys, expected_keys)

    def test_baseline_follows_the_plans_own_early_tax_deferred_draw_age(self):
        pools = {"tax_deferred": 800_000, "roth": 0, "taxable": 800_000, "real_estate": 0}
        expenses = [{"name": "Living", "annual_amount": 60_000, "start_year": None, "end_year": None}]
        plain = compare_roth_conversion_strategies(
            pools=pools, expenses=expenses, assumptions=self._assumptions(birth_year="1966", plan_horizon_years="6"),
        )
        early = compare_roth_conversion_strategies(
            pools=pools, expenses=expenses,
            assumptions=self._assumptions(birth_year="1966", plan_horizon_years="6", early_tax_deferred_age="60"),
        )
        plain_base = next(s for s in plain["strategies"] if s["key"] == "no_conversions")
        early_base = next(s for s in early["strategies"] if s["key"] == "no_conversions")
        self.assertIsNone(plain["plan_early_tax_deferred_age"])
        self.assertEqual(early["plan_early_tax_deferred_age"], 60)
        self.assertIn("age 60", early_base["label"])
        self.assertNotIn("age", plain_base["label"])
        # The baseline is now the Tax-deferred-first plan, not the Taxable-first one.
        self.assertGreater(early_base["rows"][-1]["taxable"], plain_base["rows"][-1]["taxable"])
        self.assertNotEqual(early_base["total_lifetime_tax"], plain_base["total_lifetime_tax"])

    def test_the_fixed_age_early_draw_alternative_is_dropped_when_it_just_repeats_the_baseline(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 300_000, "real_estate": 0}
        same = compare_roth_conversion_strategies(
            pools=pools, expenses=[], assumptions=self._assumptions(birth_year="1966", early_tax_deferred_age="60"),
        )
        different = compare_roth_conversion_strategies(
            pools=pools, expenses=[], assumptions=self._assumptions(birth_year="1966", early_tax_deferred_age="65"),
        )
        self.assertNotIn("tax_deferred_from_60", {s["key"] for s in same["strategies"]})
        self.assertIn("tax_deferred_from_60", {s["key"] for s in different["strategies"]})

    def test_baseline_has_zero_legacy_gain_against_itself(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 300_000, "real_estate": 0}
        result = compare_roth_conversion_strategies(pools=pools, expenses=[], assumptions=self._assumptions())
        baseline = next(s for s in result["strategies"] if s["key"] == "no_conversions")
        self.assertAlmostEqual(baseline["legacy_gain_vs_baseline"], 0.0)

    def test_results_are_sorted_best_net_legacy_first(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 500_000, "real_estate": 0}
        result = compare_roth_conversion_strategies(pools=pools, expenses=[], assumptions=self._assumptions())
        legacies = [s["net_after_tax_legacy"] for s in result["strategies"]]
        self.assertEqual(legacies, sorted(legacies, reverse=True))

    def test_a_tied_net_legacy_breaks_in_favor_of_lower_lifetime_tax(self):
        # A fully-depleted plan (huge expense vs. a small pool) drives
        # every strategy's net_after_tax_legacy to the same $0 --
        # among that tie, the strategy that cost the least in lifetime
        # tax to get there (here, "no_conversions", since every
        # conversion strategy pays extra conversion tax for no legacy
        # benefit once everything's spent down anyway) should rank first.
        pools = {"tax_deferred": 50_000, "roth": 0, "taxable": 20_000, "real_estate": 0}
        expenses = [{"name": "Baseline", "annual_amount": 200_000, "start_year": None, "end_year": None}]
        result = compare_roth_conversion_strategies(
            pools=pools, expenses=expenses, assumptions=self._assumptions(plan_horizon_years="5"),
        )
        legacies = {s["net_after_tax_legacy"] for s in result["strategies"]}
        self.assertEqual(legacies, {0.0})  # sanity: this scenario really does tie every strategy at $0
        self.assertEqual(result["strategies"][0]["key"], "no_conversions")
        taxes = [s["total_lifetime_tax"] for s in result["strategies"]]
        self.assertEqual(taxes, sorted(taxes))

    def test_defaults_to_non_spouse_heir_type(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 300_000, "real_estate": 0}
        result = compare_roth_conversion_strategies(pools=pools, expenses=[], assumptions=self._assumptions())
        self.assertEqual(result["heir_type"], "non_spouse")

    def test_heir_type_assumption_is_honored(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 300_000, "real_estate": 0}
        result = compare_roth_conversion_strategies(pools=pools, expenses=[], assumptions=self._assumptions(heir_type="spouse"))
        self.assertEqual(result["heir_type"], "spouse")

    def test_explicit_heir_base_income_overrides_the_auto_fill(self):
        pools = {"tax_deferred": 500_000, "roth": 0, "taxable": 300_000, "real_estate": 0}
        result = compare_roth_conversion_strategies(
            pools=pools, expenses=[], assumptions=self._assumptions(heir_base_income="250000"),
        )
        self.assertAlmostEqual(result["heir_base_income"], 250_000.0)

    def test_a_plan_with_no_tax_deferred_money_at_all_has_nothing_to_convert(self):
        pools = {"tax_deferred": 0, "roth": 100_000, "taxable": 300_000, "real_estate": 0}
        result = compare_roth_conversion_strategies(pools=pools, expenses=[], assumptions=self._assumptions())
        for s in result["strategies"]:
            self.assertEqual(s["total_converted"], 0.0)


if __name__ == "__main__":
    unittest.main()


class TestFanChartHover(unittest.TestCase):
    def _result(self):
        return {"band": [{"year": 2026 + i, "p10": 100.0 + i, "median": 200.0 + i, "p90": 300.0 + i} for i in range(5)]}

    def test_responsive_chart_has_instant_hover(self):
        out = render_fan_svg(self._result(), responsive=True, plain=True, birth_year=1970)
        self.assertIn('class="fan-tip nw-tip"', out)
        self.assertIn(">Balance</text>", out)
        self.assertIn("mousemove", out)
        self.assertIn("$202", out)
        self.assertIn('["Typical", "Cautious", "Strong"]', out)

    def test_fixed_size_chart_unchanged(self):
        self.assertTrue(render_fan_svg(self._result()).startswith("<svg"))
