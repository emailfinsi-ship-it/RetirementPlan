import unittest

from source.common import db
from source.reporting import benefits
from tests.testing_utils import TempConfigTestCase


class TestClaimingMath(unittest.TestCase):
    def test_full_retirement_age_by_birth_year(self):
        self.assertEqual(benefits.full_retirement_age_months(1950), 66 * 12)
        self.assertEqual(benefits.full_retirement_age_months(1955), 66 * 12 + 2)
        self.assertEqual(benefits.full_retirement_age_months(1959), 66 * 12 + 10)
        self.assertEqual(benefits.full_retirement_age_months(1960), 67 * 12)
        self.assertEqual(benefits.full_retirement_age_months(1990), 67 * 12)
        self.assertEqual(benefits.fra_text(1955), "66 and 2 months")
        self.assertEqual(benefits.fra_text(1965), "67")

    def test_claiming_at_62_with_fra_67_is_70_percent(self):
        self.assertAlmostEqual(benefits.benefit_factor(1965, 62), 0.70)

    def test_claiming_at_full_retirement_age_is_100_percent(self):
        self.assertAlmostEqual(benefits.benefit_factor(1965, 67), 1.0)
        self.assertAlmostEqual(benefits.benefit_factor(1950, 66), 1.0)

    def test_delaying_to_70_with_fra_67_is_124_percent(self):
        self.assertAlmostEqual(benefits.benefit_factor(1965, 70), 1.24)

    def test_claiming_at_64_with_fra_67_is_80_percent(self):
        self.assertAlmostEqual(benefits.benefit_factor(1965, 64), 0.80)

    def test_ages_outside_62_to_70_are_clamped(self):
        self.assertAlmostEqual(benefits.benefit_factor(1965, 55), 0.70)
        self.assertAlmostEqual(benefits.benefit_factor(1965, 75), 1.24)

    def test_claiming_table_and_break_even(self):
        rows = benefits.claiming_table(30_000, 1965)
        self.assertEqual([r["age"] for r in rows], list(range(62, 71)))
        self.assertEqual(rows[0]["start_year"], 2027)
        self.assertAlmostEqual(rows[0]["annual"], 21_000)
        self.assertIsNone(rows[0]["break_even_vs_62"])
        r70 = rows[-1]
        self.assertAlmostEqual(r70["annual"], 37_200)
        # 21000*(x-62) = 37200*(x-70)  ->  x = (37200*70 - 21000*62) / 16200
        self.assertAlmostEqual(r70["break_even_vs_62"], (37_200 * 70 - 21_000 * 62) / 16_200)
        self.assertAlmostEqual(rows[3]["total_to_85"], rows[3]["annual"] * (85 - 65))


class TestMedicare(unittest.TestCase):
    def test_lowest_tier_is_the_standard_part_b_premium(self):
        t = benefits.medicare_tier(150_000, married=True)
        self.assertEqual(t["tier"], 0)
        self.assertAlmostEqual(t["part_b_monthly"], 202.90)
        self.assertAlmostEqual(t["annual"], 12 * 202.90)

    def test_tier_boundaries_differ_for_single_and_joint(self):
        self.assertEqual(benefits.medicare_tier(218_000, True)["tier"], 0)
        self.assertEqual(benefits.medicare_tier(218_001, True)["tier"], 1)
        self.assertEqual(benefits.medicare_tier(109_001, False)["tier"], 1)
        self.assertEqual(benefits.medicare_tier(109_001, True)["tier"], 0)

    def test_top_tier(self):
        t = benefits.medicare_tier(900_000, True)
        self.assertEqual(t["tier"], 5)
        self.assertAlmostEqual(t["monthly"], 689.90 + 91.00)


class TestPlannedRowsAndApply(TempConfigTestCase):
    ASSUMPTIONS = {
        "birth_year": "1965", "spouse_birth_year": "1967", "ss_benefit_self": "30000", "ss_claim_age_self": "67",
        "ss_benefit_spouse": "20000", "ss_claim_age_spouse": "62", "medicare_magi": "300000",
        "medicare_other_monthly": "250",
    }

    def test_rows_describe_each_person(self):
        rows = benefits.planned_rows(self.ASSUMPTIONS, this_year=2026)
        names = {r["name"]: r for r in rows["income"]}
        sri = names["Social Security (Person 1)"]
        self.assertEqual(sri["start_year"], 2032)
        self.assertAlmostEqual(sri["annual_amount"], 30_000)
        anu = names["Social Security (Person 2)"]
        self.assertEqual(anu["start_year"], 2029)
        self.assertAlmostEqual(anu["annual_amount"], 20_000 * benefits.benefit_factor(1967, 62))
        self.assertTrue(sri["inflates"] and sri["base_year"] == 2026)
        med = {r["name"]: r for r in rows["expenses"]}["Medicare premiums (Person 1)"]
        # 300k joint is IRMAA tier 3: 405.80 + 37.50, plus 250 other, per month.
        self.assertAlmostEqual(med["annual_amount"], 12 * (405.80 + 37.50 + 250))
        self.assertEqual(med["start_year"], 2030)

    def test_nothing_planned_without_inputs(self):
        self.assertEqual(benefits.planned_rows({"birth_year": "1965"}), {"income": [], "expenses": []})

    def test_apply_creates_then_updates_rows_without_duplicating(self):
        first = benefits.apply_benefits_plan(self.ASSUMPTIONS, this_year=2026)
        self.assertEqual(len(first["created"]), 4)
        self.assertEqual(first["updated"], [])
        changed = {**self.ASSUMPTIONS, "ss_claim_age_self": "70"}
        second = benefits.apply_benefits_plan(changed, this_year=2026)
        self.assertEqual(second["created"], [])
        self.assertEqual(len(second["updated"]), 4)
        income = {r["name"]: r for r in db.list_line_items("income")}
        self.assertEqual(len(income), 2)
        self.assertEqual(income["Social Security (Person 1)"]["start_year"], 2035)
        self.assertAlmostEqual(income["Social Security (Person 1)"]["annual_amount"], 37_200)
        self.assertEqual(len(db.list_line_items("expenses")), 2)

    def test_a_social_security_row_is_recognised_as_social_security_income(self):
        from source.reporting.monte_carlo.withdrawal import _income_kind
        row = benefits.planned_rows(self.ASSUMPTIONS, 2026)["income"][0]
        self.assertEqual(_income_kind(row), "social_security")


if __name__ == "__main__":
    unittest.main()

