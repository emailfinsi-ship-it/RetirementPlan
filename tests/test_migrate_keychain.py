"""scripts/migrate_keychain.py -- the export/import round-trip that moves
this app's two Keychain-stored secrets (Plaid vault, login password)
between two Macs. Uses PlaidVaultTestCase's FakeKeyring rather than a real
Keychain (same as every other auth_store/secrets_store-touching test).
Each test points export_path at its own temp file rather than the
script's real default (Code/keychain_export.json), so tests never read or
write that real path."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.migrate_keychain import do_export, do_import
from source.common import auth_store, secrets_store
from tests.testing_utils import PlaidVaultTestCase


class TestMigrateKeychain(PlaidVaultTestCase):
    def setUp(self):
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.export_path = Path(self._tmpdir.name) / "keychain_export.json"

    def tearDown(self):
        self._tmpdir.cleanup()
        super().tearDown()

    def test_export_with_nothing_saved_writes_no_file(self):
        summary = do_export(export_path=self.export_path)
        self.assertIn("Nothing to export", summary)
        self.assertFalse(self.export_path.exists())

    def test_export_writes_both_blobs_when_both_are_set(self):
        secrets_store.set_plaid_client_id("client-123")
        auth_store.set_password("correct horse battery")

        summary = do_export(export_path=self.export_path)

        self.assertTrue(self.export_path.exists())
        payload = json.loads(self.export_path.read_text())
        self.assertEqual(payload["vault_account"], secrets_store.VAULT_ACCOUNT)
        self.assertEqual(payload["auth_account"], auth_store.AUTH_ACCOUNT)
        self.assertIsNotNone(payload["vault_json"])
        self.assertIn("client-123", payload["vault_json"])
        self.assertIsNotNone(payload["auth_json"])
        self.assertIn("Plaid credentials/tokens: found", summary)
        self.assertIn("Login password: found", summary)

    def test_export_omits_whichever_half_is_unset(self):
        auth_store.set_password("correct horse battery")
        # No Plaid credentials set at all.

        do_export(export_path=self.export_path)

        payload = json.loads(self.export_path.read_text())
        self.assertIsNone(payload["vault_json"])
        self.assertIsNotNone(payload["auth_json"])

    def test_import_with_no_export_file_present_says_so(self):
        summary = do_import(force=False, export_path=self.export_path)
        self.assertIn("run this script's 'export' subcommand", summary)

    def test_import_round_trips_both_secrets_into_a_fresh_keychain(self):
        secrets_store.set_plaid_client_id("client-123")
        auth_store.set_password("correct horse battery")
        do_export(export_path=self.export_path)

        # Simulate arriving on a brand new Mac: nothing saved yet.
        self.fake_keyring._store.clear()
        secrets_store.clear_vault_cache()
        auth_store.clear_auth_cache()
        self.assertFalse(auth_store.is_password_set())

        summary = do_import(force=False, export_path=self.export_path)

        self.assertIn("Imported Plaid credentials/tokens.", summary)
        self.assertIn("Imported login password.", summary)
        self.assertEqual(secrets_store.get_plaid_client_id(), "client-123")
        self.assertTrue(auth_store.verify_password("correct horse battery"))
        # The export file's job is done -- no reason to leave a plaintext
        # copy of the credentials sitting on disk afterward.
        self.assertFalse(self.export_path.exists())

    def test_import_refuses_to_overwrite_existing_credentials_without_force(self):
        auth_store.set_password("original password")
        secrets_store.set_plaid_client_id("client-123")
        do_export(export_path=self.export_path)
        # A different password already set on "this" Mac before importing.
        auth_store.set_password("a totally different password")

        summary = do_import(force=False, export_path=self.export_path)

        self.assertIn("refusing to", summary)
        self.assertTrue(auth_store.verify_password("a totally different password"))
        # Refused -- the export file is left alone, not silently consumed.
        self.assertTrue(self.export_path.exists())

    def test_import_with_force_overwrites_existing_credentials(self):
        auth_store.set_password("original password")
        do_export(export_path=self.export_path)
        auth_store.set_password("a totally different password")

        summary = do_import(force=True, export_path=self.export_path)

        self.assertIn("Imported login password.", summary)
        self.assertTrue(auth_store.verify_password("original password"))
        self.assertFalse(auth_store.verify_password("a totally different password"))


if __name__ == "__main__":
    unittest.main()
