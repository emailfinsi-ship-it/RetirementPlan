"""Hand-made Social Security rows next to the planner's rows are flagged and can be removed."""

from __future__ import annotations

import unittest

from source.common import db, demo_data
from source.reporting import benefits, data_check
from source.reporting.aggregate import build_summary
from tests.test_dashboard import DashboardTestCase


class TestDouble(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household(with_linked=True)
        for r in db.list_line_items("income"):          # the sample's own SS rows would be duplicates too
            db.delete_line_item("income", r["id"])
        for name, amount, year in (("Sri-SS", 32000, 2032), ("Anu-SS", 25000, 2037)):
            db.add_line_item("income", {"name": name, "category": "Social Security", "annual_amount": amount,
                                        "start_year": year, "base_year": year, "inflates": 1, "source": "manual"})

    def tearDown(self):
        demo_data.remove_sample_data()
        for r in db.list_line_items("income"):
            db.delete_line_item("income", r["id"])
        for key in ("ss_benefit_self", "ss_claim_age_self"):
            db.set_assumption(key, "")

    def _ids(self):
        return [i["id"] for i in data_check.run_checks(build_summary(), [], {"exists": True, "ok": True, "age_days": 0})]

    def test_nothing_flagged_until_the_planner_has_rows(self):
        # sample household's own SS rows are "sample"; hand rows alone, no planner inputs
        self.assertNotIn("double-social-security", self._ids())

    def test_flagged_once_the_planner_writes_rows_and_fix_removes_only_the_older_ones(self):
        self._post("/api/assumptions", {"ss_benefit_self": "4,250", "ss_claim_age_self": "67"})
        self._post("/api/benefits/apply", {})
        self.assertIn("double-social-security", self._ids())
        issue = next(i for i in data_check.run_checks(build_summary(), [], {"exists": True, "ok": True, "age_days": 0})
                     if i["id"] == "double-social-security")
        self.assertIn("Sri-SS", issue["title"])
        self.assertIn("Anu-SS", issue["title"])
        self.assertNotIn("Social Security (", issue["title"])     # the planner's own row is never named
        page = self._get("/expense.html").read().decode("utf-8")
        self.assertIn('id="double-ss"', page)
        status, d = self._post(issue["fix"]["url"], issue["fix"]["payload"])
        self.assertEqual(status, 200)
        self.assertEqual(d["deleted"], 2)
        names = [r["name"] for r in db.list_line_items("income")]
        self.assertNotIn("Sri-SS", names)
        self.assertNotIn("Anu-SS", names)
        self.assertTrue(any(n.startswith("Social Security (") for n in names))
        self.assertNotIn("double-social-security", self._ids())
        self.assertNotIn('id="double-ss"', self._get("/expense.html").read().decode("utf-8"))

    def test_removing_them_lowers_the_income_the_plan_counts(self):
        self._post("/api/assumptions", {"ss_benefit_self": "4,250", "ss_claim_age_self": "67"})
        self._post("/api/benefits/apply", {})
        before = len(build_summary()["income_for_simulation"])
        older = benefits.older_social_security_rows(db.list_line_items("income"), db.get_assumptions())
        self._post("/api/line-item/delete-bulk", {"items": [{"section": "income", "id": r["id"]} for r in older]})
        self.assertEqual(len(build_summary()["income_for_simulation"]), before - 2)


if __name__ == "__main__":
    unittest.main()
