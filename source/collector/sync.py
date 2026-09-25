"""Pulls current balances (every linked account, any type) and investment
holdings (Items that requested the "investments" product) directly from
Plaid, writes them into this program's own database, and regenerates
account_balances.csv/.html + portfolio_positions.csv/.html.

This is the entire "sync" for this program -- unlike FamilyFinanceTracker,
there's no transaction history to pull (Retirement Plan only ever needs a
current-balance snapshot, not spend history), so this is one pass over
every linked Item rather than three separate collector jobs.

Usage:
    python3 -m source.collector.sync
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.auth_get_request import AuthGetRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest

from source.collector import export_account_files, sync_industries
from source.collector.plaid_client import build_client
from source.common import config, db, secrets_store


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _local_now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _item_products(item_row: dict) -> set:
    return {p.strip() for p in (item_row.get("products") or "").split(",") if p.strip()}


def _sync_one_item(item_row: dict) -> tuple:
    """Returns (account_count, holding_count, numbers_count) for this Item."""
    item_key = item_row["item_key"]
    access_token = secrets_store.get_item_access_token(item_key)
    # credential_profile picks which of the two saved Plaid apps to
    # re-authenticate with -- .get(...) or "primary" is just belt-and-
    # suspenders for an item_row dict a caller built by hand without the
    # column (every row read via source.common.db always has it, thanks
    # to the migration in source.common.db.migrations).
    client = build_client(item_row["environment"], profile=item_row.get("credential_profile") or "primary")

    balance_response = client.accounts_balance_get(
        AccountsBalanceGetRequest(access_token=access_token)
    ).to_dict()
    account_count = 0
    for account in balance_response.get("accounts", []):
        db.upsert_plaid_account(item_key=item_key, account=account)
        account_count += 1

    numbers_count = 0
    if "auth" in _item_products(item_row):
        # Full account/routing numbers -- separate from the balance call
        # above, and only ever returned for checking/savings/cash-
        # management accounts (Plaid's Auth product doesn't cover
        # investment, loan, or credit accounts at all -- see auth_get's
        # docs). Wrapped so one Item's Auth call failing (e.g. the bank
        # doesn't support it for a given account) doesn't block the
        # balance sync that already succeeded above.
        try:
            auth_response = client.auth_get(AuthGetRequest(access_token=access_token)).to_dict()
            for ach in auth_response.get("numbers", {}).get("ach", []):
                db.set_plaid_account_numbers(
                    ach["account_id"],
                    account_number=ach.get("account"),
                    routing_number=ach.get("routing"),
                    is_tokenized=bool(ach.get("is_tokenized_account_number")),
                )
                numbers_count += 1
        except Exception as exc:
            print(f"[{item_key}] Auth (full account number) fetch failed: {exc}", file=sys.stderr)

    holding_count = 0
    if "investments" in _item_products(item_row):
        holdings_response = client.investments_holdings_get(
            InvestmentsHoldingsGetRequest(access_token=access_token)
        ).to_dict()
        securities_by_id = {s["security_id"]: s for s in holdings_response.get("securities", [])}
        for holding in holdings_response.get("holdings", []):
            security = securities_by_id.get(holding["security_id"], {})
            merged = {
                **holding,
                "ticker_symbol": security.get("ticker_symbol"),
                "security_name": security.get("name"),
                "security_type": security.get("type"),
            }
            db.upsert_plaid_holding(item_key=item_key, holding=merged)
            holding_count += 1

    db.mark_plaid_item_synced(item_key, _utc_now_iso())
    return account_count, holding_count, numbers_count


def sync_all() -> dict:
    """Syncs every linked Item and regenerates the CSV/HTML exports.
    Returns a summary dict; never raises for a single Item's failure --
    one bad/revoked token shouldn't block the others from syncing."""
    config.ensure_directories()
    db.init_db()
    items = db.list_plaid_items()

    succeeded = []
    errors = []
    total_accounts = 0
    total_holdings = 0
    total_numbers = 0
    for item_row in items:
        try:
            accounts, holdings, numbers = _sync_one_item(item_row)
            total_accounts += accounts
            total_holdings += holdings
            total_numbers += numbers
            succeeded.append(item_row["item_key"])
        except Exception as exc:
            errors.append({"item_key": item_row["item_key"], "error": str(exc)})
            print(f"[{item_row['item_key']}] ERROR: {exc}", file=sys.stderr)

    # Best-effort industry classification for whatever equities just got
    # synced above (Yahoo Finance -- never fails the sync, see that
    # module's own docstring: a missing library, no network, or an
    # unresolved ticker just leaves those holdings "Unknown" for now).
    industry_result = sync_industries.sync_missing_industries()

    downloaded_at = _local_now()
    export_account_files.write_account_balances(downloaded_at=downloaded_at)
    export_account_files.write_portfolio_positions(downloaded_at=downloaded_at)

    return {
        "items_synced": succeeded,
        "errors": errors,
        "accounts": total_accounts,
        "holdings": total_holdings,
        "account_numbers": total_numbers,
        "industries_classified": industry_result.get("classified", 0),
        "synced_at": downloaded_at,
    }


if __name__ == "__main__":
    result = sync_all()
    print(f"Synced {len(result['items_synced'])} item(s): {result['accounts']} account(s), {result['holdings']} holding(s).")
    if result["errors"]:
        for err in result["errors"]:
            print(f"  {err['item_key']}: {err['error']}", file=sys.stderr)
        raise SystemExit(1)
