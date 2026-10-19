"""In-app restore of a backup: checks first, saves the current data first,
asks for the password, and refuses anything that is not a listed backup."""

import json
import unittest

from source.common import auth_store, backup, config, db
from tests.test_dashboard_auth import AuthTestCase


class TestRestore(AuthTestCase):
    def setUp(self):
        super().setUp()
        self._clean()

    def tearDown(self):
        self._clean()
        super().tearDown()

    def _clean(self):
        d = backup.backup_dir()
        if d.exists():
            for f in d.glob("*"):
                f.unlink()
        db.set_meta("probe", "")

    def test_restore_brings_back_earlier_data_and_keeps_a_safety_copy(self):
        db.set_meta("probe", "before")
        saved = backup.create_backup("manual")
        db.set_meta("probe", "after")
        result = backup.restore_backup(saved.name)
        self.assertEqual(db.get_meta("probe"), "before")
        self.assertTrue(result["safety_copy"].endswith("pre-restore.db"))
        # ...and the data we had just before restoring is recoverable
        backup.restore_backup(result["safety_copy"])
        self.assertEqual(db.get_meta("probe"), "after")

    def test_unknown_or_path_like_names_are_refused(self):
        for bad in ("", "nope.db", "../../etc/passwd", "retirement_plan-19990101-000000-x.db"):
            with self.assertRaises(ValueError):
                backup.restore_backup(bad)

    def test_damaged_backup_is_refused_and_nothing_changes(self):
        db.set_meta("probe", "keep me")
        bad = backup.backup_dir() / "retirement_plan-20200101-000000-manual.db"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"this is not a database" * 50)
        with self.assertRaises(ValueError):
            backup.restore_backup(bad.name)
        self.assertEqual(db.get_meta("probe"), "keep me")

    def test_endpoint_needs_the_password(self):
        auth_store.set_password("correct horse battery")
        cookie = auth_store.issue_session_token("owner")
        db.set_meta("probe", "before")
        saved = backup.create_backup("manual")
        db.set_meta("probe", "after")
        resp, payload = self._post("/api/backup-restore", {"filename": saved.name, "password": "wrong"}, cookie=cookie)
        self.assertEqual(resp.status, 401)
        self.assertEqual(db.get_meta("probe"), "after")
        resp, payload = self._post("/api/backup-restore", {"filename": saved.name, "password": "correct horse battery"}, cookie=cookie)
        self.assertEqual(resp.status, 200, payload)
        self.assertEqual(db.get_meta("probe"), "before")

    def test_viewer_cannot_restore(self):
        auth_store.set_password("correct horse battery")
        auth_store.set_viewer_password("viewer password 1")
        cookie = auth_store.issue_session_token("viewer")
        saved = backup.create_backup("manual")
        resp, _ = self._post("/api/backup-restore", {"filename": saved.name, "password": "correct horse battery"}, cookie=cookie)
        self.assertEqual(resp.status, 403)

    def test_setup_page_offers_restore(self):
        backup.create_backup("manual")
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        conn.request("GET", "/setup.html")
        text = conn.getresponse().read().decode()
        conn.close()
        self.assertIn("Restore a backup", text)
        self.assertIn('id="restore-backup"', text)


if __name__ == "__main__":
    unittest.main()
