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

from source.common.db.connection import _now, connect
from source.common.plaid_categorize import RULE_TYPES


def list_category_rules(rule_type: str | None = None) -> list[dict]:
    with connect() as conn:
        if rule_type:
            rows = conn.execute(
                "SELECT * FROM category_rules WHERE rule_type = ? ORDER BY id", (rule_type,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM category_rules ORDER BY rule_type, id").fetchall()
        return [dict(r) for r in rows]


def upsert_category_rule(*, rule_type: str, match_key: str, category: str) -> int:
    """Adds a new rule, or replaces the category on an existing one for
    the same (rule_type, match_key) pair (case-insensitive on match_key
    for 'primary'/'detailed', matching how Plaid's own values are always
    upper-cased before comparing -- see plaid_categorize.default_category
    -- and lower-cased for 'keyword', matching the substring search
    there). Returns the rule's id."""
    rule_type = (rule_type or "").strip().lower()
    if rule_type not in RULE_TYPES:
        raise ValueError(f"Unknown rule_type '{rule_type}'. Expected one of: {', '.join(RULE_TYPES)}.")
    match_key = (match_key or "").strip()
    if not match_key:
        raise ValueError("A match value is required.")
    category = (category or "").strip()
    if not category:
        raise ValueError("A category is required.")
    normalized_key = match_key.lower() if rule_type == "keyword" else match_key.upper()
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO category_rules (rule_type, match_key, category, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(rule_type, match_key) DO UPDATE SET
                category = excluded.category, updated_at = excluded.updated_at
            """,
            (rule_type, normalized_key, category, now, now),
        )
        row = conn.execute(
            "SELECT id FROM category_rules WHERE rule_type = ? AND match_key = ?",
            (rule_type, normalized_key),
        ).fetchone()
        return row["id"]


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
    keywords: list[tuple[str, str]] = []
    for row in list_category_rules():
        if row["rule_type"] == "primary":
            primary[row["match_key"]] = row["category"]
        elif row["rule_type"] == "detailed":
            detailed[row["match_key"]] = row["category"]
        elif row["rule_type"] == "keyword":
            keywords.append((row["match_key"], row["category"]))
    return {"primary": primary, "detailed": detailed, "keywords": keywords}
