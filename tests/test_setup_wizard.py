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


class TestSetupFirst(unittest.TestCase):
    def test_setup_is_the_first_tab(self):
        self.assertEqual(NAV_ITEMS[0], ("setup.html", "Setup"))
        self.assertEqual([h for h, _ in NAV_ITEMS].count("setup.html"), 1)


class TestWizardPage(DashboardTestCase):
    def tearDown(self):
        db.set_setup_complete(False)

    def test_setup_page_has_the_wizard_with_five_steps(self):
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn('id="wizard"', body)
        for step in range(5):
            self.assertIn(f'data-step="{step}"', body)
        for field in ("wz-self", "wz-birth", "wz-return", "wz-inflation"):
            self.assertIn(f'id="{field}"', body)
        self.assertIn('id="plaid-keys"', body)

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
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn('value="1975"', body)
        self.assertIn('value="5.50"', body)
