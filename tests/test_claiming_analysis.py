"""Social Security claiming-age analysis: runs the plan once per claiming
age and suggests one."""

from __future__ import annotations

from source.common import db, demo_data
from source.reporting import benefits
from source.reporting.aggregate import build_summary
from tests.test_dashboard import DashboardTestCase


class TestClaimingAnalysis(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household()
        db.set_assumptions({"ss_benefit_self": "36000", "ss_claim_age_self": "67"})

    def tearDown(self):
        db.set_assumptions({"ss_benefit_self": "", "ss_claim_age_self": ""})
        demo_data.remove_sample_data()

    def test_runs_every_age_and_recommends_one(self):
        result = benefits.analyze_claiming(build_summary(), "self", iterations=150)
        self.assertEqual([r["age"] for r in result["rows"]], list(range(62, 71)))
        self.assertIn(result["recommended_age"], range(62, 71))
        self.assertEqual(result["chosen_age"], 67)
        annual = [r["annual"] for r in result["rows"]]
        self.assertEqual(annual, sorted(annual))  # waiting always pays more per year
        best = max(r["success_rate"] for r in result["rows"])
        rec = next(r for r in result["rows"] if r["age"] == result["recommended_age"])
        self.assertGreaterEqual(rec["success_rate"], best - 0.01 - 1e-9)

    def test_needs_a_benefit(self):
        db.set_assumptions({"ss_benefit_self": ""})
        with self.assertRaises(ValueError):
            benefits.analyze_claiming(build_summary(), "self", iterations=50)

    def test_endpoint_and_button(self):
        status, d = self._post("/api/benefits/claiming-analysis", {"person": "self"})
        self.assertEqual(status, 200)
        self.assertEqual(len(d["rows"]), 9)
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn("analyzeClaiming('self')", body)
        self.assertIn("based on my plan?", body)
