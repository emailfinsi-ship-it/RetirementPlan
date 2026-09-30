"""Pure helpers for turning Plaid's own personal_finance_category into
this program's transaction category/excluded-from-expense defaults --
shared between source.collector.sync (a brand-new transaction, first
sync) and source.common.db.transactions (resetting a manual override
back to Plaid's own classification), so both stay byte-for-byte the
same logic. Deliberately has no Plaid/db import of its own -- either
side can import this at module load time with zero import-cycle risk
(source.collector.sync already imports source.common.db, so db.
transactions importing back from sync would be circular).
"""

from __future__ import annotations

import re

# Plaid's Personal Finance Category taxonomy has ~16 top-level "primary"
# values; these two are the ones that mean the user moved their own
# money around rather than spent it -- a transfer between two of their
# own linked accounts (TRANSFER_IN/TRANSFER_OUT), in either direction.
# See https://plaid.com/documents/transactions-personal-finance-category-taxonomy.csv
_TRANSFER_PRIMARY_CATEGORIES = {"TRANSFER_IN", "TRANSFER_OUT"}

# A credit card bill payment shows up as its own "detailed" value nested
# under the LOAN_PAYMENTS primary category (e.g.
# "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT") -- checking the substring rather
# than an exact match is deliberate: it's the one LOAN_PAYMENTS variant
# that means "paying off a card whose purchases are already counted as
# spending on that card's own statement," so it's excluded here to avoid
# double-counting those same dollars once as a checking withdrawal and
# again as a credit card charge. A plain LOAN_PAYMENTS entry that isn't
# a credit card payment (e.g. a mortgage or auto loan installment) is
# NOT excluded -- this app doesn't otherwise track that payment against
# a liability balance the way it tracks a credit card's own charges, so
# it stays counted as real spending unless a person excludes it by hand.
_CREDIT_CARD_PAYMENT_MARKER = "CREDIT_CARD_PAYMENT"


def default_excluded_from_expense(primary: str | None, detailed: str | None) -> bool:
    """True for a transaction that looks like an internal transfer or a
    credit card bill payment -- see the two module-level comments above
    for exactly what that covers and why. This is only ever the
    *starting* value for a transaction's excluded_from_expense flag: the
    Real Expenditure page's bulk "Exclude"/"Include"/"Reset to automatic"
    actions can always override it by hand (see source.common.db.
    transactions.update_plaid_transaction_excluded), and an excluded
    transaction is still shown in the full transaction list, just left
    out of the expense totals -- never hidden."""
    primary = (primary or "").strip().upper()
    detailed = (detailed or "").strip().upper()
    if primary in _TRANSFER_PRIMARY_CATEGORIES:
        return True
    if _CREDIT_CARD_PAYMENT_MARKER in detailed:
        return True
    return False


# A short, curated list of broad buckets each Plaid `primary` personal_
# finance_category rolls up to by default. Replaces the old 1:1
# "prettify the detailed value" behavior, which produced a distinct
# category per fine-grained Plaid subcategory (e.g. "Food And Drink
# Coffee"/"Food And Drink Groceries"/"Food And Drink Restaurant" as
# three separate strings) -- that read as barely-categorized at all on
# the Real Expenditure charts, just dozens of near-duplicate slices.
# See https://plaid.com/documents/transactions-personal-finance-category-taxonomy.csv
# for Plaid's full primary/detailed taxonomy.
_BROAD_CATEGORY_BY_PRIMARY = {
    "INCOME": "Income",
    "TRANSFER_IN": "Transfer",
    "TRANSFER_OUT": "Transfer",
    "LOAN_PAYMENTS": "Loan Payments",
    "BANK_FEES": "Bank Fees",
    "ENTERTAINMENT": "Entertainment",
    "FOOD_AND_DRINK": "Food",
    "GENERAL_MERCHANDISE": "Shopping",
    "HOME_IMPROVEMENT": "Home Improvement",
    "MEDICAL": "Medical & Health",
    "PERSONAL_CARE": "Personal Care",
    "GENERAL_SERVICES": "General Services",
    "GOVERNMENT_AND_NON_PROFIT": "Government & Non-Profit",
    "TRANSPORTATION": "Transportation",
    "TRAVEL": "Travel",
    "RENT_AND_UTILITIES": "Housing & Utilities",
}

