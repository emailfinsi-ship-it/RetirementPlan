import csv
import unittest

from source.collector import export_account_files
from source.common import config, db
from tests.testing_utils import TempConfigTestCase


class TestAccountBalanceRecords(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name="Chase",
            products=["investments"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )

    def test_liability_balance_is_signed_negative(self):
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-credit", "name": "Chase", "type": "credit", "subtype": "credit card",
            "mask": "9999", "balances": {"current": 500.0},
        })
        records = export_account_files.account_balance_records(downloaded_at="2026-09-21 10:00:00")
        self.assertEqual(records[0][2], "-500.00")

    def test_asset_balance_is_unsigned(self):
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-checking", "name": "Chase", "type": "depository", "subtype": "checking",
            "mask": "1234", "balances": {"current": 500.0},
        })
        records = export_account_files.account_balance_records(downloaded_at="2026-09-21 10:00:00")
        self.assertEqual(records[0][2], "500.00")

    def test_write_account_balances_creates_csv_and_html(self):
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-checking", "name": "Chase", "type": "depository", "subtype": "checking",
            "mask": "1234", "balances": {"current": 500.0},
        })
        export_account_files.write_account_balances(downloaded_at="2026-09-21 10:00:00")

        csv_path = config.account_balances_csv_path()
        self.assertTrue(csv_path.exists())
        with csv_path.open(encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], list(export_account_files.ACCOUNT_CSV_COLUMNS))
        self.assertEqual(rows[1][0], "Chase")

        html_path = config.account_balances_html_path()
        self.assertTrue(html_path.exists())
        self.assertIn("Chase", html_path.read_text(encoding="utf-8"))

    def test_write_with_no_accounts_still_produces_valid_files(self):
        export_account_files.write_account_balances(downloaded_at="2026-09-21 10:00:00")
        self.assertTrue(config.account_balances_csv_path().exists())
        self.assertIn("No linked accounts", config.account_balances_html_path().read_text(encoding="utf-8"))


class TestPortfolioPositionRecords(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name="Fidelity",
            products=["investments"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Fidelity", "official_name": "Fidelity Brokerage",
            "type": "investment", "subtype": "brokerage", "mask": "5678", "balances": {"current": 1500.0},
        })

    def test_write_portfolio_positions_creates_csv_and_html(self):
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 10,
            "institution_price": 150, "institution_value": 1500, "cost_basis": 1000,
        })
        export_account_files.write_portfolio_positions(downloaded_at="2026-09-21 10:00:00")

        csv_path = config.portfolio_positions_csv_path()
        self.assertTrue(csv_path.exists())
        with csv_path.open(encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], list(export_account_files.POSITION_CSV_COLUMNS))
        self.assertEqual(rows[1][3], "AAPL")

        html_path = config.portfolio_positions_html_path()
        self.assertIn("AAPL", html_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
