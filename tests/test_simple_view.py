"""Version 2: Simple / Full view, short sentences with the detail behind an "i",
and the Social Security planner living in one place."""

from __future__ import annotations

import unittest

from source.common import db
from source.webapp import explain
from tests.test_dashboard import DashboardTestCase


class TestViewMode(DashboardTestCase):
    def tearDown(self):
        db.set_view_mode("simple")

    def test_default_is_simple_and_page_says_so(self):
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertEqual(db.view_mode(), "simple")
        self.assertIn('data-view="simple"', body)

    def test_switch_saves_and_changes_the_page(self):
        status, d = self._post("/api/view-mode", {"mode": "full"})
        self.assertEqual((status, d["mode"]), (200, "full"))
        self.assertIn('data-view="full"', self._get("/summary.html").read().decode("utf-8"))

    def test_bad_value_is_refused(self):
        status, _ = self._post("/api/view-mode", {"mode": "weird"})
        self.assertNotEqual(status, 200)
        self.assertEqual(db.view_mode(), "simple")

    def test_header_has_the_toggle_and_more_tools(self):
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn("setViewMode('full')", body)
        self.assertIn('class="more-tools simple-only"', body)

    def test_advanced_parts_are_tagged_not_removed(self):
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        for needle in ('class="adv-only"', 'The numbers behind this', 'What could go wrong?', 'Apply drawdown tax'):
            self.assertIn(needle, body)


class TestCondense(unittest.TestCase):
    LONG = ("Each row is an annual amount, optionally scoped to a year range. Inflating rows grow with the "
            "inflation rate. The money-lasts tab nets income against expenses each year, so the numbers here "
            "drive how much you must withdraw from savings in every simulated year.")

    def test_long_grey_paragraph_gets_a_one_sentence_twin_and_an_i(self):
        body = f'<p class="muted">{self.LONG}</p>'
        out, extra = explain.condense(body)
        self.assertIn(body, out)                       # the original is untouched
        self.assertIn('class="muted tx-short">Each row is an annual amount, optionally scoped to a year range.', out)
        self.assertIn('data-ex="tx:1"', out)
        self.assertEqual(extra["tx:1"]["what"], self.LONG)

    def test_short_paragraph_is_left_alone(self):
        body = '<p class="muted">Short note.</p>'
        out, extra = explain.condense(body)
        self.assertEqual((out, extra), (body, {}))

    def test_links_in_the_first_sentence_survive(self):
        body = '<p class="muted">See the <a href="/x.html">Real Estate</a> tab. ' + "More words here. " * 15 + "</p>"
        out, _ = explain.condense(body)
        self.assertIn('<a href="/x.html">Real Estate</a>', out.split("tx-short")[1].split("</p>")[0])

    def test_assets_carry_the_extra_entries(self):
        _, extra = explain.condense(f'<p class="muted">{self.LONG}</p>')
        self.assertIn('"tx:1"', explain.assets_html("summary.html", [], extra))


class TestPlannerLivesInOnePlace(DashboardTestCase):
    def tearDown(self):
        db.clear_section("income")
        db.set_assumptions({"birth_year": "", "ss_benefit_self": "", "ss_claim_age_self": ""})

    def test_planner_rows_are_read_only_on_the_income_tab(self):
        db.set_assumptions({"birth_year": "1965", "ss_benefit_self": "36000", "ss_claim_age_self": "67"})
        self._post("/api/benefits/apply", {})
        page = self._get("/expense.html").read().decode("utf-8")
        row = next(r for r in page.split("<tr>") if "row-check" in r and "Social Security (Person 1)" in r)
        self.assertIn("set by the planner", row)
        self.assertNotIn('data-field="annual_amount"', row)
        self.assertNotIn('data-field="name"', row)

    def test_hand_made_rows_stay_editable(self):
        db.add_line_item("income", {"name": "Consulting", "category": "Work", "annual_amount": 1000})
        page = self._get("/expense.html").read().decode("utf-8")
        row = next(r for r in page.split("<tr>") if "row-check" in r and "Consulting" in r)
        self.assertIn('data-field="annual_amount"', row)


class TestWatchSentence(unittest.TestCase):
    def _rows(self, spending, rmd):
        return [{"year": 2040 + i, "expenses": e, "tax": 0.0, "rmd": r} for i, (e, r) in enumerate(zip(spending, rmd))]

    def test_required_withdrawals_jump_is_named(self):
        from source.reporting import presentation as pres
        rows = self._rows([300_000, 310_000, 500_000, 510_000], [0, 0, 400_000, 410_000])
        out = pres.watch_sentence(rows, lambda v: f"${v:,.0f}")
        self.assertIn("in 2042", out)
        self.assertIn("$310,000 to $500,000", out)
        self.assertIn("requiring withdrawals", out)

    def test_smooth_plan_says_nothing(self):
        from source.reporting import presentation as pres
        self.assertEqual(pres.watch_sentence(self._rows([300_000, 306_000, 312_000], [0, 0, 0]), str), "")

    def test_conversion_to_todays_dollars_is_applied(self):
        from source.reporting import presentation as pres
        rows = self._rows([300_000, 310_000, 500_000], [0, 0, 400_000])
        out = pres.watch_sentence(rows, lambda v: f"${v:,.0f}", lambda v, y: v / 2)
        self.assertIn("$155,000 to $250,000", out)


