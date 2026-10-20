"""The confidence level behind "How much can I safely spend?" is remembered, so the
Summary shows the level picked on the Will my money last? tab (it used to be stuck at 90%)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from source.common import db, demo_data
from source.webapp import dashboard
from tests.test_dashboard import DashboardTestCase

_FAKE = {"target": 0.8, "current_spending": 90000.0, "safe_spending": 95000.0}


class TestSafeSpendLevel(DashboardTestCase):
    def setUp(self):
        db.set_meta("safe_spend_target", "")
        demo_data.seed_sample_household(with_linked=True)

    def tearDown(self):
        demo_data.remove_sample_data()
        db.set_meta("safe_spend_target", "")

    def test_default_is_ninety(self):
        self.assertEqual(db.safe_spend_target(), 0.9)

    def test_rejects_silly_values(self):
        with self.assertRaises(ValueError):
            db.set_safe_spend_target(1.5)

    def test_picking_a_level_saves_it_and_the_summary_uses_it(self):
        with patch.object(dashboard, "_safe_spending_cached", return_value=_FAKE) as fn:
            status, body = self._post("/api/safe-spending", {"target": 0.8, "save": True})
        self.assertEqual(status, 200)
        self.assertEqual(fn.call_args[0][1], 0.8)
        self.assertEqual(db.safe_spend_target(), 0.8)
        summary = self._get("/summary.html").read().decode("utf-8")
        self.assertIn('id="ss-text" data-target="0.8"', summary)
        mc = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn('<option value="0.8" selected>80%</option>', mc)
        self.assertIn('data-target="0.8"', mc)

    def test_a_lookup_without_save_does_not_change_the_saved_level(self):
        db.set_safe_spend_target(0.95)
        with patch.object(dashboard, "_safe_spending_cached", return_value=_FAKE):
            self._post("/api/safe-spending", {"target": 0.8})
        self.assertEqual(db.safe_spend_target(), 0.95)

    def test_no_target_means_the_saved_one(self):
        db.set_safe_spend_target(0.95)
        with patch.object(dashboard, "_safe_spending_cached", return_value=_FAKE) as fn:
            self._post("/api/safe-spending", {})
        self.assertEqual(fn.call_args[0][1], 0.95)


class TestSourcesChartSentence(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household(with_linked=True)

    def tearDown(self):
        demo_data.remove_sample_data()

    def test_first_sentence_says_which_dollars_the_bars_are_in(self):
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertRegex(body, r"Each bar is one year, in (today&#x27;s|future) dollars\.")


class TestHeaderActions(DashboardTestCase):
    def test_header_buttons_sit_in_a_right_aligned_group(self):
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn('class="hdr-actions"', body)
        self.assertIn(".hdr-actions { margin-left: auto; justify-content: flex-end; }", body)


if __name__ == "__main__":
    unittest.main()
