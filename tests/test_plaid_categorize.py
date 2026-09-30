import unittest

from source.common.plaid_categorize import (
    KEYWORD_MATCH_MODES,
    _keyword_rule_matches,
    default_category,
    default_excluded_from_expense,
    is_real_income,
    suggest_keyword_from_name,
)


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


class TestKeywordMatchModes(unittest.TestCase):
    """_keyword_rule_matches is the shared comparison every 'keyword'
    category_rule (source.common.db.category_rules) goes through --
    covers all four KEYWORD_MATCH_MODES directly, independent of
    default_category's own wiring (covered separately above)."""

    def test_exactly_four_modes_in_a_stable_order(self):
        # The Setup page's Match mode <select> is built directly from
        # this tuple (source.webapp.pages.setup) -- order is display
        # order, so a change here is a UI change too.
        self.assertEqual(KEYWORD_MATCH_MODES, ("contains", "starts_with", "ends_with", "regex"))

    def test_contains_matches_anywhere_in_the_text(self):
        self.assertTrue(_keyword_rule_matches("Starbucks Coffee #4521", "coffee", "contains"))
        self.assertFalse(_keyword_rule_matches("Starbucks Tea #4521", "coffee", "contains"))

    def test_starts_with_is_anchored_to_the_start(self):
        self.assertTrue(_keyword_rule_matches("Zelle payment from Jane", "zelle", "starts_with"))
        self.assertFalse(_keyword_rule_matches("Payment via Zelle", "zelle", "starts_with"))

    def test_ends_with_is_anchored_to_the_end(self):
        self.assertTrue(_keyword_rule_matches("Acme Corp Payroll", "payroll", "ends_with"))
        self.assertFalse(_keyword_rule_matches("Payroll Adjustment", "payroll", "ends_with"))

    def test_regex_searches_anywhere_and_is_case_insensitive(self):
        self.assertTrue(_keyword_rule_matches("AMZN Mktp US*1234", r"amzn\s*mktp", "regex"))
        # Anywhere in the text, not anchored, unless the pattern itself
        # anchors with ^/$.
        self.assertTrue(_keyword_rule_matches("MORTGAGE PRINCIPAL PMT", r"principal", "regex"))
        self.assertTrue(_keyword_rule_matches("MORTGAGE PRINCIPAL PMT", r"^mortgage", "regex"))
        self.assertTrue(_keyword_rule_matches("MORTGAGE PRINCIPAL PMT", r"pmt$", "regex"))
        self.assertFalse(_keyword_rule_matches("MORTGAGE PRINCIPAL PMT", r"^mortgage$", "regex"))

    def test_regex_with_a_bad_pattern_returns_false_instead_of_raising(self):
        self.assertFalse(_keyword_rule_matches("(unbalanced parens", "(unbalanced", "regex"))

    def test_every_mode_is_case_insensitive_on_both_sides(self):
        self.assertTrue(_keyword_rule_matches("STARBUCKS COFFEE", "coffee", "contains"))
        self.assertTrue(_keyword_rule_matches("starbucks coffee", "COFFEE", "contains"))
        self.assertTrue(_keyword_rule_matches("ZELLE PAYMENT", "zelle", "starts_with"))
        self.assertTrue(_keyword_rule_matches("acme payroll", "PAYROLL", "ends_with"))

    def test_unrecognized_match_mode_falls_back_to_contains(self):
        self.assertTrue(_keyword_rule_matches("Peloton Membership", "peloton", "some-future-mode"))
        self.assertFalse(_keyword_rule_matches("Soulcycle Membership", "peloton", "some-future-mode"))


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

    def test_override_with_no_matching_rule_behaves_like_no_override_at_all(self):
        self.assertEqual(
            default_category("FOOD_AND_DRINK", "FOOD_AND_DRINK_COFFEE", overrides={"primary": {}, "detailed": {}, "keywords": []}),
            "Food",
        )

    def test_primary_override_wins_over_the_built_in_default(self):
        overrides = {"primary": {"GENERAL_MERCHANDISE": "Custom Bucket"}, "detailed": {}, "keywords": []}
        self.assertEqual(default_category("GENERAL_MERCHANDISE", None, overrides=overrides), "Custom Bucket")

    def test_detailed_override_wins_over_both_the_built_in_detailed_and_primary_default(self):
        overrides = {"primary": {}, "detailed": {"FOOD_AND_DRINK_COFFEE": "Coffee Habit"}, "keywords": []}
        self.assertEqual(default_category("FOOD_AND_DRINK", "FOOD_AND_DRINK_COFFEE", overrides=overrides), "Coffee Habit")

    def test_override_detailed_wins_over_override_primary(self):
        overrides = {
            "primary": {"GENERAL_MERCHANDISE": "Shopping"},
            "detailed": {"GENERAL_MERCHANDISE_PET_SUPPLIES": "Pets"},
            "keywords": [],
        }
        self.assertEqual(
            default_category("GENERAL_MERCHANDISE", "GENERAL_MERCHANDISE_PET_SUPPLIES", overrides=overrides), "Pets",
        )

    def test_custom_keyword_rule_is_checked_before_the_built_in_keyword_list(self):
        overrides = {"primary": {}, "detailed": {}, "keywords": [("peloton", "Fitness", "contains")]}
        self.assertEqual(default_category(None, None, "Peloton Membership", overrides=overrides), "Fitness")

    def test_custom_keyword_rule_wins_over_a_built_in_keyword_match_on_the_same_text(self):
        # "starbucks" would otherwise match the built-in Food keyword list
        # -- a person's own rule for the same text always wins.
        overrides = {"primary": {}, "detailed": {}, "keywords": [("starbucks", "Work Perks", "contains")]}
        self.assertEqual(default_category(None, None, "Starbucks Coffee #4521", overrides=overrides), "Work Perks")

    def test_keyword_override_is_never_consulted_when_plaid_already_classified_it(self):
        overrides = {"primary": {}, "detailed": {}, "keywords": [("shuttle", "Custom Travel", "contains")]}
        self.assertEqual(default_category("TRAVEL", "TRAVEL_FLIGHTS", "University Shuttle Co", overrides=overrides), "Travel")

    def test_custom_keyword_rule_with_starts_with_match_mode(self):
        overrides = {"primary": {}, "detailed": {}, "keywords": [("zelle", "Transfer", "starts_with")]}
        self.assertEqual(default_category(None, None, "Zelle payment from Jane Doe", overrides=overrides), "Transfer")
        # Doesn't match when "zelle" isn't at the very start.
        self.assertEqual(default_category(None, None, "Payment via Zelle", overrides=overrides), "Uncategorized")

    def test_custom_keyword_rule_with_ends_with_match_mode(self):
        overrides = {"primary": {}, "detailed": {}, "keywords": [("corp payroll", "Salary", "ends_with")]}
        self.assertEqual(default_category(None, None, "Acme Corp Payroll", overrides=overrides), "Salary")
        self.assertEqual(default_category(None, None, "Acme Corp Payroll Adjustment", overrides=overrides), "Uncategorized")

    def test_custom_keyword_rule_with_regex_match_mode(self):
        overrides = {"primary": {}, "detailed": {}, "keywords": [(r"^amzn\s*mktp", "Shopping", "regex")]}
        self.assertEqual(default_category(None, None, "AMZN Mktp US*1234", overrides=overrides), "Shopping")
        # Doesn't match text the pattern isn't anchored to -- and this
        # text also has to avoid every OTHER built-in keyword fallback
        # (see _NAME_KEYWORDS) to actually prove the point.
        self.assertEqual(default_category(None, None, "Completely Unrelated Merchant Co", overrides=overrides), "Uncategorized")

    def test_regex_match_mode_is_case_insensitive(self):
        overrides = {"primary": {}, "detailed": {}, "keywords": [(r"MORTGAGE$", "Loan Payments", "regex")]}
        self.assertEqual(default_category(None, None, "principal pmt mortgage", overrides=overrides), "Loan Payments")

    def test_regex_match_mode_with_a_bad_pattern_never_matches_instead_of_raising(self):
        overrides = {"primary": {}, "detailed": {}, "keywords": [("(unbalanced", "Whatever", "regex")]}
        self.assertEqual(default_category(None, None, "(unbalanced parens", overrides=overrides), "Uncategorized")

    def test_unknown_match_mode_falls_back_to_contains(self):
        overrides = {"primary": {}, "detailed": {}, "keywords": [("peloton", "Fitness", "some-future-mode")]}
        self.assertEqual(default_category(None, None, "Peloton Membership", overrides=overrides), "Fitness")


