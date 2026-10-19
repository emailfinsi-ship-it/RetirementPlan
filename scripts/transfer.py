#!/usr/bin/env python3
"""Move to another Mac from the command line (the app's Setup page and welcome
screen do the same thing with buttons).

On the OLD Mac, from the Code/ folder:
    venv/bin/python scripts/transfer.py export [--out FILE] [--no-backups]
On the NEW Mac, after starting the app once (do NOT create a password first):
    venv/bin/python scripts/transfer.py import FILE [--force]

You choose a passphrase when exporting and type it again when importing. The
file holds your Keychain items, database and backups, encrypted with it."""
from __future__ import annotations

import argparse
import getpass
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from source.common import branding, config, transfer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--out", help="where to write the file (default: Desktop)")
    ex.add_argument("--no-backups", action="store_true")
    im = sub.add_parser("import")
    im.add_argument("file")
    im.add_argument("--force", action="store_true", help="replace what this Mac already has")
    args = ap.parse_args()
    try:
        if args.cmd == "export":
            first = getpass.getpass("Passphrase for the file (8+ characters): ")
            if getpass.getpass("Type it again: ") != first:
                print("The passphrases do not match.")
                return 1
            blob = transfer.build_bundle(first, include_backups=not args.no_backups)
            out = Path(args.out) if args.out else Path.home() / "Desktop" / f"{branding.INTERNAL_ID}-transfer-{time.strftime('%Y%m%d')}.finsi-transfer"
            out.write_bytes(blob)
            print(f"Saved {out} ({len(blob) / 1024:.0f} KB). Move it to the new Mac and keep the passphrase safe.")
        else:
            config.ensure_directories()
            bundle = transfer.read_bundle(Path(args.file).read_bytes(), getpass.getpass("Passphrase: "))
            result = transfer.apply_bundle(bundle, replace_existing=args.force)
            print(f"Imported: Plaid keys {'yes' if result['has_plaid_keys'] else 'no'}, login password {'yes' if result['has_password'] else 'no'}, "
                  f"database {'yes' if result['database'] else 'no'}, {result['backups']} backups. Start the app and log in with your old password.")
    except ValueError as exc:
        print(f"Could not finish: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
