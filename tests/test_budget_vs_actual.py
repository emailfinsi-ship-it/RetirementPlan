import unittest
from datetime import date as real_date
from unittest.mock import patch

from source.common import db
from source.webapp.pages.budget_vs_actual import (
    _actual_expense_and_income_by_month,
    _render_budget_vs_actual_page,
    _variance_cell,
)
from tests.testing_utils import TempConfigTestCase


def _txn(transaction_id, *, date, amount, category, excluded=False, account_id="acc-1"):
    return {
        "transaction_id": transaction_id, "account_id": account_id, "date": date, "amount": amount,
        "iso_currency_code": "USD", "name": "x", "merchant_name": "x", "pending": False,
        "category": category, "category_edited_by_user": False,
        "excluded_from_expense": excluded, "excluded_edited_by_user": False,
        "institution": "Bank", "account_name": "Checking", "account_type": "Checking",
    }


class TestVarianceCell(unittest.TestCase):
    def test_under_budget_is_good_for_spend(self):
        self.assertIn("status-ok", _variance_cell(80, 100))

    def test_over_budget_is_bad_for_spend(self):
        html = _variance_cell(120, 100)
        self.assertIn("status-warn", html)
        self.assertIn("+$20.00", html)

    def test_over_plan_is_good_for_income(self):
        self.assertIn("status-ok", _variance_cell(120, 100, higher_is_better=True))

    def test_under_plan_is_bad_for_income(self):
        self.assertIn("status-warn", _variance_cell(80, 100, higher_is_better=True))


class TestActualExpenseAndIncomeByMonth(unittest.TestCase):
    def test_splits_income_category_from_everything_else(self):
        transactions = [
            _txn("t1", date="2026-09-05", amount=50.0, category="Food"),
            _txn("t2", date="2026-09-10", amount=-2000.0, category="Income"),
        ]
        expense, income = _actual_expense_and_income_by_month(transactions)
        self.assertEqual(expense["2026-09"], 50.0)
        self.assertEqual(income["2026-09"], 2000.0)

    def test_excluded_transactions_are_left_out_of_both(self):
        transactions = [_txn("t1", date="2026-09-05", amount=500.0, category="Transfer", excluded=True)]
        expense, income = _actual_expense_and_income_by_month(transactions)
        self.assertEqual(expense, {})
        self.assertEqual(income, {})

    def test_sums_multiple_transactions_in_the_same_month(self):
        transactions = [
            _txn("t1", date="2026-09-05", amount=50.0, category="Food"),
            _txn("t2", date="2026-09-20", amount=30.0, category="Food"),
        ]
        expense, _ = _actual_expense_and_income_by_month(transactions)
        self.assertEqual(expense["2026-09"], 80.0)


class TestRenderBudgetVsActualPage(TempConfigTestCase):
    def _patched_today(self, value: real_date):
        patcher = patch("source.webapp.pages.budget_vs_actual.date")
        mock_date = patcher.start()
        mock_date.today.return_value = value
        mock_date.side_effect = lambda *a, **kw: real_date(*a, **kw)
        self.addCleanup(patcher.stop)

    def test_no_data_renders_without_error(self):
        body = _render_budget_vs_actual_page()
        self.assertIn("Budget vs Actual", body)

    def test_this_years_planned_totals_use_the_expense_income_assumptions(self):
        self._patched_today(real_date(2026, 6, 15))
        db.add_line_item("expenses", {"name": "Groceries", "category": "Fixed", "annual_amount": 12_000})
        db.add_line_item("income", {"name": "Pension", "category": "Pension", "annual_amount": 24_000})
        body = _render_budget_vs_actual_page()
        self.assertIn("2026 expense budget", body)
        self.assertIn("$12,000.00", body)
        self.assertIn("2026 income plan", body)
        self.assertIn("$24,000.00", body)

    def test_actual_spend_and_projection_reflect_synced_transactions(self):
        self._patched_today(real_date(2026, 7, 1))  # day 182 of a 365-day year
        db.add_line_item("expenses", {"name": "Groceries", "category": "Fixed", "annual_amount": 36_500})
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name="Bank",
            products=["transactions"], environment="sandbox", linked_at="2026-01-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="k", account={"account_id": "acc-1", "name": "Checking", "balances": {"current": 0}})
        db.upsert_plaid_transaction(item_key="k", transaction={
            "transaction_id": "t1", "account_id": "acc-1", "date": "2026-03-01", "amount": 18_200.0,
            "iso_currency_code": "USD", "name": "Big spend", "merchant_name": "Big spend", "pending": False,
            "plaid_category_primary": None, "plaid_category_detailed": None,
            "category": "Shopping", "excluded_from_expense": False,
        })
        body = _render_budget_vs_actual_page()
        self.assertIn("$18,200.00", body)  # actual spend so far

    def test_monthly_table_shows_each_months_flat_budget_and_actual(self):
        self._patched_today(real_date(2026, 9, 15))
        db.add_line_item("expenses", {"name": "Groceries", "category": "Fixed", "annual_amount": 12_000})
        body = _render_budget_vs_actual_page()
        # Flat monthly budget = 12000 / 12 = 1000.
        self.assertIn("$1,000.00", body)
        self.assertIn("2026-09", body)

    def test_page_explains_it_is_a_totals_level_comparison(self):
        body = _render_budget_vs_actual_page()
        self.assertIn("TOTALS", body)


if __name__ == "__main__":
    unittest.main()