class TestIsRealIncome(unittest.TestCase):
    def test_transaction_already_categorized_income_counts(self):
        self.assertTrue(is_real_income(
            primary="INCOME", category="Income", amount=-2000.0, excluded_from_expense=False,
        ))

    def test_positive_amount_categorized_income_still_counts(self):
        # Shouldn't happen from a real Plaid sync, but the category is
        # still the authoritative signal if it somehow does.
        self.assertTrue(is_real_income(
            primary="INCOME", category="Income", amount=2000.0, excluded_from_expense=False,
        ))

    def test_inbound_money_plaid_could_not_classify_counts_as_income(self):
        # The exact bug this exists to fix: a real paycheck-like deposit
        # that Plaid gave primary "OTHER" (no real classification), which
        # this app's own name-keyword fallback would otherwise guess into
        # an expense-sounding category (e.g. "Housing & Utilities") with
        # no regard for the fact that the amount is money coming IN.
        self.assertTrue(is_real_income(
            primary="OTHER", category="Housing & Utilities", amount=-10_150.0, excluded_from_expense=False,
        ))

    def test_inbound_money_with_no_primary_at_all_counts_as_income(self):
        self.assertTrue(is_real_income(
            primary=None, category="Uncategorized", amount=-500.0, excluded_from_expense=False,
        ))

    def test_refund_within_a_real_expense_category_does_not_count_as_income(self):
        # An Amazon return: Plaid ties it to the same primary
        # (GENERAL_MERCHANDISE) its original purchase used -- a refund
        # against real spending, not new income.
        self.assertFalse(is_real_income(
            primary="GENERAL_MERCHANDISE", category="Shopping", amount=-49.99, excluded_from_expense=False,
        ))

    def test_positive_amount_expense_does_not_count_as_income(self):
        self.assertFalse(is_real_income(
            primary="FOOD_AND_DRINK", category="Food", amount=42.50, excluded_from_expense=False,
        ))

    def test_excluded_transfer_never_counts_as_income_even_if_inbound(self):
        self.assertFalse(is_real_income(
            primary="TRANSFER_IN", category="Transfer", amount=-500.0, excluded_from_expense=True,
        ))

    def test_transfer_in_primary_that_was_manually_included_still_is_not_income(self):
        # TRANSFER_IN is a real primary Plaid classified -- even if a
        # person manually un-excludes it, it's a transfer between their
        # own accounts, not new income.
        self.assertFalse(is_real_income(
            primary="TRANSFER_IN", category="Transfer", amount=-500.0, excluded_from_expense=False,
        ))

    def test_manually_typed_non_income_category_on_an_unclassified_inbound_transaction_is_not_income(self):
        # The exact real, reported bug: Plaid gave a mortgage-account
        # "principal payment" mirror transaction primary "OTHER" instead
        # of the TRANSFER_IN it should have gotten, so it fell through to
        # the same OTHER-primary fallback the mystery-deposit case below
        # relies on -- but a person has since typed "mortgage" onto this
        # specific transaction by hand, and that's clearly not income.
        self.assertFalse(is_real_income(
            primary="OTHER", category="mortgage", amount=-142.23,
            excluded_from_expense=False, category_edited_by_user=True,
        ))

    def test_manually_typed_food_or_bank_fees_category_on_an_other_primary_transaction_is_not_income(self):
        # Two more real, reported cases: a refund/fee Plaid couldn't
        # classify (primary OTHER) that a person has since hand-labeled
        # with an ordinary expense category.
        self.assertFalse(is_real_income(
            primary="OTHER", category="Food", amount=-36.67,
            excluded_from_expense=False, category_edited_by_user=True,
        ))
        self.assertFalse(is_real_income(
            primary="OTHER", category="Bank Fees", amount=-8.03,
            excluded_from_expense=False, category_edited_by_user=True,
        ))

    def test_manually_typed_income_labeled_category_on_an_other_primary_transaction_still_counts(self):
        # The other side of the same fix: a person's own custom income
        # label (a rental property's own Zelle rent deposits, Plaid gave
        # primary OTHER since it's an unclassified Zelle transfer) must
        # keep counting as income after being hand-labeled -- the word
        # "income" in the category the person chose is what distinguishes
        # this from the "mortgage"/"Food"/"Bank Fees" cases above.
        for category in ("rental-income", "Rental Income -Southwood", "Rental Income -Muscat Dr", "INCOME (side gig)"):
            self.assertTrue(is_real_income(
                primary="OTHER", category=category, amount=-2000.0,
                excluded_from_expense=False, category_edited_by_user=True,
            ), f"expected {category!r} to still count as income")

    def test_unreviewed_category_on_an_other_primary_transaction_still_defaults_to_income(self):
        # Same "mortgage" category text as the false-positive test above,
        # but NOT manually edited onto this row (e.g. still whatever a
        # saved category rule or the built-in name-guess fallback most
        # recently assigned it) -- this is still effectively an
        # unreviewed guess for this specific transaction, so it keeps the
        # benefit of the doubt the OTHER-primary fallback exists for.
        self.assertTrue(is_real_income(
            primary="OTHER", category="mortgage", amount=-142.23,
            excluded_from_expense=False, category_edited_by_user=False,
        ))


