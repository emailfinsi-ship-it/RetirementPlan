import unittest

from source.common import db
from tests.testing_utils import TempConfigTestCase


class TestLineItemCrud(TempConfigTestCase):
    def test_add_and_list_assets(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 1000})
        rows = db.list_line_items("assets")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Fidelity")
        self.assertEqual(rows[0]["balance"], 1000)
        self.assertEqual(rows[0]["source"], "manual")

    def test_add_requires_a_name(self):
        with self.assertRaises(ValueError):
            db.add_line_item("assets", {"balance": 100})

    def test_add_rejects_blank_name(self):
        with self.assertRaises(ValueError):
            db.add_line_item("expenses", {"name": "   ", "annual_amount": 100})

    def test_unknown_section_rejected(self):
        with self.assertRaises(ValueError):
            db.add_line_item("bogus", {"name": "x"})

    def test_update_line_item(self):
        item_id = db.add_line_item("real_estate", {"name": "Condo", "current_value": 100})
        ok = db.update_line_item("real_estate", item_id, {"current_value": 200})
        self.assertTrue(ok)
        row = db.get_line_item("real_estate", item_id)
        self.assertEqual(row["current_value"], 200)

    def test_update_missing_id_returns_false(self):
        self.assertFalse(db.update_line_item("assets", 9999, {"balance": 1}))

    def test_update_line_item_rejects_a_blank_name(self):
        # Backs the Expense/Income tabs' inline-editable Name field --
        # clearing it entirely and blurring must not silently save a
        # nameless row (same rule add_line_item already enforces).
        item_id = db.add_line_item("expenses", {"name": "Groceries", "annual_amount": 100})
        with self.assertRaises(ValueError):
            db.update_line_item("expenses", item_id, {"name": "   "})
        # The original name is untouched.
        self.assertEqual(db.get_line_item("expenses", item_id)["name"], "Groceries")

    def test_update_line_item_coerces_a_blank_year_string_to_null(self):
        # The dashboard's inline editors always post a string (whatever
        # the <input>'s raw value is) via the generic /api/line-item/
        # update endpoint -- clearing Start Year/End Year/Base Year to
        # blank in the browser must clear the column to NULL, not store
        # the literal text "" into what's an INTEGER column.
        item_id = db.add_line_item("expenses", {
            "name": "Travel", "annual_amount": 5000, "start_year": 2030, "end_year": 2035, "base_year": 2026,
        })
        db.update_line_item("expenses", item_id, {"start_year": "", "end_year": "", "base_year": ""})
        row = db.get_line_item("expenses", item_id)
        self.assertIsNone(row["start_year"])
        self.assertIsNone(row["end_year"])
        self.assertIsNone(row["base_year"])

    def test_update_line_item_coerces_a_malformed_year_string_to_null(self):
        item_id = db.add_line_item("expenses", {"name": "Travel", "annual_amount": 5000})
        db.update_line_item("expenses", item_id, {"base_year": "not-a-year"})
        self.assertIsNone(db.get_line_item("expenses", item_id)["base_year"])

    def test_update_line_item_coerces_a_well_formed_year_string_to_int(self):
        item_id = db.add_line_item("expenses", {"name": "Travel", "annual_amount": 5000})
        db.update_line_item("expenses", item_id, {"base_year": "2029"})
        self.assertEqual(db.get_line_item("expenses", item_id)["base_year"], 2029)

    def test_update_line_item_coerces_a_numeric_string_for_a_money_field(self):
        item_id = db.add_line_item("expenses", {"name": "Groceries", "annual_amount": 100})
        db.update_line_item("expenses", item_id, {"annual_amount": "1500.50"})
        self.assertEqual(db.get_line_item("expenses", item_id)["annual_amount"], 1500.50)

    def test_update_line_item_coerces_a_malformed_money_string_to_zero(self):
        item_id = db.add_line_item("expenses", {"name": "Groceries", "annual_amount": 100})
        db.update_line_item("expenses", item_id, {"annual_amount": "not-a-number"})
        self.assertEqual(db.get_line_item("expenses", item_id)["annual_amount"], 0.0)

    def test_update_line_item_coerces_a_numeric_string_for_inflates(self):
        item_id = db.add_line_item("expenses", {"name": "Groceries", "annual_amount": 100})
        db.update_line_item("expenses", item_id, {"inflates": "1"})
        self.assertEqual(db.get_line_item("expenses", item_id)["inflates"], 1)

    def test_delete_line_item(self):
        item_id = db.add_line_item("expenses", {"name": "Healthcare", "annual_amount": 500})
        self.assertTrue(db.delete_line_item("expenses", item_id))
        self.assertIsNone(db.get_line_item("expenses", item_id))

    def test_delete_missing_id_returns_false(self):
        self.assertFalse(db.delete_line_item("expenses", 9999))

    def test_clear_section_by_source_only_removes_matching_rows(self):
        db.add_line_item("assets", {"name": "Manual one", "balance": 1, "source": "manual"})
        db.add_line_item("assets", {"name": "Imported one", "balance": 2, "source": "imported"})
        removed = db.clear_section("assets", source="imported")
        self.assertEqual(removed, 1)
        remaining = db.list_line_items("assets")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["name"], "Manual one")

    def test_clear_section_without_source_removes_everything(self):
        db.add_line_item("expenses", {"name": "A", "annual_amount": 1})
        db.add_line_item("expenses", {"name": "B", "annual_amount": 2})
        removed = db.clear_section("expenses")
        self.assertEqual(removed, 2)
        self.assertEqual(db.list_line_items("expenses"), [])

    def test_asset_defaults_to_unlinked(self):
        item_id = db.add_line_item("assets", {"name": "401k", "balance": 1})
        row = db.get_line_item("assets", item_id)
        self.assertIsNone(row["linked_account_id"])

    def test_can_set_and_clear_linked_account_id(self):
        item_id = db.add_line_item("assets", {"name": "401k", "balance": 1})
        self.assertTrue(db.update_line_item("assets", item_id, {"linked_account_id": "acc-1"}))
        self.assertEqual(db.get_line_item("assets", item_id)["linked_account_id"], "acc-1")
        self.assertTrue(db.update_line_item("assets", item_id, {"linked_account_id": None}))
        self.assertIsNone(db.get_line_item("assets", item_id)["linked_account_id"])

    def test_real_estate_row_supports_linked_account_id_and_annual_income(self):
        item_id = db.add_line_item("real_estate", {
            "name": "Moorpark", "current_value": 900_000, "loan_balance": 400_000, "annual_income": 3_000,
        })
        row = db.get_line_item("real_estate", item_id)
        self.assertIsNone(row["linked_account_id"])
        self.assertEqual(row["annual_income"], 3_000)
        self.assertTrue(db.update_line_item("real_estate", item_id, {"linked_account_id": "acc-mortgage"}))
        self.assertEqual(db.get_line_item("real_estate", item_id)["linked_account_id"], "acc-mortgage")

    def test_real_estate_annual_income_defaults_to_zero(self):
        item_id = db.add_line_item("real_estate", {"name": "Condo", "current_value": 100})
        self.assertEqual(db.get_line_item("real_estate", item_id)["annual_income"], 0)

    def test_real_estate_include_in_monte_carlo_defaults_to_off(self):
        item_id = db.add_line_item("real_estate", {"name": "Condo", "current_value": 100})
        self.assertEqual(db.get_line_item("real_estate", item_id)["include_in_monte_carlo"], 0)

    def test_real_estate_include_in_monte_carlo_is_settable(self):
        item_id = db.add_line_item("real_estate", {"name": "Condo", "current_value": 100})
        db.update_line_item("real_estate", item_id, {"include_in_monte_carlo": "1"})
        self.assertEqual(db.get_line_item("real_estate", item_id)["include_in_monte_carlo"], 1)

    def test_asset_include_in_monte_carlo_defaults_to_off(self):
        # Off by default -- a brand-new asset row was never automatically
        # part of a plan's projected drawdown until explicitly opted in,
        # same convention as real_estate's own checkbox.
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 1})
        self.assertEqual(db.get_line_item("assets", item_id)["include_in_monte_carlo"], 0)

    def test_asset_include_in_monte_carlo_is_settable(self):
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 1})
        db.update_line_item("assets", item_id, {"include_in_monte_carlo": "1"})
        self.assertEqual(db.get_line_item("assets", item_id)["include_in_monte_carlo"], 1)

    def test_income_include_in_monte_carlo_defaults_to_on(self):
        # On by default -- every income row has always unconditionally
        # netted against the withdrawal need, so a brand-new row keeps
        # that behavior unless explicitly unchecked.
        item_id = db.add_line_item("income", {"name": "Social Security", "annual_amount": 30_000})
        self.assertEqual(db.get_line_item("income", item_id)["include_in_monte_carlo"], 1)

    def test_income_include_in_monte_carlo_is_settable(self):
        item_id = db.add_line_item("income", {"name": "Social Security", "annual_amount": 30_000})
        db.update_line_item("income", item_id, {"include_in_monte_carlo": "0"})
        self.assertEqual(db.get_line_item("income", item_id)["include_in_monte_carlo"], 0)

    def test_init_db_migrates_a_database_created_before_linked_account_id_existed(self):
        # Simulate a pre-existing installation: an assets table without the
        # column, same as anyone who's already imported/added line items
        # before this feature shipped. init_db() (run at every dashboard
        # startup) has to add the column in place without losing data.
        with db.connect() as conn:
            conn.execute("ALTER TABLE assets RENAME TO assets_new_shape")
            conn.execute("""
                CREATE TABLE assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL DEFAULT 'asset',
                    category TEXT NOT NULL DEFAULT '', name TEXT NOT NULL,
                    institution TEXT NOT NULL DEFAULT '', last4 TEXT NOT NULL DEFAULT '',
                    balance REAL NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO assets (kind, category, name, institution, last4, balance, notes, source, "
                "created_at, updated_at) SELECT kind, category, name, institution, last4, balance, notes, "
                "source, created_at, updated_at FROM assets_new_shape"
            )
            conn.execute("DROP TABLE assets_new_shape")
        db.add_line_item("assets", {"name": "Pre-existing row", "balance": 500})
        db.init_db()  # the migration under test
        rows = db.list_line_items("assets")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Pre-existing row")
        self.assertIsNone(rows[0]["linked_account_id"])
        # And the column is now genuinely usable, not just present.
        self.assertTrue(db.update_line_item("assets", rows[0]["id"], {"linked_account_id": "acc-1"}))

    def test_init_db_migrates_an_assets_table_created_before_include_in_monte_carlo_existed_backfilling_from_the_old_category_list(self):
        # Simulates an installation that pre-dates per-row checkboxes,
        # where retirement_liquid_categories was still user-configurable
        # -- confirms the one-time migration reads whatever list was
        # configured (not just the "401k,Liquid" hardcoded default) to
        # decide which pre-existing rows get backfilled to checked.
        db.set_assumption("retirement_liquid_categories", "401k,Brokerage")
        with db.connect() as conn:
            conn.execute("ALTER TABLE assets RENAME TO assets_old_shape")
            conn.execute("""
                CREATE TABLE assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL DEFAULT 'asset',
                    category TEXT NOT NULL DEFAULT '', name TEXT NOT NULL,
                    institution TEXT NOT NULL DEFAULT '', last4 TEXT NOT NULL DEFAULT '',
                    balance REAL NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual', linked_account_id TEXT,
                    tax_treatment TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO assets (kind, category, name, institution, last4, balance, notes, source, "
                "linked_account_id, tax_treatment, created_at, updated_at) SELECT kind, category, name, "
                "institution, last4, balance, notes, source, linked_account_id, tax_treatment, created_at, "
                "updated_at FROM assets_old_shape"
            )
            conn.execute("DROP TABLE assets_old_shape")
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        db.add_line_item("assets", {"kind": "asset", "category": "Insurance", "name": "Whole life", "balance": 20_000})
        db.add_line_item("assets", {"kind": "asset", "category": "Brokerage", "name": "Schwab", "balance": 40_000})
        db.init_db()  # the migration under test
        rows = {r["name"]: r for r in db.list_line_items("assets")}
        self.assertEqual(rows["Fidelity"]["include_in_monte_carlo"], 1)
        self.assertEqual(rows["Schwab"]["include_in_monte_carlo"], 1)
        self.assertEqual(rows["Whole life"]["include_in_monte_carlo"], 0)

    def test_init_db_migrates_an_assets_table_with_no_prior_category_list_using_the_401k_liquid_default(self):
        with db.connect() as conn:
            conn.execute("ALTER TABLE assets RENAME TO assets_old_shape")
            conn.execute("""
                CREATE TABLE assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL DEFAULT 'asset',
                    category TEXT NOT NULL DEFAULT '', name TEXT NOT NULL,
                    institution TEXT NOT NULL DEFAULT '', last4 TEXT NOT NULL DEFAULT '',
                    balance REAL NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual', linked_account_id TEXT,
                    tax_treatment TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO assets (kind, category, name, institution, last4, balance, notes, source, "
                "linked_account_id, tax_treatment, created_at, updated_at) SELECT kind, category, name, "
                "institution, last4, balance, notes, source, linked_account_id, tax_treatment, created_at, "
                "updated_at FROM assets_old_shape"
            )
            conn.execute("DROP TABLE assets_old_shape")
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade", "balance": 50_000})
        db.init_db()  # the migration under test -- no retirement_liquid_categories row ever existed
        rows = db.list_line_items("assets")
        self.assertEqual(rows[0]["include_in_monte_carlo"], 1)

    def test_init_db_migrates_an_income_table_created_before_include_in_monte_carlo_existed_defaulting_to_included(self):
        with db.connect() as conn:
            conn.execute("ALTER TABLE income RENAME TO income_old_shape")
            conn.execute("""
                CREATE TABLE income (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '', annual_amount REAL NOT NULL DEFAULT 0,
                    start_year INTEGER, end_year INTEGER, base_year INTEGER,
                    inflates INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO income (name, category, annual_amount, start_year, end_year, base_year, "
                "inflates, notes, source, created_at, updated_at) SELECT name, category, annual_amount, "
                "start_year, end_year, base_year, inflates, notes, source, created_at, updated_at "
                "FROM income_old_shape"
            )
            conn.execute("DROP TABLE income_old_shape")
        db.add_line_item("income", {"name": "Pre-existing rental", "annual_amount": 24_000})
        db.init_db()  # the migration under test
        rows = db.list_line_items("income")
        self.assertEqual(len(rows), 1)
        # Income has always unconditionally counted -- the migration must
        # not silently change this row's contribution to the withdrawal
        # need.
        self.assertEqual(rows[0]["include_in_monte_carlo"], 1)

    def test_init_db_migrates_a_real_estate_table_created_before_linking_and_income_existed(self):
        with db.connect() as conn:
            conn.execute("ALTER TABLE real_estate RENAME TO real_estate_old_shape")
            conn.execute("""
                CREATE TABLE real_estate (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    purchase_price REAL NOT NULL DEFAULT 0, current_value REAL NOT NULL DEFAULT 0,
                    ownership_pct REAL NOT NULL DEFAULT 100, loan_balance REAL NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'manual',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO real_estate (name, purchase_price, current_value, ownership_pct, loan_balance, "
                "notes, source, created_at, updated_at) SELECT name, purchase_price, current_value, "
                "ownership_pct, loan_balance, notes, source, created_at, updated_at FROM real_estate_old_shape"
            )
            conn.execute("DROP TABLE real_estate_old_shape")
        db.add_line_item("real_estate", {"name": "Pre-existing home", "current_value": 800_000})
        db.init_db()  # the migration under test
        rows = db.list_line_items("real_estate")
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["linked_account_id"])
        self.assertEqual(rows[0]["annual_income"], 0)
        self.assertTrue(db.update_line_item("real_estate", rows[0]["id"], {"linked_account_id": "acc-mortgage"}))

    def test_init_db_migrates_a_real_estate_table_created_before_include_in_monte_carlo_existed(self):
        with db.connect() as conn:
            conn.execute("ALTER TABLE real_estate RENAME TO real_estate_old_shape")
            conn.execute("""
                CREATE TABLE real_estate (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    purchase_price REAL NOT NULL DEFAULT 0, current_value REAL NOT NULL DEFAULT 0,
                    ownership_pct REAL NOT NULL DEFAULT 100, loan_balance REAL NOT NULL DEFAULT 0,
                    annual_income REAL NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual', linked_account_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO real_estate (name, purchase_price, current_value, ownership_pct, loan_balance, "
                "annual_income, notes, source, linked_account_id, created_at, updated_at) SELECT name, "
                "purchase_price, current_value, ownership_pct, loan_balance, annual_income, notes, source, "
                "linked_account_id, created_at, updated_at FROM real_estate_old_shape"
            )
            conn.execute("DROP TABLE real_estate_old_shape")
        db.add_line_item("real_estate", {"name": "Pre-existing home", "current_value": 800_000})
        db.init_db()  # the migration under test
        rows = db.list_line_items("real_estate")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["include_in_monte_carlo"], 0)
        self.assertTrue(db.update_line_item("real_estate", rows[0]["id"], {"include_in_monte_carlo": 1}))
        self.assertEqual(db.get_line_item("real_estate", rows[0]["id"])["include_in_monte_carlo"], 1)

    def test_init_db_migrates_an_expenses_table_created_before_base_year_and_inflates_existed(self):
        with db.connect() as conn:
            conn.execute("ALTER TABLE expenses RENAME TO expenses_old_shape")
            conn.execute("""
                CREATE TABLE expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '', annual_amount REAL NOT NULL DEFAULT 0,
                    start_year INTEGER, end_year INTEGER, notes TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO expenses (name, category, annual_amount, start_year, end_year, notes, source, "
                "created_at, updated_at) SELECT name, category, annual_amount, start_year, end_year, notes, "
                "source, created_at, updated_at FROM expenses_old_shape"
            )
            conn.execute("DROP TABLE expenses_old_shape")
        db.add_line_item("expenses", {"name": "Pre-existing row", "annual_amount": 40_000})
        db.init_db()  # the migration under test
        rows = db.list_line_items("expenses")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Pre-existing row")
        self.assertIsNone(rows[0]["base_year"])
        self.assertEqual(rows[0]["inflates"], 0)
        self.assertTrue(db.update_line_item("expenses", rows[0]["id"], {"base_year": 2026, "inflates": 1}))

    def test_init_db_creates_the_income_table_for_a_database_that_predates_it(self):
        # income is a brand-new table (not a new column on an existing
        # one), so CREATE TABLE IF NOT EXISTS alone has to be enough --
        # no ALTER TABLE migration needed. Simulate a pre-existing
        # database that simply never had this table.
        with db.connect() as conn:
            conn.execute("DROP TABLE income")
        db.init_db()  # the migration under test
        item_id = db.add_line_item("income", {"name": "Rental", "annual_amount": 103_000})
        rows = db.list_line_items("income")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], item_id)


class TestAssumptions(TempConfigTestCase):
    def test_defaults_present_after_init(self):
        assumptions = db.get_assumptions()
        self.assertIn("expected_return", assumptions)
        self.assertIn("iterations", assumptions)

    def test_set_and_get_assumption(self):
        db.set_assumption("expected_return", 0.07)
        self.assertEqual(db.get_assumptions()["expected_return"], "0.07")

    def test_set_assumptions_bulk(self):
        db.set_assumptions({"iterations": 500, "plan_horizon_years": 30})
        assumptions = db.get_assumptions()
        self.assertEqual(assumptions["iterations"], "500")
        self.assertEqual(assumptions["plan_horizon_years"], "30")


class TestMeta(TempConfigTestCase):
    def test_get_meta_default_when_unset(self):
        self.assertIsNone(db.get_meta("last_import_at"))
        self.assertEqual(db.get_meta("last_import_at", "none"), "none")

    def test_set_and_get_meta(self):
        db.set_meta("last_import_at", "2026-09-21 10:00:00")
        self.assertEqual(db.get_meta("last_import_at"), "2026-09-21 10:00:00")


class TestPlaidItems(TempConfigTestCase):
    def test_upsert_and_get_item(self):
        db.upsert_plaid_item(
            item_key="fidelity_401k", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        row = db.get_plaid_item("fidelity_401k")
        self.assertEqual(row["plaid_item_id"], "item-1")
        self.assertEqual(row["products"], "investments")
        self.assertIsNone(row["last_synced_at"])

    def test_upsert_is_idempotent_on_item_key(self):
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name="Chase",
            products=[], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1-renewed", institution_id=None, institution_name="Chase",
            products=["transactions"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        self.assertEqual(len(db.list_plaid_items()), 1)
        self.assertEqual(db.get_plaid_item("k")["plaid_item_id"], "item-1-renewed")

    def test_get_missing_item_returns_none(self):
        self.assertIsNone(db.get_plaid_item("nope"))

    def test_credential_profile_defaults_to_primary(self):
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name=None,
            products=[], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        self.assertEqual(db.get_plaid_item("k")["credential_profile"], "primary")

    def test_credential_profile_round_trips_and_is_updated_on_upsert(self):
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name=None,
            products=[], environment="sandbox", credential_profile="secondary",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        self.assertEqual(db.get_plaid_item("k")["credential_profile"], "secondary")
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name=None,
            products=[], environment="sandbox", credential_profile="primary",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        self.assertEqual(db.get_plaid_item("k")["credential_profile"], "primary")

    def test_init_db_migrates_a_plaid_items_table_created_before_credential_profile_existed(self):
        with db.connect() as conn:
            conn.execute("ALTER TABLE plaid_items RENAME TO plaid_items_old")
            conn.execute("""
                CREATE TABLE plaid_items (
                    item_key TEXT PRIMARY KEY, plaid_item_id TEXT NOT NULL, institution_id TEXT,
                    institution_name TEXT, products TEXT NOT NULL DEFAULT '', environment TEXT NOT NULL,
                    linked_at TEXT NOT NULL, last_synced_at TEXT
                )
            """)
            conn.execute("""
                INSERT INTO plaid_items (item_key, plaid_item_id, institution_id, institution_name,
                                          products, environment, linked_at)
                SELECT item_key, plaid_item_id, institution_id, institution_name, products, environment, linked_at
                FROM plaid_items_old
            """)
            conn.execute("DROP TABLE plaid_items_old")
            conn.execute("""
                INSERT INTO plaid_items (item_key, plaid_item_id, institution_id, institution_name,
                                          products, environment, linked_at)
                VALUES ('pre_existing', 'item-old', NULL, 'Old Bank', 'investments', 'sandbox', '2026-01-01T00:00:00+00:00')
            """)
        db.init_db()
        with db.connect() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(plaid_items)").fetchall()}
        self.assertIn("credential_profile", columns)
        # A row that predates the column gets the "primary" default, same
        # as every Item this program has ever linked before Secondary existed.
        self.assertEqual(db.get_plaid_item("pre_existing")["credential_profile"], "primary")
        # This manually-built legacy table also predates transactions_cursor
        # (added alongside the Real Expenditure feature) -- same migration
        # pass backfills it too, as NULL (nothing to sync from yet).
        self.assertIn("transactions_cursor", columns)
        self.assertIsNone(db.get_plaid_item("pre_existing")["transactions_cursor"])

    def test_mark_synced(self):
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name=None,
            products=[], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.mark_plaid_item_synced("k", "2026-09-10T00:00:00+00:00")
        self.assertEqual(db.get_plaid_item("k")["last_synced_at"], "2026-09-10T00:00:00+00:00")

    def test_delete_item_cascades_accounts_and_holdings(self):
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name=None,
            products=["investments"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Brokerage", "balances": {"current": 100},
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-1", "institution_value": 100,
        })
        db.delete_plaid_item("k")
        self.assertIsNone(db.get_plaid_item("k"))
        self.assertEqual(db.list_plaid_accounts(), [])
        self.assertEqual(db.list_plaid_holdings(), [])

    def test_rename_item_key_updates_the_item_row_and_every_referencing_table(self):
        db.upsert_plaid_item(
            item_key="morgan_stanley", plaid_item_id="item-1", institution_id=None,
            institution_name="Charles Schwab", products=["investments", "transactions"],
            environment="production", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="morgan_stanley", account={
            "account_id": "acc-1", "name": "Brokerage", "balances": {"current": 100},
        })
        db.upsert_plaid_holding(item_key="morgan_stanley", holding={
            "account_id": "acc-1", "security_id": "sec-1", "institution_value": 100,
        })
        db.upsert_plaid_transaction(item_key="morgan_stanley", transaction=_fake_transaction_row("txn-1"))

        touched = db.rename_plaid_item_key("morgan_stanley", "schwab")

        self.assertEqual(touched, 4)  # item row + 1 account + 1 holding + 1 transaction
        self.assertIsNone(db.get_plaid_item("morgan_stanley"))
        renamed = db.get_plaid_item("schwab")
        self.assertEqual(renamed["institution_name"], "Charles Schwab")
        self.assertEqual(renamed["plaid_item_id"], "item-1")
        self.assertEqual(db.list_plaid_accounts()[0]["item_key"], "schwab")
        self.assertEqual(db.list_plaid_holdings()[0]["item_key"], "schwab")
        self.assertEqual(db.list_plaid_transactions()[0]["item_key"], "schwab")

    def test_rename_item_key_is_a_no_op_for_an_unknown_old_key(self):
        self.assertEqual(db.rename_plaid_item_key("nope", "whatever"), 0)

    def test_rename_item_key_refuses_a_new_key_already_in_use(self):
        db.upsert_plaid_item(
            item_key="a", plaid_item_id="item-1", institution_id=None, institution_name=None,
            products=[], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_item(
            item_key="b", plaid_item_id="item-2", institution_id=None, institution_name=None,
            products=[], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        with self.assertRaises(ValueError):
            db.rename_plaid_item_key("a", "b")
        # Neither Item was touched by the failed rename.
        self.assertIsNotNone(db.get_plaid_item("a"))
        self.assertIsNotNone(db.get_plaid_item("b"))


def _fake_transaction_row(transaction_id, *, account_id="acc-1", amount=42.50, date="2026-09-01",
                           name="Coffee Shop", primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_COFFEE",
                           category=None, excluded_from_expense=False):
    return {
        "transaction_id": transaction_id, "account_id": account_id, "date": date, "amount": amount,
        "iso_currency_code": "USD", "name": name, "merchant_name": name, "pending": False,
        "plaid_category_primary": primary, "plaid_category_detailed": detailed,
        "category": category if category is not None else "Food And Drink Coffee",
        "excluded_from_expense": excluded_from_expense,
    }


class TestPlaidTransactions(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        db.upsert_plaid_item(
            item_key="wells_fargo_checking", plaid_item_id="item-1", institution_id=None,
            institution_name="Wells Fargo", products=["transactions"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )

    def test_upsert_and_list_transaction(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        rows = db.list_plaid_transactions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["transaction_id"], "txn-1")
        self.assertEqual(rows[0]["category"], "Food And Drink Coffee")
        self.assertEqual(rows[0]["category_edited_by_user"], 0)
        self.assertEqual(rows[0]["excluded_from_expense"], 0)
        self.assertEqual(rows[0]["excluded_edited_by_user"], 0)

    def test_upsert_is_idempotent_on_transaction_id_and_refreshes_plaid_fields(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1", amount=10.0))
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1", amount=12.5))
        rows = db.list_plaid_transactions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], 12.5)

    def test_upsert_preserves_a_manually_edited_category_on_resync(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        db.update_plaid_transaction_category(["txn-1"], "My Own Label")
        # A later sync re-sends the same transaction (e.g. pending -> posted) --
        # Plaid's own classification is unchanged, but even if it weren't,
        # the manual edit should survive.
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1", amount=99.0))
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["category"], "My Own Label")
        self.assertEqual(row["category_edited_by_user"], 1)
        self.assertEqual(row["amount"], 99.0)  # Plaid-sourced field still refreshes

    def test_upsert_preserves_a_manually_edited_excluded_flag_on_resync(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        db.update_plaid_transaction_excluded(["txn-1"], True)
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["excluded_from_expense"], 1)
        self.assertEqual(row["excluded_edited_by_user"], 1)

    def test_delete_plaid_transactions(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-2"))
        count = db.delete_plaid_transactions(["txn-1"])
        self.assertEqual(count, 1)
        remaining = {r["transaction_id"] for r in db.list_plaid_transactions()}
        self.assertEqual(remaining, {"txn-2"})

    def test_delete_plaid_transactions_with_empty_list_is_a_no_op(self):
        self.assertEqual(db.delete_plaid_transactions([]), 0)

    def test_update_plaid_transaction_category_marks_edited_by_user(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        count = db.update_plaid_transaction_category(["txn-1"], "Groceries")
        self.assertEqual(count, 1)
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["category"], "Groceries")
        self.assertEqual(row["category_edited_by_user"], 1)

    def test_clear_plaid_transaction_category_overrides_recomputes_from_plaid_fields(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        db.update_plaid_transaction_category(["txn-1"], "My Own Label")
        count = db.clear_plaid_transaction_category_overrides(["txn-1"])
        self.assertEqual(count, 1)
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["category"], "Food")
        self.assertEqual(row["category_edited_by_user"], 0)

    def test_recategorize_all_transactions_backfills_a_stale_category(self):
        # Simulates a transaction that was synced before a
        # default_category() bucket change (or just carries a value that
        # no longer matches what it'd compute today) -- recategorize_
        # all_transactions() should bring it up to date since it was
        # never manually edited.
        db.upsert_plaid_transaction(
            item_key="wells_fargo_checking",
            transaction=_fake_transaction_row("txn-1", category="Food And Drink Coffee"),
        )
        changed = db.recategorize_all_transactions()
        self.assertEqual(changed, 1)
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["category"], "Food")

    def test_recategorize_all_transactions_never_touches_a_manual_edit(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        db.update_plaid_transaction_category(["txn-1"], "My Own Label")
        changed = db.recategorize_all_transactions()
        self.assertEqual(changed, 0)
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["category"], "My Own Label")

    def test_recategorize_all_transactions_is_a_no_op_once_everything_matches(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        db.recategorize_all_transactions()  # first pass brings it up to date
        changed_again = db.recategorize_all_transactions()
        self.assertEqual(changed_again, 0)

    def test_init_db_backfills_stale_categories_on_every_startup(self):
        # A change to default_category()'s own bucket list (source.
        # common.plaid_categorize) should reach transactions already
        # sitting in the database the next time the app starts, not just
        # ones synced from here on -- init_db() is called once at every
        # startup (see source.common.db.init_db), so this only has to
        # hold true across a second init_db() call, not a special
        # migration step a person has to remember to run.
        db.upsert_plaid_transaction(
            item_key="wells_fargo_checking",
            transaction=_fake_transaction_row("txn-1", category="Food And Drink Coffee"),
        )
        db.init_db()
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["category"], "Food")

    def test_update_plaid_transaction_excluded(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        count = db.update_plaid_transaction_excluded(["txn-1"], True)
        self.assertEqual(count, 1)
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["excluded_from_expense"], 1)
        self.assertEqual(row["excluded_edited_by_user"], 1)

    def test_clear_plaid_transaction_excluded_overrides_recomputes_from_plaid_fields(self):
        db.upsert_plaid_transaction(
            item_key="wells_fargo_checking",
            transaction=_fake_transaction_row("txn-1", primary="TRANSFER_OUT", detailed="TRANSFER_OUT_ACCOUNT_TRANSFER",
                                                excluded_from_expense=True),
        )
        db.update_plaid_transaction_excluded(["txn-1"], False)  # manually marked "include"
        count = db.clear_plaid_transaction_excluded_overrides(["txn-1"])
        self.assertEqual(count, 1)
        row = db.list_plaid_transactions()[0]
        # Back to the automatic heuristic -- a TRANSFER_OUT is excluded again.
        self.assertEqual(row["excluded_from_expense"], 1)
        self.assertEqual(row["excluded_edited_by_user"], 0)

    def test_new_transaction_defaults_to_no_income_kind_override(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["income_kind_override"], "")

    def test_update_plaid_transaction_income_kind_sets_the_override(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        count = db.update_plaid_transaction_income_kind(["txn-1"], "income")
        self.assertEqual(count, 1)
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["income_kind_override"], "income")

    def test_update_plaid_transaction_income_kind_can_clear_back_to_auto(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        db.update_plaid_transaction_income_kind(["txn-1"], "expense")
        count = db.update_plaid_transaction_income_kind(["txn-1"], "")
        self.assertEqual(count, 1)
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["income_kind_override"], "")

    def test_update_plaid_transaction_income_kind_rejects_an_unknown_kind(self):
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        with self.assertRaises(ValueError):
            db.update_plaid_transaction_income_kind(["txn-1"], "bogus")

    def test_update_plaid_transaction_income_kind_with_empty_list_is_a_no_op(self):
        self.assertEqual(db.update_plaid_transaction_income_kind([], "income"), 0)

    def test_income_kind_override_survives_a_resync(self):
        # Same "don't clobber a manual edit" guarantee category/excluded
        # overrides already get -- a later sync re-sending this
        # transaction_id must never silently clear the override.
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1"))
        db.update_plaid_transaction_income_kind(["txn-1"], "income")
        db.upsert_plaid_transaction(item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1", amount=99.0))
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["income_kind_override"], "income")
        self.assertEqual(row["amount"], 99.0)

    def test_get_and_set_transactions_cursor(self):
        self.assertIsNone(db.get_transactions_cursor("wells_fargo_checking"))
        db.set_transactions_cursor("wells_fargo_checking", "cursor-abc")
        self.assertEqual(db.get_transactions_cursor("wells_fargo_checking"), "cursor-abc")


class TestApplyCategoryRule(TempConfigTestCase):
    """source.common.db.transactions.apply_category_rule -- the Setup
    page's per-row "Apply" button, the real fix for a rule added well
    after some matching transactions were already hand-categorized (see
    this function's own docstring for the full "why")."""

    def setUp(self):
        super().setUp()
        db.upsert_plaid_item(
            item_key="wells_fargo_checking", plaid_item_id="item-1", institution_id=None,
            institution_name="Wells Fargo", products=["transactions"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )

    def test_raises_for_an_unknown_rule_id(self):
        with self.assertRaises(ValueError):
            db.apply_category_rule(999)

    def test_keyword_rule_force_overwrites_a_hand_edited_category(self):
        # The exact real-world case this exists for: a person manually
        # retyped a transaction's category to "salary" well before a
        # matching "apple" keyword rule existed -- recategorize_all_
        # transactions (the automatic pass every save/update triggers)
        # would never touch this row since category_edited_by_user=1.
        db.upsert_plaid_transaction(
            item_key="wells_fargo_checking",
            transaction=_fake_transaction_row("txn-1", name="APPLE INC. PAYROLL 123", primary="INCOME", detailed="INCOME_SALARY"),
        )
        db.update_plaid_transaction_category(["txn-1"], "salary")
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="apple", category="Salary", kind="income")

        result = db.apply_category_rule(rule_id)

        row = db.list_plaid_transactions()[0]
        self.assertEqual(result, {"matched": 1, "recategorized": 1, "kind_applied": 1})
        self.assertEqual(row["category"], "Salary")
        self.assertEqual(row["category_edited_by_user"], 0)  # rule-governed again
        self.assertEqual(row["income_kind_override"], "income")

    def test_does_not_touch_a_non_matching_transaction(self):
        db.upsert_plaid_transaction(
            item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1", name="Local Diner"),
        )
        db.update_plaid_transaction_category(["txn-1"], "Food")
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="apple", category="Salary", kind="income")

        result = db.apply_category_rule(rule_id)

        row = db.list_plaid_transactions()[0]
        self.assertEqual(result, {"matched": 0, "recategorized": 0, "kind_applied": 0})
        self.assertEqual(row["category"], "Food")
        self.assertEqual(row["income_kind_override"], "")

    def test_kind_auto_clears_a_previous_override_on_matched_rows(self):
        db.upsert_plaid_transaction(
            item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1", name="APPLE INC. PAYROLL"),
        )
        db.update_plaid_transaction_income_kind(["txn-1"], "income")
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="apple", category="Salary", kind="")

        result = db.apply_category_rule(rule_id)

        row = db.list_plaid_transactions()[0]
        self.assertEqual(result["kind_applied"], 1)
        self.assertEqual(row["income_kind_override"], "")

    def test_primary_rule_matches_on_plaid_category_primary(self):
        db.upsert_plaid_transaction(
            item_key="wells_fargo_checking",
            transaction=_fake_transaction_row("txn-1", name="Mystery Deposit", primary="OTHER", detailed="OTHER_OTHER"),
        )
        db.update_plaid_transaction_category(["txn-1"], "Uncategorized")
        rule_id = db.upsert_category_rule(rule_type="primary", match_key="other", category="Miscellaneous", kind="income")

        result = db.apply_category_rule(rule_id)

        self.assertEqual(result, {"matched": 1, "recategorized": 1, "kind_applied": 1})
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["category"], "Miscellaneous")

    def test_detailed_rule_matches_on_plaid_category_detailed(self):
        db.upsert_plaid_transaction(
            item_key="wells_fargo_checking",
            transaction=_fake_transaction_row("txn-1", name="Pet Store", primary="GENERAL_MERCHANDISE", detailed="GENERAL_MERCHANDISE_PET_SUPPLIES"),
        )
        rule_id = db.upsert_category_rule(
            rule_type="detailed", match_key="general_merchandise_pet_supplies", category="Pets", kind="expense",
        )

        result = db.apply_category_rule(rule_id)

        self.assertEqual(result["matched"], 1)
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["category"], "Pets")
        self.assertEqual(row["income_kind_override"], "expense")

    def test_matches_several_transactions_and_counts_each_outcome_separately(self):
        db.upsert_plaid_transaction(
            item_key="wells_fargo_checking", transaction=_fake_transaction_row("txn-1", name="APPLE INC. PAYROLL 1"),
        )
        db.update_plaid_transaction_category(["txn-1"], "salary")
        db.upsert_plaid_transaction(
            item_key="wells_fargo_checking",
            transaction=_fake_transaction_row("txn-2", name="APPLE INC. PAYROLL 2", primary="INCOME", detailed="INCOME_SALARY"),
        )
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="apple", category="Income", kind="income")

        result = db.apply_category_rule(rule_id)

        self.assertEqual(result["matched"], 2)
        self.assertEqual(result["recategorized"], 2)  # both: neither already had category "Income"
        self.assertEqual(result["kind_applied"], 2)
        rows = {r["transaction_id"]: r for r in db.list_plaid_transactions()}
        self.assertEqual(rows["txn-1"]["category"], "Income")
        self.assertEqual(rows["txn-2"]["category"], "Income")
        self.assertEqual(rows["txn-1"]["income_kind_override"], "income")
        self.assertEqual(rows["txn-2"]["income_kind_override"], "income")


