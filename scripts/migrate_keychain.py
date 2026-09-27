#!/usr/bin/env python3
"""Moves this app's two Keychain-stored secrets -- your Plaid API keys
and linked-account access tokens (source.common.secrets_store), and
your login password (source.common.auth_store) -- from this Mac to
another Mac you also use, for when you're relocating the whole program
(see README.md's "Moving your data to another computer") and don't want
to re-link every bank/brokerage account or set a brand new login
password on the new Mac.

Both secrets live under the same Keychain service ("RetirementPlan",
source.common.secrets_store.keychain_service()) as two separate items --
one for the Plaid vault, one for the login password. This script reads
and writes each one as an opaque JSON blob; it never parses or needs to
understand what's inside, so it stays correct even if that shape
changes later. A Keychain item genuinely never leaves the Mac it lives
on by itself -- this script is what actually copies the values across,
via a plain file that travels with the rest of RetirementPlan/.

Usage, on the OLD Mac (in Terminal, from this Code/ folder):

    venv/bin/python scripts/migrate_keychain.py export

Writes keychain_export.json right here in Code/, next to data/ and
config/ -- so when you copy or move the whole RetirementPlan/ folder to
the new Mac (AirDrop, an external drive, Migration Assistant, iCloud
Drive, however you'd normally move files), this file goes along with
it automatically. It holds your Plaid access tokens and your login
password's hash in plain JSON -- treat it like any other secret file
(don't email it to yourself or leave it sitting in a synced folder any
longer than it takes to move it) until the import step below deletes it.

On the NEW Mac, once RetirementPlan/ has arrived and you've run
./scripts/run_dashboard.sh there once already (so it has its own venv --
Ctrl+C it once you see it print "Starting dashboard..."):

    venv/bin/python scripts/migrate_keychain.py import

Writes both blobs into THIS Mac's Keychain, then deletes
keychain_export.json -- its job is done, no reason to leave a plaintext
copy of your credentials sitting on disk afterward. Refuses to overwrite
if this Mac's Keychain already has a RetirementPlan vault or login
password saved, unless you pass --force (so running this by mistake on
a Mac you're already using can't silently wipe out different
credentials already there).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import keyring

# Make this program's own source/ package importable when run as a
# plain script (this file lives at Code/scripts/, source/ is a sibling
# of scripts/ under Code/) -- same pattern as the other scripts here.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from source.common import auth_store, secrets_store  # noqa: E402
from source.common.auth_store import AUTH_ACCOUNT  # noqa: E402
from source.common.secrets_store import VAULT_ACCOUNT, keychain_service  # noqa: E402

EXPORT_PATH = Path(__file__).resolve().parent.parent / "keychain_export.json"


def do_export(*, export_path: Path = EXPORT_PATH) -> str:
    """Returns a human-readable summary; writes export_path as a side
    effect (only when there's something to export)."""
    service = keychain_service()
    vault_json = keyring.get_password(service, VAULT_ACCOUNT)
    auth_json = keyring.get_password(service, AUTH_ACCOUNT)
    if not vault_json and not auth_json:
        return (
            "Nothing found in this Mac's Keychain for the RetirementPlan service -- "
            "no Plaid credentials and no login password saved here. Nothing to export."
        )
    payload = {
        "service_name": service,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "vault_account": VAULT_ACCOUNT,
        "vault_json": vault_json,
        "auth_account": AUTH_ACCOUNT,
        "auth_json": auth_json,
    }
    export_path.write_text(json.dumps(payload, indent=2))
    lines = [
        f"Wrote {export_path}",
        f"  Plaid credentials/tokens: {'found -- included' if vault_json else 'none saved here'}",
        f"  Login password: {'found -- included' if auth_json else 'none saved here'}",
        "",
        "This file has your credentials in plain JSON -- it travels with RetirementPlan/ when",
        "you copy the folder to the new Mac. Run this script's 'import' subcommand there to load",
        "it into that Mac's Keychain; it deletes this file once it's done.",
    ]
    return "\n".join(lines)


def do_import(*, force: bool, export_path: Path = EXPORT_PATH) -> str:
    if not export_path.exists():
        return (
            f"No {export_path} found -- run this script's 'export' subcommand on the old Mac "
            "first, and make sure keychain_export.json made it into Code/ alongside data/ and config/."
        )
    payload = json.loads(export_path.read_text())
    service = payload["service_name"]

    existing_vault = keyring.get_password(service, payload["vault_account"])
    existing_auth = keyring.get_password(service, payload["auth_account"])
    if (existing_vault or existing_auth) and not force:
        return (
            "This Mac's Keychain already has RetirementPlan credentials saved -- refusing to "
            "overwrite them. Re-run with --force if you're sure you want to replace them with "
            "the ones from keychain_export.json."
        )

    lines = []
    if payload.get("vault_json"):
        keyring.set_password(service, payload["vault_account"], payload["vault_json"])
        lines.append("Imported Plaid credentials/tokens.")
    if payload.get("auth_json"):
        keyring.set_password(service, payload["auth_account"], payload["auth_json"])
        lines.append("Imported login password.")

    # Written straight to Keychain above (bypassing secrets_store's/
    # auth_store's own set_* functions, which don't have a "just take
    # this already-built blob" entry point) -- clear their in-process
    # caches so anything that reads either store next (in this same
    # process, or the dashboard process this Mac starts afterward) sees
    # what was just imported rather than whatever it last read.
    secrets_store.clear_vault_cache()
    auth_store.clear_auth_cache()

    export_path.unlink()
    lines.append(f"Deleted {export_path} (no reason to leave a plaintext copy of your credentials on disk).")
    lines.append("")
    lines.append("Done. Restart the dashboard -- your Plaid accounts and login password are now set up on this Mac too.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("export", help="Run on the OLD Mac -- writes keychain_export.json.")
    import_parser = sub.add_parser("import", help="Run on the NEW Mac -- loads keychain_export.json into its Keychain.")
    import_parser.add_argument(
        "--force", action="store_true",
        help="Overwrite this Mac's existing RetirementPlan Keychain credentials, if any.",
    )
    args = parser.parse_args()

    if args.mode == "export":
        print(do_export())
    else:
        print(do_import(force=args.force))


if __name__ == "__main__":
    main()