class TestSuggestKeywordFromName(unittest.TestCase):
    def test_prefers_merchant_name_when_present(self):
        self.assertEqual(suggest_keyword_from_name("Starbucks Coffee #4521", "Starbucks"), "starbucks")

    def test_strips_a_store_number_from_the_raw_name_when_no_merchant_name(self):
        self.assertEqual(suggest_keyword_from_name("Starbucks Coffee #4521"), "starbucks coffee")

    def test_strips_an_ach_payroll_reference_block_so_two_months_of_the_same_deposit_match(self):
        # The exact real-world case this exists for -- Plaid's own ACH
        # descriptor packs a transaction/period-specific reference number
        # into the same string as the stable payee name.
        name = "APPLE INC. DES:PAYROLL ID:117316 INDN:XXXXX0358 CO ID:XXXXX04110 PPD"
        self.assertEqual(suggest_keyword_from_name(name), "apple inc")

    def test_two_different_months_of_the_same_paycheck_derive_the_same_keyword(self):
        month_one = "ACME UTILITY CO DES:PAYROLL ID:1000001"
        month_two = "ACME UTILITY CO DES:PAYROLL ID:1000002"
        self.assertEqual(suggest_keyword_from_name(month_one), suggest_keyword_from_name(month_two))

    def test_bare_run_of_digits_is_cut_off(self):
        self.assertEqual(suggest_keyword_from_name("XYZ CORP PAYROLL DEPOSIT 09052026"), "xyz corp payroll deposit")

    def test_falls_back_to_first_few_words_when_the_whole_name_is_reference_like(self):
        self.assertEqual(suggest_keyword_from_name("DES:PAYROLL ID:117316"), "des:payroll id:117316")

    def test_blank_name_and_merchant_name_returns_empty_string(self):
        self.assertEqual(suggest_keyword_from_name(None, None), "")
        self.assertEqual(suggest_keyword_from_name("", ""), "")

    def test_is_lowercased(self):
        self.assertEqual(suggest_keyword_from_name(None, "PELOTON"), "peloton")


if __name__ == "__main__":
    unittest.main()
