"""User-editable overrides on top of source.common.plaid_categorize's
hardcoded category-rollup defaults -- see the category_rules table's own
comment in schema.py for the full "why" and exactly what each rule_type
means. This module is just CRUD over that table; the actual override
logic (a DB row always wins over the matching built-in default) lives in
source.common.plaid_categorize.default_category via the `overrides` dict
load_active_overrides() below builds -- kept there, not here, so that
module stays a pure, db-free set of helpers (see its own docstring).
"""

from __future__ import annotations

import sqlite3

from source.common.db.connection import _now, connect
from source.common.plaid_categorize import KEYWORD_MATCH_MODES, RULE_TYPES


def list_category_rules(rule_type: str | None = None) -> list[dict]:
    with connect() as conn:
        if rule_type:
            rows = conn.execute(
                "SELECT * FROM category_rules WHERE rule_type = ? ORDER BY id", (rule_type,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM category_rules ORDER BY rule_type, id").fetchall()
        return [dict(r) for r in rows]


def _normalize_rule(*, rule_type: str, match_key: str, category: str, match_mode: str) -> tuple[str, str, str, str]:
    """Shared validation/normalization for upsert_category_rule and
    update_category_rule below -- returns (rule_type, match_key,
    match_mode, category), trimmed and cased exactly how plaid_
    categorize compares them at match time. Raises ValueError for
    anything a person could type wrong on the Setup page's form (an
    empty required field, or an unrecognized rule_type/match_mode)."""
    rule_type = (rule_type or "").strip().lower()
    if rule_type not in RULE_TYPES:
        raise ValueError(f"Unknown rule_type '{rule_type}'. Expected one of: {', '.join(RULE_TYPES)}.")
    match_key = (match_key or "").strip()
    if not match_key:
        raise ValueError("A match value is required.")
    category = (category or "").strip()
    if not category:
        raise ValueError("A category is required.")
    if rule_type == "keyword":
        match_mode = (match_mode or "contains").strip().lower()
        if match_mode not in KEYWORD_MATCH_MODES:
            raise ValueError(f"Unknown match_mode '{match_mode}'. Expected one of: {', '.join(KEYWORD_MATCH_MODES)}.")
        # "regex" keeps match_key exactly as typed -- a pattern's own
        # case sometimes matters syntactically (e.g. a named group), and
        # plaid_categorize._keyword_rule_matches already applies
        # re.IGNORECASE at match time regardless. Every other keyword
        # mode stays plain lowercase text, same as every rule saved
        # before match_mode existed.
        normalized_key = match_key if match_mode == "regex" else match_key.lower()
    else:
        # A 'primary'/'detailed' rule is always an exact, case-
        # insensitive match on Plaid's own value -- match_mode doesn't
        # mean anything for these; "exact" is just a stable, readable
        # constant so every row in the table has *some* value.
        match_mode = "exact"
        normalized_key = match_key.upper()
    return rule_type, normalized_key, match_mode, category


def upsert_category_rule(*, rule_type: str, match_key: str, category: str, match_mode: str = "contains") -> int:
    """Adds a new rule, or replaces the match_mode/category on an
    existing one for the same (rule_type, match_key) pair. `match_mode`
    (one of plaid_categorize.KEYWORD_MATCH_MODES -- "contains" is the
    original, and still the default, behavior) only means anything for
    rule_type="keyword"; it's ignored (stored as "exact") for
    "primary"/"detailed" rules, which are always an exact match on
    Plaid's own value. Returns the rule's id.

    Identifies a rule purely by (rule_type, match_key) -- saving with a
    DIFFERENT match_key never renames an existing row, it adds a new
    one; see update_category_rule below for a true in-place edit that
    can also change match_key/rule_type on an already-saved rule."""
    rule_type, normalized_key, match_mode, category = _normalize_rule(
        rule_type=rule_type, match_key=match_key, category=category, match_mode=match_mode,
    )
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO category_rules (rule_type, match_key, match_mode, category, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_type, match_key) DO UPDATE SET
                match_mode = excluded.match_mode, category = excluded.category, updated_at = excluded.updated_at
            """,
            (rule_type, normalized_key, match_mode, category, now, now),
        )
        row = conn.execute(
            "SELECT id FROM category_rules WHERE rule_type = ? AND match_key = ?",
            (rule_type, normalized_key),
        ).fetchone()
        return row["id"]


def update_category_rule(
    rule_id: int, *, rule_type: str, match_key: str, category: str, match_mode: str = "contains",
) -> None:
    """True in-place edit of an already-saved rule, by its own id --
    unlike upsert_category_rule (which identifies a rule by its
    (rule_type, match_key) pair, so retyping match_key there just adds a
    second row rather than renaming the first), this updates the SAME
    row no matter what about it changes. Backs the Setup page's
    "Category rules" card once a rule is editable in place (see
    dashboard.py's /api/category-rule/update). Raises ValueError for the
    same bad input upsert_category_rule rejects, and also if the edited
    (rule_type, match_key) pair would collide with a DIFFERENT existing
    rule, or if rule_id doesn't exist."""
    rule_type, normalized_key, match_mode, category = _normalize_rule(
        rule_type=rule_type, match_key=match_key, category=category, match_mode=match_mode,
    )
    now = _now()
    with connect() as conn:
        try:
            cur = conn.execute(
                "UPDATE category_rules SET rule_type = ?, match_key = ?, match_mode = ?, category = ?, "
                "updated_at = ? WHERE id = ?",
                (rule_type, normalized_key, match_mode, category, now, rule_id),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"A rule for {rule_type} '{normalized_key}' already exists.")
        if cur.rowcount == 0:
            raise ValueError(f"No category rule found with id {rule_id}.")


def delete_category_rule(rule_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
        return cur.rowcount > 0


def load_active_overrides() -> dict:
    """The current set of user overrides, shaped exactly how
    plaid_categorize.default_category's `overrides` parameter expects --
    see that function's docstring. Call once per batch of transactions
    (a sync pass, a bulk reset, recategorize_all_transactions) rather
    than once per transaction; it's a handful of rows for a personal
    single-user database, but there's no reason to re-query per row."""
    primary: dict[str, str] = {}
    detailed: dict[str, str] = {}
    keywords: list[tuple[str, str, str]] = []
    for row in list_category_rules():
        if row["rule_type"] == "primary":
            primary[row["match_key"]] = row["category"]
        elif row["rule_type"] == "detailed":
            detailed[row["match_key"]] = row["category"]
        elif row["rule_type"] == "keyword":
            keywords.append((row["match_key"], row["category"], row["match_mode"]))
    return {"primary": primary, "detailed": detailed, "keywords": keywords}