# A handful of `detailed` values whose own primary bucket above would be
# too broad to be useful on its own -- each is pulled into a more
# specific bucket instead of falling into its primary's default (e.g. a
# student loan payment reads as "Education / College Fees", not the
# generic "Loan Payments" every mortgage/auto-loan installment gets).
# Checked before the primary-level table above.
_BROAD_CATEGORY_DETAILED_OVERRIDES = {
    "LOAN_PAYMENTS_STUDENT_LOAN_PAYMENT": "Education / College Fees",
    "GENERAL_SERVICES_EDUCATION": "Education / College Fees",
    "GENERAL_SERVICES_INSURANCE": "Insurance",
    "GENERAL_SERVICES_CHILDCARE": "Childcare",
    "GENERAL_SERVICES_AUTOMOTIVE": "Transportation",
    "GOVERNMENT_AND_NON_PROFIT_DONATIONS": "Donations & Gifts",
    "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT": "Taxes",
}

# Keyword fallback for a transaction Plaid never classified at all (no
# primary/detailed, which does happen for some pending or oddly-coded
# transactions) -- a best-effort guess from the merchant/transaction
# name text, checked in order, first match wins. Deliberately short and
# conservative: a miss just falls through to "Uncategorized", same as
# before this existed.
_NAME_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("university", "college", "tuition", "campus", "student loan"), "Education / College Fees"),
    (("airline", "airlines", "airbnb", "hotel", "expedia", "delta air", "united air", "marriott", "hilton"), "Travel"),
    (("uber", "lyft", "shell", "chevron", "exxon", "gas station", "parking", "transit"), "Transportation"),
    (("netflix", "spotify", "hulu", "disney+", "movie", "cinema", "theatre"), "Entertainment"),
    (("amazon", "walmart", "target", "costco", "best buy"), "Shopping"),
    (("restaurant", "cafe", "coffee", "starbucks", "mcdonald", "grill", "diner"), "Food"),
    (("pharmacy", "clinic", "hospital", "doctor", "dental"), "Medical & Health"),
    (("insurance",), "Insurance"),
    (("rent", "landlord", "electric company", "utility", "utilities", "water bill"), "Housing & Utilities"),
)


# Primary categories whose own classification already means Plaid tied
# this transaction to a real kind of spending -- a negative (inbound)
# amount under one of these reads as a refund/return against that same
# kind of spending, not new income (e.g. an Amazon return lands back
# under GENERAL_MERCHANDISE, the same primary its original purchase
# used). Excludes INCOME (obviously already income) -- TRANSFER_IN/
# TRANSFER_OUT are handled separately below (is_real_income checks
# _TRANSFER_PRIMARY_CATEGORIES directly), since a transfer isn't a
# "real kind of spending" either, but it still isn't income even when a
# person manually un-excludes it from the expense total. See
# is_real_income() below.
_EXPENSE_PRIMARY_CATEGORIES = set(_BROAD_CATEGORY_BY_PRIMARY) - {"INCOME", "TRANSFER_IN", "TRANSFER_OUT"}


