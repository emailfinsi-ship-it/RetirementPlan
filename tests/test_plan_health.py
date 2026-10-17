import unittest

from source.reporting.plan_health import plan_health_card_html, plan_health_items


def _summary(**over):
    base = {
        "assumptions": {"birth_year": "1965", "spouse_birth_year": "1967", "retirement_year": "2030", "apply_drawdown_tax": "1"},
        "drawdown_tax_deferred_by_owner": {"self": 100.0, "spouse": 50.0, "unassigned": 0.0},
        "expenses": [{"name": "Living", "annual_amount": 1}],
        "income": [{"name": "Social Security (Person 1)", "category": "Social Security"}],
        "retirement_pools": {"tax_deferred": 1.0, "roth": 0.0, "taxable": 0.0},
        "real_estate": [],
    }
    base.update(over)
    return base


class TestPlanHealth(unittest.TestCase):
    def test_complete_plan_has_no_items(self):
        self.assertEqual(plan_health_items(_summary()), [])
        self.assertIn("Nothing missing", plan_health_card_html([]))

    def test_missing_birth_years_and_retirement_year(self):
        s = _summary(assumptions={"apply_drawdown_tax": "1"})
        texts = " | ".join(i["text"] for i in plan_health_items(s))
        self.assertIn("Person 1's birth year", texts)
        self.assertIn("Person 2's birth year", texts)
        self.assertIn("No retirement year", texts)

    def test_anu_birth_year_only_flagged_when_anu_owns_tax_deferred_money(self):
        s = _summary(
            assumptions={"birth_year": "1965", "retirement_year": "2030", "apply_drawdown_tax": "1"},
            drawdown_tax_deferred_by_owner={"self": 100.0, "spouse": 0.0, "unassigned": 0.0},
        )
        self.assertEqual(plan_health_items(s), [])

    def test_unassigned_money_no_expenses_no_pools_and_tax_off(self):
        s = _summary(
            drawdown_tax_deferred_by_owner={"self": 1.0, "spouse": 0.0, "unassigned": 5.0}, expenses=[],
            retirement_pools={"tax_deferred": 0.0, "roth": 0.0, "taxable": 0.0},
            assumptions={"birth_year": "1965", "retirement_year": "2030", "apply_drawdown_tax": "0"},
        )
        texts = " | ".join(i["text"] for i in plan_health_items(s))
        for needle in ("no Owner", "No expenses", "In Monte Carlo?", "Apply drawdown tax"):
            self.assertIn(needle, texts)

    def test_flags_missing_social_security(self):
        texts = " | ".join(i["text"] for i in plan_health_items(_summary(income=[])))
        self.assertIn("No Social Security income", texts)

    def test_property_gaps(self):
        s = _summary(real_estate=[
            {"name": "Rental", "current_value": 500000, "purchase_price": None, "loan_balance": 200000, "loan_end_year": None},
            {"name": "Empty", "current_value": 0, "purchase_price": 1, "loan_balance": 0, "loan_end_year": None},
        ])
        texts = [i["text"] for i in plan_health_items(s)]
        self.assertTrue(any("Rental has no purchase price" in t for t in texts))
        self.assertTrue(any("Rental has a loan but no" in t for t in texts))
        self.assertTrue(any("Empty has no current value" in t for t in texts))

    def test_card_lists_each_item_with_a_fix_link(self):
        html = plan_health_card_html(plan_health_items(_summary(assumptions={})))
        self.assertIn("to review", html)
        self.assertIn(">Fix</a>", html)


if __name__ == "__main__":
    unittest.main()
