"""Ranked next steps and the "biggest moves" cause line."""

from __future__ import annotations

import unittest
from datetime import date

from source.common import db
from source.reporting import advice, progress
from tests.test_dashboard import DashboardTestCase

TODAY = date(2026, 10, 1)


def summary(birth=1980):
    return {"assumptions": {"birth_year": birth}}


def pos(sid, value, kind="Equity", **kw):
    return {"security_id": sid, "market_value": value, "security_type": kind, "security_name": sid,
            "ticker": sid, "tax_treatment": "taxable", "cost_basis": value, "account": "A", "institution": "Firm", **kw}


class TestBuildActions(DashboardTestCase):
    def test_low_chance_is_first(self):
        issue = {"level": "warn", "title": "Negative cash", "detail": "d", "href": "/x"}
        acts = advice.build_actions(summary(), 0.6, [], [issue], [], today=TODAY)
        self.assertEqual(acts[0]["title"], "Raise your chance of lasting")
        self.assertEqual([a["rank"] for a in acts], [1, 2])
        self.assertEqual(acts[1]["title"], "Negative cash")

    def test_healthy_plan_has_nothing(self):
        mix = [pos("s", 70_000, "Etf", security_name="Total Stock Market ETF"), pos("b", 25_000, "Mutual Fund", security_name="Total Bond Market Fund"), pos("c", 5_000, "Cash")]
        self.assertEqual(advice.build_actions(summary(1986), 0.95, mix, [], [], today=TODAY), [])

    def test_drift_and_ss_prompt(self):
        acts = advice.build_actions(summary(1966), 0.95, [pos("s", 100_000, "Etf", security_name="Total Stock Market ETF")], [], [], today=TODAY)
        titles = [a["title"] for a in acts]
        self.assertIn("Rebalance your mix", titles)
        self.assertIn("Compare Social Security claiming ages", titles)

    def test_capped_and_deduplicated(self):
        items = [{"level": "warn", "text": f"Missing {i}", "href": "/x"} for i in range(10)]
        acts = advice.build_actions(summary(), 0.5, [], [], items, today=TODAY)
        self.assertEqual(len(acts), advice.MAX_ACTIONS)


class TestMovers(unittest.TestCase):
    def test_biggest_movers(self):
        rows = [
            {"asset_id": 1, "snapshot_date": "2026-09-01", "balance": 100, "name": "Roth"},
            {"asset_id": 1, "snapshot_date": "2026-10-01", "balance": 600, "name": "Roth"},
            {"asset_id": 2, "snapshot_date": "2026-09-01", "balance": 900, "name": "Checking"},
            {"asset_id": 2, "snapshot_date": "2026-10-01", "balance": 700, "name": "Checking"},
            {"asset_id": 3, "snapshot_date": "2026-09-28", "balance": 50, "name": "New"},
            {"asset_id": 3, "snapshot_date": "2026-10-01", "balance": 5000, "name": "New"},
        ]
        m = progress.biggest_movers(rows, date(2026, 9, 1))
        self.assertEqual([x["name"] for x in m], ["Roth", "Checking"])  # "New" has no start near the base date
        self.assertEqual(m[0]["change"], 500)
        self.assertEqual(m[1]["change"], -200)


class TestSummaryPage(DashboardTestCase):
    def test_ranked_card_renders(self):
        status, _ = self._post("/api/sample-data", {"with_linked": True})
        self.assertEqual(status, 200)
        try:
            body = self._get("/summary.html").read().decode("utf-8")
            self.assertIn("What should I do next?", body)
            self.assertIn('class="ns-num', body)
        finally:
            self._post("/api/sample-data", {"action": "remove"})


if __name__ == "__main__":
    unittest.main()
