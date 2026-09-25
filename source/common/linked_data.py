"""Live account balances and portfolio positions, pulled directly from
Plaid via this program's own sync (source.collector.sync) and stored in
its own database -- no dependency on FamilyFinanceTracker or any other
app. This module is the read side: it just shapes what's already in
plaid_accounts/plaid_holdings for the Asset/Summary tabs and the Excel
export, the same way it always has (function names/shapes here are kept
stable on purpose, since aggregate.py and dashboard.py build on them).

Balances reflect whatever the last sync ("Sync now" on the Summary,
Linked Accounts, or Linked Positions page, or the Setup page's Plaid
card) wrote to the database -- call source.collector.sync.sync_all() to
refresh them from Plaid.
"""

from __future__ import annotations

from source.common import db

_LIABILITY_TYPES = {"credit", "loan"}


def _is_liability_type(typ) -> bool:
    return str(typ or "").strip().lower() in _LIABILITY_TYPES


def linked_data_status() -> dict:
    items = db.list_plaid_items()
    last_synced = [i["last_synced_at"] for i in items if i["last_synced_at"]]
    return {
        "configured": len(items) > 0,
        "item_count": len(items),
        "last_synced_at": max(last_synced) if last_synced else None,
    }


def _signed_balance(account: dict) -> float:
    balance = account["current_balance"]
    signed = -abs(balance) if balance is not None and _is_liability_type(account["type"]) else balance
    return signed if signed is not None else 0.0


def read_linked_account_balances() -> list:
    items_by_key = {i["item_key"]: i for i in db.list_plaid_items()}
    result = []
    for a in db.list_plaid_accounts():
        item = items_by_key.get(a["item_key"], {})
        result.append({
            "account_id": a["account_id"],
            "item_key": a["item_key"],
            # The real bank/brokerage name, from the parent Item (set once
            # at Link time from Plaid's own institution metadata) -- NOT
            # the account's own Plaid `name`/`official_name` (that's
            # exposed separately below as "account_name"). Those two used
            # to be conflated here (this field used to just be a["name"]),
            # which is wrong whenever Plaid's account-level name doesn't
            # happen to read like a bank name (e.g. "Individual Brokerage",
            # "401(k)", "Checking") -- see linkable_accounts() below, which
            # already did this correctly for the Asset-tab picker.
            "institution": item.get("institution_name") or "",
            "account_name": a["official_name"] or a["name"] or "",
            "last4": (a["mask"] or "")[-4:],
            # Full account/routing number, only ever present for a
            # checking/savings/cash-management account whose Item
            # requested the Auth product (source.collector.sync) -- None
            # for everything else (investment, loan, credit), same as the
            # mask-only mask/last4 story before this existed.
            "account_number": a["account_number"] or None,
            "routing_number": a["routing_number"] or None,
            "is_tokenized_account_number": bool(a["is_tokenized_account_number"]),
            "balance": _signed_balance(a),
            "last_update": a["updated_at"] or "",
            "account_type": (a["subtype"] or a["type"] or "").replace("_", " ").title(),
            # The raw Plaid `type` ("credit"/"loan" vs "depository"/
            # "investment"), not the title-cased subtype above (a credit
            # card's subtype is itself "Credit Card", but a mortgage's
            # subtype can be anything) -- lets a caller (the Linked
            # Accounts page's "Classify" action) default a new line
            # item's Asset/Liability kind correctly without re-deriving
            # this from the display string.
            "is_liability": _is_liability_type(a["type"]),
        })
    return result


