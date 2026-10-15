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

from source.common.db.category_rules import load_active_overrides, upsert_category_rule
from source.common.db.connection import _now, connect
from source.common.plaid_categorize import (
    INCOME_KIND_OPTIONS,
    _keyword_rule_matches,
    default_category,
    default_excluded_from_expense,
    suggest_keyword_from_name,
)


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
        overrides = load_active_overrides()
        now = _now()
        for row in rows:
            category = default_category(
                row["plaid_category_primary"], row["plaid_category_detailed"],
                row["merchant_name"] or row["name"], overrides=overrides,
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
    own bucket list (source.common.plaid_categorize), OR a person's own
    category_rules override added/edited/deleted on the Setup page, apply
    to transactions already sitting in the database, not just ones synced
    from here on. Called once from source.common.db._migrate_schema on
    every app startup (cheap and idempotent for a single-user database's
    transaction volume) AND right after any category_rules change (see
    dashboard._handle_category_rule_save/_delete), so a person never has
    to do anything to pick up a broader/renamed category bucket. A
    manually-set category is never touched -- same protection
    update_plaid_transaction_category always gets. Returns how many rows
    were actually changed."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT transaction_id, category, plaid_category_primary, plaid_category_detailed, merchant_name, name "
            "FROM plaid_transactions WHERE category_edited_by_user = 0"
        ).fetchall()
        overrides = load_active_overrides()
        now = _now()
        changed = 0
        for row in rows:
            new_category = default_category(
                row["plaid_category_primary"], row["plaid_category_detailed"],
                row["merchant_name"] or row["name"], overrides=overrides,
            )
            if new_category != row["category"]:
                conn.execute(
                    "UPDATE plaid_transactions SET category = ?, updated_at = ? WHERE transaction_id = ?",
                    (new_category, now, row["transaction_id"]),
                )
                changed += 1
        return changed


