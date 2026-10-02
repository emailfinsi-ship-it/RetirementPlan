"""Additive, idempotent column migrations for a database created before
a column existed -- schema.SCHEMA's CREATE TABLE IF NOT EXISTS only
covers a brand-new database, so an already-existing one needs an
explicit ALTER TABLE the first time this runs against it. Safe to call
on every startup (see connection... actually __init__.init_db): each
ALTER TABLE only fires if the column is still missing.
"""

from __future__ import annotations


def _migrate_schema(conn) -> None:
    """Additive, idempotent column migrations for databases created before
    a column existed -- CREATE TABLE IF NOT EXISTS in SCHEMA above only
    covers a brand-new database, so an already-existing one needs an
    explicit ALTER TABLE the first time this runs against it. Safe to
    call on every startup: each ALTER TABLE only fires if the column is
    still missing."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(assets)").fetchall()}
    if "linked_account_id" not in existing:
        conn.execute("ALTER TABLE assets ADD COLUMN linked_account_id TEXT")
    existing_re = {row["name"] for row in conn.execute("PRAGMA table_info(real_estate)").fetchall()}
    if "linked_account_id" not in existing_re:
        conn.execute("ALTER TABLE real_estate ADD COLUMN linked_account_id TEXT")
    if "annual_income" not in existing_re:
        conn.execute("ALTER TABLE real_estate ADD COLUMN annual_income REAL NOT NULL DEFAULT 0")
    existing_pa = {row["name"] for row in conn.execute("PRAGMA table_info(plaid_accounts)").fetchall()}
    if "account_number" not in existing_pa:
        conn.execute("ALTER TABLE plaid_accounts ADD COLUMN account_number TEXT")
    if "routing_number" not in existing_pa:
        conn.execute("ALTER TABLE plaid_accounts ADD COLUMN routing_number TEXT")
    if "is_tokenized_account_number" not in existing_pa:
        conn.execute("ALTER TABLE plaid_accounts ADD COLUMN is_tokenized_account_number INTEGER NOT NULL DEFAULT 0")
    existing_exp = {row["name"] for row in conn.execute("PRAGMA table_info(expenses)").fetchall()}
    if "base_year" not in existing_exp:
        conn.execute("ALTER TABLE expenses ADD COLUMN base_year INTEGER")
    if "inflates" not in existing_exp:
        conn.execute("ALTER TABLE expenses ADD COLUMN inflates INTEGER NOT NULL DEFAULT 0")
    existing_si = {row["name"] for row in conn.execute("PRAGMA table_info(security_industries)").fetchall()}
    if existing_si and "sector" not in existing_si:
        conn.execute("ALTER TABLE security_industries ADD COLUMN sector TEXT")
    if "tax_treatment" not in existing:
        conn.execute("ALTER TABLE assets ADD COLUMN tax_treatment TEXT NOT NULL DEFAULT ''")
    if "include_in_monte_carlo" not in existing_re:
        conn.execute("ALTER TABLE real_estate ADD COLUMN include_in_monte_carlo INTEGER NOT NULL DEFAULT 0")
    if "include_in_monte_carlo" not in existing:
        # New column -- backfill it from whatever retirement_liquid_categories
        # assumption this database had configured (that assumption drove
        # which Asset rows counted toward the simulation before per-row
        # checkboxes existed; it's no longer written by init_db, but an
        # upgrading database may still have a row for it left over from
        # before this migration ran). Falls back to the historical
        # {"401k", "liquid"} default if that assumption was never set.
        conn.execute("ALTER TABLE assets ADD COLUMN include_in_monte_carlo INTEGER NOT NULL DEFAULT 0")
        categories_row = conn.execute(
            "SELECT value FROM assumptions WHERE key = 'retirement_liquid_categories'"
        ).fetchone()
        raw = categories_row["value"] if categories_row and categories_row["value"] else "401k,Liquid"
        categories = {c.strip().lower() for c in raw.split(",") if c.strip()} or {"401k", "liquid"}
        placeholders = ", ".join("?" for _ in categories)
        conn.execute(
            f"UPDATE assets SET include_in_monte_carlo = 1 "
            f"WHERE kind = 'asset' AND lower(trim(category)) IN ({placeholders})",
            list(categories),
        )
    existing_pi = {row["name"] for row in conn.execute("PRAGMA table_info(plaid_items)").fetchall()}
    if "credential_profile" not in existing_pi:
        # Every Item linked before this column existed used the one
        # Plaid app this program has always had -- DEFAULT 'primary'
        # keeps it that way without needing a data backfill.
        conn.execute("ALTER TABLE plaid_items ADD COLUMN credential_profile TEXT NOT NULL DEFAULT 'primary'")
    existing_income = {row["name"] for row in conn.execute("PRAGMA table_info(income)").fetchall()}
    if "include_in_monte_carlo" not in existing_income:
        # Income has always unconditionally counted toward the simulation,
        # so every pre-existing row (and this column's own DEFAULT) stays
        # included unless the user unchecks it -- no silent change in
        # anyone's projected numbers.
        conn.execute("ALTER TABLE income ADD COLUMN include_in_monte_carlo INTEGER NOT NULL DEFAULT 1")
    if "transactions_cursor" not in existing_pi:
        # NULL for every pre-existing Item -- source.collector.sync's
        # transactions_sync call treats a NULL/missing cursor as "give me
        # this Item's whole history from the start," exactly the same as
        # a brand-new Item that just requested the "transactions" product
        # for the first time (see plaid_items.transactions_cursor's own
        # column comment in schema.py).
        conn.execute("ALTER TABLE plaid_items ADD COLUMN transactions_cursor TEXT")
    existing_ph = {row["name"] for row in conn.execute("PRAGMA table_info(plaid_holdings)").fetchall()}
    if "vested_quantity" not in existing_ph:
        # Plaid's own Holding object carries vested_quantity/vested_value
        # for stock-plan accounts (an employer RSU/ESPP plan's holding is
        # otherwise reported at its FULL quantity/value, unvested shares
        # included) -- NULL for every pre-existing row and for any
        # ordinary brokerage/401k holding, where Plaid never populates
        # these fields in the first place. See linked_data.
        # read_linked_portfolio_positions' own comment on how this is
        # used: vested_value stands in for institution_value on the
        # Linked Positions tab whenever it's present, not just here.
        conn.execute("ALTER TABLE plaid_holdings ADD COLUMN vested_quantity REAL")
    if "vested_value" not in existing_ph:
        conn.execute("ALTER TABLE plaid_holdings ADD COLUMN vested_value REAL")
    existing_cr = {row["name"] for row in conn.execute("PRAGMA table_info(category_rules)").fetchall()}
    if existing_cr and "match_mode" not in existing_cr:
        # Every pre-existing rule was always a plain substring check --
        # DEFAULT 'contains' keeps every one of them matching exactly as
        # before (see schema.py's own comment on category_rules for what
        # the other three modes mean).
        conn.execute("ALTER TABLE category_rules ADD COLUMN match_mode TEXT NOT NULL DEFAULT 'contains'")
    existing_pt = {row["name"] for row in conn.execute("PRAGMA table_info(plaid_transactions)").fetchall()}
    if existing_pt and "income_kind_override" not in existing_pt:
        # '' (auto-detect, unchanged behavior for every pre-existing row)
        # -- see schema.py's own comment on plaid_transactions for what
        # this column is for.
        conn.execute("ALTER TABLE plaid_transactions ADD COLUMN income_kind_override TEXT NOT NULL DEFAULT ''")
    if existing_cr and "kind" not in existing_cr:
        # '' (no opinion, unchanged behavior for every pre-existing rule)
        # -- see schema.py's own comment on category_rules for what this
        # column is for and how "Apply" (source.common.db.transactions.
        # apply_category_rule) uses it.
        conn.execute("ALTER TABLE category_rules ADD COLUMN kind TEXT NOT NULL DEFAULT ''")