class TestPlaidAccountsAndHoldings(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name="Chase",
            products=["investments"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )

    def test_account_balances_from_payload_prefers_nested_balances(self):
        current, available = db.account_balances_from_payload({
            "balances": {"current": 100.0, "available": 90.0},
        })
        self.assertEqual((current, available), (100.0, 90.0))

    def test_account_balances_from_payload_falls_back_to_flat_keys(self):
        current, available = db.account_balances_from_payload({
            "current_balance": 50.0, "available_balance": None,
        })
        self.assertEqual((current, available), (50.0, None))

    def test_upsert_account_is_idempotent_on_account_id(self):
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Checking", "balances": {"current": 100},
        })
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Checking", "balances": {"current": 150},
        })
        rows = db.list_plaid_accounts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["current_balance"], 150)

    def test_set_plaid_account_numbers_records_the_full_account_and_routing_number(self):
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Checking", "balances": {"current": 5_000},
        })
        ok = db.set_plaid_account_numbers(
            "acc-1", account_number="1234567890", routing_number="121000248", is_tokenized=False,
        )
        self.assertTrue(ok)
        row = db.get_plaid_account("acc-1")
        self.assertEqual(row["account_number"], "1234567890")
        self.assertEqual(row["routing_number"], "121000248")
        self.assertFalse(row["is_tokenized_account_number"])

    def test_set_plaid_account_numbers_on_an_unknown_account_returns_false(self):
        ok = db.set_plaid_account_numbers("does-not-exist", account_number="1", routing_number="2")
        self.assertFalse(ok)

    def test_upsert_plaid_account_does_not_clobber_previously_set_account_numbers(self):
        # A regular balance sync (accounts_balance_get) never returns
        # account/routing numbers -- re-upserting the account row (e.g. on
        # the next "Sync now") must not wipe out numbers a prior Auth call
        # already stored.
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Checking", "balances": {"current": 5_000},
        })
        db.set_plaid_account_numbers("acc-1", account_number="1234567890", routing_number="121000248")
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Checking", "balances": {"current": 5_200},
        })
        row = db.get_plaid_account("acc-1")
        self.assertEqual(row["current_balance"], 5_200)
        self.assertEqual(row["account_number"], "1234567890")

    def test_init_db_migrates_a_plaid_accounts_table_created_before_account_numbers_existed(self):
        with db.connect() as conn:
            conn.execute("ALTER TABLE plaid_accounts RENAME TO plaid_accounts_old")
            conn.execute("""
                CREATE TABLE plaid_accounts (
                    account_id TEXT PRIMARY KEY, item_key TEXT NOT NULL, name TEXT, official_name TEXT,
                    type TEXT, subtype TEXT, mask TEXT, current_balance REAL, available_balance REAL,
                    iso_currency_code TEXT, updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                INSERT INTO plaid_accounts (account_id, item_key, name, mask, current_balance, updated_at)
                SELECT account_id, item_key, name, mask, current_balance, updated_at FROM plaid_accounts_old
            """)
            conn.execute("DROP TABLE plaid_accounts_old")
        db.init_db()
        with db.connect() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(plaid_accounts)").fetchall()}
        self.assertIn("account_number", columns)
        self.assertIn("routing_number", columns)
        self.assertIn("is_tokenized_account_number", columns)
        # And the migrated table is still usable for a real write.
        db.upsert_plaid_account(item_key="k", account={"account_id": "acc-9", "name": "Checking"})
        ok = db.set_plaid_account_numbers("acc-9", account_number="1", routing_number="2")
        self.assertTrue(ok)

    def test_init_db_migrates_a_plaid_holdings_table_created_before_vested_columns_existed(self):
        with db.connect() as conn:
            conn.execute("ALTER TABLE plaid_holdings RENAME TO plaid_holdings_old")
            conn.execute("""
                CREATE TABLE plaid_holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, item_key TEXT NOT NULL, account_id TEXT NOT NULL,
                    security_id TEXT NOT NULL, ticker_symbol TEXT, security_name TEXT, security_type TEXT,
                    quantity REAL, institution_price REAL, institution_value REAL, cost_basis REAL,
                    iso_currency_code TEXT, updated_at TEXT NOT NULL, UNIQUE(account_id, security_id)
                )
            """)
            conn.execute("DROP TABLE plaid_holdings_old")
        db.init_db()
        with db.connect() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(plaid_holdings)").fetchall()}
        self.assertIn("vested_quantity", columns)
        self.assertIn("vested_value", columns)
        # And the migrated table is still usable for a real write.
        db.upsert_plaid_account(item_key="k", account={"account_id": "acc-1", "name": "Stock Plan"})
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-1", "institution_value": 100,
            "vested_quantity": 5, "vested_value": 50,
        })
        self.assertEqual(db.list_plaid_holdings()[0]["vested_value"], 50)

    def test_upsert_holding_stores_vested_quantity_and_value_when_plaid_provides_them(self):
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Stock Plan", "balances": {"current": 100_000},
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-1", "institution_value": 1500,
            "vested_quantity": 7.0, "vested_value": 700.0,
        })
        row = db.list_plaid_holdings()[0]
        self.assertEqual(row["vested_quantity"], 7.0)
        self.assertEqual(row["vested_value"], 700.0)

    def test_upsert_holding_leaves_vested_fields_null_when_plaid_omits_them(self):
        # Ordinary (non-stock-plan) holdings -- the overwhelming majority
        # -- never carry these fields at all.
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Brokerage", "balances": {"current": 1000},
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-1", "institution_value": 100,
        })
        row = db.list_plaid_holdings()[0]
        self.assertIsNone(row["vested_quantity"])
        self.assertIsNone(row["vested_value"])

    def test_upsert_holding_is_idempotent_on_account_and_security(self):
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Brokerage", "balances": {"current": 1000},
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-1", "institution_value": 100,
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-1", "institution_value": 250,
        })
        rows = db.list_plaid_holdings()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["institution_value"], 250)

    def test_prune_plaid_holdings_removes_a_pair_not_in_keep_pairs(self):
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Brokerage", "balances": {"current": 1000},
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-sold", "institution_value": 100,
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-kept", "institution_value": 200,
        })
        removed = db.prune_plaid_holdings(item_key="k", keep_pairs={("acc-1", "sec-kept")})
        self.assertEqual(removed, 1)
        rows = db.list_plaid_holdings()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["security_id"], "sec-kept")

    def test_prune_plaid_holdings_only_touches_its_own_item_key(self):
        db.upsert_plaid_item(
            item_key="other", plaid_item_id="item-2", institution_id=None, institution_name="Fidelity",
            products=["investments"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Brokerage", "balances": {"current": 1000},
        })
        db.upsert_plaid_account(item_key="other", account={
            "account_id": "acc-2", "name": "401k", "balances": {"current": 2000},
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-1", "institution_value": 100,
        })
        db.upsert_plaid_holding(item_key="other", holding={
            "account_id": "acc-2", "security_id": "sec-2", "institution_value": 200,
        })
        # Pruning item "k" down to nothing must not touch item "other"'s
        # own holding, even though neither pair is in keep_pairs.
        removed = db.prune_plaid_holdings(item_key="k", keep_pairs=set())
        self.assertEqual(removed, 1)
        remaining = {(r["item_key"], r["security_id"]) for r in db.list_plaid_holdings()}
        self.assertEqual(remaining, {("other", "sec-2")})

    def test_prune_plaid_holdings_with_every_pair_kept_deletes_nothing(self):
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Brokerage", "balances": {"current": 1000},
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-1", "institution_value": 100,
        })
        removed = db.prune_plaid_holdings(item_key="k", keep_pairs={("acc-1", "sec-1")})
        self.assertEqual(removed, 0)
        self.assertEqual(len(db.list_plaid_holdings()), 1)

    def test_get_plaid_account_by_id(self):
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Brokerage", "balances": {"current": 1000},
        })
        row = db.get_plaid_account("acc-1")
        self.assertEqual(row["name"], "Brokerage")

    def test_get_plaid_account_missing_returns_none(self):
        self.assertIsNone(db.get_plaid_account("nope"))


