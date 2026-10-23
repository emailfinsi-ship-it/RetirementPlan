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


class TestMoneyBoxesKeepWhatYouType(DashboardTestCase):
    def test_comma_formatting_skips_number_boxes(self):
        # A type="number" box (the Add forms) cannot hold "12,345": writing the
        # comma version into it made the browser wipe the amount on Tab.
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn("if (el.type !== 'text') return;", body)
        self.assertLess(body.index("function formatMoneyInputs"), body.index("if (el.type !== 'text') return;"))


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
        self.assertNotIn("Compare</button>", body)

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

    def test_report_reads_like_an_adviser_review_for_a_client(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "K", "balance": 900_000, "include_in_monte_carlo": 1})
        db.add_line_item("expenses", {"name": "Living", "category": "Fixed", "annual_amount": 50_000})
        try:
            body = self._get("/report.html").read().decode("utf-8")
        finally:
            db.clear_section("assets")
            db.clear_section("expenses")
        titles = re.findall(r'<h2 class="rep-title">\d\. ([^<]+)</h2>', body)
        self.assertEqual(titles, [
            "Your plan at a glance", "Goals and where you stand", "Good, expected and bad markets",
            "Income and tax picture", "Assumptions and disclosures",
        ])
        self.assertIn("What we recommend", body)
        self.assertIn("Important information", body)
        self.assertIn("Retirement plan review prepared for", body)
        # Good / expected / bad market columns, and the page numbers on paper.
        for words in ("Bad market", "Expected market", "Good market"):
            self.assertIn(words, body)
        self.assertIn("counter(page)", body)
        # One brand only, and nothing clickable on a printed page.
        self.assertIn("FinSi", body)
        self.assertNotRegex(body.split("</style>")[-1].split('<section')[1], r'<a href="/')

    def test_every_page_header_has_the_report_button_before_the_eye_icon(self):
        for page in ("/summary.html", "/asset.html", "/setup.html"):
            body = self._get(page).read().decode("utf-8")
            self.assertIn("Report Download", body, page)
            self.assertIn('href="/report.html"', body, page)
            self.assertLess(body.index('id="report-btn"'), body.index('id="hide-toggle"'), page)

    def test_header_has_a_quit_button_right_after_the_theme_button(self):
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn('id="quit-btn"', body)
        self.assertIn("/api/quit", body)
        self.assertLess(body.index('id="theme-toggle"'), body.index('id="quit-btn"'))

    def test_setup_leads_with_the_wizard_banner_and_ends_with_the_import(self):
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn("Run the Setup Wizard", body)
        self.assertLess(body.index("Run the Setup Wizard"), body.index("Household"))
        self.assertGreater(body.index("Advanced: import a spreadsheet"), body.index("Quit "))

    def test_hide_balances_is_an_icon_with_an_accessible_label(self):
        body = self._get("/asset.html").read().decode("utf-8")
        toggle = re.search(r'<button[^>]*id="hide-toggle".*?</button>', body, flags=re.S).group(0)
        self.assertIn('aria-label="Hide balances"', toggle)
        self.assertIn("<svg", toggle)
        self.assertNotIn(">Hide balances<", toggle)

    def test_summary_no_longer_repeats_the_report_as_a_card(self):
        db.add_line_item("expenses", {"name": "Living", "category": "Fixed", "annual_amount": 50_000})
        try:
            body = self._get("/summary.html").read().decode("utf-8")
        finally:
            db.clear_section("expenses")
        self.assertNotIn("Download plan report (PDF)", body)


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


