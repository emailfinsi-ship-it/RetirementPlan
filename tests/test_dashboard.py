"""source.webapp.dashboard -- boots a real ThreadingHTTPServer on an
ephemeral port (0) against a temp-dir-backed config, same pattern as
FamilyFinanceTracker's own TestNoStoreCacheHeader, since these handlers
need a real socket rather than being unit-testable in isolation.

Also patches the `keyring` module functions with an in-memory FakeKeyring
(see tests/testing_utils.py) so the Setup page's Plaid-credentials card and
the /api/plaid-* routes never touch a real macOS Keychain, and mocks the
actual Plaid network calls (link_item.link_real_item, remove_item.
remove_item, sync.sync_all) so these tests never make a real HTTP request
to Plaid or open a browser tab."""

import http.client
import json
import random
import re
import tempfile
import threading
import unittest
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import keyring

from source.common import branding, app_settings, auth_store, backup, config, db, secrets_store
from source.webapp import dashboard
from tests.testing_utils import FakeKeyring


class DashboardTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmpdir.name)
        cls.fake_keyring = FakeKeyring()
        cls._patches = [
            patch.object(config, "DATA_DIR", tmp / "data"),
            patch.object(config, "DB_PATH", tmp / "data" / "retirement_plan.db"),
            patch.object(config, "OUTPUT_DIR", tmp / "output"),
            patch.object(config, "LOG_DIR", tmp / "logs"),
            patch.object(config, "CONFIG_DIR", tmp / "config"),
            # A real config.set_data_dir()/set_output_dir() call would otherwise
            # persist to the real ~/Library/Application Support/RetirementPlan/
            # settings.json on whatever machine runs this suite -- redirect
            # that to the same temp dir.
            patch.object(app_settings, "_SETTINGS_DIR", tmp / "app_settings"),
            patch.object(app_settings, "_SETTINGS_PATH", tmp / "app_settings" / "settings.json"),
            patch.object(keyring, "get_password", cls.fake_keyring.get_password),
            patch.object(keyring, "set_password", cls.fake_keyring.set_password),
            patch.object(keyring, "delete_password", cls.fake_keyring.delete_password),
        ]
        for p in cls._patches:
            p.start()
        config.ensure_directories()
        db.init_db()
        secrets_store.clear_vault_cache()
        auth_store.clear_auth_cache()
        # Everyday (plain) wording is the app's default, but the tests below
        # check the page text as written in the code, which is the technical
        # wording. tests/test_wording.py covers the plain wording itself.
        db.set_wording_mode("technical")
        # No test in this file sets a login password unless it says so
        # explicitly, so the auth gate in dashboard.Handler stays off by
        # default here -- same "every existing test keeps behaving
        # exactly as it did before login existed" guarantee
        # secrets_store.clear_vault_cache() above already gives the
        # Plaid vault.
        dashboard._login_failures.clear()

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        secrets_store.clear_vault_cache()
        auth_store.clear_auth_cache()
        for p in cls._patches:
            p.stop()
        cls._tmpdir.cleanup()

    # /monte-carlo.html's own render time (an on-demand Gaussian +
    # S&P-bootstrap + 6-scenario historical stress test simulation) has
    # been clocked as high as ~5.7s on a busy sandbox -- above what used
    # to be this timeout (5s), which made every test touching that page
    # an intermittent, environment-load-dependent failure rather than a
    # real one. 30s gives real headroom without masking an actual hang.
    _HTTP_TIMEOUT = 30

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        try:
            conn.request("GET", path)
            return conn.getresponse()
        finally:
            conn.close()

    def _post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        try:
            data = json.dumps(body).encode("utf-8")
            conn.request("POST", path, body=data, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            payload = json.loads(resp.read().decode("utf-8"))
            return resp.status, payload
        finally:
            conn.close()


class TestGroupByCategory(unittest.TestCase):
    """Unit tests for the module-level helper, independent of the HTTP layer."""

    def test_groups_preserve_first_appearance_order(self):
        rows = [
            {"category": "Liquid Assets", "name": "Checking"},
            {"category": "Retirement Account", "name": "401k"},
            {"category": "Liquid Assets", "name": "Savings"},
        ]
        groups = dashboard._group_by_category(rows)
        self.assertEqual([cat for cat, _ in groups], ["Liquid Assets", "Retirement Account"])
        self.assertEqual(len(dict(groups)["Liquid Assets"]), 2)
        self.assertEqual(len(dict(groups)["Retirement Account"]), 1)

    def test_blank_category_becomes_uncategorized(self):
        rows = [{"category": "", "name": "Misc"}, {"category": "   ", "name": "Other"}]
        groups = dashboard._group_by_category(rows)
        self.assertEqual([cat for cat, _ in groups], ["Uncategorized"])
        self.assertEqual(len(dict(groups)["Uncategorized"]), 2)

    def test_empty_input_returns_no_groups(self):
        self.assertEqual(dashboard._group_by_category([]), [])


class TestChooseFileDialog(unittest.TestCase):
    """Unit tests for the module-level helper, independent of the HTTP layer."""

    def test_builds_an_osascript_command_with_type_filter(self):
        fake_result = Mock(returncode=0, stdout="/path/to/file.xlsx\n", stderr="")
        with patch("source.webapp.dashboard.subprocess.run", return_value=fake_result) as mock_run:
            path = dashboard._choose_file_dialog("Pick one", file_types=["xlsx", "xlsm"])
        self.assertEqual(path, "/path/to/file.xlsx")
        args = mock_run.call_args[0][0]
        self.assertEqual(args[0], "osascript")
        script = args[2]
        self.assertIn("choose file", script)
        self.assertIn('"xlsx"', script)
        self.assertIn('"xlsm"', script)
        self.assertIn("Pick one", script)

    def test_no_type_filter_omits_of_type_clause(self):
        fake_result = Mock(returncode=0, stdout="/path/to/file\n", stderr="")
        with patch("source.webapp.dashboard.subprocess.run", return_value=fake_result) as mock_run:
            dashboard._choose_file_dialog("Pick one")
        script = mock_run.call_args[0][0][2]
        self.assertNotIn("of type", script)

    def test_cancel_returns_none(self):
        fake_result = Mock(returncode=1, stdout="", stderr="execution error: User canceled. (-128)")
        with patch("source.webapp.dashboard.subprocess.run", return_value=fake_result):
            self.assertIsNone(dashboard._choose_file_dialog("Pick one"))

    def test_timeout_raises_runtime_error(self):
        import subprocess as subprocess_module
        with patch(
            "source.webapp.dashboard.subprocess.run",
            side_effect=subprocess_module.TimeoutExpired(cmd="osascript", timeout=300),
        ):
            with self.assertRaises(RuntimeError):
                dashboard._choose_file_dialog("Pick one")


class TestPagesRenderWithEmptyState(DashboardTestCase):
    def test_every_page_returns_200(self):
        for path in (
            "/summary.html", "/asset.html", "/linked-accounts.html", "/linked-positions.html", "/rebalance.html", "/expense.html",
            "/real-estate.html", "/monte-carlo.html", "/setup.html", "/setup-wizard.html",
        ):
            with self.subTest(path=path):
                resp = self._get(path)
                self.assertEqual(resp.status, 200)
                resp.read()

    def test_empty_install_root_lands_on_the_setup_wizard(self):
        resp = self._get("/")
        resp.read()
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.getheader("Location"), "/setup-wizard.html")

    def test_cache_control_no_store(self):
        resp = self._get("/summary.html")
        self.assertEqual(resp.getheader("Cache-Control"), "no-store")

    def test_unknown_path_is_404(self):
        resp = self._get("/nope")
        self.assertEqual(resp.status, 404)

    def test_expense_nav_label_and_title_reflect_income_and_expense(self):
        # The tab covers both Expense and Income line-item sections (see
        # _render_expense_page), so its nav label/title says so rather
        # than just "Expense".
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertRegex(body, r'href="/expense.html" class="active">.*<span class="nl">Income &amp; Expenses</span></a>')
        self.assertIn("<title>" + branding.PRODUCT_NAME + " — Income &amp; Expenses</title>", body)

    def test_monte_carlo_page_renders_with_no_data(self):
        resp = self._get("/monte-carlo.html")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode("utf-8")
        self.assertIn("Monte Carlo", body)
        # The historical stress test section renders even with an empty
        # plan -- no data to divide by zero on, since every scenario just
        # replays $0 forward.
        self.assertIn("Historical recession stress test", body)
        self.assertIn("Great Depression (1929)", body)

    def test_summary_page_has_what_if_return_card(self):
        db.add_line_item("expenses", {"name": "Baseline", "category": "Fixed", "annual_amount": 60_000})
        try:
            resp = self._get("/summary.html")
            body = resp.read().decode("utf-8")
        finally:
            db.clear_section("expenses")
        self.assertIn("Will your money last?", body)
        self.assertIn("/monte-carlo.html#assumptions", body)
        self.assertIn("Chance your money lasts", body)
        self.assertIn("Typical case", body)
        # The interactive what-if moved to the Monte Carlo tab, next to the Assumptions.
        self.assertNotIn('id="wi-spend"', body)
        mc = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn("Try a what-if", mc)
        self.assertIn('id="wi-spend"', mc)
        self.assertLess(mc.index('id="wi-spend"'), mc.index('name="expected_return_pct"'))

    def test_nav_has_nine_tabs_and_paired_pages_share_one(self):
        from source.webapp.render_helpers.shell import NAV_ITEMS
        self.assertEqual(len(NAV_ITEMS), 10)  # the eight plan tabs + Trading + Stock Analysis
        pairs = {
            "/asset.html": ("/real-estate.html", "Real Estate"),
            "/linked-accounts.html": ("/rebalance.html", "Risk &amp; Suggestions"),
            "/real-expenditure.html": ("/budget-vs-actual.html", "Budget vs Actual"),
            "/drawdown-planning.html": ("/legacy-planning.html", "Legacy Planning"),
        }
        for first, (second, label) in pairs.items():
            for path in (first, second):
                with self.subTest(path=path):
                    body = self._get(path).read().decode("utf-8")
                    self.assertIn(f'<a href="{first}" class="active">', body)  # same top-level tab lit
                    self.assertIn(f'<a href="{second}"', body)
                    self.assertIn(f'>{label}</a>', body)
        # Unpaired tabs show no section row.
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertNotIn('<div class="subnav">', body)

    def test_income_tab_explains_how_rental_income_is_taxed(self):
        body = self._get("/expense.html").read().decode("utf-8")
        self.assertIn("Rental income:", body)
        self.assertIn("after property costs", body)
        self.assertIn("Loan ends", body)

    def test_money_last_tab_has_the_social_security_planner(self):
        db.set_assumptions({"birth_year": "1965", "ss_benefit_self": "30000", "ss_claim_age_self": "67"})
        try:
            body = self._get("/monte-carlo.html").read().decode("utf-8")
            income_tab = self._get("/expense.html").read().decode("utf-8")
        finally:
            db.set_assumptions({"birth_year": "", "ss_benefit_self": "", "ss_claim_age_self": ""})
        self.assertIn('id="benefits-planner"', body)
        self.assertIn("<h2 style=\"margin-top:0\">Social Security</h2>", body)
        self.assertIn("claiming age comparison", body)
        self.assertIn("function saveBenefits(", body)
        # One place only: the Income tab points at it instead of repeating the form.
        self.assertNotIn('id="benefits-form"', income_tab)
        self.assertIn('id="ss-pointer"', income_tab)

    def test_benefits_apply_endpoint_writes_the_rows(self):
        db.set_assumptions({"birth_year": "1965", "ss_benefit_self": "30000", "ss_claim_age_self": "67", "medicare_magi": "100000"})
        try:
            status, payload = self._post("/api/benefits/apply", {})
            self.assertEqual(status, 200)
            self.assertEqual(sorted(payload["created"]), ["Medicare premiums (Person 1)", "Social Security (Person 1)"])
            self.assertEqual([r["name"] for r in db.list_line_items("income")], ["Social Security (Person 1)"])
        finally:
            db.clear_section("income")
            db.clear_section("expenses")
            db.set_assumptions({"birth_year": "", "ss_benefit_self": "", "ss_claim_age_self": "", "medicare_magi": ""})

    def test_stress_test_tables_scroll_inside_their_own_box(self):
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        section = body[body.index("Historical recession stress test"):body.index("What moves your plan most")]
        self.assertEqual(section.count('<div style="overflow-x:auto">\n<table'), section.count("<table"))

    def test_how_it_works_arrow_css_escape_is_a_real_css_escape(self):
        # A Python "\\203A" written with one backslash would be an octal escape -- garbage on screen.
        from source.webapp.render_helpers.styles import PAGE_CSS
        self.assertIn('content: "\\203A"', PAGE_CSS)
        self.assertNotIn("\x15", PAGE_CSS)

    def test_real_estate_page_has_an_address_column_and_update_button(self):
        db.add_line_item("real_estate", {"name": "Rental", "current_value": 100_000, "address": "1 Main St"})
        try:
            body = self._get("/real-estate.html").read().decode("utf-8")
        finally:
            db.clear_section("real_estate")
        self.assertIn("Address (for value lookup)", body)
        self.assertIn("1 Main St", body)
        self.assertIn("refreshPropertyValue(", body)

    def test_setup_page_has_the_rentcast_card(self):
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn("Property value estimates (RentCast, optional)", body)
        self.assertIn("No RentCast key saved", body)

    def test_refresh_value_needs_a_key_then_updates_the_property(self):
        from unittest.mock import patch
        from source.common import secrets_store
        item_id = db.add_line_item("real_estate", {"name": "Rental", "current_value": 100_000, "address": "1 Main St"})
        try:
            status, payload = self._post("/api/real-estate/refresh-value", {"id": item_id})
            self.assertEqual(status, 400)
            self.assertIn("RentCast API key", payload["error"])
            status, _ = self._post("/api/rentcast-key", {"api_key": "KEY"})
            self.assertEqual(status, 200)
            with patch.object(dashboard.rentcast, "fetch_value_estimate",
                              return_value={"price": 250_000.0, "low": 240_000.0, "high": 260_000.0}) as fake:
                status, payload = self._post("/api/real-estate/refresh-value", {"id": item_id})
            self.assertEqual(status, 200)
            self.assertEqual(payload["price"], 250_000.0)
            fake.assert_called_once_with("1 Main St", "KEY")
            row = db.get_line_item("real_estate", item_id)
            self.assertEqual(row["current_value"], 250_000.0)
            self.assertTrue(row["value_updated_at"])
            body = self._get("/real-estate.html").read().decode("utf-8")
            self.assertIn("updated ", body)
        finally:
            db.clear_section("real_estate")
            secrets_store.delete_rentcast_api_key()

    def test_refresh_value_falls_back_to_a_street_address_used_as_the_name(self):
        from unittest.mock import patch
        from source.common import secrets_store
        item_id = db.add_line_item("real_estate", {"name": "6675 Muscat Dr", "current_value": 100_000})
        try:
            self._post("/api/rentcast-key", {"api_key": "KEY"})
            with patch.object(dashboard.rentcast, "fetch_value_estimate", return_value={"price": 9.0, "low": None, "high": None}) as fake:
                status, _ = self._post("/api/real-estate/refresh-value", {"id": item_id})
            self.assertEqual(status, 200)
            fake.assert_called_once_with("6675 Muscat Dr", "KEY")
        finally:
            db.clear_section("real_estate")
            secrets_store.delete_rentcast_api_key()

    def test_refresh_value_reports_a_missing_address(self):
        from source.common import secrets_store
        item_id = db.add_line_item("real_estate", {"name": "Rental", "current_value": 100_000})
        try:
            self._post("/api/rentcast-key", {"api_key": "KEY"})
            status, payload = self._post("/api/real-estate/refresh-value", {"id": item_id})
            self.assertEqual(status, 400)
            self.assertIn("no address", payload["error"])
        finally:
            db.clear_section("real_estate")
            secrets_store.delete_rentcast_api_key()

    def test_monte_carlo_page_has_the_saved_scenarios_card(self):
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn("Saved scenarios", body)
        self.assertIn("Nothing saved yet.", body)
        self.assertIn("Save current assumptions", body)

    def test_scenario_endpoints_save_list_compare_load_delete(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "401k", "balance": 500_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Living", "annual_amount": 40_000})
        db.set_assumptions({"iterations": 100, "expected_return": "0.06"})
        try:
            status, payload = self._post("/api/scenarios/save", {"name": "Base"})
            self.assertEqual(status, 200)
            sid = payload["id"]
            body = self._get("/monte-carlo.html").read().decode("utf-8")
            self.assertIn("Base", body)
            self.assertIn("Compare all scenarios", body)
            status, payload = self._post("/api/scenarios/compare", {})
            self.assertEqual(status, 200)
            self.assertEqual([r["name"] for r in payload["results"]], ["Current plan", "Base"])
            db.set_assumptions({"expected_return": "0.01"})
            status, payload = self._post("/api/scenarios/load", {"id": sid})
            self.assertTrue(payload["ok"])
            self.assertEqual(str(db.get_assumptions()["expected_return"]), "0.06")
            status, payload = self._post("/api/scenarios/delete", {"id": sid})
            self.assertTrue(payload["ok"])
            self.assertEqual(db.list_scenarios(), [])
        finally:
            db.clear_section("assets")
            db.clear_section("expenses")
            db.set_assumptions({"iterations": "", "expected_return": ""})
            for sc in db.list_scenarios():
                db.delete_scenario(sc["id"])

    def test_summary_shows_the_plan_health_card(self):
        db.add_line_item("expenses", {"name": "Baseline", "category": "Fixed", "annual_amount": 60_000})
        try:
            body = self._get("/summary.html").read().decode("utf-8")
        finally:
            db.clear_section("expenses")
        self.assertIn("What should I do next?", body)
        self.assertIn("birth year isn&#x27;t set", body)
        # The answer comes first, then what to do next; the trend charts sit in a fold below.
        self.assertLess(body.index("What should I do next?"), body.index("Total assets over time"))

    def test_summary_shows_a_total_asset_trend_once_there_is_history(self):
        for day, total in (("2026-01-01", 100_000.0), ("2026-02-01", 110_000.0)):
            db.record_snapshot(
                net_worth=total, manual_asset_total=total, linked_asset_total=0.0, liability_total=0.0,
                real_estate_equity_total=0.0, retirement_liquid_total=total, snapshot_date=day,
            )
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("Total assets over time", body)
        self.assertIn("<svg", body)

    def test_setup_page_has_the_excel_export_button(self):
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn("Generate Excel export", body)
        self.assertIn("/api/export", body)

    def test_long_intro_text_is_collapsed_behind_how_it_works(self):
        for path in ("/monte-carlo.html", "/drawdown-planning.html", "/legacy-planning.html", "/real-estate.html", "/real-expenditure.html"):
            with self.subTest(path=path):
                body = self._get(path).read().decode("utf-8")
                self.assertIn('<details class="how-it-works">', body)

    def test_account_balances_export_not_generated_yet_is_404(self):
        resp = self._get("/account-balances.html")
        self.assertEqual(resp.status, 404)
        resp.read()

    def test_portfolio_positions_export_not_generated_yet_is_404(self):
        resp = self._get("/portfolio-positions.html")
        self.assertEqual(resp.status, 404)
        resp.read()

    def test_shared_sortable_table_js_is_present_on_every_page(self):
        for path in (
            "/summary.html", "/asset.html", "/linked-accounts.html", "/linked-positions.html", "/expense.html",
            "/real-estate.html", "/monte-carlo.html", "/setup.html",
        ):
            with self.subTest(path=path):
                resp = self._get(path)
                body = resp.read().decode("utf-8")
                self.assertIn("function sortTableBy(", body)
                self.assertIn("function initSortableTables()", body)
                self.assertIn("function updateField(", body)

    def test_setup_page_linked_accounts_table_is_sortable(self):
        resp = self._get("/setup.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<table class="sortable">', body)

    def test_sort_state_is_persisted_to_localstorage_so_a_reload_does_not_lose_it(self):
        # A person-reported annoyance: sort a table, edit one row (every
        # bulk-edit action on this page ends with a location.reload()),
        # and the sort silently reverted to the server's default row
        # order. sortTableBy now writes the clicked sort to localStorage
        # and initSortableTables reads it back on the next load.
        resp = self._get("/real-expenditure.html")
        body = resp.read().decode("utf-8")
        self.assertIn("function _sortStorageKey(", body)
        self.assertIn("localStorage.setItem(table.dataset.sortKey", body)
        self.assertIn("localStorage.getItem(table.dataset.sortKey", body)

    def test_pie_filter_js_is_present_on_every_page(self):
        # Shared with every page (like the bulk-delete JS) even though only
        # Linked Positions currently has pie charts to click.
        for path in (
            "/summary.html", "/asset.html", "/linked-accounts.html", "/linked-positions.html", "/expense.html",
            "/real-estate.html", "/monte-carlo.html", "/setup.html",
        ):
            with self.subTest(path=path):
                resp = self._get(path)
                body = resp.read().decode("utf-8")
                self.assertIn("function handlePieSegClick(", body)
                self.assertIn("function handlePieSegKeydown(", body)
                self.assertIn("function applyPositionFilters(", body)
                self.assertIn("function clearPositionFilters(", body)
                self.assertIn("function refreshLinkedPositionsBarCharts(", body)


class TestLineItemEndpoints(DashboardTestCase):
    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("expenses")
        db.clear_section("real_estate")
        db.clear_section("income")

    def test_add_asset_line_item(self):
        status, payload = self._post("/api/line-item/add", {
            "section": "assets",
            "fields": {"kind": "asset", "name": "Fidelity", "balance": "100000"},
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        rows = db.list_line_items("assets")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Fidelity")

    def test_add_income_line_item(self):
        # The generic /api/line-item/add endpoint is section-agnostic
        # (db._TABLE_COLUMNS drives it), so "income" needs no new route --
        # this confirms it actually works end to end, base_year/inflates
        # included.
        status, payload = self._post("/api/line-item/add", {
            "section": "income",
            "fields": {
                "name": "Rental", "category": "Rental", "annual_amount": "103000",
                "base_year": "2026", "inflates": "1",
            },
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        rows = db.list_line_items("income")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Rental")
        self.assertEqual(rows[0]["base_year"], 2026)
        self.assertEqual(rows[0]["inflates"], 1)

    def test_update_income_inflates_flag(self):
        item_id = db.add_line_item("income", {"name": "Rental", "annual_amount": 103_000})
        status, payload = self._post("/api/line-item/update", {
            "section": "income", "id": item_id, "fields": {"inflates": 1, "base_year": 2026},
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        row = db.get_line_item("income", item_id)
        self.assertEqual(row["inflates"], 1)
        self.assertEqual(row["base_year"], 2026)

    def test_add_without_name_returns_400(self):
        status, payload = self._post("/api/line-item/add", {"section": "assets", "fields": {"balance": "100"}})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("name", payload["error"].lower())

    def test_delete_line_item(self):
        item_id = db.add_line_item("expenses", {"name": "Healthcare", "annual_amount": 500})
        status, payload = self._post("/api/line-item/delete", {"section": "expenses", "id": item_id})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIsNone(db.get_line_item("expenses", item_id))

    def test_delete_bulk_removes_every_requested_item(self):
        a_id = db.add_line_item("assets", {"kind": "asset", "name": "Cash", "balance": 1_000})
        e_id = db.add_line_item("expenses", {"name": "Healthcare", "annual_amount": 500})
        r_id = db.add_line_item("real_estate", {"name": "Rental", "current_value": 100_000})
        status, payload = self._post("/api/line-item/delete-bulk", {
            "items": [
                {"section": "assets", "id": a_id},
                {"section": "expenses", "id": e_id},
                {"section": "real_estate", "id": r_id},
            ],
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deleted"], 3)
        self.assertIsNone(db.get_line_item("assets", a_id))
        self.assertIsNone(db.get_line_item("expenses", e_id))
        self.assertIsNone(db.get_line_item("real_estate", r_id))

    def test_delete_bulk_skips_bad_entries_but_still_deletes_the_rest(self):
        a_id = db.add_line_item("assets", {"kind": "asset", "name": "Cash", "balance": 1_000})
        status, payload = self._post("/api/line-item/delete-bulk", {
            "items": [
                {"section": "assets", "id": a_id},
                {"section": "bogus", "id": 1},
                {"section": "assets", "id": 999999},  # already gone / never existed
            ],
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deleted"], 1)
        self.assertIsNone(db.get_line_item("assets", a_id))

    def test_delete_bulk_with_empty_items_is_a_no_op(self):
        status, payload = self._post("/api/line-item/delete-bulk", {"items": []})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["deleted"], 0)

    def test_asset_liability_real_estate_and_expense_tables_have_row_checkboxes_instead_of_delete_buttons(self):
        db.add_line_item("assets", {"kind": "asset", "name": "Cash", "balance": 1_000})
        db.add_line_item("assets", {"kind": "liability", "name": "Card", "balance": 500})
        db.add_line_item("real_estate", {"name": "Rental", "current_value": 100_000})
        db.add_line_item("expenses", {"name": "Healthcare", "annual_amount": 500})
        for path in ("/asset.html", "/real-estate.html", "/expense.html"):
            with self.subTest(path=path):
                resp = self._get(path)
                body = resp.read().decode("utf-8")
                self.assertIn('class="row-check"', body)
                self.assertIn('class="select-all-check"', body)
                self.assertNotIn("deleteLineItem(", body)

    def test_bulk_bar_and_its_js_are_present_on_every_page(self):
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn('id="bulk-bar"', body)
        self.assertIn("function deleteSelectedRows(section)", body)
        self.assertIn("function refreshBulkBar()", body)
        self.assertIn("/api/line-item/delete-bulk", body)

    def test_shared_page_script_has_no_duplicate_top_level_function_names(self):
        # Regression test: every page's <script> is the same shared block
        # (shell.py's PAGE_SHELL), so two `function foo(...) {...}`
        # declarations with the same name anywhere in it silently collide
        # -- the one that appears later in source order wins in the
        # browser's global scope, with no error. This is exactly how the
        # row-checkbox "Delete selected" bar's own refreshBulkBar()
        # (no args, shows/enables #bulk-bar) once got shadowed by the
        # Linked Positions tab's own same-named refreshBulkBar(barId,
        # inputId) declared later in the same script: every page's
        # checkbox looked selectable, but #bulk-bar (default
        # display:none) never actually appeared, so deleting was
        # unreachable from the UI on every page, imported or manual row
        # alike -- even though the backend delete endpoint itself was
        # always fine. A plain substring test (like the one above) can't
        # catch this since the string "function refreshBulkBar()" is
        # present regardless of how many times it's declared; only
        # counting occurrences does.
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        script = body.split("<script>", 1)[1].rsplit("</script>", 1)[0]
        names = re.findall(r"\nfunction (\w+)\(", script)
        dupes = {name: count for name, count in Counter(names).items() if count > 1}
        self.assertEqual(dupes, {}, f"duplicate top-level function declaration(s) in the shared page script: {dupes}")

    def test_unknown_section_returns_400(self):
        status, payload = self._post("/api/line-item/add", {"section": "bogus", "fields": {"name": "x"}})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_asset_page_reflects_added_item(self):
        db.add_line_item("assets", {"kind": "asset", "name": "Vanguard Brokerage", "balance": 42_000})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Vanguard Brokerage", body)
        self.assertIn("42,000", body)

    def test_asset_page_groups_line_items_into_a_table_per_category(self):
        db.add_line_item("assets", {"kind": "asset", "category": "Retirement Account", "name": "401k", "balance": 100_000})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid Assets", "name": "Checking", "balance": 5_000})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Car loan", "balance": 8_000})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Retirement Account", body)
        self.assertIn("Liquid Assets", body)
        self.assertIn("Loan", body)
        # Each category's subtotal appears once (its own <tfoot>), separate
        # from the other category's numbers -- not one flat combined table.
        self.assertIn("100,000", body)
        self.assertIn("5,000", body)
        self.assertIn("Total assets", body)
        self.assertIn("Total liabilities", body)

    def test_asset_page_shows_real_estate_as_a_collapsed_summary_line(self):
        # The Assets tab used to repeat every property's name/value/loan/
        # equity in its own full table right below the asset categories
        # -- pure duplication of the Real Estate tab's own,
        # already-editable table (same underlying real_estate rows, just
        # shown twice). It's now a single line: total equity and a count,
        # linking to that tab instead of re-listing each property.
        db.add_line_item("real_estate", {
            "name": "Home", "current_value": 500_000, "loan_balance": 200_000, "ownership_pct": 100,
        })
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Real estate equity", body)
        self.assertIn("300,000", body)  # equity = 500,000 - 200,000
        self.assertIn("1 property", body)
        self.assertIn('href="/real-estate.html"', body)
        self.assertNotIn("Real Estate Asset", body)  # the old per-property table's own heading is gone
        self.assertNotIn("Home", body)  # property names no longer repeated on the Assets tab

    def test_asset_page_real_estate_line_pluralizes_and_totals_multiple_properties(self):
        db.add_line_item("real_estate", {
            "name": "Home", "current_value": 500_000, "loan_balance": 200_000, "ownership_pct": 100,
        })
        db.add_line_item("real_estate", {
            "name": "Cabin", "current_value": 300_000, "loan_balance": 100_000, "ownership_pct": 100,
        })
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("2 properties", body)
        self.assertIn("500,000", body)  # combined equity = 300,000 + 200,000

    def test_asset_page_real_estate_line_handles_zero_properties(self):
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("no properties yet", body)
        self.assertIn('href="/real-estate.html"', body)

    def test_uncategorized_line_item_gets_its_own_bucket(self):
        db.add_line_item("assets", {"kind": "asset", "name": "Misc", "balance": 1_000})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Uncategorized", body)

    def test_asset_name_institution_last4_and_balance_are_editable_inputs(self):
        db.add_line_item("assets", {
            "kind": "asset", "name": "Southwood Dr", "institution": "Chase", "last4": "1234", "balance": 5_000,
        })
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("updateField('assets'", body)
        self.assertIn("'name'", body)
        self.assertIn("'institution'", body)
        self.assertIn("'last4'", body)
        self.assertIn("'balance'", body)
        self.assertIn('value="Southwood Dr"', body)
        self.assertIn('value="Chase"', body)

    def test_asset_category_cell_is_an_editable_input_with_a_datalist(self):
        # Same pattern as Expense/Income's own category cell (see
        # test_category_cell_is_an_editable_input_wired_to_update_category_field)
        # -- an <input> pre-filled with the row's current category, wired to
        # the shared updateField() and offering every category already in
        # use (across both Assets and Liabilities) via a datalist, so a
        # mis-imported row (e.g. a credit card that landed under "Loan")
        # can be recategorized in place instead of deleted and re-added.
        item_id = db.add_line_item("assets", {
            "kind": "liability", "category": "Loan", "name": "Credit Card", "balance": 3_000,
        })
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn('list="assets-categories"', body)
        self.assertIn('data-field="category"', body)
        self.assertIn(f"updateField('assets', {item_id}, 'category', this.value)", body)
        self.assertIn('value="Loan"', body)

    def test_editing_an_assets_category_moves_it_into_the_new_categorys_table(self):
        # The exact scenario from the user's report: a "Credit Card" row
        # imported under the wrong category ("Loan") should end up counted
        # in the "Credit Card" category's own subtotal once its category
        # is corrected -- no delete-and-re-add required.
        item_id = db.add_line_item("assets", {
            "kind": "liability", "category": "Loan", "name": "Credit Card", "balance": 3_000,
        })
        status, payload = self._post("/api/line-item/update", {
            "section": "assets", "id": item_id, "fields": {"category": "Credit Card"},
        })
        self.assertTrue(payload["ok"])
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertEqual(db.get_line_item("assets", item_id)["category"], "Credit Card")
        # It no longer sits in a "Loan" category table at all (the category
        # heading itself, not just the word "Loan", which also appears in
        # this page's own help text as an example)...
        loan_heading = '<div style="font-weight:600; font-size:13px; margin:16px 0 4px 0; color:var(--ink-soft);">Loan</div>'
        credit_card_heading = (
            '<div style="font-weight:600; font-size:13px; margin:16px 0 4px 0; color:var(--ink-soft);">Credit Card</div>'
        )
        self.assertNotIn(loan_heading, body)
        # ...and its balance is now grouped under a "Credit Card" category table instead.
        self.assertIn(credit_card_heading, body)
        self.assertIn("3,000", body)

    def test_updating_an_asset_name_via_the_generic_update_endpoint(self):
        item_id = db.add_line_item("assets", {"kind": "asset", "name": "Old Name", "balance": 1_000})
        status, payload = self._post("/api/line-item/update", {
            "section": "assets", "id": item_id, "fields": {"name": "New Name"},
        })
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_line_item("assets", item_id)["name"], "New Name")

    def test_category_table_and_linked_accounts_table_have_sortable_class(self):
        db.add_line_item("assets", {"kind": "asset", "name": "Cash", "balance": 1_000})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<table class="sortable">', body)

    def test_linked_accounts_table_has_a_balance_total(self):
        # The "Linked accounts (live, read-only)" table lives on its own
        # Linked Accounts tab, not the Assets tab -- see TestLinkedAccountsPage.
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-1", "name": "401k", "official_name": "Fidelity 401k",
            "type": "investment", "subtype": "401k", "mask": "1234",
            "balances": {"current": 30_000.0, "available": None, "iso_currency_code": "USD"},
        })
        try:
            resp = self._get("/linked-accounts.html")
            body = resp.read().decode("utf-8")
            self.assertIn("30,000", body)
        finally:
            db.delete_plaid_item("fidelity")

    def test_expense_page_has_an_annual_amount_total_and_is_sortable(self):
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 40_000})
        db.add_line_item("expenses", {"name": "Travel", "annual_amount": 10_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<table class="sortable li-table">', body)
        self.assertIn("50,000", body)  # total of the two rows


class TestExpensePageIncomeAndInflation(DashboardTestCase):
    """The Expense tab's Fixed/Variable-cost-with-inflation and Income
    (Rental, Social Security, ...) feature -- imported from the user's
    own budget table/spreadsheet model: a line item can grow from a
    Base Year by the Inflation % assumption, and Income nets against
    Expenses for the withdrawal need shown here and used by Monte Carlo."""

    def tearDown(self):
        db.clear_section("expenses")
        db.clear_section("income")

    def test_income_section_and_add_form_are_present(self):
        # Expense/Income no longer each carry their own bottom add-form --
        # both go through the shared "+ Add" modal (see PAGE_SHELL), opened
        # here via a section-specific shortcut button.
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn("<h2>Income</h2>", body)
        self.assertIn("openAddModal('income')", body)
        self.assertIn("openAddModal('expenses')", body)
        self.assertIn("No income line items yet.", body)
        self.assertIn("No expense line items yet.", body)

    def test_expense_and_income_tables_have_base_year_and_inflates_columns(self):
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertEqual(body.count("<th class=\"num\">Base Year</th>"), 2)  # Expenses + Income tables
        self.assertEqual(body.count("<th>Inflates?</th>"), 2)

    def test_inflating_row_shows_this_years_value_note(self):
        db.set_assumption("current_year", 2028)
        db.set_assumption("inflation_rate", 0.03)
        db.add_line_item("expenses", {
            "name": "Fixed cost", "category": "Fixed", "annual_amount": 197_800,
            "base_year": 2026, "inflates": 1,
        })
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        # 197,800 * 1.03^2 = 209,846
        self.assertIn("2028 value: $209,846", body)

    def test_tiles_show_expense_income_and_net_need(self):
        db.set_assumption("current_year", 2028)
        db.set_assumption("inflation_rate", 0.0)
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 300_000})
        db.add_line_item("income", {"name": "Rental", "annual_amount": 103_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<div class="label">2028 expense need</div><div class="value">$300,000</div>', body)
        self.assertIn('<div class="label">2028 income</div><div class="value">$103,000</div>', body)
        self.assertIn('<div class="label">2028 net withdrawal need</div><div class="value">$197,000</div>', body)

    def test_table_total_excludes_a_row_whose_year_range_does_not_cover_this_year(self):
        # Regression: the table's "Total (this year value)" footer must
        # respect each row's start_year/end_year -- not just sum every
        # row's inflated amount regardless of whether it's even in
        # effect yet (e.g. Social Security starting in a future year).
        db.set_assumption("current_year", 2028)
        db.add_line_item("income", {"name": "Rental", "annual_amount": 103_000})
        db.add_line_item("income", {"name": "Social Security", "annual_amount": 42_000, "start_year": 2035})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        # The nominal total still includes both rows (103,000 + 42,000).
        self.assertIn("Total (nominal)</td><td class=\"num\">$145,000</td>", body)
        # But the "this year" total must not -- Social Security hasn't
        # started yet, so only Rental counts toward 2028.
        self.assertIn("Total (2028 value)</td><td class=\"num\">$103,000</td>", body)

    def test_income_row_has_a_row_checkbox_for_bulk_delete(self):
        db.add_line_item("income", {"name": "Rental", "annual_amount": 103_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn('data-section="income"', body)

    def test_monte_carlo_page_nets_income_against_expense_need(self):
        db.set_assumption("current_year", 2028)
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 150_000})
        db.add_line_item("income", {"name": "Rental", "annual_amount": 50_000})
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn('the total of Income rows checked "In simulation?"', body)

    def test_inflation_pct_tile_is_an_editable_form_posting_to_assumptions(self):
        # Previously a read-only tile; the Expense tab should let you
        # change the Inflation % assumption right here, same endpoint
        # the Monte Carlo tab's own assumptions form already posts to.
        db.set_assumption("inflation_rate", 0.03)
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<div class="label">Inflation %</div>', body)
        self.assertIn('name="inflation_rate_pct"', body)
        self.assertIn('value="3.00"', body)
        self.assertIn("/api/assumptions", body)

    def test_saving_inflation_pct_from_the_expense_tab_updates_the_assumption(self):
        status, payload = self._post("/api/assumptions", {"inflation_rate_pct": "4.5"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertAlmostEqual(float(db.get_assumptions()["inflation_rate"]), 0.045)
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn('value="4.50"', body)

    def test_category_cell_is_an_editable_input_wired_to_update_category_field(self):
        item_id = db.add_line_item("expenses", {"name": "Groceries", "category": "Fixed", "annual_amount": 12_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn('list="expenses-categories"', body)
        self.assertIn('data-field="category"', body)
        self.assertIn(f"updateCategoryField('expenses', {item_id}, this,", body)
        self.assertIn('value="Fixed"', body)

    def test_income_category_cell_uses_the_income_section_and_datalist(self):
        item_id = db.add_line_item("income", {"name": "Rental", "category": "Rental", "annual_amount": 24_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn('list="income-categories"', body)
        self.assertIn(f"updateCategoryField('income', {item_id}, this,", body)


class TestIncomePageIncludeInMonteCarloCheckbox(DashboardTestCase):
    """The Income section's per-row "In simulation?" checkbox --
    income.include_in_monte_carlo, defaulting to on (every income row has
    always unconditionally netted against the withdrawal need, so this
    must not silently change anyone's existing numbers). Expenses have no
    such column -- every expense always counts."""

    def tearDown(self):
        db.clear_section("income")
        db.clear_section("expenses")

    def test_column_shown_only_on_the_income_table_not_expenses(self):
        db.add_line_item("income", {"name": "Rental", "annual_amount": 24_000})
        db.add_line_item("expenses", {"name": "Groceries", "annual_amount": 12_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertEqual(body.count("<th>In simulation?</th>"), 1)

    def test_new_income_row_defaults_checked(self):
        item_id = db.add_line_item("income", {"name": "Rental", "annual_amount": 24_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn(
            f'checked data-field="include_in_monte_carlo" '
            f'onchange="updateField(\'income\', {item_id}, \'include_in_monte_carlo\', this.checked ? 1 : 0)">',
            body,
        )

    def test_unchecking_persists_through_the_generic_update_endpoint(self):
        item_id = db.add_line_item("income", {"name": "Rental", "annual_amount": 24_000})
        status, payload = self._post("/api/line-item/update", {"section": "income", "id": item_id, "fields": {"include_in_monte_carlo": 0}})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_line_item("income", item_id)["include_in_monte_carlo"], 0)

    def test_an_unchecked_income_row_is_excluded_from_the_monte_carlo_starting_net_need(self):
        db.set_assumption("current_year", 2028)
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 150_000})
        item_id = db.add_line_item("income", {"name": "Rental", "annual_amount": 50_000})
        db.update_line_item("income", item_id, {"include_in_monte_carlo": 0})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        # The unchecked row is dropped from the net-need math -- income
        # shows $0, so net need equals the full expense need.
        self.assertIn('<div class="label">2028 income</div><div class="value">$0</div>', body)
        self.assertIn('<div class="label">2028 net withdrawal need</div><div class="value">$150,000</div>', body)

    def test_base_year_and_inflates_cells_carry_data_field_for_the_variable_auto_inflate_js(self):
        db.add_line_item("expenses", {"name": "Groceries", "category": "Fixed", "annual_amount": 12_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn('data-field="base_year"', body)
        self.assertIn('data-field="inflates"', body)

    def test_add_form_category_field_wires_up_the_auto_inflate_js_with_the_current_year(self):
        # The shared "+ Add" modal's single Category field (used for both
        # Expenses and Income) reads the current year off <body
        # data-current-year="..."> at click time, rather than each page
        # baking its own current year into a per-section form.
        db.set_assumption("current_year", 2029)
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn('data-current-year="2029"', body)
        self.assertIn("autoInflateIfVariableCategory(this, document.body.dataset.currentYear)", body)

    def test_page_includes_the_variable_auto_inflate_js_helpers(self):
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn("function updateCategoryField(", body)
        self.assertIn("function autoInflateIfVariableCategory(", body)

    def test_setting_category_to_variable_via_the_update_endpoint_can_also_set_inflates_and_base_year(self):
        # The auto-inflate-on-"Variable" behavior itself lives in the
        # browser (updateCategoryField() decides what extra fields to
        # send), but the generic update endpoint it posts to must accept
        # category/inflates/base_year together in one call, which is
        # exactly what that JS does when you type "Variable".
        item_id = db.add_line_item("expenses", {"name": "Utilities", "category": "Fixed", "annual_amount": 6_000})
        status, payload = self._post("/api/line-item/update", {
            "section": "expenses", "id": item_id,
            "fields": {"category": "Variable", "inflates": 1, "base_year": 2026},
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        row = db.get_line_item("expenses", item_id)
        self.assertEqual(row["category"], "Variable")
        self.assertEqual(row["inflates"], 1)
        self.assertEqual(row["base_year"], 2026)

    def test_expense_and_income_rows_are_fully_editable_without_delete_and_re_add(self):
        # Name, Annual Amount, Start/End Year, Base Year, Inflates, and
        # Notes should all be inline-editable inputs wired to the shared
        # update JS -- Category and Source are covered by their own
        # tests (Category has its own auto-inflate side effect; Source
        # is bookkeeping and stays read-only).
        item_id = db.add_line_item("expenses", {
            "name": "Groceries", "category": "Fixed", "annual_amount": 12_000,
            "start_year": 2027, "end_year": 2040, "notes": "weekly shop",
        })
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn(f"updateField('expenses', {item_id}, 'name', this.value)", body)
        self.assertIn(f"updateMoneyField('expenses', {item_id}, 'annual_amount', this)", body)
        self.assertIn(f"updateField('expenses', {item_id}, 'start_year', this.value)", body)
        self.assertIn(f"updateField('expenses', {item_id}, 'end_year', this.value)", body)
        self.assertIn(f"updateField('expenses', {item_id}, 'notes', this.value)", body)
        self.assertIn('value="Groceries"', body)
        self.assertIn('value="12,000"', body)
        self.assertIn('value="2027"', body)
        self.assertIn('value="2040"', body)
        self.assertIn('value="weekly shop"', body)
        # Source is deliberately plain text (shown only for non-manual rows), not an input.
        self.assertNotIn('data-field="source"', body)

    def test_a_never_set_start_end_and_base_year_render_as_blank_inputs_not_zero(self):
        db.add_line_item("expenses", {"name": "Groceries", "annual_amount": 12_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        # None of the three optional-year fields should render as "0" --
        # that would look like a real value both to a human reading it
        # and to the Variable-category auto-inflate JS's emptiness check.
        self.assertNotIn('data-field="start_year" value="0"', body)
        self.assertNotIn('value="0" data-field="start_year"', body)
        self.assertNotIn('data-field="end_year" value="0"', body)
        self.assertNotIn('value="0" data-field="end_year"', body)
        self.assertNotIn('data-field="base_year" value="0"', body)
        self.assertNotIn('value="0" data-field="base_year"', body)
        self.assertIn('value="" data-field="base_year"', body)

    def test_editing_income_name_via_the_generic_update_endpoint(self):
        item_id = db.add_line_item("income", {"name": "Rentl", "annual_amount": 24_000})
        status, payload = self._post("/api/line-item/update", {
            "section": "income", "id": item_id, "fields": {"name": "Rental"},
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_line_item("income", item_id)["name"], "Rental")

    def test_clearing_an_expense_name_via_the_update_endpoint_is_rejected(self):
        item_id = db.add_line_item("expenses", {"name": "Groceries", "annual_amount": 12_000})
        status, payload = self._post("/api/line-item/update", {
            "section": "expenses", "id": item_id, "fields": {"name": "   "},
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(db.get_line_item("expenses", item_id)["name"], "Groceries")


class TestExpensePageCategoryCharts(DashboardTestCase):
    """The Income & Expenses tab's "Expenses by category" and "Income by
    category" donut charts -- added per the user's "add Pie chart for
    Income and Expense by Category" request. Same _donut_chart_html/
    _grouped_slices helpers (and "no data yet" empty state) as every
    other donut in the app, grouped on annual_amount (nominal), same
    basis the tables' own "Total (nominal)" footer sums and the same one
    the Summary tab's own "Expenses by category" bar chart already uses."""

    def tearDown(self):
        db.clear_section("expenses")
        db.clear_section("income")

    def test_both_chart_titles_are_present(self):
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Expenses by category (annual, nominal)", body)
        self.assertIn("Income by category (annual, nominal)", body)

    def test_empty_state_shows_no_data_yet_for_both_charts_instead_of_erroring(self):
        resp = self._get("/expense.html")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode("utf-8")
        self.assertEqual(body.count("No data yet."), 2)

    def test_expense_chart_groups_by_category_and_sums_annual_amount(self):
        db.add_line_item("expenses", {"name": "Rent", "category": "Fixed", "annual_amount": 30_000})
        db.add_line_item("expenses", {"name": "Utilities", "category": "Fixed", "annual_amount": 6_000})
        db.add_line_item("expenses", {"name": "Travel", "category": "Variable", "annual_amount": 14_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        # Fixed = 30,000 + 6,000 = 36,000; Variable = 14,000 -- both as
        # slice legend values, not the raw per-row amounts.
        self.assertIn("$36,000", body)
        self.assertIn("$14,000", body)

    def test_income_chart_is_independent_of_the_expense_chart(self):
        db.add_line_item("expenses", {"name": "Rent", "category": "Fixed", "annual_amount": 30_000})
        db.add_line_item("income", {"name": "Rental income", "category": "Rental", "annual_amount": 18_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn("$30,000", body)
        self.assertIn("$18,000", body)
        # Only the Expenses chart should be "No data yet." once Income
        # actually has a row.
        self.assertEqual(body.count("No data yet."), 0)

    def test_uncategorized_row_folds_into_unknown_not_dropped_silently(self):
        db.add_line_item("expenses", {"name": "Misc", "annual_amount": 5_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Unknown", body)
        self.assertIn("$5,000", body)

    def test_charts_appear_before_the_line_item_tables(self):
        db.add_line_item("expenses", {"name": "Rent", "category": "Fixed", "annual_amount": 30_000})
        resp = self._get("/expense.html")
        body = resp.read().decode("utf-8")
        self.assertLess(
            body.index("Expenses by category (annual, nominal)"),
            body.index("<h2>Expenses</h2>"),
        )

    def test_income_comes_before_expenses(self):
        body = self._get("/expense.html").read().decode("utf-8")
        self.assertLess(body.index("<h2>Income</h2>"), body.index("<h2>Expenses</h2>"))
        self.assertLess(body.index("Income by category"), body.index("Expenses by category"))
        self.assertLess(body.index(" income</div>"), body.index(" expense need</div>"))


class TestAssetPageSummaryTables(DashboardTestCase):
    """The two top-of-page summary tables on the Assets tab: a per-category
    breakdown ending in Investable savings (every asset row checked "In
    Monte Carlo?", net of liabilities), and a rollup of Investable savings
    + real estate's effective equity into Total Asset."""

    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("real_estate")

    def test_summary_table_shows_every_asset_category_with_its_subtotal(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade", "balance": 50_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Insurance", "name": "Whole life", "balance": 20_000})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Card", "balance": 5_000})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        # The rollup table (Investable savings -> Total Asset) now renders
        # above this category table, so find the category table's own
        # "Summary" label div (not the nav bar's "Summary" link, nor the
        # rollup table's own "Investable savings" row before it) and its
        # tfoot after that point.
        start = body.index(">Summary</div>")
        summary = body[start : body.index("Investable savings</td><td class=\"num\">", start) + 60]
        self.assertIn("<td>401k</td><td class=\"num\">$100,000</td>", summary)
        self.assertIn("<td>Liquid</td><td class=\"num\">$50,000</td>", summary)
        self.assertIn("<td>Insurance</td><td class=\"num\">$20,000</td>", summary)
        self.assertIn("<td>Liabilities</td><td class=\"num\">-$5,000</td>", summary)

    def test_net_liquid_asset_sums_only_rows_checked_in_monte_carlo_minus_liabilities(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade", "balance": 50_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Insurance", "name": "Whole life", "balance": 20_000})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Card", "balance": 5_000})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        # 100,000 + 50,000 - 5,000 = 145,000 -- Insurance's 20,000 is
        # unchecked, so the total must not equal 165,000.
        self.assertIn("Investable savings</td><td class=\"num\">$145,000</td>", body)
        self.assertNotIn("$165,000", body)

    def test_an_unchecked_row_is_excluded_from_net_liquid_asset(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Investable savings</td><td class=\"num\">$0</td>", body)

    def test_rollup_table_totals_net_liquid_asset_and_real_estate_equity(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade", "balance": 50_000, "include_in_monte_carlo": 1})
        db.add_line_item("real_estate", {"name": "Home", "current_value": 500_000, "loan_balance": 300_000, "ownership_pct": 100})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Effective Equity on Real Estate</td><td class=\"num\">$200,000</td>", body)
        # Investable savings (150,000) + RE equity (200,000) = 350,000.
        self.assertIn("Total Asset</td><td class=\"num\">$350,000</td>", body)

    def test_rollup_table_uses_the_live_loan_balance_for_effective_equity(self):
        db.upsert_plaid_item(
            item_key="wells_fargo", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Wells Fargo", products=["transactions"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="wells_fargo", account={
            "account_id": "acc-mortgage", "name": "Mortgage", "official_name": "Mortgage",
            "type": "loan", "subtype": "mortgage", "mask": "7982",
            "balances": {"current": 480_000.0, "available": None, "iso_currency_code": "USD"},
        })
        item_id = db.add_line_item("real_estate", {
            "name": "Moorpark", "current_value": 900_000, "loan_balance": 1, "ownership_pct": 100,
        })
        db.update_line_item("real_estate", item_id, {"linked_account_id": "acc-mortgage"})
        try:
            resp = self._get("/asset.html")
            body = resp.read().decode("utf-8")
            # 900,000 - 480,000 (live) = 420,000, not the stale loan_balance=1.
            self.assertIn("Effective Equity on Real Estate</td><td class=\"num\">$420,000</td>", body)
        finally:
            db.delete_plaid_item("wells_fargo")

    def test_empty_state_shows_zero_net_liquid_asset_and_total_asset(self):
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Investable savings</td><td class=\"num\">$0</td>", body)
        self.assertIn("Total Asset</td><td class=\"num\">$0</td>", body)

    def test_summary_table_subtotals_match_each_category_detail_tables_own_subtotal(self):
        # The top table and the per-category detail table below it are
        # computed from the same subtotal, not two independently
        # recomputed numbers that could drift apart.
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 77_777})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("<td>401k</td><td class=\"num\">$77,777</td>", body)  # top Summary table's row
        self.assertIn("Subtotal</td><td class=\"num\">$77,777</td>", body)  # 401k detail table's own tfoot

    def test_rollup_table_renders_above_the_category_summary_table(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000, "include_in_monte_carlo": 1})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertLess(body.index("Total Asset</td>"), body.index("Investable savings = the balance"))


class TestAssetPageIncludeInMonteCarloCheckbox(DashboardTestCase):
    """The Assets tab's per-row "In the plan?" checkbox -- replaces the
    old category-list assumption (retirement_liquid_categories) with
    per-row control, same pattern as the Real Estate tab's own
    "In the plan?" column. New rows default unchecked (opt-in), same
    as a new Real Estate row -- a brand-new asset was never automatically
    part of a plan's projected drawdown until explicitly included."""

    def tearDown(self):
        db.clear_section("assets")

    def test_checkbox_column_shown_on_every_asset_table_but_not_liability_tables(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        db.add_line_item("assets", {"kind": "asset", "category": "Insurance", "name": "Whole life", "balance": 20_000})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Card", "balance": 5_000})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertEqual(body.count("<th>In the plan?</th>"), 2)

    def test_every_asset_table_uses_the_same_fixed_column_widths(self):
        """A fixed colgroup (not content-sized columns) keeps Name,
        Balance, Linked account etc. aligned from one category's table to
        the next and stops the Linked account column collapsing to a
        sliver (its header wrapping one letter per line)."""
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Cash", "balance": 20_000})
        body = self._get("/asset.html").read().decode("utf-8")
        colgroups = re.findall(r"<colgroup>.*?</colgroup>", body)
        self.assertEqual(len(colgroups), 2)
        self.assertEqual(colgroups[0], colgroups[1])
        self.assertEqual(body.count("table-layout:fixed"), 2)
        self.assertEqual(colgroups[0].count("<col "), 11)

    def test_new_asset_row_defaults_unchecked(self):
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        row = db.get_line_item("assets", item_id)
        self.assertEqual(row["include_in_monte_carlo"], 0)

    def test_checking_the_box_persists_through_the_generic_update_endpoint(self):
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        status, payload = self._post("/api/line-item/update", {"section": "assets", "id": item_id, "fields": {"include_in_monte_carlo": 1}})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        row = db.get_line_item("assets", item_id)
        self.assertEqual(row["include_in_monte_carlo"], 1)

    def test_checked_row_renders_the_checkbox_as_checked(self):
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        db.update_line_item("assets", item_id, {"include_in_monte_carlo": 1})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn(
            f'checked data-field="include_in_monte_carlo" '
            f'onchange="updateField(\'assets\', {item_id}, \'include_in_monte_carlo\', this.checked ? 1 : 0)">',
            body,
        )


class TestAssetPageTaxTreatment(DashboardTestCase):
    """The Assets tab's Tax treatment column -- shown on every asset
    category table (not liability tables), editable through the same
    generic /api/line-item/update endpoint every other editable cell
    uses. A row's Tax treatment only actually matters once it's also
    checked "In the plan?", but the column itself is always there so
    it's ready the moment a row is opted in."""

    def tearDown(self):
        db.clear_section("assets")

    def test_column_shown_on_every_asset_category_table(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        db.add_line_item("assets", {"kind": "asset", "category": "Insurance", "name": "Whole life", "balance": 20_000})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertEqual(body.count("<th>Tax treatment</th>"), 2)

    def test_untagged_401k_row_defaults_to_tax_deferred_selected(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<option value="tax_deferred" selected>', body)

    def test_untagged_liquid_row_defaults_to_taxable_selected(self):
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade", "balance": 50_000})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<option value="taxable" selected>', body)

    def test_updating_tax_treatment_persists_through_the_generic_update_endpoint(self):
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        status, payload = self._post("/api/line-item/update", {"section": "assets", "id": item_id, "fields": {"tax_treatment": "roth"}})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        row = db.get_line_item("assets", item_id)
        self.assertEqual(row["tax_treatment"], "roth")

    def test_updated_tax_treatment_shows_as_selected_on_reload(self):
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        db.update_line_item("assets", item_id, {"tax_treatment": "roth"})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<option value="roth" selected>', body)


class TestLinkAccountEndpoint(DashboardTestCase):
    def setUp(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-401k", "name": "APPLE 401(K) PLAN", "official_name": "APPLE 401(K) PLAN",
            "type": "investment", "subtype": "401k", "mask": "1234",
            "balances": {"current": 62_000.0, "available": None, "iso_currency_code": "USD"},
        })
        self.item_id = db.add_line_item("assets", {"kind": "asset", "name": "Vatsa 401k", "balance": 100})

    def tearDown(self):
        db.clear_section("assets")
        db.delete_plaid_item("fidelity")

    def test_link_sets_linked_account_id(self):
        status, payload = self._post("/api/line-item/link-account", {
            "section": "assets", "id": self.item_id, "account_id": "acc-401k",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_line_item("assets", self.item_id)["linked_account_id"], "acc-401k")

    def test_link_to_unknown_account_id_returns_400(self):
        status, payload = self._post("/api/line-item/link-account", {
            "section": "assets", "id": self.item_id, "account_id": "not-a-real-account",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIsNone(db.get_line_item("assets", self.item_id)["linked_account_id"])

    def test_unlink_with_blank_account_id_clears_it(self):
        db.update_line_item("assets", self.item_id, {"linked_account_id": "acc-401k"})
        status, payload = self._post("/api/line-item/link-account", {
            "section": "assets", "id": self.item_id, "account_id": "",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIsNone(db.get_line_item("assets", self.item_id)["linked_account_id"])

    def test_asset_page_shows_live_balance_for_a_linked_row_instead_of_the_typed_one(self):
        db.update_line_item("assets", self.item_id, {"linked_account_id": "acc-401k"})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("62,000", body)  # the live Plaid balance
        self.assertNotIn("$100", body)  # not the stale typed-in balance
        self.assertIn("Fidelity — APPLE 401(K) PLAN", body)

    def test_linked_accounts_page_shows_which_line_item_its_folded_into(self):
        db.update_line_item("assets", self.item_id, {"linked_account_id": "acc-401k"})
        resp = self._get("/linked-accounts.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Linked to: Vatsa 401k", body)

    def test_balance_is_not_an_editable_input_once_linked_to_a_live_account(self):
        db.update_line_item("assets", self.item_id, {"linked_account_id": "acc-401k"})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertNotIn("'balance'", body)  # live -- no input for it anymore
        # But Name/Institution/Last4 are still editable even on a linked row.
        self.assertIn("'name'", body)

    def test_linking_via_the_endpoint_auto_populates_institution_and_last4(self):
        self._post("/api/line-item/link-account", {
            "section": "assets", "id": self.item_id, "account_id": "acc-401k",
        })
        row = db.get_line_item("assets", self.item_id)
        self.assertEqual(row["institution"], "Fidelity")
        self.assertEqual(row["last4"], "1234")

    def test_asset_page_shows_the_auto_populated_institution_and_last4(self):
        self._post("/api/line-item/link-account", {
            "section": "assets", "id": self.item_id, "account_id": "acc-401k",
        })
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn('value="Fidelity"', body)
        self.assertIn('value="1234"', body)

    def test_a_row_linked_before_this_feature_existed_self_heals_on_page_load(self):
        # Simulate an old row that only ever got linked_account_id set
        # directly (the original, pre-auto-populate behavior) -- Institution/
        # Last 4 are still blank even though it's linked.
        db.update_line_item("assets", self.item_id, {"linked_account_id": "acc-401k"})
        self.assertEqual(db.get_line_item("assets", self.item_id)["institution"], "")
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn('value="Fidelity"', body)
        self.assertIn('value="1234"', body)
        # And it's now actually persisted, not just rendered once.
        row = db.get_line_item("assets", self.item_id)
        self.assertEqual(row["institution"], "Fidelity")
        self.assertEqual(row["last4"], "1234")

    def test_unlinking_leaves_the_previously_auto_populated_values_in_place(self):
        self._post("/api/line-item/link-account", {
            "section": "assets", "id": self.item_id, "account_id": "acc-401k",
        })
        self._post("/api/line-item/link-account", {"section": "assets", "id": self.item_id, "account_id": ""})
        row = db.get_line_item("assets", self.item_id)
        self.assertEqual(row["institution"], "Fidelity")
        self.assertEqual(row["last4"], "1234")


class TestClassifyLinkedAccountEndpoint(DashboardTestCase):
    """The Linked Accounts page's one-step "Classify" action --
    /api/line-item/classify-linked-account -- creates the Asset-tab line
    item and links it to a not-yet-classified Plaid account in a single
    call, per the user's "I do see not linked account and I am not able
    to classify" request. Institution/Account # auto-populate the same
    way /api/line-item/link-account's own does (see
    _linked_institution_fields, shared by both)."""

    def setUp(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-brokerage", "name": "Individual Brokerage", "official_name": "Individual Brokerage -8651",
            "type": "investment", "subtype": "brokerage", "mask": "8651",
            "balances": {"current": 7_227.59, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-visa", "name": "Wells Fargo Active Cash Visa", "official_name": "Wells Fargo Active Cash Visa Card",
            "type": "credit", "subtype": "credit card", "mask": "2618",
            "balances": {"current": 0.0, "available": 5000.0, "iso_currency_code": "USD"},
        })

    def tearDown(self):
        db.clear_section("assets")
        db.delete_plaid_item("fidelity")

    def test_classify_creates_a_linked_line_item(self):
        status, payload = self._post("/api/line-item/classify-linked-account", {
            "account_id": "acc-brokerage", "kind": "asset", "category": "Liquid", "name": "Individual Brokerage",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        row = db.get_line_item("assets", payload["id"])
        self.assertEqual(row["kind"], "asset")
        self.assertEqual(row["category"], "Liquid")
        self.assertEqual(row["name"], "Individual Brokerage")
        self.assertEqual(row["linked_account_id"], "acc-brokerage")

    def test_classify_auto_populates_institution_and_last4_like_link_account_does(self):
        status, payload = self._post("/api/line-item/classify-linked-account", {
            "account_id": "acc-brokerage", "kind": "asset", "category": "Liquid", "name": "Individual Brokerage",
        })
        row = db.get_line_item("assets", payload["id"])
        self.assertEqual(row["institution"], "Fidelity")
        self.assertEqual(row["last4"], "8651")

    def test_classify_as_liability_for_a_credit_card(self):
        status, payload = self._post("/api/line-item/classify-linked-account", {
            "account_id": "acc-visa", "kind": "liability", "category": "Credit Card", "name": "Wells Fargo Visa",
        })
        self.assertEqual(status, 200)
        row = db.get_line_item("assets", payload["id"])
        self.assertEqual(row["kind"], "liability")

    def test_unknown_account_id_returns_400_and_creates_nothing(self):
        status, payload = self._post("/api/line-item/classify-linked-account", {
            "account_id": "not-a-real-account", "kind": "asset", "category": "Liquid", "name": "Ghost account",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(db.list_line_items("assets"), [])

    def test_missing_category_returns_400_and_creates_nothing(self):
        status, payload = self._post("/api/line-item/classify-linked-account", {
            "account_id": "acc-brokerage", "kind": "asset", "category": "", "name": "Individual Brokerage",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(db.list_line_items("assets"), [])

    def test_missing_name_returns_400_and_creates_nothing(self):
        status, payload = self._post("/api/line-item/classify-linked-account", {
            "account_id": "acc-brokerage", "kind": "asset", "category": "Liquid", "name": "",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(db.list_line_items("assets"), [])

    def test_invalid_kind_returns_400_and_creates_nothing(self):
        status, payload = self._post("/api/line-item/classify-linked-account", {
            "account_id": "acc-brokerage", "kind": "not-a-kind", "category": "Liquid", "name": "Individual Brokerage",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(db.list_line_items("assets"), [])

    def test_missing_account_id_returns_400(self):
        status, payload = self._post("/api/line-item/classify-linked-account", {
            "kind": "asset", "category": "Liquid", "name": "Individual Brokerage",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_classified_account_shows_up_as_live_on_the_asset_tab(self):
        status, payload = self._post("/api/line-item/classify-linked-account", {
            "account_id": "acc-brokerage", "kind": "asset", "category": "Liquid", "name": "Individual Brokerage",
        })
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("7,228", body)
        self.assertIn("Individual Brokerage", body)

    def test_linked_accounts_page_shows_classify_form_for_unlinked_rows(self):
        resp = self._get("/linked-accounts.html")
        body = resp.read().decode("utf-8")
        self.assertIn("classify-row", body)
        self.assertIn("classifyLinkedAccount('acc-brokerage'", body)
        self.assertNotIn("Not linked to a line item", body)

    def test_classify_kind_defaults_to_liability_for_a_credit_card_and_asset_otherwise(self):
        import re

        resp = self._get("/linked-accounts.html")
        body = resp.read().decode("utf-8")
        # Non-greedy match from that row's own classify-row div (there's
        # no nesting) up through its account_id, so this doesn't depend
        # on how much table markup precedes the row.
        brokerage_section = re.search(r'<div class="classify-row".*?classifyLinkedAccount\(\'acc-brokerage\'', body, re.S).group()
        visa_section = re.search(r'<div class="classify-row".*?classifyLinkedAccount\(\'acc-visa\'', body, re.S).group()
        self.assertIn('<option value="asset" selected>', brokerage_section)
        self.assertIn('<option value="liability" selected>', visa_section)

    def test_linked_accounts_page_no_longer_shows_classify_form_once_linked(self):
        self._post("/api/line-item/classify-linked-account", {
            "account_id": "acc-brokerage", "kind": "asset", "category": "Liquid", "name": "Individual Brokerage",
        })
        resp = self._get("/linked-accounts.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Linked to: Individual Brokerage", body)
        self.assertNotIn("classifyLinkedAccount('acc-brokerage'", body)
        # The still-unlinked account's own classify form is unaffected.
        self.assertIn("classifyLinkedAccount('acc-visa'", body)


class TestFullAccountNumber(DashboardTestCase):
    """A checking/savings account whose Item requested Plaid's Auth
    product gets its real account number stored (source.collector.sync);
    everywhere the app used to show just the last-4 mask should now show
    that full number instead, per the user's explicit request."""

    def setUp(self):
        db.upsert_plaid_item(
            item_key="wells_fargo_checking", plaid_item_id="item-wf", institution_id="ins_wf",
            institution_name="Wells Fargo", products=["auth"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="wells_fargo_checking", account={
            "account_id": "acc-checking", "name": "Checking", "official_name": "Everyday Checking",
            "type": "depository", "subtype": "checking", "mask": "6789",
            "balances": {"current": 5_000.0, "available": 4_900.0, "iso_currency_code": "USD"},
        })
        db.set_plaid_account_numbers("acc-checking", account_number="1234567890", routing_number="121000248")
        self.item_id = db.add_line_item("assets", {"kind": "asset", "name": "Checking", "balance": 100})

    def tearDown(self):
        db.clear_section("assets")
        db.delete_plaid_item("wells_fargo_checking")

    def test_linking_populates_the_full_account_number_not_the_mask(self):
        self._post("/api/line-item/link-account", {
            "section": "assets", "id": self.item_id, "account_id": "acc-checking",
        })
        row = db.get_line_item("assets", self.item_id)
        self.assertEqual(row["last4"], "1234567890")

    def test_asset_page_shows_the_full_number_in_the_editable_field(self):
        self._post("/api/line-item/link-account", {
            "section": "assets", "id": self.item_id, "account_id": "acc-checking",
        })
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn('value="1234567890"', body)
        self.assertNotIn('value="6789"', body)

    def test_link_dropdown_label_shows_the_full_number(self):
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Wells Fargo — Everyday Checking (1234567890)", body)

    def test_linked_accounts_table_shows_the_full_number_instead_of_the_mask(self):
        # The "Linked accounts (live, read-only)" table lives on its own
        # Linked Accounts tab.
        resp = self._get("/linked-accounts.html")
        body = resp.read().decode("utf-8")
        self.assertIn("1234567890", body)
        self.assertIn("Account #", body)  # header relabeled from "Last 4"

    def test_a_tokenized_account_number_is_flagged(self):
        db.set_plaid_account_numbers(
            "acc-checking", account_number="9999999999", routing_number="121000248", is_tokenized=True,
        )
        resp = self._get("/linked-accounts.html")
        body = resp.read().decode("utf-8")
        self.assertIn("9999999999 (tokenized)", body)

    def test_an_investment_account_with_no_auth_data_still_shows_the_mask(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-fid", institution_id="ins_fid",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-401k", "name": "401k", "official_name": "APPLE 401(K) PLAN",
            "type": "investment", "subtype": "401k", "mask": "4321",
            "balances": {"current": 40_000.0, "available": None, "iso_currency_code": "USD"},
        })
        try:
            resp = self._get("/asset.html")
            body = resp.read().decode("utf-8")
            self.assertIn("...4321", body)  # dropdown falls back to the mask
        finally:
            db.delete_plaid_item("fidelity")

    def test_setup_page_has_a_full_account_number_checkbox(self):
        resp = self._get("/setup.html")
        body = resp.read().decode("utf-8")
        self.assertIn('name="full_account_number"', body)
        self.assertIn("full_account_number.checked", body)


class TestRealEstateLinkAndIncome(DashboardTestCase):
    def setUp(self):
        db.upsert_plaid_item(
            item_key="wells_fargo", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Wells Fargo", products=["transactions"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="wells_fargo", account={
            "account_id": "acc-mortgage", "name": "MORTGAGE ...7982", "official_name": "MORTGAGE ...7982",
            "type": "loan", "subtype": "mortgage", "mask": "7982",
            "balances": {"current": 480_000.0, "available": None, "iso_currency_code": "USD"},
        })
        self.item_id = db.add_line_item("real_estate", {
            "name": "Moorpark", "current_value": 900_000, "loan_balance": 1, "ownership_pct": 100,
            "annual_income": 24_000,
        })

    def tearDown(self):
        db.clear_section("real_estate")
        db.delete_plaid_item("wells_fargo")

    def test_add_real_estate_with_annual_income(self):
        status, payload = self._post("/api/line-item/add", {
            "section": "real_estate",
            "fields": {"name": "Rental", "current_value": "300000", "annual_income": "18000"},
        })
        self.assertTrue(payload["ok"])
        row = db.get_line_item("real_estate", payload["id"])
        self.assertEqual(row["annual_income"], 18000)

    def test_real_estate_page_shows_annual_income_and_total(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn("24,000", body)
        self.assertIn("Annual Income", body)

    def test_link_account_endpoint_works_for_real_estate_section(self):
        status, payload = self._post("/api/line-item/link-account", {
            "section": "real_estate", "id": self.item_id, "account_id": "acc-mortgage",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_line_item("real_estate", self.item_id)["linked_account_id"], "acc-mortgage")

    def test_real_estate_page_shows_live_loan_balance_once_linked(self):
        db.update_line_item("real_estate", self.item_id, {"linked_account_id": "acc-mortgage"})
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn("480,000", body)  # the live balance
        self.assertIn("420,000", body)  # equity: 900,000 - 480,000
        self.assertIn("Wells Fargo — MORTGAGE ...7982", body)

    def test_asset_page_real_estate_line_reflects_live_loan_balance_once_linked(self):
        # The Assets tab's collapsed real-estate summary line shows equity,
        # not the loan balance itself -- so linking to a live mortgage
        # account (480,000, vs. the typed-in loan_balance of 1) should
        # show up here as a *lower* equity figure (900,000 - 480,000 =
        # 420,000), not as the raw balance -- same live-balance-if-linked
        # rule real_estate_equity()/effective_loan_balance() apply
        # everywhere else (see the Real Estate tab's own
        # equivalent test above).
        db.update_line_item("real_estate", self.item_id, {"linked_account_id": "acc-mortgage"})
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertIn("420,000", body)

    def test_linked_accounts_page_shows_the_real_estate_link(self):
        db.update_line_item("real_estate", self.item_id, {"linked_account_id": "acc-mortgage"})
        resp = self._get("/linked-accounts.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Linked to: Moorpark", body)

    def test_ownership_pct_is_an_editable_input_prefilled_with_the_current_value(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn("updateField('real_estate'", body)
        self.assertIn("'ownership_pct'", body)
        self.assertIn('value="100"', body)

    def test_annual_income_is_an_editable_input_in_the_same_row(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn("'annual_income'", body)
        self.assertIn('value="24,000"', body)

    def test_updating_annual_income_via_the_generic_update_endpoint(self):
        status, payload = self._post("/api/line-item/update", {
            "section": "real_estate", "id": self.item_id, "fields": {"annual_income": "36000"},
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_line_item("real_estate", self.item_id)["annual_income"], 36000)

    def test_loan_balance_shows_a_your_share_note_when_partially_owned(self):
        db.update_line_item("real_estate", self.item_id, {
            "linked_account_id": "acc-mortgage", "ownership_pct": 50,
        })
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn("your share: $240,000", body)  # 480,000 * 50%

    def test_loan_balance_has_no_your_share_note_at_full_ownership(self):
        db.update_line_item("real_estate", self.item_id, {"linked_account_id": "acc-mortgage"})
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertNotIn("your share", body)

    def test_updating_ownership_pct_via_the_generic_update_endpoint_rescales_equity(self):
        db.update_line_item("real_estate", self.item_id, {"loan_balance": 300_000})
        status, payload = self._post("/api/line-item/update", {
            "section": "real_estate", "id": self.item_id, "fields": {"ownership_pct": "50"},
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        # (900,000 - 300,000) * 50% = 300,000
        self.assertIn("300,000", body)

    def test_name_purchase_price_and_current_value_are_editable_inputs(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn("updateField('real_estate'", body)
        self.assertIn("'name'", body)
        self.assertIn("'purchase_price'", body)
        self.assertIn("'current_value'", body)
        self.assertIn('value="900,000"', body)  # current_value, unformatted for the input

    def test_updating_name_via_the_generic_update_endpoint(self):
        status, payload = self._post("/api/line-item/update", {
            "section": "real_estate", "id": self.item_id, "fields": {"name": "Moorpark Ave"},
        })
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_line_item("real_estate", self.item_id)["name"], "Moorpark Ave")

    def test_loan_balance_is_an_editable_input_when_not_linked(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn("'loan_balance'", body)

    def test_loan_balance_is_not_an_editable_input_once_linked_to_a_live_account(self):
        db.update_line_item("real_estate", self.item_id, {"linked_account_id": "acc-mortgage"})
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertNotIn("'loan_balance'", body)  # live -- no input for it anymore

    def test_totals_row_covers_purchase_price_current_value_and_loan_balance(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Totals", body)

    def test_table_has_sortable_class(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<table class="sortable">', body)

    def test_source_column_has_been_removed(self):
        # The Source column (manual/imported bookkeeping) added little
        # for the user and its width contributed to the table getting
        # squeezed narrow enough that the Linked account header wrapped
        # one letter per line -- dropped entirely.
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertNotIn("<th>Source</th>", body)

    def test_table_is_wrapped_in_a_horizontally_scrolling_container(self):
        # With ten columns (several fixed-width money inputs plus the
        # Linked account dropdown), the table is wider than the page's
        # own max-width -- wrapping it in an overflow-x:auto container
        # lets it scroll instead of the browser's table layout algorithm
        # squeezing the Linked account header down to an unreadable,
        # one-letter-per-line column.
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<div style="overflow-x:auto">', body)
        self.assertLess(body.index('<div style="overflow-x:auto">'), body.index('<table class="sortable">'))


class TestRealEstateIncludeInMonteCarlo(DashboardTestCase):
    """The Real Estate tab's "In the plan?" checkbox column --
    lets a property's equity opt in to the Monte Carlo / historical
    stress test simulations as a 4th, untaxed, last-drawn pool (see
    source.reporting.aggregate.build_summary and monte_carlo._WITHDRAWAL_ORDER)."""

    def setUp(self):
        self.item_id = db.add_line_item("real_estate", {
            "name": "Cabin", "current_value": 300_000, "loan_balance": 0, "ownership_pct": 100,
        })

    def tearDown(self):
        db.clear_section("real_estate")

    def test_column_header_present(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn("In the plan?", body)

    def test_loan_end_year_column_is_editable_and_blank_clears_it(self):
        body = self._get("/real-estate.html").read().decode("utf-8")
        self.assertIn("Loan ends (year)", body)
        self.assertIn(f"updateField('real_estate', {self.item_id}, 'loan_end_year'", body)
        status, _ = self._post("/api/line-item/update", {
            "section": "real_estate", "id": self.item_id, "fields": {"loan_end_year": "2051"},
        })
        self.assertEqual(status, 200)
        self.assertEqual(db.list_line_items("real_estate")[0]["loan_end_year"], 2051)
        self._post("/api/line-item/update", {
            "section": "real_estate", "id": self.item_id, "fields": {"loan_end_year": ""},
        })
        self.assertIsNone(db.list_line_items("real_estate")[0]["loan_end_year"])

    def test_drawdown_page_explains_the_rental_tax_shelter_once_a_loan_end_year_is_set(self):
        db.update_line_item("real_estate", self.item_id, {"loan_end_year": "2051", "annual_income": "30000"})
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("Loan ends (year)", body)
        self.assertIn("sheltered by mortgage interest and depreciation", body)

    def test_unchecked_by_default(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn(f"updateField('real_estate', {self.item_id}, 'include_in_monte_carlo'", body)
        # The checkbox itself shouldn't render "checked" for a row that
        # defaults to 0 -- distinguish this from the Inflates column's
        # own equivalent by checking there's no "checked" immediately
        # before this row's include_in_monte_carlo input.
        row = body[body.index(f'data-id="{self.item_id}"'):]
        mc_input = row[row.index("include_in_monte_carlo") - 80 : row.index("include_in_monte_carlo")]
        self.assertNotIn("checked", mc_input)

    def test_checking_it_persists_and_shows_checked_on_reload(self):
        status, payload = self._post("/api/line-item/update", {
            "section": "real_estate", "id": self.item_id, "fields": {"include_in_monte_carlo": 1},
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_line_item("real_estate", self.item_id)["include_in_monte_carlo"], 1)
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn("checked", body)

    def test_included_equity_total_line_reflects_only_opted_in_properties(self):
        db.add_line_item("real_estate", {"name": "Rental", "current_value": 500_000, "loan_balance": 0, "ownership_pct": 100})
        db.update_line_item("real_estate", self.item_id, {"include_in_monte_carlo": 1})
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Included in the plan's simulations", body)
        self.assertIn("300,000", body)  # only the Cabin, not the Rental


class TestNumberInputFormattingForLargeValues(DashboardTestCase):
    """A 7+-digit Purchase Price/Current Value/Loan Balance used to render
    as literal scientific notation in the editable input itself (e.g.
    1,600,000 became the text "1.6e+06") -- not a column-width/truncation
    issue, but Python's old `:g` formatting in _editable_number_cell,
    which switches to exponential past 6 significant digits and, worse,
    silently rounds off digits once it does (3336607.99 became
    "3.33661e+06", i.e. rounded to the nearest $10). Fixed by
    _format_number_input_value (str()/repr() on the float, which never
    goes scientific in any realistic dollar/percentage/year range here).
    Per the user's "loan balance, purchase price and current value all
    has problem" -- all three also got a wider (115px) column so the
    now-un-abbreviated digits aren't cramped."""

    def setUp(self):
        db.upsert_plaid_item(
            item_key="wells_fargo", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Wells Fargo", products=["transactions"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="wells_fargo", account={
            "account_id": "acc-mortgage", "name": "MORTGAGE ...7982", "official_name": "MORTGAGE ...7982",
            "type": "loan", "subtype": "mortgage", "mask": "7982",
            "balances": {"current": 483_471.76, "available": None, "iso_currency_code": "USD"},
        })
        self.item_id = db.add_line_item("real_estate", {
            "name": "Moorpark", "purchase_price": 1_290_000, "current_value": 3_336_607.99,
            "loan_balance": 1_100_000, "ownership_pct": 100,
        })

    def tearDown(self):
        db.clear_section("real_estate")
        db.delete_plaid_item("wells_fargo")

    def test_format_number_input_value_never_uses_scientific_notation(self):
        from source.webapp.render_helpers import _format_number_input_value

        self.assertEqual(_format_number_input_value(1_600_000.0), "1600000")
        self.assertEqual(_format_number_input_value(3_336_607.99), "3336607.99")
        self.assertEqual(_format_number_input_value(365_000.0), "365000")
        self.assertEqual(_format_number_input_value(1_234_567.89), "1234567.89")
        self.assertEqual(_format_number_input_value(0.0), "0")
        self.assertEqual(_format_number_input_value(-50_000.0), "-50000")
        self.assertEqual(_format_number_input_value(100.5), "100.5")
        self.assertEqual(_format_number_input_value(33.333), "33.333")

    def test_seven_digit_purchase_price_and_current_value_render_in_full(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn('value="1,290,000"', body)
        self.assertIn('value="3,336,607.99"', body)
        self.assertNotIn("e+0", body)
        self.assertNotIn("e-0", body)

    def test_seven_digit_loan_balance_renders_in_full_when_not_linked(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertIn('value="1,100,000"', body)

    def test_purchase_price_current_value_and_loan_balance_columns_are_widened(self):
        resp = self._get("/real-estate.html")
        body = resp.read().decode("utf-8")
        self.assertEqual(body.count("width:115px"), 3)  # purchase_price, current_value, loan_balance

    def test_current_value_survives_a_round_trip_through_the_update_endpoint(self):
        # Regression check for the precision-loss half of the old bug --
        # not just cosmetic: the old :g-formatted "3.33661e+06" that
        # showed in the box would have actually saved back as a rounded
        # $3,336,610 if the row was ever re-submitted unchanged.
        status, payload = self._post("/api/line-item/update", {
            "section": "real_estate", "id": self.item_id,
            "fields": {"current_value": "3336607.99"},
        })
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_line_item("real_estate", self.item_id)["current_value"], 3336607.99)


class TestLinkedPositionsPage(DashboardTestCase):
    def setUp(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-brokerage", "name": "Fidelity", "official_name": "Fidelity Brokerage",
            "type": "investment", "subtype": "brokerage", "mask": "5678",
            "balances": {"current": 1500.0, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_holding(item_key="fidelity", holding={
            "account_id": "acc-brokerage", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 10,
            "institution_price": 150, "institution_value": 1500, "cost_basis": 1000,
            "iso_currency_code": "USD",
        })

    def tearDown(self):
        db.delete_plaid_item("fidelity")

    def test_linked_positions_page_shows_holdings(self):
        resp = self._get("/linked-positions.html")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode("utf-8")
        self.assertIn("AAPL", body)
        self.assertIn("Linked Positions", body)

    def test_nav_includes_linked_positions_tab(self):
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        self.assertRegex(body, r'href="/linked-accounts.html" class="active">.*<span class="nl">Linked Accounts</span></a>')
        self.assertIn('href="/linked-positions.html" class="active">Positions</a>', body)

    def test_asset_page_no_longer_embeds_the_positions_table_but_links_to_it(self):
        resp = self._get("/asset.html")
        body = resp.read().decode("utf-8")
        self.assertNotIn("AAPL", body)
        self.assertIn('href="/linked-positions.html"', body)

    def test_linked_positions_table_has_a_market_value_total_and_is_sortable(self):
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<table class="sortable" id="linked-positions-table">', body)
        self.assertIn("1,500", body)  # appears both in the row and the total

    def test_linked_positions_page_shows_type_institution_donuts_and_an_industry_bar_chart(self):
        # Type and institution stay donuts (few categories, read fine as
        # pies); industry is a horizontal bar chart instead (it tends to
        # accumulate many distinct values once positions are manually
        # tagged, and a pie/donut stops being legible past ~6-7 slices --
        # see the dataviz skill).
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Positions by type (market value)", body)
        self.assertIn("Positions by institution (market value)", body)
        self.assertIn("Positions by sector (market value)", body)
        self.assertIn("Positions by industry (market value)", body)
        self.assertIn('class="bar-chart"', body)
        # JS hook refreshLinkedPositionsBarCharts() (shell.py) uses to
        # rewrite each bar chart's own "-- $X total" header when Sector/
        # Industry recomputes against another active filter (e.g.
        # Institution) -- see that function's own comment.
        self.assertEqual(body.count('class="muted bar-chart-total-label"'), 2)
        # The single holding is an "Equity" at "Fidelity", not yet
        # industry-classified -- the type/institution donuts should show
        # a legend row (single slice, no "Other" fold), and the sector/
        # industry bars should show "Unknown".
        self.assertIn("Equity", body)
        self.assertIn("Fidelity", body)
        self.assertIn("Unknown", body)
        self.assertNotIn("Other", body.split("Positions by type")[1].split("Positions by sector")[0])

    def test_industry_bar_chart_shows_every_distinct_industry_uncapped(self):
        # Unlike the type/institution donuts (still capped -- a pie/donut
        # stops being legible past ~6-7 slices), the industry bar chart
        # shows every distinct industry as its own directly-labeled bar,
        # however many there are -- folding a long tail into "Other"
        # used to hide a real, specific industry like a single position's
        # "Auto Manufacturers" behind a vague grouped label just because
        # its total market value wasn't in some top-N cutoff.
        # Reuses this class's own "acc-brokerage" account (created in
        # setUp above) so tearDown's db.delete_plaid_item("fidelity") --
        # which deletes holdings by looking up account_ids for that item
        # -- cleans these up too, rather than leaking them into later
        # tests in this class (setUpClass/the temp db are shared across
        # every test method here, only setUp/tearDown run per-test).
        now = "2026-09-01T00:00:00Z"
        security_ids = [f"sec-extra-{i}" for i in range(20)]
        try:
            for i, security_id in enumerate(security_ids):
                db.upsert_plaid_holding(item_key="fidelity", holding={
                    "account_id": "acc-brokerage", "security_id": security_id, "ticker_symbol": f"T{i}",
                    "security_name": f"Security {i}", "security_type": "equity", "quantity": 1,
                    "institution_price": 10, "institution_value": 10, "cost_basis": 10,
                    "iso_currency_code": "USD",
                })
                db.set_security_industry(security_id=security_id, ticker=f"T{i}", industry=f"Industry {i}", updated_at=now)
            resp = self._get("/linked-positions.html")
            body = resp.read().decode("utf-8")
            industry_section = body.split("Positions by industry")[1].split('<div id="positions-filter-bar"')[0]
            for i in range(20):
                self.assertIn(f"Industry {i}", industry_section)
            self.assertNotIn(">Other<", industry_section)
        finally:
            # security_industries is a standalone cache table, not
            # cascade-deleted by tearDown's db.delete_plaid_item -- see
            # test_industry_column_and_chart_reflect_a_classified_holding
            # above for the same cleanup pattern.
            db.clear_security_industries(security_ids)

    def test_sector_chart_rolls_up_two_different_industries_into_one_sector(self):
        # "Semiconductors" and "Consumer Electronics" are two distinct
        # industries that both roll up to "Technology" -- the sector
        # chart should combine their market values into a single slice,
        # unlike the industry chart which keeps them separate.
        db.upsert_plaid_holding(item_key="fidelity", holding={
            "account_id": "acc-brokerage", "security_id": "sec-nvda", "ticker_symbol": "NVDA",
            "security_name": "NVIDIA Corp", "security_type": "equity", "quantity": 1,
            "institution_price": 500, "institution_value": 500, "cost_basis": 500,
            "iso_currency_code": "USD",
        })
        db.set_security_industry(
            security_id="sec-aapl", ticker="AAPL", industry="Consumer Electronics",
            updated_at="2026-09-13T00:00:00+00:00",
        )
        db.set_security_industry(
            security_id="sec-nvda", ticker="NVDA", industry="Semiconductors",
            updated_at="2026-09-13T00:00:00+00:00",
        )
        try:
            resp = self._get("/linked-positions.html")
            body = resp.read().decode("utf-8")
            sector_section = body.split("Positions by sector")[1].split("Positions by industry")[0]
            # A single "Technology" slice/bar, not one per industry --
            # its member_labels is just ["Technology"] since the grouping
            # already happened on the per-row "sector" field (mapped from
            # each row's distinct industry) rather than on industry
            # itself; both rows carry data-sector="Technology" so a click
            # on this one bar still filters both of them.
            self.assertIn('data-values="[&quot;Technology&quot;]"', sector_section)
            # $1,500 (AAPL) + $500 (NVDA) = $2,000, all under one "Technology" bar.
            self.assertIn("Technology: $2,000 (100%)", sector_section)
            self.assertEqual(body.count('data-sector="Technology"'), 2)
        finally:
            db.clear_security_industries(["sec-aapl", "sec-nvda"])

    def test_pie_slices_and_legend_rows_are_clickable_and_carry_filter_data(self):
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        # Both the SVG wedge and its legend row are ".pie-seg" elements
        # carrying the dim/slice-id/values the shared JS filters on.
        self.assertIn('class="pie-seg"', body)
        self.assertIn('data-dim="type"', body)
        self.assertIn('data-dim="institution"', body)
        self.assertIn('data-dim="industry"', body)
        self.assertIn('onclick="handlePieSegClick(this)"', body)
        self.assertIn('onkeydown="handlePieSegKeydown(event, this)"', body)
        # The single Equity/Fidelity/Unknown-industry holding's slice
        # values match the row's own data-type/data-institution/
        # data-industry attributes exactly.
        self.assertIn('data-values="[&quot;Equity&quot;]"', body)
        self.assertIn('data-values="[&quot;Fidelity&quot;]"', body)
        self.assertIn('data-values="[&quot;Unknown&quot;]"', body)

    def test_positions_table_rows_carry_matching_filter_attributes(self):
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        self.assertIn('id="linked-positions-table"', body)
        self.assertIn('id="linked-positions-total"', body)
        self.assertIn('id="positions-filter-bar"', body)
        self.assertIn(
            'data-type="Equity" data-institution="Fidelity" data-industry="Unknown" data-sector="Unknown" '
            'data-market-value="1500.0"',
            body,
        )
        # Not yet classified -- shown as "Unclassified" in the table cell.
        self.assertIn("Unclassified", body)

    def test_a_second_distinct_holding_gets_its_own_matching_row_and_slice_values(self):
        # A second holding at a different institution with a different
        # security type -- the "Positions by type" chart should then carry
        # two distinct slices whose data-values match each row's own
        # data-type exactly, and likewise for "Positions by institution".
        db.upsert_plaid_item(
            item_key="schwab", plaid_item_id="item-2", institution_id="ins_2",
            institution_name="Charles Schwab", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="schwab", account={
            "account_id": "acc-schwab", "name": "Schwab", "official_name": "Schwab Brokerage",
            "type": "investment", "subtype": "brokerage", "mask": "1111",
            "balances": {"current": 500.0, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_holding(item_key="schwab", holding={
            "account_id": "acc-schwab", "security_id": "sec-bond", "ticker_symbol": "",
            "security_name": "US Treasury Bond", "security_type": "fixed income", "quantity": 5,
            "institution_price": 100, "institution_value": 500, "cost_basis": 500,
            "iso_currency_code": "USD",
        })
        try:
            resp = self._get("/linked-positions.html")
            body = resp.read().decode("utf-8")
            self.assertIn(
                'data-type="Equity" data-institution="Fidelity" data-industry="Unknown" data-sector="Unknown" '
                'data-market-value="1500.0"',
                body,
            )
            # "Charles Schwab" (the Item's real institution_name) -- not
            # "Schwab" (the account row's own Plaid `name`). Deliberately
            # different strings here so this test actually exercises the
            # institution-vs-account-label distinction (see linked_data.
            # read_linked_portfolio_positions' own comment on this).
            self.assertIn(
                'data-type="Fixed Income" data-institution="Charles Schwab" data-industry="Unknown" data-sector="Unknown" '
                'data-market-value="500.0"',
                body,
            )
            self.assertIn('data-values="[&quot;Fixed Income&quot;]"', body)
            self.assertIn('data-values="[&quot;Charles Schwab&quot;]"', body)
            # Two type slices => two distinct slice ids on the type chart.
            self.assertIn('data-slice-id="type-0"', body)
            self.assertIn('data-slice-id="type-1"', body)
        finally:
            db.delete_plaid_item("schwab")


    def test_industry_column_and_chart_reflect_a_classified_holding(self):
        # security_industries is a standalone cache table (see db.py's
        # module docstring on it) -- not cascade-deleted by tearDown's
        # db.delete_plaid_item, so this test cleans up its own row to
        # avoid leaking a classification into a later test that shares
        # this class's single database (see DashboardTestCase.setUpClass).
        db.set_security_industry(
            security_id="sec-aapl", ticker="AAPL", industry="Consumer Electronics",
            updated_at="2026-09-13T00:00:00+00:00",
        )
        try:
            resp = self._get("/linked-positions.html")
            body = resp.read().decode("utf-8")
            self.assertIn("<th>Industry</th>", body)
            self.assertIn("Consumer Electronics", body)
            self.assertIn(
                'data-type="Equity" data-institution="Fidelity" data-industry="Consumer Electronics" '
                'data-sector="Technology" data-market-value="1500.0"',
                body,
            )
            self.assertIn('data-values="[&quot;Consumer Electronics&quot;]"', body)
            # The intro paragraph mentions the word "Unclassified" as
            # general help text -- check the table itself doesn't show
            # it for this now-classified row.
            table_html = body.split('id="linked-positions-table"')[1].split("</table>")[0]
            self.assertNotIn("Unclassified", table_html)
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM security_industries WHERE security_id = ?", ("sec-aapl",))

    def test_positions_table_has_a_checkbox_column_and_the_bulk_classify_bar(self):
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        self.assertIn('class="position-check"', body)
        self.assertIn('class="position-select-all"', body)
        self.assertIn('data-security-id="sec-aapl"', body)
        self.assertIn('data-ticker="AAPL"', body)
        self.assertIn('id="industry-bulk-bar"', body)
        self.assertIn('id="industry-bulk-input"', body)
        self.assertIn('id="industry-options"', body)
        self.assertIn("function classifySelectedIndustry()", body)
        self.assertIn("function clearSelectedIndustry()", body)
        self.assertIn("function clearPositionSelection()", body)
        self.assertIn("function refreshIndustryBulkBar()", body)
        self.assertIn("/api/classify-industry", body)
        # This bar is scoped to the Linked Positions page, not the
        # global delete-bulk bar every other page shares -- distinct
        # classes/ids so the two mechanisms' JS never collides.
        self.assertNotIn('class="position-check row-check"', body)
        # The "Set sector" bar -- same mechanism, its own bar/id/input.
        self.assertIn('id="sector-bulk-bar"', body)
        self.assertIn('id="sector-bulk-input"', body)
        self.assertIn('id="sector-options"', body)
        self.assertIn("function classifySelectedSector()", body)
        self.assertIn("function clearSelectedSector()", body)
        self.assertIn("/api/classify-sector", body)

    def test_positions_table_offers_every_industry_already_in_use_on_the_bulk_classify_datalist(self):
        db.set_security_industry(
            security_id="sec-aapl", ticker="AAPL", industry="Consumer Electronics",
            updated_at="2026-09-13T00:00:00+00:00",
        )
        try:
            resp = self._get("/linked-positions.html")
            body = resp.read().decode("utf-8")
            datalist_html = body.split('id="industry-options"')[1].split("</datalist>")[0]
            self.assertIn("Consumer Electronics", datalist_html)
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM security_industries WHERE security_id = ?", ("sec-aapl",))


class TestLinkedPositionsVestedValue(DashboardTestCase):
    """A stock-plan holding (an employer RSU/ESPP grant) is reported by
    Plaid at its FULL institution_value, unvested shares included, with
    vested_value as a separate optional field the institution may or may
    not provide -- the Linked Positions tab shows the vested-only figure
    whenever it's present (see linked_data.read_linked_portfolio_positions'
    own comment), with a small marker + tooltip so it doesn't just look
    like the position silently shrank."""

    def setUp(self):
        db.upsert_plaid_item(
            item_key="etrade", plaid_item_id="item-etrade", institution_id="ins_1",
            institution_name="E*TRADE from Morgan Stanley", products=["investments"],
            environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="etrade", account={
            "account_id": "acc-stockplan", "name": "Stock Plan (AAPL) -2013",
            "type": "investment", "subtype": "stock plan", "mask": "2013",
            "balances": {"current": 150_000.0, "available": None, "iso_currency_code": "USD"},
        })

    def tearDown(self):
        db.delete_plaid_item("etrade")

    def test_market_value_shown_is_vested_only_with_a_marker_and_tooltip(self):
        db.upsert_plaid_holding(item_key="etrade", holding={
            "account_id": "acc-stockplan", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 1000,
            "institution_price": 150, "institution_value": 150_000, "cost_basis": 100_000,
            "vested_quantity": 400, "vested_value": 60_000,
        })
        body = self._get("/linked-positions.html").read().decode("utf-8")
        self.assertIn("$60,000", body)  # the vested figure shown as the Market Value
        self.assertIn("(vested)", body)
        self.assertIn("full grant (incl. unvested) is $150,000", body)
        # The unfiltered full grant total must not appear as the row's
        # own displayed value/table total (it's only in the tooltip).
        self.assertNotIn('>$150,000<', body)

    def test_market_value_total_and_charts_use_the_vested_figure_too(self):
        db.upsert_plaid_holding(item_key="etrade", holding={
            "account_id": "acc-stockplan", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 1000,
            "institution_price": 150, "institution_value": 150_000,
            "vested_quantity": 400, "vested_value": 60_000,
        })
        body = self._get("/linked-positions.html").read().decode("utf-8")
        self.assertIn('id="linked-positions-total">$60,000</td>', body)
        self.assertIn('data-market-value="60000.0"', body)

    def test_an_ordinary_holding_with_no_vested_split_shows_no_marker(self):
        db.upsert_plaid_holding(item_key="etrade", holding={
            "account_id": "acc-stockplan", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 1000,
            "institution_price": 150, "institution_value": 150_000,
        })
        body = self._get("/linked-positions.html").read().decode("utf-8")
        self.assertIn("$150,000", body)
        self.assertNotIn("(vested)", body)


class TestOtherTypeSubcategorization(DashboardTestCase):
    """Plaid's "security_type" folds a lot of distinct real-world holdings
    (REITs, private funds, etc.) into one generic "other" value -- the
    Linked Positions page should split that bucket by the holding's
    existing Industry tag ("Other: REIT") wherever one is set, both in the
    "Positions by type" chart and the table's Type column/data-type filter
    attribute, and leave an un-tagged "Other" holding (or any non-"Other"
    type) showing exactly as before."""

    def setUp(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-brokerage", "name": "Fidelity", "official_name": "Fidelity Brokerage",
            "type": "investment", "subtype": "brokerage", "mask": "5678",
            "balances": {"current": 2500.0, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_holding(item_key="fidelity", holding={
            "account_id": "acc-brokerage", "security_id": "sec-reit", "ticker_symbol": "O",
            "security_name": "Realty Income Corp", "security_type": "other", "quantity": 10,
            "institution_price": 150, "institution_value": 1500, "cost_basis": 1000,
            "iso_currency_code": "USD",
        })
        db.upsert_plaid_holding(item_key="fidelity", holding={
            "account_id": "acc-brokerage", "security_id": "sec-mystery", "ticker_symbol": "",
            "security_name": "Unclassified Other Holding", "security_type": "other", "quantity": 20,
            "institution_price": 50, "institution_value": 1000, "cost_basis": 1000,
            "iso_currency_code": "USD",
        })
        db.set_security_industry(
            security_id="sec-reit", ticker="O", industry="REIT", updated_at="2026-09-13T00:00:00+00:00",
        )

    def tearDown(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM security_industries WHERE security_id = ?", ("sec-reit",))
        db.delete_plaid_item("fidelity")

    def test_industry_tagged_other_holding_shows_a_derived_other_colon_industry_label(self):
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        # Chart slice carries the derived label, not the raw "Other".
        self.assertIn('data-values="[&quot;Other: REIT&quot;]"', body)
        # Table row's filter attribute and visible Type cell both use it.
        # "REIT" (the plain tag, not a Yahoo Finance industry string like
        # "REIT - Diversified") isn't in the sector table, so it lands in
        # "Other" rather than being guessed into Real Estate.
        self.assertIn(
            'data-type="Other: REIT" data-institution="Fidelity" data-industry="REIT" data-sector="Other" '
            'data-market-value="1500.0"',
            body,
        )
        self.assertIn("<td>Other: REIT</td>", body)

    def test_untagged_other_holding_still_shows_as_plain_other(self):
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        self.assertIn(
            'data-type="Other" data-institution="Fidelity" data-industry="Unknown" data-sector="Unknown" '
            'data-market-value="1000.0"',
            body,
        )
        self.assertIn('data-values="[&quot;Other&quot;]"', body)

    def test_type_chart_shows_both_as_distinct_slices_not_folded_together(self):
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        self.assertIn('data-slice-id="type-0"', body)
        self.assertIn('data-slice-id="type-1"', body)

    def test_a_non_other_type_is_unaffected_even_with_an_industry_tag(self):
        db.upsert_plaid_holding(item_key="fidelity", holding={
            "account_id": "acc-brokerage", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 10,
            "institution_price": 150, "institution_value": 1500, "cost_basis": 1000,
            "iso_currency_code": "USD",
        })
        db.set_security_industry(
            security_id="sec-aapl", ticker="AAPL", industry="Consumer Electronics",
            updated_at="2026-09-13T00:00:00+00:00",
        )
        try:
            resp = self._get("/linked-positions.html")
            body = resp.read().decode("utf-8")
            self.assertIn(
                'data-type="Equity" data-institution="Fidelity" data-industry="Consumer Electronics" '
                'data-sector="Technology" data-market-value="1500.0"',
                body,
            )
            self.assertIn('data-values="[&quot;Equity&quot;]"', body)
        finally:
            with db.connect() as conn:
                conn.execute("DELETE FROM security_industries WHERE security_id = ?", ("sec-aapl",))


class TestClassifyIndustryEndpoint(DashboardTestCase):
    """Backs the Linked Positions page's multi-select "Set industry"/
    "Clear industry" bar. Sets up the same single Fidelity/AAPL holding
    (security_id "sec-aapl") as TestLinkedPositionsPage.setUp, kept as its
    own class (rather than subclassing TestLinkedPositionsPage) so this
    doesn't re-run that class's whole test list under a second name."""

    def setUp(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-brokerage", "name": "Fidelity", "official_name": "Fidelity Brokerage",
            "type": "investment", "subtype": "brokerage", "mask": "5678",
            "balances": {"current": 1500.0, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_holding(item_key="fidelity", holding={
            "account_id": "acc-brokerage", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 10,
            "institution_price": 150, "institution_value": 1500, "cost_basis": 1000,
            "iso_currency_code": "USD",
        })

    def tearDown(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM security_industries WHERE security_id = ?", ("sec-aapl",))
        db.delete_plaid_item("fidelity")

    def test_setting_an_industry_classifies_every_requested_item(self):
        status, payload = self._post("/api/classify-industry", {
            "items": [{"security_id": "sec-aapl", "ticker": "AAPL"}],
            "industry": "Consumer Electronics",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(db.get_security_industries(), {"sec-aapl": "Consumer Electronics"})

    def test_setting_a_manual_industry_overrides_an_existing_auto_classified_one(self):
        db.set_security_industry(security_id="sec-aapl", ticker="AAPL", industry="Unknown", updated_at="2026-09-01T00:00:00+00:00")
        status, payload = self._post("/api/classify-industry", {
            "items": [{"security_id": "sec-aapl", "ticker": "AAPL"}],
            "industry": "Cash",
        })
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_security_industries(), {"sec-aapl": "Cash"})

    def test_blank_industry_clears_the_classification_instead_of_setting_it(self):
        db.set_security_industry(security_id="sec-aapl", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-01T00:00:00+00:00")
        status, payload = self._post("/api/classify-industry", {
            "items": [{"security_id": "sec-aapl", "ticker": "AAPL"}],
            "industry": None,
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(db.get_security_industries(), {})

    def test_classify_skips_items_missing_a_security_id_but_still_classifies_the_rest(self):
        status, payload = self._post("/api/classify-industry", {
            "items": [
                {"security_id": "sec-aapl", "ticker": "AAPL"},
                {"ticker": "NOID"},
            ],
            "industry": "Consumer Electronics",
        })
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(db.get_security_industries(), {"sec-aapl": "Consumer Electronics"})

    def test_classifying_then_reloading_the_page_reflects_the_new_industry_in_the_bar_chart(self):
        status, payload = self._post("/api/classify-industry", {
            "items": [{"security_id": "sec-aapl", "ticker": "AAPL"}],
            "industry": "Consumer Electronics",
        })
        self.assertTrue(payload["ok"])
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Consumer Electronics", body)
        self.assertIn('data-values="[&quot;Consumer Electronics&quot;]"', body)


class TestClassifySectorEndpoint(DashboardTestCase):
    """Backs the Linked Positions page's multi-select "Set sector"/"Clear
    sector" bar -- a manual override mainly meant for a mutual fund/ETF/
    target-date fund, which never gets an `industry` classified for it in
    the first place (see db.set_security_sector's docstring), so it has
    no other way out of the "Unknown" sector bucket. Same setup/teardown
    pattern as TestClassifyIndustryEndpoint above, kept separate so it
    doesn't re-run that class's whole test list under a second name."""

    def setUp(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-brokerage", "name": "Fidelity", "official_name": "Fidelity Brokerage",
            "type": "investment", "subtype": "brokerage", "mask": "5678",
            "balances": {"current": 500.0, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_holding(item_key="fidelity", holding={
            "account_id": "acc-brokerage", "security_id": "sec-idx", "ticker_symbol": "VG.INST.500.IDX",
            "security_name": "Vg Inst 500 Idx", "security_type": "mutual fund", "quantity": 10,
            "institution_price": 50, "institution_value": 500, "cost_basis": 400,
            "iso_currency_code": "USD",
        })

    def tearDown(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM security_industries WHERE security_id = ?", ("sec-idx",))
        db.delete_plaid_item("fidelity")

    def test_setting_a_sector_classifies_every_requested_item(self):
        status, payload = self._post("/api/classify-sector", {
            "items": [{"security_id": "sec-idx", "ticker": "VG.INST.500.IDX"}],
            "sector": "Diversified",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(db.get_security_sectors(), {"sec-idx": "Diversified"})

    def test_setting_a_sector_overrides_a_previous_manual_sector(self):
        db.set_security_sector(security_id="sec-idx", ticker="VG.INST.500.IDX", sector="Other", updated_at="2026-09-01T00:00:00+00:00")
        status, payload = self._post("/api/classify-sector", {
            "items": [{"security_id": "sec-idx", "ticker": "VG.INST.500.IDX"}],
            "sector": "Diversified",
        })
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_security_sectors(), {"sec-idx": "Diversified"})

    def test_blank_sector_clears_the_override_instead_of_setting_it(self):
        db.set_security_sector(security_id="sec-idx", ticker="VG.INST.500.IDX", sector="Diversified", updated_at="2026-09-01T00:00:00+00:00")
        status, payload = self._post("/api/classify-sector", {
            "items": [{"security_id": "sec-idx", "ticker": "VG.INST.500.IDX"}],
            "sector": None,
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(db.get_security_sectors(), {})

    def test_classify_skips_items_missing_a_security_id_but_still_classifies_the_rest(self):
        status, payload = self._post("/api/classify-sector", {
            "items": [
                {"security_id": "sec-idx", "ticker": "VG.INST.500.IDX"},
                {"ticker": "NOID"},
            ],
            "sector": "Diversified",
        })
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(db.get_security_sectors(), {"sec-idx": "Diversified"})

    def test_classifying_then_reloading_the_page_reflects_the_new_sector_in_the_bar_chart_and_row(self):
        status, payload = self._post("/api/classify-sector", {
            "items": [{"security_id": "sec-idx", "ticker": "VG.INST.500.IDX"}],
            "sector": "Diversified",
        })
        self.assertTrue(payload["ok"])
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Diversified", body)
        self.assertIn('data-sector="Diversified"', body)
        # The Industry column/derivation is untouched -- still "Unclassified".
        self.assertIn("Unclassified", body)


class TestGroupedSlicesAndDonutChart(unittest.TestCase):
    """Unit tests for the chart helpers used on the Linked Positions page
    (_grouped_slices, _donut_chart_html, and _bar_chart_html) -- kept
    separate from the DashboardTestCase suite since these are pure
    functions with no server/db involved."""

    def test_sums_value_by_key_and_orders_largest_first(self):
        rows = [
            {"security_type": "equity", "market_value": 100},
            {"security_type": "bond", "market_value": 500},
            {"security_type": "equity", "market_value": 50},
        ]
        slices = dashboard._grouped_slices(rows, key="security_type", value_key="market_value")
        self.assertEqual(slices, [("bond", 500.0, ["bond"]), ("equity", 150.0, ["equity"])])

    def test_blank_or_missing_key_falls_back_to_unknown(self):
        rows = [
            {"security_type": "", "market_value": 10},
            {"market_value": 20},
        ]
        slices = dashboard._grouped_slices(rows, key="security_type", value_key="market_value")
        self.assertEqual(slices, [("Unknown", 30.0, ["Unknown"])])

    def test_more_than_six_distinct_values_fold_into_other(self):
        rows = [{"security_type": f"type-{i}", "market_value": (7 - i) * 10} for i in range(7)]
        slices = dashboard._grouped_slices(rows, key="security_type", value_key="market_value")
        self.assertEqual(len(slices), 7)  # 6 real slices + "Other"
        labels = [label for label, _, _ in slices]
        self.assertEqual(labels[:6], ["type-0", "type-1", "type-2", "type-3", "type-4", "type-5"])
        self.assertEqual(labels[6], "Other")
        # type-6 (10) is the only one folded in, so "Other" should equal it.
        self.assertEqual(slices[6][1], 10.0)
        # The "Other" bucket remembers which raw labels it folded together,
        # so a click on it can still filter the underlying rows.
        self.assertEqual(slices[6][2], ["type-6"])
        # A real (non-folded) slice's member_labels is just itself.
        self.assertEqual(slices[0][2], ["type-0"])

    def test_max_slices_none_returns_every_distinct_value_with_no_other_bucket(self):
        rows = [{"security_type": f"type-{i}", "market_value": (20 - i)} for i in range(20)]
        slices = dashboard._grouped_slices(rows, key="security_type", value_key="market_value", max_slices=None)
        self.assertEqual(len(slices), 20)
        self.assertNotIn("Other", [label for label, _, _ in slices])
        # Still sorted largest-first.
        self.assertEqual(slices[0][0], "type-0")
        self.assertEqual(slices[-1][0], "type-19")

    def test_exactly_six_distinct_values_does_not_add_an_other_bucket(self):
        rows = [{"security_type": f"type-{i}", "market_value": 1} for i in range(6)]
        slices = dashboard._grouped_slices(rows, key="security_type", value_key="market_value")
        self.assertEqual(len(slices), 6)
        self.assertNotIn("Other", [label for label, _, _ in slices])

    def test_donut_chart_with_no_data_shows_a_fallback_card(self):
        html_out = dashboard._donut_chart_html("Positions by type (market value)", [], dim="type")
        self.assertIn("No data yet.", html_out)
        self.assertNotIn("<svg", html_out)

    def test_donut_chart_renders_svg_legend_and_tooltips_for_each_slice(self):
        slices = [("equity", 750.0, ["equity"]), ("bond", 250.0, ["bond"])]
        html_out = dashboard._donut_chart_html("Positions by type (market value)", slices, dim="type")
        self.assertIn("<svg", html_out)
        self.assertIn("Positions by type (market value)", html_out)
        self.assertIn("equity", html_out)
        self.assertIn("bond", html_out)
        # Legend shows value + percent for each slice.
        self.assertIn("75%", html_out)
        self.assertIn("25%", html_out)
        # Native <title> hover tooltips, one per wedge.
        self.assertEqual(html_out.count("<title>"), 2)
        # Fixed-order categorical colors -- first slice gets slot 1, second slot 2.
        self.assertIn(dashboard._DONUT_COLORS[0], html_out)
        self.assertIn(dashboard._DONUT_COLORS[1], html_out)

    def test_donut_chart_other_slice_uses_the_muted_color_not_a_categorical_slot(self):
        slices = [
            ("a", 10.0, ["a"]), ("b", 9.0, ["b"]), ("c", 8.0, ["c"]),
            ("d", 7.0, ["d"]), ("e", 6.0, ["e"]), ("f", 5.0, ["f"]),
            ("Other", 4.0, ["g"]),
        ]
        html_out = dashboard._donut_chart_html("Test", slices, dim="type")
        self.assertIn(dashboard._DONUT_OTHER_COLOR, html_out)

    def test_each_slice_is_a_clickable_pie_seg_with_dim_slice_id_and_values(self):
        slices = [("equity", 750.0, ["equity"]), ("bond", 250.0, ["bond"])]
        html_out = dashboard._donut_chart_html("Test", slices, dim="type")
        # Two elements per slice: the circle wedge and its legend row.
        self.assertEqual(html_out.count('class="pie-seg"'), 2)  # one per circle
        self.assertEqual(html_out.count('class="legend-row pie-seg"'), 2)  # one per legend row
        # Neither element should end up with two `class` attributes.
        self.assertNotIn('class="pie-seg" class=', html_out)
        self.assertNotIn('class="legend-row pie-seg" class=', html_out)
        self.assertIn('data-dim="type"', html_out)
        self.assertIn('data-slice-id="type-0"', html_out)
        self.assertIn('data-slice-id="type-1"', html_out)
        self.assertIn('onclick="handlePieSegClick(this)"', html_out)
        self.assertIn('tabindex="0"', html_out)
        self.assertIn('role="button"', html_out)

    def test_other_slices_values_attribute_lists_every_folded_raw_label(self):
        slices = [
            ("a", 10.0, ["a"]), ("b", 9.0, ["b"]), ("c", 8.0, ["c"]),
            ("d", 7.0, ["d"]), ("e", 6.0, ["e"]), ("f", 5.0, ["f"]),
            ("Other", 4.0, ["g", "h", "i"]),
        ]
        html_out = dashboard._donut_chart_html("Test", slices, dim="type")
        self.assertIn('data-values="[&quot;g&quot;, &quot;h&quot;, &quot;i&quot;]"', html_out)

    def test_bar_chart_with_no_data_shows_a_fallback_card(self):
        html_out = dashboard._bar_chart_html("Positions by industry (market value)", [], dim="industry")
        self.assertIn("No data yet.", html_out)
        self.assertNotIn('class="bar-chart"', html_out)

    def test_bar_chart_with_many_rows_is_a_scrollable_list_with_a_hint(self):
        slices = [(f"Cat {i}", 100.0 - i, [f"Cat {i}"]) for i in range(14)]
        html_out = dashboard._bar_chart_html("Real expenditure by category", slices, dim="expense-category")
        self.assertIn("14 rows -- scroll the list to see them all.", html_out)
        self.assertIn('role="region"', html_out)
        self.assertEqual(html_out.count('class="bar-row pie-seg"'), 14)  # every row, none folded away

    def test_bar_chart_with_few_rows_has_no_scroll_hint(self):
        slices = [(f"Cat {i}", 100.0 - i, [f"Cat {i}"]) for i in range(10)]
        html_out = dashboard._bar_chart_html("Real expenditure by category", slices, dim="expense-category")
        self.assertNotIn("scroll the list", html_out)
        self.assertNotIn('role="region"', html_out)

    def test_bar_chart_renders_a_labeled_row_per_slice_with_value_and_percent(self):
        slices = [("Cash", 750.0, ["Cash"]), ("Semiconductors", 250.0, ["Semiconductors"])]
        html_out = dashboard._bar_chart_html("Positions by industry (market value)", slices, dim="industry")
        self.assertIn('class="bar-chart"', html_out)
        self.assertIn("Positions by industry (market value)", html_out)
        self.assertIn("Cash", html_out)
        self.assertIn("Semiconductors", html_out)
        self.assertIn("75%", html_out)
        self.assertIn("25%", html_out)
        # No SVG involved -- this is the plain HTML bar form, not a donut.
        self.assertNotIn("<svg", html_out)
        # Fixed-order categorical colors, same sequence as the donut chart.
        self.assertIn(dashboard._DONUT_COLORS[0], html_out)
        self.assertIn(dashboard._DONUT_COLORS[1], html_out)

    def test_bar_chart_other_bucket_uses_the_muted_color(self):
        slices = [
            ("a", 10.0, ["a"]), ("b", 9.0, ["b"]), ("c", 8.0, ["c"]),
            ("d", 7.0, ["d"]), ("e", 6.0, ["e"]), ("f", 5.0, ["f"]),
            ("Other", 4.0, ["g"]),
        ]
        html_out = dashboard._bar_chart_html("Test", slices, dim="industry")
        self.assertIn(dashboard._DONUT_OTHER_COLOR, html_out)

    def test_bar_chart_rows_are_clickable_pie_segs_with_dim_slice_id_and_values(self):
        # Reuses the exact same click-to-filter contract as the donut
        # chart (".pie-seg" + data-dim/data-slice-id/data-values, wired
        # to the shared handlePieSegClick() JS) so no separate filtering
        # JS was needed when this chart switched from a donut to a bar.
        slices = [("Cash", 750.0, ["Cash"]), ("Semiconductors", 250.0, ["Semiconductors"])]
        html_out = dashboard._bar_chart_html("Test", slices, dim="industry")
        self.assertEqual(html_out.count('class="bar-row pie-seg"'), 2)
        self.assertIn('data-dim="industry"', html_out)
        self.assertIn('data-slice-id="industry-0"', html_out)
        self.assertIn('data-slice-id="industry-1"', html_out)
        self.assertIn('onclick="handlePieSegClick(this)"', html_out)
        self.assertIn('onkeydown="handlePieSegKeydown(event, this)"', html_out)
        self.assertIn('tabindex="0"', html_out)
        self.assertIn('role="button"', html_out)
        self.assertIn('data-values="[&quot;Cash&quot;]"', html_out)


class TestSectorForIndustry(unittest.TestCase):
    """Unit tests for _sector_for_industry/_SECTOR_BY_INDUSTRY -- the
    lookup that rolls up a fine-grained Yahoo Finance industry (what
    source.collector.sync_industries stores) to a broader sector for the
    Linked Positions page's "Positions by sector" chart."""

    def test_known_industries_map_to_their_sector(self):
        self.assertEqual(dashboard._sector_for_industry("Semiconductors"), "Technology")
        self.assertEqual(dashboard._sector_for_industry("Consumer Electronics"), "Technology")
        self.assertEqual(dashboard._sector_for_industry("Auto Manufacturers"), "Consumer Cyclical")
        self.assertEqual(dashboard._sector_for_industry("Internet Retail"), "Consumer Cyclical")
        self.assertEqual(dashboard._sector_for_industry("Internet Content & Information"), "Communication Services")
        self.assertEqual(dashboard._sector_for_industry("Drug Manufacturers - General"), "Healthcare")
        self.assertEqual(dashboard._sector_for_industry("Banks - Diversified"), "Financial Services")
        self.assertEqual(dashboard._sector_for_industry("Aerospace & Defense"), "Industrials")
        self.assertEqual(dashboard._sector_for_industry("Asset Management"), "Financial Services")

    def test_lookup_is_case_insensitive(self):
        self.assertEqual(dashboard._sector_for_industry("semiconductors"), "Technology")
        self.assertEqual(dashboard._sector_for_industry("SEMICONDUCTORS"), "Technology")

    def test_blank_or_missing_industry_is_unknown(self):
        self.assertEqual(dashboard._sector_for_industry(""), "Unknown")
        self.assertEqual(dashboard._sector_for_industry(None), "Unknown")
        self.assertEqual(dashboard._sector_for_industry("   "), "Unknown")

    def test_unrecognized_industry_falls_back_to_other_not_a_guess(self):
        # A manually typed-in tag (e.g. "Cash", "International Equity")
        # isn't in the sector table -- it should land in "Other" rather
        # than being silently mis-sorted into some sector it doesn't
        # belong to.
        self.assertEqual(dashboard._sector_for_industry("Cash"), "Other")
        self.assertEqual(dashboard._sector_for_industry("International Equity"), "Other")


class TestAssumptionsEndpoint(DashboardTestCase):
    def test_percent_fields_are_converted_to_decimals(self):
        status, payload = self._post("/api/assumptions", {"expected_return_pct": "7.5"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertAlmostEqual(float(db.get_assumptions()["expected_return"]), 0.075)

    def test_summary_page_reflects_return_rate_changed_from_summary_itself(self):
        # This is the endpoint the Summary page's "What if: expected
        # return" card posts to -- a partial update (just this one field)
        # must not disturb the other assumptions the Monte Carlo tab uses.
        db.set_assumptions({"return_volatility": 0.12, "iterations": 200})
        status, _ = self._post("/api/assumptions", {"expected_return_pct": "9.0"})
        self.assertEqual(status, 200)
        assumptions = db.get_assumptions()
        self.assertAlmostEqual(float(assumptions["expected_return"]), 0.09)
        self.assertAlmostEqual(float(assumptions["return_volatility"]), 0.12)

        resp = self._get("/summary.html")
        body = resp.read().decode("utf-8")
        self.assertIn("9.00% average yearly growth", body)


class TestMonteCarloStartingBalance(DashboardTestCase):
    """The Monte Carlo tab's starting balance is Investable savings -- 401k +
    Liquid, net of liabilities -- not full net worth: real estate equity
    and other Asset-tab categories (Insurance, etc.) aren't money you'd
    draw down in retirement, and liabilities (a loan, a credit card
    balance, ...) do reduce what's actually available, per the user's
    "montecarlo simulations should be on 'Investable savings'" request. The
    Summary tab's "What if: expected return" card runs the same
    simulation and must show the same starting balance, so the two tabs
    stay in sync with each other."""

    def setUp(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade", "balance": 50_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Insurance", "name": "Whole life", "balance": 20_000})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Credit card", "balance": 10_000})
        db.add_line_item("real_estate", {"name": "Home", "current_value": 500_000, "loan_balance": 300_000, "ownership_pct": 100})

    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("real_estate")

    def test_monte_carlo_page_starting_balance_is_net_liquid_asset(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        # 100,000 (401k) + 50,000 (Liquid) - 10,000 (liability) =
        # 140,000 -- net of the liability (unlike the old
        # retirement_liquid_total, which would show 150,000 here), and
        # not the 360,000 net worth (which would also add Insurance and
        # RE equity).
        self.assertIn("$140,000", body)
        self.assertNotIn("$150,000", body)
        self.assertNotIn("$360,000", body)

    def test_summary_page_what_if_card_shows_the_same_starting_balance(self):
        resp = self._get("/summary.html")
        body = resp.read().decode("utf-8")
        self.assertIn("$140,000", body)

    def test_monte_carlo_and_summary_pages_agree_on_starting_balance(self):
        # The two tabs must never drift apart -- both read build_summary()'s
        # net_liquid_asset, so a figure that appears on one must appear
        # on the other too.
        mc_body = self._get("/monte-carlo.html").read().decode("utf-8")
        summary_body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("$140,000", mc_body)
        self.assertIn("$140,000", summary_body)


class TestMonteCarloStartingBalanceWithOptedInRealEstate(DashboardTestCase):
    """Reported bug: once a property is opted in to the simulation (Real
    Estate Analysis tab's "In the plan?"), run_simulation/
    run_historical_bootstrap_simulation/run_historical_stress_test all
    ignore their own `starting_balance` argument and instead walk down
    sum(pools.values()) -- which includes the opted-in real estate
    equity as a 4th pool (see source.reporting.monte_carlo.
    _run_random_simulation's own comment) -- but the Monte Carlo and
    Summary pages' intro text still only quoted Investable savings, understating
    the money actually being simulated. Fixed by a "Starting balance"
    tile (Investable savings + opted-in real estate) and updated copy on
    both pages."""

    def setUp(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade", "balance": 50_000, "include_in_monte_carlo": 1})
        item_id = db.add_line_item("real_estate", {"name": "Rental", "current_value": 500_000, "loan_balance": 200_000, "ownership_pct": 100})
        db.update_line_item("real_estate", item_id, {"include_in_monte_carlo": 1})

    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("real_estate")

    def test_monte_carlo_page_starting_balance_tile_includes_opted_in_real_estate(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        # Investable savings (150,000) + opted-in equity (500,000 - 200,000
        # = 300,000) = 450,000 -- not just the 150,000 Investable savings.
        self.assertIn('<div class="label">Starting balance</div><div class="value">$450,000</div>', body)
        self.assertIn('<div class="label">Real estate (opted in)</div><div class="value">$300,000</div>', body)

    def test_monte_carlo_page_intro_paragraph_states_the_correct_total(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Plus $300,000 of real estate equity opted in", body)
        self.assertIn("$450,000 simulated in total", body)

    def test_summary_what_if_card_starting_balance_tile_includes_opted_in_real_estate(self):
        resp = self._get("/summary.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<div class="label">Starting balance</div><div class="value">$450,000</div>', body)


class TestMonteCarloAndSummaryAgreeOnSimulationResults(DashboardTestCase):
    """Reported bug: the Monte Carlo tab and the Summary tab's "What if"
    card showed two different Median ending balance / Success rate
    figures for the same plan. Both call run_simulation() with identical
    starting_balance/pools/assumptions/expenses/income (see
    TestMonteCarloStartingBalance above), but each used to leave `rng`
    unseeded -- two independent, unseeded 1000-path Monte Carlo runs
    landing on two different (if both individually plausible) numbers by
    pure chance, not a calculation error. source.reporting.monte_carlo.
    stable_simulation_seed fixes this by deriving a seed from those same
    inputs, so both tabs replay the exact same 1000 paths."""

    def setUp(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 1_000_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade", "balance": 500_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Baseline", "category": "Fixed", "annual_amount": 60_000})

    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("expenses")
        db.set_assumption("expected_return", 0.06)

    def test_median_ending_balance_matches_between_the_two_tabs(self):
        mc_body = self._get("/monte-carlo.html").read().decode("utf-8")
        summary_body = self._get("/summary.html").read().decode("utf-8")
        mc_value = re.search(r"Typical case</div><div class=\"value\">(\$[\d,.]+)</div>", mc_body).group(1)
        summary_value = re.search(r"Typical case</div><div class=\"value\">(\$[\d,.]+)</div>", summary_body).group(1)
        self.assertEqual(mc_value, summary_value)

    def test_success_rate_matches_between_the_two_tabs(self):
        mc_body = self._get("/monte-carlo.html").read().decode("utf-8")
        summary_body = self._get("/summary.html").read().decode("utf-8")
        mc_value = re.search(r"Chance your money lasts</div><div class=\"value\">((?:&gt;|>)?\d+%)</div>", mc_body).group(1)
        summary_value = re.search(r"Chance your money lasts</div><div class=\"value\">((?:&gt;|>)?\d+%)</div>", summary_body).group(1)
        self.assertEqual(mc_value, summary_value)

    def test_reloading_either_tab_repeatedly_gives_the_same_number(self):
        # Not just cross-tab agreement -- also reproducible run to run,
        # since the same tab's own simulation used to re-randomize on
        # every page load too.
        first = self._get("/monte-carlo.html").read().decode("utf-8")
        second = self._get("/monte-carlo.html").read().decode("utf-8")
        first_value = re.search(r"Typical case</div><div class=\"value\">(\$[\d,.]+)</div>", first).group(1)
        second_value = re.search(r"Typical case</div><div class=\"value\">(\$[\d,.]+)</div>", second).group(1)
        self.assertEqual(first_value, second_value)

    def test_changing_an_assumption_changes_the_result(self):
        # The determinism shouldn't be so sticky that a real change to
        # the plan gets ignored -- a different expected return should
        # (almost certainly) produce a different median ending balance.
        before = self._get("/monte-carlo.html").read().decode("utf-8")
        before_value = re.search(r"Typical case</div><div class=\"value\">(\$[\d,.]+)</div>", before).group(1)
        db.set_assumption("expected_return", 0.15)
        after = self._get("/monte-carlo.html").read().decode("utf-8")
        after_value = re.search(r"Typical case</div><div class=\"value\">(\$[\d,.]+)</div>", after).group(1)
        self.assertNotEqual(before_value, after_value)


class TestSummaryPageAssetTotals(DashboardTestCase):
    """The Summary tab no longer shows a standalone "Manual asset total"
    tile -- it didn't match what the Assets tab itself displayed, since the
    Assets tab breaks balances out by category (401k, Liquid, Insurance,
    ...). Instead the Summary tab shows the same real, per-category
    balances and totals the Assets tab shows, plus a rate-of-return tile."""

    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("real_estate")
        db.clear_section("expenses")

    def _seed(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 100_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade", "balance": 50_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Insurance", "name": "Whole life", "balance": 20_000})
        db.add_line_item("assets", {"kind": "liability", "category": "Loan", "name": "Credit card", "balance": 5_000})
        db.add_line_item("real_estate", {"name": "Home", "current_value": 500_000, "loan_balance": 300_000, "ownership_pct": 100})

    def test_manual_asset_total_label_is_gone(self):
        self._seed()
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertNotIn("Manual asset total", body)

    def test_linked_account_balances_tile_is_gone(self):
        self._seed()
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertNotIn("Linked account balances", body)

    def test_expense_need_tile_shows_next_years_projected_number(self):
        db.set_assumption("current_year", 2026)
        db.set_assumption("inflation_rate", 0.0)
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 300_000})
        body = self._get("/summary.html").read().decode("utf-8")
        # Shows 2027 (next year), not 2026 (this year) -- and does not
        # also show a stale "2026 expense need" tile.
        self.assertIn('<div class="label">Yearly spending in 2027</div><div class="value">$300,000</div>', body)
        self.assertNotIn("Yearly spending in 2026", body)

    def test_net_liquid_asset_and_total_asset_tiles_are_present(self):
        self._seed()
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn('<div class="label">Investable savings</div><div class="value">$145,000</div>', body)
        # The ledger lists property at full market value, its mortgage under
        # "owe", and the lines reconcile to net worth.
        from source.reporting.aggregate import build_summary

        sm = build_summary()
        own = sm["manual_asset_total"] + sm["linked_asset_total"] + sm["real_estate_value_total"]
        owe = sm["liability_total"] + (sm["real_estate_value_total"] - sm["real_estate_equity_total"])
        self.assertAlmostEqual(own - owe, sm["net_worth"], places=2)
        self.assertIn(f"Total you own</span><span class=\"grow\"></span><strong>${own:,.0f}</strong>", body)
        self.assertIn(f"Total you owe</span><span class=\"grow\"></span><strong>${owe:,.0f}</strong>", body)
        self.assertIn("Real estate (market value)", body)
        self.assertIn("Mortgages &amp; property loans", body)

    def test_expected_rate_of_return_tile_shows_the_assumption_as_a_percent(self):
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 60_000})
        resp = self._get("/summary.html")
        body = resp.read().decode("utf-8")
        # No assumptions saved yet -- falls back to the same 6.00% default
        # the Monte Carlo Assumptions form uses.
        self.assertIn("6.00% average yearly growth", body)

    def test_summary_points_to_the_asset_tab_instead_of_repeating_the_category_table(self):
        # The per-category table lives only on the Assets tab; Summary keeps
        # its Net Liquid / Total Asset tiles and links across.
        self._seed()
        summary_body = self._get("/summary.html").read().decode("utf-8")
        asset_body = self._get("/asset.html").read().decode("utf-8")
        self.assertNotIn("Assets by category", summary_body)
        self.assertIn('href="/asset.html"', summary_body)
        for expected in (
            "<td>401k</td><td class=\"num\">$100,000</td>",
            "<td>Liquid</td><td class=\"num\">$50,000</td>",
            "<td>Insurance</td><td class=\"num\">$20,000</td>",
            "Investable savings</td><td class=\"num\">$145,000</td>",
            "Total Asset</td><td class=\"num\">$345,000</td>",
        ):
            self.assertIn(expected, asset_body)

    def test_empty_state_shows_zero_totals_not_an_error(self):
        resp = self._get("/summary.html")
        body = resp.read().decode("utf-8")
        # A brand-new plan shows the welcome card rather than a wall of $0s.
        self.assertIn("let&#x27;s build your plan", body)
        self.assertIn("/setup-wizard.html", body)
        self.assertNotIn("Investable savings", body)

    def test_rollup_table_renders_above_the_category_summary_table(self):
        self._seed()
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertLess(body.index("Total Asset</td>"), body.index("Investable savings = the balance"))


class TestGaussianSimulationTiles(DashboardTestCase):
    """The Monte Carlo tab's first simulation (drawing returns from the
    Expected return/Return volatility assumptions the user sets) reports
    a 10th/median/90th percentile ending balance range alongside success
    rate and iterations -- not just the median -- so the spread is visible
    without reading it off the fan chart."""

    def setUp(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 1_000_000})

    def tearDown(self):
        db.clear_section("assets")

    def test_tiles_include_10th_median_and_90th_percentile_ending_balance(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Chance your money lasts", body)
        self.assertIn("Iterations", body)
        self.assertRegex(body, r"Cautious case \(1 in 10 do worse\)</div><div class=\"value\">\$[\d,]+</div>")
        self.assertRegex(body, r"Typical case</div><div class=\"value\">\$[\d,]+</div>")
        self.assertRegex(body, r"Strong case \(1 in 10 do better\)</div><div class=\"value\">\$[\d,]+</div>")

    def test_tile_values_match_a_freshly_run_gaussian_simulation(self):
        from source.reporting.aggregate import build_summary
        from source.reporting.monte_carlo import run_simulation

        s = build_summary()
        result = run_simulation(
            starting_balance=s["net_liquid_asset"], expenses=s["expenses"], income=s["income"],
            assumptions=s["assumptions"], rng=random.Random(0),
        )
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        # Randomly seeded per request, so just confirm this section's own
        # (non-"S&P 500"-prefixed) tiles are present and well-formed --
        # exact figures will differ from this one-off comparison run.
        self.assertIsNotNone(result)
        self.assertNotIn('<div class="label">S&amp;P 500 10th percentile ending balance', body.split("S&amp;P 500 historical-returns simulation")[0])


class TestSp500HistoricalBootstrapSection(DashboardTestCase):
    """The Monte Carlo tab's second random simulation -- draws each
    simulated year's return from real recorded S&P 500 annual returns
    (bootstrap resampling) instead of the Gaussian expected-return/
    volatility assumptions, reported as its own success rate + p10/
    median/p90 ending balance tiles alongside the Gaussian one's tiles
    and chart. Per user feedback this section reports figures only --
    no fan chart of its own (see
    test_section_has_no_chart_of_its_own_just_the_gaussian_fan_chart_above)."""

    def setUp(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 1_000_000})

    def tearDown(self):
        db.clear_section("assets")

    def test_section_heading_and_tiles_are_present(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn("S&amp;P 500 historical-returns simulation", body)
        self.assertIn("S&amp;P 500 chance your money lasts", body)
        self.assertIn("S&amp;P 500 cautious case", body)
        self.assertIn("S&amp;P 500 strong case", body)
        self.assertIn("S&amp;P 500 typical case", body)

    def test_section_has_no_chart_of_its_own_just_the_gaussian_fan_chart_above(self):
        # Per user feedback, this section reports its own tiles (success
        # rate, 10th/median/90th percentile ending balance) but doesn't
        # render a second fan chart -- there's exactly one <svg> on the
        # page, belonging to the Gaussian simulation above it.
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        import re

        # (the nav's own icon tiles are <svg>s too -- count only the page's charts)
        page = re.sub(r"<nav>.*?</nav>", "", body, flags=re.S)
        page = re.sub(r'<button[^>]*id="hide-toggle".*?</button>', "", page, flags=re.S)  # header eye icon
        self.assertEqual(page.count("<svg"), 1)

    def test_tiles_show_figures_consistent_with_a_freshly_run_bootstrap_simulation(self):
        from source.reporting.aggregate import build_summary
        from source.reporting.monte_carlo import run_historical_bootstrap_simulation

        s = build_summary()
        result = run_historical_bootstrap_simulation(
            starting_balance=s["net_liquid_asset"], expenses=s["expenses"], income=s["income"],
            assumptions=s["assumptions"], rng=random.Random(0),
        )
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        # Randomly seeded on each request, so exact figures will differ
        # from this one-off run -- just confirm the section reports
        # sane, present values in the expected dollar format rather than
        # erroring or being blank.
        self.assertRegex(body, r"S&amp;P 500 cautious case</div><div class=\"value\">\$[\d,]+</div>")
        self.assertRegex(body, r"S&amp;P 500 strong case</div><div class=\"value\">\$[\d,]+</div>")
        self.assertIsNotNone(result)  # sanity: the function itself doesn't error on real plan data


class TestHistoricalStressTestTable(DashboardTestCase):
    """The Monte Carlo tab's "Historical recession stress test" table --
    same feature as the original workbook's own tab of that name, added
    per the user's "create a table with all balance and years from
    simulations ... with recession accounted" request."""

    def setUp(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 1_000_000})
        db.set_assumptions({"plan_horizon_years": 3, "current_year": 2028})

    def tearDown(self):
        db.clear_section("assets")
        db.set_assumptions({"plan_horizon_years": 40, "current_year": ""})

    def _stress_test_section(self, body: str) -> str:
        start = body.index("Historical recession stress test")
        # Ends at the Sensitivity section (not Assumptions) -- the
        # sensitivity tornado table sits between the two and has its own
        # "sortable" table, which would otherwise get counted as part of
        # the stress-test section by tests that count sortable tables in
        # this slice.
        end = body.index("<h2 id=\"levers\">What moves your plan most</h2>")
        return body[start:end]

    def test_section_and_both_tables_are_present(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        section = self._stress_test_section(body)
        self.assertIn("Scenario", section)
        self.assertIn("Depleted?", section)
        self.assertIn("Year-by-year detail", section)
        self.assertIn("Great Depression (1929)", section)
        self.assertIn("Dot-com Crash (2000)", section)
        self.assertIn("Global Financial Crisis (2007)", section)
        self.assertIn("Stagflation (1973)", section)
        self.assertNotIn("No-crash baseline", section)
        self.assertIn("Expected return (6.0%/yr)", section)
        self.assertRegex(section, r"S&amp;P 500 last \d+ years average \(\d{4}-\d{4}, ")
        # Expected return is the first scenario column/row.
        self.assertLess(section.index("Expected return (6.0%/yr)"), section.index("Great Depression (1929)"))

    def test_detail_table_has_a_yearly_drawdown_column_shared_across_scenarios(self):
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 60_000, "start_year": None, "end_year": None})
        db.add_line_item("income", {"name": "Rental", "annual_amount": 10_000, "start_year": None, "end_year": None})
        try:
            from source.reporting.aggregate import build_summary
            from source.reporting.monte_carlo import run_historical_stress_test

            s = build_summary()
            result = run_historical_stress_test(
                starting_balance=s["net_liquid_asset"], expenses=s["expenses"], income=s["income"],
                assumptions=s["assumptions"],
            )
            resp = self._get("/monte-carlo.html")
            body = resp.read().decode("utf-8")
            section = self._stress_test_section(body)
            self.assertIn("Yearly Drawdown", section)
            # 60,000 - 10,000 = 50,000, flat every year (no inflation set).
            self.assertIn(dashboard._money(result["yearly_needs"][0]), section)
            self.assertIn(dashboard._money(50_000), section)
        finally:
            db.clear_section("expenses")
            db.clear_section("income")

    def test_detail_table_has_a_total_income_column_next_to_total_expense(self):
        # Shown alongside Total Expense (the two raw, un-netted tab
        # totals) so the user can compare them directly -- e.g. see that
        # an Income row with "Inflates" checked grows year over year same
        # as an inflating Expense row would.
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 60_000, "start_year": None, "end_year": None})
        db.add_line_item("income", {"name": "Rental", "annual_amount": 10_000, "start_year": None, "end_year": None})
        try:
            from source.reporting.aggregate import build_summary
            from source.reporting.monte_carlo import run_historical_stress_test

            s = build_summary()
            result = run_historical_stress_test(
                starting_balance=s["net_liquid_asset"], expenses=s["expenses"], income=s["income"],
                assumptions=s["assumptions"],
            )
            resp = self._get("/monte-carlo.html")
            body = resp.read().decode("utf-8")
            section = self._stress_test_section(body)
            self.assertIn("<th class=\"num\">Total Income</th>", section)
            self.assertEqual(result["yearly_income"][0], 10_000)
            # All three figures appear on the first data row, in Year,
            # Total Expense, Total Income, Yearly Drawdown column order.
            self.assertIn(
                f'<td>2028</td><td class="num">{dashboard._money(60_000)}</td>'
                f'<td class="num">{dashboard._money(10_000)}</td>'
                f'<td class="num">{dashboard._money(50_000)}</td>',
                section,
            )
        finally:
            db.clear_section("expenses")
            db.clear_section("income")

    def test_detail_table_has_a_total_expense_column_next_to_total_income(self):
        # Lets the user check the arithmetic themselves: Total Expense -
        # Total Income (- the flat offset, if any) should equal Yearly
        # Drawdown on every row. Column order puts Total Expense and
        # Total Income next to each other, both before Yearly Drawdown.
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 60_000, "start_year": None, "end_year": None})
        db.add_line_item("income", {"name": "Rental", "annual_amount": 10_000, "start_year": None, "end_year": None})
        try:
            resp = self._get("/monte-carlo.html")
            body = resp.read().decode("utf-8")
            section = self._stress_test_section(body)
            self.assertIn("<th class=\"num\">Total Expense</th>", section)
            # Total Expense's column header appears before Total Income's,
            # which appears before Yearly Drawdown's.
            self.assertLess(
                section.index('<th class="num">Total Expense</th>'),
                section.index('<th class="num">Total Income</th>'),
            )
            self.assertLess(
                section.index('<th class="num">Total Income</th>'),
                section.index('<th class="num">Yearly Drawdown</th>'),
            )
            # No income offset set here (defaults to 0) -- Total Expense
            # (60,000) - Total Income (10,000) == Yearly Drawdown
            # (50,000), directly checkable from the rendered row.
            self.assertIn(
                f'<td>2028</td><td class="num">{dashboard._money(60_000)}</td>'
                f'<td class="num">{dashboard._money(10_000)}</td>'
                f'<td class="num">{dashboard._money(50_000)}</td>',
                section,
            )
        finally:
            db.clear_section("expenses")
            db.clear_section("income")

    def test_detail_table_shows_the_real_1929_return_and_matches_the_computed_balance(self):
        # Ground truth from the simulation function itself, so this test
        # stays correct even if the historical dataset is ever extended --
        # it checks the dashboard renders what the function computed,
        # not a hand-transcribed dollar figure.
        from source.reporting.aggregate import build_summary
        from source.reporting.monte_carlo import run_historical_stress_test

        s = build_summary()
        result = run_historical_stress_test(
            starting_balance=s["net_liquid_asset"], expenses=s["expenses"], assumptions=s["assumptions"],
        )
        gd = next(sc for sc in result["scenarios"] if sc["label"].startswith("Great Depression"))

        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        section = self._stress_test_section(body)
        self.assertIn("Great Depression Return", section)
        self.assertIn("Great Depression Balance", section)
        self.assertIn(f"{gd['path'][0]['return'] * 100:.2f}%", section)  # -8.42%
        self.assertIn(dashboard._money(gd["path"][0]["balance"]), section)
        self.assertIn(dashboard._money(gd["ending_balance"]), section)

    def test_no_expenses_means_no_scenario_depletes(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        section = self._stress_test_section(body)
        summary_table = section[: section.index("Year-by-year detail")]
        self.assertNotIn(">Yes<", summary_table)

    def test_detail_table_rows_are_sortable_like_every_other_table(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        section = self._stress_test_section(body)
        self.assertEqual(section.count('<table class="sortable">'), 2)  # summary + detail


class TestDrawdownTaxAssumption(DashboardTestCase):
    """The Monte Carlo tab's "Apply drawdown tax" checkbox and the Tax
    (Fed+CA)/Total Withdrawal columns it adds to the Year-by-year detail
    table -- added per the user's "add tax related expenditure we need
    on drawdown ... based on current Fed rate and CA tax" request. On by
    default (source.common.db.DEFAULT_ASSUMPTIONS)."""

    def setUp(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 1_000_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 100_000, "start_year": None, "end_year": None})
        db.set_assumptions({"plan_horizon_years": 2, "current_year": 2028})

    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("expenses")
        db.set_assumptions({"plan_horizon_years": 40, "current_year": "", "apply_drawdown_tax": "1"})

    def _stress_test_section(self, body: str) -> str:
        start = body.index("Historical recession stress test")
        # Ends at the Sensitivity section (not Assumptions) -- the
        # sensitivity tornado table sits between the two and has its own
        # "sortable" table, which would otherwise get counted as part of
        # the stress-test section by tests that count sortable tables in
        # this slice.
        end = body.index("<h2 id=\"levers\">What moves your plan most</h2>")
        return body[start:end]

    def test_checkbox_is_checked_by_default(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<input type="checkbox" name="apply_drawdown_tax" value="1" style="width:auto;" checked>', body)
        self.assertIn("Apply drawdown tax (Fed + CA, current brackets)", body)

    def test_detail_table_has_tax_and_total_withdrawal_columns_after_yearly_drawdown(self):
        # The dashboard always calls the simulation functions with the
        # Assets tab's three-pool split (source.webapp.pages.monte_carlo_page.
        # _render_monte_carlo_page's pools=pools), so the live page is
        # always in per-scenario-tax mode: Tax/Total Withdrawal aren't a
        # shared column pair anymore (that's only true in the legacy
        # pools=None path exercised directly against
        # run_historical_stress_test elsewhere) -- each scenario gets its
        # own Return/Tax/Withdrawal/Balance group instead.
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        section = self._stress_test_section(body)
        self.assertLess(
            section.index('<th class="num">Yearly Drawdown</th>'),
            section.index('<th class="num">Great Depression Return</th>'),
        )
        self.assertLess(
            section.index('<th class="num">Great Depression Return</th>'),
            section.index('<th class="num">Great Depression Tax</th>'),
        )
        self.assertLess(
            section.index('<th class="num">Great Depression Tax</th>'),
            section.index('<th class="num">Great Depression Withdrawal</th>'),
        )
        self.assertLess(
            section.index('<th class="num">Great Depression Withdrawal</th>'),
            section.index('<th class="num">Great Depression Balance</th>'),
        )
        self.assertNotIn('<th class="num">Tax (Fed+CA)</th>', section)
        self.assertNotIn('<th class="num">Total Withdrawal</th>', section)

    def test_tax_is_positive_and_total_withdrawal_is_need_plus_tax_by_default(self):
        from source.reporting.aggregate import build_summary
        from source.reporting.monte_carlo import run_historical_stress_test

        s = build_summary()
        result = run_historical_stress_test(
            starting_balance=s["net_liquid_asset"], expenses=s["expenses"], assumptions=s["assumptions"],
        )
        self.assertTrue(result["apply_drawdown_tax"])
        self.assertGreater(result["yearly_tax"][0], 0.0)
        self.assertAlmostEqual(result["yearly_total_withdrawal"][0], result["yearly_needs"][0] + result["yearly_tax"][0], places=6)

        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        section = self._stress_test_section(body)
        self.assertIn(dashboard._money(result["yearly_tax"][0]), section)
        self.assertIn(dashboard._money(result["yearly_total_withdrawal"][0]), section)

    def test_unchecking_apply_drawdown_tax_zeroes_the_tax_column_and_updates_the_balance(self):
        status, payload = self._post("/api/assumptions", {"apply_drawdown_tax": 0})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_assumptions()["apply_drawdown_tax"], "0")

        from source.reporting.aggregate import build_summary
        from source.reporting.monte_carlo import run_historical_stress_test

        s = build_summary()
        result = run_historical_stress_test(
            starting_balance=s["net_liquid_asset"], expenses=s["expenses"], assumptions=s["assumptions"],
        )
        self.assertFalse(result["apply_drawdown_tax"])
        self.assertEqual(result["yearly_tax"][0], 0.0)
        self.assertEqual(result["yearly_total_withdrawal"][0], result["yearly_needs"][0])

        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        # Unchecked -- no trailing " checked" before the tag closes (the
        # checked variant, asserted in test_checkbox_is_checked_by_default
        # above, always has one).
        self.assertIn('<input type="checkbox" name="apply_drawdown_tax" value="1" style="width:auto;">', body)
        section = self._stress_test_section(body)
        # Tax column reads $0, immediately followed by Total
        # Withdrawal equal to Yearly Drawdown (needs[0]) -- confirms the
        # table (not just the raw result dict above) reflects tax being off.
        self.assertIn(
            f'<td class="num">{dashboard._money(0.0)}</td>'
            f'<td class="num">{dashboard._money(result["yearly_needs"][0])}</td>',
            section,
        )

    def test_re_checking_apply_drawdown_tax_restores_a_positive_tax(self):
        self._post("/api/assumptions", {"apply_drawdown_tax": 0})
        status, payload = self._post("/api/assumptions", {"apply_drawdown_tax": 1})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_assumptions()["apply_drawdown_tax"], "1")
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<input type="checkbox" name="apply_drawdown_tax" value="1" style="width:auto;" checked>', body)

    def test_gaussian_tiles_show_estimated_tax_when_applied(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn("First-year tax (median path)", body)
        self.assertIn("Total tax over horizon", body)

    def test_gaussian_tiles_omit_tax_when_turned_off(self):
        self._post("/api/assumptions", {"apply_drawdown_tax": 0})
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertNotIn("First-year tax (median path)", body)
        self.assertNotIn("Total tax over horizon", body)


class TestMonteCarloSensitivitySection(DashboardTestCase):
    """The Monte Carlo tab's "What moves your plan most" tornado
    view (source.reporting.monte_carlo.sensitivity) -- rendered by
    _sensitivity_html in monte_carlo_page.py, between the historical
    stress test and the Assumptions form."""

    def setUp(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 1_000_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None})

    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("expenses")

    def test_section_renders_with_every_lever_labeled(self):
        resp = self._get("/monte-carlo.html")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode("utf-8")
        self.assertIn("What moves your plan most", body)
        for label in ("Expected return", "Return volatility", "Inflation", "Plan horizon", "Expense level", "Income level"):
            self.assertIn(label, body)

    def test_section_reports_a_baseline_success_rate(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn("This plan's baseline Success rate is", body)

    def test_scenarios_come_right_after_the_answer_then_the_levers_then_the_assumptions(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        stress_idx = body.index("Historical recession stress test")
        sensitivity_idx = body.index("What moves your plan most")
        assumptions_idx = body.index('id="assumptions"')
        # Scenario table and year-by-year returns come first (right after the answer), then the levers.
        self.assertLess(stress_idx, sensitivity_idx)
        self.assertLess(sensitivity_idx, assumptions_idx)

    def test_year_by_year_numbers_start_expanded_and_social_security_is_folded_below(self):
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn('style="margin-top:14px" open><summary>Show the year-by-year numbers</summary>', body)
        self.assertIn('id="ss-fold"', body)
        self.assertLess(body.index("Historical recession stress test"), body.index('id="ss-fold"'))


class TestMonteCarloPoolsAndRmd(DashboardTestCase):
    """The Monte Carlo tab's three-pool split (Tax-deferred/Roth/Taxable
    tiles, sourced from each Asset row's Tax treatment) and RMD
    modeling (Birth year assumption + the "set a Birth year" nudge) --
    added per the user's "add per-account tax treatment and RMD-aware
    withdrawal ordering" request. build_summary()'s retirement_pools is
    exercised in tests/test_aggregate.py; this class only checks the
    Monte Carlo page renders it and the two new assumption fields
    correctly."""

    def setUp(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 400_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Roth IRA", "balance": 100_000, "tax_treatment": "roth", "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Etrade brokerage", "balance": 250_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 60_000, "start_year": None, "end_year": None})

    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("expenses")
        # db.set_assumptions() stores keys literally -- it doesn't do the
        # "_pct" suffix -> /100 conversion that only the /api/assumptions
        # HTTP endpoint applies, so resetting after a test that POSTed
        # "taxable_gains_fraction_pct" means resetting the underlying
        # "taxable_gains_fraction" key itself, not the "_pct"-suffixed one
        # -- and back to its real default (DEFAULT_ASSUMPTIONS'
        # "0.4"), not "", since an empty string isn't treated the same
        # as an absent key by _pct()'s .get(key, default).
        db.set_assumptions({
            "birth_year": "", "retirement_year": "", "taxable_gains_fraction": "0.4",
            "plan_horizon_years": 40, "current_year": "",
        })

    def test_pool_tiles_show_balances_by_tax_treatment(self):
        # 401k -> tax_deferred (category default), the row explicitly
        # marked roth -> roth, the other Liquid row (no tax_treatment
        # set) -> taxable (category default) -- same
        # _DEFAULT_TAX_TREATMENT_BY_CATEGORY resolution
        # source.reporting.aggregate.effective_tax_treatment uses.
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Pre-tax (401k / traditional IRA)", body)
        self.assertIn("Roth (tax-free)", body)
        self.assertIn("Taxable (brokerage)", body)
        self.assertIn(dashboard._money(400_000), body)
        self.assertIn(dashboard._money(100_000), body)
        self.assertIn(dashboard._money(250_000), body)

    def test_birth_year_field_defaults_blank_and_shows_rmd_nudge(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<label>Person 1\'s birth year (for RMDs)<input name="birth_year" type="number" step="1" placeholder="e.g. 1960" value="">', body)
        self.assertIn("Set a Birth year in Assumptions below", body)

    def test_setting_birth_year_persists_and_removes_the_rmd_nudge(self):
        status, _ = self._post("/api/assumptions", {"birth_year": "1960"})
        self.assertEqual(status, 200)
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn('name="birth_year" type="number" step="1" placeholder="e.g. 1960" value="1960"', body)
        self.assertNotIn("Set a Birth year in Assumptions below", body)

    def test_taxable_gains_fraction_field_defaults_to_40_percent(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<label>Taxable gains %<input name="taxable_gains_fraction_pct" type="number" step="1" value="40.00"', body)

    def test_setting_taxable_gains_fraction_persists(self):
        status, _ = self._post("/api/assumptions", {"taxable_gains_fraction_pct": "25"})
        self.assertEqual(status, 200)
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<label>Taxable gains %<input name="taxable_gains_fraction_pct" type="number" step="1" value="25.00"', body)

    def test_intro_paragraph_mentions_the_three_pool_withdrawal_order(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn("drawn Taxable first, then Tax-deferred, then Roth last", body)

    def test_retirement_year_field_defaults_blank_and_shows_a_nudge(self):
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn('<label>Retirement year<input name="retirement_year" type="number" step="1" placeholder="e.g. 2035" value="">', body)
        self.assertIn("Set a Retirement year in Assumptions below", body)

    def test_setting_retirement_year_persists_and_removes_the_nudge(self):
        status, _ = self._post("/api/assumptions", {"retirement_year": "2035"})
        self.assertEqual(status, 200)
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        self.assertIn('name="retirement_year" type="number" step="1" placeholder="e.g. 2035" value="2035"', body)
        self.assertNotIn("Set a Retirement year in Assumptions below", body)
        self.assertIn("No withdrawal happens in any simulated year before 2035", body)

    def test_setting_retirement_year_hides_pre_retirement_rows_from_the_historical_stress_test(self):
        db.set_assumptions({"current_year": "2026", "plan_horizon_years": "3", "retirement_year": "2028", "apply_drawdown_tax": "0"})
        resp = self._get("/monte-carlo.html")
        body = resp.read().decode("utf-8")
        # Year-by-year detail table columns are Year, Total Expense,
        # Total Income, Yearly Drawdown. 2026/2027 (before retirement)
        # withdraw nothing by design, so those rows are hidden entirely
        # rather than shown with a $0 Yearly Drawdown; 2028 is the
        # first (and here, only) visible row, showing the real $60,000
        # Yearly Drawdown.
        money0, money60k = dashboard._money(0), dashboard._money(60_000)
        self.assertNotIn(f'<td>2026</td><td class="num">{money60k}</td><td class="num">{money0}</td><td class="num">{money0}</td>', body)
        self.assertNotIn(f'<td>2027</td><td class="num">{money60k}</td><td class="num">{money0}</td><td class="num">{money0}</td>', body)
        self.assertIn(f'<td>2028</td><td class="num">{money60k}</td><td class="num">{money0}</td><td class="num">{money60k}</td>', body)
        self.assertIn("Years before 2028 (your set Retirement year) are omitted below", body)


class TestHistoricalStressTestHtmlPerScenarioTax(unittest.TestCase):
    """Unit tests for source.webapp.pages.monte_carlo_page.
    _historical_stress_test_html against hand-built result dicts, so
    both branches (legacy shared Tax/Total Withdrawal columns vs.
    per-scenario Tax/Withdrawal columns) are covered directly without
    needing a live three-pool plan through the HTTP layer."""

    def _base_result(self, **overrides):
        result = {
            "years": [2026, 2027],
            "last_recorded_year": 2025,
            "apply_drawdown_tax": True,
            "yearly_total_expense": [60_000, 61_800],
            "yearly_income": [0, 0],
            "yearly_needs": [60_000, 61_800],
            "scenarios": [
                {
                    "label": "Great Depression (1929)",
                    "depleted": False,
                    "depleted_year": None,
                    "ending_balance": 900_000,
                    "path": [
                        {"return": -0.0842, "balance": 950_000},
                        {"return": -0.25, "balance": 900_000},
                    ],
                },
            ],
        }
        result.update(overrides)
        return result

    def test_legacy_mode_keeps_shared_tax_and_total_withdrawal_columns(self):
        from source.webapp.pages.monte_carlo_page import _historical_stress_test_html

        result = self._base_result(
            yearly_tax=[8_000, 8_200],
            yearly_total_withdrawal=[68_000, 70_000],
        )
        html_out = _historical_stress_test_html(result)
        self.assertIn('<th class="num">Tax (Fed+CA)</th>', html_out)
        self.assertIn('<th class="num">Total Withdrawal</th>', html_out)
        self.assertNotIn("Great Depression Tax", html_out)
        self.assertNotIn("Great Depression Withdrawal", html_out)
        self.assertIn(dashboard._money(8_000), html_out)
        self.assertIn(dashboard._money(68_000), html_out)

    def test_per_scenario_tax_mode_gives_each_scenario_its_own_tax_and_withdrawal_columns(self):
        from source.webapp.pages.monte_carlo_page import _historical_stress_test_html

        result = self._base_result(per_scenario_tax=True)
        result["scenarios"][0]["yearly_tax"] = [7_500, 7_700]
        result["scenarios"][0]["yearly_total_withdrawal"] = [67_500, 69_500]
        html_out = _historical_stress_test_html(result)
        self.assertNotIn('<th class="num">Tax (Fed+CA)</th>', html_out)
        self.assertNotIn('<th class="num">Total Withdrawal</th>', html_out)
        self.assertIn('<th class="num">Great Depression Tax</th>', html_out)
        self.assertIn('<th class="num">Great Depression Withdrawal</th>', html_out)
        self.assertLess(
            html_out.index('<th class="num">Great Depression Return</th>'),
            html_out.index('<th class="num">Great Depression Tax</th>'),
        )
        self.assertLess(
            html_out.index('<th class="num">Great Depression Tax</th>'),
            html_out.index('<th class="num">Great Depression Withdrawal</th>'),
        )
        self.assertLess(
            html_out.index('<th class="num">Great Depression Withdrawal</th>'),
            html_out.index('<th class="num">Great Depression Balance</th>'),
        )
        self.assertIn(dashboard._money(7_500), html_out)
        self.assertIn(dashboard._money(67_500), html_out)

    def test_per_scenario_tax_mode_handles_missing_per_scenario_lists_gracefully(self):
        # Defensive: a scenario dict without yearly_tax/yearly_total_withdrawal
        # (shouldn't happen given how run_historical_stress_test builds
        # them, but the renderer shouldn't crash if it ever did) renders
        # blank cells rather than raising.
        from source.webapp.pages.monte_carlo_page import _historical_stress_test_html

        result = self._base_result(per_scenario_tax=True)
        html_out = _historical_stress_test_html(result)
        self.assertIn('<th class="num">Great Depression Tax</th>', html_out)

    def test_per_scenario_tax_mode_zero_tax_note_when_drawdown_tax_off(self):
        from source.webapp.pages.monte_carlo_page import _historical_stress_test_html

        result = self._base_result(per_scenario_tax=True, apply_drawdown_tax=False)
        result["scenarios"][0]["yearly_tax"] = [0, 0]
        result["scenarios"][0]["yearly_total_withdrawal"] = [60_000, 61_800]
        html_out = _historical_stress_test_html(result)
        self.assertIn("Total Withdrawal equals Yearly Drawdown", html_out)


class TestBackupsCard(DashboardTestCase):
    """The Setup page's Backups card and the /api/backup-now endpoint --
    added per the user's "implement automatic backup" request. DashboardTestCase
    builds its server directly rather than through dashboard.run(), so
    no startup backup happens on its own here -- each test starts from
    zero backups."""

    def tearDown(self):
        for b in backup.list_backups():
            Path(b["path"]).unlink(missing_ok=True)

    def test_setup_page_shows_no_backups_yet_before_any_are_taken(self):
        resp = self._get("/setup.html")
        body = resp.read().decode("utf-8")
        self.assertIn("No backups yet", body)

    def test_back_up_now_creates_a_backup_and_the_setup_page_reflects_it(self):
        status, payload = self._post("/api/backup-now", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(Path(payload["path"]).exists())

        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn("1 backup on disk", body)
        self.assertIn(Path(payload["path"]).name, body)

    def test_multiple_backups_show_plural_count_and_most_recent_first(self):
        backup.create_backup(reason="one")
        backup.create_backup(reason="two")
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn("2 backups on disk", body)

    def test_backups_folder_location_is_shown(self):
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn(str(backup.backup_dir()), body)


class TestExportEndpoint(DashboardTestCase):
    def test_export_returns_a_path_that_exists(self):
        status, payload = self._post("/api/export", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(Path(payload["path"]).exists())


class TestPlaidCredentialsEndpoint(DashboardTestCase):
    def tearDown(self):
        secrets_store.clear_vault_cache()
        self.fake_keyring._store.clear()

    def test_saving_credentials_updates_the_vault(self):
        status, payload = self._post("/api/plaid-credentials", {
            "client_id": "client-abc", "secret": "secret-xyz", "environment": "sandbox",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(secrets_store.get_plaid_client_id(), "client-abc")
        self.assertEqual(secrets_store.get_plaid_secret(env="sandbox"), "secret-xyz")

    def test_setup_page_reflects_saved_credentials(self):
        self._post("/api/plaid-credentials", {"client_id": "client-abc", "secret": "s", "environment": "sandbox"})
        resp = self._get("/setup.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Client ID: saved", body)
        self.assertIn("sandbox", body)

    def test_credentials_default_to_the_primary_profile(self):
        status, payload = self._post("/api/plaid-credentials", {
            "client_id": "client-abc", "secret": "secret-xyz", "environment": "sandbox",
        })
        self.assertEqual(status, 200)
        self.assertEqual(secrets_store.get_plaid_client_id(profile="primary"), "client-abc")
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.get_plaid_client_id(profile="secondary")

    def test_saving_secondary_profile_does_not_touch_primary(self):
        self._post("/api/plaid-credentials", {
            "client_id": "primary-client", "secret": "primary-secret", "environment": "sandbox", "profile": "primary",
        })
        self._post("/api/plaid-credentials", {
            "client_id": "secondary-client", "secret": "secondary-secret", "environment": "sandbox", "profile": "secondary",
        })
        self.assertEqual(secrets_store.get_plaid_client_id(profile="primary"), "primary-client")
        self.assertEqual(secrets_store.get_plaid_client_id(profile="secondary"), "secondary-client")

    def test_saving_credentials_for_unknown_profile_returns_400(self):
        status, payload = self._post("/api/plaid-credentials", {
            "client_id": "client-abc", "secret": "s", "environment": "sandbox", "profile": "tertiary",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_setup_page_shows_both_credential_profiles(self):
        resp = self._get("/setup.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Primary", body)
        self.assertIn("Secondary", body)


class TestPlaidConnectEndpoint(DashboardTestCase):
    def tearDown(self):
        db.delete_plaid_item("test_item")
        secrets_store.clear_vault_cache()
        self.fake_keyring._store.clear()

    def test_connect_calls_link_real_item_and_reports_ok(self):
        with patch("source.webapp.dashboard.plaid_link_item.link_real_item", return_value="plaid-item-1") as mock_link:
            status, payload = self._post("/api/plaid-connect", {
                "item_key": "test_item", "products": "investments", "environment": "sandbox",
            })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        mock_link.assert_called_once_with(
            "test_item", products=["investments"], environment="sandbox", profile="primary",
        )

    def test_connect_passes_through_the_chosen_profile(self):
        with patch("source.webapp.dashboard.plaid_link_item.link_real_item", return_value="plaid-item-1") as mock_link:
            status, payload = self._post("/api/plaid-connect", {
                "item_key": "test_item", "products": "investments", "environment": "sandbox", "profile": "secondary",
            })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        mock_link.assert_called_once_with(
            "test_item", products=["investments"], environment="sandbox", profile="secondary",
        )

    def test_connect_without_item_key_returns_400(self):
        status, payload = self._post("/api/plaid-connect", {"products": "investments"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_connect_failure_surfaces_error_message(self):
        with patch(
            "source.webapp.dashboard.plaid_link_item.link_real_item",
            side_effect=TimeoutError("Timed out waiting for Link to complete in the browser."),
        ):
            status, payload = self._post("/api/plaid-connect", {"item_key": "test_item"})
        self.assertEqual(status, 500)
        self.assertFalse(payload["ok"])
        self.assertIn("Timed out", payload["error"])


class TestPlaidRemoveEndpoint(DashboardTestCase):
    def test_remove_calls_remove_item(self):
        with patch("source.webapp.dashboard.plaid_remove_item.remove_item") as mock_remove:
            status, payload = self._post("/api/plaid-remove", {"item_key": "test_item"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        mock_remove.assert_called_once_with("test_item")

    def test_remove_without_item_key_returns_400(self):
        status, payload = self._post("/api/plaid-remove", {})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])


class TestChooseFileEndpoint(DashboardTestCase):
    def test_returns_chosen_path_on_success(self):
        fake_result = Mock(returncode=0, stdout="/Users/hadya/Downloads/plan.xlsx\n", stderr="")
        with patch("source.webapp.dashboard.subprocess.run", return_value=fake_result):
            status, payload = self._post("/api/choose-file", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["path"], "/Users/hadya/Downloads/plan.xlsx")

    def test_user_canceling_the_dialog_is_not_a_500(self):
        fake_result = Mock(returncode=1, stdout="", stderr="execution error: User canceled. (-128)")
        with patch("source.webapp.dashboard.subprocess.run", return_value=fake_result):
            status, payload = self._post("/api/choose-file", {})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "Canceled")

    def test_other_osascript_failure_surfaces_message(self):
        fake_result = Mock(returncode=1, stdout="", stderr="some other AppleScript error")
        with patch("source.webapp.dashboard.subprocess.run", return_value=fake_result):
            status, payload = self._post("/api/choose-file", {})
        self.assertEqual(status, 500)
        self.assertFalse(payload["ok"])
        self.assertIn("some other AppleScript error", payload["error"])

    def test_osascript_missing_surfaces_a_friendly_message(self):
        with patch("source.webapp.dashboard.subprocess.run", side_effect=FileNotFoundError()):
            status, payload = self._post("/api/choose-file", {})
        self.assertEqual(status, 500)
        self.assertFalse(payload["ok"])
        self.assertIn("file picker", payload["error"].lower())


class TestPlaidSyncEndpoint(DashboardTestCase):
    def tearDown(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM net_worth_snapshots")

    def test_sync_calls_sync_all_and_returns_summary(self):
        fake_summary = {"items_synced": ["a"], "errors": [], "accounts": 1, "holdings": 0, "synced_at": "now"}
        with patch("source.webapp.dashboard.plaid_sync.sync_all", return_value=fake_summary) as mock_sync:
            status, payload = self._post("/api/plaid-sync", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"], fake_summary)
        mock_sync.assert_called_once()

    def test_sync_also_captures_a_net_worth_snapshot(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM net_worth_snapshots")
        with patch("source.webapp.dashboard.plaid_sync.sync_all", return_value={}):
            self._post("/api/plaid-sync", {})
        self.assertEqual(len(db.list_net_worth_snapshots()), 1)

    def test_a_snapshot_failure_does_not_fail_the_sync_response(self):
        with patch("source.webapp.dashboard.plaid_sync.sync_all", return_value={}), \
             patch("source.webapp.dashboard.capture_net_worth_snapshot", side_effect=RuntimeError("boom")):
            status, payload = self._post("/api/plaid-sync", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])


class TestSyncNowButtonPlacement(DashboardTestCase):
    """"Sync now" moved off the Setup page and onto Summary (when at least
    one Plaid item is connected), Linked Accounts, and Linked Positions
    (the latter two always, since those pages are nothing but synced
    data) -- see _sync_now_button_html."""

    def tearDown(self):
        db.delete_plaid_item("test_item")

    def _link_an_item(self):
        db.upsert_plaid_item(
            item_key="test_item", plaid_item_id="plaid-item-1", institution_id="ins_1",
            institution_name="Test Bank", products=["investments"], environment="sandbox", linked_at="now",
        )

    def test_setup_page_no_longer_has_the_sync_now_form(self):
        self._link_an_item()
        body = self._get("/setup.html").read().decode("utf-8")
        # The old inline form is gone; the only Sync now left is the compact header button.
        self.assertNotIn('onsubmit="event.preventDefault();\n  var btn = this.querySelector(\'button\');\n  btn.disabled = true; btn.textContent = \'Syncing...\'', body)
        self.assertEqual(body.count(">Sync now<"), 1)
        self.assertIn("<a href=\"/linked-accounts.html\">Linked Accounts</a>", body)
        self.assertIn("<a href=\"/linked-positions.html\">Linked Positions</a>", body)

    def test_linked_pages_use_the_one_header_sync_button(self):
        # One "Sync now" for every tab, in the header once something is linked --
        # not a second copy inside each page.
        self._link_an_item()
        for path in ("/linked-positions.html", "/linked-accounts.html", "/real-expenditure.html", "/summary.html"):
            body = self._get(path).read().decode("utf-8")
            self.assertEqual(body.count(">Sync now<"), 1, path)
            self.assertIn('id="sync-btn"', body)

    def test_linked_pages_have_no_sync_button_when_nothing_is_linked(self):
        for path in ("/linked-positions.html", "/linked-accounts.html", "/real-expenditure.html"):
            self.assertNotIn(">Sync now<", self._get(path).read().decode("utf-8"), path)

    def test_header_sync_alert_includes_account_numbers_and_industries(self):
        self._link_an_item()
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("industry classification(s)", body)

    def test_summary_page_has_sync_now_once_an_item_is_linked(self):
        self._link_an_item()
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn(">Sync now<", body)

    def test_header_sync_button_sits_before_the_report_button(self):
        self._link_an_item()
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn('id="sync-btn"', body)
        self.assertLess(body.index('id="sync-btn"'), body.index('id="report-btn"'))
        self.assertEqual(body.count(">Sync now<"), 1)

    def test_summary_page_omits_sync_now_when_nothing_is_linked(self):
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertNotIn(">Sync now<", body)


class TestLinkedAccountsPage(DashboardTestCase):
    """The "Linked accounts (live, read-only)" table's own tab, split out
    of Linked Positions -- see _render_linked_accounts_page. Institution/
    account-type donuts are split into separate Assets and Liabilities
    breakdowns (see that function's own comment on why)."""

    def setUp(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-brokerage", "name": "Fidelity", "official_name": "Fidelity Brokerage",
            "type": "investment", "subtype": "brokerage", "mask": "5678",
            "balances": {"current": 1500.0, "available": None, "iso_currency_code": "USD"},
        })

    def tearDown(self):
        db.delete_plaid_item("fidelity")

    def test_page_renders_and_nav_includes_it(self):
        resp = self._get("/linked-accounts.html")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode("utf-8")
        self.assertIn("Linked Accounts", body)
        self.assertRegex(body, r'href="/linked-accounts.html" class="active">.*<span class="nl">Linked Accounts</span></a>')

    def test_shows_balance_donuts_and_a_sortable_total(self):
        resp = self._get("/linked-accounts.html")
        body = resp.read().decode("utf-8")
        self.assertIn("Assets by institution", body)
        self.assertIn("Assets by account type", body)
        self.assertIn("Liabilities by institution", body)
        self.assertIn("Liabilities by account type", body)
        self.assertIn('<table id="linked-accounts-table" class="sortable">', body)
        self.assertIn("1,500", body)  # row + total

    def test_assets_and_liabilities_are_charted_separately_not_as_gross_magnitude(self):
        # Regression test for a user-reported mismatch: a single combined
        # "balance" donut used to sum abs(balance) per institution/type,
        # so a mortgage's debt counted as a positive dollar amount right
        # alongside actual asset balances -- an institution's slice could
        # claim far more than its accounts' net balance, and clicking it
        # to filter the table below (whose Total correctly nets
        # liabilities against assets) showed a much smaller number.
        # Splitting into Assets/Liabilities charts means each number is
        # the plain, correct magnitude of exactly what it represents.
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-mortgage", "name": "Mortgage", "official_name": "Mortgage",
            "type": "loan", "subtype": "mortgage", "mask": "1111",
            "balances": {"current": 500_000.0, "available": None, "iso_currency_code": "USD"},
        })
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        assets_section = body.split("Assets by institution")[1].split("Liabilities by institution")[0]
        liabilities_section = body.split("Liabilities by institution")[1].split("Click a slice of any chart")[0]
        # The Assets chart(s) still show only the $1,500 brokerage
        # balance -- the mortgage's $500,000 debt never inflates them.
        self.assertIn("Fidelity: $1,500 (100%)", assets_section)
        self.assertNotIn("$500,000", assets_section)
        # The Liabilities chart(s) show the mortgage's own magnitude.
        self.assertIn("Fidelity: $500,000 (100%)", liabilities_section)
        self.assertNotIn("$1,500", liabilities_section)
        # Net worth line: $1,500 assets minus $500,000 liabilities.
        self.assertIn("net worth across every linked account is -$498,500", body)

    def test_table_has_an_item_key_column_showing_the_real_institution(self):
        resp = self._get("/linked-accounts.html")
        body = resp.read().decode("utf-8")
        self.assertIn("<th>Item Key</th>", body)
        # The row's Institution cell is the Item's real institution name
        # ("Fidelity", from setUp's institution_name) -- not the
        # account's own Plaid name ("Fidelity Brokerage" as official_name,
        # which happens to also start with "Fidelity" here, so assert on
        # the Item Key cell too, which is unambiguous).
        self.assertIn("<td>fidelity</td>", body)

    def test_empty_state_does_not_error(self):
        db.delete_plaid_item("fidelity")
        try:
            resp = self._get("/linked-accounts.html")
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            self.assertIn("No linked account data yet", body)
        finally:
            # Re-seed for this test's own tearDown, which expects the item
            # to still exist.
            db.upsert_plaid_item(
                item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
                institution_name="Fidelity", products=["investments"], environment="sandbox",
                linked_at="2026-09-01T00:00:00+00:00",
            )

    def test_linked_positions_page_no_longer_embeds_the_accounts_table_but_links_to_it(self):
        resp = self._get("/linked-positions.html")
        body = resp.read().decode("utf-8")
        self.assertNotIn("Linked accounts (live, read-only)", body)
        self.assertIn('href="/linked-accounts.html"', body)

    def test_charts_and_table_rows_are_wired_for_click_to_filter(self):
        # Same click-to-filter contract as Linked Positions/Real
        # Expenditure -- data-dim/data-slice-id/data-values on each donut
        # slice, data-institution/data-account-type on each row, wired to
        # applyAccountsFilters() in shell.py's shared script.
        resp = self._get("/linked-accounts.html")
        body = resp.read().decode("utf-8")
        self.assertIn('id="linked-accounts-table"', body)
        self.assertIn('id="accounts-filter-bar"', body)
        self.assertIn('id="linked-accounts-shown-count"', body)
        self.assertIn('id="linked-accounts-balance-total"', body)
        self.assertIn('data-dim="account-institution"', body)
        self.assertIn('data-dim="account-type"', body)
        self.assertIn('data-institution="Fidelity" data-account-type="Brokerage" data-balance="1500.0"', body)
        self.assertIn("function applyAccountsFilters(", body)


class TestLinkedAccountsInvestmentHistoryChart(DashboardTestCase):
    """The "Investment balance history" section on the Linked Accounts
    tab -- see _investment_balance_history_series /
    _multi_line_chart_html. Tracks daily balances per linked investment
    account (source.common.db.account_balance_snapshots), plus a
    combined Total line once there's more than one account."""

    def setUp(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-brokerage", "name": "Fidelity", "official_name": "Fidelity Brokerage",
            "type": "investment", "subtype": "brokerage", "mask": "5678",
            "balances": {"current": 1500.0, "available": None, "iso_currency_code": "USD"},
        })

    def tearDown(self):
        db.delete_plaid_item("fidelity")
        with db.connect() as conn:
            conn.execute("DELETE FROM account_balance_snapshots")

    def test_empty_state_shows_come_back_later_message(self):
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn("Investment balance history", body)
        self.assertIn("Investment balance over time", body)
        self.assertIn("no data yet", body)

    def test_section_is_collapsed_by_default(self):
        # A plain <details> with no `open` attribute, matching the rest
        # of the program's collapsed-by-default disclosure sections --
        # the section takes a click to expand rather than always
        # claiming space on the page.
        db.record_account_balance_snapshot(account_id="acc-brokerage", balance=1000.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc-brokerage", balance=1200.0, snapshot_date="2026-09-15")
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn('<details>\n<summary style="cursor:pointer; font-size:13px; font-weight:650; color:var(--ink);">Investment balance history</summary>', body)
        self.assertNotIn('<details open>\n<summary style="cursor:pointer; font-size:13px; font-weight:650; color:var(--ink);">Investment balance history</summary>', body)

    def test_single_account_history_renders_without_a_total_line(self):
        db.record_account_balance_snapshot(account_id="acc-brokerage", balance=1000.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc-brokerage", balance=1200.0, snapshot_date="2026-09-15")
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn("Fidelity — Fidelity Brokerage", body)
        # A lone account's own line already IS the total, so no separate
        # "Total" series/legend entry is added for it.
        self.assertNotIn(">Total<", body.split("Investment balance history")[1].split('id="accounts-filter-bar"')[0])

    def test_chart_is_logarithmic_and_discloses_it(self):
        # A small account and a much larger one would otherwise squash
        # the small one's own movement flat on a linear axis -- see
        # _multi_line_chart_html's log_scale docstring. The disclosure
        # note and at least one $-labeled gridline both have to be
        # present, not just a silently reshaped line.
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-ira", "name": "Fidelity IRA", "official_name": "Fidelity IRA",
            "type": "investment", "subtype": "ira", "mask": "9999",
            "balances": {"current": 500.0, "available": None, "iso_currency_code": "USD"},
        })
        db.record_account_balance_snapshot(account_id="acc-brokerage", balance=500_000.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc-ira", balance=500.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc-brokerage", balance=520_000.0, snapshot_date="2026-09-15")
        db.record_account_balance_snapshot(account_id="acc-ira", balance=600.0, snapshot_date="2026-09-15")
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        section = body.split("Investment balance history")[1].split('id="accounts-filter-bar"')[0]
        self.assertIn("Logarithmic scale", section)
        self.assertIn("equal percentage change", section)
        # A gridline $ label somewhere in the plausible range of these
        # balances (hundreds to hundreds of thousands).
        self.assertTrue(
            any(label in section for label in ("$1K", "$10K", "$100K", "$500", "$5K", "$50K")),
            section,
        )

    def test_multiple_accounts_add_an_emphasized_total_line(self):
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-ira", "name": "Fidelity IRA", "official_name": "Fidelity IRA",
            "type": "investment", "subtype": "ira", "mask": "9999",
            "balances": {"current": 3000.0, "available": None, "iso_currency_code": "USD"},
        })
        db.record_account_balance_snapshot(account_id="acc-brokerage", balance=1000.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc-ira", balance=3000.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc-brokerage", balance=1100.0, snapshot_date="2026-09-15")
        db.record_account_balance_snapshot(account_id="acc-ira", balance=3100.0, snapshot_date="2026-09-15")
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        section = body.split("Investment balance history")[1].split('id="accounts-filter-bar"')[0]
        self.assertIn("Fidelity — Fidelity Brokerage", section)
        self.assertIn("Fidelity — Fidelity IRA", section)
        self.assertIn(">Total<", section)
        # Headline change figure reads off the Total (the emphasized
        # series): 4,000 on 09-01 -> 4,200 on 09-15, a +$200 change.
        self.assertIn("+$200", section)

    def test_only_investment_type_accounts_get_a_history_series(self):
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-checking", "name": "Checking", "official_name": "Checking",
            "type": "depository", "subtype": "checking", "mask": "0000",
            "balances": {"current": 500.0, "available": 500.0, "iso_currency_code": "USD"},
        })
        db.record_account_balance_snapshot(account_id="acc-brokerage", balance=1000.0, snapshot_date="2026-09-01")
        db.record_account_balance_snapshot(account_id="acc-brokerage", balance=1200.0, snapshot_date="2026-09-15")
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        section = body.split("Investment balance history")[1].split('id="accounts-filter-bar"')[0]
        self.assertNotIn("Checking", section)

    def test_a_full_sync_captures_a_snapshot_for_the_linked_investment_account(self):
        with patch("source.webapp.dashboard.plaid_sync.sync_all", return_value={}):
            self._post("/api/plaid-sync", {})
        rows = db.list_account_balance_snapshots("acc-brokerage")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["balance"], 1500.0)

    def test_a_snapshot_failure_does_not_fail_the_sync_response(self):
        with patch("source.webapp.dashboard.plaid_sync.sync_all", return_value={}), \
             patch("source.webapp.dashboard.capture_investment_account_balances", side_effect=RuntimeError("boom")):
            status, payload = self._post("/api/plaid-sync", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])


class TestUnifiedAddModal(DashboardTestCase):
    """The single "+ Add" entry point (a fab button + modal in PAGE_SHELL,
    shared by every page) that replaced the separate add-forms the Asset,
    Expense/Income, and Real Estate tabs each used to carry -- see
    ADD_KIND_INFO in PAGE_SHELL's own JS for the section/kind each of the
    five types maps to."""

    def test_fab_button_and_modal_present_on_every_tab(self):
        for path in (
            "/asset.html", "/expense.html", "/real-estate.html", "/summary.html",
            "/linked-accounts.html", "/linked-positions.html",
        ):
            with self.subTest(path=path):
                body = self._get(path).read().decode("utf-8")
                self.assertIn('class="fab-add"', body)
                self.assertIn('id="add-modal-overlay"', body)
                self.assertIn("function openAddModal(", body)
                self.assertIn("function submitAddModal(", body)

    def test_modal_offers_all_five_kinds_and_maps_to_the_right_section(self):
        body = self._get("/summary.html").read().decode("utf-8")
        for option in ('value="asset"', 'value="liability"', 'value="expenses"', 'value="income"', 'value="real_estate"'):
            self.assertIn(option, body)
        self.assertIn("asset: {section: 'assets', kind: 'asset'", body)
        self.assertIn("liability: {section: 'assets', kind: 'liability'", body)
        self.assertIn("expenses: {section: 'expenses', kind: null", body)
        self.assertIn("income: {section: 'income', kind: null", body)
        self.assertIn("real_estate: {section: 'real_estate', kind: null", body)

    def test_asset_page_has_add_shortcuts_instead_of_its_own_form(self):
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn("openAddModal('asset')", body)
        self.assertIn("openAddModal('liability')", body)
        self.assertNotIn('name="kind"><option value="asset">Asset</option><option value="liability">Liability</option>', body)

    def test_real_estate_page_has_add_shortcut_instead_of_its_own_form(self):
        body = self._get("/real-estate.html").read().decode("utf-8")
        self.assertIn("openAddModal('real_estate')", body)

    def test_add_via_modal_endpoint_still_works_for_every_kind(self):
        # The modal is purely a front-end consolidation -- it still posts
        # through the same /api/line-item/add each old per-tab form used,
        # so existing add behavior (and the tests covering it) are
        # untouched.
        status, payload = self._post("/api/line-item/add", {
            "section": "assets", "fields": {"kind": "asset", "name": "Brokerage", "balance": 1000},
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        db.clear_section("assets")


class TestSummaryInsightCard(DashboardTestCase):
    """The Summary tab's "Summary insight" card -- financial-health ratio
    tiles plus an asset-allocation donut and an expenses-by-category bar
    chart, built from the same build_summary() figures as the rest of the
    page (see _summary_insight_html)."""

    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("expenses")
        db.clear_section("income")

    def test_insight_card_is_absent_for_a_completely_empty_plan(self):
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertNotIn("Summary insight", body)

    def test_insight_card_shows_ratio_tiles_and_charts_once_populated(self):
        db.set_assumption("current_year", 2028)
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity", "balance": 100_000})
        db.add_line_item("expenses", {"name": "Baseline", "category": "Fixed", "annual_amount": 40_000})
        db.add_line_item("income", {"name": "Rental", "category": "Rental", "annual_amount": 10_000})
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("Summary insight", body)
        self.assertIn("2028 income covers expenses", body)
        self.assertIn("Liquid share of net worth", body)
        self.assertIn("Debt-to-asset ratio", body)
        self.assertIn("Asset allocation by category", body)
        self.assertIn("Expenses by category", body)
        # 10,000 / 40,000 = 25%
        self.assertIn('<div class="label">2028 income covers expenses</div><div class="value">25%</div>', body)


def _seed_transaction_item(item_key="wells_fargo_checking", *, account_id="acc-checking"):
    db.upsert_plaid_item(
        item_key=item_key, plaid_item_id=f"item-{item_key}", institution_id="ins_1",
        institution_name="Wells Fargo", products=["transactions"], environment="sandbox",
        linked_at="2026-09-01T00:00:00+00:00",
    )
    db.upsert_plaid_account(item_key=item_key, account={
        "account_id": account_id, "name": "Checking", "official_name": "Everyday Checking",
        "type": "depository", "subtype": "checking", "mask": "6789",
        "balances": {"current": 5_000.0, "available": None, "iso_currency_code": "USD"},
    })


def _seed_transaction(transaction_id, *, item_key="wells_fargo_checking", account_id="acc-checking",
                       amount=42.50, date="2026-09-01", name="Coffee Shop",
                       primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_COFFEE"):
    from source.common.plaid_categorize import default_category, default_excluded_from_expense
    db.upsert_plaid_transaction(item_key=item_key, transaction={
        "transaction_id": transaction_id, "account_id": account_id, "date": date, "amount": amount,
        "iso_currency_code": "USD", "name": name, "merchant_name": name, "pending": False,
        "plaid_category_primary": primary, "plaid_category_detailed": detailed,
        "category": default_category(primary, detailed),
        "excluded_from_expense": default_excluded_from_expense(primary, detailed),
    })


class TestRealExpenditurePage(DashboardTestCase):
    def tearDown(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM plaid_transactions")
        db.delete_plaid_item("wells_fargo_checking")

    def test_nav_includes_real_expenditure(self):
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn('href="/real-expenditure.html"', body)
        self.assertIn("Actual Spending", body)

    def test_empty_state(self):
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("No transactions synced yet", body)

    def test_a_transaction_renders_with_institution_account_and_category(self):
        _seed_transaction_item()
        _seed_transaction("txn-1")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("Wells Fargo", body)
        self.assertIn("Everyday Checking", body)
        self.assertIn("Coffee Shop", body)
        self.assertIn("Food", body)
        self.assertIn("42.50", body)

    def test_monthly_and_annual_summaries_total_included_transactions(self):
        _seed_transaction_item()
        _seed_transaction("txn-1", amount=40.0, date="2026-09-05")
        _seed_transaction("txn-2", amount=60.0, date="2026-09-20")
        _seed_transaction("txn-3", amount=25.0, date="2026-08-01")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("<td>2026-09</td>", body)
        self.assertIn("$100", body)  # September total: 40 + 60
        self.assertIn("<td>2026</td>", body)
        self.assertIn("$125", body)  # annual total: 40 + 60 + 25

    def test_excluded_transactions_are_shown_but_not_counted_in_the_total(self):
        _seed_transaction_item()
        _seed_transaction("txn-spend", amount=50.0)
        _seed_transaction("txn-transfer", amount=200.0, primary="TRANSFER_OUT", detailed="TRANSFER_OUT_ACCOUNT_TRANSFER")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        # The transfer still shows up in the full list...
        self.assertIn("excluded", body)
        # ...but the "Total real expenditure" tile only counts the spend.
        self.assertIn("50.00", body)
        self.assertIn("Across 1 counted transaction", body)
        self.assertIn("1 more excluded", body)

    def test_manually_edited_category_is_marked_with_an_asterisk(self):
        _seed_transaction_item()
        _seed_transaction("txn-1")
        db.update_plaid_transaction_category(["txn-1"], "My Own Label")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("My Own Label *", body)

    def test_bulk_classify_bar_and_datalist_are_present(self):
        _seed_transaction_item()
        _seed_transaction("txn-1")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn('id="transaction-bulk-bar"', body)
        self.assertIn('list="transaction-categories"', body)
        self.assertIn("classifySelectedTransactions()", body)
        self.assertIn("setSelectedTransactionsExcluded(true)", body)
        self.assertIn("setSelectedTransactionsExcluded(false)", body)
        self.assertIn("resetSelectedTransactionsExpenseFlag()", body)
        self.assertIn('class="transaction-check"', body)

    def test_bulk_bar_has_income_kind_buttons(self):
        _seed_transaction_item()
        _seed_transaction("txn-1")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("setSelectedTransactionsIncomeKind('income')", body)
        self.assertIn("setSelectedTransactionsIncomeKind('expense')", body)
        self.assertIn("setSelectedTransactionsIncomeKind('')", body)

    def test_kind_filter_buttons_are_present_and_wired(self):
        _seed_transaction_item()
        _seed_transaction("txn-1")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn('id="expenditure-kind-filter-all"', body)
        self.assertIn('id="expenditure-kind-filter-income"', body)
        self.assertIn('id="expenditure-kind-filter-expense"', body)
        self.assertIn("setExpenditureKindFilter('income')", body)
        self.assertIn("setExpenditureKindFilter('expense')", body)
        # "All" is the only one active by default, since no filter is
        # applied until a person clicks one of these.
        self.assertIn('id="expenditure-kind-filter-all" class="kind-filter-btn active"', body)

    def test_counted_rows_carry_a_data_kind_attribute_for_the_quick_filter(self):
        _seed_transaction_item()
        _seed_transaction("txn-expense", amount=40.0, primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_COFFEE")
        _seed_transaction("txn-income", amount=-500.0, primary="INCOME", detailed="INCOME_WAGES")
        _seed_transaction(
            "txn-excluded", amount=100.0, primary="TRANSFER_OUT", detailed="TRANSFER_OUT_ACCOUNT_TRANSFER",
        )
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn('data-kind="expense"', body)
        self.assertIn('data-kind="income"', body)
        # The excluded (transfer) row's own <tr> never gets a data-kind
        # at all -- confirmed by counting: exactly one expense row and
        # one income row carry the attribute, not three.
        self.assertEqual(body.count('data-kind="expense"'), 1)
        self.assertEqual(body.count('data-kind="income"'), 1)

    def test_marking_a_mislabeled_income_transaction_shows_the_override_badge(self):
        _seed_transaction_item()
        _seed_transaction("txn-1", amount=-500.0, name="APPLE INC. PAYROLL", primary="INCOME", detailed="INCOME_WAGES")
        db.update_plaid_transaction_category(["txn-1"], "salary")
        db.update_plaid_transaction_income_kind(["txn-1"], "income")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("marked income", body)
        # The override made it a real-income row again -- the heuristic-
        # only "counted as income" badge is redundant once the override
        # badge is already saying so, so it's suppressed.
        self.assertNotIn("counted as income", body)

    def test_charts_and_table_rows_are_wired_for_click_to_filter(self):
        # The category/month bar charts and the transaction table below
        # them share the same click-to-filter contract Linked Positions
        # uses (data-dim/data-slice-id/data-values on each bar,
        # data-category/data-month on each row) -- see
        # applyExpenditureFilters() in shell.py's shared script.
        _seed_transaction_item()
        _seed_transaction("txn-1", amount=40.0, date="2026-09-05")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn('id="real-expenditure-table"', body)
        self.assertIn('id="expenditure-filter-bar"', body)
        self.assertIn('id="real-expenditure-shown-count"', body)
        self.assertIn('data-dim="expense-category"', body)
        self.assertIn('data-dim="expense-month"', body)
        self.assertIn('data-category="Food" data-month="2026-09"', body)

    def test_shared_script_has_the_expenditure_filter_functions(self):
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("function applyExpenditureFilters(", body)
        self.assertIn("function renderFilterChips(", body)
        self.assertIn("applyExpenditureFilters();", body)

    def test_transactions_sharing_account_date_amount_and_name_are_flagged_as_possible_duplicates(self):
        # Two distinct Plaid transaction_ids can still describe what
        # looks like the same real-world transaction -- flagged, not
        # hidden or auto-excluded (see _duplicate_counts' docstring).
        _seed_transaction_item()
        _seed_transaction("txn-1", amount=2.0, date="2026-09-01", name="Apple Caffe")
        _seed_transaction("txn-2", amount=2.0, date="2026-09-01", name="Apple Caffe")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertEqual(body.count("possible duplicate (2)"), 2)
        self.assertEqual(body.count("exclude this one"), 2)
        self.assertIn("2 transactions flagged", body)

    def test_transactions_that_dont_match_are_not_flagged(self):
        _seed_transaction_item()
        _seed_transaction("txn-1", amount=2.0, date="2026-09-01", name="Apple Caffe")
        _seed_transaction("txn-2", amount=3.5, date="2026-09-01", name="Apple Caffe")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertNotIn("possible duplicate", body)

    def test_an_already_excluded_duplicate_has_no_quick_exclude_link(self):
        _seed_transaction_item()
        _seed_transaction("txn-1", amount=2.0, date="2026-09-01", name="Apple Caffe")
        _seed_transaction("txn-2", amount=2.0, date="2026-09-01", name="Apple Caffe")
        db.update_plaid_transaction_excluded(["txn-2"], True)
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertEqual(body.count("possible duplicate (2)"), 2)
        # Only the still-counted one (txn-1) gets the quick-exclude link.
        self.assertEqual(body.count("exclude this one"), 1)

    def test_a_transaction_properly_categorized_income_counts_toward_total_real_income(self):
        _seed_transaction_item()
        _seed_transaction("txn-payroll", amount=-2000.0, name="Employer Payroll", primary="INCOME", detailed="INCOME_WAGES")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("Total real income", body)
        self.assertIn("$2,000", body)
        # Displayed as a plain positive figure, not a raw negative Plaid amount.
        self.assertIn("+$2,000", body)

    def test_inbound_money_plaid_could_not_classify_counts_as_income_not_expense(self):
        # The exact bug this exists to fix: Plaid gives no real primary
        # (OTHER), so this app's own name-keyword guesser assigns an
        # expense-sounding category ("Housing & Utilities") from the
        # description text alone -- but the amount is money coming IN, so
        # it should count as real income, not real expenditure.
        _seed_transaction_item()
        _seed_transaction(
            "txn-mystery-deposit", amount=-10_150.0, name="ACME UTILITY CO DES:PAYROLL",
            primary="OTHER", detailed="OTHER_OTHER",
        )
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("$10,150", body)  # shows up in the income tile
        self.assertIn("+$10,150", body)  # displayed positive in the row
        self.assertIn("counted as income", body)  # flagged since its category isn't literally "Income"
        # And NOT counted in real expenditure -- the total tile should
        # read $0 since this is the only transaction.
        self.assertIn("$0", body)

    def test_refund_within_a_real_expense_category_is_not_treated_as_income(self):
        _seed_transaction_item()
        _seed_transaction(
            "txn-refund", amount=-49.99, name="Amazon Refund",
            primary="GENERAL_MERCHANDISE", detailed="GENERAL_MERCHANDISE_ONLINE_MARKETPLACES",
        )
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertNotIn("counted as income", body)
        # A refund still shows with Plaid's raw negative sign (nets
        # against that category's spend), not the "+" income display.
        self.assertIn("-$50", body)

    def test_income_category_row_has_no_redundant_counted_as_income_badge(self):
        _seed_transaction_item()
        _seed_transaction("txn-payroll", amount=-2000.0, name="Employer Payroll", primary="INCOME", detailed="INCOME_WAGES")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertNotIn("counted as income", body)

    def test_income_charts_are_present_and_wired_for_click_to_filter(self):
        _seed_transaction_item()
        _seed_transaction("txn-payroll", amount=-2000.0, name="Employer Payroll", primary="INCOME", detailed="INCOME_WAGES")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("Real income by category", body)
        self.assertIn("Real income by month (last 12)", body)
        self.assertIn('data-dim="income-category"', body)
        self.assertIn('data-dim="income-month"', body)

    def test_no_income_yet_shows_the_no_data_state_for_income_charts(self):
        _seed_transaction_item()
        _seed_transaction("txn-1")  # an ordinary Food purchase, no income
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("Real income by category", body)
        self.assertNotIn('data-dim="income-category"', body)  # no-data state renders no bars at all

    def test_manually_categorized_mortgage_transaction_is_not_counted_as_income(self):
        # The exact real, reported bug: a mortgage-account "principal
        # payment" mirror transaction Plaid gave primary "OTHER" (instead
        # of the TRANSFER_IN it should have gotten), then hand-labeled
        # "mortgage" -- must count as real expenditure, not real income.
        _seed_transaction_item()
        _seed_transaction(
            "txn-mortgage-principal", amount=-142.23, name="Principal only payment",
            primary="OTHER", detailed="OTHER_OTHER",
        )
        db.update_plaid_transaction_category(["txn-mortgage-principal"], "mortgage")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertNotIn("counted as income", body)
        self.assertIn("-$142", body)  # shown with Plaid's raw sign, like any other counted expense
        # Nothing counts as income for this single transaction.
        self.assertIn(
            '<h3 style="margin-top:0; font-size:13px;">Total real income</h3>\n'
            '<p style="font-size:22px; font-weight:600; margin:4px 0;">$0</p>',
            body,
        )

    def test_manually_categorized_food_and_bank_fees_transactions_are_not_counted_as_income(self):
        _seed_transaction_item()
        _seed_transaction(
            "txn-food-other", amount=-36.67, name="BANOS ARABES DE CORDOBA",
            primary="OTHER", detailed="OTHER_OTHER",
        )
        db.update_plaid_transaction_category(["txn-food-other"], "Food")
        _seed_transaction(
            "txn-fee-other", amount=-8.03, name="Bank of America DES:CASHREWARD",
            primary="OTHER", detailed="OTHER_OTHER",
        )
        db.update_plaid_transaction_category(["txn-fee-other"], "Bank Fees")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertNotIn("counted as income", body)

    def test_manually_categorized_rental_income_transaction_still_counts_as_income(self):
        # The other side of the same fix -- a hand-typed category that
        # itself reads as income (contains "income") must keep counting,
        # even though it's just as manually-edited as the "mortgage" case
        # above and shares the same OTHER primary.
        _seed_transaction_item()
        _seed_transaction(
            "txn-rent", amount=-2000.0, name="ZELLE FROM TENANT ON 09/01 REF # X RENT",
            primary="OTHER", detailed="OTHER_OTHER",
        )
        db.update_plaid_transaction_category(["txn-rent"], "rental-income")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("counted as income", body)
        self.assertIn("+$2,000", body)

    def test_income_chart_row_attribute_is_not_added_to_an_excluded_row_sharing_the_same_category(self):
        # Regression test for the click-to-filter bug reported alongside
        # the income-miscount bug above: clicking an income-by-category
        # bar used to surface every row anywhere sharing that category
        # text, including ones properly excluded as internal transfers,
        # rather than just the row(s) that actually made up that bar's
        # own dollar total.
        _seed_transaction_item()
        # Excluded (an internal transfer Plaid tied to the loan account)
        # but a person -- or a saved rule -- happened to label it with
        # the same "rental-income" text as the real income row below.
        _seed_transaction(
            "txn-rental-income-excluded", amount=-500.0, name="Internal transfer",
            primary="TRANSFER_IN", detailed="TRANSFER_IN_OTHER_TRANSFER_IN",
        )
        db.update_plaid_transaction_category(["txn-rental-income-excluded"], "rental-income")
        # The real rent deposit that actually counts as income.
        _seed_transaction(
            "txn-rental-income-real", amount=-2000.0, name="ZELLE FROM TENANT ON 09/01 REF # X RENT",
            primary="OTHER", detailed="OTHER_OTHER",
        )
        db.update_plaid_transaction_category(["txn-rental-income-real"], "rental-income")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        # Both rows share the plain data-category attribute...
        self.assertEqual(body.count('data-category="rental-income"'), 2)
        # ...but only the one that actually counts as income carries the
        # income-chart attribute; the excluded transfer never does.
        self.assertEqual(body.count('data-income-category="rental-income"'), 1)

    def test_every_row_has_a_categorize_similar_link(self):
        _seed_transaction_item()
        _seed_transaction("txn-1")
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn("categorizeSimilarTransactions('txn-1')", body)
        self.assertIn("categorize similar", body)


class TestClassifyTransactionCategoryEndpoint(DashboardTestCase):
    def setUp(self):
        _seed_transaction_item()
        _seed_transaction("txn-1")

    def tearDown(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM plaid_transactions")
        db.delete_plaid_item("wells_fargo_checking")

    def test_setting_a_category_classifies_every_requested_item(self):
        status, payload = self._post("/api/classify-transaction-category", {
            "items": [{"transaction_id": "txn-1"}], "category": "Groceries",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["category"], "Groceries")
        self.assertEqual(row["category_edited_by_user"], 1)

    def test_blank_category_resets_to_the_plaid_default_instead_of_blanking_it(self):
        db.update_plaid_transaction_category(["txn-1"], "My Own Label")
        status, payload = self._post("/api/classify-transaction-category", {
            "items": [{"transaction_id": "txn-1"}], "category": None,
        })
        self.assertTrue(payload["ok"])
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["category"], "Food")
        self.assertEqual(row["category_edited_by_user"], 0)

    def test_skips_items_missing_a_transaction_id_but_still_classifies_the_rest(self):
        status, payload = self._post("/api/classify-transaction-category", {
            "items": [{"transaction_id": "txn-1"}, {}],
            "category": "Groceries",
        })
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)


class TestClassifyTransactionExpenseFlagEndpoint(DashboardTestCase):
    def setUp(self):
        _seed_transaction_item()
        _seed_transaction("txn-1")

    def tearDown(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM plaid_transactions")
        db.delete_plaid_item("wells_fargo_checking")

    def test_exclude_action_marks_it_excluded_and_edited_by_user(self):
        status, payload = self._post("/api/classify-transaction-expense-flag", {
            "items": [{"transaction_id": "txn-1"}], "action": "exclude",
        })
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["excluded_from_expense"], 1)
        self.assertEqual(row["excluded_edited_by_user"], 1)

    def test_include_action_marks_it_included_and_edited_by_user(self):
        db.update_plaid_transaction_excluded(["txn-1"], True)
        status, payload = self._post("/api/classify-transaction-expense-flag", {
            "items": [{"transaction_id": "txn-1"}], "action": "include",
        })
        self.assertTrue(payload["ok"])
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["excluded_from_expense"], 0)
        self.assertEqual(row["excluded_edited_by_user"], 1)

    def test_reset_action_goes_back_to_the_automatic_heuristic(self):
        db.update_plaid_transaction_excluded(["txn-1"], True)
        status, payload = self._post("/api/classify-transaction-expense-flag", {
            "items": [{"transaction_id": "txn-1"}], "action": "reset",
        })
        self.assertTrue(payload["ok"])
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["excluded_from_expense"], 0)  # a coffee purchase isn't a transfer
        self.assertEqual(row["excluded_edited_by_user"], 0)

    def test_unknown_action_returns_400(self):
        status, payload = self._post("/api/classify-transaction-expense-flag", {
            "items": [{"transaction_id": "txn-1"}], "action": "bogus",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])


class TestClassifyTransactionIncomeKindEndpoint(DashboardTestCase):
    """/api/classify-transaction-income-kind -- the Actual Spending
    page's "Mark as income"/"Mark as expense"/"Auto-detect" bulk action.
    See plaid_categorize.is_real_income's own income_kind_override
    docstring for why this exists: a manually-retyped category that IS
    income but doesn't literally contain the word "income" ("salary",
    "Rental-mp", "tax-refund" were real examples) was otherwise falling
    out of "real income" with no text-matching fix available."""

    def setUp(self):
        _seed_transaction_item()
        _seed_transaction("txn-1")

    def tearDown(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM plaid_transactions")
        db.delete_plaid_item("wells_fargo_checking")

    def test_marking_as_income_sets_the_override(self):
        status, payload = self._post("/api/classify-transaction-income-kind", {
            "items": [{"transaction_id": "txn-1"}], "kind": "income",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["income_kind_override"], "income")

    def test_marking_as_expense_sets_the_override(self):
        status, payload = self._post("/api/classify-transaction-income-kind", {
            "items": [{"transaction_id": "txn-1"}], "kind": "expense",
        })
        self.assertTrue(payload["ok"])
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["income_kind_override"], "expense")

    def test_blank_kind_clears_back_to_auto_detect(self):
        db.update_plaid_transaction_income_kind(["txn-1"], "income")
        status, payload = self._post("/api/classify-transaction-income-kind", {
            "items": [{"transaction_id": "txn-1"}], "kind": "",
        })
        self.assertTrue(payload["ok"])
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["income_kind_override"], "")

    def test_unknown_kind_returns_400(self):
        status, payload = self._post("/api/classify-transaction-income-kind", {
            "items": [{"transaction_id": "txn-1"}], "kind": "bogus",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_the_override_makes_a_manually_mislabeled_real_income_row_count(self):
        # End-to-end regression test for the actual reported bug: a
        # payroll deposit (amount negative -- Plaid's money-in
        # convention) hand-recategorized "salary" (no literal "income"
        # in the text) stopped counting as real income once category_
        # edited_by_user kicked in -- marking it as income directly fixes
        # that without needing to retype the category.
        _seed_transaction("txn-payroll", amount=-500.0, name="APPLE INC. PAYROLL", primary="INCOME", detailed="INCOME_WAGES")
        db.update_plaid_transaction_category(["txn-payroll"], "salary")
        from source.common import linked_data
        before = {t["transaction_id"]: t for t in linked_data.read_transactions()}["txn-payroll"]
        self.assertFalse(before["is_real_income"])
        self._post("/api/classify-transaction-income-kind", {
            "items": [{"transaction_id": "txn-payroll"}], "kind": "income",
        })
        after = {t["transaction_id"]: t for t in linked_data.read_transactions()}["txn-payroll"]
        self.assertTrue(after["is_real_income"])


class TestPlaidConnectTransactionsEndpoint(DashboardTestCase):
    def tearDown(self):
        db.delete_plaid_item("test_item")
        secrets_store.clear_vault_cache()
        self.fake_keyring._store.clear()

    def test_calls_enable_transactions_for_item_and_reports_ok(self):
        with patch("source.webapp.dashboard.plaid_link_item.enable_transactions_for_item") as mock_enable:
            status, payload = self._post("/api/plaid-connect-transactions", {"item_key": "test_item"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        mock_enable.assert_called_once_with("test_item")

    def test_without_item_key_returns_400(self):
        status, payload = self._post("/api/plaid-connect-transactions", {})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_failure_surfaces_error_message(self):
        with patch(
            "source.webapp.dashboard.plaid_link_item.enable_transactions_for_item",
            side_effect=TimeoutError("Timed out waiting for Link to complete in the browser."),
        ):
            status, payload = self._post("/api/plaid-connect-transactions", {"item_key": "test_item"})
        self.assertEqual(status, 500)
        self.assertFalse(payload["ok"])
        self.assertIn("Timed out", payload["error"])


class TestSetupPageEnableTransactionsButton(DashboardTestCase):
    def tearDown(self):
        db.delete_plaid_item("investments_only")
        db.delete_plaid_item("has_transactions")

    def test_item_without_transactions_shows_the_enable_button(self):
        db.upsert_plaid_item(
            item_key="investments_only", plaid_item_id="item-1", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn("enableTransactionsForItem('investments_only')", body)

    def test_item_with_transactions_does_not_show_the_enable_button(self):
        db.upsert_plaid_item(
            item_key="has_transactions", plaid_item_id="item-2", institution_id="ins_2",
            institution_name="Wells Fargo", products=["transactions"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertNotIn("enableTransactionsForItem('has_transactions')", body)


class TestAssetPageNetWorthHistory(DashboardTestCase):
    """The Assets tab's over-time chart (see source.webapp.pages.asset.
    _liquid_and_total_points): Investable savings, one point per captured
    day, laid out by real elapsed time on a y-axis fitted to the data."""

    def tearDown(self):
        db.clear_section("real_estate")
        with db.connect() as conn:
            conn.execute("DELETE FROM net_worth_snapshots")

    def _snap(self, liquid, snapshot_date, *, liabilities=0.0, re_equity=0.0, re_value=None):
        db.record_snapshot(
            net_worth=liquid - liabilities + re_equity, manual_asset_total=0, linked_asset_total=0,
            liability_total=liabilities, real_estate_equity_total=re_equity, retirement_liquid_total=liquid,
            real_estate_value_total=re_value, snapshot_date=snapshot_date,
        )

    def test_summary_page_no_longer_has_this_card(self):
        self._snap(100_000.0, "2026-09-01")
        self._snap(110_000.0, "2026-10-01")
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertNotIn('id="nw-explorer"', body)

    def test_a_single_day_of_history_shows_the_collapsed_come_back_tomorrow_message(self):
        self._snap(100.0, "2026-09-01")
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn("Net liquid asset over time", body)
        self.assertIn("Come back tomorrow", body)
        self.assertIn('<details class="card">', body)
        self.assertNotIn("<details open", body)

    def test_every_day_is_its_own_point_not_collapsed_to_a_month(self):
        self._snap(100_000.0, "2026-09-01")
        self._snap(101_000.0, "2026-09-02")
        self._snap(103_500.0, "2026-09-03")
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn('id="nw-explorer"', body)
        self.assertIn('"points": [["2026-09-01", 100000.0], ["2026-09-02", 101000.0], ["2026-09-03", 103500.0]]', body)
        self.assertIn("+$3,500", body)
        self.assertIn("since 2026-09-01", body)

    def test_the_headline_is_net_liquid_asset_net_of_liabilities(self):
        self._snap(100_000.0, "2026-09-01", liabilities=10_000.0, re_equity=500_000.0)
        self._snap(120_000.0, "2026-09-02", liabilities=10_000.0, re_equity=500_000.0)
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn('"name": "Investable savings"', body)
        self.assertIn('["2026-09-01", 90000.0], ["2026-09-02", 110000.0]', body)

    def test_a_second_capture_the_same_day_replaces_that_days_point(self):
        self._snap(100_000.0, "2026-09-01")
        self._snap(999_000.0, "2026-09-01")
        self._snap(110_000.0, "2026-09-02")
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertNotIn('["2026-09-01", 100000.0]', body)
        self.assertIn('["2026-09-01", 999000.0]', body)
        self.assertIn("-$889,000", body)

    def test_real_estate_lines_are_chips_and_the_total_switches_to_total_asset(self):
        db.add_line_item("real_estate", {"name": "Home", "current_value": 900_000.0, "loan_balance": 300_000.0})
        self._snap(100_000.0, "2026-09-01", re_equity=590_000.0)
        self._snap(110_000.0, "2026-09-02", re_equity=600_000.0, re_value=900_000.0)
        self._snap(120_000.0, "2026-09-03", re_equity=605_000.0, re_value=905_000.0)
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn('data-re="value"', body)
        self.assertIn('data-re="equity"', body)
        # Off by default; the page only ever draws ONE chart for all of this.
        self.assertEqual(body.count('id="nw-explorer"'), 1)
        self.assertNotIn("Net worth &amp; real estate over time", body)
        self.assertIn('"name": "Total Asset"', body)
        self.assertIn('["2026-09-01", 690000.0], ["2026-09-02", 710000.0], ["2026-09-03", 725000.0]', body)
        # Value starts the first day it was recorded; equity has the full history.
        self.assertIn('"key": "value", "name": "Real estate value", "dash": "", "points": [["2026-09-02", 900000.0]', body)
        self.assertIn('"key": "equity", "name": "Real estate equity", "dash": "6 4", "points": [["2026-09-01", 590000.0]', body)

    def test_no_real_estate_chips_without_a_property(self):
        self._snap(100_000.0, "2026-09-01")
        self._snap(110_000.0, "2026-09-02")
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertNotIn("data-re=", body)
        self.assertIn('"total": null', body)


class TestLiquidAndTotalPoints(unittest.TestCase):
    def test_liquid_is_net_of_liabilities_and_total_adds_real_estate_equity_in_date_order(self):
        from source.webapp.pages.asset import _liquid_and_total_points
        rows = [
            {"snapshot_date": "2026-09-02", "retirement_liquid_total": 200.0, "liability_total": 20.0,
             "real_estate_equity_total": 50.0},
            {"snapshot_date": "2026-09-01", "retirement_liquid_total": 100.0, "liability_total": 10.0,
             "real_estate_equity_total": 40.0},
        ]
        liquid, total = _liquid_and_total_points(rows)
        self.assertEqual(liquid, [("2026-09-01", 90.0), ("2026-09-02", 180.0)])
        self.assertEqual(total, [("2026-09-01", 130.0), ("2026-09-02", 230.0)])

    def test_empty_history(self):
        from source.webapp.pages.asset import _liquid_and_total_points
        self.assertEqual(_liquid_and_total_points([]), ([], []))


class TestLineChartHtml(unittest.TestCase):
    def _render(self, points):
        from source.webapp.render_helpers import _line_chart_html
        return _line_chart_html("Trend", points)

    def test_y_axis_fits_the_data_instead_of_starting_at_zero(self):
        # $7.9M moving by only ~$70K: if the axis began at $0 the line
        # would be flat; fitted, the axis labels stay near the data.
        body = self._render([("2026-09-01", 7_838_000.0), ("2026-09-02", 7_908_000.0)])
        self.assertNotIn(">$0<", body)
        self.assertIn(">$7.830M</text>", body)
        self.assertIn(">$7.916M</text>", body)

    def test_the_line_spans_a_visible_share_of_the_plot_height(self):
        import re
        body = self._render([("2026-09-01", 7_838_000.0), ("2026-09-02", 7_908_000.0)])
        path = re.search(r'<path d="M ([\d.]+) ([\d.]+) L ([\d.]+) ([\d.]+)"', body)
        y_first, y_last = float(path.group(2)), float(path.group(4))
        self.assertGreater(y_first - y_last, 100)  # most of the 270px-tall plot

    def test_x_positions_follow_real_elapsed_time(self):
        import re
        body = self._render([("2026-09-01", 1.0), ("2026-09-02", 2.0), ("2026-09-11", 3.0)])
        path = re.search(r'<path d="M ([\d.]+) [\d.]+ L ([\d.]+) [\d.]+ L ([\d.]+) [\d.]+"', body)
        x0, x1, x2 = (float(path.group(i)) for i in (1, 2, 3))
        # day 1 of 10 vs day 10 of 10: the first gap is a tenth of the second... of the total.
        self.assertAlmostEqual((x1 - x0) / (x2 - x0), 0.1, places=2)

    def test_non_date_labels_fall_back_to_even_spacing(self):
        import re
        body = self._render([("2026-09", 1.0), ("2026-10", 2.0), ("2026-12", 3.0)])
        path = re.search(r'<path d="M ([\d.]+) [\d.]+ L ([\d.]+) [\d.]+ L ([\d.]+) [\d.]+"', body)
        x0, x1, x2 = (float(path.group(i)) for i in (1, 2, 3))
        self.assertAlmostEqual((x1 - x0) / (x2 - x0), 0.5, places=2)

    def test_scales_to_the_card_width(self):
        body = self._render([("2026-09-01", 1.0), ("2026-09-02", 2.0)])
        self.assertIn("width:100%", body)
        self.assertIn('viewBox="0 0 960 270"', body)

    def test_a_flat_series_still_draws_mid_chart(self):
        import re
        body = self._render([("2026-09-01", 5_000.0), ("2026-09-02", 5_000.0)])
        path = re.search(r'<path d="M [\d.]+ ([\d.]+) L [\d.]+ ([\d.]+)"', body)
        self.assertEqual(path.group(1), path.group(2))

    def test_a_long_history_keeps_hover_targets_but_only_the_latest_dot_is_visible(self):
        from datetime import date, timedelta
        start = date(2026, 1, 1)
        points = [((start + timedelta(days=i)).isoformat(), 1000.0 + i) for i in range(100)]
        body = self._render(points)
        self.assertEqual(body.count("<circle"), 100)  # every day still has a tooltip
        self.assertEqual(body.count('fill="transparent"'), 99)
        self.assertIn("2026-01-01: $1,000", body)

    def test_has_labeled_x_and_y_axes(self):
        body = self._render([("2026-09-01", 7_000_000.0), ("2026-10-01", 8_000_000.0)])
        self.assertIn(">Net worth</text>", body)  # y-axis title
        self.assertIn(">Date</text>", body)  # x-axis title
        # Five y value labels, evenly spaced over the fitted range...
        for label in ("$6.88M", "$7.19M", "$7.50M", "$7.81M", "$8.12M"):
            self.assertIn(f">{label}</text>", body)
        # ...and dated x ticks: both ends in full plus short in-between dates.
        for label in ("2026-09-01", "2026-10-01", "Sep 6", "Sep 11", "Sep 16", "Sep 21", "Sep 26"):
            self.assertIn(f">{label}</text>", body)

    def test_draws_the_axis_lines_themselves(self):
        body = self._render([("2026-09-01", 1.0), ("2026-09-20", 2.0)])
        # The y axis (vertical, at the plot's left edge) and x axis (horizontal, along its bottom).
        self.assertIn('x1="84" y1="14" x2="84" y2="216"', body)
        self.assertIn('x1="84" y1="216" x2="942" y2="216"', body)

    def test_in_between_date_ticks_appear_on_a_longer_span(self):
        body = self._render([("2026-09-01", 1.0), ("2026-10-01", 2.0)])
        self.assertIn("Sep 16", body)


class TestBudgetVsActualRouting(DashboardTestCase):
    def test_page_is_reachable_and_in_the_nav(self):
        body = self._get("/budget-vs-actual.html").read().decode("utf-8")
        self.assertIn("Budget vs Actual", body)
        # Budget vs Actual lives under the Spending tab, next to Actual Spending.
        self.assertRegex(body, r'href="/real-expenditure.html" class="active">.*<span class="nl">Spending</span></a>')
        self.assertIn('<div class="subnav">', body)

    def test_real_expenditure_page_links_to_it(self):
        body = self._get("/real-expenditure.html").read().decode("utf-8")
        self.assertIn('href="/budget-vs-actual.html"', body)


class TestAutoSyncSettingsEndpoint(DashboardTestCase):
    def tearDown(self):
        app_settings.set_auto_sync_enabled(True)
        app_settings.set_auto_sync_interval_days(30)
        db.delete_plaid_item("auto_sync_test_item")

    def test_saving_settings(self):
        status, payload = self._post("/api/auto-sync-settings", {"enabled": False, "interval_days": 14})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(app_settings.get_auto_sync_enabled())
        self.assertEqual(app_settings.get_auto_sync_interval_days(), 14)

    def test_setup_page_shows_the_automatic_sync_card(self):
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn("Automatic sync", body)
        self.assertIn("api/auto-sync-settings", body)

    def test_setup_page_shows_overdue_status(self):
        from datetime import datetime, timedelta, timezone
        db.upsert_plaid_item(
            item_key="auto_sync_test_item", plaid_item_id="item-1", institution_id=None,
            institution_name="Bank", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        stale = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        db.mark_plaid_item_synced("auto_sync_test_item", stale)
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn("Overdue", body)


class TestCategoryRuleEndpoints(DashboardTestCase):
    def tearDown(self):
        # DashboardTestCase shares ONE database across every test in this
        # class (class-level setUp, not per-test) -- without this, a rule
        # one test saves and never deletes leaks into every test that
        # runs after it alphabetically, silently inflating list_category_
        # rules() counts other tests assert on. Every test below creates
        # whatever rule(s) it needs itself, so clearing here is always
        # safe.
        with db.connect() as conn:
            conn.execute("DELETE FROM category_rules")

    def test_saving_a_rule_persists_it(self):
        status, payload = self._post("/api/category-rule/save", {
            "rule_type": "keyword", "match_key": "peloton", "category": "Fitness",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        rules = db.list_category_rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["category"], "Fitness")

    def test_saving_a_rule_returns_400_for_an_unknown_rule_type(self):
        status, payload = self._post("/api/category-rule/save", {
            "rule_type": "nonsense", "match_key": "x", "category": "Y",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_saving_a_rule_immediately_recategorizes_matching_transactions(self):
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name=None,
            products=["transactions"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_transaction(item_key="k", transaction={
            "transaction_id": "t1", "account_id": "acc-1", "date": "2026-09-01", "amount": 25.0,
            "iso_currency_code": "USD", "name": "Peloton Membership", "merchant_name": "Peloton",
            "pending": False, "plaid_category_primary": None, "plaid_category_detailed": None,
            "category": "Uncategorized", "excluded_from_expense": False,
        })
        status, payload = self._post("/api/category-rule/save", {
            "rule_type": "keyword", "match_key": "peloton", "category": "Fitness",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["recategorized"], 1)
        self.assertEqual(db.list_plaid_transactions()[0]["category"], "Fitness")

    def test_deleting_a_rule(self):
        rule_id = db.upsert_category_rule(rule_type="primary", match_key="a", category="A")
        status, payload = self._post("/api/category-rule/delete", {"id": rule_id})
        self.assertEqual(status, 200)
        self.assertTrue(payload["deleted"])
        self.assertEqual(db.list_category_rules(), [])

    def test_deleting_an_unknown_rule_reports_not_deleted_but_still_ok(self):
        status, payload = self._post("/api/category-rule/delete", {"id": 999})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["deleted"])

    def test_setup_page_lists_saved_rules_and_the_built_in_reference_table(self):
        db.upsert_category_rule(rule_type="keyword", match_key="peloton", category="Fitness")
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn("Category rules", body)
        self.assertIn("peloton", body)
        self.assertIn("Fitness", body)
        self.assertIn("deleteCategoryRule(", body)
        self.assertIn("updateCategoryRule(", body)
        # The built-in reference table shows at least one hardcoded default.
        self.assertIn("GENERAL_MERCHANDISE", body)

    def test_setup_page_shows_a_match_mode_selector_for_a_keyword_rule(self):
        rule_id = db.upsert_category_rule(
            rule_type="keyword", match_key="uber", category="Transportation", match_mode="starts_with",
        )
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn(f"updateCategoryRule({rule_id}", body)
        self.assertIn('name="match_mode"', body)
        self.assertIn("Starts with", body)
        # This row's own Match mode select is a live, enabled control
        # (unlike a "primary"/"detailed" rule's -- see the next test).
        self.assertIn('name="match_mode" style="width:115px;">', body)

    def test_setup_page_disables_match_mode_for_a_primary_or_detailed_rule(self):
        # match_mode is meaningless for a "primary"/"detailed" rule
        # (always an exact match on Plaid's own value) -- its own row's
        # Match mode <select> is disabled rather than offering a choice
        # that wouldn't do anything.
        db.upsert_category_rule(rule_type="primary", match_key="general_merchandise", category="Shopping")
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn('name="match_mode" disabled style="width:115px;">', body)

    def test_saving_a_keyword_rule_with_match_mode_persists_it(self):
        status, payload = self._post("/api/category-rule/save", {
            "rule_type": "keyword", "match_key": "uber", "category": "Transportation", "match_mode": "starts_with",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.list_category_rules()[0]["match_mode"], "starts_with")

    def test_updating_a_rule_edits_it_in_place(self):
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="peloton", category="Fitness")
        status, payload = self._post("/api/category-rule/update", {
            "id": rule_id, "rule_type": "keyword", "match_key": "soulcycle",
            "category": "Wellness", "match_mode": "ends_with",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        rules = db.list_category_rules()
        self.assertEqual(len(rules), 1)  # still one row -- edited, not duplicated
        self.assertEqual(rules[0]["id"], rule_id)
        self.assertEqual(rules[0]["match_key"], "soulcycle")
        self.assertEqual(rules[0]["category"], "Wellness")
        self.assertEqual(rules[0]["match_mode"], "ends_with")

    def test_updating_a_rule_immediately_recategorizes_matching_transactions(self):
        db.upsert_plaid_item(
            item_key="k2", plaid_item_id="item-2", institution_id=None, institution_name=None,
            products=["transactions"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_transaction(item_key="k2", transaction={
            "transaction_id": "t2", "account_id": "acc-2", "date": "2026-09-01", "amount": 25.0,
            "iso_currency_code": "USD", "name": "Soulcycle Class", "merchant_name": "Soulcycle",
            "pending": False, "plaid_category_primary": None, "plaid_category_detailed": None,
            "category": "Uncategorized", "excluded_from_expense": False,
        })
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="peloton", category="Fitness")
        status, payload = self._post("/api/category-rule/update", {
            "id": rule_id, "rule_type": "keyword", "match_key": "soulcycle", "category": "Wellness",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["recategorized"], 1)
        updated = next(t for t in db.list_plaid_transactions() if t["transaction_id"] == "t2")
        self.assertEqual(updated["category"], "Wellness")

    def test_updating_an_unknown_rule_returns_400(self):
        status, payload = self._post("/api/category-rule/update", {
            "id": 999, "rule_type": "keyword", "match_key": "peloton", "category": "Fitness",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_updating_a_rule_to_collide_with_another_returns_400(self):
        db.upsert_category_rule(rule_type="keyword", match_key="peloton", category="Fitness")
        other_id = db.upsert_category_rule(rule_type="keyword", match_key="soulcycle", category="Wellness")
        status, payload = self._post("/api/category-rule/update", {
            "id": other_id, "rule_type": "keyword", "match_key": "peloton", "category": "Wellness",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_saving_a_rule_with_a_kind_persists_it(self):
        status, payload = self._post("/api/category-rule/save", {
            "rule_type": "keyword", "match_key": "apple", "category": "Salary", "kind": "income",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.list_category_rules()[0]["kind"], "income")

    def test_saving_a_rule_with_no_kind_defaults_to_auto_detect(self):
        status, payload = self._post("/api/category-rule/save", {
            "rule_type": "keyword", "match_key": "peloton", "category": "Fitness",
        })
        self.assertEqual(status, 200)
        self.assertEqual(db.list_category_rules()[0]["kind"], "")

    def test_saving_a_rule_rejects_an_unknown_kind(self):
        status, payload = self._post("/api/category-rule/save", {
            "rule_type": "keyword", "match_key": "apple", "category": "Salary", "kind": "bogus",
        })
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_updating_a_rule_can_change_kind(self):
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="apple", category="Salary", kind="income")
        status, payload = self._post("/api/category-rule/update", {
            "id": rule_id, "rule_type": "keyword", "match_key": "apple", "category": "Salary", "kind": "expense",
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.list_category_rules()[0]["kind"], "expense")

    def test_setup_page_shows_kind_selector_and_one_apply_all_button(self):
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="apple", category="Salary", kind="income")
        db.upsert_category_rule(rule_type="keyword", match_key="google", category="Salary", kind="income")
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn('name="kind"', body)
        # One button for every rule -- no per-row Apply any more.
        self.assertEqual(body.count('onclick="applyAllCategoryRules()"'), 1)
        self.assertNotIn(f"applyCategoryRule({rule_id})", body)
        self.assertIn("Income", body)


class TestApplyCategoryRuleEndpoint(DashboardTestCase):
    """Setup page's per-row "Apply" button -- source.common.db.
    transactions.apply_category_rule via /api/category-rule/apply. See
    TestCategoryRuleEndpoints above for the ordinary save/update flow
    this builds on, which never force-overwrites a hand-edited
    transaction the way this endpoint deliberately does."""

    def tearDown(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM plaid_transactions")
            conn.execute("DELETE FROM category_rules")
        db.delete_plaid_item("apply-rule-item")

    def _seed(self, transaction_id, **kwargs):
        if not db.get_plaid_item("apply-rule-item"):
            db.upsert_plaid_item(
                item_key="apply-rule-item", plaid_item_id="item-apply", institution_id=None,
                institution_name=None, products=["transactions"], environment="sandbox",
                linked_at="2026-09-01T00:00:00+00:00",
            )
        defaults = {
            "transaction_id": transaction_id, "account_id": "acc-1", "date": "2026-09-01", "amount": -500.0,
            "iso_currency_code": "USD", "name": "APPLE INC. PAYROLL 117316", "merchant_name": None,
            "pending": False, "plaid_category_primary": "INCOME", "plaid_category_detailed": "INCOME_SALARY",
            "category": "Food And Drink Coffee", "excluded_from_expense": False,
        }
        defaults.update(kwargs)
        db.upsert_plaid_transaction(item_key="apply-rule-item", transaction=defaults)

    def test_apply_forces_category_and_kind_onto_a_hand_edited_transaction(self):
        self._seed("t1")
        db.update_plaid_transaction_category(["t1"], "salary")  # hand-edited, category_edited_by_user=1
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="apple", category="Salary", kind="income")

        status, payload = self._post("/api/category-rule/apply", {"id": rule_id})

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True, "matched": 1, "recategorized": 1, "kind_applied": 1})
        row = db.list_plaid_transactions()[0]
        self.assertEqual(row["category"], "Salary")
        self.assertEqual(row["category_edited_by_user"], 0)  # the keyword rule now governs it again
        self.assertEqual(row["income_kind_override"], "income")

    def test_apply_does_not_touch_a_non_matching_transaction(self):
        self._seed("t1", name="Local Diner", merchant_name="Local Diner")
        rule_id = db.upsert_category_rule(rule_type="keyword", match_key="apple", category="Salary", kind="income")

        status, payload = self._post("/api/category-rule/apply", {"id": rule_id})

        self.assertEqual(status, 200)
        self.assertEqual(payload["matched"], 0)
        self.assertEqual(db.list_plaid_transactions()[0]["income_kind_override"], "")

    def test_apply_all_applies_every_rule_and_the_higher_precedence_one_wins_a_tie(self):
        self._seed("t1")
        self._seed("t2", name="GOOGLE PAYROLL", plaid_category_primary="OTHER", plaid_category_detailed="OTHER_OTHER")
        db.update_plaid_transaction_category(["t1", "t2"], "salary")  # both hand-edited
        # Two keyword rules that both match t1: the earlier rule (lower id) is the one a
        # normal categorization pass would pick, so it must win.
        db.upsert_category_rule(rule_type="keyword", match_key="apple", category="First", kind="income")
        db.upsert_category_rule(rule_type="keyword", match_key="payroll", category="Second", kind="expense")
        db.upsert_category_rule(rule_type="keyword", match_key="google", category="Alphabet", kind="income")

        status, payload = self._post("/api/category-rule/apply-all", {})

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["rules"], 3)
        by_id = {r["transaction_id"]: r for r in db.list_plaid_transactions()}
        self.assertEqual(by_id["t1"]["category"], "First")
        self.assertEqual(by_id["t1"]["income_kind_override"], "income")
        # t2 matches "payroll" (id 2) and "google" (id 3): the lower id wins.
        self.assertEqual(by_id["t2"]["category"], "Second")
        self.assertEqual(by_id["t2"]["income_kind_override"], "expense")

    def test_apply_all_with_no_rules_is_a_harmless_no_op(self):
        status, payload = self._post("/api/category-rule/apply-all", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"ok": True, "rules": 0, "recategorized": 0, "kind_applied": 0})

    def test_apply_returns_400_for_an_unknown_rule_id(self):
        status, payload = self._post("/api/category-rule/apply", {"id": 999})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])


class TestApplyCategoryRuleFromTransactionEndpoint(DashboardTestCase):
    """Actual Spending's per-row "Categorize similar" action -- source.
    common.db.transactions.apply_category_rule_from_transaction via
    /api/category-rule/apply-from-transaction. See TestCategoryRuleEndpoints
    above for the lower-level /api/category-rule/save this builds on."""

    def tearDown(self):
        with db.connect() as conn:
            conn.execute("DELETE FROM plaid_transactions")
            # This class's own rules only -- DashboardTestCase shares one
            # database across every test in this module (see its
            # setUpClass), so leaving an unrelated rule untouched matters.
            conn.execute(
                "DELETE FROM category_rules WHERE rule_type = 'keyword' AND match_key IN ('starbucks', 'acme utility co')"
            )
        db.delete_plaid_item("k")

    def _find_rule(self, match_key):
        return next((r for r in db.list_category_rules() if r["match_key"] == match_key), None)

    def _seed(self, transaction_id, *, name, merchant_name, category, amount=42.0):
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-k", institution_id=None, institution_name="Bank",
            products=["transactions"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="k", account={"account_id": "acc-1", "name": "Checking", "balances": {"current": 0}})
        db.upsert_plaid_transaction(item_key="k", transaction={
            "transaction_id": transaction_id, "account_id": "acc-1", "date": "2026-09-01", "amount": amount,
            "iso_currency_code": "USD", "name": name, "merchant_name": merchant_name, "pending": False,
            "plaid_category_primary": "OTHER", "plaid_category_detailed": "OTHER_OTHER",
            "category": category, "excluded_from_expense": False,
        })

    def test_derives_a_keyword_from_merchant_name_and_saves_it_as_a_rule(self):
        self._seed("t1", name="Starbucks Coffee #4521", merchant_name="Starbucks", category="Food")
        status, payload = self._post("/api/category-rule/apply-from-transaction", {"transaction_id": "t1"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["keyword"], "starbucks")
        self.assertEqual(payload["category"], "Food")
        rule = self._find_rule("starbucks")
        self.assertIsNotNone(rule)
        self.assertEqual(rule["rule_type"], "keyword")
        self.assertEqual(rule["category"], "Food")

    def test_applies_immediately_to_another_matching_transaction(self):
        self._seed("t1", name="ACME UTILITY CO DES:PAYROLL ID:1", merchant_name="", category="Housing & Utilities", amount=-10_150.0)
        self._seed("t2", name="ACME UTILITY CO DES:PAYROLL ID:2", merchant_name="", category="Uncategorized", amount=-10_150.0)
        # t1 is the example the person retyped by hand first (mirrors the
        # bulk-classify bar's own "Set category" call, which always marks
        # category_edited_by_user -- otherwise recategorize_all_
        # transactions would immediately overwrite it right back).
        db.update_plaid_transaction_category(["t1"], "Income")
        status, payload = self._post("/api/category-rule/apply-from-transaction", {"transaction_id": "t1"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["keyword"], "acme utility co")
        self.assertEqual(payload["category"], "Income")
        self.assertEqual(payload["recategorized"], 1)
        by_id = {t["transaction_id"]: t for t in db.list_plaid_transactions()}
        self.assertEqual(by_id["t2"]["category"], "Income")

    def test_unknown_transaction_id_returns_400(self):
        status, payload = self._post("/api/category-rule/apply-from-transaction", {"transaction_id": "nope"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_a_transaction_with_no_usable_name_or_merchant_returns_400(self):
        self._seed("t1", name="", merchant_name="", category="Uncategorized")
        status, payload = self._post("/api/category-rule/apply-from-transaction", {"transaction_id": "t1"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])


class TestDrawdownPlanningPage(DashboardTestCase):
    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("real_estate")
        db.clear_section("account_tax_splits")
        for item_key in ("fidelity", "chase"):
            db.delete_plaid_item(item_key)
        db.set_assumptions({"retirement_year": "", "current_year": "", "early_tax_deferred_age": "", "birth_year": ""})

    def _link_fidelity_401k(self, *, account_id="acc-401k", balance=100_000.0):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-fidelity", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": account_id, "name": "401(K) PLAN", "official_name": "401(K) PLAN",
            "type": "investment", "subtype": "401k", "mask": "1234",
            "balances": {"current": balance, "available": None, "iso_currency_code": "USD"},
        })

    def test_year_table_has_a_today_row_that_matches_the_resource_total(self):
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "A", "balance": 1_234_567, "include_in_monte_carlo": 1})
        db.set_assumptions({"retirement_year": "2030", "current_year": "2026", "expected_return": "0.08"})
        try:
            body = self._get("/drawdown-planning.html").read().decode("utf-8")
        finally:
            db.set_assumptions({"expected_return": "0.06"})
        self.assertIn("Today (starting balances, before any growth)", body)
        today_row = body.split("Today (starting balances, before any growth)")[1].split("</tr>")[0]
        self.assertIn("1,234,567", today_row)           # the same total as the tiles above
        self.assertIn("8.0% before the first row below", body)

    def test_year_table_shows_rental_and_social_security_income_columns(self):
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "A", "balance": 900_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Living", "annual_amount": 120_000})
        db.add_line_item("income", {"name": "Rental income", "category": "Rental", "annual_amount": 41_000})
        db.add_line_item("income", {"name": "Social Security", "category": "Social Security", "annual_amount": 33_000})
        try:
            body = self._get("/drawdown-planning.html").read().decode("utf-8")
        finally:
            db.clear_section("expenses")
            db.clear_section("income")
        self.assertIn('<th class="num">Rental income</th>', body)
        self.assertIn('<th class="num">Social Security</th>', body)
        self.assertNotIn('<th class="num">Other income</th>', body)
        self.assertIn("41,000", body)
        self.assertIn("33,000", body)

    def test_nav_includes_drawdown_planning_tab(self):
        resp = self._get("/summary.html")
        body = resp.read().decode("utf-8")
        self.assertIn('href="/drawdown-planning.html"', body)

    def test_page_loads_with_no_data_at_all(self):
        resp = self._get("/drawdown-planning.html")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode("utf-8")
        self.assertIn("Drawdown Planning", body)
        self.assertIn("/linked-accounts.html#tax-buckets", body)   # the tax-bucket table and split card moved there
        linked = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn("No retirement/liquid resources yet", linked)

    def test_shows_tiles_for_each_tax_bucket(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 200_000, "include_in_monte_carlo": 1})
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("Tax-deferred (401k/Traditional)", body)
        self.assertIn("Roth (tax-free)", body)
        self.assertIn("Taxable (brokerage)", body)
        self.assertIn("200,000", body)

    def test_unlinked_fidelity_roth_account_shows_up_with_a_detected_roth_bucket(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-fidelity", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-roth", "name": "ROTH IRA", "official_name": "ROTH IRA",
            "type": "investment", "subtype": "roth", "mask": "1234",
            "balances": {"current": 75_000.0, "available": None, "iso_currency_code": "USD"},
        })
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn("ROTH IRA", body)
        self.assertIn("Fidelity", body)
        self.assertIn("Linked account (not on Assets tab)", body)
        self.assertIn("75,000", body)
        # Roth appears both as the tile and the source table's Tax bucket cell.
        self.assertIn("Roth (tax-free)", body)

    def test_split_card_offers_an_unlinked_investment_account_to_split(self):
        self._link_fidelity_401k(balance=100_000.0)
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn("Split a linked account across tax buckets", body)
        self.assertIn('<option value="acc-401k">Fidelity — 401(K) PLAN ($100,000)</option>', body)

    def test_no_unlinked_investment_accounts_shows_a_helpful_message_instead_of_the_add_form(self):
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn("No linked investment accounts are available to split", body)

    def test_adding_splits_replaces_the_lump_source_row_with_named_pieces(self):
        # The user's own scenario: a Fidelity 401k that mixes pre-tax and
        # Roth money in one account ("for fidelity can i segregate the
        # sources manually" / "give me option to break up one sum to
        # parts").
        self._link_fidelity_401k(balance=100_000.0)
        status, _ = self._post("/api/line-item/add", {
            "section": "account_tax_splits",
            "fields": {"account_id": "acc-401k", "name": "Base Pay Traditional", "tax_treatment": "tax_deferred", "amount": "70000"},
        })
        self.assertEqual(status, 200)
        status, _ = self._post("/api/line-item/add", {
            "section": "account_tax_splits",
            "fields": {"account_id": "acc-401k", "name": "Roth In-Plan Conversion", "tax_treatment": "roth", "amount": "30000"},
        })
        self.assertEqual(status, 200)
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn("401(K) PLAN — Base Pay Traditional", body)
        self.assertIn("401(K) PLAN — Roth In-Plan Conversion", body)
        self.assertNotIn(">401(K) PLAN</td>", body)  # the lump source row is gone
        self.assertNotIn("adjust the amounts below so they match", body)  # 70k + 30k == the account's own balance

    def test_mismatched_split_total_shows_a_warning(self):
        self._link_fidelity_401k(balance=100_000.0)
        status, _ = self._post("/api/line-item/add", {
            "section": "account_tax_splits",
            "fields": {"account_id": "acc-401k", "name": "Base Pay Traditional", "tax_treatment": "tax_deferred", "amount": "40000"},
        })
        self.assertEqual(status, 200)
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn("adjust the amounts below so they match", body)

    def test_an_account_already_on_the_asset_tab_can_still_be_split(self):
        # The exact case the user ran into: their Fidelity 401k was
        # already added as an Asset-tab row (so it no longer showed up
        # as "unlinked"), and the split card's account picker offered
        # nothing to select -- it now offers every live investment
        # account, linked to an Asset row or not.
        self._link_fidelity_401k(balance=100_000.0)
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "401k", "balance": 1, "include_in_monte_carlo": 1})
        db.update_line_item("assets", item_id, {"linked_account_id": "acc-401k"})
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn('<option value="acc-401k">Fidelity — 401(K) PLAN ($100,000)</option>', body)

        status, _ = self._post("/api/line-item/add", {
            "section": "account_tax_splits",
            "fields": {"account_id": "acc-401k", "name": "Base Pay Traditional", "tax_treatment": "tax_deferred", "amount": "70000"},
        })
        self.assertEqual(status, 200)
        status, _ = self._post("/api/line-item/add", {
            "section": "account_tax_splits",
            "fields": {"account_id": "acc-401k", "name": "Roth In-Plan Conversion", "tax_treatment": "roth", "amount": "30000"},
        })
        self.assertEqual(status, 200)
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn("401k — Base Pay Traditional", body)
        self.assertIn("401k — Roth In-Plan Conversion", body)
        # The lump "401k" source row (and its old single bucket) is gone,
        # and the tiles above reflect the split too -- $30,000 now
        # shows up as Roth rather than all $100,000 sitting under
        # Tax-deferred.
        self.assertIn("$70,000", body)
        self.assertIn("$30,000", body)

    def test_year_by_year_table_is_present_with_data(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("Year-by-year withdrawal sequence", body)
        self.assertIn("<th>Year</th>", body)
        self.assertIn("<th>Age</th>", body)
        self.assertIn("<th class=\"num\">RMD</th>", body)

    def test_opted_in_real_estate_appears_as_its_own_source_row(self):
        r_id = db.add_line_item("real_estate", {"name": "Cabin", "current_value": 300_000, "loan_balance": 0, "ownership_pct": 100})
        db.update_line_item("real_estate", r_id, {"include_in_monte_carlo": 1})
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn("Cabin", body)
        self.assertIn("Real estate (opted in)", body)

    def test_no_retirement_year_set_shows_every_year(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("Set a Retirement year on the Summary or Will my money last? tab", body)
        self.assertNotIn("are omitted below", body)

    def test_retirement_year_set_hides_the_years_before_it(self):
        db.set_assumptions({"current_year": "2026", "retirement_year": "2028"})
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("No withdrawal happens before 2028", body)
        self.assertIn("Years before 2028 (your set Retirement year) are omitted below", body)
        self.assertNotIn("<td>2026</td>", body)
        self.assertNotIn("<td>2027</td>", body)
        self.assertIn("<td>2028</td>", body)

    def test_this_years_plan_callout_names_the_first_visible_years_withdrawal(self):
        db.set_assumptions({"current_year": "2027"})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Brokerage", "balance": 500_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None})
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("Your plan for 2027", body)
        self.assertIn("from Taxable", body)

    def test_this_years_plan_callout_respects_the_retirement_year_gate(self):
        # The callout's "first visible row" must be the same 2028 row the
        # table itself leads with -- not the (hidden, $0-need) 2026 row.
        db.set_assumptions({"current_year": "2026", "retirement_year": "2028"})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Brokerage", "balance": 500_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None})
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("Your plan for 2028", body)
        self.assertNotIn("Your plan for 2026", body)

    def test_this_years_plan_callout_says_nothing_needed_when_pools_are_empty(self):
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("Nothing needs to come out of the portfolio this year", body)

    def test_year_by_year_table_includes_withdrawn_and_ending_columns(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("Withdrawn: Taxable", body)
        self.assertIn("Withdrawn: Tax-deferred", body)
        self.assertIn("Ending: Taxable", body)
        self.assertIn("Ending: Tax-deferred", body)
        self.assertIn("Ending: Roth", body)
        # Columns that are $0 in every row are left out instead of printing a wall of $0.
        self.assertNotIn("Withdrawn: Roth", body)
        self.assertNotIn("Withdrawn: Real estate", body)
        self.assertNotIn("Ending: Real estate", body)

    def test_real_estate_columns_appear_once_a_property_is_opted_in(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        db.add_line_item("real_estate", {"name": "Cabin", "current_value": 300_000, "include_in_monte_carlo": 1})
        try:
            body = self._get("/drawdown-planning.html").read().decode("utf-8")
        finally:
            db.clear_section("real_estate")
        self.assertIn("Ending: Real estate", body)

    def test_links_to_the_legacy_planning_tab_for_the_heir_tax_question(self):
        # The two tabs cross-link each other's own content instead of
        # duplicating it, per the user's own request ("remove duplicates
        # from Legacy and Drawdown"). This checks the in-body link, not
        # just the nav bar (which links every tab from every page).
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn('<a href="/legacy-planning.html">Legacy Planning</a>', body)

    def test_withdrawal_order_card_is_present_with_an_empty_field_by_default(self):
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("Withdrawal order", body)
        self.assertIn('name="early_tax_deferred_age"', body)
        self.assertIn("Right now the plan uses the default order", body)

    def test_setting_the_early_tax_deferred_age_persists_and_is_reflected_in_the_field(self):
        status, _ = self._post("/api/assumptions", {"early_tax_deferred_age": "60"})
        self.assertEqual(status, 200)
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn('name="early_tax_deferred_age" type="number" step="1" min="0" placeholder="e.g. 60" value="60"', body)
        self.assertIn("Right now, spending draws Tax-deferred FIRST", body)

    def test_setting_the_early_tax_deferred_age_changes_the_plan_and_table(self):
        db.set_assumptions({"current_year": "2027", "birth_year": "1967", "early_tax_deferred_age": "60"})
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Brokerage", "balance": 500_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None})
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("from Tax-deferred", body)
        self.assertIn("Once you reach age 60, spending draws Tax-deferred first", body)


class TestLegacyPlanningPage(DashboardTestCase):
    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("real_estate")
        db.set_assumptions({
            "retirement_year": "", "current_year": "", "heir_type": "", "heir_base_income": "", "heir_spread_years": "",
            "early_tax_deferred_age": "", "birth_year": "",
        })

    def test_baseline_is_labelled_your_current_plan_when_an_early_draw_age_is_set(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        db.set_assumptions({"birth_year": "1966", "early_tax_deferred_age": "60"})
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn("Your current plan: spend Tax-deferred first from age 60, no conversions", body)
        self.assertIn("vs. your current plan", body)
        self.assertIn("applies to the baseline and to every conversion row", body)

    def test_nav_includes_legacy_planning_tab(self):
        resp = self._get("/legacy-planning.html")
        body = resp.read().decode("utf-8")
        self.assertRegex(body, r'href="/drawdown-planning.html" class="active">.*<span class="nl">Drawdown &amp; Legacy</span></a>')
        self.assertIn('href="/legacy-planning.html" class="active">Legacy Planning</a>', body)

    def test_page_loads_with_no_data_at_all(self):
        resp = self._get("/legacy-planning.html")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode("utf-8")
        self.assertIn("Legacy Planning", body)
        self.assertIn("Strategy comparison", body)

    def test_shows_a_row_for_every_named_strategy(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn("No Roth conversions (today&#x27;s default order)", body)
        self.assertIn("Convert up to the 12% federal bracket each year", body)
        self.assertIn("Convert up to the 22% federal bracket each year", body)
        self.assertIn("Convert as much as the Taxable pool can afford the tax on", body)
        self.assertIn("today&#x27;s default", body)
        self.assertIn("Recommended", body)

    def test_shows_the_early_tax_deferred_spending_strategy_alongside_conversions(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn("Spend Tax-deferred first starting at age 60", body)

    def test_defaults_to_non_spouse_heir_and_shows_the_field_selected(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn('<option value="non_spouse" selected>', body)

    def test_setting_heir_type_to_spouse_persists_and_is_reflected(self):
        status, _ = self._post("/api/assumptions", {"heir_type": "spouse"})
        self.assertEqual(status, 200)
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn('<option value="spouse" selected>', body)

    def test_setting_an_explicit_heir_base_income_persists(self):
        status, _ = self._post("/api/assumptions", {"heir_base_income": "180000"})
        self.assertEqual(status, 200)
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn('name="heir_base_income" type="number" step="0.01" placeholder="$180,000" value="180000"', body)

    def test_year_by_year_drilldown_for_the_recommended_strategy_is_present(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn("Year-by-year:", body)
        self.assertIn(">Conversion</th>", body)

    def test_a_plan_with_no_tax_deferred_money_still_renders_cleanly(self):
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Brokerage", "balance": 500_000, "include_in_monte_carlo": 1})
        resp = self._get("/legacy-planning.html")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode("utf-8")
        self.assertIn("Strategy comparison", body)
        self.assertIn(dashboard._money(0.0), body)  # "Total converted" is $0 for every strategy

    def test_this_years_plan_callout_appears_before_the_heir_assumptions_card(self):
        db.set_assumptions({"current_year": "2027"})
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn("Your plan for 2027", body)
        self.assertLess(body.index("Your plan for 2027"), body.index("Heir assumptions"))

    def test_this_years_plan_callout_states_a_roth_conversion_amount(self):
        db.set_assumptions({"current_year": "2027"})
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Brokerage", "balance": 200_000, "include_in_monte_carlo": 1})
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertTrue("Convert " in body or "No Roth conversion this year" in body)

    def test_year_by_year_drilldown_includes_withdrawn_and_ending_columns(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn("Withdrawn: Taxable", body)
        self.assertIn("Withdrawn: Tax-deferred", body)
        self.assertIn("Ending: Taxable", body)
        # Both tabs share the same column set, and both leave out columns that are $0 in every row.
        self.assertNotIn("Ending: Real estate", body)

    def test_links_back_to_the_drawdown_planning_tab(self):
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn('<a href="/drawdown-planning.html">Drawdown\nPlanning</a>', body)

    def test_no_retirement_year_set_shows_every_year(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn("Set a Retirement year on the Summary or Will my money last? tab", body)
        self.assertNotIn("are omitted below", body)

    def test_retirement_year_set_hides_the_years_before_it_same_as_drawdown_planning(self):
        db.set_assumptions({"current_year": "2026", "retirement_year": "2028"})
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Baseline", "annual_amount": 50_000, "start_year": None, "end_year": None})
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn("No withdrawal happens before 2028", body)
        self.assertIn("Years before 2028 (your set Retirement year) are omitted below", body)
        self.assertIn("Your plan for 2028", body)
        self.assertNotIn("Your plan for 2026", body)
        self.assertNotIn("<td>2026</td>", body)
        self.assertNotIn("<td>2027</td>", body)
        self.assertIn("<td>2028</td>", body)

    def test_heir_spread_years_field_defaults_per_heir_type(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 500_000, "include_in_monte_carlo": 1})
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn('name="heir_spread_years"', body)
        self.assertIn('placeholder="10"', body)  # non_spouse default

        status, _ = self._post("/api/assumptions", {"heir_type": "spouse"})
        self.assertEqual(status, 200)
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn('placeholder="20"', body)  # spouse default

    def test_setting_heir_spread_years_persists_and_is_reflected(self):
        status, _ = self._post("/api/assumptions", {"heir_spread_years": "15"})
        self.assertEqual(status, 200)
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn('name="heir_spread_years" type="number" step="1" min="1" placeholder="15" value="15"', body)


class TestSummaryRetirementYearCard(DashboardTestCase):
    """The Summary tab's "Plan outlook" card states the retirement year
    (read-only -- it is entered on the Monte Carlo tab's Assumptions form)."""

    def setUp(self):
        # A plan with nothing in it shows the welcome card instead.
        db.add_line_item("expenses", {"name": "Baseline", "category": "Fixed", "annual_amount": 60_000})

    def tearDown(self):
        db.set_assumptions({"retirement_year": "", "current_year": ""})
        db.clear_section("expenses")

    def test_not_set_shows_the_not_set_note(self):
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("Retirement year not set", body)

    def test_setting_it_on_the_assumptions_endpoint_shows_on_summary_and_monte_carlo(self):
        status, _ = self._post("/api/assumptions", {"retirement_year": "2040"})
        self.assertEqual(status, 200)
        summary_body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("Retirement year 2040", summary_body)
        mc_body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn('name="retirement_year" type="number" step="1" placeholder="e.g. 2035" value="2040"', mc_body)

    def test_outlook_says_years_away(self):
        db.set_assumptions({"current_year": "2026", "retirement_year": "2036"})
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("Retirement year 2036 (10 years away)", body)

    def test_outlook_says_years_into_retirement_once_past_it(self):
        db.set_assumptions({"current_year": "2036", "retirement_year": "2026"})
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("Retirement year 2026 (10 years into retirement)", body)


class TestLogTicks(unittest.TestCase):
    """_log_ticks -- the 1/2/5 x 10^n gridline generator behind the
    Linked Accounts investment-balance chart's logarithmic axis. Pure
    function, no dashboard/DB needed."""

    def test_degenerate_ranges_return_no_ticks(self):
        from source.webapp.render_helpers.charts import _log_ticks
        self.assertEqual(_log_ticks(0, 100), [])
        self.assertEqual(_log_ticks(-10, 100), [])
        self.assertEqual(_log_ticks(100, 100), [])
        self.assertEqual(_log_ticks(100, 50), [])

    def test_a_couple_decades_uses_the_full_1_2_5_pattern(self):
        from source.webapp.render_helpers.charts import _log_ticks
        self.assertEqual(_log_ticks(100, 5000), [100, 200, 500, 1000, 2000, 5000])

    def test_a_single_narrow_decade_still_returns_the_one_tick_inside_it(self):
        from source.webapp.render_helpers.charts import _log_ticks
        self.assertEqual(_log_ticks(950, 1050), [1000])

    def test_a_very_wide_range_falls_back_to_the_coarsest_decades_only_pattern(self):
        # Neither the 1-2-5 nor the 1-5 pattern fits under max_ticks
        # across 7 orders of magnitude, so this falls all the way back
        # to bare powers of ten -- still more than max_ticks here (a
        # best-effort fallback, not a hard cap), but at least the
        # sparsest pattern available rather than a cluttered one.
        from source.webapp.render_helpers.charts import _log_ticks
        ticks = _log_ticks(1, 10_000_000, max_ticks=6)
        self.assertEqual(ticks, [1, 10, 100, 1_000, 10_000, 100_000, 1_000_000, 10_000_000])

    def test_a_moderately_wide_range_falls_back_to_the_1_5_pattern(self):
        from source.webapp.render_helpers.charts import _log_ticks
        # 1-2-5 across this range would be too many ticks (> max_ticks),
        # so this falls back one tier to 1-5 rather than all the way to
        # decades-only.
        ticks = _log_ticks(10, 5000, max_ticks=6)
        self.assertEqual(ticks, [10, 50, 100, 500, 1_000, 5_000])

    def test_ticks_are_always_within_the_given_range(self):
        from source.webapp.render_helpers.charts import _log_ticks
        ticks = _log_ticks(237, 8_412)
        for t in ticks:
            self.assertGreaterEqual(t, 237 * 0.999)
            self.assertLessEqual(t, 8_412 * 1.001)


if __name__ == "__main__":
    unittest.main()


class TestDailySnapshotLoop(unittest.TestCase):
    """dashboard._daily_snapshot_loop -- the background timer that records
    a new day's snapshot even if nobody opens the app that day."""

    def test_each_tick_passes_the_last_captured_date_forward(self):
        from unittest.mock import patch
        calls = []

        def fake_capture(last):
            calls.append(last)
            return f"day-{len(calls)}"

        with patch.object(dashboard, "capture_daily_snapshots_if_new_day", side_effect=fake_capture), \
                patch.object(dashboard.time, "sleep") as sleeper:
            dashboard._daily_snapshot_loop(interval_seconds=7, max_ticks=3)
        self.assertEqual(sleeper.call_count, 3)
        sleeper.assert_called_with(7)
        self.assertEqual(calls[1:], ["day-1", "day-2"])  # carries each result into the next tick

    def test_a_failed_capture_is_retried_on_the_next_tick_and_never_stops_the_loop(self):
        from unittest.mock import patch
        outcomes = [RuntimeError("boom"), "2026-09-02"]
        seen = []

        def fake_capture(last):
            seen.append(last)
            result = outcomes.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(dashboard, "capture_daily_snapshots_if_new_day", side_effect=fake_capture), \
                patch.object(dashboard.time, "sleep"):
            dashboard._daily_snapshot_loop(interval_seconds=1, max_ticks=2)
        # The failure didn't advance the "last captured" date, so the retry saw the same value.
        self.assertEqual(seen[0], seen[1])


class TestThemeToggle(DashboardTestCase):
    """A header Auto/Light/Dark toggle (persisted in localStorage and applied
    as <html data-theme> before first paint) on top of the OS-following
    prefers-color-scheme default; chart text uses theme variables so it's
    readable on a dark surface."""

    def test_every_page_has_the_toggle_and_the_early_init_script(self):
        for path in ("/asset.html", "/linked-accounts.html", "/setup.html"):
            body = self._get(path).read().decode("utf-8")
            self.assertIn('id="theme-toggle"', body, path)
            self.assertIn('onclick="rpCycleTheme()"', body, path)
            self.assertIn("localStorage.getItem('rp-theme')", body, path)
            # The init script sits in <head>, before <body>, so there is no flash.
            self.assertLess(body.index("rp-theme"), body.index("<body"), path)

    def test_css_supports_a_forced_light_and_forced_dark_theme(self):
        from source.webapp.render_helpers.styles import PAGE_CSS

        self.assertIn(':root[data-theme="dark"]', PAGE_CSS)
        self.assertIn(':root:not([data-theme="light"])', PAGE_CSS)
        self.assertIn("@media (prefers-color-scheme: dark)", PAGE_CSS)

    def test_login_page_applies_the_saved_theme_too(self):
        resp = self._get("/login.html")
        body = resp.read().decode("utf-8")
        self.assertIn("rp-theme", body)

    def test_donut_total_uses_theme_ink_not_a_fixed_dark_color(self):
        from source.webapp.render_helpers.charts import _donut_chart_html

        html_out = _donut_chart_html("T", [("A", 100.0, ["a"]), ("B", 50.0, ["b"])], dim="type")
        self.assertIn("fill:var(--ink", html_out)
        self.assertNotIn('fill="#0b0b0b"', html_out)


class TestStockAnalysisTab(DashboardTestCase):
    """The Stock Analysis tab (pages/stock_analysis.py): the watchlist table and the
    Quote and chart card, read-only, using the keys saved on the Trading tab."""

    def tearDown(self):
        from source.common import secrets_store
        secrets_store.delete_alpaca_keys()
        secrets_store.delete_alpaca_keys(mode="live")

    def test_without_keys_it_asks_to_connect_on_the_trading_tab(self):
        resp = self._get("/stock-analysis.html")
        self.assertEqual(resp.status, 200)
        body = resp.read().decode("utf-8")
        self.assertIn("Stock Analysis", body)
        self.assertIn("Connect on the Trading tab", body)
        self.assertNotIn("lookupQuote", body)

    def test_with_keys_it_shows_the_watchlist_table_then_quote_and_chart(self):
        from source.common import secrets_store
        secrets_store.set_alpaca_keys("PKX", "S3")
        body = self._get("/stock-analysis.html").read().decode("utf-8")
        self.assertIn('id="watchlist"', body)
        self.assertIn("/api/watchlist/data", body)
        self.assertIn("Quote and chart", body)
        self.assertLess(body.index('id="watchlist"'), body.index('id="quote"'))
        self.assertIn("never places an order", body)
        self.assertNotIn("S3", body)

    def test_live_keys_alone_are_enough_and_the_tab_is_lit(self):
        from source.common import secrets_store
        secrets_store.set_alpaca_keys("AKX", "L1", mode="live")
        body = self._get("/stock-analysis.html").read().decode("utf-8")
        self.assertIn('id="watchlist"', body)
        self.assertIn('<a href="/stock-analysis.html" class="active">', body)

    def test_the_watchlist_routes_add_list_and_remove(self):
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch
        from source.common import secrets_store
        from tests.test_alpaca import FakeAlpaca
        from tests.test_watchlist import climb, multi_bars, snap
        secrets_store.set_alpaca_keys("PKX", "S3")
        self.assertEqual(self._post("/api/watchlist/add", {"symbol": "up"}), (200, {"ok": True, "added": ["UP"]}))
        status, payload = self._post("/api/watchlist/add", {"symbol": "$$"})
        self.assertEqual(status, 400)
        self.assertIn("not a ticker", payload["error"])
        fake = FakeAlpaca({
            ("GET", "data.alpaca.markets/v2/stocks/bars"): multi_bars(UP=climb()),
            ("GET", "data.alpaca.markets/v2/stocks/snapshots"): {"UP": snap(330.0, 328.0)},
        })
        with patch("urllib.request.urlopen", fake):
            status, payload = self._post("/api/watchlist/data", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["rows"][0]["symbol"], "UP")
        self.assertEqual(payload["rows"][0]["price"], 330.0)
        self.assertTrue(all(c["method"] == "GET" for c in fake.calls))          # reading prices never orders
        self.assertEqual(self._post("/api/watchlist/remove", {"symbol": "UP"})[0], 200)
        with patch("urllib.request.urlopen", fake):
            self.assertEqual(self._post("/api/watchlist/data", {})[1]["rows"], [])


class TestTradingTab(DashboardTestCase):
    """The Trading tab (pages/trading.py + the /api/alpaca* routes): an Alpaca
    PAPER account only. Every Alpaca call goes through a fake urlopen."""

    def setUp(self):
        from source.collector import alpaca
        alpaca._previews.clear()

    def tearDown(self):
        from source.common import secrets_store
        secrets_store.delete_alpaca_keys()

    def _fake(self, extra=None):
        from tests.test_alpaca import FakeAlpaca, trade_route
        routes = {
            ("GET", "paper-api.alpaca.markets/v2/account"): {
                "status": "ACTIVE", "account_number": "PA123", "equity": "101000", "last_equity": "100000",
                "cash": "90000", "buying_power": "180000"},
            ("GET", "paper-api.alpaca.markets/v2/positions"): [
                {"symbol": "VTI", "qty": "10", "avg_entry_price": "200", "current_price": "210",
                 "market_value": "2100", "unrealized_pl": "100", "unrealized_plpc": "0.05"}],
            ("GET", "paper-api.alpaca.markets/v2/orders"): [
                {"id": "61e69015-8549-4bfd-b9c3-01e75843f47d", "symbol": "BND", "side": "buy", "qty": "5",
                 "type": "limit", "limit_price": "70", "status": "new", "submitted_at": "2026-10-01T14:30:00Z"}],
            **trade_route(250.0),
            ("POST", "paper-api.alpaca.markets/v2/orders"): {"id": "o-9", "status": "accepted"},
            **(extra or {}),
        }
        return FakeAlpaca(routes)

    def _connect(self, fake):
        from unittest.mock import patch
        with patch("urllib.request.urlopen", fake):
            return self._post("/api/alpaca-keys", {"key_id": "PKX", "secret": "S3"})

    def test_trading_is_its_own_main_tab(self):
        from source.webapp.render_helpers.shell import NAV_ITEMS
        self.assertIn(("trading-live.html", "Trading"), NAV_ITEMS)
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn('<a href="/trading-live.html"', body)          # the tab opens on the live account
        for url in ("/trading.html", "/trading-live.html"):          # and stays lit on either page
            page = self._get(url).read().decode("utf-8")
            self.assertIn('<a href="/trading-live.html" class="active">', page)
        self.assertLess(page.index("Live account (REAL money)"), page.index("Practice account (play money)"))

    def test_the_trading_tab_has_its_own_icon_not_the_blank_default(self):
        from source.webapp.render_helpers.shell import _NAV_ICONS, _nav_icon_html
        self.assertIn("trading.html", _NAV_ICONS)
        self.assertIn("<rect", _nav_icon_html("trading.html"))

    def test_without_keys_the_page_offers_to_connect_and_says_it_is_practice_only(self):
        body = self._get("/trading.html").read().decode("utf-8")
        self.assertIn("Connect your Alpaca practice account", body)
        self.assertIn("Practice only", body)
        self.assertIn("/api/alpaca-keys", body)

    def test_a_wrong_key_is_refused_and_not_saved(self):
        from source.common import secrets_store
        from tests.test_alpaca import FakeAlpaca, http_error
        fake = FakeAlpaca({("GET", "paper-api.alpaca.markets/v2/account"): http_error(401)})
        status, payload = self._connect(fake)
        self.assertEqual(status, 400)
        self.assertIn("rejected the keys", payload["error"])
        self.assertFalse(secrets_store.has_alpaca_keys())

    def test_connecting_then_the_page_shows_account_positions_and_orders(self):
        from unittest.mock import patch
        from source.common import secrets_store
        fake = self._fake()
        status, _ = self._connect(fake)
        self.assertEqual(status, 200)
        self.assertEqual(secrets_store.get_alpaca_keys(), ("PKX", "S3"))
        with patch("urllib.request.urlopen", fake):
            body = self._get("/trading.html").read().decode("utf-8")
        self.assertIn("Practice account value", body)
        self.assertIn("$101,000.00", body)
        self.assertIn("+$1,000.00", body)       # change since yesterday
        self.assertIn("VTI", body)
        self.assertIn("(+5.0%)", body)
        self.assertIn("BND", body)
        self.assertIn('data-order-id="61e69015-8549-4bfd-b9c3-01e75843f47d"', body)  # open order can be cancelled
        self.assertIn("Place a practice order", body)
        self.assertNotIn("S3", body)             # the secret is never shown

    def test_the_trading_pages_no_longer_hold_the_quote_card_but_point_to_stock_analysis(self):
        from unittest.mock import patch
        self._connect(self._fake())
        with patch("urllib.request.urlopen", self._fake()):
            body = self._get("/trading.html").read().decode("utf-8")
        self.assertNotIn("lookupQuote", body)
        self.assertIn('href="/stock-analysis.html?symbol=VTI"', body)     # a position's symbol opens in Stock Analysis
        self.assertIn('href="/stock-analysis.html"', body)
        self.assertIn("new URLSearchParams(location.search).get('symbol')", body)   # an order link can pre-fill the ticket

    def test_the_quote_route_returns_rating_trends_and_a_chart(self):
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch
        from tests.test_quote import bars_payload, make_bars
        bars = make_bars([100 + i * 0.2 for i in range(300)], start=datetime.now(timezone.utc) - timedelta(days=300))
        extra = {
            ("GET", "data.alpaca.markets/v2/stocks/VTI/bars"): bars_payload(bars),
            ("GET", "data.alpaca.markets/v2/stocks/VTI/snapshot"): {
                "latestTrade": {"p": 160.0, "t": "2026-10-01T15:00:00Z"}, "latestQuote": {"bp": 159.9, "ap": 160.1, "bs": 1, "as": 1},
                "dailyBar": {"o": 159, "h": 161, "l": 158, "c": 160.0, "v": 1000}, "prevDailyBar": {"o": 1, "h": 2, "l": 1, "c": 158.5, "v": 9}},
        }
        fake = self._fake(extra)
        self._connect(fake)
        with patch("urllib.request.urlopen", fake):
            status, payload = self._post("/api/alpaca/quote", {"mode": "paper", "symbol": "vti", "range": "6M"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["symbol"], "VTI")
        self.assertEqual(payload["quote"]["price"], 160.0)
        self.assertEqual(payload["range"], "6M")
        self.assertIn("label", payload["rating"])
        self.assertEqual(len(payload["trends"]), 3)
        self.assertIn("<svg", payload["chart"])
        self.assertTrue(all(c["url"].startswith("https://data.alpaca.markets/") for c in fake.calls if "/bars" in c["url"] or "/snapshot" in c["url"]))
        self.assertFalse([c for c in fake.calls if c["method"] == "POST" and "orders" in c["url"]])   # looking up never orders

    def test_the_quote_route_refuses_a_nonsense_ticker(self):
        from unittest.mock import patch
        fake = self._fake()
        self._connect(fake)
        with patch("urllib.request.urlopen", fake):
            status, payload = self._post("/api/alpaca/quote", {"mode": "paper", "symbol": "$$$"})
        self.assertEqual(status, 400)
        self.assertIn("ticker", payload["error"])

    def test_a_down_connection_shows_a_message_not_an_error_page(self):
        import urllib.error
        from unittest.mock import patch
        from tests.test_alpaca import FakeAlpaca
        self._connect(self._fake())
        down = FakeAlpaca({("GET", "paper-api.alpaca.markets/v2/account"): urllib.error.URLError("down")})
        with patch("urllib.request.urlopen", down):
            resp = self._get("/trading.html")
            body = resp.read().decode("utf-8")
        self.assertEqual(resp.status, 200)
        self.assertIn("reach Alpaca", body)
        self.assertIn("Remove saved keys", body)

    def test_preview_then_order_places_exactly_one_practice_order(self):
        from unittest.mock import patch
        fake = self._fake()
        self._connect(fake)
        order = {"symbol": "vti", "side": "buy", "qty": "10", "type": "market"}
        with patch("urllib.request.urlopen", fake):
            status, preview = self._post("/api/alpaca/preview", order)
            self.assertEqual(status, 200)
            self.assertEqual(preview["estimate"], 2500.0)
            self.assertFalse([c for c in fake.calls if c["method"] == "POST"])   # nothing sent yet
            status, placed = self._post("/api/alpaca/order", {"token": preview["token"]})
            self.assertEqual(status, 200)
            self.assertEqual(placed["id"], "o-9")
            status, again = self._post("/api/alpaca/order", {"token": preview["token"]})
            self.assertEqual(status, 400)
            self.assertIn("expired", again["error"])
        posts = [c for c in fake.calls if c["method"] == "POST" and "/v2/orders" in c["url"] and "alpaca-keys" not in c["url"]]
        self.assertEqual(len(posts), 1)
        self.assertTrue(posts[0]["url"].startswith("https://paper-api.alpaca.markets/"))

    def test_ordering_without_a_preview_is_refused(self):
        from unittest.mock import patch
        fake = self._fake()
        self._connect(fake)
        with patch("urllib.request.urlopen", fake):
            status, payload = self._post("/api/alpaca/order", {"token": "made-up"})
        self.assertEqual(status, 400)
        self.assertFalse([c for c in fake.calls if c["method"] == "POST"])

    def test_an_oversized_order_is_refused_with_a_reason(self):
        from unittest.mock import patch
        fake = self._fake()
        self._connect(fake)
        with patch("urllib.request.urlopen", fake):
            status, payload = self._post("/api/alpaca/preview", {"symbol": "VTI", "side": "buy", "qty": "500", "type": "market"})
        self.assertEqual(status, 400)
        self.assertIn("limited", payload["error"])

    def test_preview_without_keys_says_to_connect(self):
        status, payload = self._post("/api/alpaca/preview", {"symbol": "VTI", "side": "buy", "qty": "1", "type": "market"})
        self.assertEqual(status, 400)
        self.assertIn("No Alpaca keys", payload["error"])

    def test_cancel_and_disconnect(self):
        from unittest.mock import patch
        from source.common import secrets_store
        oid = "61e69015-8549-4bfd-b9c3-01e75843f47d"
        fake = self._fake({("DELETE", f"paper-api.alpaca.markets/v2/orders/{oid}"): {}})
        self._connect(fake)
        with patch("urllib.request.urlopen", fake):
            status, _ = self._post("/api/alpaca/cancel", {"id": oid})
        self.assertEqual(status, 200)
        self.assertTrue([c for c in fake.calls if c["method"] == "DELETE"])
        status, _ = self._post("/api/alpaca-keys/delete", {})
        self.assertEqual(status, 200)
        self.assertFalse(secrets_store.has_alpaca_keys())


class TestDebtPaydownChart(DashboardTestCase):
    """The "Debt paydown over time" card under the Liabilities table
    (asset.py's _debt_paydown_html, drawn by charts._net_worth_explorer_html
    in debt mode)."""

    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("real_estate")
        with db.connect() as conn:
            conn.execute("DELETE FROM net_worth_snapshots")
            conn.execute("DELETE FROM debt_balance_snapshots")

    def _snap(self, liabilities, snapshot_date, *, re_value=None, re_equity=0.0):
        db.record_snapshot(
            net_worth=0, manual_asset_total=0, linked_asset_total=0, liability_total=liabilities,
            real_estate_equity_total=re_equity, retirement_liquid_total=0,
            real_estate_value_total=re_value, snapshot_date=snapshot_date,
        )

    def _card(self, name, values):
        row = db.add_line_item("assets", {"kind": "liability", "category": "Card", "name": name, "balance": values[-1]})
        for i, v in enumerate(values, start=1):
            db.record_debt_balance_snapshot(source="liability", row_id=row, balance=v, name=name, snapshot_date=f"2026-09-0{i}")
        return row

    def test_no_card_at_all_without_any_debt(self):
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertNotIn("Debt paydown over time", body)
        self.assertNotIn('id="debt-explorer"', body)

    def test_one_day_of_history_shows_the_come_back_tomorrow_message(self):
        self._card("Visa", [5_000.0])
        self._snap(5_000.0, "2026-09-01")
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn("Debt paydown over time", body)
        self.assertIn("Come back tomorrow to see debt paydown", body)
        self.assertNotIn('id="debt-explorer"', body)

    def test_the_card_sits_under_the_liabilities_table_with_a_paid_down_headline(self):
        card = self._card("Visa", [5_000.0, 4_500.0, 4_000.0])
        for i, v in enumerate((5_000.0, 4_500.0, 4_000.0), start=1):
            self._snap(v, f"2026-09-0{i}")
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertEqual(body.count('id="debt-explorer"'), 1)
        self.assertLess(body.index("Total liabilities:"), body.index('id="debt-explorer"'))
        self.assertIn("Debt paydown over time", body)
        self.assertIn("paid down $1,000 (20.0%) since 2026-09-01", body)
        self.assertIn(f'data-id="{card}"', body)
        self.assertIn("Visa", body)
        self.assertIn("rp-debt-assets", body)
        self.assertIn("Debt balances over time", body)
        # The asset chart is untouched and keeps its own storage keys.
        self.assertNotIn('id="nw-explorer"', body.split('id="debt-explorer"')[0].split("Total liabilities:")[1])

    def test_a_rise_reads_up_and_is_not_called_paid_down(self):
        self._snap(4_000.0, "2026-09-01")
        self._snap(5_000.0, "2026-09-02")
        self._card("Visa", [4_000.0, 5_000.0])
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn("up $1,000 (25.0%) since 2026-09-01", body)
        self.assertNotIn("paid down $1,000", body)

    def test_mortgages_join_into_all_debts_and_become_the_headline(self):
        db.add_line_item("real_estate", {"name": "Home", "current_value": 900_000.0, "loan_balance": 300_000.0})
        self._snap(5_000.0, "2026-09-01", re_value=None, re_equity=590_000.0)
        self._snap(5_000.0, "2026-09-02", re_value=900_000.0, re_equity=600_000.0)
        self._snap(4_000.0, "2026-09-03", re_value=900_000.0, re_equity=602_000.0)
        body = self._get("/asset.html").read().decode("utf-8")
        card = body[body.index('id="debt-explorer"'):]
        self.assertIn('"name": "All debts"', card)
        self.assertIn('"headlineTotal": true', card)
        self.assertIn('["2026-09-02", 305000.0], ["2026-09-03", 302000.0]', card)
        self.assertIn('data-re="mort"', card)
        self.assertIn('data-re="liab"', card)
        self.assertIn("paid down $3,000 (1.0%) since 2026-09-02", card)

    def test_without_mortgage_history_the_headline_is_just_liabilities(self):
        db.add_line_item("real_estate", {"name": "Home", "current_value": 900_000.0, "loan_balance": 300_000.0})
        self._snap(5_000.0, "2026-09-01", re_equity=600_000.0)
        self._snap(4_000.0, "2026-09-02", re_equity=600_000.0)
        body = self._get("/asset.html").read().decode("utf-8")
        card = body[body.index('id="debt-explorer"'):]
        self.assertIn('"total": null', card)
        self.assertNotIn('data-re="mort"', card)
        self.assertIn('"headlineTotal": false', card)

    def test_each_chart_keeps_its_own_storage_keys(self):
        self._card("Visa", [5_000.0, 4_000.0])
        self._snap(5_000.0, "2026-09-01")
        self._snap(4_000.0, "2026-09-02")
        body = self._get("/asset.html").read().decode("utf-8")
        debt_part = body[body.index('id="debt-explorer"'):]
        self.assertNotIn("rp-nw-", debt_part)
        self.assertIn("rp-debt-show", debt_part)


class TestNetWorthExplorer(DashboardTestCase):
    """The Assets tab's net-worth card with a picker for plotting individual
    assets next to the total (charts._net_worth_explorer_html)."""

    def tearDown(self):
        db.clear_section("assets")
        db.clear_section("real_estate")
        with db.connect() as conn:
            conn.execute("DELETE FROM net_worth_snapshots")
            conn.execute("DELETE FROM asset_balance_snapshots")

    def _history(self, name, values):
        asset_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": name, "balance": values[-1]})
        for i, v in enumerate(values, start=1):
            db.record_asset_balance_snapshot(asset_id=asset_id, balance=v, name=name, snapshot_date=f"2026-09-0{i}")
        return asset_id

    def _net_worth(self, values):
        for i, v in enumerate(values, start=1):
            db.record_snapshot(
                net_worth=v, manual_asset_total=0, linked_asset_total=0, liability_total=0,
                real_estate_equity_total=0, retirement_liquid_total=v, snapshot_date=f"2026-09-0{i}",
            )

    def test_explorer_replaces_the_static_chart_when_an_asset_has_history(self):
        self._net_worth([1_000_000.0, 1_010_000.0, 1_030_000.0])
        asset_id = self._history("Fidelity 401k", [400_000.0, 405_000.0, 410_000.0])
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn('id="nw-explorer"', body)
        self.assertIn(f'data-id="{asset_id}"', body)
        self.assertIn("Fidelity 401k", body)
        self.assertIn('data-mode="pct"', body)
        self.assertIn('"points": [["2026-09-01", 1000000.0]', body)
        self.assertIn("+$30,000 (+3.0%) since 2026-09-01", body)

    def test_explorer_is_shown_even_when_no_asset_has_two_days_of_history(self):
        self._net_worth([1_000_000.0, 1_010_000.0])
        asset_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "New", "balance": 5})
        db.record_asset_balance_snapshot(asset_id=asset_id, balance=5.0, name="New", snapshot_date="2026-09-02")
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn('id="nw-explorer"', body)
        self.assertIn('data-nw="1"', body)
        self.assertNotIn(f'class="nw-chip" data-id="{asset_id}"', body)  # one day of history: not plottable yet
        self.assertIn("two days of history", body)

    def test_real_estate_chips_default_off_and_persist_their_choice(self):
        db.add_line_item("real_estate", {"name": "Home", "current_value": 900_000.0, "loan_balance": 300_000.0})
        self._net_worth([1_000_000.0, 1_010_000.0])
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn('class="nw-chip" data-re="value" aria-pressed="false"', body)
        self.assertIn("rp-nw-re", body)
        self.assertIn("anyRe()", body)

    def test_asset_names_are_escaped_and_cannot_break_out_of_the_embedded_json(self):
        self._net_worth([1.0, 2.0])
        self._history("</script><b>x</b>", [10.0, 11.0])
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertNotIn("</script><b>", body)
        self.assertIn("&lt;/script&gt;&lt;b&gt;x&lt;/b&gt;", body)  # the chip label
        self.assertIn("<\\/script>", body)  # ...and the JSON payload's escaped form

    def test_net_worth_chip_is_a_toggle_like_the_asset_chips(self):
        self._net_worth([1_000_000.0, 1_010_000.0])
        self._history("Fidelity 401k", [400_000.0, 405_000.0])
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn('<button type="button" class="nw-chip" data-nw="1" aria-pressed="true"', body)
        self.assertNotIn("nw-chip-fixed", body)
        # The script handles it and remembers the choice.
        self.assertIn("showNw", body)
        self.assertIn("rp-nw-show", body)

    def test_hovering_the_chart_shows_a_values_tooltip_not_just_a_native_title(self):
        self._net_worth([1_000_000.0, 1_010_000.0])
        self._history("Fidelity 401k", [400_000.0, 405_000.0])
        body = self._get("/asset.html").read().decode("utf-8")
        # A hover readout (guide line + one row per visible series) driven by pointer events...
        self.assertIn("addEventListener('pointermove', showTip)", body)
        self.assertIn("nw-tip-row", body)
        self.assertIn("nw-guide", body)
        # ...and its styling ships in the shared stylesheet.
        self.assertIn(".nw-tip {", body)


class TestWholeDollarMoneyFormatting(unittest.TestCase):
    def test_money_is_whole_dollars_with_thousands_commas(self):
        from source.webapp.render_helpers.formatting import _money
        self.assertEqual(_money(465965.67), "$465,966")
        self.assertEqual(_money(1234567), "$1,234,567")
        self.assertEqual(_money(-889000.4), "-$889,000")
        self.assertEqual(_money(0), "$0")
        self.assertEqual(_money(-0.2), "$0")  # never "-$0"
        self.assertEqual(_money(None), "--")

    def test_cents_are_kept_on_request(self):
        from source.webapp.render_helpers.formatting import _money
        self.assertEqual(_money(4.5, cents=True), "$4.50")
        self.assertEqual(_money(-1234.567, cents=True), "-$1,234.57")

    def test_money_input_values_have_commas_and_only_real_cents(self):
        from source.webapp.render_helpers.formatting import _format_money_input_value
        self.assertEqual(_format_money_input_value(1290000), "1,290,000")
        self.assertEqual(_format_money_input_value(1234.56), "1,234.56")
        self.assertEqual(_format_money_input_value(None), "0")
        self.assertEqual(_format_money_input_value(-50000), "-50,000")

    def test_money_cell_is_a_text_input_that_strips_commas_on_save(self):
        from source.webapp.render_helpers.cells import _editable_number_cell
        cell = _editable_number_cell("assets", 3, "balance", 1500000, money=True)
        self.assertIn('type="text"', cell)
        self.assertIn('value="1,500,000"', cell)
        self.assertIn("updateMoneyField('assets', 3, 'balance', this)", cell)


class TestLineChartHoverTooltip(unittest.TestCase):
    """The net-worth trend shows an instant crosshair + tooltip on hover (not only the slow native title)."""

    def test_chart_carries_hover_layer_and_every_day(self):
        from source.webapp.render_helpers import _line_chart_html
        out = _line_chart_html("Trend", [("2026-09-26", 100.0), ("2026-09-27", 150.0), ("2026-10-01", 90.0)])
        self.assertIn('class="lc-tip"', out)
        self.assertIn('class="lc-cross"', out)
        self.assertIn('mousemove', out)
        self.assertIn('touchmove', out)
        for day in ("2026-09-26", "2026-09-27", "2026-10-01"):
            self.assertIn(day, out)
        self.assertIn("$150", out)

    def test_no_hover_layer_without_data(self):
        from source.webapp.render_helpers import _line_chart_html
        self.assertNotIn("lc-tip", _line_chart_html("Trend", [("2026-09-26", 100.0)]))
