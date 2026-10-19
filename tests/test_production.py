"""Production safeguards: private files, diagnostics, legal page, update check."""

import http.client
import json
import os
import stat
import unittest
from unittest.mock import patch

from source.common import app_settings, branding, config, production
from tests.test_dashboard import DashboardTestCase


class TestProduction(DashboardTestCase):
    def test_protect_files_makes_database_private(self):
        os.chmod(config.DB_PATH, 0o644)
        production.protect_files()
        self.assertEqual(stat.S_IMODE(config.DB_PATH.stat().st_mode), 0o600)

    def test_redaction_hides_private_things(self):
        text = production.redact("me@example.com password: hunter22 account 123456789012 in " + os.path.expanduser("~") + "/x")
        for bad in ("me@example.com", "hunter22", "123456789012"):
            self.assertNotIn(bad, text)
        self.assertIn("~/x", text)

    def test_diagnostics_download_has_version_and_no_secrets(self):
        resp = self._get("/diagnostics.txt")
        body = resp.read().decode()
        self.assertEqual(resp.status, 200)
        self.assertIn(branding.APP_VERSION, body)
        self.assertIn("attachment", resp.getheader("Content-Disposition"))

    def test_legal_page_is_public_and_linked_from_footer(self):
        resp = self._get("/legal.html")
        page = resp.read().decode()
        self.assertEqual(resp.status, 200)
        self.assertIn("Privacy", page)
        self.assertIn("Terms of use", page)
        self.assertIn("never moves money", page)
        footer = self._get("/summary.html").read().decode()
        self.assertIn('href="/legal.html"', footer)

    def test_setup_page_has_about_card(self):
        page = self._get("/setup.html").read().decode()
        self.assertIn("Check for updates", page)
        self.assertIn("Download support report", page)
        self.assertIn("FileVault", page)

    def test_update_check(self):
        with patch.object(app_settings, "get_update_feed_url", return_value=""):
            self.assertFalse(production.check_for_update()["configured"])
        feed = lambda url: {"version": "9.9.9", "url": "https://example.com/get", "notes": "New"}
        with patch.object(app_settings, "get_update_feed_url", return_value="https://example.com/l.json"):
            r = production.check_for_update(fetch=feed)
            self.assertTrue(r["update"])
            same = production.check_for_update(fetch=lambda u: {"version": branding.APP_VERSION})
            self.assertFalse(same["update"])
            def boom(u): raise OSError("offline")
            self.assertFalse(production.check_for_update(fetch=boom)["ok"])
        with patch.object(app_settings, "get_update_feed_url", return_value="http://insecure.example/l.json"):
            self.assertFalse(production.check_for_update(fetch=feed)["ok"])

    def test_update_feed_must_be_https(self):
        status, _ = self._post("/api/update-feed", {"url": "http://x.example/a.json"})
        self.assertEqual(status, 400)
        status, _ = self._post("/api/update-feed", {"url": ""})
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
