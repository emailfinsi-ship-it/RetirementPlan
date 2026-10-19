"""Move to another Mac: the encrypted transfer file and its two doors
(Setup export, welcome-screen import)."""

import base64
import gzip
import json
import unittest

from source.common import auth_store, backup, db, first_run, secrets_store, transfer
from tests.test_dashboard_auth import AuthTestCase


class TransferBase(AuthTestCase):
    def setUp(self):
        super().setUp()
        self._clean_backups()

    def tearDown(self):
        first_run.enforce(False)
        self._clean_backups()
        db.set_meta("probe", "")
        super().tearDown()

    def _clean_backups(self):
        d = backup.backup_dir()
        if d.exists():
            for f in d.glob("*"):
                f.unlink()

    def _wipe_this_mac(self):
        self.fake_keyring._store.clear()
        auth_store.clear_auth_cache()
        secrets_store.clear_vault_cache()
        db.set_meta("probe", "wrong mac")
        self._clean_backups()


class TestBundle(TransferBase):
    def _make(self):
        auth_store.set_password("correct horse battery")
        self.key = auth_store.new_recovery_key()
        secrets_store.set_smtp_password("mail-secret-1")
        db.set_meta("probe", "from the old mac")
        backup.create_backup("manual")
        return transfer.build_bundle("transfer passphrase")

    def test_round_trip_brings_everything_back(self):
        blob = self._make()
        self.assertNotIn(b"correct horse", blob)          # encrypted
        self.assertNotIn(b"from the old mac", blob)
        self._wipe_this_mac()
        result = transfer.apply_bundle(transfer.read_bundle(blob, "transfer passphrase"))
        self.assertTrue(result["database"] and result["has_password"] and result["has_plaid_keys"] is not None)
        self.assertTrue(auth_store.verify_password("correct horse battery"))
        self.assertTrue(auth_store.verify_recovery_key(self.key))
        self.assertEqual(secrets_store.get_smtp_password(), "mail-secret-1")
        self.assertEqual(db.get_meta("probe"), "from the old mac")
        self.assertEqual(len(backup.list_backups()), 1)

    def test_wrong_passphrase_or_junk_is_refused(self):
        blob = self._make()
        with self.assertRaises(ValueError):
            transfer.read_bundle(blob, "not the passphrase")
        with self.assertRaises(ValueError):
            transfer.read_bundle(b"hello", "transfer passphrase")
        with self.assertRaises(ValueError):
            transfer.read_bundle(blob[:-5] + b"xxxxx", "transfer passphrase")
        with self.assertRaises(ValueError):
            transfer.build_bundle("short")

    def test_never_overwrites_a_mac_that_is_already_set_up(self):
        blob = self._make()
        payload = transfer.read_bundle(blob, "transfer passphrase")
        with self.assertRaises(ValueError):
            transfer.apply_bundle(payload)             # this Mac has a password
        self.assertEqual(db.get_meta("probe"), "from the old mac")

    def test_unsafe_backup_names_are_ignored(self):
        self._make()
        payload = transfer.read_bundle(transfer.build_bundle("transfer passphrase"), "transfer passphrase")
        payload["backups"] = {"../evil.db": base64.b64encode(gzip.compress(b"x")).decode(), "notes.txt": base64.b64encode(gzip.compress(b"x")).decode()}
        self._wipe_this_mac()
        result = transfer.apply_bundle(payload)
        self.assertEqual(result["backups"], 0)

    def test_without_backups_option(self):
        auth_store.set_password("correct horse battery")
        backup.create_backup("manual")
        payload = transfer.read_bundle(transfer.build_bundle("transfer passphrase", include_backups=False), "transfer passphrase")
        self.assertEqual(payload["backups"], {})


class TestDoors(TransferBase):
    def _post_raw(self, path, body, cookie=None):
        return self._post(path, body, cookie=cookie)

    def test_export_needs_the_password_and_import_works_on_a_new_install(self):
        auth_store.set_password("correct horse battery")
        db.set_meta("probe", "from the old mac")
        cookie = auth_store.issue_session_token("owner")
        resp, _ = self._post("/api/transfer-export", {"password": "bad", "passphrase": "transfer passphrase"}, cookie=cookie)
        self.assertEqual(resp.status, 401)
        resp, _ = self._post("/api/transfer-export", {"password": "correct horse battery", "passphrase": "short"}, cookie=cookie)
        self.assertEqual(resp.status, 400)
        resp, out = self._post("/api/transfer-export", {"password": "correct horse battery", "passphrase": "transfer passphrase"}, cookie=cookie)
        self.assertEqual(resp.status, 200)
        self.assertTrue(out["filename"].endswith(".finsi-transfer"))
        # new Mac: first launch, nothing set up
        self._wipe_this_mac()
        first_run.enforce(True)
        resp, _ = self._post("/api/transfer-import", {"data_b64": out["data_b64"], "passphrase": "nope nope nope"})
        self.assertEqual(resp.status, 400)
        resp, info = self._post("/api/transfer-import", {"data_b64": out["data_b64"], "passphrase": "transfer passphrase"})
        self.assertEqual(resp.status, 200, info)
        self.assertTrue(auth_store.verify_password("correct horse battery"))
        self.assertEqual(db.get_meta("probe"), "from the old mac")
        resp, _ = self._post("/api/transfer-import", {"data_b64": out["data_b64"], "passphrase": "transfer passphrase"})
        self.assertEqual(resp.status, 400)            # a set-up Mac cannot be overwritten this way

    def test_garbage_upload_is_a_clean_error(self):
        first_run.enforce(True)
        resp, info = self._post("/api/transfer-import", {"data_b64": "%%%not base64%%%", "passphrase": "transfer passphrase"})
        self.assertEqual(resp.status, 400)
        self.assertFalse(info["ok"])

    def test_setup_and_welcome_pages_offer_it(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        conn.request("GET", "/setup.html")
        self.assertIn("Move to another Mac", conn.getresponse().read().decode())
        conn.close()
        first_run.enforce(True)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        conn.request("GET", "/welcome.html")
        page = conn.getresponse().read().decode()
        conn.close()
        self.assertIn("Moving from another Mac?", page)
        self.assertIn("/api/transfer-import", page)


if __name__ == "__main__":
    unittest.main()
