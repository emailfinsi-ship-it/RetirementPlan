"""Plaid-pulled spend transactions (credit card, checking, and
investment-account cash activity) -- powers the Real Expenditure tab
(source.webapp.pages.real_expenditure). Populated by
source.collector.sync._sync_transactions_for_item's cursor-based
incremental pull from Plaid's transactions_sync endpoint.

Every transaction starts out auto-categorized from Plaid's own
personal_finance_category, and auto-excluded from the expense total if
it looks like an internal transfer or a credit card bill payment (see
source.common.plaid_categorize for exactly how). Both of those are just
*defaults* -- category_edited_by_user/excluded_edited_by_user record
once a person has overridden either one by hand (via the Real
Expenditure page's bulk-classify bars), so a later resync (Plaid
re-sending the same transaction_id as "modified", e.g. pending ->
posted) always refreshes Plaid's own fields but never clobbers a
manual edit.
"""

from __future__ import annotations

from source.common.db.connection import _now, connect
from source.common.plaid_categorize import default_category, default_excluded_from_expense


def upsert_plaid_transaction(*, item_key: str, transaction: dict) -> None:
    """transaction is the flat dict source.collector.sync builds per Plaid
    Transaction (see sync._transaction_to_dict) -- includes both Plaid's
    own fields and this row's *default* category/excluded_from_expense,
    computed fresh from whatever Plaid returned this time. On a
    brand-new transaction_id those defaults are simply what gets stored.
    On an existing one, Plaid-sourced fields (amount/date/name/pending/
    plaid_category_*) always refresh to Plaid's latest, but category/
    excluded_from_expense only take the new default when this row's own
    category_edited_by_user/excluded_edited_by_user flag is still unset
    -- otherwise the existing (manually edited) value is kept as-is."""
    with connect() as conn:
        existing = conn.execute(
            "SELECT category, category_edited_by_user, excluded_from_expense, excluded_edited_by_user "
            "FROM plaid_transactions WHERE transaction_id = ?",
            (transaction["transaction_id"],),
        ).fetchone()
        category = transaction["category"]
        excluded_from_expense = transaction["excluded_from_expense"]
        category_edited_by_user = 0
        excluded_edited_by_user = 0
        if existing:
            category_edited_by_user = existing["category_edited_by_user"]
            excluded_edited_by_user = existing["excluded_edited_by_user"]
            if category_edited_by_user:
                category = existing["category"]
            if excluded_edited_by_user:
                excluded_from_expense = bool(existing["excluded_from_expense"])
        conn.execute(
            """
            INSERT INTO plaid_transactions (
                transaction_id, item_key, account_id, date, amount, iso_currency_code, name, merchant_name,
                pending, plaid_category_primary, plaid_category_detailed, category, category_edited_by_user,
                excluded_from_expense, excluded_edited_by_user, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(transaction_id) DO UPDATE SET
                item_key=excluded.item_key, account_id=excluded.account_id, date=excluded.date,
                amount=excluded.amount, iso_currency_code=excluded.iso_currency_code, name=excluded.name,
                merchant_name=excluded.merchant_name, pending=excluded.pending,
                plaid_category_primary=excluded.plaid_category_primary,
                plaid_category_detailed=excluded.plaid_category_detailed,
                category=excluded.category, excluded_from_expense=excluded.excluded_from_expense,
                updated_at=excluded.updated_at
            """,
            (
                transaction["transaction_id"], item_key, transaction["account_id"], transaction["date"],
                transaction["amount"], transaction.get("iso_currency_code"), transaction.get("name") or "",
                transaction.get("merchant_name"), 1 if transaction.get("pending") else 0,
                transaction.get("plaid_category_primary"), transaction.get("plaid_category_detailed"),
                category, category_edited_by_user, 1 if excluded_from_expense else 0, excluded_edited_by_user,
                _now(),
            ),
        )



def delete_plaid_transactions(transaction_ids: list[str]) -> int:
    """Removes transactions Plaid itself reported as gone (transactions_
    sync's own "removed" list -- a voided pending charge, a since-
    reversed transaction, etc). Never fired for a person's own delete
    action -- a row here isn't independently owned the way a manual
    Asset/Expense line item is, Plaid stays the source of truth for
    which transactions exist at all, so the Real Expenditure page has no
    per-row/bulk delete of its own."""
    if not transaction_ids:
        return 0
    with connect() as conn:
        placeholders = ", ".join("?" for _ in transaction_ids)
        cur = conn.execute(
            f"DELETE FROM plaid_transactions WHERE transaction_id IN ({placeholders})",
            list(transaction_ids),
        )
        return cur.rowcount



def list_plaid_transactions() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM plaid_transactions ORDER BY date DESC, transaction_id").fetchall()
        return [dict(r) for r in rows]



def update_plaid_transaction_category(transaction_ids: list[str], category: str) -> int:
    """Bulk "Set category" -- marks category_edited_by_user so a later
    resync never overwrites it. Backs the Real Expenditure page's
    checkbox + bulk-classify bar (same pattern as the Linked Positions
    page's industry/sector classifier -- see dashboard._handle_classify_
    industry). Returns how many rows were updated."""
    if not transaction_ids:
        return 0
    with connect() as conn:
        placeholders = ", ".join("?" for _ in transaction_ids)
        cur = conn.execute(
            f"UPDATE plaid_transactions SET category = ?, category_edited_by_user = 1, updated_at = ? "
            f"WHERE transaction_id IN ({placeholders})",
            [category, _now(), *transaction_ids],
        )
        return cur.rowcount



