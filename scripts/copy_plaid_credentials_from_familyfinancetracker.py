#!/usr/bin/env python3
"""One-time helper: copies your existing Plaid credentials and linked-Item
metadata from FamilyFinanceTracker into Retirement Plan, so you don't have
to re-enter your Plaid API keys or re-link every bank/brokerage account
(log in again, go through Plaid Link) from scratch.

What it copies
--------------
1. Your Plaid client ID, per-environment secret(s), and each linked
   Item's access token -- straight from FamilyFinanceTracker's macOS
   Keychain vault into Retirement Plan's own Keychain vault (a different
   Keychain item, its own service name), landing in Retirement Plan's
   "Primary" Plaid credential profile (see source.common.secrets_store --
   Retirement Plan supports a second, independent "Secondary" profile too,
   for a second Plaid app, but FamilyFinanceTracker has no such concept,
   so there's nothing to copy into Secondary). If Retirement Plan already
   has some credentials saved in Primary, this MERGES rather than
   overwriting -- anything you've already set up directly in Retirement
   Plan is kept; only missing pieces are filled in from
   FamilyFinanceTracker.
2. Each linked Item's non-secret metadata (item_key, institution name,
   products, environment) -- read straight from FamilyFinanceTracker's
   SQLite database file (plain file, no app code involved) and inserted
   into Retirement Plan's own database. Existing Items in Retirement Plan
   are left alone; only Items it doesn't already know about are added.

What it does NOT copy
----------------------
Account balances or holdings themselves -- those come from Plaid fresh,
every time. After running this, use "Sync now" on Retirement Plan's
Summary, Linked Accounts, or Linked Positions page to pull current
balances for the newly-copied Items.

This is the ONLY supported way credentials move between the two apps --
Retirement Plan's own code never reads FamilyFinanceTracker's Keychain
item on its own. Run this once, in your own Terminal, on your own Mac:

    cd ~/Downloads/RetirementPlan/Code   # or wherever you extracted it
    venv/bin/python scripts/copy_plaid_credentials_from_familyfinancetracker.py

Pass --fft-db to point at a non-default FamilyFinanceTracker database
location (e.g. if you moved its Data location in that app's Setup page):

    venv/bin/python scripts/copy_plaid_credentials_from_familyfinancetracker.py \\
        --fft-db "/Users/you/Documents/FamilyFinanceData/family_finance.db"
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import keyring

# Make this program's own source/ package importable when run as a plain
# script (this file lives at Code/scripts/, source/ is a sibling of
# scripts/ under Code/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from source.common import config, db  # noqa: E402
from source.common import secrets_store  # noqa: E402

FFT_SERVICE = "FamilyFinanceTracker"
FFT_VAULT_ACCOUNT = "vault"
DEFAULT_FFT_DB = Path.home() / "FamilyFinanceTracker" / "Code" / "data" / "family_finance.db"


def copy_credentials() -> list:
    """Returns a list of human-readable lines describing what happened.

    Goes through source.common.secrets_store's public get/set functions
    (profile="primary") rather than reading/writing the vault's raw JSON
    directly -- that way this script never needs to know the vault's
    internal shape (which has changed once already, to add the Secondary
    profile) and automatically benefits from any future change to it too.
    "Existing wins on conflict": only fills in a field Retirement Plan's
    Primary profile doesn't already have."""
    lines = []
    raw = keyring.get_password(FFT_SERVICE, FFT_VAULT_ACCOUNT)
    if not raw:
        lines.append("No FamilyFinanceTracker Plaid vault found in the Keychain -- nothing to copy.")
        return lines
    try:
        incoming = json.loads(raw)
    except json.JSONDecodeError:
        lines.append("FamilyFinanceTracker's Keychain vault isn't valid JSON -- skipping credential copy.")
        return lines

    copied_client_id = False
    incoming_client_id = (incoming.get("plaid_client_id") or "").strip()
    if incoming_client_id:
        try:
            secrets_store.get_plaid_client_id(profile="primary")
        except secrets_store.SecretNotFoundError:
            secrets_store.set_plaid_client_id(incoming_client_id, profile="primary")
            copied_client_id = True

    copied_secrets = []
    for env, secret in (incoming.get("plaid_secrets") or {}).items():
        secret = (secret or "").strip()
        if not secret:
            continue
        try:
            secrets_store.get_plaid_secret(env=env, profile="primary")
        except secrets_store.SecretNotFoundError:
            secrets_store.set_plaid_secret(secret, env=env, profile="primary")
            copied_secrets.append(env)

    copied_tokens = []
    for item_key, token in (incoming.get("access_tokens") or {}).items():
        token = (token or "").strip()
        if not token:
            continue
        try:
            secrets_store.get_item_access_token(item_key)
        except secrets_store.SecretNotFoundError:
            secrets_store.set_item_access_token(item_key, token)
            copied_tokens.append(item_key)

    if copied_client_id:
        lines.append("Copied Plaid client ID into the Primary profile.")
    if copied_secrets:
        lines.append(f"Copied Plaid secret(s) into the Primary profile for: {', '.join(sorted(copied_secrets))}.")
    if copied_tokens:
        lines.append(f"Copied access token(s) for item(s): {', '.join(sorted(copied_tokens))}.")
    if not (copied_client_id or copied_secrets or copied_tokens):
        lines.append("Retirement Plan already had all of that -- nothing new to copy from the Keychain.")
    return lines


def copy_item_metadata(fft_db_path: Path) -> list:
    lines = []
    if not fft_db_path.exists():
        lines.append(f"No FamilyFinanceTracker database found at {fft_db_path} -- skipping Item metadata copy.")
        return lines

    conn = sqlite3.connect(str(fft_db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT item_key, plaid_item_id, institution_id, institution_name, products, environment, linked_at "
            "FROM items"
        ).fetchall()
    finally:
        conn.close()

    existing_keys = {i["item_key"] for i in db.list_plaid_items()}
    copied = []
    for row in rows:
        if row["item_key"] in existing_keys:
            continue
        products = [p.strip() for p in (row["products"] or "").split(",") if p.strip()]
        db.upsert_plaid_item(
            item_key=row["item_key"],
            plaid_item_id=row["plaid_item_id"],
            institution_id=row["institution_id"],
            institution_name=row["institution_name"],
            products=products,
            environment=row["environment"],
            linked_at=row["linked_at"],
        )
        copied.append(row["item_key"])

    if copied:
        lines.append(f"Copied Item metadata for: {', '.join(copied)}.")
    else:
        lines.append("No new Item metadata to copy (Retirement Plan already knows about all of them, or none exist).")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--fft-db", type=Path, default=DEFAULT_FFT_DB,
        help=f"Path to FamilyFinanceTracker's family_finance.db (default: {DEFAULT_FFT_DB})",
    )
    args = parser.parse_args()

    # This program's own database may not exist yet if the dashboard has
    # never been run before (that's normally what creates it). Item
    # metadata below is inserted straight via source.common.db, so make
    # sure the schema is there first -- same call the dashboard itself
    # makes on startup (source.webapp.dashboard.run).
    config.ensure_directories()
    db.init_db()

    print("Copying Plaid credentials from FamilyFinanceTracker's Keychain vault...")
    for line in copy_credentials():
        print(f"  {line}")

    print(f"\nCopying linked-Item metadata from {args.fft_db}...")
    for line in copy_item_metadata(args.fft_db):
        print(f"  {line}")

    print("\nDone. Open the dashboard's Summary or Linked Accounts page and click \"Sync now\" to pull current balances.")


if __name__ == "__main__":
    main()
