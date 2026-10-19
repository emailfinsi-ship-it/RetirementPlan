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
    owner TEXT NOT NULL DEFAULT '',                -- 'self' | 'spouse', or '' (Unassigned -- the default for
                                                    -- every pre-existing row). Whose account this is, so the
                                                    -- Monte Carlo engine can compute each person's Required
                                                    -- Minimum Distribution from their own balance and their
                                                    -- own birth year (see source.reporting.rmd and
                                                    -- source.reporting.monte_carlo.pools). Unassigned is
                                                    -- modeled under the plan owner's own birth year until
                                                    -- someone assigns it -- the UI flags it so it isn't
                                                    -- silently left that way.
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_owners (
    account_id TEXT PRIMARY KEY,                   -- plaid_accounts.account_id -- a live linked account that is NOT
                                                    -- tied to an Asset-tab row (an Asset row's own `owner` column
                                                    -- covers that case), so its owner has to live somewhere too.
                                                    -- A split account (account_tax_splits) takes this same owner
                                                    -- for every one of its pieces.
    owner TEXT NOT NULL DEFAULT '',                -- 'self' | 'spouse' | '' -- same vocabulary as assets.owner
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_tax_splits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,                      -- plaid_accounts.account_id this split applies to --
                                                    -- one linked investment account (typically a 401k not yet
                                                    -- added to the Asset tab) broken into several named pieces,
                                                    -- per the user's own request ("for fidelity can i segregate
                                                    -- the sources manually" -- a single Plaid account/subtype
                                                    -- can hold pre-tax, Roth, and after-tax money all at once,
                                                    -- e.g. Fidelity's own "Sources" breakdown: Base Pay
                                                    -- Traditional, Roth In-Plan Conversion, After-tax, ...).
    name TEXT NOT NULL,                            -- this split's own label, e.g. "Roth in-plan conversion" --
                                                    -- purely descriptive (matches the institution's own naming
                                                    -- if the user copies it over), doesn't drive anything else.
    tax_treatment TEXT NOT NULL DEFAULT 'tax_deferred', -- 'tax_deferred' | 'roth' | 'taxable' -- see
                                                    -- source.reporting.aggregate's own _VALID_TAX_TREATMENTS.
    amount REAL NOT NULL DEFAULT 0,
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
    address TEXT NOT NULL DEFAULT '',             -- street address, used only to look up a value estimate (RentCast)
    value_updated_at TEXT,                        -- when current_value was last refreshed from RentCast, or NULL
    loan_end_year INTEGER,                        -- year this property's loan is paid off, or NULL. Its rental income
                                                    -- is treated as taxable only AFTER this year (interest and
                                                    -- depreciation shelter it until then) -- see source.reporting.
                                                    -- monte_carlo.assumptions._resolve_rental_taxable_fraction.
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
    linked_category TEXT NOT NULL DEFAULT '',      -- optional Real Expenditure category to compare this row with
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
    linked_category TEXT NOT NULL DEFAULT '',      -- optional real-income category to compare this row with
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
    vested_quantity REAL,        -- Plaid-provided, stock-plan holdings only (see migrations.py's comment)
    vested_value REAL,           -- ditto -- NULL whenever Plaid doesn't split vested/unvested for this holding
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
    income_kind_override TEXT NOT NULL DEFAULT '', -- '' (auto-detect, the default), 'income', or
                                        -- 'expense' -- an explicit person-set override that
                                        -- plaid_categorize.is_real_income() checks FIRST, ahead of
                                        -- its own text-based heuristics. Exists because a category
                                        -- someone hand-types (e.g. "salary", "Rental-mp", "tax-
                                        -- refund") often doesn't literally contain the word "income",
                                        -- so without an explicit override those real-income rows were
                                        -- silently falling out of "real income" entirely the moment
                                        -- they were manually recategorized -- a real person-reported
                                        -- regression this column exists to fix for good, rather than
                                        -- chasing more text-matching edge cases.
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
--   'keyword'  -- match_key is checked against the transaction's
--                 merchant/transaction name according to match_mode
--                 below, checked before everything else (Plaid-category
--                 rules and the built-in tables included), in ascending
--                 id order (oldest-added first), first match wins.
-- match_mode only means anything for rule_type='keyword' (a 'primary'/
-- 'detailed' rule is always an exact match on Plaid's own value, case-
-- insensitive) -- one of:
--   'contains'    -- match_key anywhere in the name (the original, and
--                    still the default, behavior -- lowercase substring).
--   'starts_with' -- name starts with match_key.
--   'ends_with'   -- name ends with match_key.
--   'regex'       -- match_key is an arbitrary regular expression,
--                    searched anywhere in the name (case-insensitive); a
--                    bad pattern just never matches rather than raising
--                    (see plaid_categorize._keyword_rule_matches).
-- See source.common.plaid_categorize.KEYWORD_MATCH_MODES (the single
-- source of truth for these four strings) and that module's own
-- _keyword_rule_matches for exactly how each mode compares text.
-- kind ('' | 'income' | 'expense', source.common.plaid_categorize.
-- INCOME_KIND_OPTIONS) is this rule's own opinion on whether every
-- transaction it matches is real income, a real expense, or '' (no
-- opinion -- plaid_categorize.is_real_income's own text heuristic
-- decides, same as before this column existed). Only takes effect when
-- a person clicks "Apply" on the Setup page (source.common.db.
-- transactions.apply_category_rule), which force-sets income_kind_
-- override to this value on every transaction the rule matches --
-- deliberately NOT automatic on every save/update the way the category
-- text itself is (see recategorize_all_transactions), because unlike
-- the category text, this one needs to be able to overwrite a
-- transaction a person already hand-edited (category_edited_by_user=1)
-- -- exactly the case a rule added well after some matching
-- transactions were already manually retyped (e.g. "salary") hits, and
-- recategorize_all_transactions' normal category_edited_by_user=0 guard
-- would otherwise skip those rows forever.
-- Named snapshots of the planning assumptions (returns, inflation, retirement
-- year, birth years, tax toggles, the real-estate sale settings, ...) so
-- "Retire at 60" and "Retire at 65" can be compared side by side. The JSON
-- holds only the assumption keys listed in source.reporting.scenarios.
-- SCENARIO_KEYS; the line-item tables (assets, expenses, ...) are shared.
CREATE TABLE IF NOT EXISTS saved_scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    assumptions_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS category_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL,          -- 'primary' | 'detailed' | 'keyword'
    match_key TEXT NOT NULL,
    match_mode TEXT NOT NULL DEFAULT 'contains',
    category TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(rule_type, match_key)
);

-- One row per calendar day this program was open (or synced) -- a
-- running history of source.reporting.aggregate.build_summary()'s own
-- headline totals, captured automatically (see aggregate.
-- capture_net_worth_snapshot, called from source.webapp.dashboard.run()
-- on every startup and again after every successful Plaid sync) so the
-- Summary tab can chart net worth over time without a person ever having
-- to do anything to start tracking it. snapshot_date is the PRIMARY KEY
-- (not an id) specifically so capturing twice in the same day -- opening
-- the app, then syncing later that same day -- always UPSERTs that day's
-- row with the latest numbers rather than piling up several same-day
-- points a line chart would just show as one anyway.
CREATE TABLE IF NOT EXISTS net_worth_snapshots (
    snapshot_date TEXT PRIMARY KEY,           -- "YYYY-MM-DD", local date
    net_worth REAL NOT NULL,
    manual_asset_total REAL NOT NULL,
    linked_asset_total REAL NOT NULL,
    liability_total REAL NOT NULL,
    real_estate_equity_total REAL NOT NULL,
    retirement_liquid_total REAL NOT NULL,
    -- Your share of every property's market value (current_value x
    -- ownership %, before subtracting loans). NULL on snapshots taken
    -- before this column existed -- no value history was kept then, so
    -- the Asset tab's real-estate line simply starts on the first day
    -- this was recorded (equity, above, has the longer history).
    real_estate_value_total REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Per-account daily balance history for linked investment accounts (see
-- source.reporting.aggregate.capture_investment_account_balances, called
-- from the same two places as capture_net_worth_snapshot above: on every
-- dashboard startup and after every successful Plaid sync) so the Linked
-- Accounts tab can chart each investment account's balance over time,
-- plus a combined Total line. UNIQUE(account_id, snapshot_date) is this
-- table's answer to net_worth_snapshots' single-column PRIMARY KEY above
-- -- same reasoning (capturing twice in one day upserts that day's row
-- instead of piling up duplicate same-day points), just keyed per
-- account instead of there being only one row per day.
CREATE TABLE IF NOT EXISTS account_balance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,              -- "YYYY-MM-DD", local date
    balance REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(account_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_account_balance_snapshots_account
    ON account_balance_snapshots(account_id, snapshot_date);

-- One row per (Asset-tab row, calendar day): that row's effective balance
-- (the live Plaid balance for a linked row, the typed balance otherwise)
-- as of that day. Written alongside every net-worth snapshot (see
-- source.reporting.aggregate.capture_net_worth_snapshot), so the Asset
-- tab's net-worth chart can plot individual assets next to the total.
-- name/category are stored too so a row's history still reads sensibly
-- after it's renamed; a row that's deleted simply stops appearing (the
-- chart only lists assets that still exist). asset_id is the assets
-- table's id; there's deliberately no foreign key -- history outlives
-- the row it came from.
CREATE TABLE IF NOT EXISTS asset_balance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,              -- "YYYY-MM-DD", local date
    balance REAL NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(asset_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_asset_balance_snapshots_asset
    ON asset_balance_snapshots(asset_id, snapshot_date);
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
    # The spouse's birth year, for HER own RMD start age (73 vs 75) and
    # her own age each simulated year -- applies only to accounts whose
    # Owner is set to the spouse. "" means "not set", which skips RMDs
    # for her accounts (same as an unset birth_year does for the plan
    # owner's). See source.reporting.monte_carlo.pools.
    "spouse_birth_year": "",
    # The calendar year retirement starts -- "" means "not set", which
    # skips retirement-year gating entirely (every simulated year is
    # eligible for a withdrawal, matching this program's behavior before
    # this assumption existed). Set, it zeroes out the Monte Carlo/
    # Drawdown Planning withdrawal need for every year before it (income
    # is assumed to cover expenses pre-retirement) -- see
    # source.reporting.monte_carlo.annual_net_withdrawal_need.
    "retirement_year": "",
    # Drawdown Planning tab -- the age spending switches to drawing
    # Tax-deferred FIRST instead of Taxable first (401k/IRA withdrawals
    # are already penalty-free from 59 1/2, well before RMDs would force
    # them at 73/75). "" means "not set", which keeps the plan's default
    # Taxable-first order for the whole horizon -- this only changes
    # anything once the user explicitly opts in by setting an age. See
    # source.reporting.monte_carlo.assumptions._resolve_early_tax_deferred_age
    # and drawdown_schedule.deterministic_drawdown_schedule.
    "early_tax_deferred_age": "",
    # What fraction of a taxable-brokerage withdrawal is assumed to be
    # capital gain (vs. return of already-taxed cost basis) -- this
    # program doesn't track per-lot cost basis, so this is a deliberate,
    # user-adjustable simplification rather than an attempt at exact
    # lot accounting. See source.reporting.monte_carlo's module
    # docstring for how it's used.
    "taxable_gains_fraction": "0.4",
    # Legacy Planning tab -- source.reporting.monte_carlo.legacy_planning.
    # "non_spouse" (adult child, etc. -- SECURE Act's forced 10-year
    # drawdown, taxed as their own ordinary income) or "spouse" (can roll
    # an inherited Traditional IRA into their own, no forced short
    # window). Defaults to "non_spouse", the more complex and more
    # tax-costly case, rather than silently understating a heir's tax
    # bill for the more common non-spouse-heir estate plan.
    "heir_type": "non_spouse",
    # The heir's own assumed ordinary taxable income, used to estimate
    # what tax bracket an inherited Tax-deferred distribution stacks
    # into -- "" means "not set", which auto-fills from this plan's own
    # current Yearly Drawdown need (estimate_default_heir_base_income;
    # "use my own current bracket as a stand-in"). Left as a real dollar
    # figure rather than a bare percentage so it can be typed over with
    # an actual estimate of the heir's own income.
    "heir_base_income": "",
    # How many years the heir's own inherited Tax-deferred balance is
    # assumed to be spread across as even annual distributions -- ""
    # falls back to a heir_type-appropriate default (10 for non_spouse,
    # matching the SECURE Act's own forced window; 20 for spouse, this
    # program's own placeholder guess at "a long remaining lifetime").
    # See legacy_planning._resolve_heir_spread_years and
    # estimate_heir_tax_on_tax_deferred for why this is user-editable
    # rather than hardcoded (a spouse has no forced window at all, and
    # some non-spouse heirs -- a minor child, a disabled or chronically
    # ill beneficiary -- are exempt from the flat 10-year rule too).
    "heir_spread_years": "",
    # Real Estate tab's "what if I sold" what-if -- see source.reporting.
    # monte_carlo.real_estate_sale. Sale year "" = this year; selling
    # cost is a fraction of the sale price; appreciation "" = the
    # Inflation assumption.
    "re_sale_year": "",
    "re_selling_cost": "0.06",
    "re_appreciation": "",
}
