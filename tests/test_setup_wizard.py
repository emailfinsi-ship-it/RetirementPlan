"""First-run setup wizard: the flag/needed logic, the landing redirect,
Setup being the first nav tab, and the wizard card itself."""

from __future__ import annotations

import unittest

from source.common import db
from source.webapp.render_helpers.shell import NAV_ITEMS
from tests.test_dashboard import DashboardTestCase
from tests.testing_utils import TempConfigTestCase


class TestSetupNeeded(TempConfigTestCase):
    def test_fresh_install_needs_setup(self):
        self.assertTrue(db.setup_needed())
        self.assertFalse(db.setup_complete())

    def test_finishing_the_wizard_clears_it(self):
        db.set_setup_complete(True)
        self.assertFalse(db.setup_needed())
        self.assertTrue(db.setup_complete())

    def test_existing_install_with_data_is_never_sent_to_the_wizard(self):
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Checking", "balance": 100})
        self.assertFalse(db.setup_needed())


class TestNav(unittest.TestCase):
    def test_setup_tab_stays_last_and_wizard_is_not_a_tab(self):
        self.assertEqual(NAV_ITEMS[-1], ("setup.html", "Setup"))
        self.assertNotIn("setup-wizard.html", [h for h, _ in NAV_ITEMS])
        self.assertEqual([h for h, _ in NAV_ITEMS].count("setup.html"), 1)


class TestWizardPage(DashboardTestCase):
    def tearDown(self):
        db.set_setup_complete(False)

    def test_setup_page_links_to_the_wizard(self):
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn('href="/setup-wizard.html"', body)
        self.assertNotIn('id="wizard"', body)

    def test_wizard_page_has_five_steps(self):
        body = self._get("/setup-wizard.html").read().decode("utf-8")
        self.assertIn('id="wizard"', body)
        for step in range(5):
            self.assertIn(f'data-step="{step}"', body)
        for field in ("wz-self", "wz-birth", "wz-return", "wz-inflation"):
            self.assertIn(f'id="{field}"', body)
        self.assertIn('/setup.html#plaid-keys', body)
        self.assertIn('id="plaid-keys"', self._get("/setup.html").read().decode("utf-8"))

    def test_setup_complete_endpoint_sets_the_flag(self):
        status, payload = self._post("/api/setup-complete", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(db.setup_complete())

    def test_wizard_saves_through_existing_endpoints_and_prefills(self):
        self._post("/api/assumptions", {"birth_year": "1975", "retirement_year": "2040",
                                        "expected_return_pct": "5.5", "inflation_rate_pct": "2.5"})
        a = db.get_assumptions()
        self.assertEqual(a["birth_year"], "1975")
        self.assertAlmostEqual(float(a["expected_return"]), 0.055)
        body = self._get("/setup-wizard.html").read().decode("utf-8")
        self.assertIn('value="1975"', body)
        self.assertIn('value="5.50"', body)


class TestSetupPageSections(DashboardTestCase):
    def _setup(self):
        return self._get("/setup.html").read().decode("utf-8")

    def test_linked_accounts_backups_and_category_rules_start_collapsed(self):
        body = self._setup()
        for card_id in ("linked-accounts-card", "backups-card", "category-rules-card"):
            i = body.index(f'id="{card_id}"')
            tag = body[body.rfind("<details", 0, i + 1):body.index(">", i)]
            self.assertNotIn(" open", tag, card_id)

    def test_backup_keep_setting(self):
        from source.common import app_settings, backup

        self.assertEqual(backup.KEEP_BACKUPS, 3)
        status, payload = self._post("/api/backup-keep", {"keep": 5})
        try:
            self.assertEqual(status, 200)
            self.assertEqual(payload["keep"], 5)
            self.assertIn('name="keep"', self._setup())
        finally:
            app_settings._write({k: v for k, v in app_settings._read().items() if k != "backup_keep"})
