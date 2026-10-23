import unittest

from source.common import db
from source.reporting.aggregate import (
    asset_balance_history,
    build_summary,
    capture_asset_balance_snapshots,
    capture_debt_balance_snapshots,
    debt_balance_history,
    capture_daily_snapshots_if_new_day,
    capture_investment_account_balances,
    capture_net_worth_snapshot,
    category_subtotals,
    effective_loan_balance,
    effective_tax_treatment,
    real_estate_equity,
)
from tests.testing_utils import TempConfigTestCase


class TestRealEstateEquity(unittest.TestCase):
    def test_full_ownership(self):
        row = {"current_value": 500_000, "loan_balance": 200_000, "ownership_pct": 100}
        self.assertEqual(real_estate_equity(row), 300_000)

    def test_partial_ownership_scales_the_loan_too(self):
        # Ownership % applies to (value - loan) as a whole, not just value:
        # a 50% owner's equity is half of the 300,000 net, not half the
        # value minus the entire loan.
        row = {"current_value": 500_000, "loan_balance": 200_000, "ownership_pct": 50}
        self.assertEqual(real_estate_equity(row), 150_000)

    def test_missing_ownership_pct_defaults_to_full(self):
        row = {"current_value": 500_000, "loan_balance": 200_000}
        self.assertEqual(real_estate_equity(row), 300_000)

    def test_explicit_loan_balance_overrides_the_rows_own(self):
        row = {"current_value": 500_000, "loan_balance": 200_000, "ownership_pct": 100}
        self.assertEqual(real_estate_equity(row, loan_balance=50_000), 450_000)


class TestEffectiveLoanBalance(unittest.TestCase):
    def test_unlinked_row_uses_its_own_loan_balance(self):
        row = {"loan_balance": 200_000, "linked_account_id": None}
        self.assertEqual(effective_loan_balance(row, {}), 200_000)

    def test_linked_row_uses_the_live_balance_as_a_positive_magnitude(self):
        row = {"loan_balance": 1, "linked_account_id": "acc-1"}
        live = {"acc-1": {"balance": -480_000.0}}  # Plaid signs a loan balance negative
        self.assertEqual(effective_loan_balance(row, live), 480_000.0)

    def test_linked_to_a_removed_account_falls_back_to_the_typed_balance(self):
        row = {"loan_balance": 200_000, "linked_account_id": "acc-gone"}
        self.assertEqual(effective_loan_balance(row, {}), 200_000)