class TestSecurityIndustries(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name="Schwab",
            products=["investments"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="k", account={
            "account_id": "acc-1", "name": "Brokerage", "balances": {"current": 1000},
        })

    def test_set_and_get_security_industry(self):
        db.set_security_industry(security_id="sec-1", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")
        self.assertEqual(db.get_security_industries(), {"sec-1": "Consumer Electronics"})

    def test_set_security_industry_is_idempotent_on_security_id(self):
        db.set_security_industry(security_id="sec-1", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")
        db.set_security_industry(security_id="sec-1", ticker="AAPL", industry="Technology Hardware", updated_at="2026-09-14T00:00:00+00:00")
        self.assertEqual(db.get_security_industries(), {"sec-1": "Technology Hardware"})

    def test_list_unclassified_equity_tickers_only_includes_unclassified_equities_with_a_ticker(self):
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_type": "equity", "institution_value": 100,
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-voo", "ticker_symbol": "VOO",
            "security_type": "etf", "institution_value": 200,
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-no-ticker", "ticker_symbol": None,
            "security_type": "equity", "institution_value": 50,
        })
        db.upsert_plaid_holding(item_key="k", holding={
            "account_id": "acc-1", "security_id": "sec-nvda", "ticker_symbol": "NVDA",
            "security_type": "equity", "institution_value": 300,
        })
        db.set_security_industry(security_id="sec-nvda", ticker="NVDA", industry="Semiconductors", updated_at="2026-09-13T00:00:00+00:00")

        pending = db.list_unclassified_equity_tickers()
        self.assertEqual([r["security_id"] for r in pending], ["sec-aapl"])

    def test_clear_security_industries_removes_the_given_rows_and_reports_the_count(self):
        db.set_security_industry(security_id="sec-1", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")
        db.set_security_industry(security_id="sec-2", ticker="MSFT", industry="Software", updated_at="2026-09-13T00:00:00+00:00")
        db.set_security_industry(security_id="sec-3", ticker="NVDA", industry="Semiconductors", updated_at="2026-09-13T00:00:00+00:00")

        removed = db.clear_security_industries(["sec-1", "sec-2"])

        self.assertEqual(removed, 2)
        self.assertEqual(db.get_security_industries(), {"sec-3": "Semiconductors"})

    def test_clear_security_industries_is_a_no_op_for_an_unclassified_or_unknown_security_id(self):
        db.set_security_industry(security_id="sec-1", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")

        removed = db.clear_security_industries(["sec-never-classified"])

        self.assertEqual(removed, 0)
        self.assertEqual(db.get_security_industries(), {"sec-1": "Consumer Electronics"})

    def test_clear_security_industries_with_an_empty_list_is_a_no_op(self):
        db.set_security_industry(security_id="sec-1", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")

        removed = db.clear_security_industries([])

        self.assertEqual(removed, 0)
        self.assertEqual(db.get_security_industries(), {"sec-1": "Consumer Electronics"})

    def test_init_db_creates_the_security_industries_table_for_a_database_that_predates_it(self):
        # security_industries is a brand-new table (not a new column on
        # an existing one), so CREATE TABLE IF NOT EXISTS alone has to be
        # enough -- no ALTER TABLE migration needed. Simulate a
        # pre-existing database that simply never had this table.
        with db.connect() as conn:
            conn.execute("DROP TABLE security_industries")
        db.init_db()  # the migration under test
        db.set_security_industry(security_id="sec-1", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")
        self.assertEqual(db.get_security_industries(), {"sec-1": "Consumer Electronics"})

    def test_migration_adds_the_sector_column_to_a_database_that_predates_it(self):
        # Simulate a database created before the `sector` column existed
        # -- security_industries itself is already there (unlike the
        # brand-new-table case above), just missing this one column.
        with db.connect() as conn:
            conn.execute("DROP TABLE security_industries")
            conn.execute(
                "CREATE TABLE security_industries (security_id TEXT PRIMARY KEY, ticker TEXT, "
                "industry TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO security_industries VALUES ('sec-1', 'AAPL', 'Consumer Electronics', '2026-09-13T00:00:00+00:00')"
            )
        db.init_db()  # the migration under test -- must not drop the existing row
        self.assertEqual(db.get_security_industries(), {"sec-1": "Consumer Electronics"})
        db.set_security_sector(security_id="sec-1", ticker="AAPL", sector="Technology", updated_at="2026-09-13T00:00:00+00:00")
        self.assertEqual(db.get_security_sectors(), {"sec-1": "Technology"})


class TestSecuritySectors(TempConfigTestCase):
    """Unit tests for the manual sector override -- set_security_sector/
    get_security_sectors/clear_security_sectors -- used by mutual funds,
    ETFs, and target-date funds, which never get an `industry` classified
    for them in the first place (see set_security_sector's docstring)."""

    def test_set_and_get_security_sector(self):
        db.set_security_sector(security_id="sec-fund", ticker="VG.INST.500.IDX", sector="Diversified", updated_at="2026-09-13T00:00:00+00:00")
        self.assertEqual(db.get_security_sectors(), {"sec-fund": "Diversified"})

    def test_setting_sector_on_a_fresh_security_id_leaves_industry_blank(self):
        db.set_security_sector(security_id="sec-fund", ticker="VG.INST.500.IDX", sector="Diversified", updated_at="2026-09-13T00:00:00+00:00")
        self.assertEqual(db.get_security_industries(), {"sec-fund": ""})

    def test_setting_sector_preserves_an_existing_industry_classification(self):
        db.set_security_industry(security_id="sec-1", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")
        db.set_security_sector(security_id="sec-1", ticker="AAPL", sector="Real Estate", updated_at="2026-09-14T00:00:00+00:00")
        self.assertEqual(db.get_security_industries(), {"sec-1": "Consumer Electronics"})
        self.assertEqual(db.get_security_sectors(), {"sec-1": "Real Estate"})

    def test_set_security_sector_is_idempotent_on_security_id(self):
        db.set_security_sector(security_id="sec-fund", ticker="VOO", sector="Diversified", updated_at="2026-09-13T00:00:00+00:00")
        db.set_security_sector(security_id="sec-fund", ticker="VOO", sector="Technology", updated_at="2026-09-14T00:00:00+00:00")
        self.assertEqual(db.get_security_sectors(), {"sec-fund": "Technology"})

    def test_get_security_sectors_omits_securities_with_no_sector_set(self):
        db.set_security_industry(security_id="sec-1", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")
        self.assertEqual(db.get_security_sectors(), {})

    def test_clear_security_sectors_clears_just_the_sector_not_the_row(self):
        db.set_security_industry(security_id="sec-1", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")
        db.set_security_sector(security_id="sec-1", ticker="AAPL", sector="Real Estate", updated_at="2026-09-14T00:00:00+00:00")

        removed = db.clear_security_sectors(["sec-1"])

        self.assertEqual(removed, 1)
        self.assertEqual(db.get_security_sectors(), {})
        # The industry classification survives clearing the sector.
        self.assertEqual(db.get_security_industries(), {"sec-1": "Consumer Electronics"})

    def test_clear_security_sectors_is_a_no_op_for_an_unset_security_id(self):
        db.set_security_sector(security_id="sec-fund", ticker="VOO", sector="Diversified", updated_at="2026-09-13T00:00:00+00:00")

        removed = db.clear_security_sectors(["sec-never-set"])

        self.assertEqual(removed, 0)
        self.assertEqual(db.get_security_sectors(), {"sec-fund": "Diversified"})

    def test_clear_security_sectors_with_an_empty_list_is_a_no_op(self):
        db.set_security_sector(security_id="sec-fund", ticker="VOO", sector="Diversified", updated_at="2026-09-13T00:00:00+00:00")

        removed = db.clear_security_sectors([])

        self.assertEqual(removed, 0)
        self.assertEqual(db.get_security_sectors(), {"sec-fund": "Diversified"})


class TestCategoryRules(TempConfigTestCase):
    def test_upsert_and_list(self):
        db.upsert_category_rule(rule_type="primary", match_key="general_merchandise", category="Shopping")
        rows = db.list_category_rules()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rule_type"], "primary")
        # Normalized upper-case for primary/detailed, matching how Plaid's
        # own values are compared in plaid_categorize.default_category.
        self.assertEqual(rows[0]["match_key"], "GENERAL_MERCHANDISE")
        self.assertEqual(rows[0]["category"], "Shopping")

    def test_keyword_rule_is_lowercased(self):
        db.upsert_category_rule(rule_type="keyword", match_key="PELOTON", category="Fitness")
        self.assertEqual(db.list_category_rules()[0]["match_key"], "peloton")

    def test_upsert_is_idempotent_on_rule_type_and_match_key(self):
        db.upsert_category_rule(rule_type="detailed", match_key="foo", category="Bar")
        db.upsert_category_rule(rule_type="detailed", match_key="foo", category="Baz")
        rows = db.list_category_rules()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "Baz")

    def test_upsert_rejects_an_unknown_rule_type(self):
        with self.assertRaises(ValueError):
            db.upsert_category_rule(rule_type="nonsense", match_key="foo", category="Bar")

    def test_upsert_rejects_a_blank_match_key_or_category(self):
        with self.assertRaises(ValueError):
            db.upsert_category_rule(rule_type="primary", match_key="  ", category="Bar")
        with self.assertRaises(ValueError):
            db.upsert_category_rule(rule_type="primary", match_key="foo", category="  ")

    def test_list_can_filter_by_rule_type(self):
        db.upsert_category_rule(rule_type="primary", match_key="a", category="A")
        db.upsert_category_rule(rule_type="keyword", match_key="b", category="B")
        self.assertEqual(len(db.list_category_rules(rule_type="primary")), 1)
        self.assertEqual(len(db.list_category_rules(rule_type="keyword")), 1)

    def test_delete_category_rule(self):
        rule_id = db.upsert_category_rule(rule_type="primary", match_key="a", category="A")
        self.assertTrue(db.delete_category_rule(rule_id))
        self.assertEqual(db.list_category_rules(), [])

    def test_delete_missing_rule_returns_false(self):
        self.assertFalse(db.delete_category_rule(999))

    def test_load_active_overrides_shapes_rows_for_default_category(self):
        db.upsert_category_rule(rule_type="primary", match_key="general_merchandise", category="Shopping")
        db.upsert_category_rule(rule_type="detailed", match_key="foo_bar", category="Baz")
        db.upsert_category_rule(rule_type="keyword", match_key="peloton", category="Fitness")

        overrides = db.load_active_overrides()

        self.assertEqual(overrides["primary"], {"GENERAL_MERCHANDISE": "Shopping"})
        self.assertEqual(overrides["detailed"], {"FOO_BAR": "Baz"})
        # A 3-tuple -- (match_key, category, match_mode) -- not just
        # (match_key, category), so plaid_categorize._guess_category_
        # from_name knows HOW to compare match_key, not just what it is.
        self.assertEqual(overrides["keywords"], [("peloton", "Fitness", "contains")])

    def test_load_active_overrides_is_empty_by_default(self):
        self.assertEqual(db.load_active_overrides(), {"primary": {}, "detailed": {}, "keywords": []})

    def test_upsert_keyword_rule_defaults_to_contains_match_mode(self):
        db.upsert_category_rule(rule_type="keyword", match_key="peloton", category="Fitness")
        self.assertEqual(db.list_category_rules()[0]["match_mode"], "contains")

    def test_upsert_keyword_rule_accepts_starts_with_ends_with_and_regex(self):
        db.upsert_category_rule(rule_type="keyword", match_key="uber", category="Transportation", match_mode="starts_with")
        db.upsert_category_rule(rule_type="keyword", match_key="corp", category="Business", match_mode="ends_with")
        db.upsert_category_rule(rule_type="keyword", match_key=r"^amzn.*mktp", category="Shopping", match_mode="regex")
        rows = {r["match_key"]: r["match_mode"] for r in db.list_category_rules()}
        self.assertEqual(rows["uber"], "starts_with")
        self.assertEqual(rows["corp"], "ends_with")
        self.assertEqual(rows["^amzn.*mktp"], "regex")

    def test_upsert_rejects_an_unknown_match_mode(self):
        with self.assertRaises(ValueError):
            db.upsert_category_rule(rule_type="keyword", match_key="foo", category="Bar", match_mode="fuzzy")

    def test_upsert_ignores_match_mode_for_primary_and_detailed_rules(self):
        # match_mode only means anything for a 'keyword' rule -- a
        # 'primary'/'detailed' rule is always an exact match on Plaid's
        # own value, so whatever was passed is normalized to "exact"
        # rather than stored (or rejected) as-is.
        db.upsert_category_rule(rule_type="primary", match_key="food_and_drink", category="Food", match_mode="regex")
        self.assertEqual(db.list_category_rules()[0]["match_mode"], "exact")

    def test_regex_match_key_keeps_its_original_case(self):
        # Unlike contains/starts_with/ends_with (always lowercased),
        # a regex pattern's own case can matter syntactically, and
        # plaid_categorize._keyword_rule_matches already matches
        # case-insensitively at match time regardless.
        db.upsert_category_rule(rule_type="keyword", match_key="Amazon|AMZN", category="Shopping", match_mode="regex")
        self.assertEqual(db.list_category_rules()[0]["match_key"], "Amazon|AMZN")

    def test_update_category_rule_edits_the_same_row_in_place(self):
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="peloton", category="Fitness")
        db.update_category_rule(
            rule_id, rule_type="keyword", match_key="soulcycle", category="Wellness", match_mode="starts_with",
        )
        rows = db.list_category_rules()
        self.assertEqual(len(rows), 1)  # edited in place, not a second row
        self.assertEqual(rows[0]["id"], rule_id)
        self.assertEqual(rows[0]["match_key"], "soulcycle")
        self.assertEqual(rows[0]["category"], "Wellness")
        self.assertEqual(rows[0]["match_mode"], "starts_with")

    def test_update_category_rule_can_change_rule_type(self):
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="peloton", category="Fitness")
        db.update_category_rule(rule_id, rule_type="primary", match_key="general_merchandise", category="Shopping")
        rows = db.list_category_rules()
        self.assertEqual(rows[0]["rule_type"], "primary")
        self.assertEqual(rows[0]["match_key"], "GENERAL_MERCHANDISE")
        self.assertEqual(rows[0]["match_mode"], "exact")

    def test_update_category_rule_rejects_a_collision_with_a_different_rule(self):
        db.upsert_category_rule(rule_type="keyword", match_key="peloton", category="Fitness")
        other_id = db.upsert_category_rule(rule_type="keyword", match_key="soulcycle", category="Wellness")
        with self.assertRaises(ValueError):
            db.update_category_rule(other_id, rule_type="keyword", match_key="peloton", category="Wellness")
        # The rejected update must not have partially applied.
        other_row = next(r for r in db.list_category_rules() if r["id"] == other_id)
        self.assertEqual(other_row["match_key"], "soulcycle")

    def test_update_category_rule_raises_for_an_unknown_id(self):
        with self.assertRaises(ValueError):
            db.update_category_rule(999, rule_type="keyword", match_key="peloton", category="Fitness")

    def test_update_category_rule_rejects_the_same_bad_input_as_upsert(self):
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="peloton", category="Fitness")
        with self.assertRaises(ValueError):
            db.update_category_rule(rule_id, rule_type="nonsense", match_key="peloton", category="Fitness")
        with self.assertRaises(ValueError):
            db.update_category_rule(rule_id, rule_type="keyword", match_key="", category="Fitness")

    def test_upsert_defaults_to_no_kind_opinion(self):
        db.upsert_category_rule(rule_type="keyword", match_key="peloton", category="Fitness")
        self.assertEqual(db.list_category_rules()[0]["kind"], "")

    def test_upsert_can_set_kind_to_income_or_expense(self):
        db.upsert_category_rule(rule_type="keyword", match_key="apple", category="Salary", kind="income")
        db.upsert_category_rule(rule_type="keyword", match_key="mortgage", category="Loan Payments", kind="expense")
        rows = {r["match_key"]: r["kind"] for r in db.list_category_rules()}
        self.assertEqual(rows["apple"], "income")
        self.assertEqual(rows["mortgage"], "expense")

    def test_upsert_rejects_an_unknown_kind(self):
        with self.assertRaises(ValueError):
            db.upsert_category_rule(rule_type="keyword", match_key="apple", category="Salary", kind="bogus")

    def test_update_category_rule_can_change_kind(self):
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="apple", category="Salary", kind="income")
        db.update_category_rule(rule_id, rule_type="keyword", match_key="apple", category="Salary", kind="expense")
        self.assertEqual(db.list_category_rules()[0]["kind"], "expense")
        db.update_category_rule(rule_id, rule_type="keyword", match_key="apple", category="Salary", kind="")
        self.assertEqual(db.list_category_rules()[0]["kind"], "")


class TestNetWorthSnapshots(TempConfigTestCase):
    def _record(self, snapshot_date, net_worth=100.0):
        db.record_snapshot(
            net_worth=net_worth, manual_asset_total=10.0, linked_asset_total=20.0,
            liability_total=5.0, real_estate_equity_total=30.0, retirement_liquid_total=40.0,
            snapshot_date=snapshot_date,
        )

    def test_record_and_list(self):
        self._record("2026-09-01", net_worth=100.0)
        rows = db.list_net_worth_snapshots()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["snapshot_date"], "2026-09-01")
        self.assertEqual(rows[0]["net_worth"], 100.0)
        self.assertEqual(rows[0]["linked_asset_total"], 20.0)

    def test_recording_the_same_day_twice_upserts_rather_than_duplicating(self):
        self._record("2026-09-01", net_worth=100.0)
        self._record("2026-09-01", net_worth=150.0)
        rows = db.list_net_worth_snapshots()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["net_worth"], 150.0)

    def test_list_is_ordered_by_date_ascending(self):
        self._record("2026-09-03")
        self._record("2026-09-01")
        self._record("2026-09-02")
        dates = [r["snapshot_date"] for r in db.list_net_worth_snapshots()]
        self.assertEqual(dates, ["2026-09-01", "2026-09-02", "2026-09-03"])

    def test_record_defaults_to_todays_date(self):
        from datetime import date
        db.record_snapshot(
            net_worth=1.0, manual_asset_total=0, linked_asset_total=0,
            liability_total=0, real_estate_equity_total=0, retirement_liquid_total=0,
        )
        self.assertEqual(db.list_net_worth_snapshots()[0]["snapshot_date"], date.today().isoformat())


class TestAccountBalanceSnapshots(TempConfigTestCase):
    def test_record_and_list(self):
        db.record_account_balance_snapshot(account_id="acc1", balance=1000.0, snapshot_date="2026-09-01")
        rows = db.list_account_balance_snapshots()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["account_id"], "acc1")
        self.assertEqual(rows[0]["snapshot_date"], "2026-09-01")
        self.assertEqual(rows[0]["balance"], 1000.0)

    def test_recording_the_same_account_the_same_day_twice_upserts_rather_than_duplicating(self):
        db.record_account_balance_snapshot(account_id="acc1", balance=1000.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc1", balance=1500.0, snapshot_date="2026-09-01")
        rows = db.list_account_balance_snapshots()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["balance"], 1500.0)

    def test_two_different_accounts_on_the_same_day_are_both_kept(self):
        db.record_account_balance_snapshot(account_id="acc1", balance=1000.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc2", balance=500.0, snapshot_date="2026-09-01")
        rows = db.list_account_balance_snapshots()
        self.assertEqual(len(rows), 2)

    def test_list_can_be_filtered_to_one_account(self):
        db.record_account_balance_snapshot(account_id="acc1", balance=1000.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc2", balance=500.0, snapshot_date="2026-09-01")
        rows = db.list_account_balance_snapshots("acc1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["account_id"], "acc1")

    def test_list_is_ordered_by_date_ascending(self):
        db.record_account_balance_snapshot(account_id="acc1", balance=1.0, snapshot_date="2026-09-03")
        db.record_account_balance_snapshot(account_id="acc1", balance=1.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc1", balance=1.0, snapshot_date="2026-09-02")
        dates = [r["snapshot_date"] for r in db.list_account_balance_snapshots("acc1")]
        self.assertEqual(dates, ["2026-09-01", "2026-09-02", "2026-09-03"])

    def test_record_defaults_to_todays_date(self):
        from datetime import date
        db.record_account_balance_snapshot(account_id="acc1", balance=1.0)
        self.assertEqual(db.list_account_balance_snapshots()[0]["snapshot_date"], date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
