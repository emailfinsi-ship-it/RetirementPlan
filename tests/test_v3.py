"""Version 3: three tabs, gauge verdict, live what-if sliders, "what changed"
sentence and suggested spending from real transactions."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from source.common import db, demo_data
from source.reporting import presentation as pres, progress, real_link
from source.webapp.pages import summary_blocks as blocks
from source.webapp.pages.expense import _suggested_spending_html
from tests.test_dashboard import DashboardTestCase

TODAY = date(2026, 10, 20)


class TestGauge(unittest.TestCase):
    def test_ring_fills_to_the_chance(self):
        out = blocks.gauge_html(0.5, "warn")
        self.assertIn("tone-warn", out)
        self.assertIn("50%", out)
        circ = 2 * 3.14159265 * 54
        self.assertIn(f'stroke-dashoffset="{circ * 0.5:.1f}"', out)

    def test_near_certain_never_claims_100(self):
        self.assertIn(">99%", blocks.gauge_html(1.0, "ok"))

    def test_out_of_range_is_clamped(self):
        self.assertIn('stroke-dashoffset="0.0"', blocks.gauge_html(7, "ok"))
        self.assertIn("0%", blocks.gauge_html(-1, "bad"))


class TestChangeSentence(unittest.TestCase):
    def _change(self, net, parts, rate_then):
        return {"since": date(2026, 9, 26), "net_change": net, "parts": parts, "rate_then": rate_then, "movers": []}

    def _say(self, change, rate):
        return progress.change_sentence(change, rate, lambda v: f"${v:,.0f}", pres.percent_display)

    def test_up_with_a_clear_driver_and_a_moved_chance(self):
        out = self._say(self._change(50_000, [("Investments & savings", 48_000), ("Home equity", 2_000)], 0.71), 0.68)
        self.assertEqual(out, "Since Sep 26, your net worth is up $50,000, mostly from investments. "
                              "Your chance of lasting went from 71% to 68%.")

    def test_down_and_steady_chance(self):
        out = self._say(self._change(-10_000, [("Home equity", -9_000)], 0.8), 0.801)
        self.assertIn("down $10,000, mostly from home equity", out)
        self.assertIn("steady at 80%", out)

    def test_no_clear_driver_names_none(self):
        out = self._say(self._change(10_000, [("Investments & savings", 4_000), ("Home equity", 3_000), ("Other assets", 3_000)], None), 0.5)
        self.assertNotIn("mostly", out)

    def test_nothing_to_compare_or_nothing_moved_is_silent(self):
        self.assertEqual(self._say(None, 0.5), "")
        self.assertEqual(self._say(self._change(0.2, [], 0.5), 0.5), "")


class TestSuggestedSpending(unittest.TestCase):
    def _t(self, cat, amount, days_ago=30, income=False):
        return {"category": cat, "amount": amount, "date": (TODAY - timedelta(days=days_ago)).isoformat(),
                "is_real_income": income, "excluded_from_expense": False}

    def _txns(self):
        out = []
        for m in range(12):
            out += [self._t("Groceries", 700, 10 + m * 30), self._t("Dining", 300, 12 + m * 30), self._t("Coffee", 20, 14 + m * 30)]
        return out + [self._t("Paycheck", -5000, 20, income=True)]

    def test_lists_unplanned_categories_biggest_first_and_skips_small_ones(self):
        got = real_link.suggest_plan_lines(self._txns(), [], today=TODAY)
        self.assertEqual([g["category"] for g in got], ["Groceries", "Dining"])
        # 12 payments spread over ~11 months of history are scaled up to a year
        self.assertAlmostEqual(got[0]["annual"], 8400 * 12 / got[0]["months"], delta=1)
        self.assertGreaterEqual(got[0]["annual"], 8400)
        self.assertAlmostEqual(got[0]["monthly"], got[0]["annual"] / 12)

    def test_skips_categories_already_linked_or_named_in_the_plan(self):
        plan = [{"name": "Food", "linked_category": "groceries"}, {"name": "Dining", "linked_category": ""}]
        self.assertEqual(real_link.suggest_plan_lines(self._txns(), plan, today=TODAY), [])

    def test_income_is_never_suggested_as_spending(self):
        got = real_link.suggest_plan_lines(self._txns(), [], today=TODAY)
        self.assertNotIn("Paycheck", [g["category"] for g in got])

    def test_card_markup(self):
        out = _suggested_spending_html(real_link.suggest_plan_lines(self._txns(), [], today=TODAY), 2026)
        self.assertIn('id="suggested-spending"', out)
        self.assertIn('data-category="Groceries"', out)
        self.assertIn("addSuggestedSpending(this, 2026)", out)
        self.assertEqual(_suggested_spending_html([], 2026), "")


class TestSummaryV3(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household(with_linked=True)

    def tearDown(self):
        demo_data.remove_sample_data()

    def test_hero_has_the_gauge_next_to_the_headline(self):
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn('class="hero-main"', body)
        self.assertIn('class="gauge tone-', body)
        self.assertLess(body.index('class="gauge'), body.index('class="hero-title"'))

    def test_what_if_card_has_live_sliders(self):
        body = self._get("/summary.html").read().decode("utf-8")
        for needle in ('id="wq-spend"', 'id="wq-retire"', "function wiLive(", "function wqRun(", "wqCache"):
            self.assertIn(needle, body)

    def test_nav_is_today_my_plan_explore(self):
        body = self._get("/summary.html").read().decode("utf-8")
        nav = body[body.index("<nav>"):body.index("</nav>")]
        for label in ("Today", "My Plan", "Explore", "Setup"):
            self.assertIn(f'<span class="nl">{label}</span>', nav)
        self.assertNotIn("Drawdown", nav)

    def test_income_page_has_no_suggestion_card_without_transactions(self):
        self.assertNotIn('id="suggested-spending"', self._get("/expense.html").read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
