"""Unlinks a Plaid Item: best-effort /item/remove call (revokes the access
token at Plaid's end so it can't be used again from anywhere), then
deletes the Keychain token and every local row for that Item. The Plaid
call is best-effort -- an already-revoked/expired token, or no network,
shouldn't block cleaning up the local state, so any /item/remove failure
is swallowed (mirrors FamilyFinanceTracker's own source.collector.
remove_item)."""

from __future__ import annotations

from plaid.model.item_remove_request import ItemRemoveRequest

from source.collector.plaid_client import build_client
from source.common import db, secrets_store


def remove_item(item_key: str) -> None:
    item_row = db.get_plaid_item(item_key)
    if item_row is None:
        raise ValueError(f"No linked Item '{item_key}'.")

    try:
        access_token = secrets_store.get_item_access_token(item_key)
        client = build_client(item_row["environment"], profile=item_row.get("credential_profile") or "primary")
        client.item_remove(ItemRemoveRequest(access_token=access_token))
    except Exception:
        pass  # best-effort -- local cleanup below still proceeds

    try:
        secrets_store.delete_item_access_token(item_key)
    except Exception:
        pass

    db.delete_plaid_item(item_key)