def linkable_accounts() -> list:
    """Plaid accounts shaped for the Asset tab's "linked account" picker
    and for looking up a linked line item's live balance by account_id --
    read_linked_account_balances() above is display-only (no id); both
    functions pull the real institution name from the parent plaid_items
    row (see that function's own comment) so a picker entry reads like
    "Fidelity -- APPLE 401(K) PLAN (...1234)"."""
    items_by_key = {i["item_key"]: i for i in db.list_plaid_items()}
    result = []
    for a in db.list_plaid_accounts():
        item = items_by_key.get(a["item_key"], {})
        result.append({
            "account_id": a["account_id"],
            "institution": item.get("institution_name") or "",
            "label": a["official_name"] or a["name"] or "(unnamed account)",
            "mask": a["mask"] or "",
            "account_number": a["account_number"] or None,
            "routing_number": a["routing_number"] or None,
            "is_tokenized_account_number": bool(a["is_tokenized_account_number"]),
            "balance": _signed_balance(a),
            "last_update": a["updated_at"] or "",
        })
    return result


def read_linked_portfolio_positions() -> list:
    accounts_by_id = {a["account_id"]: a for a in db.list_plaid_accounts()}
    # Best-effort, Yahoo-Finance-classified industry per security_id
    # (source.collector.sync_industries) -- blank for anything not yet
    # classified (a fund/ETF, or an equity synced since the last "Sync
    # now"), which the dashboard's chart/table both show as "Unknown".
    industries_by_security_id = db.get_security_industries()
    # A manual sector override (source.webapp.dashboard's "Set sector"
    # bulk action) -- for a mutual fund/ETF that never gets an `industry`
    # in the first place (see set_security_sector's own docstring), this
    # is the only way it leaves the "Unknown" sector bucket. Blank when
    # unset, same convention as industries_by_security_id above.
    sectors_by_security_id = db.get_security_sectors()
    result = []
    for h in db.list_plaid_holdings():
        account = accounts_by_id.get(h["account_id"], {})
        result.append({
            "security_id": h["security_id"],
            "institution": account.get("name") or "",
            "account": account.get("official_name") or account.get("name") or "",
            "security_name": h["security_name"] or "",
            "ticker": h["ticker_symbol"] or "",
            "security_type": (h["security_type"] or "").replace("_", " ").title(),
            "industry": industries_by_security_id.get(h["security_id"]) or "",
            "manual_sector": sectors_by_security_id.get(h["security_id"]) or "",
            "market_value": h["institution_value"] or 0.0,
            "position_as_of": h["updated_at"] or "",
        })
    return result


def read_transactions() -> list:
    """Every synced Plaid transaction (source.collector.sync._sync_
    transactions_for_item), joined with its account/institution for
    display -- powers the Real Expenditure tab (source.webapp.pages.
    real_expenditure). Plaid's own amount convention is kept as-is
    (positive = money out, negative = money in/refund) rather than
    flipped to a "spend is positive" convention here, so a category or
    monthly total that simply sums `amount` already nets a refund
    against the spending it partially or fully reverses."""
    accounts_by_id = {a["account_id"]: a for a in db.list_plaid_accounts()}
    items_by_key = {i["item_key"]: i for i in db.list_plaid_items()}
    result = []
    for t in db.list_plaid_transactions():
        account = accounts_by_id.get(t["account_id"], {})
        item = items_by_key.get(t["item_key"], {})
        result.append({
            "transaction_id": t["transaction_id"],
            "date": t["date"],
            "amount": t["amount"] or 0.0,
            "iso_currency_code": t["iso_currency_code"] or "",
            "name": t["name"] or "",
            "merchant_name": t["merchant_name"] or "",
            "pending": bool(t["pending"]),
            "category": t["category"] or "Uncategorized",
            "category_edited_by_user": bool(t["category_edited_by_user"]),
            "excluded_from_expense": bool(t["excluded_from_expense"]),
            "excluded_edited_by_user": bool(t["excluded_edited_by_user"]),
            "institution": item.get("institution_name") or "",
            "account_name": account.get("official_name") or account.get("name") or "",
            "account_type": (account.get("subtype") or account.get("type") or "").replace("_", " ").title(),
        })
    return result


def linked_totals() -> dict:
    balances = read_linked_account_balances()
    positions = read_linked_portfolio_positions()
    return {
        "account_balances_total": sum(r["balance"] for r in balances),
        "account_count": len(balances),
        "portfolio_market_value_total": sum(r["market_value"] for r in positions),
        "position_count": len(positions),
    }