def clear_plaid_transaction_category_overrides(transaction_ids: list[str]) -> int:
    """Undoes update_plaid_transaction_category -- resets `category` back
    to whatever Plaid's own classification says (recomputed from this
    row's own plaid_category_primary/detailed via the exact same
    default_category helper a brand-new transaction gets) and clears
    category_edited_by_user, so a future resync keeps it in sync with
    Plaid again from here on. Backs the Real Expenditure page's "Reset
    category" bulk action. Returns how many rows were updated."""
    if not transaction_ids:
        return 0
    with connect() as conn:
        placeholders = ", ".join("?" for _ in transaction_ids)
        rows = conn.execute(
            f"SELECT transaction_id, plaid_category_primary, plaid_category_detailed, merchant_name, name "
            f"FROM plaid_transactions WHERE transaction_id IN ({placeholders})",
            list(transaction_ids),
        ).fetchall()
        now = _now()
        for row in rows:
            category = default_category(
                row["plaid_category_primary"], row["plaid_category_detailed"],
                row["merchant_name"] or row["name"],
            )
            conn.execute(
                "UPDATE plaid_transactions SET category = ?, category_edited_by_user = 0, updated_at = ? "
                "WHERE transaction_id = ?",
                (category, now, row["transaction_id"]),
            )
        return len(rows)


def recategorize_all_transactions() -> int:
    """Re-runs default_category() over every transaction that hasn't been
    manually re-labeled (category_edited_by_user = 0), using each row's
    own already-stored plaid_category_primary/detailed/name -- no Plaid
    call involved. This is what lets a change to default_category()'s
    own bucket list (source.common.plaid_categorize) apply to
    transactions already sitting in the database, not just ones synced
    from here on; called once from source.common.db._migrate_schema on
    every app startup (cheap and idempotent for a single-user database's
    transaction volume), so a person never has to do anything to pick up
    a broader/renamed category bucket. A manually-set category is never
    touched -- same protection update_plaid_transaction_category always
    gets. Returns how many rows were actually changed."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT transaction_id, category, plaid_category_primary, plaid_category_detailed, merchant_name, name "
            "FROM plaid_transactions WHERE category_edited_by_user = 0"
        ).fetchall()
        now = _now()
        changed = 0
        for row in rows:
            new_category = default_category(
                row["plaid_category_primary"], row["plaid_category_detailed"],
                row["merchant_name"] or row["name"],
            )
            if new_category != row["category"]:
                conn.execute(
                    "UPDATE plaid_transactions SET category = ?, updated_at = ? WHERE transaction_id = ?",
                    (new_category, now, row["transaction_id"]),
                )
                changed += 1
        return changed



def update_plaid_transaction_excluded(transaction_ids: list[str], excluded: bool) -> int:
    """Bulk "Exclude from total"/"Include in total" -- marks
    excluded_edited_by_user so a later resync never overrides a manual
    correction to Plaid's own transfer/credit-card-payment auto-tagging
    (source.common.plaid_categorize.default_excluded_from_expense).
    Returns how many rows were updated."""
    if not transaction_ids:
        return 0
    with connect() as conn:
        placeholders = ", ".join("?" for _ in transaction_ids)
        cur = conn.execute(
            f"UPDATE plaid_transactions SET excluded_from_expense = ?, excluded_edited_by_user = 1, updated_at = ? "
            f"WHERE transaction_id IN ({placeholders})",
            [1 if excluded else 0, _now(), *transaction_ids],
        )
        return cur.rowcount



def clear_plaid_transaction_excluded_overrides(transaction_ids: list[str]) -> int:
    """Undoes update_plaid_transaction_excluded -- resets
    excluded_from_expense back to Plaid's own auto-tagging heuristic
    (recomputed from this row's plaid_category_primary/detailed) and
    clears excluded_edited_by_user. Backs the Real Expenditure page's
    "Reset to automatic" bulk action. Returns how many rows were
    updated."""
    if not transaction_ids:
        return 0
    with connect() as conn:
        placeholders = ", ".join("?" for _ in transaction_ids)
        rows = conn.execute(
            f"SELECT transaction_id, plaid_category_primary, plaid_category_detailed "
            f"FROM plaid_transactions WHERE transaction_id IN ({placeholders})",
            list(transaction_ids),
        ).fetchall()
        now = _now()
        for row in rows:
            excluded = default_excluded_from_expense(row["plaid_category_primary"], row["plaid_category_detailed"])
            conn.execute(
                "UPDATE plaid_transactions SET excluded_from_expense = ?, excluded_edited_by_user = 0, updated_at = ? "
                "WHERE transaction_id = ?",
                (1 if excluded else 0, now, row["transaction_id"]),
            )
        return len(rows)



def get_transactions_cursor(item_key: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT transactions_cursor FROM plaid_items WHERE item_key = ?", (item_key,)
        ).fetchone()
        return row["transactions_cursor"] if row else None



def set_transactions_cursor(item_key: str, cursor: str | None) -> None:
    with connect() as conn:
        conn.execute("UPDATE plaid_items SET transactions_cursor = ? WHERE item_key = ?", (cursor, item_key))
