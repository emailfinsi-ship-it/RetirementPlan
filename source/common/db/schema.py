"""The database's DDL (every CREATE TABLE, run idempotently on every
startup via IF NOT EXISTS -- see connection.init_db) and the Monte
Carlo assumptions table's default values, seeded once via INSERT OR
IGNORE so a simulation can run before anything is imported or
hand-configured.
"""

from __future__ import annotations


SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'asset',          -- 'asset' | 'liability'
    category TEXT NOT NULL DEFAULT '',            -- e.g. 401k, Liquid, Insurance, Cash, Loan
    name TEXT NOT NULL,
    institution TEXT NOT NULL DEFAULT '',
    last4 TEXT NOT NULL DEFAULT '',
    balance REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',        -- 'manual' | 'imported'
    linked_account_id TEXT,                       -- plaid_accounts.account_id this row tracks live, or NULL
    tax_treatment TEXT NOT NULL DEFAULT '',        -- 'tax_deferred' | 'roth' | 'taxable', or '' (not set --
                                                    -- falls back to a category-based default; see
                                                    -- source.reporting.aggregate.effective_tax_treatment).
                                                    -- Only meaningful for a row with include_in_monte_carlo
                                                    -- set -- what the Monte Carlo simulation's three-pool
                                                    -- withdrawal/RMD/tax engine uses to know which pool a
                                                    -- given account belongs to.
    include_in_monte_carlo INTEGER NOT NULL DEFAULT 0, -- 1 = this asset's balance is one of the Monte Carlo /
                                                    -- historical stress test simulations' starting pools (see
                                                    -- source.reporting.aggregate.build_summary). Off by
                                                    -- default for a brand-new row; existing rows are
                                                    -- backfilled on migration from whatever category list
                                                    -- was previously configured (see _migrate_schema below).
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS real_estate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    purchase_price REAL NOT NULL DEFAULT 0,
    current_value REAL NOT NULL DEFAULT 0,
    ownership_pct REAL NOT NULL DEFAULT 100,
    loan_balance REAL NOT NULL DEFAULT 0,
    annual_income REAL NOT NULL DEFAULT 0,         -- e.g. rental income this property brings in per year
    notes TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    linked_account_id TEXT,                       -- plaid_accounts.account_id this row's loan_balance tracks live, or NULL
    include_in_monte_carlo INTEGER NOT NULL DEFAULT 0, -- 1 = this property's equity is added as a 4th,
                                                    -- untaxed, last-drawn pool in the Monte Carlo /
                                                    -- historical stress test simulations (see
                                                    -- source.reporting.aggregate.build_summary and
                                                    -- source.reporting.monte_carlo's _WITHDRAWAL_ORDER).
                                                    -- Off by default -- real estate equity has never been
                                                    -- part of a plan's projected drawdown until opted in.
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',            -- e.g. Fixed, Variable, or an imported-ledger label
    annual_amount REAL NOT NULL DEFAULT 0,
    start_year INTEGER,
    end_year INTEGER,
    base_year INTEGER,                            -- the year annual_amount is denominated in (e.g. 2026)
    inflates INTEGER NOT NULL DEFAULT 0,           -- 1 = grows from base_year by the inflation assumption each simulated year
    notes TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Income streams that offset the retirement withdrawal need -- rental
-- income, Social Security, a pension, etc. Same shape as expenses
-- (including base_year/inflates), read by the same Monte Carlo /
-- historical stress test / Summary calculations, just subtracted from
-- the expense need instead of added to it (see
-- source.reporting.monte_carlo.annual_income_need).
CREATE TABLE IF NOT EXISTS income (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',            -- e.g. Rental, Social Security, Pension
    annual_amount REAL NOT NULL DEFAULT 0,
    start_year INTEGER,
    end_year INTEGER,
    base_year INTEGER,
    inflates INTEGER NOT NULL DEFAULT 0,
    include_in_monte_carlo INTEGER NOT NULL DEFAULT 1, -- 1 = this income stream nets against the withdrawal
                                                    -- need in the Monte Carlo / historical stress test
                                                    -- simulations (see source.reporting.aggregate.
                                                    -- build_summary's income_for_simulation). On by default --
                                                    -- every income row has always counted toward the
                                                    -- simulation, so a new row (and every pre-existing one,
                                                    -- via migration) keeps that behavior unless unchecked.
    notes TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assumptions (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Plaid-linked items/accounts/holdings -- this program's own direct Plaid
-- integration (source.plaid.*), independent of FamilyFinanceTracker.
-- Schema deliberately mirrors FamilyFinanceTracker's own items/accounts/
-- holdings tables (trimmed: no transactions_cursor, no transactions table
-- at all -- this program only ever needs balances and holdings, never
-- spend history) so the two apps' data shapes stay easy to reason about
-- side by side, even though nothing here reads FamilyFinanceTracker's
-- database directly.
CREATE TABLE IF NOT EXISTS plaid_items (
    item_key TEXT PRIMARY KEY,       -- our own short label, also the Keychain lookup key
    plaid_item_id TEXT NOT NULL,
    institution_id TEXT,
    institution_name TEXT,
    products TEXT NOT NULL DEFAULT '',   -- comma-separated, e.g. "investments,transactions"
    environment TEXT NOT NULL,       -- "sandbox" or "production"
    credential_profile TEXT NOT NULL DEFAULT 'primary', -- which saved Plaid app's client_id/
                                      -- secret this Item was linked (and is re-synced) with --
                                      -- "primary" or "secondary", see
                                      -- source.common.secrets_store.PROFILES. Defaults to
                                      -- "primary" so every Item linked before this column
                                      -- existed keeps working with the one Plaid app this
                                      -- program has always used.
    transactions_cursor TEXT,        -- Plaid transactions_sync's own opaque cursor -- NULL until
                                      -- the first transactions pull for this Item, then always the
                                      -- last response's next_cursor, so every later sync only asks
                                      -- Plaid for what changed since then rather than the Item's
                                      -- whole transaction history again. Only meaningful for an
                                      -- Item whose products include "transactions" -- see
                                      -- source.collector.sync._sync_transactions_for_item.
    linked_at TEXT NOT NULL,
    last_synced_at TEXT
);

CREATE TABLE IF NOT EXISTS plaid_accounts (
    account_id TEXT PRIMARY KEY,     -- Plaid account_id
    item_key TEXT NOT NULL REFERENCES plaid_items(item_key),
    name TEXT,
    official_name TEXT,
    type TEXT,
    subtype TEXT,
    mask TEXT,
    current_balance REAL,
    available_balance REAL,
    iso_currency_code TEXT,
    account_number TEXT,             -- full account number, Auth product only (checking/savings) -- NULL otherwise
    routing_number TEXT,             -- ditto
    is_tokenized_account_number INTEGER NOT NULL DEFAULT 0,  -- some OAuth banks (Chase/PNC/US Bank) return a TAN, not the real number
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plaid_holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL,
    account_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    ticker_symbol TEXT,
    security_name TEXT,
    security_type TEXT,
    quantity REAL,
    institution_price REAL,
    institution_value REAL,
    cost_basis REAL,
    iso_currency_code TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(account_id, security_id)
);

-- Best-effort industry classification for equity holdings, via Yahoo
-- Finance (source.collector.sync_industries) -- Plaid has no industry
-- data. Cached indefinitely once found (an industry essentially never
-- changes for a given security): sync_industries only looks up a
-- security_id it hasn't already classified.
--
-- `sector` is a separate, optional manual override for the Linked
-- Positions page's "Positions by sector" chart (source.webapp.dashboard.
-- _sector_for_industry normally derives a sector from `industry`, but a
-- mutual fund/ETF/target-date fund never gets an `industry` in the first
-- place -- see sync_industries's own docstring -- so there's nothing to
-- derive from; setting `sector` here directly is how one of those gets
-- out of the "Unknown" bucket without inventing a fake industry for it).
-- A row can have `industry` set with no `sector` (the common case --
-- sector is derived), `sector` set with no `industry` (industry stays ''
-- -- a fund tagged straight into a sector), or both.
CREATE TABLE IF NOT EXISTS security_industries (
    security_id TEXT PRIMARY KEY,
    ticker TEXT,
    industry TEXT NOT NULL,
    sector TEXT,
    updated_at TEXT NOT NULL
);

-- Individual spend transactions pulled from Plaid for whichever linked
-- Items requested the "transactions" product (credit card, checking,
-- and investment-account cash activity alike -- Plaid returns all of
-- it through the same transactions_sync endpoint regardless of account
-- type) -- powers the Real Expenditure tab (source.webapp.pages.
-- real_expenditure). See source.common.plaid_categorize for exactly how
-- `category`/`excluded_from_expense` get their starting values from
-- Plaid's own personal_finance_category, and source.collector.sync.
-- _sync_transactions_for_item for the cursor-based incremental pull
-- that populates this table.
CREATE TABLE IF NOT EXISTS plaid_transactions (
    transaction_id TEXT PRIMARY KEY,   -- Plaid's own id -- stable across syncs, so re-pulling the
                                        -- same transaction (e.g. pending -> posted) upserts in place
    item_key TEXT NOT NULL,
    account_id TEXT NOT NULL,
    date TEXT NOT NULL,                -- "YYYY-MM-DD"
    amount REAL NOT NULL,              -- Plaid convention: positive = money out, negative = money in
    iso_currency_code TEXT,
    name TEXT NOT NULL DEFAULT '',     -- Plaid's raw transaction description
    merchant_name TEXT,
    pending INTEGER NOT NULL DEFAULT 0,
    plaid_category_primary TEXT,       -- Plaid's own personal_finance_category.primary, unedited --
    plaid_category_detailed TEXT,      -- ...and .detailed -- kept around so a "Reset to automatic"
                                        -- action can always recompute category/excluded_from_expense
                                        -- from Plaid's own classification, not just from whatever this
                                        -- row's `category` happened to already say.
    category TEXT NOT NULL DEFAULT '', -- editable; starts as plaid_category_detailed/primary
                                        -- prettified (source.common.plaid_categorize.default_category)
    category_edited_by_user INTEGER NOT NULL DEFAULT 0, -- 1 once a person has bulk-set this row's
                                        -- category by hand -- a later resync (Plaid re-sending this
                                        -- transaction_id as "modified") then leaves `category` alone
                                        -- instead of recomputing it from Plaid's classification again.
    excluded_from_expense INTEGER NOT NULL DEFAULT 0, -- 1 = left out of the Real Expenditure total
                                        -- (still shown in the full transaction list, never hidden) --
                                        -- starts from plaid_categorize.default_excluded_from_expense
                                        -- (an internal transfer or credit card bill payment), editable
    excluded_edited_by_user INTEGER NOT NULL DEFAULT 0, -- same "don't clobber a manual edit on
                                        -- resync" guard as category_edited_by_user, for the flag above
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plaid_transactions_date ON plaid_transactions(date);

-- User-editable overrides on top of source.common.plaid_categorize's
-- hardcoded default category-rollup rules (Plaid primary/detailed ->
-- broad bucket, and the merchant-name keyword fallback) -- see that
-- module's docstring for the built-in defaults this layers on top of.
-- A row here always wins over the matching built-in default (checked
-- first by source.common.plaid_categorize.default_category whenever the
-- caller passes overrides= built from these rows -- see
-- source.common.db.category_rules.load_active_overrides), so a person
-- can correct or extend the rollup without this program's own code ever
-- changing. rule_type is one of:
--   'primary'  -- match_key is a Plaid personal_finance_category.primary
--                 value (e.g. "GENERAL_MERCHANDISE"), case-insensitive.
--   'detailed' -- match_key is a Plaid .detailed value (e.g.
--                 "GENERAL_MERCHANDISE_PET_SUPPLIES"), case-insensitive,
--                 checked before 'primary' (more specific wins), same
--                 order as the built-in tables.
--   'keyword'  -- match_key is a single lowercase substring checked
--                 against the transaction's merchant/transaction name,
--                 checked before every built-in keyword rule, in
--                 ascending id order (oldest-added first), first match
--                 wins -- only ever consulted when Plaid gave no
--                 primary/detailed at all, same as the built-in list.
CREATE TABLE IF NOT EXISTS category_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL,          -- 'primary' | 'detailed' | 'keyword'
    match_key TEXT NOT NULL,
    category TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(rule_type, match_key)
);
"""


DEFAULT_ASSUMPTIONS = {
    "expected_return": "0.06",
    "return_volatility": "0.12",
    "inflation_rate": "0.03",
    "iterations": "1000",
    "plan_horizon_years": "40",
    "current_year": "",  # "" -> monte_carlo.py falls back to today's year
    "annual_income_offset": "0",  # e.g. rental/pension income netted against need
    # "1"/"0" -- whether each simulated year's withdrawal is grossed up
    # for an estimated federal + California income tax bill (see
    # source.reporting.monte_carlo's module docstring and
    # estimate_annual_drawdown_tax). Defaults on, since a 401k/IRA
    # withdrawal really is taxable income.
    "apply_drawdown_tax": "1",
    # The birth year used for Required Minimum Distribution (RMD) timing
    # in the Monte Carlo simulation's tax-deferred pool -- "" means "not
    # set", which simply skips RMD modeling rather than blocking the
    # rest of the simulation on it. See source.reporting.rmd.
    "birth_year": "",
    # What fraction of a taxable-brokerage withdrawal is assumed to be
    # capital gain (vs. return of already-taxed cost basis) -- this
    # program doesn't track per-lot cost basis, so this is a deliberate,
    # user-adjustable simplification rather than an attempt at exact
    # lot accounting. See source.reporting.monte_carlo's module
    # docstring for how it's used.
    "taxable_gains_fraction": "0.4",
}