class TestBuildSummary(TempConfigTestCase):
    def test_empty_state(self):
        s = build_summary()
        self.assertEqual(s["net_worth"], 0)
        self.assertEqual(s["manual_asset_total"], 0)
        self.assertFalse(s["linked_status"]["configured"])

    def test_net_worth_combines_assets_liabilities_and_real_estate(self):
        db.add_line_item("assets", {"kind": "asset", "name": "401k", "balance": 100_000})
        db.add_line_item("assets", {"kind": "liability", "name": "Loan", "balance": 20_000})
        db.add_line_item("real_estate", {"name": "Home", "current_value": 500_000, "loan_balance": 300_000, "ownership_pct": 100})
        s = build_summary()
        # 100,000 (asset) - 20,000 (liability) + (500,000 - 300,000) (equity) = 280,000
        self.assertEqual(s["net_worth"], 280_000)
        self.assertEqual(s["manual_asset_total"], 100_000)
        self.assertEqual(s["liability_total"], 20_000)
        self.assertEqual(s["real_estate_equity_total"], 200_000)

    def test_rental_taxable_schedule_follows_the_loan_end_years(self):
        import json
        self.assertEqual(build_summary()["assumptions"]["rental_taxable_schedule"], "")
        db.add_line_item("real_estate", {"name": "A", "current_value": 1, "annual_income": 60_000, "loan_end_year": 2051})
        db.add_line_item("real_estate", {"name": "B", "current_value": 1, "annual_income": 20_000})
        db.add_line_item("real_estate", {"name": "Home", "current_value": 1, "annual_income": 0, "loan_end_year": 2040})
        schedule = json.loads(build_summary()["assumptions"]["rental_taxable_schedule"])
        self.assertEqual(schedule, [[2051, 60_000.0], [None, 20_000.0]])  # the rent-less Home is ignored

    def test_rental_taxable_schedule_without_any_annual_income_weights_loan_rows_equally(self):
        import json
        db.add_line_item("real_estate", {"name": "A", "current_value": 1, "loan_end_year": 2051})
        db.add_line_item("real_estate", {"name": "B", "current_value": 1, "loan_end_year": 2045})
        schedule = json.loads(build_summary()["assumptions"]["rental_taxable_schedule"])
        self.assertEqual(schedule, [[2051, 1.0], [2045, 1.0]])

    def test_this_year_expense_need_uses_current_year_assumption(self):
        db.set_assumption("current_year", 2030)
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 40_000})
        db.add_line_item("expenses", {"name": "Year 2031", "annual_amount": 5_000, "start_year": 2031, "end_year": 2031})
        s = build_summary()
        self.assertEqual(s["this_year"], 2030)
        self.assertEqual(s["this_year_expense_need"], 40_000)

    def test_this_year_expense_need_applies_inflation_to_an_inflating_row(self):
        db.set_assumption("current_year", 2028)
        db.set_assumption("inflation_rate", 0.03)
        db.add_line_item("expenses", {
            "name": "Fixed cost", "category": "Fixed", "annual_amount": 197_800,
            "base_year": 2026, "inflates": 1,
        })
        s = build_summary()
        self.assertAlmostEqual(s["this_year_expense_need"], 197_800 * 1.03 ** 2, places=2)

    def test_this_year_income_and_net_need_net_income_against_expenses(self):
        db.set_assumption("current_year", 2028)
        db.set_assumption("inflation_rate", 0.0)
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 300_000})
        db.add_line_item("income", {"name": "Rental", "category": "Rental", "annual_amount": 103_000})
        db.add_line_item("income", {"name": "Social Security", "category": "Social Security", "annual_amount": 42_000, "start_year": 2035})
        s = build_summary()
        # SS hasn't started yet in 2028 -- only rental income counts.
        self.assertEqual(s["this_year_income"], 103_000)
        self.assertEqual(s["this_year_expense_need"], 300_000)
        self.assertEqual(s["this_year_net_need"], 300_000 - 103_000)
        self.assertEqual(s["income"][0]["name"], "Rental")

    def test_next_year_expense_need_is_one_calendar_year_ahead(self):
        # The Summary page's tile shows next year's projected need, not
        # this year's -- next_year is always this_year + 1, computed
        # independently of (and without altering) current_year/this_year,
        # which every other page still treats as "now".
        db.set_assumption("current_year", 2026)
        db.set_assumption("inflation_rate", 0.03)
        db.add_line_item("expenses", {
            "name": "Fixed cost", "category": "Fixed", "annual_amount": 100_000,
            "base_year": 2026, "inflates": 1,
        })
        s = build_summary()
        self.assertEqual(s["this_year"], 2026)
        self.assertEqual(s["next_year"], 2027)
        self.assertAlmostEqual(s["this_year_expense_need"], 100_000 * 1.03 ** 0, places=2)
        self.assertAlmostEqual(s["next_year_expense_need"], 100_000 * 1.03 ** 1, places=2)

    def test_income_for_simulation_excludes_an_unchecked_row(self):
        db.set_assumption("current_year", 2028)
        db.set_assumption("inflation_rate", 0.0)
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 300_000})
        db.add_line_item("income", {"name": "Rental", "annual_amount": 103_000})
        unchecked_id = db.add_line_item("income", {"name": "Side gig", "annual_amount": 20_000})
        db.update_line_item("income", unchecked_id, {"include_in_monte_carlo": 0})
        s = build_summary()
        # "income" itself still lists every row (for display) -- only
        # "income_for_simulation" (and anything derived from it, like
        # this_year_income) drops the unchecked one.
        self.assertEqual(len(s["income"]), 2)
        self.assertEqual(len(s["income_for_simulation"]), 1)
        self.assertEqual(s["income_for_simulation"][0]["name"], "Rental")
        self.assertEqual(s["this_year_income"], 103_000)
        self.assertEqual(s["this_year_net_need"], 300_000 - 103_000)

    def test_income_for_simulation_includes_a_row_with_no_explicit_flag_since_it_defaults_on(self):
        # A row added straight through db.add_line_item without
        # specifying include_in_monte_carlo relies on the column's own
        # DEFAULT 1 -- confirms build_summary() honors that default too,
        # not just an explicitly-set 1.
        db.add_line_item("income", {"name": "Pension", "annual_amount": 40_000})
        s = build_summary()
        self.assertEqual(len(s["income_for_simulation"]), 1)

    def test_empty_state_income_fields_are_zero(self):
        s = build_summary()
        self.assertEqual(s["income"], [])
        self.assertEqual(s["this_year_income"], 0)
        self.assertEqual(s["this_year_net_need"], 0)

    def test_net_worth_folds_in_linked_plaid_balances(self):
        db.upsert_plaid_item(
            item_key="fidelity_401k", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-1", "name": "401k", "official_name": "Fidelity 401k",
            "type": "investment", "subtype": "401k", "mask": "1234",
            "balances": {"current": 75_000, "available": None, "iso_currency_code": "USD"},
        })
        db.add_line_item("assets", {"kind": "asset", "name": "Cash", "balance": 10_000})
        s = build_summary()
        self.assertTrue(s["linked_status"]["configured"])
        self.assertEqual(s["linked_asset_total"], 75_000)
        self.assertEqual(s["net_worth"], 85_000)

    def test_linking_a_line_item_to_a_plaid_account_uses_the_live_balance_once_not_twice(self):
        # Same setup as above, but "Cash" is now linked to that same
        # Fidelity account -- the point of linking is that the line item
        # tracks the live balance automatically, so it must show up in
        # net worth exactly once (via manual_asset_total, using the live
        # number), not once from the line item and again from
        # linked_asset_total.
        db.upsert_plaid_item(
            item_key="fidelity_401k", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-1", "name": "401k", "official_name": "Fidelity 401k",
            "type": "investment", "subtype": "401k", "mask": "1234",
            "balances": {"current": 75_000, "available": None, "iso_currency_code": "USD"},
        })
        item_id = db.add_line_item("assets", {"kind": "asset", "name": "Vatsa 401k", "balance": 100})
        db.update_line_item("assets", item_id, {"linked_account_id": "acc-1"})
        s = build_summary()
        self.assertEqual(s["manual_asset_total"], 75_000)  # live balance, not the stale 100
        self.assertEqual(s["linked_asset_total"], 0)  # already folded into manual_asset_total above
        self.assertEqual(s["net_worth"], 75_000)

    def test_linking_a_liability_row_uses_the_positive_magnitude(self):
        db.upsert_plaid_item(
            item_key="chase", plaid_item_id="item-2", institution_id="ins_2",
            institution_name="Chase", products=["transactions"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="chase", account={
            "account_id": "acc-cc", "name": "Chase Credit Card", "official_name": "Chase Credit Card",
            "type": "credit", "subtype": "credit card", "mask": "9999",
            "balances": {"current": 1_200.0, "available": None, "iso_currency_code": "USD"},
        })
        item_id = db.add_line_item("assets", {"kind": "liability", "name": "Chase card", "balance": 1})
        db.update_line_item("assets", item_id, {"linked_account_id": "acc-cc"})
        s = build_summary()
        # Plaid signs a credit balance negative (-1,200); the liability
        # total (subtracted from net worth) must still come out positive.
        self.assertEqual(s["liability_total"], 1_200.0)
        self.assertEqual(s["net_worth"], -1_200.0)

    def test_retirement_liquid_total_only_counts_rows_checked_in_monte_carlo(self):
        # The Monte Carlo tab's starting balance is narrower than net
        # worth -- only money that could actually fund retirement
        # withdrawals. Insurance and real estate equity are net worth,
        # but not this -- and, per-row now, an unchecked row isn't either.
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade", "balance": 50_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Insurance", "name": "Whole life", "balance": 20_000})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Credit card", "balance": 5_000})
        db.add_line_item("real_estate", {"name": "Home", "current_value": 500_000, "loan_balance": 300_000, "ownership_pct": 100})
        s = build_summary()
        self.assertEqual(s["retirement_liquid_total"], 150_000)  # 100,000 + 50,000, nothing else
        # Net worth still includes everything, for comparison.
        self.assertEqual(s["net_worth"], 100_000 + 50_000 + 20_000 - 5_000 + 200_000)

    def test_retirement_liquid_total_ignores_category_now_only_the_checkbox_matters(self):
        # Category used to gate this (the old retirement_liquid_categories
        # assumption); now it's purely per-row -- an arbitrary category
        # counts once checked, and a 401k/Liquid row doesn't count if left
        # unchecked.
        db.add_line_item("assets", {"kind": "asset", "category": "Brokerage", "name": "A", "balance": 10_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "B", "balance": 5_000})
        s = build_summary()
        self.assertEqual(s["retirement_liquid_total"], 10_000)

    def test_retirement_liquid_total_uses_the_live_balance_when_linked(self):
        db.upsert_plaid_item(
            item_key="fidelity_401k", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-1", "name": "401k", "official_name": "Fidelity 401k",
            "type": "investment", "subtype": "401k", "mask": "1234",
            "balances": {"current": 75_000, "available": None, "iso_currency_code": "USD"},
        })
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Vatsa 401k", "balance": 1, "include_in_monte_carlo": 1})
        db.update_line_item("assets", item_id, {"linked_account_id": "acc-1"})
        s = build_summary()
        self.assertEqual(s["retirement_liquid_total"], 75_000)  # live balance, not the stale 1

    def test_retirement_liquid_total_zero_when_nothing_checked(self):
        db.add_line_item("assets", {"kind": "asset", "category": "Insurance", "name": "Whole life", "balance": 20_000})
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 100_000})
        s = build_summary()
        self.assertEqual(s["retirement_liquid_total"], 0)

    def test_linked_account_id_pointing_at_a_removed_account_falls_back_to_the_typed_balance(self):
        item_id = db.add_line_item("assets", {"kind": "asset", "name": "Old link", "balance": 500})
        db.update_line_item("assets", item_id, {"linked_account_id": "acc-does-not-exist"})
        s = build_summary()
        self.assertEqual(s["manual_asset_total"], 500)

    def test_linking_a_property_loan_uses_the_live_balance_once_not_twice(self):
        db.upsert_plaid_item(
            item_key="wells_fargo", plaid_item_id="item-3", institution_id="ins_4",
            institution_name="Wells Fargo", products=["transactions"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="wells_fargo", account={
            "account_id": "acc-mortgage", "name": "MORTGAGE ...7982", "official_name": "MORTGAGE ...7982",
            "type": "loan", "subtype": "mortgage", "mask": "7982",
            "balances": {"current": 480_000.0, "available": None, "iso_currency_code": "USD"},
        })
        item_id = db.add_line_item("real_estate", {
            "name": "Moorpark", "current_value": 900_000, "loan_balance": 1, "ownership_pct": 100,
        })
        db.update_line_item("real_estate", item_id, {"linked_account_id": "acc-mortgage"})
        s = build_summary()
        # Equity uses the live mortgage balance (900,000 - 480,000), not the stale 1.
        self.assertEqual(s["real_estate_equity_total"], 420_000)
        # And that Plaid account isn't also counted separately.
        self.assertEqual(s["linked_asset_total"], 0)
        self.assertEqual(s["net_worth"], 420_000)


class TestEffectiveTaxTreatment(unittest.TestCase):
    def test_explicit_value_wins(self):
        self.assertEqual(effective_tax_treatment({"category": "401k", "tax_treatment": "roth"}), "roth")

    def test_401k_category_defaults_to_tax_deferred(self):
        self.assertEqual(effective_tax_treatment({"category": "401k", "tax_treatment": ""}), "tax_deferred")
        self.assertEqual(effective_tax_treatment({"category": "401k", "tax_treatment": None}), "tax_deferred")

    def test_liquid_category_defaults_to_taxable(self):
        self.assertEqual(effective_tax_treatment({"category": "Liquid", "tax_treatment": ""}), "taxable")

    def test_unrecognized_category_defaults_to_taxable(self):
        self.assertEqual(effective_tax_treatment({"category": "Insurance", "tax_treatment": ""}), "taxable")

    def test_garbage_stored_value_falls_back_to_category_default(self):
        self.assertEqual(effective_tax_treatment({"category": "401k", "tax_treatment": "bogus"}), "tax_deferred")

    def test_case_insensitive(self):
        self.assertEqual(effective_tax_treatment({"category": "401K", "tax_treatment": "ROTH"}), "roth")

    def test_live_by_account_id_omitted_behaves_exactly_as_before(self):
        # No live_by_account_id argument at all -- every pre-existing
        # caller/test that only ever passed one positional arg must keep
        # getting exactly the old category-default behavior.
        row = {"category": "Liquid", "tax_treatment": "", "linked_account_id": "acc-roth"}
        self.assertEqual(effective_tax_treatment(row), "taxable")

    def test_linked_accounts_detected_treatment_overrides_the_category_default(self):
        # A Roth IRA linked on the Asset tab, filed under the "Liquid"
        # category (its category is unrelated to tax status) and never
        # manually tagged -- the account's own Plaid subtype ("roth")
        # should win over the "Liquid" -> taxable category guess.
        row = {"category": "Liquid", "tax_treatment": "", "linked_account_id": "acc-roth"}
        live_by_account_id = {"acc-roth": {"detected_tax_treatment": "roth"}}
        self.assertEqual(effective_tax_treatment(row, live_by_account_id), "roth")

    def test_explicit_tax_treatment_still_wins_over_detection(self):
        row = {"category": "Liquid", "tax_treatment": "taxable", "linked_account_id": "acc-roth"}
        live_by_account_id = {"acc-roth": {"detected_tax_treatment": "roth"}}
        self.assertEqual(effective_tax_treatment(row, live_by_account_id), "taxable")

    def test_unlinked_row_falls_back_to_category_default_even_with_live_by_account_id(self):
        row = {"category": "401k", "tax_treatment": "", "linked_account_id": None}
        self.assertEqual(effective_tax_treatment(row, {}), "tax_deferred")

    def test_linked_account_with_no_detection_falls_back_to_category_default(self):
        # e.g. a linked brokerage account -- subtype isn't a recognized
        # retirement-account subtype, so detected_tax_treatment is None.
        row = {"category": "Liquid", "tax_treatment": "", "linked_account_id": "acc-brokerage"}
        live_by_account_id = {"acc-brokerage": {"detected_tax_treatment": None}}
        self.assertEqual(effective_tax_treatment(row, live_by_account_id), "taxable")


class TestRetirementPools(TempConfigTestCase):
    """build_summary()'s tax_deferred_total/roth_total/taxable_total and
    retirement_pools -- the three-way split of retirement_liquid_total
    that source.reporting.monte_carlo's withdrawal/RMD engine simulates
    separately."""

    def test_splits_by_explicit_tax_treatment(self):
        a1 = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Trad 401k", "balance": 100_000, "include_in_monte_carlo": 1})
        db.update_line_item("assets", a1, {"tax_treatment": "tax_deferred"})
        a2 = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Roth 401k", "balance": 40_000, "include_in_monte_carlo": 1})
        db.update_line_item("assets", a2, {"tax_treatment": "roth"})
        a3 = db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Brokerage", "balance": 60_000, "include_in_monte_carlo": 1})
        db.update_line_item("assets", a3, {"tax_treatment": "taxable"})
        s = build_summary()
        self.assertEqual(s["tax_deferred_total"], 100_000)
        self.assertEqual(s["roth_total"], 40_000)
        self.assertEqual(s["taxable_total"], 60_000)
        self.assertEqual(s["tax_deferred_total"] + s["roth_total"] + s["taxable_total"], s["retirement_liquid_total"])

    def test_untagged_rows_use_category_default(self):
        # Nothing explicitly tagged: 401k falls to tax_deferred, Liquid
        # falls to taxable -- matches the pre-this-feature behavior where
        # everything was implicitly taxed as if pre-tax/401k.
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "B", "balance": 25_000, "include_in_monte_carlo": 1})
        s = build_summary()
        self.assertEqual(s["tax_deferred_total"], 100_000)
        self.assertEqual(s["taxable_total"], 25_000)
        self.assertEqual(s["roth_total"], 0)

    def test_retirement_pools_sums_to_net_liquid_asset(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "B", "balance": 50_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Card", "balance": 10_000})
        s = build_summary()
        pools = s["retirement_pools"]
        self.assertAlmostEqual(sum(pools.values()), s["net_liquid_asset"])

    def test_liability_nets_out_of_taxable_pool_first(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "B", "balance": 50_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Card", "balance": 10_000})
        s = build_summary()
        pools = s["retirement_pools"]
        self.assertEqual(pools["taxable"], 40_000)  # 50,000 - 10,000
        self.assertEqual(pools["tax_deferred"], 100_000)  # untouched

    def test_liability_larger_than_taxable_spills_into_tax_deferred(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "B", "balance": 5_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Card", "balance": 20_000})
        s = build_summary()
        pools = s["retirement_pools"]
        self.assertEqual(pools["taxable"], 0)
        self.assertEqual(pools["tax_deferred"], 85_000)  # 100,000 - (20,000 - 5,000)

    def test_pools_never_go_negative(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 1_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Card", "balance": 50_000})
        s = build_summary()
        pools = s["retirement_pools"]
        self.assertEqual(pools["taxable"], 0)
        self.assertEqual(pools["tax_deferred"], 0)
        self.assertEqual(pools["roth"], 0)

    def test_retirement_pools_has_a_real_estate_key_defaulting_to_zero(self):
        # Always present (even with no real estate at all, or none opted
        # in) so every caller can treat retirement_pools as a fixed
        # four-key shape -- see aggregate.build_summary's own comment.
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 100_000, "include_in_monte_carlo": 1})
        s = build_summary()
        self.assertEqual(s["retirement_pools"]["real_estate"], 0)

    def test_opted_in_property_equity_becomes_the_real_estate_pool(self):
        db.add_line_item("real_estate", {
            "name": "Rental", "current_value": 500_000, "loan_balance": 200_000, "ownership_pct": 100,
        })
        r2_id = db.add_line_item("real_estate", {
            "name": "Cabin", "current_value": 300_000, "loan_balance": 0, "ownership_pct": 100,
        })
        s = build_summary()
        # Neither property opted in yet -- the pool is empty even though
        # real_estate_equity_total (net worth's own figure) is not.
        self.assertEqual(s["retirement_pools"]["real_estate"], 0)
        self.assertGreater(s["real_estate_equity_total"], 0)

    def test_only_opted_in_properties_count_toward_the_real_estate_pool(self):
        r1_id = db.add_line_item("real_estate", {
            "name": "Rental", "current_value": 500_000, "loan_balance": 200_000, "ownership_pct": 100,
        })
        db.add_line_item("real_estate", {
            "name": "Cabin", "current_value": 300_000, "loan_balance": 0, "ownership_pct": 100,
        })
        db.update_line_item("real_estate", r1_id, {"include_in_monte_carlo": 1})
        s = build_summary()
        self.assertEqual(s["retirement_pools"]["real_estate"], 300_000)  # Rental equity only: 500,000 - 200,000

    def test_real_estate_pool_is_not_netted_against_asset_tab_liabilities(self):
        # A property's own mortgage is already netted into its equity by
        # real_estate_equity() -- an unrelated Asset-tab liability (e.g. a
        # credit card) shouldn't also eat into the opted-in real estate
        # pool the way it eats into taxable/tax_deferred/roth.
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Card", "balance": 1_000_000})
        r_id = db.add_line_item("real_estate", {"name": "Cabin", "current_value": 300_000, "loan_balance": 0, "ownership_pct": 100})
        db.update_line_item("real_estate", r_id, {"include_in_monte_carlo": 1})
        s = build_summary()
        self.assertEqual(s["retirement_pools"]["real_estate"], 300_000)


class TestDrawdownPlanning(TempConfigTestCase):
    """build_summary()'s drawdown_pools/drawdown_sources/
    drawdown_unlinked_total -- the Drawdown Planning tab's own numbers,
    which extend retirement_pools with linked Plaid investment accounts
    that were never added to the Asset tab at all (source.common.
    linked_data.detected_tax_treatment, keyed off each account's own
    Plaid subtype)."""

    def _link_fidelity_roth(self, *, account_id="acc-roth", subtype="roth", balance=50_000.0):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-fidelity", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": account_id, "name": "ROTH IRA", "official_name": "ROTH IRA",
            "type": "investment", "subtype": subtype, "mask": "4321",
            "balances": {"current": balance, "available": None, "iso_currency_code": "USD"},
        })

    def test_drawdown_pools_matches_retirement_pools_with_nothing_unlinked(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 100_000, "include_in_monte_carlo": 1})
        s = build_summary()
        self.assertEqual(s["drawdown_pools"], s["retirement_pools"])
        self.assertEqual(s["drawdown_unlinked_total"], 0)

    def test_an_unlinked_investment_account_is_added_to_its_detected_bucket(self):
        # Fidelity Roth IRA, never added to the Asset tab at all -- the
        # exact scenario the user asked for ("account sources like Roth
        # conversion, IRA, 401k for fidelity").
        self._link_fidelity_roth(balance=50_000.0)
        s = build_summary()
        self.assertEqual(s["drawdown_pools"]["roth"], 50_000.0)
        self.assertEqual(s["drawdown_unlinked_total"], 50_000.0)
        # retirement_pools itself is untouched -- it only ever reflects
        # manual Asset-tab rows checked "In the plan?".
        self.assertEqual(s["retirement_pools"]["roth"], 0.0)

    def test_an_unlinked_investment_account_with_no_detected_subtype_defaults_to_taxable(self):
        self._link_fidelity_roth(account_id="acc-brokerage", subtype="brokerage", balance=30_000.0)
        s = build_summary()
        self.assertEqual(s["drawdown_pools"]["taxable"], 30_000.0)

    def test_an_account_already_linked_to_an_asset_row_is_not_double_counted(self):
        self._link_fidelity_roth(balance=50_000.0)
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Roth", "balance": 1, "include_in_monte_carlo": 1})
        db.update_line_item("assets", item_id, {"linked_account_id": "acc-roth"})
        s = build_summary()
        # Already inside retirement_pools (via effective_tax_treatment's
        # own detection) -- must not also be added a second time as an
        # "unlinked" account.
        self.assertEqual(s["drawdown_unlinked_total"], 0)
        self.assertEqual(s["drawdown_pools"]["roth"], 50_000.0)
        self.assertEqual(s["retirement_pools"]["roth"], 50_000.0)  # auto-filled from the linked subtype too

    def test_a_non_investment_linked_account_is_never_pulled_into_drawdown_pools(self):
        # A checking/credit account isn't a retirement resource -- only
        # type == "investment" accounts are eligible for the unlinked
        # drawdown-pool treatment.
        db.upsert_plaid_item(
            item_key="chase", plaid_item_id="item-chase", institution_id="ins_2",
            institution_name="Chase", products=["transactions"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="chase", account={
            "account_id": "acc-checking", "name": "Checking", "official_name": "Checking",
            "type": "depository", "subtype": "checking", "mask": "5555",
            "balances": {"current": 10_000.0, "available": None, "iso_currency_code": "USD"},
        })
        s = build_summary()
        self.assertEqual(s["drawdown_unlinked_total"], 0)

    def test_drawdown_sources_lists_manual_linked_and_real_estate_rows(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Manual 401k", "balance": 100_000, "include_in_monte_carlo": 1})
        self._link_fidelity_roth(balance=50_000.0)
        r_id = db.add_line_item("real_estate", {"name": "Cabin", "current_value": 300_000, "loan_balance": 0, "ownership_pct": 100})
        db.update_line_item("real_estate", r_id, {"include_in_monte_carlo": 1})
        s = build_summary()
        names = {src["name"]: src for src in s["drawdown_sources"]}
        self.assertEqual(names["Manual 401k"]["tax_bucket"], "tax_deferred")
        self.assertEqual(names["Manual 401k"]["origin"], "Manual entry (Assets tab)")
        self.assertEqual(names["ROTH IRA"]["tax_bucket"], "roth")
        self.assertEqual(names["ROTH IRA"]["origin"], "Linked account (not on Assets tab)")
        self.assertEqual(names["ROTH IRA"]["institution"], "Fidelity")
        self.assertEqual(names["Cabin"]["tax_bucket"], "real_estate")
        self.assertEqual(names["Cabin"]["balance"], 300_000)

    def test_drawdown_sources_is_empty_with_no_data(self):
        s = build_summary()
        self.assertEqual(s["drawdown_sources"], [])

    def test_splits_replace_the_lump_source_with_named_pieces_and_their_own_buckets(self):
        # Per the user's own request ("for fidelity can i segregate the
        # sources manually" / "give me option to break up one sum to
        # parts") -- a single Plaid account/subtype is one bucket for the
        # whole balance, but a real 401k can mix pre-tax and Roth money.
        self._link_fidelity_roth(subtype="401k", balance=100_000.0)
        db.add_line_item("account_tax_splits", {
            "account_id": "acc-roth", "name": "Base Pay Traditional", "tax_treatment": "tax_deferred", "amount": 70_000,
        })
        db.add_line_item("account_tax_splits", {
            "account_id": "acc-roth", "name": "Roth In-Plan Conversion", "tax_treatment": "roth", "amount": 30_000,
        })
        s = build_summary()
        self.assertEqual(s["drawdown_pools"]["tax_deferred"], 70_000.0)
        self.assertEqual(s["drawdown_pools"]["roth"], 30_000.0)
        self.assertEqual(s["drawdown_unlinked_total"], 100_000.0)
        names = {src["name"]: src for src in s["drawdown_sources"]}
        self.assertNotIn("ROTH IRA", names)  # the lump entry is gone, replaced by its own pieces below
        self.assertEqual(names["ROTH IRA -- Base Pay Traditional"]["tax_bucket"], "tax_deferred")
        self.assertEqual(names["ROTH IRA -- Base Pay Traditional"]["balance"], 70_000.0)
        self.assertEqual(names["ROTH IRA -- Roth In-Plan Conversion"]["tax_bucket"], "roth")
        self.assertEqual(names["ROTH IRA -- Roth In-Plan Conversion"]["origin"], "Linked account (not on Assets tab, manually split)")
        self.assertEqual(s["account_split_mismatches"], [])

    def test_split_mismatch_with_the_live_balance_is_flagged(self):
        self._link_fidelity_roth(subtype="401k", balance=100_000.0)
        db.add_line_item("account_tax_splits", {
            "account_id": "acc-roth", "name": "Base Pay Traditional", "tax_treatment": "tax_deferred", "amount": 40_000,
        })
        s = build_summary()
        self.assertEqual(len(s["account_split_mismatches"]), 1)
        mismatch = s["account_split_mismatches"][0]
        self.assertEqual(mismatch["account_id"], "acc-roth")
        self.assertEqual(mismatch["live_balance"], 100_000.0)
        self.assertEqual(mismatch["split_total"], 40_000.0)

    def test_a_split_for_an_account_linked_to_an_asset_tab_row_is_applied_there_too(self):
        # Splitting isn't limited to the "unlinked investment account"
        # case -- once the split's own account is linked to a manual
        # Asset row (the common case: a 401k the user already added),
        # its splits replace that row's own single Tax treatment bucket
        # everywhere, including retirement_pools -- so the Monte Carlo
        # simulation itself sees the split too, not just the Drawdown
        # Planning tab's own snapshot.
        self._link_fidelity_roth(subtype="401k", balance=100_000.0)
        db.add_line_item("account_tax_splits", {
            "account_id": "acc-roth", "name": "Base Pay Traditional", "tax_treatment": "tax_deferred", "amount": 70_000,
        })
        db.add_line_item("account_tax_splits", {
            "account_id": "acc-roth", "name": "Roth In-Plan Conversion", "tax_treatment": "roth", "amount": 30_000,
        })
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "401k", "balance": 1, "include_in_monte_carlo": 1})
        db.update_line_item("assets", item_id, {"linked_account_id": "acc-roth"})
        s = build_summary()
        self.assertEqual(s["retirement_pools"]["tax_deferred"], 70_000.0)
        self.assertEqual(s["retirement_pools"]["roth"], 30_000.0)
        self.assertEqual(s["drawdown_pools"]["tax_deferred"], 70_000.0)
        self.assertEqual(s["drawdown_pools"]["roth"], 30_000.0)
        self.assertEqual(s["account_split_mismatches"], [])
        names = {src["name"]: src for src in s["drawdown_sources"]}
        self.assertNotIn("401k", names)  # the lump row is gone, replaced by its own named pieces
        self.assertEqual(names["401k -- Base Pay Traditional"]["tax_bucket"], "tax_deferred")
        self.assertEqual(names["401k -- Roth In-Plan Conversion"]["tax_bucket"], "roth")
        self.assertEqual(names["401k -- Roth In-Plan Conversion"]["origin"], "Linked account (Assets tab, manually split)")

    def test_splittable_investment_accounts_includes_ones_already_linked_to_an_asset_row(self):
        # unlinked_investment_accounts (the Drawdown Planning tab's own
        # "lump balance" list) still excludes a linked account -- but
        # splittable_investment_accounts (the split card's own account
        # picker) offers it too, since row_bucket_amounts above now
        # applies a linked account's splits as well.
        self._link_fidelity_roth(subtype="401k", balance=100_000.0)
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "401k", "balance": 1, "include_in_monte_carlo": 1})
        db.update_line_item("assets", item_id, {"linked_account_id": "acc-roth"})
        s = build_summary()
        self.assertIn("acc-roth", {acc["account_id"] for acc in s["splittable_investment_accounts"]})
        self.assertNotIn("acc-roth", {acc["account_id"] for acc in s["unlinked_investment_accounts"]})


