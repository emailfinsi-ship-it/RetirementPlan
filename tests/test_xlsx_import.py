"""Tests for source.importer.xlsx_import, against the current workbook
layout (Summary & Assumptions, Real Estate).

Building a *real* encrypted .xlsx in a test is more trouble than it's
worth (msoffcrypto-tool is a decrypt-only library), so encryption/password
handling is tested against a small stand-in for msoffcrypto.OfficeFile
(_FakeOfficeFile) that mimics its is_encrypted/load_key/decrypt contract
without touching real crypto -- the actual decrypt path is exercised for
real every time a user imports their real password-protected workbook;
this only needs to prove xlsx_import.py calls that contract correctly and
handles a wrong password / no password gracefully.
"""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import openpyxl

from source.common import db
from source.importer import xlsx_import
from tests.testing_utils import TempConfigTestCase


def _build_fixture_workbook(*, include_monte_carlo_sheet: bool = True) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sw = wb.create_sheet("Summary & Assumptions")
    sw["A1"] = "Retirement Financial Plan — Summary & Assumptions"

    sw["A3"] = "401K / IRA"
    sw["A4"], sw["B4"] = "Account", "Balance"
    sw["A5"], sw["B5"] = "Fidelity 401k", 250_000
    sw["A6"], sw["B6"] = "Vanguard IRA", 90_000
    sw["A7"], sw["B7"] = "Total 401k/IRA", 340_000

    sw["A9"] = "Liquid Investments"
    sw["A10"], sw["B10"] = "Account", "Balance"
    sw["A11"], sw["B11"] = "Brokerage", 150_000
    sw["A12"], sw["B12"] = "Total Liquid Investments", 150_000

    sw["A14"] = "Loans / Committed"
    sw["A15"], sw["B15"] = "Item", "Balance"
    sw["A16"], sw["B16"] = "HELOC", 30_000
    sw["A17"], sw["B17"] = "Loan payoff BEFORE retirement?", "YES"  # non-numeric -- skipped
    sw["A18"], sw["B18"] = "Total Loans", 30_000

    sw["A20"] = "Annual Expense Need (2026 basis)"
    sw["A21"], sw["B21"] = "Category", "Annual"
    sw["A22"], sw["B22"] = "Fixed cost (house + property tax)", 197_800
    sw["A23"], sw["B23"] = "Variable cost (utility, medical, food, etc.)", 104_400
    sw["A24"], sw["B24"] = "Total Annual Expense Need (2026 $)", 302_200

    sw["A26"] = "Retirement Income Assumptions"
    sw["A27"], sw["B27"] = "Annual rental income (net)", 103_000
    sw["A28"], sw["B28"] = "Social Security (monthly, per person)", 3_500
    sw["A29"], sw["B29"] = "Social Security (annual)", 42_000
    sw["A30"], sw["B30"] = "SS start age", 65

    sw["A32"] = "Key Modeling Assumptions"
    sw["A34"], sw["B34"] = "Birth year", 1970
    sw["A35"], sw["B35"] = "Retirement year", 2028
    sw["A36"], sw["B36"] = "Retirement age", 58
    sw["A37"], sw["B37"] = "Portfolio growth rate (nominal, blended)", 0.07
    sw["A38"], sw["B38"] = "Inflation rate (expenses)", 0.03
    sw["A39"], sw["B39"] = "Plan horizon — end age", 90

    re_ws = wb.create_sheet("Real Estate")
    re_ws["A3"] = "Asset"
    re_ws["B3"], re_ws["C3"], re_ws["D3"] = "Original Price", "Current Value", "Ownership %"
    re_ws["A4"] = "Moorpark"
    re_ws["B4"], re_ws["C4"], re_ws["D4"], re_ws["F4"] = 1_290_000, 3_000_000, 100, 501_000
    re_ws["A5"] = "Muscat Dr"
    re_ws["B5"], re_ws["C5"], re_ws["D5"], re_ws["F5"] = 980_000, 1_350_000, 0.5, 625_000  # fraction ownership
    re_ws["A6"] = "Total"
    re_ws["C6"] = 4_350_000  # should be skipped (name starts with "Total")

    if include_monte_carlo_sheet:
        mc = wb.create_sheet("Monte Carlo Simulation")
        mc["A5"], mc["B5"] = "Number of trials", 2000
        mc["A7"], mc["B7"] = "Return volatility (std dev)", 0.15

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class _FakeOfficeFile:
    """Stand-in for msoffcrypto.OfficeFile: is_encrypted()/load_key()/
    decrypt() with a fixed correct_password, nothing else."""

    def __init__(self, fh, *, correct_password: str, plaintext_bytes: bytes):
        self._plaintext = plaintext_bytes
        self._correct_password = correct_password
        self._key_loaded_ok = False

    def is_encrypted(self):
        return True

    def load_key(self, password=None):
        if password != self._correct_password:
            raise Exception("Invalid password")
        self._key_loaded_ok = True

    def decrypt(self, buf):
        if not self._key_loaded_ok:
            raise Exception("decrypt() called before a valid load_key()")
        buf.write(self._plaintext)


