"""Social Security amounts must save, whether typed as 36000, 36,000 or $36,000."""

from __future__ import annotations

import unittest

from source.common import db, demo_data
from source.reporting import benefits
from tests.test_dashboard import DashboardTestCase


class TestCleanNumber(unittest.TestCase):
    def test_forms(self):
        for raw in ("42000", "42,000", "$42,000", " 42 000 ", "$ 42,000.50"):
            self.assertAlmostEqual(float(db.clean_number_text(raw)), float(raw.replace("$", "").replace(",", "").replace(" ", "")))
        self.assertEqual(db.clean_number_text("abc"), "abc")
        self.assertEqual(db.clean_number_text(""), "")


class TestIncomeRowSaves(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household(with_linked=True)
        self.row = next(r for r in db.list_line_items("income") if r["name"].startswith("Social Security (Alex)"))

    def tearDown(self):
        demo_data.remove_sample_data()

    def test_amount_with_commas_or_dollar_sign_is_saved_not_zeroed(self):
        for raw, want in (("42,000", 42000.0), ("$51,500", 51500.0), (47000, 47000.0), ("38000.5", 38000.5)):
            status, d = self._post("/api/line-item/update", {"section": "income", "id": self.row["id"], "fields": {"annual_amount": raw}})
            self.assertEqual(status, 200, d)
            self.assertEqual(db.get_line_item("income", self.row["id"])["annual_amount"], want)

    def test_adding_a_row_with_commas_keeps_the_amount(self):
        i = db.add_line_item("income", {"name": "SSA test", "category": "Social Security", "annual_amount": "$36,000"})
        self.assertEqual(db.get_line_item("income", i)["annual_amount"], 36000.0)
        db.delete_line_item("income", i)


class TestPlannerSaves(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household(with_linked=True)

    def tearDown(self):
        demo_data.remove_sample_data()
        for key in ("ss_benefit_self", "ss_benefit_spouse", "ss_claim_age_self", "ss_claim_age_spouse"):
            db.set_assumption(key, "")

    def _alex_row(self):
        return next(r for r in db.list_line_items("income") if r["name"] == "Social Security (Alex)" and r["source"] == benefits.BENEFITS_SOURCE)

    def test_typed_with_commas_or_dollar_sign_saves_the_plain_number(self):
        for raw in ("36,000", "$36,000", "36000"):
            status, d = self._post("/api/assumptions", {"ss_benefit_self": raw})
            self.assertEqual(status, 200, d)
            self.assertEqual(db.get_assumptions()["ss_benefit_self"], "36000")

    def test_text_that_is_not_a_number_is_refused_with_a_clear_message(self):
        status, d = self._post("/api/assumptions", {"ss_benefit_self": "thirty six thousand"})
        self.assertEqual(status, 400)
        self.assertIn("number", d["error"])
        self.assertNotEqual(db.get_assumptions().get("ss_benefit_self"), "thirty six thousand")

    def test_blank_fields_are_left_alone(self):
        self._post("/api/assumptions", {"ss_benefit_self": "30,000"})
        status, _ = self._post("/api/assumptions", {"ss_benefit_self": "", "ss_benefit_spouse": ""})
        self.assertEqual(status, 200)
        self.assertEqual(db.get_assumptions()["ss_benefit_self"], "30000")

    def test_save_and_apply_writes_the_row_and_a_new_value_updates_it(self):
        self._post("/api/assumptions", {"ss_benefit_self": "$30,000", "ss_claim_age_self": "67"})
        status, d = self._post("/api/benefits/apply", {})
        self.assertEqual(status, 200)
        self.assertIn("Social Security (Alex)", d["created"] + d["updated"])
        first = self._alex_row()["annual_amount"]
        self.assertGreater(first, 0)
        self._post("/api/assumptions", {"ss_benefit_self": "42,000"})
        self._post("/api/benefits/apply", {})
        second = self._alex_row()["annual_amount"]
        self.assertAlmostEqual(second / first, 42000 / 30000, places=3)

    def test_planner_shows_the_monthly_amount_from_the_ssa_statement(self):
        db.set_assumption("ss_benefit_self", "42000")      # stored per year
        page = self._get("/expense.html").read().decode("utf-8")
        self.assertIn('name="ss_benefit_self" type="text"', page)
        self.assertIn('value="3500"', page)                # shown per month
        self.assertIn("per month", page)
        self.assertIn("Math.round(n * 12)", page)          # saved per year

    def test_planner_inputs_accept_typing_commas(self):
        page = self._get("/expense.html").read().decode("utf-8")
        self.assertIn('name="ss_benefit_self" type="text"', page)
        self.assertNotIn('name="ss_benefit_self" type="number"', page)
        self.assertIn('id="benefits-planner"', page)
        self.assertIn("benefits-saved", page)


if __name__ == "__main__":
    unittest.main()
