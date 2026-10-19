"""First launch: the admin password and the database must be set up before
anything else works -- on the Mac app and the from-source download alike."""

import http.client
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source.common import auth_store, branding, config, db, first_run
from tests.test_dashboard_auth import AuthTestCase


class FirstRunBase(AuthTestCase):
    def setUp(self):
        super().setUp()
        first_run.enforce(True)

    def tearDown(self):
        first_run.enforce(False)
        db.set_setup_complete(False)
        super().tearDown()

    def _raw(self, method, path, body=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        try:
            headers = {"Content-Type": "application/json"}
            if host:
                headers["Host"] = host
            data = json.dumps(body).encode() if body is not None else None
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            return resp, resp.read().decode("utf-8")
        finally:
            conn.close()


class TestGate(FirstRunBase):
    def test_every_page_sends_you_to_the_welcome_screen(self):
        for path in ("/", "/summary.html", "/setup.html", "/login.html", "/monte-carlo.html"):
            resp, _ = self._raw("GET", path)
            self.assertEqual(resp.status, 302, path)
            self.assertEqual(resp.getheader("Location"), "/welcome.html", path)

    def test_welcome_screen_shows_logo_name_and_both_steps(self):
        resp, page = self._raw("GET", "/welcome.html")
        self.assertEqual(resp.status, 200)
        self.assertIn('src="/icons/logo.svg"', page)
        self.assertIn(branding.PRODUCT_NAME, page)
        self.assertIn(branding.PRODUCT_TAGLINE, page)
        self.assertIn("Create your admin password", page)
        self.assertIn("Set up your database", page)
        self.assertIn(str(config.DATA_DIR), page)

    def test_logo_loads_before_setup(self):
        resp, body = self._raw("GET", "/icons/logo.svg")
        self.assertEqual(resp.status, 200)
        self.assertIn("<svg", body)

    def test_saving_anything_else_is_refused(self):
        resp, body = self._raw("POST", "/api/assumptions", {"x": 1})
        self.assertEqual(resp.status, 403)
        self.assertIn("first-time setup", body)

    def test_not_enforced_means_old_behaviour(self):
        first_run.enforce(False)
        resp, _ = self._raw("GET", "/summary.html")
        self.assertEqual(resp.status, 200)


class TestCompleteSetup(FirstRunBase):
    def test_password_must_match_and_be_long_enough(self):
        for body, word in (({"password": "short", "confirm": "short"}, "8 characters"),
                           ({"password": "longenough1", "confirm": "different1"}, "match"),
                           ({"password": "longenough1"}, "match")):
            resp, text = self._raw("POST", "/api/first-run", body)
            self.assertEqual(resp.status, 400)
            self.assertIn(word, text)
        self.assertFalse(auth_store.is_password_set())

    def test_success_sets_password_signs_you_in_and_opens_the_app(self):
        resp, text = self._raw("POST", "/api/first-run", {"password": "correct horse", "confirm": "correct horse"})
        self.assertEqual(resp.status, 200)
        self.assertTrue(json.loads(text)["ok"])
        self.assertIn(dashboard_cookie(), resp.getheader("Set-Cookie"))
        self.assertTrue(auth_store.is_password_set())
        self.assertTrue(config.DB_PATH.exists())
        resp, _ = self._raw("GET", "/welcome.html")      # done: no way back in
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.getheader("Location"), "/")

    def test_cannot_run_twice(self):
        self._raw("POST", "/api/first-run", {"password": "correct horse", "confirm": "correct horse"})
        resp, _ = self._raw("POST", "/api/first-run", {"password": "another one 1", "confirm": "another one 1"})
        self.assertNotEqual(resp.status, 200)
        self.assertTrue(auth_store.verify_password("correct horse"))

    def test_only_from_this_computer(self):
        resp, _ = self._raw("POST", "/api/first-run", {"password": "correct horse", "confirm": "correct horse"}, host="evil.example.com")
        self.assertEqual(resp.status, 403)
        self.assertFalse(auth_store.is_password_set())

    def test_bad_folder_leaves_setup_open(self):
        resp, text = self._raw("POST", "/api/first-run", {"password": "correct horse", "confirm": "correct horse", "data_dir": "relative/path"})
        self.assertEqual(resp.status, 400)
        self.assertIn("full folder path", text)
        self.assertFalse(auth_store.is_password_set())

    def test_chosen_folder_gets_the_database(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(config, "DATA_DIR", config.DATA_DIR), patch.object(config, "DB_PATH", config.DB_PATH):
            target = Path(tmp) / "my-data"
            resp, text = self._raw("POST", "/api/first-run",
                                   {"password": "correct horse", "confirm": "correct horse", "data_dir": str(target)})
            self.assertEqual(resp.status, 200, text)
            self.assertTrue((target / "retirement_plan.db").exists())
            self.assertEqual(config.DATA_DIR, target.resolve())
        # the empty starter file is gone; give the shared test database back
        config.ensure_directories()
        db.init_db()


class TestRecoveryKey(FirstRunBase):
    def _setup(self):
        resp, text = self._raw("POST", "/api/first-run", {"password": "correct horse", "confirm": "correct horse"})
        return json.loads(text)["recovery_key"]

    def test_key_is_shown_once_in_a_friendly_format(self):
        key = self._setup()
        parts = key.split("-")
        self.assertEqual([len(p) for p in parts], [4, 4, 4, 4, 4])
        self.assertTrue(auth_store.has_recovery_key())
        self.assertNotIn(key.replace("-", ""), json.dumps(auth_store._load_vault()))   # only a hash is stored

    def test_forgot_page_and_login_link(self):
        self._setup()
        resp, page = self._raw("GET", "/forgot.html")
        self.assertEqual(resp.status, 200)
        self.assertIn("Reset your password", page)
        _, login = self._raw("GET", "/login.html")
        self.assertIn("/forgot.html", login)

    def test_reset_with_key_sets_new_password_and_new_key(self):
        key = self._setup()
        body = {"recovery_key": key.lower().replace("-", " "), "password": "brand new pass", "confirm": "brand new pass"}
        resp, text = self._raw("POST", "/api/reset-password", body)
        self.assertEqual(resp.status, 200, text)
        new_key = json.loads(text)["recovery_key"]
        self.assertNotEqual(new_key, key)
        self.assertTrue(auth_store.verify_password("brand new pass"))
        self.assertFalse(auth_store.verify_password("correct horse"))
        resp, _ = self._raw("POST", "/api/reset-password", {**body, "password": "third password", "confirm": "third password"})
        self.assertEqual(resp.status, 401)          # the used key no longer works

    def test_wrong_key_and_mismatched_passwords_are_refused(self):
        self._setup()
        resp, _ = self._raw("POST", "/api/reset-password",
                            {"recovery_key": "AAAA-AAAA-AAAA-AAAA-AAAA", "password": "brand new pass", "confirm": "brand new pass"})
        self.assertEqual(resp.status, 401)
        resp, _ = self._raw("POST", "/api/reset-password",
                            {"recovery_key": "x", "password": "brand new pass", "confirm": "other other"})
        self.assertEqual(resp.status, 400)
        self.assertTrue(auth_store.verify_password("correct horse"))

    def test_owner_can_make_a_new_key_with_password(self):
        old = self._setup()
        cookie = auth_store.issue_session_token("owner")
        from source.webapp import dashboard
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        headers = {"Content-Type": "application/json", "Cookie": f"{dashboard.SESSION_COOKIE_NAME}={cookie}"}
        conn.request("POST", "/api/recovery-key", body=json.dumps({"password": "wrong"}), headers=headers)
        self.assertEqual(conn.getresponse().status, 401)
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        conn.request("POST", "/api/recovery-key", body=json.dumps({"password": "correct horse"}), headers=headers)
        resp = conn.getresponse()
        new = json.loads(resp.read())["recovery_key"]
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertTrue(auth_store.verify_recovery_key(new))
        self.assertFalse(auth_store.verify_recovery_key(old))


class TestExistingInstall(FirstRunBase):
    def test_existing_database_is_kept_and_only_password_added(self):
        db.set_setup_complete(True)     # stands in for "already has the user's data"
        self.assertTrue(first_run.existing_database())
        _, page = self._raw("GET", "/welcome.html")
        self.assertIn("existing database", page)
        self.assertNotIn('id="fr-folder"', page)
        before = config.DATA_DIR
        resp, _ = self._raw("POST", "/api/first-run",
                            {"password": "correct horse", "confirm": "correct horse", "data_dir": "/tmp/ignored-folder-xyz"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(config.DATA_DIR, before)


def dashboard_cookie():
    from source.webapp import dashboard
    return dashboard.SESSION_COOKIE_NAME


if __name__ == "__main__":
    unittest.main()