class TestCategorySubtotals(unittest.TestCase):
    """The shared helper behind build_summary()'s asset_category_subtotals
    and the Asset tab's own top Summary table -- same function, so the two
    pages can never show different numbers for the same category."""

    def test_sums_per_category_in_first_seen_order(self):
        rows = [
            {"category": "401k", "balance": 100_000, "kind": "asset"},
            {"category": "Liquid", "balance": 50_000, "kind": "asset"},
            {"category": "401k", "balance": 25_000, "kind": "asset"},
        ]
        self.assertEqual(category_subtotals(rows, {}), [("401k", 125_000), ("Liquid", 50_000)])

    def test_blank_category_folds_into_uncategorized(self):
        rows = [{"category": None, "balance": 10, "kind": "asset"}, {"category": "  ", "balance": 5, "kind": "asset"}]
        self.assertEqual(category_subtotals(rows, {}), [("Uncategorized", 15)])

    def test_uses_the_live_balance_when_linked(self):
        rows = [{"category": "401k", "balance": 1, "kind": "asset", "linked_account_id": "acc-1"}]
        live = {"acc-1": {"balance": 75_000.0}}
        self.assertEqual(category_subtotals(rows, live), [("401k", 75_000.0)])


class TestBuildSummaryAssetBreakdown(TempConfigTestCase):
    """asset_category_subtotals / net_liquid_asset / total_asset -- lifted
    into build_summary() so the Summary tab can show the Asset tab's *real*
    balances by category instead of a single lumped "manual asset total"
    figure that didn't match what the Asset tab itself displayed."""

    def test_empty_state(self):
        s = build_summary()
        self.assertEqual(s["asset_category_subtotals"], [])
        self.assertEqual(s["net_liquid_asset"], 0)
        self.assertEqual(s["total_asset"], 0)

    def test_matches_what_the_asset_tab_itself_would_show(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade", "balance": 50_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Insurance", "name": "Whole life", "balance": 20_000})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Credit card", "balance": 5_000})
        db.add_line_item("real_estate", {"name": "Home", "current_value": 500_000, "loan_balance": 300_000, "ownership_pct": 100})
        s = build_summary()
        self.assertEqual(
            s["asset_category_subtotals"],
            [("401k", 100_000), ("Liquid", 50_000), ("Insurance", 20_000)],
        )
        # Net Liquid Asset = rows checked "In the plan?" only, net of
        # liabilities -- same rule as retirement_liquid_total, Insurance
        # excluded (left unchecked).
        self.assertEqual(s["net_liquid_asset"], 100_000 + 50_000 - 5_000)
        # Total Asset = Net Liquid Asset + real estate equity.
        self.assertEqual(s["total_asset"], s["net_liquid_asset"] + 200_000)

    def test_liability_rows_are_excluded_from_the_asset_breakdown(self):
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Card", "balance": 5_000})
        s = build_summary()
        self.assertEqual(s["asset_category_subtotals"], [])