def is_real_income(
    *,
    primary: str | None,
    category: str | None,
    amount: float,
    excluded_from_expense: bool,
    category_edited_by_user: bool = False,
) -> bool:
    """True for a transaction that should count as *real income* on the
    Real Expenditure and Budget vs Actual pages -- broader than a plain
    `category == "Income"` check, so a paycheck-like deposit Plaid
    couldn't classify (no primary, or primary "OTHER") doesn't silently
    vanish into whatever expense-sounding category this module's own
    name-keyword fallback (_guess_category_from_name, right below)
    happened to guess for it from text in its description, with no
    regard for which way the money actually moved.

    Counts as income when either:
    - `category` is already exactly "Income" (Plaid's own INCOME
      primary, a user override, or a saved category rule all funnel
      here); or
    - `amount` is negative (Plaid's convention: money IN), `primary`
      isn't one of the two transfer primaries (an internal transfer is
      never income, however it's currently flagged), `primary` is
      anything other than a primary category Plaid itself tied to a
      real kind of spending (_EXPENSE_PRIMARY_CATEGORIES) -- that last
      case is a refund/return against that same spending, not income --
      AND, when a person has personally retyped this exact row's own
      category (`category_edited_by_user`), that category reads like an
      income label (contains "income", case-insensitively -- covers
      "Income" itself, "rental-income", "Rental Income -<property>",
      and the like).

    That last condition is the fix for a real, reported bug: Plaid
    sometimes gives a mortgage-account "principal payment" mirror
    transaction (or a refund/fee it can't otherwise classify) primary
    "OTHER" instead of the TRANSFER_IN it should have gotten -- with no
    real primary to go on, this function used to fall back to "inbound
    money with an uninformative primary must be income" unconditionally,
    which is right for a not-yet-reviewed deposit (the "mystery
    paycheck" case this whole OTHER fallback exists for -- see
    test_inbound_money_plaid_could_not_classify_counts_as_income) but
    wrong once a person has since typed a specific, clearly-not-income
    category onto that exact transaction by hand ("mortgage", "Food",
    "Bank Fees" are real examples that were wrongly counted as income
    before this check existed). A category set by a saved rule/
    recategorize pass rather than typed onto this specific row
    (category_edited_by_user=False) still gets the benefit of the doubt
    -- it's still effectively an unreviewed guess as far as this one
    transaction goes.

    An excluded transaction (an internal transfer or credit card
    payment -- see default_excluded_from_expense) is never income; it's
    not counted in any total on these pages at all."""
    if excluded_from_expense:
        return False
    category_text = (category or "").strip()
    if category_text == "Income":
        return True
    if amount >= 0:
        return False
    primary_key = (primary or "").strip().upper()
    if primary_key in _TRANSFER_PRIMARY_CATEGORIES:
        return False
    if primary_key in _EXPENSE_PRIMARY_CATEGORIES:
        return False
    if category_edited_by_user and "income" not in category_text.lower():
        return False
    return True


def _guess_category_from_name(name: str | None, extra_keywords: list[tuple[str, str]] | None = None) -> str | None:
    text = (name or "").strip().lower()
    if not text:
        return None
    # User-added keyword rules (source.common.db.category_rules) are
    # checked first, in the order they were added, so a person's own
    # rule always wins over a built-in one that might also match the
    # same text -- see default_category's own docstring for why this
    # function takes them as a parameter instead of importing the db
    # itself.
    for keyword, category in extra_keywords or ():
        if keyword in text:
            return category
    for keywords, category in _NAME_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category
    return None


# Matches the point in a raw transaction description where a stable
# payee name (e.g. "APPLE INC.") gives way to a transaction- or period-
# specific reference block -- an ACH descriptor's own "DES:"/"ID:"/
# "INDN:"/"CO ID:" tags, a SEC code like "PPD"/"CCD"/"WEB"/"TEL", a
# store-number-style "#1234", or a bare run of 4+ digits (an
# ambiguously-labeled reference number). See suggest_keyword_from_name.
_REFERENCE_BLOCK_PATTERN = re.compile(
    r"\b(?:DES|ID|INDN|CO\s*ID|SEC)\s*:|\bPPD\b|\bCCD\b|\bWEB\b|\bTEL\b|#\d|\d{4,}",
    re.IGNORECASE,
)


def suggest_keyword_from_name(name: str | None, merchant_name: str | None = None) -> str:
    """Best-effort, stable keyword for a category_rules 'keyword' rule,
    derived from one transaction's own merchant_name/name -- lets a
    person tag a single transaction as the example of a category and
    have every similar transaction (already synced, and any future one)
    picked up the same way, without having to type a keyword by hand on
    the Setup page (see source.common.db.transactions.apply_category_
    rule_from_transaction, which is what actually calls this).

    Prefers `merchant_name` (Plaid's own cleaned merchant field, e.g.
    "Starbucks") when present -- already stable across every occurrence
    of the same real-world payee. Falls back to `name` (the raw
    description) with everything from the first reference-block-looking
    token onward cut off (_REFERENCE_BLOCK_PATTERN above), since an ACH
    deposit's own description -- exactly the case this exists for, a
    paycheck-like deposit Plaid couldn't classify at all -- otherwise
    carries a transaction- or period-specific number that would stop
    two months of the very same paycheck from ever matching the same
    keyword. Returns "" (never None) when nothing usable is left, so a
    caller can treat a blank result as "couldn't derive one" without an
    extra None check."""
    merchant_name = (merchant_name or "").strip()
    if merchant_name:
        return merchant_name.lower()
    text = (name or "").strip()
    if not text:
        return ""
    match = _REFERENCE_BLOCK_PATTERN.search(text)
    stable = text[: match.start()] if match else text
    stable = stable.strip(" -:#.,")
    if len(stable) < 3:
        # The whole description was reference-y (or the match landed
        # right at the start) -- fall back to its first few words
        # instead of an unusably short or empty keyword.
        stable = " ".join(text.split()[:3])
    return stable.lower()


