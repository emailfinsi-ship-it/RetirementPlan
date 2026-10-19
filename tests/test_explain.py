"""The "i" pop-ups: every known tile and card title gets a button, every page
gets "About this page", and the explanations are shipped with the page."""

import html
import http.client
import json
import re
import unittest

from source.common import db, demo_data
from source.webapp import explain
from tests.test_dashboard import DashboardTestCase

PAGES = ["summary.html", "asset.html", "real-estate.html", "linked-accounts.html", "linked-positions.html",
         "rebalance.html", "expense.html", "real-expenditure.html", "budget-vs-actual.html", "monte-carlo.html",
         "drawdown-planning.html", "legacy-planning.html", "setup.html"]


class TestMatching(unittest.TestCase):
    def test_known_titles_and_labels(self):
        cases = [
            ("Net worth", "summary.html", "net_worth"),
            ("Investable savings", "summary.html", "investable"),
            ("Yearly spending in 2027", "summary.html", "yearly_spending"),
            ("Chance your money lasts", "summary.html", "chance"),
            ("Cautious case (1 in 10 do worse)", "summary.html", "cautious"),
            ("S&amp;P 500 chance your money lasts", "monte-carlo.html", "mc_sp_chance"),
            ("Since Aug 24", "summary.html", "since_then"),
            ("Alerts (4)", "summary.html", "alerts"),
            ("Data check (3)", "summary.html", "data_check"),
            ("2026 income covers expenses", "summary.html", "coverage"),
            ("Expenses by category (annual, nominal) -- $106K total", "summary.html", "expense_chart"),
            ("Expenses by category (annual, nominal)", "expense.html", "ie_charts"),
            ("Roth (tax-free)", "drawdown-planning.html", "dd_pool_tile"),
            ("Move to another Mac", "setup.html", "su_transfer"),
        ]
        for text, page, key in cases:
            self.assertEqual(explain.key_for(text, page), key, text)

    def test_unknown_text_gets_nothing(self):
        self.assertIsNone(explain.key_for("Some brand new heading", "summary.html"))
        self.assertIsNone(explain.key_for("Roth (tax-free)", "summary.html"))     # page-limited rule

    def test_annotate_leaves_the_page_untouched_and_lists_matches(self):
        body = '<div class="card"><h2>What should I do next?</h2></div><div class="tile"><div class="label">Net worth</div></div>'
        out, targets = explain.annotate(body, "summary.html")
        self.assertEqual(out, body)                      # the page's own HTML is never changed
        self.assertEqual(sorted(targets), [["net worth", "net_worth"], ["what should i do next?", "next_steps"]])

    def test_every_entry_is_complete_and_plain(self):
        for key in explain.all_keys():
            e = explain._E[key]
            self.assertTrue(e["title"] and e["what"], key)
            for field in ("what", "read", "do"):
                self.assertNotIn("<", e[field], key)         # plain text only
                self.assertLess(len(e[field]), 400, key)     # short enough to read at a glance

    def test_every_rule_points_at_an_entry(self):
        for _rx, key, _pages in explain.RULES:
            self.assertIn(key, explain.all_keys())


class TestPages(DashboardTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        demo_data.seed_sample_household(with_history=True, with_linked=True)
        db.set_setup_complete(True)

    def _page(self, name):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        conn.request("GET", "/" + name)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 200, name)
        return text

    def _data(self, page_html):
        m = re.search(r'<script type="application/json" id="ex-data">(.*?)</script>', page_html, re.S)
        self.assertIsNotNone(m)
        return json.loads(m.group(1).replace("<\\/", "</"))

    def _keys(self, page_html):
        return {k for _t, k in self._data(page_html)["targets"]}

    def test_every_tab_has_about_button_and_its_explanation(self):
        for name in PAGES:
            page = self._page(name)
            self.assertIn(f'data-ex="page:{name}"', page, name)
            data = self._data(page)
            self.assertIn(f"page:{name}", data["entries"])
            self.assertLessEqual(self._keys(page), set(data["entries"]), f"{name}: titles without a shipped explanation")

    def test_summary_tiles_are_all_explained(self):
        used = self._keys(self._page("summary.html"))
        for key in ("plan_status", "net_worth", "investable", "yearly_spending", "where_you_stand", "safe_spend",
                    "own_owe", "money_last", "start_balance", "chance", "cautious", "typical", "strong",
                    "spending_sources", "trend", "insight", "coverage", "liquid_share", "debt_ratio",
                    "asset_alloc", "expense_chart", "data_check", "next_steps"):
            self.assertIn(key, used, key)

    def test_other_tabs_have_tile_explanations_too(self):
        for name, key in (("monte-carlo.html", "chance"), ("drawdown-planning.html", "dd_rmd"), ("rebalance.html", "mix_today"),
                          ("expense.html", "ie_withdraw"), ("budget-vs-actual.html", "bva_expense"), ("setup.html", "su_security"),
                          ("legacy-planning.html", "lg_compare"), ("linked-positions.html", "checkup")):
            self.assertIn(key, self._keys(self._page(name)), f"{name} {key}")

    def test_page_html_is_not_modified_by_the_buttons(self):
        page = self._page("summary.html")
        self.assertIn('<div class="label">Net worth</div><div class="value">', page)

    def test_popup_script_and_style_ship_with_the_page(self):
        page = self._page("summary.html")
        self.assertIn('id="ex-data"', page)
        self.assertIn("#ex-overlay", page)
        self.assertIn("aria-modal", page)
        self.assertIn("div.label", page)


if __name__ == "__main__":
    unittest.main()
