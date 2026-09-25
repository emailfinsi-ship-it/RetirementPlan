import unittest

import openpyxl

from source.common import db
from source.reporting import excel_export
from tests.testing_utils import TempConfigTestCase


class TestExcelExport(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 40_000})
        db.add_line_item("real_estate", {"name": "Home", "current_value": 500_000, "loan_balance": 200_000})

    def test_export_writes_a_readable_workbook_with_expected_sheets(self):
        path = excel_export.export_current_state()
        self.assertTrue(path.exists())
        wb = openpyxl.load_workbook(str(path))
        self.assertEqual(
            set(wb.sheetnames),
            {
                "Summary", "Asset", "Expense", "Income", "Real Estate Analysis",
                "Linked Positions", "Linked Accounts", "Monte Carlo Simulation", "Monte Carlo Stress Test",
            },
        )

    def test_asset_sheet_contains_the_line_item(self):
        path = excel_export.export_current_state()
        wb = openpyxl.load_workbook(str(path))
        ws = wb["Asset"]
        names = [ws.cell(row=r, column=3).value for r in range(2, ws.max_row + 1)]
        self.assertIn("Fidelity", names)

    def test_export_records_meta(self):
        excel_export.export_current_state()
        self.assertIsNotNone(db.get_meta("last_export_at"))
        self.assertIsNotNone(db.get_meta("last_export_path"))

    def test_real_estate_sheet_has_annual_income_column(self):
        path = excel_export.export_current_state()
        wb = openpyxl.load_workbook(str(path))
        ws = wb["Real Estate Analysis"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        self.assertIn("Annual Income", headers)

    def test_real_estate_sheet_your_loan_share_reflects_ownership_pct(self):
        db.clear_section("real_estate")
        db.add_line_item("real_estate", {
            "name": "Moorpark", "current_value": 900_000, "loan_balance": 400_000, "ownership_pct": 50,
        })
        path = excel_export.export_current_state()
        wb = openpyxl.load_workbook(str(path))
        ws = wb["Real Estate Analysis"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        share_col = headers.index("Your Loan Share") + 1
        equity_col = headers.index("Equity") + 1
        row = next(r for r in range(2, ws.max_row + 1) if ws.cell(row=r, column=1).value == "Moorpark")
        self.assertEqual(ws.cell(row=row, column=share_col).value, 200_000)
        self.assertEqual(ws.cell(row=row, column=equity_col).value, 250_000)

    def test_asset_sheet_exports_live_balance_for_a_linked_row(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-1", "name": "401k", "official_name": "Fidelity 401k",
            "type": "investment", "subtype": "401k", "mask": "1234",
            "balances": {"current": 55_000.0, "available": None, "iso_currency_code": "USD"},
        })
        item_id = db.add_line_item("assets", {"kind": "asset", "name": "Linked 401k", "balance": 1})
        db.update_line_item("assets", item_id, {"linked_account_id": "acc-1"})
        path = excel_export.export_current_state()
        wb = openpyxl.load_workbook(str(path))
        ws = wb["Asset"]
        rows = {ws.cell(row=r, column=3).value: ws.cell(row=r, column=6).value for r in range(2, ws.max_row + 1)}
        self.assertEqual(rows["Linked 401k"], 55_000.0)

    def test_monte_carlo_band_written_when_result_supplied(self):
        result = {"band": [{"year": 2027, "p10": 1, "median": 2, "p90": 3}]}
        path = excel_export.export_current_state(monte_carlo_result=result)
        wb = openpyxl.load_workbook(str(path))
        ws = wb["Monte Carlo Simulation"]
        values = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
        self.assertIn(2027, values)

    def test_monte_carlo_sheet_self_computes_when_no_result_is_supplied(self):
        # Regression test: /api/export used to call export_current_state()
        # with no monte_carlo_result at all, so the Monte Carlo Simulation
        # sheet's band table silently never had any data in it. It should
        # now run the simulations itself.
        path = excel_export.export_current_state()
        wb = openpyxl.load_workbook(str(path))
        ws = wb["Monte Carlo Simulation"]
        values = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
        self.assertIn("Gaussian simulation (Expected return / Volatility)", values)
        self.assertIn("S&P 500 historical-returns simulation", values)

    def test_summary_sheet_includes_net_liquid_asset_and_category_subtotals(self):
        path = excel_export.export_current_state()
        wb = openpyxl.load_workbook(str(path))
        ws = wb["Summary"]
        labels = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
        self.assertIn("Net Liquid Asset (Monte Carlo starting balance)", labels)
        self.assertIn("401k", labels)  # asset category subtotal row

    def test_linked_positions_sheet_contains_synced_holdings(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-1", "name": "Brokerage", "official_name": "Fidelity Brokerage",
            "type": "investment", "subtype": "brokerage", "mask": "1234",
            "balances": {"current": 10_000.0, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_holding(item_key="fidelity", holding={
            "account_id": "acc-1", "security_id": "sec-1", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc.", "security_type": "equity", "quantity": 10,
            "institution_price": 200.0, "institution_value": 2_000.0, "cost_basis": 1_500.0,
        })
        path = excel_export.export_current_state()
        wb = openpyxl.load_workbook(str(path))
        ws = wb["Linked Positions"]
        names = [ws.cell(row=r, column=3).value for r in range(2, ws.max_row + 1)]
        self.assertIn("Apple Inc.", names)

    def test_linked_accounts_sheet_contains_synced_account_balance(self):
        db.upsert_plaid_item(
            item_key="chase", plaid_item_id="item-2", institution_id="ins_2",
            institution_name="Chase", products=["auth"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="chase", account={
            "account_id": "acc-2", "name": "Checking", "official_name": "Chase Checking",
            "type": "depository", "subtype": "checking", "mask": "5678",
            "balances": {"current": 3_000.0, "available": 3_000.0, "iso_currency_code": "USD"},
        })
        path = excel_export.export_current_state()
        wb = openpyxl.load_workbook(str(path))
        ws = wb["Linked Accounts"]
        # Column 1 is the real institution name (the parent Item's
        # institution_name, "Chase" here) -- not the account's own Plaid
        # name ("Checking"), which this sheet doesn't otherwise surface.
        balances = {
            ws.cell(row=r, column=1).value: ws.cell(row=r, column=4).value for r in range(2, ws.max_row + 1)
        }
        self.assertEqual(balances["Chase"], 3_000.0)

    def test_stress_test_sheet_has_expense_income_drawdown_and_scenario_columns(self):
        # export_current_state() with no monte_carlo_result self-computes
        # via _default_monte_carlo_result(), which passes pools= the same
        # way the live Monte Carlo tab does -- so this sheet is always in
        # per-scenario-tax mode (retirement_pools is never None), not the
        # legacy shared-columns layout.
        path = excel_export.export_current_state()
        wb = openpyxl.load_workbook(str(path))
        ws = wb["Monte Carlo Stress Test"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        self.assertEqual(headers[:4], ["Year", "Total Expense", "Total Income", "Yearly Drawdown"])
        self.assertNotIn("Tax (Fed+CA)", headers)
        self.assertIn("Great Depression (1929) Return", headers)
        self.assertIn("Great Depression (1929) Tax", headers)
        self.assertIn("Great Depression (1929) Withdrawal", headers)
        self.assertIn("Great Depression (1929) Balance", headers)

    def test_stress_test_sheet_tax_column_reflects_the_apply_drawdown_tax_assumption(self):
        # Drawdown tax is on by default (source.common.db.DEFAULT_
        # ASSUMPTIONS) -- with a real withdrawal need, the first
        # scenario's first-year Tax cell should be a positive number and
        # Withdrawal should be Yearly Drawdown + Tax, not just Yearly
        # Drawdown. (Per-scenario mode -- see the test above -- so this
        # reads the first scenario's own Tax/Withdrawal columns, not a
        # shared pair.)
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 1_000_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 100_000, "start_year": None, "end_year": None})
        try:
            path = excel_export.export_current_state()
            wb = openpyxl.load_workbook(str(path))
            ws = wb["Monte Carlo Stress Test"]
            headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
            tax_col = headers.index("Great Depression (1929) Tax") + 1
            withdrawal_col = headers.index("Great Depression (1929) Withdrawal") + 1
            drawdown_col = headers.index("Yearly Drawdown") + 1
            tax = ws.cell(row=2, column=tax_col).value
            drawdown = ws.cell(row=2, column=drawdown_col).value
            withdrawal = ws.cell(row=2, column=withdrawal_col).value
            self.assertGreater(tax, 0.0)
            self.assertAlmostEqual(withdrawal, drawdown + tax, places=6)
        finally:
            db.clear_section("assets")
            db.clear_section("expenses")

        # And with the assumption turned off, the Tax column goes to
        # zero and Withdrawal collapses back to Yearly Drawdown.
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 1_000_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 100_000, "start_year": None, "end_year": None})
        db.set_assumptions({"apply_drawdown_tax": "0"})
        try:
            path = excel_export.export_current_state()
            wb = openpyxl.load_workbook(str(path))
            ws = wb["Monte Carlo Stress Test"]
            headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
            tax_col = headers.index("Great Depression (1929) Tax") + 1
            withdrawal_col = headers.index("Great Depression (1929) Withdrawal") + 1
            drawdown_col = headers.index("Yearly Drawdown") + 1
            tax = ws.cell(row=2, column=tax_col).value
            drawdown = ws.cell(row=2, column=drawdown_col).value
            withdrawal = ws.cell(row=2, column=withdrawal_col).value
            self.assertEqual(tax, 0.0)
            self.assertEqual(withdrawal, drawdown)
        finally:
            db.clear_section("assets")
            db.clear_section("expenses")
            db.set_assumptions({"apply_drawdown_tax": "1"})

    def test_stress_test_sheet_legacy_shared_columns_when_pools_not_supplied(self):
        # A caller that still hands in its own pools=None result (an
        # older test, or a future non-pools caller) keeps getting the
        # original shared Tax/Total Withdrawal layout -- this program
        # never drops support for that shape, only stops using it by
        # default.
        from source.reporting.monte_carlo import run_historical_stress_test

        stress_result = run_historical_stress_test(
            starting_balance=1_000_000,
            expenses=[{"name": "Baseline", "annual_amount": 100_000, "start_year": None, "end_year": None}],
            income=[],
            assumptions=db.get_assumptions(),
        )
        self.assertFalse(stress_result["per_scenario_tax"])
        path = excel_export.export_current_state(monte_carlo_result={"stress_test": stress_result})
        wb = openpyxl.load_workbook(str(path))
        ws = wb["Monte Carlo Stress Test"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, ws.max_column + 1)]
        self.assertEqual(
            headers[:6],
            ["Year", "Total Expense", "Total Income", "Yearly Drawdown", "Tax (Fed+CA)", "Total Withdrawal"],
        )
        self.assertIn("Great Depression (1929) Return", headers)
        self.assertIn("Great Depression (1929) Balance", headers)
        self.assertNotIn("Great Depression (1929) Tax", headers)

    def test_default_monte_carlo_result_passes_pools_matching_the_live_tab(self):
        # Regression test for the export-vs-tab divergence this was
        # fixed to close: _default_monte_carlo_result() must hand the
        # same retirement_pools split to the simulations that the Monte
        # Carlo tab itself uses (source.webapp.pages.monte_carlo_page.
        # _render_monte_carlo_page), not the legacy pools=None mode.
        from source.reporting.aggregate import build_summary

        summary = build_summary()
        result = excel_export._default_monte_carlo_result(summary)
        self.assertTrue(result["stress_test"]["per_scenario_tax"])
        self.assertTrue(result["gaussian"].get("pools"))
        self.assertTrue(result["sp500_bootstrap"].get("pools"))


if __name__ == "__main__":
    unittest.main()