class TestCaptureNetWorthSnapshot(TempConfigTestCase):
    def test_records_todays_snapshot_from_a_built_summary(self):
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Bank", "balance": 10_000})
        capture_net_worth_snapshot()
        rows = db.list_net_worth_snapshots()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["net_worth"], 10_000)

    def test_accepts_an_already_built_summary_without_rebuilding_it(self):
        s = build_summary()
        s = {**s, "net_worth": 12345.0}
        capture_net_worth_snapshot(s)
        self.assertEqual(db.list_net_worth_snapshots()[0]["net_worth"], 12345.0)

    def test_calling_it_twice_the_same_day_upserts_not_duplicates(self):
        capture_net_worth_snapshot()
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Bank", "balance": 5_000})
        capture_net_worth_snapshot()
        rows = db.list_net_worth_snapshots()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["net_worth"], 5_000)


class TestCaptureInvestmentAccountBalances(TempConfigTestCase):
    def test_records_one_snapshot_per_investment_account(self):
        capture_investment_account_balances([
            {"account_id": "acc1", "balance": 1_000.0, "type": "investment"},
            {"account_id": "acc2", "balance": 2_000.0, "type": "investment"},
        ])
        rows = db.list_account_balance_snapshots()
        self.assertEqual(len(rows), 2)
        balances = {r["account_id"]: r["balance"] for r in rows}
        self.assertEqual(balances, {"acc1": 1_000.0, "acc2": 2_000.0})

    def test_non_investment_accounts_are_skipped(self):
        capture_investment_account_balances([
            {"account_id": "acc1", "balance": 1_000.0, "type": "investment"},
            {"account_id": "acc2", "balance": 500.0, "type": "depository"},
            {"account_id": "acc3", "balance": 100.0, "type": "credit"},
        ])
        rows = db.list_account_balance_snapshots()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["account_id"], "acc1")

    def test_calling_it_twice_the_same_day_upserts_not_duplicates(self):
        capture_investment_account_balances([{"account_id": "acc1", "balance": 1_000.0, "type": "investment"}])
        capture_investment_account_balances([{"account_id": "acc1", "balance": 1_500.0, "type": "investment"}])
        rows = db.list_account_balance_snapshots()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["balance"], 1_500.0)

    def test_empty_account_list_records_nothing(self):
        capture_investment_account_balances([])
        self.assertEqual(db.list_account_balance_snapshots(), [])


