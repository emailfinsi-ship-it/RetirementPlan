"""Linking an Income/Expense line to a real (synced) category, plus the
redesigned Income/Expense page layout (Income first, Add buttons on top)."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from source.common import db
from source.reporting import real_link
from tests.test_dashboard import DashboardTestCase


def txn(i, amount, cat, income=False, days_ago=10):
    return {"transaction_id": str(i), "amount": amount, "category": cat, "is_real_income": income,
            "excluded_from_expense": False, "date": (date.today() - timedelta(days=days_ago)).isoformat()}


class TestRealLinkMath(unittest.TestCase):
    def test_categories_split_expense_and_income(self):
        cats = real_link.real_categories([txn(1, 50, "Food"), txn(2, -900, "Income", income=True)])
        self.assertEqual(cats, {"expenses": ["Food"], "income": ["Income"]})

    def test_twelve_months_sums_and_annualises_short_history(self):
        full = [txn(i, 100, "Food", days_ago=i * 30) for i in range(1, 13)]
        a = real_link.actual_last_12_months(full, "expenses", "Food")
        self.assertEqual(a["months"], 12)
        self.assertAlmostEqual(a["annual"], 1200.0)
        short = [txn(1, 100, "Food", days_ago=65), txn(2, 100, "Food", days_ago=35), txn(3, 100, "Food", days_ago=5)]
        a = real_link.actual_last_12_months(short, "expenses", "Food")
        self.assertEqual(a["months"], 2)
        self.assertAlmostEqual(a["annual"], 300 * 12 / 2)

    def test_income_uses_positive_amounts_and_no_match_is_none(self):
        rows = [txn(1, -1000, "Income", income=True, days_ago=20)]
        self.assertAlmostEqual(real_link.actual_last_12_months(rows, "income", "Income")["annual"], 12000.0)
        self.assertIsNone(real_link.actual_last_12_months(rows, "expenses", "Income"))
        self.assertIsNone(real_link.actual_last_12_months(rows, "income", ""))


class TestIncomeExpensePage(DashboardTestCase):
    def tearDown(self):
        db.clear_section("expenses")
        db.clear_section("income")

    def test_income_first_with_add_buttons_in_each_header(self):
        db.add_line_item("income", {"name": "Salary", "category": "Salary", "annual_amount": 100_000})
        db.add_line_item("expenses", {"name": "Rent", "category": "Fixed", "annual_amount": 30_000})
        body = self._get("/expense.html").read().decode("utf-8")
        self.assertLess(body.index("<h2>Income</h2>"), body.index("<h2>Expenses</h2>"))
        self.assertLess(body.index("+ Add income"), body.index("<table", body.index("<h2>Income</h2>")))
        self.assertLess(body.index("+ Add expense"), body.index("<table", body.index("<h2>Expenses</h2>")))
        self.assertIn("Link to real income", body)
        self.assertIn("Link to real expense", body)
        self.assertIn("<colgroup>", body)

    def test_delete_button_sits_in_each_card_header(self):
        db.add_line_item("income", {"name": "Salary", "annual_amount": 100_000})
        db.add_line_item("expenses", {"name": "Rent", "annual_amount": 30_000})
        body = self._get("/expense.html").read().decode("utf-8")
        for section in ("income", "expenses"):
            head = body[body.index(f'id="{section}-card"'):]
            head = head[:head.index("<table")]
            self.assertIn(f"deleteSelectedRows('{section}')", head)
            self.assertIn("+ Add", head)
        self.assertIn("function refreshCardDeleteButtons", body)

    def test_link_a_row_and_see_actual(self):
        db.upsert_plaid_item(item_key="rl", plaid_item_id="p", institution_id="i", institution_name="Bank",
                             products=["transactions"], environment="sandbox", linked_at="now")
        db.upsert_plaid_account(item_key="rl", account={"account_id": "a1", "name": "Checking", "type": "depository",
                                                        "subtype": "checking", "balances": {"current": 10}})
        try:
            for i in range(1, 13):
                db.upsert_plaid_transaction(item_key="rl", transaction={
                    "transaction_id": f"t{i}", "account_id": "a1",
                    "date": (date.today() - timedelta(days=i * 28)).isoformat(), "amount": 500.0, "name": "Mortgage",
                    "category": "House-Loan", "excluded_from_expense": False,
                    "plaid_category_primary": "LOAN_PAYMENTS", "plaid_category_detailed": "x"})
            item_id = db.add_line_item("expenses", {"name": "Mortgage", "category": "Fixed", "annual_amount": 5_000})
            body = self._get("/expense.html").read().decode("utf-8")
            self.assertIn('<option value="House-Loan">', body)
            self.assertNotIn("Real: <strong>", body)
            status, _ = self._post("/api/line-item/update", {"section": "expenses", "id": item_id,
                                                             "fields": {"linked_category": "House-Loan"}})
            self.assertEqual(status, 200)
            body = self._get("/expense.html").read().decode("utf-8")
            self.assertRegex(body, r"Real: <strong>\$6,\d{3}</strong>/yr")
            self.assertIn("over the plan", body)
            self.assertIn(">Use</button>", body)
        finally:
            db.delete_plaid_item("rl")


if __name__ == "__main__":
    unittest.main()