class TestNextStepsCap(unittest.TestCase):
    def test_only_three_shown_rest_folded(self):
        from source.webapp.pages import summary_blocks as blocks
        actions = [{"rank": i + 1, "level": "info", "title": f"Step {i + 1}", "href": "/x", "why": ""} for i in range(5)]
        out = blocks.next_steps_html(actions)
        visible = out.split('<details class="ns-more">')[0]
        for n in (1, 2, 3):
            self.assertIn(f"Step {n}", visible)
        self.assertNotIn("Step 4", visible)
        self.assertIn("Show 2 more", out)
        self.assertIn("Step 5", out)

    def test_three_or_fewer_has_no_fold(self):
        from source.webapp.pages import summary_blocks as blocks
        actions = [{"rank": 1, "level": "info", "title": "Only", "href": "/x", "why": ""}]
        self.assertNotIn("ns-more", blocks.next_steps_html(actions).replace(".ns-more", ""))


class TestNewInputWarnings(unittest.TestCase):
    def _issues(self, **summary):
        from source.reporting import data_check
        base = {"assumptions": {"spouse_birth_year": "1965"}, "drawdown_pools": {"tax_deferred": 1_000_000},
                "income": [], "expenses": []}
        base.update(summary)
        return {i["id"]: i for i in data_check.check_plan(base)}

    def test_lopsided_split_is_flagged(self):
        got = self._issues(drawdown_spouse_tax_deferred_share=0.88)
        self.assertIn("lopsided-401k-split", got)
        self.assertIn("88%", got["lopsided-401k-split"]["title"])
        self.assertIn("your partner's", got["lopsided-401k-split"]["title"])

    def test_even_split_or_no_spouse_is_quiet(self):
        self.assertNotIn("lopsided-401k-split", self._issues(drawdown_spouse_tax_deferred_share=0.5))
        self.assertNotIn("lopsided-401k-split", self._issues(drawdown_spouse_tax_deferred_share=0.9, assumptions={}))

    def test_flat_rent_next_to_inflating_spending(self):
        rent = [{"name": "House-Rental", "category": "Rental", "annual_amount": 40_000, "inflates": 0}]
        food = [{"name": "Food", "category": "Variable", "annual_amount": 12_000, "inflates": 1}]
        self.assertIn("rent-not-inflating", self._issues(income=rent, expenses=food))
        self.assertNotIn("rent-not-inflating", self._issues(income=[dict(rent[0], inflates=1)], expenses=food))
        self.assertNotIn("rent-not-inflating", self._issues(income=rent, expenses=[]))


class TestSummaryExtras(DashboardTestCase):
    def setUp(self):
        from source.common import demo_data
        demo_data.seed_sample_household(with_linked=True)

    def tearDown(self):
        from source.common import demo_data
        demo_data.remove_sample_data()
        db.set_tour_seen(False)

    def test_summary_has_the_quick_what_if_card(self):
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn('id="whatif-quick"', body)
        self.assertIn("I spend 10% less", body)
        self.assertIn("function wiQuick(", body)

    def test_tour_runs_once_then_stays_off(self):
        db.set_tour_seen(False)
        self.assertIn('data-tour="auto"', self._get("/summary.html").read().decode("utf-8"))
        self.assertIn('data-tour="off"', self._get("/asset.html").read().decode("utf-8"))
        status, _ = self._post("/api/tour-seen", {})
        self.assertEqual(status, 200)
        self.assertIn('data-tour="off"', self._get("/summary.html").read().decode("utf-8"))

    def test_summary_page_offers_the_tour_button(self):
        self.assertIn("startTour()", self._get("/summary.html").read().decode("utf-8"))


class TestWizardSpendingQuestion(DashboardTestCase):
    def test_asks_for_monthly_spending_when_none_entered(self):
        db.clear_section("expenses")
        body = self._get("/setup-wizard.html").read().decode("utf-8")
        self.assertIn('id="wz-spend"', body)
        self.assertIn("Cautious (5% a year)", body)

    def test_does_not_ask_when_spending_exists(self):
        i = db.add_line_item("expenses", {"name": "Food", "category": "Variable", "annual_amount": 1000})
        try:
            self.assertNotIn('id="wz-spend"', self._get("/setup-wizard.html").read().decode("utf-8"))
        finally:
            db.delete_line_item("expenses", i)


if __name__ == "__main__":
    unittest.main()
