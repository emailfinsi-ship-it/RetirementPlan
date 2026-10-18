"""Presentation steps 4-6: hide balances, sample household / demo, the
printable plan report, and the small tab-polish changes."""

from __future__ import annotations

import re
import unittest
from unittest import mock

from source.common import config, db, demo_data
from source.webapp.render_helpers import shell
from tests.test_dashboard import DashboardTestCase


class TestSampleHousehold(DashboardTestCase):
    def tearDown(self):
        demo_data.remove_sample_data()
        db.set_setup_complete(False)

    def test_seed_adds_sample_rows_and_remove_deletes_only_them(self):
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Mine", "balance": 5})
        demo_data.seed_sample_household()
        self.assertTrue(demo_data.has_sample_data())
        removed = demo_data.remove_sample_data()
        self.assertGreater(removed, 5)
        self.assertFalse(demo_data.has_sample_data())
        self.assertEqual([r["name"] for r in db.list_line_items("assets")], ["Mine"])
        db.clear_section("assets")

    def test_seed_twice_is_a_no_op(self):
        demo_data.seed_sample_household()
        n = len(db.list_line_items("assets"))
        demo_data.seed_sample_household()
        self.assertEqual(len(db.list_line_items("assets")), n)

    def test_endpoint_loads_then_removes_and_wizard_offers_button_only_when_empty(self):
        body = self._get("/setup-wizard.html").read().decode("utf-8")
        self.assertIn("Load sample household", body)
        status, _ = self._post("/api/sample-data", {})
        self.assertEqual(status, 200)
        body = self._get("/setup-wizard.html").read().decode("utf-8")
        self.assertNotIn("Load sample household", body)
        setup = self._get("/setup.html").read().decode("utf-8")
        self.assertIn("Remove sample data", setup)
        status, payload = self._post("/api/sample-data", {"action": "remove"})
        self.assertEqual(status, 200)
        self.assertGreater(payload["removed"], 0)
        setup = self._get("/setup.html").read().decode("utf-8")
        self.assertNotIn("Remove sample data", setup)

    def test_endpoint_refuses_to_load_into_a_plan_that_has_real_data(self):
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Mine", "balance": 5})
        try:
            status, _ = self._post("/api/sample-data", {})
            self.assertNotEqual(status, 200)
        finally:
            db.clear_section("assets")

    def test_sample_summary_reads_as_a_verdict(self):
        demo_data.seed_sample_household()
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertRegex(body, r"Your plan (is on track|is worth a second look|needs attention)")
        self.assertIn("Will your money last?", body)


class TestDemoBanner(unittest.TestCase):
    def test_banner_only_in_demo_mode(self):
        with mock.patch.object(config, "DEMO", False):
            self.assertEqual(shell._demo_banner_html(), "")
        with mock.patch.object(config, "DEMO", True):
            self.assertIn("Demo mode", shell._demo_banner_html())


class TestHideBalances(DashboardTestCase):
    def test_every_page_carries_the_hide_toggle_and_script(self):
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn('id="hide-toggle"', body)
        self.assertIn("rpToggleHide", body)
        self.assertIn("rp-hide", body)


class TestPlanReport(DashboardTestCase):
    def test_empty_plan_report_says_nothing_to_report(self):
        body = self._get("/report.html").read().decode("utf-8")
        self.assertIn("plan report", body)
        self.assertIn("nothing to report", body)

    def test_report_with_a_plan_has_story_assumptions_and_disclaimer(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "K", "balance": 900_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Living", "category": "Fixed", "annual_amount": 50_000})
        try:
            resp = self._get("/report.html")
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
        finally:
            db.clear_section("assets")
            db.clear_section("expenses")
        self.assertIn("window.print()", body)
        self.assertIn("Will your money last?", body)
        self.assertIn("Assumptions used", body)
        self.assertIn("not financial, tax or legal advice", body)
        self.assertIn("@media print", body)
        # Nothing interactive that makes no sense on paper.
        self.assertNotIn("Change assumptions", body)
        self.assertNotIn("Run what-if check", body)

    def test_report_numbers_match_the_summary(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "K", "balance": 900_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Living", "category": "Fixed", "annual_amount": 50_000})
        try:
            rep = self._get("/report.html").read().decode("utf-8")
            summ = self._get("/summary.html").read().decode("utf-8")
        finally:
            db.clear_section("assets")
            db.clear_section("expenses")
        pat = r"Typical case</div><div class=\"value\">(\$[\d,.]+)</div>"
        self.assertEqual(re.search(pat, rep).group(1), re.search(pat, summ).group(1))

    def test_summary_links_to_the_report(self):
        db.add_line_item("expenses", {"name": "Living", "category": "Fixed", "annual_amount": 50_000})
        try:
            body = self._get("/summary.html").read().decode("utf-8")
        finally:
            db.clear_section("expenses")
        self.assertIn("Download plan report (PDF)", body)
        self.assertIn('href="/report.html"', body)


class TestTabPolish(DashboardTestCase):
    def test_setup_groups_technical_sections_under_advanced(self):
        body = self._get("/setup.html").read().decode("utf-8")
        adv = body.index('id="advanced-settings"')
        for marker in ("Data &amp; output locations", 'id="category-rules-card"', "Automatic sync</h2>", "Network access &amp; your iPhone"):
            self.assertGreater(body.index(marker), adv, marker)
        # Security stays outside (above) the advanced group.
        self.assertLess(body.index("<h2 style=\"margin-top:0\">Security</h2>"), adv)

    def test_blank_years_cells_say_every_year(self):
        db.add_line_item("expenses", {"name": "Living", "category": "Fixed", "annual_amount": 50_000})
        try:
            body = self._get("/expense.html").read().decode("utf-8")
        finally:
            db.clear_section("expenses")
        self.assertIn("every year", body)

    def test_linked_account_numbers_are_blurred_until_revealed(self):
        body = self._get("/linked-accounts.html").read().decode("utf-8")
        self.assertIn("show-acct", body)
        self.assertIn(".acct-num", body)


if __name__ == "__main__":
    unittest.main()
