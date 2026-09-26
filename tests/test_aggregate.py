import unittest

from source.common import db
from source.reporting.aggregate import (
    build_summary,
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
        # Net Liquid Asset = rows checked "In Monte Carlo?" only, net of
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


if __name__ == "__main__":
    unittest.main()
