"""SQLite storage for the Retirement Plan program.

This program is the system of record going forward (see the module
docstring on source.importer.xlsx_import for how it gets seeded once from
the user's old hand-built workbook). Three editable line-item tables --
assets, real_estate, expenses -- back the Asset / Real Estate / Expense
tabs; each row can be added, edited, or deleted from the dashboard ("Allow
each section we could add a line item"). assumptions is a small key/value
table backing the Monte Carlo tab's inputs. meta records one-time-import
and last-export bookkeeping.

Money is stored as REAL (a plain float). This is a single-user personal
tool working with account-statement-precision balances, not a ledger
reconciling to the penny across thousands of transactions, so the
float-precision tradeoff FamilyFinanceTracker's own db.py accepts for the
same reason applies here too.

This used to be a single ~800-line db.py file; it's now a package split
by concern -- schema/defaults (schema.py), the connection context
manager (connection.py), startup migrations (migrations.py), the
generic line-item CRUD every editable tab shares (line_items.py),
Monte Carlo assumptions (assumptions.py), import/export bookkeeping
(meta.py), and the three Plaid-integration areas (plaid.py,
securities.py, transactions.py). Every caller in this codebase does
`from source.common import db` and then calls `db.something(...)`, so
nothing outside this package needs to change: every name is re-exported
here, from the same place, including init_db() itself (the one function
that ties schema+connection+migrations together to prepare a database
for use).
"""

from __future__ import annotations

from source.common.db.schema import SCHEMA, DEFAULT_ASSUMPTIONS
from source.common.db.connection import _now, connect
from source.common.db.migrations import _migrate_schema
from source.common.db.category_rules import (
    delete_category_rule,
    list_category_rules,
    load_active_overrides,
    update_category_rule,
    upsert_category_rule,
)
from source.common.db.net_worth_snapshots import list_net_worth_snapshots, record_snapshot
from source.common.db.account_balance_snapshots import (
    list_account_balance_snapshots,
    record_account_balance_snapshot,
)


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate_schema(conn)
        for key, value in DEFAULT_ASSUMPTIONS.items():
            conn.execute(
                "INSERT OR IGNORE INTO assumptions (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, _now()),
            )
    # Deliberately its own connection, opened only after the schema/
    # migrations one above has fully committed and closed -- calling
    # this from inside that still-open transaction would hit SQLite's
    # single-writer lock (a nested connect() can't write until the outer
    # one commits). Cheap and idempotent for a single-user database's
    # transaction volume, so every startup keeps already-synced
    # transactions' categories in sync with source.common.plaid_
    # categorize's current bucket list, not just newly-synced ones.
    recategorize_all_transactions()



from source.common.db.line_items import (
    _INT_FLAG_FIELDS,
    _NULLABLE_INT_FIELDS,
    _NUMERIC_FIELDS,
    _TABLE_COLUMNS,
    _coerce_line_item_value,
    _table,
    add_line_item,
    clear_section,
    delete_line_item,
    get_line_item,
    list_line_items,
    update_line_item,
)
from source.common.db.assumptions import get_assumptions, set_assumption, set_assumptions
from source.common.db.owners import OWNER_LABELS, OWNER_OPTIONS, get_account_owners, normalize_owner, set_account_owner
from source.common.db.meta import get_meta, set_meta
from source.common.db.plaid import (
    account_balances_from_payload,
    delete_plaid_item,
    get_plaid_account,
    get_plaid_item,
    list_plaid_accounts,
    list_plaid_items,
    list_plaid_holdings,
    mark_plaid_item_synced,
    prune_plaid_holdings,
    rename_plaid_item_key,
    set_plaid_account_numbers,
    upsert_plaid_account,
    upsert_plaid_holding,
    upsert_plaid_item,
)
from source.common.db.securities import (
    clear_security_industries,
    clear_security_sectors,
    get_security_industries,
    get_security_sectors,
    list_unclassified_equity_tickers,
    set_security_industry,
    set_security_sector,
)
from source.common.db.transactions import (
    apply_category_rule,
    apply_category_rule_from_transaction,
    clear_plaid_transaction_category_overrides,
    clear_plaid_transaction_excluded_overrides,
    delete_plaid_transactions,
    get_transactions_cursor,
    list_plaid_transactions,
    recategorize_all_transactions,
    set_transactions_cursor,
    update_plaid_transaction_category,
    update_plaid_transaction_excluded,
    update_plaid_transaction_income_kind,
    upsert_plaid_transaction,
)

__all__ = [
    "SCHEMA",
    "DEFAULT_ASSUMPTIONS",
    "connect",
    "init_db",
    "_TABLE_COLUMNS",
    "_table",
    "_NULLABLE_INT_FIELDS",
    "_NUMERIC_FIELDS",
    "_INT_FLAG_FIELDS",
    "_coerce_line_item_value",
    "add_line_item",
    "list_line_items",
    "get_line_item",
    "update_line_item",
    "delete_line_item",
    "clear_section",
    "get_assumptions",
    "set_assumption",
    "set_assumptions",
    "OWNER_LABELS",
    "OWNER_OPTIONS",
    "get_account_owners",
    "normalize_owner",
    "set_account_owner",
    "get_meta",
    "set_meta",
    "list_category_rules",
    "upsert_category_rule",
    "update_category_rule",
    "delete_category_rule",
    "load_active_overrides",
    "record_snapshot",
    "list_net_worth_snapshots",
    "record_account_balance_snapshot",
    "list_account_balance_snapshots",
    "upsert_plaid_item",
    "get_plaid_item",
    "list_plaid_items",
    "mark_plaid_item_synced",
    "rename_plaid_item_key",
    "delete_plaid_item",
    "account_balances_from_payload",
    "upsert_plaid_account",
    "set_plaid_account_numbers",
    "list_plaid_accounts",
    "get_plaid_account",
    "upsert_plaid_holding",
    "list_plaid_holdings",
    "prune_plaid_holdings",
    "set_security_industry",
    "get_security_industries",
    "set_security_sector",
    "get_security_sectors",
    "clear_security_sectors",
    "clear_security_industries",
    "list_unclassified_equity_tickers",
    "upsert_plaid_transaction",
    "delete_plaid_transactions",
    "list_plaid_transactions",
    "update_plaid_transaction_category",
    "clear_plaid_transaction_category_overrides",
    "recategorize_all_transactions",
    "apply_category_rule",
    "apply_category_rule_from_transaction",
    "update_plaid_transaction_excluded",
    "clear_plaid_transaction_excluded_overrides",
    "update_plaid_transaction_income_kind",
    "get_transactions_cursor",
    "set_transactions_cursor",
]
