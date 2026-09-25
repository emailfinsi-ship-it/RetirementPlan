"""Plaid-linked items/accounts/holdings -- this program's own direct
Plaid integration (source.plaid.*), independent of FamilyFinanceTracker.
Schema deliberately mirrors FamilyFinanceTracker's own items/accounts/
holdings tables (trimmed: no transactions_cursor, no transactions table
at all -- this program only ever needs balances and holdings, never
spend history) so the two apps' data shapes stay easy to reason about
side by side, even though nothing here reads FamilyFinanceTracker's
database directly.
"""

from __future__ import annotations

from source.common.db.connection import _now, connect


def upsert_plaid_item(
    *,
    item_key: str,
    plaid_item_id: str,
    institution_id: str | None,
    institution_name: str | None,
    products: list[str],
    environment: str,
    linked_at: str,
    credential_profile: str = "primary",
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO plaid_items (item_key, plaid_item_id, institution_id, institution_name,
                                      products, environment, credential_profile, linked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_key) DO UPDATE SET
                plaid_item_id=excluded.plaid_item_id,
                institution_id=excluded.institution_id,
                institution_name=excluded.institution_name,
                products=excluded.products,
                environment=excluded.environment,
                credential_profile=excluded.credential_profile
            """,
            (
                item_key, plaid_item_id, institution_id, institution_name, ",".join(products),
                environment, credential_profile, linked_at,
            ),
        )



def get_plaid_item(item_key: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM plaid_items WHERE item_key = ?", (item_key,)).fetchone()
        return dict(row) if row else None



def list_plaid_items() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM plaid_items ORDER BY linked_at").fetchall()
        return [dict(r) for r in rows]



def mark_plaid_item_synced(item_key: str, synced_at: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE plaid_items SET last_synced_at = ? WHERE item_key = ?", (synced_at, item_key))



def delete_plaid_item(item_key: str) -> None:
    """Removes everything local for an Item (accounts, holdings, then the
    item row itself). Does not touch the Keychain or call Plaid -- see
    source.plaid.remove_item for the full unlink flow."""
    with connect() as conn:
        account_ids = [
            r["account_id"] for r in conn.execute(
                "SELECT account_id FROM plaid_accounts WHERE item_key = ?", (item_key,)
            ).fetchall()
        ]
        for account_id in account_ids:
            conn.execute("DELETE FROM plaid_holdings WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM plaid_accounts WHERE item_key = ?", (item_key,))
        conn.execute("DELETE FROM plaid_items WHERE item_key = ?", (item_key,))



def account_balances_from_payload(account: dict) -> tuple:
    """Pulls (current, available) out of either a raw Plaid account payload
    (nested "balances" dict) or an already-flattened dict."""
    balances = account.get("balances") if isinstance(account.get("balances"), dict) else {}
    current = balances.get("current")
    available = balances.get("available")
    if current is None:
        current = account.get("current_balance")
    if available is None:
        available = account.get("available_balance")
    return (
        float(current) if current is not None else None,
        float(available) if available is not None else None,
    )



def upsert_plaid_account(*, item_key: str, account: dict) -> None:
    current_balance, available_balance = account_balances_from_payload(account)
    balances = account.get("balances") if isinstance(account.get("balances"), dict) else {}
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO plaid_accounts (account_id, item_key, name, official_name, type, subtype,
                                         mask, current_balance, available_balance, iso_currency_code, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                item_key=excluded.item_key, name=excluded.name, official_name=excluded.official_name,
                type=excluded.type, subtype=excluded.subtype, mask=excluded.mask,
                current_balance=excluded.current_balance, available_balance=excluded.available_balance,
                iso_currency_code=excluded.iso_currency_code, updated_at=excluded.updated_at
            """,
            (
                account["account_id"], item_key, account.get("name"), account.get("official_name"),
                account.get("type"), account.get("subtype"), account.get("mask"),
                current_balance, available_balance, balances.get("iso_currency_code"), _now(),
            ),
        )



def set_plaid_account_numbers(
    account_id: str, *, account_number: str | None, routing_number: str | None, is_tokenized: bool = False,
) -> bool:
    """Records the full account/routing number for one account, fetched
    separately via Plaid's Auth product (source.collector.sync only calls
    this for accounts that support it -- Auth only covers checking/
    savings/cash-management, never investment/loan/credit accounts, see
    that module's docstring). Deliberately its own function rather than
    folded into upsert_plaid_account's regular INSERT/UPDATE: an ordinary
    balance sync (accounts_balance_get) never returns these fields, so
    upsert_plaid_account must never overwrite them with None on a normal
    sync pass -- only this explicit call, after a real Auth fetch,
    touches these two columns."""
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE plaid_accounts
            SET account_number = ?, routing_number = ?, is_tokenized_account_number = ?, updated_at = ?
            WHERE account_id = ?
            """,
            (account_number, routing_number, 1 if is_tokenized else 0, _now(), account_id),
        )
        return cur.rowcount > 0



def list_plaid_accounts() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM plaid_accounts ORDER BY item_key, name").fetchall()
        return [dict(r) for r in rows]



def get_plaid_account(account_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM plaid_accounts WHERE account_id = ?", (account_id,)).fetchone()
        return dict(row) if row else None



def upsert_plaid_holding(*, item_key: str, holding: dict) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO plaid_holdings (item_key, account_id, security_id, ticker_symbol, security_name,
                                         security_type, quantity, institution_price, institution_value,
                                         cost_basis, iso_currency_code, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, security_id) DO UPDATE SET
                ticker_symbol=excluded.ticker_symbol, security_name=excluded.security_name,
                security_type=excluded.security_type, quantity=excluded.quantity,
                institution_price=excluded.institution_price, institution_value=excluded.institution_value,
                cost_basis=excluded.cost_basis, iso_currency_code=excluded.iso_currency_code,
                updated_at=excluded.updated_at
            """,
            (
                item_key, holding["account_id"], holding["security_id"], holding.get("ticker_symbol"),
                holding.get("security_name"), holding.get("security_type"), holding.get("quantity"),
                holding.get("institution_price"), holding.get("institution_value"), holding.get("cost_basis"),
                holding.get("iso_currency_code"), _now(),
            ),
        )



def list_plaid_holdings() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM plaid_holdings ORDER BY item_key, security_name").fetchall()
        return [dict(r) for r in rows]
