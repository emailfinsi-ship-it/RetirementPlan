"""Pulls current balances (every linked account, any type), investment
holdings (Items that requested the "investments" product), and spend
transactions (Items that requested the "transactions" product) directly
from Plaid, writes them into this program's own database, and
regenerates account_balances.csv/.html + portfolio_positions.csv/.html.

This is the entire "sync" for this program: one pass over every linked
Item, pulling whichever of balances/holdings/transactions that Item's
own `products` list requested. Transactions use Plaid's cursor-based
transactions_sync endpoint (see _sync_transactions_for_item) -- an
incremental pull after the first one, using each Item's own stored
transactions_cursor, rather than re-asking Plaid for that Item's entire
history on every sync.

Usage:
    python3 -m source.collector.sync
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.auth_get_request import AuthGetRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from source.collector import export_account_files, sync_industries
from source.collector.plaid_client import build_client
from source.common import config, db, secrets_store
from source.common.plaid_categorize import default_category, default_excluded_from_expense


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _local_now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _item_products(item_row: dict) -> set:
    return {p.strip() for p in (item_row.get("products") or "").split(",") if p.strip()}


def _transaction_to_dict(t: dict, *, category_overrides: dict | None = None) -> dict:
    """Flattens one Plaid Transaction (already .to_dict()'d) into the
    plain dict source.common.db.transactions.upsert_plaid_transaction
    expects -- Plaid's own fields plus this row's *default*
    category/excluded_from_expense, computed fresh from Plaid's
    personal_finance_category every time (upsert_plaid_transaction is
    what actually decides whether to keep a manual override instead --
    this function never knows or cares whether one exists). category_
    overrides is source.common.db.category_rules.load_active_overrides()'s
    own shape -- see default_category's own docstring -- loaded once per
    sync pass by this function's caller rather than once per transaction."""
    pfc = t.get("personal_finance_category") or {}
    primary = pfc.get("primary")
    detailed = pfc.get("detailed")
    return {
        "transaction_id": t["transaction_id"],
        "account_id": t["account_id"],
        "date": str(t["date"]),
        "amount": t["amount"],
        "iso_currency_code": t.get("iso_currency_code"),
        "name": t.get("name"),
        "merchant_name": t.get("merchant_name"),
        "pending": bool(t.get("pending")),
        "plaid_category_primary": primary,
        "plaid_category_detailed": detailed,
        "category": default_category(
            primary, detailed, t.get("merchant_name") or t.get("name"), overrides=category_overrides,
        ),
        "excluded_from_expense": default_excluded_from_expense(primary, detailed),
    }


def _sync_transactions_for_item(item_row: dict, client, access_token: str) -> int:
    """Pulls every added/modified transaction for this Item via Plaid's
    cursor-based transactions_sync -- incremental after the first call
    (only ever asks Plaid for what changed since item_row's own stored
    transactions_cursor, never the whole history again), and removes any
    transaction Plaid itself reports gone (a voided pending charge,
    since-reversed transaction, etc). Returns how many transactions were
    added/updated. Only called when "transactions" is in this Item's own
    products -- see _sync_one_item below, same gating _item_products
    already does for "auth"/"investments"."""
    item_key = item_row["item_key"]
    cursor = db.get_transactions_cursor(item_key)
    category_overrides = db.load_active_overrides()
    count = 0
    has_more = True
    while has_more:
        request = (
            TransactionsSyncRequest(access_token=access_token, cursor=cursor)
            if cursor else TransactionsSyncRequest(access_token=access_token)
        )
        response = client.transactions_sync(request).to_dict()
        for t in response.get("added", []) + response.get("modified", []):
            db.upsert_plaid_transaction(
                item_key=item_key, transaction=_transaction_to_dict(t, category_overrides=category_overrides),
            )
            count += 1
        removed_ids = [r["transaction_id"] for r in response.get("removed", [])]
        if removed_ids:
            db.delete_plaid_transactions(removed_ids)
        cursor = response.get("next_cursor")
        has_more = bool(response.get("has_more"))
    db.set_transactions_cursor(item_key, cursor)
    return count


def _sync_one_item(item_row: dict) -> tuple:
    """Returns (account_count, holding_count, numbers_count,
    transaction_count) for this Item."""
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
        synced_keys = set()
        for holding in holdings_response.get("holdings", []):
            security = securities_by_id.get(holding["security_id"], {})
            merged = {
                **holding,
                "ticker_symbol": security.get("ticker_symbol"),
                "security_name": security.get("name"),
                "security_type": security.get("type"),
            }
            db.upsert_plaid_holding(item_key=item_key, holding=merged)
            synced_keys.add((holding["account_id"], holding["security_id"]))
            holding_count += 1
        # This response is a full snapshot across every investment
        # account under this Item -- anything previously synced for
        # this item_key that ISN'T in today's response any more has
        # been sold, transferred out, or the account closed, so it has
        # to be removed here too. Without this, a sold-off position
        # just stayed in plaid_holdings forever at its last-known
        # value -- e.g. this is exactly what made one real account's
        # AAPL/other positions here look "duplicated" against a sibling
        # account under the same Item: those rows hadn't been touched
        # by the last several syncs (see prune_plaid_holdings' own
        # docstring for why Net Worth itself was never affected).
        db.prune_plaid_holdings(item_key=item_key, keep_pairs=synced_keys)

    transaction_count = 0
    if "transactions" in _item_products(item_row):
        # Wrapped the same way Auth is above -- a Transactions failure
        # (e.g. this Item hasn't actually been re-consented for it yet,
        # or Plaid returns PRODUCT_NOT_READY right after linking) doesn't
        # block the balance/holdings sync that already succeeded.
        try:
            transaction_count = _sync_transactions_for_item(item_row, client, access_token)
        except Exception as exc:
            print(f"[{item_key}] Transactions sync failed: {exc}", file=sys.stderr)

    db.mark_plaid_item_synced(item_key, _utc_now_iso())
    return account_count, holding_count, numbers_count, transaction_count


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
    total_transactions = 0
    for item_row in items:
        if item_row.get("environment") == "sample":
            continue  # pretend accounts from the sample household: nothing to fetch
        try:
            accounts, holdings, numbers, transactions = _sync_one_item(item_row)
            total_accounts += accounts
            total_holdings += holdings
            total_numbers += numbers
            total_transactions += transactions
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
        "transactions": total_transactions,
        "industries_classified": industry_result.get("classified", 0),
        "synced_at": downloaded_at,
    }


if __name__ == "__main__":
    result = sync_all()
    print(
        f"Synced {len(result['items_synced'])} item(s): {result['accounts']} account(s), "
        f"{result['holdings']} holding(s), {result['transactions']} transaction(s)."
    )
    if result["errors"]:
        for err in result["errors"]:
            print(f"  {err['item_key']}: {err['error']}", file=sys.stderr)
        raise SystemExit(1)