if __name__ == "__main__":
    unittest.main()


class TestCaptureDailySnapshotsIfNewDay(TempConfigTestCase):
    def _dates(self):
        return [r["snapshot_date"] for r in db.list_net_worth_snapshots()]

    def test_captures_when_the_date_has_changed(self):
        from datetime import date
        today = date.today().isoformat()
        returned = capture_daily_snapshots_if_new_day("1999-01-01")
        self.assertEqual(returned, today)
        self.assertEqual(self._dates(), [today])

    def test_the_first_ever_call_captures_today(self):
        from datetime import date
        today = date.today().isoformat()
        self.assertEqual(capture_daily_snapshots_if_new_day(None), today)
        self.assertEqual(self._dates(), [today])

    def test_does_nothing_on_the_same_day(self):
        returned = capture_daily_snapshots_if_new_day("2026-09-02", today="2026-09-02")
        self.assertEqual(returned, "2026-09-02")
        self.assertEqual(self._dates(), [])

    def test_a_failed_capture_propagates_so_the_day_is_not_marked_done(self):
        from unittest.mock import patch
        with patch("source.reporting.aggregate.capture_net_worth_snapshot", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                capture_daily_snapshots_if_new_day("2026-09-01", today="2026-09-02")

    def test_also_records_investment_account_balances(self):
        from unittest.mock import patch
        with patch("source.reporting.aggregate.capture_investment_account_balances") as balances:
            capture_daily_snapshots_if_new_day("2026-09-01", today="2026-09-02")
        balances.assert_called_once()


class TestRealEstateValueCapture(TempConfigTestCase):
    def test_value_is_your_ownership_share_of_market_value_before_loans(self):
        db.add_line_item("real_estate", {"name": "Home", "current_value": 1_000_000, "loan_balance": 400_000})
        db.add_line_item("real_estate", {
            "name": "Cabin", "current_value": 200_000, "loan_balance": 50_000, "ownership_pct": 50,
        })
        s = build_summary()
        self.assertEqual(s["real_estate_value_total"], 1_100_000.0)
        self.assertEqual(s["real_estate_equity_total"], 600_000.0 + 75_000.0)

    def test_capture_net_worth_snapshot_records_the_value(self):
        db.add_line_item("real_estate", {"name": "Home", "current_value": 800_000, "loan_balance": 300_000})
        capture_net_worth_snapshot()
        row = db.list_net_worth_snapshots()[0]
        self.assertEqual(row["real_estate_value_total"], 800_000.0)
        self.assertEqual(row["real_estate_equity_total"], 500_000.0)


class TestAssetBalanceSnapshots(TempConfigTestCase):
    """Per-asset daily history behind the Asset tab's "plot individual
    assets next to net worth" chart."""

    def _asset(self, name, balance, **extra):
        return db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": name, "balance": balance, **extra})

    def test_capture_records_one_row_per_asset_and_skips_liabilities(self):
        a = self._asset("Fidelity", 100_000)
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Card", "balance": 5_000})
        capture_asset_balance_snapshots()
        rows = db.list_asset_balance_snapshots()
        self.assertEqual([(r["asset_id"], r["balance"], r["name"]) for r in rows], [(a, 100_000.0, "Fidelity")])

    def test_capturing_twice_the_same_day_overwrites_instead_of_duplicating(self):
        a = self._asset("Fidelity", 100_000)
        capture_asset_balance_snapshots()
        db.update_line_item("assets", a, {"balance": 120_000})
        capture_asset_balance_snapshots()
        rows = db.list_asset_balance_snapshots(a)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["balance"], 120_000.0)

    def test_capture_net_worth_snapshot_also_captures_assets(self):
        a = self._asset("Fidelity", 100_000)
        capture_net_worth_snapshot()
        self.assertEqual(len(db.list_asset_balance_snapshots(a)), 1)

    def test_history_is_sorted_largest_first_and_sorted_by_date(self):
        small = self._asset("Small", 1_000)
        big = self._asset("Big", 9_000)
        for d, v in (("2026-09-02", 9_100.0), ("2026-09-01", 9_000.0)):
            db.record_asset_balance_snapshot(asset_id=big, balance=v, name="Big", snapshot_date=d)
        db.record_asset_balance_snapshot(asset_id=small, balance=1_000.0, name="Small", snapshot_date="2026-09-01")
        history = asset_balance_history(db.list_line_items("assets"))
        self.assertEqual([h["name"] for h in history], ["Big", "Small"])
        self.assertEqual(history[0]["points"], [("2026-09-01", 9_000.0), ("2026-09-02", 9_100.0)])

    def test_linked_rows_backfill_from_their_accounts_own_history_and_own_snapshots_win(self):
        a = self._asset("Linked 401k", 1, linked_account_id="acc-1")
        db.record_account_balance_snapshot(account_id="acc-1", balance=50_000.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc-1", balance=51_000.0, snapshot_date="2026-09-02")
        db.record_asset_balance_snapshot(asset_id=a, balance=52_500.0, name="Linked 401k", snapshot_date="2026-09-02")
        history = asset_balance_history(db.list_line_items("assets"))
        self.assertEqual(history[0]["points"], [("2026-09-01", 50_000.0), ("2026-09-02", 52_500.0)])

    def test_rows_with_no_history_and_liabilities_are_left_out(self):
        self._asset("No history", 5_000)
        liab = db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Card", "balance": 5_000})
        db.record_asset_balance_snapshot(asset_id=liab, balance=5_000.0, name="Card", snapshot_date="2026-09-01")
        self.assertEqual(asset_balance_history(db.list_line_items("assets")), [])


class TestDebtBalanceSnapshots(TempConfigTestCase):
    """Per-debt daily history behind the Assets & Debts page's debt paydown
    chart: Liabilities rows plus home mortgages (your share of the loan)."""

    def _liability(self, name, balance, **extra):
        return db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": name, "balance": balance, **extra})

    def test_capture_records_each_liability_and_skips_assets(self):
        card = self._liability("Card", 5_000)
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        capture_debt_balance_snapshots()
        rows = db.list_debt_balance_snapshots()
        self.assertEqual([(r["source"], r["row_id"], r["balance"], r["name"]) for r in rows],
                         [("liability", card, 5_000.0, "Card")])

    def test_a_mortgage_is_recorded_as_your_share_of_the_loan(self):
        home = db.add_line_item("real_estate", {
            "name": "Home", "current_value": 800_000, "loan_balance": 300_000, "ownership_pct": 50,
        })
        capture_debt_balance_snapshots()
        rows = db.list_debt_balance_snapshots("real_estate")
        self.assertEqual([(r["row_id"], r["balance"], r["category"]) for r in rows], [(home, 150_000.0, "Mortgage")])

    def test_a_property_with_no_loan_is_skipped_until_it_has_history(self):
        home = db.add_line_item("real_estate", {"name": "Paid off", "current_value": 500_000, "loan_balance": 0})
        capture_debt_balance_snapshots()
        self.assertEqual(db.list_debt_balance_snapshots("real_estate"), [])
        db.update_line_item("real_estate", home, {"loan_balance": 10_000})
        capture_debt_balance_snapshots()
        db.update_line_item("real_estate", home, {"loan_balance": 0})
        db.record_debt_balance_snapshot(source="real_estate", row_id=home, balance=10_000.0, snapshot_date="2026-01-01")
        capture_debt_balance_snapshots()  # paid off: the zero is recorded, not dropped
        zero = [r for r in db.list_debt_balance_snapshots("real_estate") if r["balance"] == 0.0]
        self.assertEqual(len(zero), 1)

    def test_capturing_twice_the_same_day_overwrites(self):
        card = self._liability("Card", 5_000)
        capture_debt_balance_snapshots()
        db.update_line_item("assets", card, {"balance": 4_000})
        capture_debt_balance_snapshots()
        rows = db.list_debt_balance_snapshots("liability")
        self.assertEqual([r["balance"] for r in rows], [4_000.0])

    def test_capture_net_worth_snapshot_also_captures_debts(self):
        self._liability("Card", 5_000)
        capture_net_worth_snapshot()
        self.assertEqual(len(db.list_debt_balance_snapshots()), 1)

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(ValueError):
            db.record_debt_balance_snapshot(source="bogus", row_id=1, balance=1.0)

    def test_history_lists_both_kinds_largest_first_with_distinct_ids(self):
        card = self._liability("Card", 5_000)
        home = db.add_line_item("real_estate", {"name": "Home", "current_value": 800_000, "loan_balance": 300_000})
        for d, v in (("2026-09-02", 4_500.0), ("2026-09-01", 5_000.0)):
            db.record_debt_balance_snapshot(source="liability", row_id=card, balance=v, name="Card", snapshot_date=d)
        db.record_debt_balance_snapshot(source="real_estate", row_id=home, balance=300_000.0, snapshot_date="2026-09-01")
        history = debt_balance_history(
            [r for r in db.list_line_items("assets") if r["kind"] == "liability"], db.list_line_items("real_estate"),
        )
        self.assertEqual([h["name"] for h in history], ["Home mortgage", "Card"])
        self.assertEqual(history[0]["id"], home + 1_000_000)
        self.assertEqual(history[0]["category"], "Mortgage")
        self.assertEqual(history[1]["id"], card)
        self.assertEqual(history[1]["points"], [("2026-09-01", 5_000.0), ("2026-09-02", 4_500.0)])

    def test_history_leaves_out_deleted_rows_and_rows_with_no_snapshots(self):
        card = self._liability("Card", 5_000)
        self._liability("No history", 100)
        db.record_debt_balance_snapshot(source="liability", row_id=card, balance=5_000.0, snapshot_date="2026-09-01")
        db.record_debt_balance_snapshot(source="liability", row_id=9999, balance=1.0, snapshot_date="2026-09-01")
        history = debt_balance_history([r for r in db.list_line_items("assets")], [])
        self.assertEqual([h["id"] for h in history], [card])

    def test_remap_moves_history_to_the_new_ids(self):
        db.record_debt_balance_snapshot(source="liability", row_id=1, balance=5.0, snapshot_date="2026-09-01")
        db.record_debt_balance_snapshot(source="liability", row_id=1, balance=4.0, snapshot_date="2026-09-02")
        db.record_debt_balance_snapshot(source="liability", row_id=7, balance=3.0, snapshot_date="2026-09-02")
        db.remap_debt_balance_snapshots("liability", {1: 7})
        rows = db.list_debt_balance_snapshots("liability")
        self.assertEqual(sorted((r["row_id"], r["snapshot_date"], r["balance"]) for r in rows),
                         [(7, "2026-09-01", 5.0), (7, "2026-09-02", 3.0)])
