"""Shared test helpers: a temp-directory-backed config patch, used by every
test module below so no test ever touches a real data/output folder. Also a
FakeKeyring for anything that touches source.common.secrets_store, so tests
never touch a real macOS Keychain (and can run on any machine, including a
Linux CI box with no keyring backend at all)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import keyring
import keyring.errors

from source.common import auth_store, config, db, secrets_store


class TempConfigTestCase(unittest.TestCase):
    """Patches config.DATA_DIR/DB_PATH/OUTPUT_DIR to a fresh temp dir for
    each test and initializes a clean database."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self._patches = [
            patch.object(config, "DATA_DIR", tmp / "data"),
            patch.object(config, "DB_PATH", tmp / "data" / "retirement_plan.db"),
            patch.object(config, "OUTPUT_DIR", tmp / "output"),
            patch.object(config, "LOG_DIR", tmp / "logs"),
            patch.object(config, "CONFIG_DIR", tmp / "config"),
        ]
        for p in self._patches:
            p.start()
        config.ensure_directories()
        db.init_db()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()


class FakeKeyring:
    """Minimal in-memory stand-in for the `keyring` module's get_password /
    set_password / delete_password, keyed the same way (service, username).
    Good enough for secrets_store.py, which only ever calls those three
    functions -- never touches a real OS keychain."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        key = (service, username)
        if key not in self._store:
            raise keyring.errors.PasswordDeleteError("Password not found")
        del self._store[key]


class PlaidVaultTestCase(TempConfigTestCase):
    """Adds a FakeKeyring in place of the real `keyring` module functions,
    and makes sure secrets_store's AND auth_store's in-process vault
    caches never leak between tests (both live in the same fake Keychain
    item store here, and both cache their own vault dict in-process the
    same way, so both need clearing together). Use this (instead of
    TempConfigTestCase) for anything that calls source.common.
    secrets_store or source.common.auth_store directly or indirectly
    (the Plaid connect/remove/sync dashboard routes, the login/session
    routes, the collector modules, the migration script)."""

    def setUp(self):
        super().setUp()
        self.fake_keyring = FakeKeyring()
        self._keyring_patches = [
            patch.object(keyring, "get_password", self.fake_keyring.get_password),
            patch.object(keyring, "set_password", self.fake_keyring.set_password),
            patch.object(keyring, "delete_password", self.fake_keyring.delete_password),
        ]
        for p in self._keyring_patches:
            p.start()
        secrets_store.clear_vault_cache()
        auth_store.clear_auth_cache()

    def tearDown(self):
        secrets_store.clear_vault_cache()
        auth_store.clear_auth_cache()
        for p in self._keyring_patches:
            p.stop()
        super().tearDown()