class TestLoadWorkbookUnencrypted(TempConfigTestCase):
    def test_loads_plain_workbook(self):
        path = self._write_fixture()
        wb = xlsx_import.load_workbook(path)
        self.assertIn("Real Estate", wb.sheetnames)

    def test_missing_file_raises(self):
        with self.assertRaises(xlsx_import.ImportError_):
            xlsx_import.load_workbook(self.data_dir / "nope.xlsx")

    def test_missing_expected_sheet_raises(self):
        import openpyxl as _openpyxl

        wb = _openpyxl.Workbook()
        path = self.data_dir / "incomplete.xlsx"
        wb.save(str(path))
        with self.assertRaises(xlsx_import.ImportError_):
            xlsx_import.load_workbook(path)

    def setUp(self):
        super().setUp()
        from source.common import config

        self.data_dir = config.DATA_DIR

    def _write_fixture(self, **kwargs):
        path = self.data_dir / "plan.xlsx"
        path.write_bytes(_build_fixture_workbook(**kwargs))
        return path


class TestLoadWorkbookEncrypted(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        from source.common import config

        self.path = config.DATA_DIR / "plan.xlsx"
        self.path.write_bytes(b"not a real encrypted file, the fake OfficeFile ignores this")
        self._plaintext = _build_fixture_workbook()

    def _patched_office_file(self):
        plaintext = self._plaintext

        def factory(fh):
            return _FakeOfficeFile(fh, correct_password="secret123", plaintext_bytes=plaintext)

        return patch.object(xlsx_import.msoffcrypto, "OfficeFile", side_effect=factory)

    def test_correct_password_decrypts(self):
        with self._patched_office_file():
            wb = xlsx_import.load_workbook(self.path, password="secret123")
        self.assertIn("Real Estate", wb.sheetnames)

    def test_wrong_password_raises_friendly_error(self):
        with self._patched_office_file():
            with self.assertRaises(xlsx_import.ImportError_) as ctx:
                xlsx_import.load_workbook(self.path, password="wrong")
        self.assertIn("password", str(ctx.exception).lower())

    def test_no_password_raises_friendly_error(self):
        with self._patched_office_file():
            with self.assertRaises(xlsx_import.ImportError_) as ctx:
                xlsx_import.load_workbook(self.path)
        self.assertIn("password-protected", str(ctx.exception))


class TestImportFromXlsx(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        from source.common import config

        self.path = config.DATA_DIR / "plan.xlsx"
        self.path.write_bytes(_build_fixture_workbook())

    def test_reimport_carries_each_assets_balance_history_to_its_new_id(self):
        xlsx_import.import_from_xlsx(self.path)
        old = {r["name"]: r["id"] for r in db.list_line_items("assets") if r["kind"] == "asset"}
        db.record_asset_balance_snapshot(
            asset_id=old["Fidelity 401k"], balance=240_000, name="Fidelity 401k", category="401k",
            snapshot_date="2026-01-05",
        )

        xlsx_import.import_from_xlsx(self.path)

        new = {r["name"]: r["id"] for r in db.list_line_items("assets") if r["kind"] == "asset"}
        self.assertNotEqual(new["Fidelity 401k"], old["Fidelity 401k"])
        history = db.list_asset_balance_snapshots(new["Fidelity 401k"])
        self.assertEqual([(h["snapshot_date"], h["balance"]) for h in history], [("2026-01-05", 240_000)])
        self.assertEqual(db.list_asset_balance_snapshots(old["Fidelity 401k"]), [])

    def test_reimport_keeps_a_loan_end_year_typed_on_the_real_estate_tab(self):
        xlsx_import.import_from_xlsx(self.path)
        row = next(r for r in db.list_line_items("real_estate") if r["name"] == "Moorpark")
        db.update_line_item("real_estate", row["id"], {"loan_end_year": "2051"})

        xlsx_import.import_from_xlsx(self.path)

        rows = {r["name"]: r for r in db.list_line_items("real_estate")}
        self.assertEqual(rows["Moorpark"]["loan_end_year"], 2051)
        self.assertIsNone(rows["Muscat Dr"]["loan_end_year"])

    def test_imports_real_estate_rows_and_skips_total(self):
        xlsx_import.import_from_xlsx(self.path)
        rows = db.list_line_items("real_estate")
        names = {r["name"] for r in rows}
        self.assertEqual(names, {"Moorpark", "Muscat Dr"})

    def test_ownership_pct_fraction_and_percent_both_normalize(self):
        xlsx_import.import_from_xlsx(self.path)
        rows = {r["name"]: r for r in db.list_line_items("real_estate")}
        self.assertEqual(rows["Moorpark"]["ownership_pct"], 100.0)
        self.assertEqual(rows["Muscat Dr"]["ownership_pct"], 50.0)

    def test_real_estate_purchase_price_and_loan_balance(self):
        xlsx_import.import_from_xlsx(self.path)
        rows = {r["name"]: r for r in db.list_line_items("real_estate")}
        self.assertEqual(rows["Moorpark"]["purchase_price"], 1_290_000)
        self.assertEqual(rows["Moorpark"]["loan_balance"], 501_000)

    def test_imports_401k_and_liquid_asset_accounts(self):
        xlsx_import.import_from_xlsx(self.path)
        rows = {r["name"]: r for r in db.list_line_items("assets") if r["kind"] == "asset"}
        self.assertEqual(rows["Fidelity 401k"]["balance"], 250_000)
        self.assertEqual(rows["Fidelity 401k"]["category"], "401k")
        self.assertEqual(rows["Vanguard IRA"]["category"], "401k")
        self.assertEqual(rows["Brokerage"]["category"], "Liquid")
        self.assertEqual(rows["Brokerage"]["balance"], 150_000)

    def test_asset_block_totals_and_non_numeric_rows_are_not_imported(self):
        xlsx_import.import_from_xlsx(self.path)
        names = {r["name"] for r in db.list_line_items("assets")}
        self.assertNotIn("Total 401k/IRA", names)
        self.assertNotIn("Total Liquid Investments", names)
        self.assertNotIn("Loan payoff BEFORE retirement?", names)

    def test_imports_loan_as_liability(self):
        xlsx_import.import_from_xlsx(self.path)
        liabilities = [r for r in db.list_line_items("assets") if r["kind"] == "liability"]
        self.assertEqual(len(liabilities), 1)
        self.assertEqual(liabilities[0]["name"], "HELOC")
        self.assertEqual(liabilities[0]["balance"], 30_000)

    def test_imports_fixed_and_variable_expense_with_inflation(self):
        xlsx_import.import_from_xlsx(self.path)
        rows = {r["name"]: r for r in db.list_line_items("expenses")}
        fixed = rows["Fixed cost (house + property tax)"]
        self.assertEqual(fixed["annual_amount"], 197_800)
        self.assertEqual(fixed["base_year"], 2026)
        self.assertEqual(fixed["inflates"], 1)
        variable = rows["Variable cost (utility, medical, food, etc.)"]
        self.assertEqual(variable["annual_amount"], 104_400)
        self.assertEqual(variable["base_year"], 2026)

    def test_imports_rental_and_social_security_income(self):
        xlsx_import.import_from_xlsx(self.path)
        rows = {r["name"]: r for r in db.list_line_items("income")}
        rental = rows["Rental income"]
        self.assertEqual(rental["annual_amount"], 103_000)
        self.assertEqual(rental["base_year"], 2026)
        self.assertEqual(rental["inflates"], 1)
        ss = rows["Social Security"]
        self.assertEqual(ss["annual_amount"], 42_000)
        self.assertEqual(ss["inflates"], 0)
        # Birth year 1970 + SS start age 65 = 2035.
        self.assertEqual(ss["start_year"], 2035)

    def test_imports_key_modeling_assumptions(self):
        xlsx_import.import_from_xlsx(self.path)
        assumptions = db.get_assumptions()
        self.assertEqual(float(assumptions["expected_return"]), 0.07)
        self.assertEqual(float(assumptions["inflation_rate"]), 0.03)
        # Retirement year becomes the simulation's starting year.
        self.assertEqual(int(float(assumptions["current_year"])), 2028)
        # Plan horizon end age 90 - retirement age 58 = 32 years.
        self.assertEqual(int(float(assumptions["plan_horizon_years"])), 32)

    def test_imports_extra_assumptions_from_monte_carlo_sheet_when_present(self):
        xlsx_import.import_from_xlsx(self.path)
        assumptions = db.get_assumptions()
        self.assertEqual(float(assumptions["return_volatility"]), 0.15)
        self.assertEqual(int(float(assumptions["iterations"])), 2000)

    def test_missing_monte_carlo_sheet_does_not_fail_import(self):
        self.path.write_bytes(_build_fixture_workbook(include_monte_carlo_sheet=False))
        summary = xlsx_import.import_from_xlsx(self.path)
        self.assertNotIn("return_volatility", summary["assumptions_imported"])
        self.assertEqual(summary["real_estate_count"], 2)  # core import still succeeds

    def test_records_import_meta(self):
        xlsx_import.import_from_xlsx(self.path)
        self.assertIsNotNone(db.get_meta("last_import_at"))
        self.assertEqual(db.get_meta("last_import_source"), str(self.path))

    def test_summary_counts(self):
        summary = xlsx_import.import_from_xlsx(self.path)
        self.assertEqual(summary["real_estate_count"], 2)
        self.assertEqual(summary["asset_count"], 4)  # 2 401k/IRA + 1 liquid account + 1 loan
        self.assertEqual(summary["expense_count"], 2)
        self.assertEqual(summary["income_count"], 2)

    def test_reimport_clears_only_previously_imported_rows(self):
        db.add_line_item("assets", {"kind": "asset", "name": "Manual cash", "balance": 5_000, "source": "manual"})
        xlsx_import.import_from_xlsx(self.path)
        xlsx_import.import_from_xlsx(self.path)  # re-run
        rows = db.list_line_items("assets")
        names = [r["name"] for r in rows]
        self.assertEqual(names.count("Manual cash"), 1)
        self.assertEqual(names.count("Fidelity 401k"), 1)

    def test_reimport_does_not_duplicate_income_rows(self):
        xlsx_import.import_from_xlsx(self.path)
        xlsx_import.import_from_xlsx(self.path)
        rows = db.list_line_items("income")
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
