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


def default_category(primary: str | None, detailed: str | None) -> str:
    """A readable starting category from Plaid's own
    personal_finance_category -- the `detailed` value
    ("FOOD_AND_DRINK_COFFEE") prettified into "Food And Drink Coffee"
    when present, falling back to `primary` prettified the same way,
    then "Uncategorized" if Plaid never classified this transaction at
    all. Just the STARTING value shown in the Category column/datalist
    -- like every other category field in this app, it's free text with
    no fixed enum, so a person can retype it to anything via the
    Real Expenditure page's bulk-classify bar."""
    raw = (detailed or primary or "").strip()
    if not raw:
        return "Uncategorized"
    return " ".join(word.capitalize() for word in raw.replace("_", " ").split())