def apply_category_rule_from_transaction(transaction_id: str) -> dict:
    """Turns one transaction into a reusable keyword rule for every
    similar transaction, past and future -- backs the Real Expenditure
    page's per-row "Categorize similar" action (dashboard._handle_
    apply_category_rule_from_transaction), for exactly the case this
    program's own income-capture bug came from: a paycheck-like deposit
    Plaid gave no real classification for, so its Category is whatever
    a name-only guess produced, and every other month's copy of that
    same deposit needs the same fix, not just this one.

    Uses THIS transaction's own already-set Category (whatever it is --
    typically just retyped via the bulk-classify bar right before this
    is called) as the category to propagate, and derives a stable
    keyword from its own merchant_name/name via plaid_categorize.
    suggest_keyword_from_name rather than asking a person to type one
    by hand -- the whole point of "show it one example" is not having
    to. Saves the rule (source.common.db.category_rules.
    upsert_category_rule) and immediately re-runs recategorize_all_
    transactions() so every other not-manually-edited transaction
    already in the database that matches picks up the same category
    right away, not just ones synced from here on (same as saving a
    rule by hand on the Setup page).

    Returns {"keyword": ..., "category": ..., "recategorized": count}.
    Raises ValueError if no transaction with this id exists, or if no
    usable keyword could be derived from it (a blank name AND merchant_
    name -- very rare for a real synced transaction)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT category, merchant_name, name FROM plaid_transactions WHERE transaction_id = ?",
            (transaction_id,),
        ).fetchone()
    if not row:
        raise ValueError(f"No transaction found with id '{transaction_id}'.")
    keyword = suggest_keyword_from_name(row["name"], row["merchant_name"])
    if not keyword:
        raise ValueError("Couldn't find enough text in this transaction's description to build a keyword from.")
    upsert_category_rule(rule_type="keyword", match_key=keyword, category=row["category"])
    changed = recategorize_all_transactions()
    return {"keyword": keyword, "category": row["category"], "recategorized": changed}


def apply_category_rule(rule_id: int) -> dict:
    """Force-applies ONE saved category_rules row to every transaction it
    matches, INCLUDING ones a person already hand-edited (category_
    edited_by_user=1). The Setup page's "Category rules" card already
    auto-applies a saved rule to every transaction that ISN'T hand-edited
    the moment it's saved (see recategorize_all_transactions, called
    right after every save/update/delete) -- deliberately conservative,
    so tweaking a rule's keyword never silently reverts someone's own
    unrelated manual categorization elsewhere. This is the explicit,
    opt-in escape hatch for the opposite real case: a person typed a
    category onto a transaction by hand (e.g. "salary") well before a
    matching rule existed, so the automatic pass skips that row forever
    -- "Apply" on the Setup page calls this to retroactively bring
    exactly THIS rule's own matches into line, and nothing else.

    Matches transactions the same way plaid_categorize.default_category
    would for this rule's own rule_type: a 'keyword' rule against each
    transaction's merchant_name (falling back to name), via plaid_
    categorize._keyword_rule_matches (same match_mode semantics as
    everywhere else this rule is used); a 'primary'/'detailed' rule
    against plaid_category_primary/plaid_category_detailed, exact and
    case-insensitive.

    For every matched transaction: sets category to this rule's own
    category and resets category_edited_by_user back to 0 (once a rule
    has been explicitly applied to a row, that row is rule-governed
    again -- a future sync or recategorize_all_transactions pass keeps
    it in sync with the rule from here on, same as any other rule-
    matched row). ALSO sets income_kind_override (plaid_categorize.
    is_real_income's own explicit override) to this rule's own `kind`
    ('', 'income', or 'expense') on every matched row, independent of
    whether its category text actually changed -- this is what makes a
    manually-retyped category that IS income but doesn't contain the
    word "income" (the exact case income_kind_override exists for)
    actually count once its rule says so, without a separate per-
    transaction "Mark as income" click for every matching row. A rule
    saved with kind="" clears income_kind_override back to "" (auto-
    detect) on every row it matches -- flipping a rule's Kind back to
    Auto and clicking Apply again undoes a previous income/expense
    designation the same way.

    Returns {"matched": <rows this rule's own match criteria matched>,
    "recategorized": <rows whose category or category_edited_by_user
    flag actually changed>, "kind_applied": <rows whose income_kind_
    override actually changed>}. Raises ValueError if no rule exists
    with this id."""
    with connect() as conn:
        rule = conn.execute("SELECT * FROM category_rules WHERE id = ?", (rule_id,)).fetchone()
        if not rule:
            raise ValueError(f"No category rule found with id {rule_id}.")
        rule_type = rule["rule_type"]
        match_key = rule["match_key"]
        match_mode = rule["match_mode"]
        category = rule["category"]
        kind = rule["kind"] or ""
        if kind not in INCOME_KIND_OPTIONS:
            kind = ""
        if rule_type == "keyword":
            rows = conn.execute(
                "SELECT transaction_id, name, merchant_name, category, category_edited_by_user, "
                "income_kind_override FROM plaid_transactions"
            ).fetchall()
            matched = [
                row for row in rows
                if _keyword_rule_matches(row["merchant_name"] or row["name"] or "", match_key, match_mode)
            ]
        else:
            column = "plaid_category_primary" if rule_type == "primary" else "plaid_category_detailed"
            rows = conn.execute(
                f"SELECT transaction_id, category, category_edited_by_user, income_kind_override, "
                f"{column} AS match_col FROM plaid_transactions"
            ).fetchall()
            matched = [row for row in rows if (row["match_col"] or "").strip().upper() == match_key]
        now = _now()
        recategorized = 0
        kind_applied = 0
        for row in matched:
            if row["category"] != category or row["category_edited_by_user"]:
                conn.execute(
                    "UPDATE plaid_transactions SET category = ?, category_edited_by_user = 0, updated_at = ? "
                    "WHERE transaction_id = ?",
                    (category, now, row["transaction_id"]),
                )
                recategorized += 1
            if row["income_kind_override"] != kind:
                conn.execute(
                    "UPDATE plaid_transactions SET income_kind_override = ?, updated_at = ? WHERE transaction_id = ?",
                    (kind, now, row["transaction_id"]),
                )
                kind_applied += 1
        return {"matched": len(matched), "recategorized": recategorized, "kind_applied": kind_applied}


def apply_all_category_rules() -> dict:
    """Force-applies EVERY saved category rule (see apply_category_rule, which
    this just loops over) -- the Setup page's single "Apply all rules"
    button, instead of clicking each row's own Apply in turn. Rules are
    applied lowest-precedence first so that where two rules match the same
    transaction the one a normal categorization pass would pick wins
    (plaid_categorize.default_category checks a Plaid subcategory rule, then
    a Plaid category rule, then keyword rules in id order): keyword rules by
    id DESCENDING, then category rules, then subcategory rules.

    Returns {"rules": <rules applied>, "recategorized": <total category
    updates>, "kind_applied": <total income/expense updates>} -- the two
    counts are summed across rules, so a transaction a second rule changed
    again counts twice."""
    from source.common.db.category_rules import list_category_rules

    rules = list_category_rules()
    order = {"keyword": 0, "primary": 1, "detailed": 2}
    rules.sort(key=lambda r: (order.get(r["rule_type"], 0), -r["id"] if r["rule_type"] == "keyword" else r["id"]))
    recategorized = 0
    kind_applied = 0
    for rule in rules:
        result = apply_category_rule(rule["id"])
        recategorized += result["recategorized"]
        kind_applied += result["kind_applied"]
    return {"rules": len(rules), "recategorized": recategorized, "kind_applied": kind_applied}


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



def update_plaid_transaction_income_kind(transaction_ids: list[str], kind: str) -> int:
    """Bulk "Mark as income" / "Mark as expense" / "Auto-detect" -- sets
    (or clears, for kind="") plaid_transactions.income_kind_override,
    which plaid_categorize.is_real_income() checks ahead of its own
    text-based heuristics (see that function's own docstring on
    income_kind_override for why this exists: a manually-retyped
    category that IS income but doesn't literally contain the word
    "income" -- "salary", "Rental-mp", "tax-refund" were real examples --
    was otherwise falling out of "real income" with no text-matching fix
    that wouldn't just trade one false negative for a different one).
    Unlike category/excluded_from_expense there's no separate "_edited_
    by_user" companion flag here: the override column IS the "has a
    person set this" signal, and '' always means "use the heuristic,"
    so there's nothing a resync could clobber by overwriting a default.
    Backs the Real Expenditure page's bulk-classify bar. Returns how
    many rows were updated. Raises ValueError for an unknown kind."""
    if kind not in INCOME_KIND_OPTIONS:
        raise ValueError(f"Unknown income kind '{kind}' -- expected one of {INCOME_KIND_OPTIONS!r}.")
    if not transaction_ids:
        return 0
    with connect() as conn:
        placeholders = ", ".join("?" for _ in transaction_ids)
        cur = conn.execute(
            f"UPDATE plaid_transactions SET income_kind_override = ?, updated_at = ? "
            f"WHERE transaction_id IN ({placeholders})",
            [kind, _now(), *transaction_ids],
        )
        return cur.rowcount



def get_transactions_cursor(item_key: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT transactions_cursor FROM plaid_items WHERE item_key = ?", (item_key,)
        ).fetchone()
        return row["transactions_cursor"] if row else None



def set_transactions_cursor(item_key: str, cursor: str | None) -> None:
    with connect() as conn:
        conn.execute("UPDATE plaid_items SET transactions_cursor = ? WHERE item_key = ?", (cursor, item_key))
