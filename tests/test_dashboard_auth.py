"""HTTP-level tests for the login gate added to dashboard.Handler --
source.common.auth_store has its own direct unit tests (test_auth_store.py);
this file is about the gate itself: which paths require a session, how the
session cookie round-trips, first-time password setup, and login rate
limiting. Reuses DashboardTestCase's real-socket harness from
test_dashboard.py rather than re-implementing it."""

import html.parser
import http.client
import json
import time
import unittest

from source.common import app_settings, auth_store
from source.webapp import dashboard
from tests.test_dashboard import DashboardTestCase


def _cookie_value(set_cookie_header: str | None, name: str) -> str | None:
    if not set_cookie_header:
        return None
    for part in set_cookie_header.split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part[len(name) + 1 :]
    return None


class AuthTestCase(DashboardTestCase):
    """Adds cookie-aware get/post helpers on top of DashboardTestCase, and
    guarantees every test starts and ends with no password set (each test
    method's own choice to call auth_store.set_password is what actually
    turns the gate on)."""

    def setUp(self):
        auth_store.clear_auth_cache()
        self.fake_keyring._store.clear()
        dashboard._login_failures.clear()
        app_settings.set_bind_host("127.0.0.1")

    def tearDown(self):
        auth_store.clear_auth_cache()
        self.fake_keyring._store.clear()
        app_settings.set_bind_host("127.0.0.1")
        dashboard._login_failures.clear()

    def _get(self, path, *, cookie=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        try:
            headers = {"Cookie": f"{dashboard.SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            resp.read()
            return resp
        finally:
            conn.close()

    def _post(self, path, body, *, cookie=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        try:
            headers = {"Content-Type": "application/json"}
            if cookie:
                headers["Cookie"] = f"{dashboard.SESSION_COOKIE_NAME}={cookie}"
            conn.request("POST", path, body=json.dumps(body).encode("utf-8"), headers=headers)
            resp = conn.getresponse()
            payload = json.loads(resp.read().decode("utf-8"))
            return resp, payload
        finally:
            conn.close()


class TestNoPasswordSetYet(AuthTestCase):
    def test_every_page_loads_with_no_gate_when_no_password_is_set(self):
        resp = self._get("/summary.html")
        self.assertEqual(resp.status, 200)

    def test_login_page_shows_first_time_setup_form(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        conn.request("GET", "/login.html")
        raw = conn.getresponse().read().decode("utf-8")
        conn.close()
        self.assertIn("Set a login password", raw)


class TestSetPasswordFirstTime(AuthTestCase):
    def test_set_password_succeeds_and_issues_a_session_cookie(self):
        resp, payload = self._post("/api/set-password", {"password": "correct horse battery", "confirm": "correct horse battery"})
        self.assertEqual(resp.status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(auth_store.is_password_set())
        cookie = _cookie_value(resp.getheader("Set-Cookie"), dashboard.SESSION_COOKIE_NAME)
        self.assertIsNotNone(cookie)
        self.assertTrue(auth_store.verify_session_token(cookie))

    def test_mismatched_confirm_is_rejected(self):
        resp, payload = self._post("/api/set-password", {"password": "correct horse battery", "confirm": "different one"})
        self.assertEqual(resp.status, 400)
        self.assertFalse(payload["ok"])
        self.assertFalse(auth_store.is_password_set())

    def test_too_short_password_is_rejected(self):
        resp, payload = self._post("/api/set-password", {"password": "short"})
        self.assertEqual(resp.status, 400)
        self.assertFalse(auth_store.is_password_set())


class TestGateOncePasswordIsSet(AuthTestCase):
    def _login(self, password="correct horse battery"):
        auth_store.set_password(password)
        resp, payload = self._post("/api/login", {"password": password})
        self.assertTrue(payload["ok"])
        return _cookie_value(resp.getheader("Set-Cookie"), dashboard.SESSION_COOKIE_NAME)

    def test_get_without_cookie_redirects_to_login(self):
        auth_store.set_password("correct horse battery")
        resp = self._get("/summary.html")
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.getheader("Location"), "/login.html")

    def test_get_with_valid_cookie_succeeds(self):
        cookie = self._login()
        resp = self._get("/summary.html", cookie=cookie)
        self.assertEqual(resp.status, 200)

    def test_post_without_cookie_is_401(self):
        auth_store.set_password("correct horse battery")
        resp, payload = self._post("/api/line-item/add", {"section": "assets", "fields": {"name": "x", "balance": 1}})
        self.assertEqual(resp.status, 401)
        self.assertFalse(payload["ok"])

    def test_post_with_valid_cookie_succeeds(self):
        cookie = self._login()
        resp, payload = self._post(
            "/api/line-item/add", {"section": "assets", "fields": {"name": "x", "balance": 1}}, cookie=cookie,
        )
        self.assertEqual(resp.status, 200)
        self.assertTrue(payload["ok"])

    def test_manifest_and_login_page_stay_reachable_without_a_session(self):
        auth_store.set_password("correct horse battery")
        self.assertEqual(self._get("/login.html").status, 200)
        # manifest.json may 404 (no static file on disk in this test env)
        # but must never redirect to login -- that's the gate-bypass
        # contract being tested, not whether the file exists.
        resp = self._get("/manifest.json")
        self.assertNotEqual(resp.status, 302)

    def test_logout_clears_the_cookie(self):
        cookie = self._login()
        resp, payload = self._post("/api/logout", {}, cookie=cookie)
        self.assertTrue(payload["ok"])
        set_cookie = resp.getheader("Set-Cookie")
        self.assertIn("Max-Age=0", set_cookie)

    def test_changing_password_requires_being_logged_in(self):
        auth_store.set_password("correct horse battery")
        resp, payload = self._post("/api/set-password", {"password": "a brand new password"})
        self.assertEqual(resp.status, 401)
        self.assertFalse(payload["ok"])
        self.assertTrue(auth_store.verify_password("correct horse battery"))

    def test_changing_password_while_logged_in_succeeds_and_rotates_sessions(self):
        cookie = self._login()
        resp, payload = self._post("/api/set-password", {"password": "a brand new password"}, cookie=cookie)
        self.assertEqual(resp.status, 200)
        self.assertTrue(payload["ok"])
        # the OLD cookie must no longer verify -- password change is a
        # log-out-everywhere.
        self.assertFalse(auth_store.verify_session_token(cookie))


class TestSetupPageSecurityAndNetworkCards(AuthTestCase):
    def _body(self, *, cookie=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        headers = {"Cookie": f"{dashboard.SESSION_COOKIE_NAME}={cookie}"} if cookie else {}
        conn.request("GET", "/setup.html", headers=headers)
        raw = conn.getresponse().read().decode("utf-8")
        conn.close()
        return raw

    def test_security_card_shows_not_set_warning_by_default(self):
        body = self._body()
        self.assertIn("No password set yet", body)
        self.assertIn("Set a password", body)

    def test_security_card_shows_enabled_once_a_password_exists(self):
        auth_store.set_password("correct horse battery")
        resp, _ = self._post("/api/login", {"password": "correct horse battery"})
        cookie = _cookie_value(resp.getheader("Set-Cookie"), dashboard.SESSION_COOKIE_NAME)
        body = self._body(cookie=cookie)
        self.assertIn("Password protection is on", body)
        self.assertIn("Change password", body)

    def test_network_card_shows_localhost_only_by_default(self):
        body = self._body()
        self.assertIn("this Mac only (127.0.0.1)", body)

    def test_set_bind_host_endpoint_persists_the_setting(self):
        resp, payload = self._post("/api/set-bind-host", {"bind_host": "0.0.0.0"})
        self.assertEqual(resp.status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(app_settings.get_bind_host(), "0.0.0.0")

    def test_set_bind_host_rejects_an_unknown_value(self):
        resp, payload = self._post("/api/set-bind-host", {"bind_host": "8.8.8.8"})
        self.assertEqual(resp.status, 400)
        self.assertFalse(payload["ok"])

    def test_password_form_onsubmit_attribute_is_not_truncated_by_an_unescaped_quote(self):
        """A real bug, found the hard way: an earlier version of this
        attribute built its "passwords don't match" JS string with \\"
        (a Python escape that renders as a literal '"' character) inside
        a JS double-quoted string -- but the onsubmit attribute itself is
        ALSO double-quote-delimited, so that literal '"' prematurely
        closed the HTML attribute as far as any real browser's HTML
        parser is concerned, silently dropping everything after it --
        including postJSON(...) and even event.preventDefault() itself.
        The browser then fell through to a native GET form submission,
        putting the new password in the page's own URL query string and
        never calling the API at all -- looked like nothing happened
        (no JS error, a normal-looking page load), no password ever got
        saved, and every existing test here missed it because they all
        post straight to /api/set-password, bypassing the rendered form
        (and its onsubmit JS) entirely. This test instead runs the
        actual rendered HTML through html.parser -- the same class of
        parser a browser uses -- so a stray unescaped quote that
        truncates the attribute fails this test even though the raw
        Python source "looks" fine. Parses the Security card's own HTML
        fragment directly (not the whole /setup.html page) since the
        page also has an unrelated "+ Add" modal form with its own
        onsubmit -- this isolates the one attribute the bug actually
        hit rather than picking up whichever form happens to render
        last."""
        from source.webapp.pages.setup import _security_card_html

        card_html = _security_card_html(password_set=False)

        class _FormAttrParser(html.parser.HTMLParser):
            onsubmit = None

            def handle_starttag(self, tag, attrs):
                if tag == "form":
                    value = dict(attrs).get("onsubmit")
                    if value:
                        self.onsubmit = value

        parser = _FormAttrParser()
        parser.feed(card_html)
        self.assertIsNotNone(parser.onsubmit, "no <form onsubmit=...> found in the Security card")
        self.assertIn("event.preventDefault()", parser.onsubmit)
        self.assertIn("postJSON('/api/set-password'", parser.onsubmit)
        self.assertIn("location.reload()", parser.onsubmit)


class TestLoginFailures(AuthTestCase):
    def test_wrong_password_is_rejected(self):
        auth_store.set_password("correct horse battery")
        resp, payload = self._post("/api/login", {"password": "nope"})
        self.assertEqual(resp.status, 401)
        self.assertFalse(payload["ok"])

    def test_login_against_no_password_set_fails_cleanly(self):
        resp, payload = self._post("/api/login", {"password": "anything"})
        self.assertEqual(resp.status, 400)
        self.assertFalse(payload["ok"])

    def test_repeated_failures_trigger_rate_limiting(self):
        auth_store.set_password("correct horse battery")
        for _ in range(dashboard._MAX_LOGIN_FAILURES):
            resp, _ = self._post("/api/login", {"password": "nope"})
            self.assertEqual(resp.status, 401)
        resp, payload = self._post("/api/login", {"password": "correct horse battery"})
        self.assertEqual(resp.status, 429)
        self.assertFalse(payload["ok"])

    def test_successful_login_clears_the_failure_count(self):
        auth_store.set_password("correct horse battery")
        for _ in range(dashboard._MAX_LOGIN_FAILURES - 1):
            self._post("/api/login", {"password": "nope"})
        resp, payload = self._post("/api/login", {"password": "correct horse battery"})
        self.assertEqual(resp.status, 200)
        self.assertTrue(payload["ok"])
        # failure count reset -- another wrong attempt right after a
        # success shouldn't immediately be rate-limited.
        resp, payload = self._post("/api/login", {"password": "nope"})
        self.assertEqual(resp.status, 401)


if __name__ == "__main__":
    unittest.main()
