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
