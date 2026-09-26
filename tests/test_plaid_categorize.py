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
    def test_rolls_up_a_detailed_value_to_its_broad_bucket(self):
        # Every FOOD_AND_DRINK subcategory -- coffee, groceries,
        # restaurants -- rolls up to the same "Food" bucket rather than
        # each getting its own distinct string.
        self.assertEqual(default_category("FOOD_AND_DRINK", "FOOD_AND_DRINK_COFFEE"), "Food")
        self.assertEqual(default_category("FOOD_AND_DRINK", "FOOD_AND_DRINK_GROCERIES"), "Food")

    def test_falls_back_to_primary_bucket_when_detailed_is_missing(self):
        self.assertEqual(default_category("FOOD_AND_DRINK", None), "Food")

    def test_falls_back_to_uncategorized_when_both_are_missing(self):
        self.assertEqual(default_category(None, None), "Uncategorized")

    def test_falls_back_to_uncategorized_for_blank_strings(self):
        self.assertEqual(default_category("", ""), "Uncategorized")

    def test_is_case_insensitive(self):
        self.assertEqual(default_category("food_and_drink", "food_and_drink_coffee"), "Food")

    def test_detailed_override_wins_over_its_own_primarys_default_bucket(self):
        # A student loan payment would otherwise fall into the generic
        # "Loan Payments" bucket every mortgage/auto-loan installment
        # gets -- it's specific enough to earn its own bucket instead.
        self.assertEqual(
            default_category("LOAN_PAYMENTS", "LOAN_PAYMENTS_STUDENT_LOAN_PAYMENT"), "Education / College Fees",
        )
        self.assertEqual(default_category("LOAN_PAYMENTS", "LOAN_PAYMENTS_MORTGAGE_PAYMENT"), "Loan Payments")

    def test_general_services_education_is_college_fees(self):
        self.assertEqual(default_category("GENERAL_SERVICES", "GENERAL_SERVICES_EDUCATION"), "Education / College Fees")

    def test_general_services_insurance_and_childcare_get_their_own_buckets(self):
        self.assertEqual(default_category("GENERAL_SERVICES", "GENERAL_SERVICES_INSURANCE"), "Insurance")
        self.assertEqual(default_category("GENERAL_SERVICES", "GENERAL_SERVICES_CHILDCARE"), "Childcare")

    def test_unmapped_primary_falls_back_to_uncategorized(self):
        self.assertEqual(default_category("SOME_FUTURE_PLAID_CATEGORY", None), "Uncategorized")

    def test_name_guess_used_only_when_plaid_gave_no_category_at_all(self):
        # Plaid didn't classify this one -- the merchant name alone is
        # enough to make a reasonable guess rather than leaving it
        # Uncategorized.
        self.assertEqual(default_category(None, None, "Stanford University Tuition"), "Education / College Fees")
        self.assertEqual(default_category(None, None, "United Airlines Flight 123"), "Travel")
        self.assertEqual(default_category(None, None, "Starbucks Coffee #4521"), "Food")

    def test_name_guess_is_not_consulted_when_plaid_already_classified_it(self):
        # Plaid's own classification always wins over a name guess, even
        # if the merchant name would have suggested something else.
        self.assertEqual(default_category("TRAVEL", "TRAVEL_FLIGHTS", "University Shuttle Co"), "Travel")

    def test_unmatched_name_still_falls_back_to_uncategorized(self):
        self.assertEqual(default_category(None, None, "XYZ1234 POS Purchase"), "Uncategorized")


if __name__ == "__main__":
    unittest.main()
