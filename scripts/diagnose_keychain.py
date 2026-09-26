#!/usr/bin/env python3
"""One-time diagnostic: why a login password set on the Setup page doesn't
seem to survive restarting the dashboard (source.common.auth_store), even
though this program's *other* Keychain-backed vault -- Plaid access
tokens, source.common.secrets_store, same service name, same mechanism --
clearly does persist (a linked Plaid Item keeps syncing across restarts
without being re-linked).

Since both vaults are the same "one JSON blob under a Keychain generic-
password item" mechanism, just under a different Keychain *account*
string ("vault" vs "auth") within the same *service* ("RetirementPlan"),
a persistence difference between the two is almost certainly either:
  (a) a Keychain access-control prompt tied to the "auth" account
      specifically that hasn't been (or can't be) answered -- each
      distinct service+account pair can trigger its own separate macOS
      "Do you want to allow python3 to access..." prompt the first time
      it's touched, even once you've already said yes for "vault"; or
  (b) the "auth" write genuinely isn't happening/persisting for some
      other reason (wrong Keychain backend, wrong keychain_service()
      value at read vs write time, etc).

Run this in your own Terminal, from Code/, with the SAME Python you run
the dashboard with:

    venv/bin/python scripts/diagnose_keychain.py

It only ever writes to a disposable "diagnostic" account under this same
service -- it never touches your real login password or your Plaid vault
-- and cleans that test entry up again before exiting. Share the printed
output; it pins down exactly which of the above is happening.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import keyring  # noqa: E402

from source.common import auth_store, secrets_store  # noqa: E402

DIAG_ACCOUNT = "diagnostic-roundtrip"


def main() -> None:
    print("=" * 70)
    print("1. Which keyring backend is actually active right now?")
    backend = keyring.get_keyring()
    print(f"   {backend.__class__.__module__}.{backend.__class__.__name__}")
    if "macOS" not in backend.__class__.__module__ and "Keychain" not in backend.__class__.__name__:
        print("   ^ NOT the macOS Keychain backend -- this alone would explain everything:")
        print("     whatever backend this is may not persist the way the macOS one does.")
    print()

    service = secrets_store.keychain_service()
    print(f"2. Keychain service name this process resolves to: {service!r}")
    print("   (should be 'RetirementPlan' -- if it says 'RetirementPlan-test', something")
    print("   is making this process think it's running under a test runner.)")
    print()

    print("3. Does the Plaid vault (account 'vault') already have something in it?")
    try:
        raw = keyring.get_password(service, "vault")
        print(f"   Found: {'yes, ' + str(len(raw)) + ' bytes' if raw else 'no (empty)'}")
    except Exception as exc:  # noqa: BLE001 -- diagnostic, we want to see anything
        print(f"   ERROR reading it: {exc!r}")
    print()

    print("4. Does the login-password vault (account 'auth') have something in it RIGHT NOW,")
    print("   from this process's point of view?")
    try:
        raw = keyring.get_password(service, "auth")
        print(f"   Found: {'yes, ' + str(len(raw)) + ' bytes' if raw else 'no (empty)'}")
    except Exception as exc:  # noqa: BLE001
        print(f"   ERROR reading it: {exc!r}")
    print(f"   auth_store.is_password_set() says: {auth_store.is_password_set()}")
    print()

    print("5. Round-trip test: write then immediately read back a disposable value")
    print(f"   under service={service!r}, account={DIAG_ACCOUNT!r} (NOT your real password).")
    test_value = "diagnostic-value-12345"
    try:
        keyring.set_password(service, DIAG_ACCOUNT, test_value)
        print("   Write: succeeded, no exception.")
    except Exception as exc:  # noqa: BLE001
        print(f"   Write: FAILED -- {exc!r}")
        print()
        print("   This means writing to the Keychain from this process fails outright --")
        print("   the same call auth_store.set_password() makes, so this is very likely")
        print("   why your login password never sticks either.")
        return
    try:
        read_back = keyring.get_password(service, DIAG_ACCOUNT)
    except Exception as exc:  # noqa: BLE001
        print(f"   Read-back: FAILED -- {exc!r}")
        read_back = None
    else:
        print(f"   Read-back: {'matches what was written' if read_back == test_value else f'MISMATCH ({read_back!r})'}")
    try:
        keyring.delete_password(service, DIAG_ACCOUNT)
    except Exception:
        pass
    print()
    print("=" * 70)
    print("If step 5's write+read-back succeeded in THIS process but the printed message")
    print("at dashboard startup still says no login password is set after you've set one")
    print("and restarted, the missing piece is almost certainly a macOS Keychain access")
    print("prompt for the 'auth' item specifically -- watch for a system dialog (it can")
    print("appear behind other windows) right when you click \"Set password\", and choose")
    print("\"Always Allow\". If no such dialog ever appears and it still doesn't persist,")
    print("send this whole output back and we'll dig further from there.")


if __name__ == "__main__":
    main()
