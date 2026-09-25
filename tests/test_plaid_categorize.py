import unittest

from source.common.plaid_categorize import default_category, default_excluded_from_expense


class TestDefaultExcludedFromExpense(unittest.TestCase):
    def test_transfer_out_is_excluded(self):
        self.assertTrue(default_excluded_from_expense("TRANSFER_OUT", "TRANSFER_OUT_ACCOUNT_TRANSFER"))

    def test_transfer_in_is_excluded(self):
        self.assertTrue(default_excluded_from_expense("TRANSFER_IN", "TRANSFER_IN_ACCOUNT_TRANSFER"))

    def test_credit_card_payment_is_excluded(self):
        self.assertTrue(default_excluded_from_expense("LOAN_PAYMENTS", "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"))

    def test_plain_loan_payment_is_not_excluded(self):
        # A mortgage/auto loan installment isn't tracked against a
        # liability balance the way a credit card's own charges are, so
        # it stays counted as real spending unless excluded by hand.
        self.assertFalse(default_excluded_from_expense("LOAN_PAYMENTS", "LOAN_PAYMENTS_MORTGAGE_PAYMENT"))

    def test_ordinary_spend_is_not_excluded(self):
        self.assertFalse(default_excluded_from_expense("FOOD_AND_DRINK", "FOOD_AND_DRINK_GROCERIES"))

    def test_handles_missing_categories(self):
        self.assertFalse(default_excluded_from_expense(None, None))

    def test_is_case_insensitive(self):
        self.assertTrue(default_excluded_from_expense("transfer_out", "transfer_out_account_transfer"))


class TestDefaultCategory(unittest.TestCase):
    def test_prettifies_the_detailed_category(self):
        self.assertEqual(default_category("FOOD_AND_DRINK", "FOOD_AND_DRINK_COFFEE"), "Food And Drink Coffee")

    def test_falls_back_to_primary_when_detailed_is_missing(self):
        self.assertEqual(default_category("FOOD_AND_DRINK", None), "Food And Drink")

    def test_falls_back_to_uncategorized_when_both_are_missing(self):
        self.assertEqual(default_category(None, None), "Uncategorized")

    def test_falls_back_to_uncategorized_for_blank_strings(self):
        self.assertEqual(default_category("", ""), "Uncategorized")


if __name__ == "__main__":
    unittest.main()
