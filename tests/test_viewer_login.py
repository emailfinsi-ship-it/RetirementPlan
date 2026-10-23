"""The read-only (viewer) login: a second password that can look but not change."""

from __future__ import annotations

import json
import unittest

from source.common import auth_store, db
from source.webapp import dashboard
from tests.test_dashboard_auth import AuthTestCase, _cookie_value


class TestViewerStore(AuthTestCase):
    def test_roles_and_revocation(self):
        auth_store.set_password("owner-password-1")
        with self.assertRaises(ValueError):
            auth_store.set_viewer_password("owner-password-1")  # must differ
        with self.assertRaises(ValueError):
            auth_store.set_viewer_password("short")
        auth_store.set_viewer_password("viewer-password-2")
        self.assertEqual(auth_store.login_role("owner-password-1"), "owner")
        self.assertEqual(auth_store.login_role("viewer-password-2"), "viewer")
        self.assertIsNone(auth_store.login_role("nope-nope-nope"))
        owner, viewer = auth_store.issue_session_token("owner"), auth_store.issue_session_token("viewer")
        self.assertEqual(auth_store.session_role(owner), "owner")
        self.assertEqual(auth_store.session_role(viewer), "viewer")
        # a viewer cookie cannot be turned into an owner one
        forged = viewer.split(".")[0]
        self.assertIsNone(auth_store.session_role(forged + "." + owner.split(".")[1]))
        auth_store.set_viewer_password("another-viewer-3")  # change: old viewer sessions end
        self.assertIsNone(auth_store.session_role(viewer))
        self.assertEqual(auth_store.session_role(owner), "owner")
        viewer2 = auth_store.issue_session_token("viewer")
        auth_store.clear_viewer_password()
        self.assertIsNone(auth_store.session_role(viewer2))

    def test_viewer_needs_owner_password_first(self):
        with self.assertRaises(ValueError):
            auth_store.set_viewer_password("viewer-password-2")


class TestViewerHttp(AuthTestCase):
    def _login(self, password):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        conn.request("POST", "/api/login", body=json.dumps({"password": password}), headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        cookie = _cookie_value(resp.getheader("Set-Cookie"), dashboard.SESSION_COOKIE_NAME)
        conn.close()
        return resp.status, cookie

    def setUp(self):
        super().setUp()
        auth_store.set_password("owner-password-1")
        auth_store.set_viewer_password("viewer-password-2")
        self.owner = self._login("owner-password-1")[1]
        status, self.viewer = self._login("viewer-password-2")
        self.assertEqual(status, 200)

    def test_viewer_can_read_but_not_write(self):
        body = self._get("/summary.html", cookie=self.viewer)
        self.assertEqual(body.status, 200)
        status = self._post("/api/line-item/add", {"section": "expenses", "fields": {"name": "x", "annual_amount": 1}}, cookie=self.viewer)[0].status
        self.assertEqual(status, 403)
        status = self._post("/api/assumptions", {"values": {"inflation_rate": "0.1"}}, cookie=self.viewer)[0].status
        self.assertEqual(status, 403)
        status = self._post("/api/viewer-password", {"remove": True}, cookie=self.viewer)[0].status
        self.assertEqual(status, 403)
        status = self._post("/api/set-password", {"password": "hijack-password"}, cookie=self.viewer)[0].status
        self.assertEqual(status, 403)
        status = self._post("/api/what-if", {}, cookie=self.viewer)[0].status
        self.assertEqual(status, 200)  # try-it calculations are allowed

    def test_viewer_sees_banner_owner_does_not(self):
        import http.client
        def page(cookie):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
            c.request("GET", "/summary.html", headers={"Cookie": f"{dashboard.SESSION_COOKIE_NAME}={cookie}"})
            body = c.getresponse().read().decode("utf-8")
            c.close()
            return body
        self.assertIn("View-only.", page(self.viewer))
        self.assertNotIn("View-only.", page(self.owner))

    def test_viewer_cannot_open_setup(self):
        self.assertEqual(self._get("/setup.html", cookie=self.viewer).status, 302)
        self.assertEqual(self._get("/setup.html", cookie=self.owner).status, 200)
        # the Trading tab holds the broker keys and can place orders: owner only
        self.assertEqual(self._get("/trading.html", cookie=self.viewer).status, 302)
        for path in ("/api/alpaca-keys", "/api/alpaca/preview", "/api/alpaca/order", "/api/alpaca/cancel", "/api/alpaca-keys/delete"):
            self.assertEqual(self._post(path, {}, cookie=self.viewer)[0].status, 403, path)

    def test_owner_still_writes_and_viewer_banner_only_for_viewer(self):
        status = self._post("/api/viewer-password", {"password": "viewer-password-9"}, cookie=self.owner)[0].status
        self.assertEqual(status, 200)

    def test_removing_viewer_password_signs_viewer_out(self):
        self._post("/api/viewer-password", {"remove": True}, cookie=self.owner)
        self.assertEqual(self._get("/summary.html", cookie=self.viewer).status, 302)


if __name__ == "__main__":
    unittest.main()
