#!/usr/bin/env python3
"""One-time helper: renames a linked Plaid Item's own internal item_key --
the short label chosen back when it was first linked (see
source.collector.link_item), which just labels the database rows and the
Keychain access-token entry, and is separate from institution_name (the
real bank/brokerage name Plaid itself reports, shown as "Institution" on
the Linked Accounts page and everywhere else).

Why this exists: a couple of Items were originally linked with an
item_key guessed before the actual institution was known (e.g. the Plaid
Link flow that was expected to end up at Morgan Stanley was actually
completed against a Charles Schwab login, or vice versa), so the item_key
now reads confusingly next to the correct institution_name Plaid reports
right beside it. Nothing is functionally broken by this -- every
calculation, chart, and total already uses institution_name, never
item_key -- it's confusing labeling, not a data bug. This script just
fixes the label.

Renames, in one local transaction:
  - the plaid_items row itself, and every plaid_accounts/plaid_holdings/
    plaid_transactions row that references the old item_key (source.
    common.db.plaid.rename_plaid_item_key)
  - the matching Keychain access-token entry (source.common.secrets_store)

Run this in your own Terminal, from Code/, with the SAME Python you run
the dashboard with -- it needs real Keychain access, which this program's
own sandboxed tooling can't reach:

    venv/bin/python scripts/rename_plaid_item_key.py --old morgan_stanley --new schwab
    venv/bin/python scripts/rename_plaid_item_key.py --old chase --new robinhood

Defaults to a dry run (prints what it would do, changes nothing) -- pass
--apply to actually make the change. Stop the dashboard first if it's
running, same as for any other direct database edit.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from source.common import config, db, secrets_store  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--old", required=True, help="The existing item_key to rename, e.g. 'morgan_stanley'.")
    parser.add_argument("--new", required=True, help="The new item_key, e.g. 'schwab'.")
    parser.add_argument("--apply", action="store_true", help="Actually make the change (default: dry run).")
    args = parser.parse_args()

    config.ensure_directories()

    item = db.get_plaid_item(args.old)
    if not item:
        print(f"No linked Item with item_key '{args.old}' -- nothing to do.")
        known = sorted(i["item_key"] for i in db.list_plaid_items())
        print(f"Currently linked item_keys: {', '.join(known) if known else '(none)'}")
        return
    if db.get_plaid_item(args.new):
        print(f"item_key '{args.new}' is already in use by another linked Item -- pick a different --new value.")
        return

    print(f"Item '{args.old}' (institution: {item.get('institution_name') or '?'}) -> '{args.new}'")
    try:
        old_token = secrets_store.get_item_access_token(args.old)
    except secrets_store.SecretNotFoundError:
        old_token = None
        print("  Note: no Keychain access token found under the old item_key -- will only rename database rows.")

    if not args.apply:
        print("Dry run only -- pass --apply to actually rename it. Nothing has been changed.")
        return

    touched = db.rename_plaid_item_key(args.old, args.new)
    print(f"  Database: renamed item_key on {touched} row(s) across plaid_items/plaid_accounts/"
          "plaid_holdings/plaid_transactions.")

    if old_token is not None:
        secrets_store.set_item_access_token(args.new, old_token)
        secrets_store.delete_item_access_token(args.old)
        print("  Keychain: moved the access token from the old item_key to the new one.")

    print(f"Done -- '{args.old}' is now '{args.new}'. Restart the dashboard to see the new label.")


if __name__ == "__main__":
    main()
