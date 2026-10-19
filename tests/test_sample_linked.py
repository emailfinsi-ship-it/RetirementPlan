"""The pretend linked accounts that ship with the sample household."""

from __future__ import annotations

import unittest

from source.common import db, demo_data
from source.reporting.aggregate import build_summary
from tests.test_dashboard import DashboardTestCase


class TestSampleLinked(DashboardTestCase):
    def tearDown(self):
        demo_data.remove_sample_data()

    def test_seeds_accounts_holdings_transactions_without_double_counting(self):
        demo_data.seed_sample_household(with_linked=True)
        self.assertTrue(demo_data.has_sample_linked())
        self.assertEqual(len(db.list_plaid_accounts()), 8)
        self.assertGreater(len(db.list_plaid_transactions()), 60)
        s = build_summary()
        # Sample assets are tied to the pretend accounts, so liquid money is the same as without them.
        self.assertAlmostEqual(s["net_liquid_asset"], 3_230_000, delta=1)
        self.assertAlmostEqual(s["real_estate_equity_total"], 940_000, delta=1)

    def test_every_page_renders_with_the_sample_accounts(self):
        demo_data.seed_sample_household(with_linked=True)
        for path in ("summary", "asset", "real-estate", "linked-accounts", "linked-positions", "rebalance", "expense",
                     "real-expenditure", "budget-vs-actual", "monte-carlo", "drawdown-planning", "legacy-planning", "setup"):
            with self.subTest(path=path):
                self.assertEqual(self._get(f"/{path}.html").status, 200)

    def test_remove_clears_everything_and_sync_skips_sample_items(self):
        demo_data.seed_sample_household(with_linked=True)
        from source.collector import sync
        result = sync.sync_all()
        self.assertEqual(result["errors"], [])
        demo_data.remove_sample_data()
        self.assertEqual(db.list_plaid_items(), [])
        self.assertEqual(db.list_plaid_transactions(), [])
        self.assertEqual(db.list_line_items("assets"), [])

    def test_can_add_linked_to_an_already_loaded_sample_household(self):
        demo_data.seed_sample_household()
        self.assertFalse(demo_data.has_sample_linked())
        demo_data.seed_sample_household(with_linked=True)
        self.assertTrue(demo_data.has_sample_linked())
        status, _ = self._post("/api/sample-data", {"action": "remove"})
        self.assertEqual(status, 200)
        self.assertFalse(demo_data.has_sample_linked())


if __name__ == "__main__":
    unittest.main()