# The three kinds of rule source.common.db.category_rules stores --
# duplicated here (not imported from there) to keep this module's "no
# db import" guarantee (see module docstring): both sides just need to
# agree on the same three strings, and a db module importing a constant
# from this pure-helpers module is the direction that's actually safe.
RULE_TYPES = ("primary", "detailed", "keyword")


def list_built_in_rules() -> list[dict]:
    """This module's own hardcoded rollup rules, flattened into the same
    shape as source.common.db.category_rules.list_category_rules() rows
    (minus id/timestamps), purely for read-only display -- the Setup
    page's "Category rules" card shows these alongside a person's own
    saved overrides so it's clear what's already covered by default
    before adding a new rule. A keyword rule here shows its first keyword
    as a representative match_key with the rest appended to the category
    label, since the built-in list groups several keywords under one
    category (unlike a saved override, which is always one keyword per
    row) -- this function never needs to round-trip back into
    default_category, just to be readable on a page."""
    rules = []
    for key, category in _BROAD_CATEGORY_BY_PRIMARY.items():
        rules.append({"rule_type": "primary", "match_key": key, "category": category})
    for key, category in _BROAD_CATEGORY_DETAILED_OVERRIDES.items():
        rules.append({"rule_type": "detailed", "match_key": key, "category": category})
    for keywords, category in _NAME_KEYWORDS:
        rules.append({"rule_type": "keyword", "match_key": ", ".join(keywords), "category": category})
    return rules


def default_category(
    primary: str | None,
    detailed: str | None,
    name: str | None = None,
    overrides: dict | None = None,
) -> str:
    """A readable starting category from Plaid's own
    personal_finance_category, rolled up into a short list of broad
    buckets (see _BROAD_CATEGORY_BY_PRIMARY/_BROAD_CATEGORY_DETAILED_
    OVERRIDES above) rather than a distinct string per fine-grained
    Plaid subcategory. `name` (the transaction's own name/merchant_name)
    is only consulted when Plaid gave no personal_finance_category at
    all -- a best-effort keyword guess instead of an immediate
    "Uncategorized" -- and is optional so every existing caller that
    doesn't have it handy keeps working unchanged. Just the STARTING
    value shown in the Category column/datalist -- like every other
    category field in this app, it's free text with no fixed enum, so a
    person can retype it to anything via the Real Expenditure page's
    bulk-classify bar.

    `overrides`, when given, is source.common.db.category_rules.
    load_active_overrides()'s own shape: {"primary": {KEY: category},
    "detailed": {KEY: category}, "keywords": [(keyword, category), ...]}
    -- a person's own rules (Setup page's "Category rules" card), always
    checked BEFORE the matching built-in table/list below, so a custom
    rule always wins over a built-in one that would otherwise also
    match. Optional and defaults to none, so every existing caller that
    hasn't been taught about user overrides yet keeps working exactly as
    before."""
    overrides = overrides or {}
    override_primary = overrides.get("primary") or {}
    override_detailed = overrides.get("detailed") or {}
    override_keywords = overrides.get("keywords") or []

    primary_key = (primary or "").strip().upper()
    detailed_key = (detailed or "").strip().upper()
    if detailed_key in override_detailed:
        return override_detailed[detailed_key]
    if primary_key in override_primary:
        return override_primary[primary_key]
    if detailed_key in _BROAD_CATEGORY_DETAILED_OVERRIDES:
        return _BROAD_CATEGORY_DETAILED_OVERRIDES[detailed_key]
    if primary_key in _BROAD_CATEGORY_BY_PRIMARY:
        return _BROAD_CATEGORY_BY_PRIMARY[primary_key]
    guessed = _guess_category_from_name(name, override_keywords)
    if guessed:
        return guessed
    return "Uncategorized"