class TestInteractiveWhatIf(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household()

    def tearDown(self):
        demo_data.remove_sample_data()

    def test_form_has_editable_boxes_and_quick_tries(self):
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn("Assumptions &amp; what-if", body)
        self.assertNotIn('id="wi-spend"', self._get("/summary.html").read().decode("utf-8"))
        for needle in ('id="wi-spend"', 'id="wi-retire"', 'id="wi-growth"', "Compare", "Spend 10% less", "runWhatIf"):
            self.assertIn(needle, body)

    def test_custom_what_if_returns_base_and_changed_results(self):
        status, d = self._post("/api/what-if", {"custom": True, "spend_change_pct": "-15", "retire_shift_years": "2"})
        self.assertEqual(status, 200)
        self.assertIn("spend 15% less", d["label"])
        for side in ("base", "whatif"):
            self.assertEqual(set(d[side]), {"success_rate", "p10", "median", "p90"})
        self.assertGreaterEqual(d["whatif"]["median"], d["base"]["median"])

    def test_baseline_matches_the_summary_headline(self):
        _, d = self._post("/api/what-if", {"custom": True, "spend_change_pct": "-10"})
        body = self._get("/summary.html").read().decode("utf-8")
        pat = r"Chance your money lasts</div><div class=\"value\">((?:&gt;|>)?\d+%)</div>"
        shown = re.search(pat, body).group(1).replace("&gt;", ">")
        rate = d["base"]["success_rate"]
        self.assertEqual(shown, ">99%" if rate >= 0.995 else f"{rate * 100:.0f}%")

    def test_no_change_and_out_of_range_values_are_refused(self):
        for bad in ({"custom": True}, {"custom": True, "spend_change_pct": "0"},
                    {"custom": True, "spend_change_pct": "500"}, {"custom": True, "spend_change_pct": "abc"}):
            status, _ = self._post("/api/what-if", bad)
            self.assertNotEqual(status, 200, bad)

    def test_retiring_later_needs_a_retirement_year(self):
        db.set_assumptions({"retirement_year": ""})
        status, _ = self._post("/api/what-if", {"custom": True, "retire_shift_years": "2"})
        self.assertNotEqual(status, 200)


class TestSpendingChartInteractivity(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household()

    def tearDown(self):
        demo_data.remove_sample_data()

    def test_chart_carries_hover_focus_and_table_hooks(self):
        body = self._get("/summary.html").read().decode("utf-8")
        for needle in ('class="yr-hit"', 'legend-btn', 'id="src-detail"', 'id="src-data"',
                       "Show the numbers as a table", 'class="seg"'):
            self.assertIn(needle, body)

    def test_embedded_data_matches_the_table_and_is_valid_json(self):
        import json

        body = self._get("/summary.html").read().decode("utf-8")
        raw = re.search(r'<script type="application/json" id="src-data">(.*?)</script>', body, flags=re.S).group(1)
        data = json.loads(raw.replace("<\\/", "</"))
        self.assertEqual(len(data["names"]), len(data["colors"]))
        self.assertTrue(data["rows"])
        for row in data["rows"]:
            self.assertEqual(len(row["v"]), len(data["names"]))
        first = data["rows"][0]
        self.assertIn(f"<td>{first['year']}</td>", body)


class TestMonteCarloPersonalPage(DashboardTestCase):
    """The Monte Carlo tab reads as "Will my money last?": a plain verdict,
    a retirement-year slider, a "What could go wrong?" group with one
    sentence per historical crash, and advanced inputs tucked away."""

    def setUp(self):
        demo_data.seed_sample_household()

    def tearDown(self):
        demo_data.remove_sample_data()

    def test_page_is_personal_and_organised(self):
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        for needle in ("Will my money last?", "market simulations your savings last", "When could I retire?",
                       'id="rx-slider"', "What could go wrong?", "markets replayed from today",
                       "The biggest lever for your plan", "What moves your plan most", "Advanced settings"):
            self.assertIn(needle, body)
        # Purpose first: the answer and the scenario tables, then what moves it and the what-if,
        # then spending / retirement age, then the extra tests.
        self.assertLess(body.index("Historical recession stress test"), body.index("What moves your plan most"))
        self.assertLess(body.index("What moves your plan most"), body.index('id="rx-slider"'))
        self.assertLess(body.index('id="rx-slider"'), body.index("What could go wrong?"))

    def test_advanced_inputs_still_saved_once(self):
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        for name in ("iterations", "return_volatility_pct", "annual_income_offset", "taxable_gains_fraction_pct"):
            self.assertEqual(body.count(f'name="{name}"'), 1)
        adv = body[body.index("Advanced settings"):]
        self.assertLess(adv.index('name="iterations"'), adv.index("Save &amp; re-run"))

    def test_slider_needs_a_retirement_year(self):
        db.set_assumptions({"retirement_year": ""})
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertNotIn('id="rx-slider"', body)
        self.assertIn("When could I retire?", body)
