"""The PWA static assets (manifest.json, service-worker.js, icons/) --
served byte-for-byte from source/webapp/static by dashboard.Handler's
_send_static_file, unauthenticated (see dashboard._PUBLIC_PATHS),
regardless of whether a login password is set."""

import http.client
import json
import unittest

from source.common import auth_store, branding
from tests.test_dashboard import DashboardTestCase


class TestStaticAssetsServed(DashboardTestCase):
    def _get_raw(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp, resp.read()
        finally:
            conn.close()

    def test_manifest_is_served_as_valid_json(self):
        resp, body = self._get_raw("/manifest.json")
        self.assertEqual(resp.status, 200)
        self.assertIn("manifest+json", resp.getheader("Content-Type"))
        parsed = json.loads(body)
        self.assertEqual(parsed["name"], branding.PRODUCT_NAME)
        self.assertNotIn("__PRODUCT", json.dumps(parsed))
        self.assertEqual(parsed["display"], "standalone")
        self.assertTrue(parsed["icons"])

    def test_manifest_icons_all_resolve_to_a_served_file(self):
        _, body = self._get_raw("/manifest.json")
        parsed = json.loads(body)
        for icon in parsed["icons"]:
            resp, data = self._get_raw(icon["src"])
            self.assertEqual(resp.status, 200, f"{icon['src']} should 200")
            self.assertGreater(len(data), 0)

    def test_apple_touch_icon_is_served(self):
        resp, data = self._get_raw("/icons/icon-180.png")
        self.assertEqual(resp.status, 200)
        self.assertIn("image/", resp.getheader("Content-Type"))
        self.assertGreater(len(data), 0)

    def test_service_worker_is_served_as_javascript(self):
        resp, body = self._get_raw("/service-worker.js")
        self.assertEqual(resp.status, 200)
        self.assertIn("javascript", resp.getheader("Content-Type"))
        self.assertIn("caches.open", body.decode("utf-8"))

    def test_unknown_icon_path_is_a_clean_404_not_a_crash(self):
        resp, _ = self._get_raw("/icons/does-not-exist.png")
        self.assertEqual(resp.status, 404)

    def test_page_shell_links_the_manifest_and_service_worker(self):
        resp, body = self._get_raw("/summary.html")
        text = body.decode("utf-8")
        self.assertIn('rel="manifest" href="/manifest.json"', text)
        self.assertIn("navigator.serviceWorker.register('/service-worker.js')", text)
        self.assertIn('name="apple-mobile-web-app-capable" content="yes"', text)
        self.assertIn('name="viewport"', text)


class TestStaticAssetsBypassLoginGate(DashboardTestCase):
    def setUp(self):
        auth_store.clear_auth_cache()
        self.fake_keyring._store.clear()

    def tearDown(self):
        auth_store.clear_auth_cache()
        self.fake_keyring._store.clear()

    def _get_raw(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp, resp.read()
        finally:
            conn.close()

    def test_manifest_reachable_with_a_password_set_and_no_session(self):
        auth_store.set_password("correct horse battery")
        resp, _ = self._get_raw("/manifest.json")
        self.assertEqual(resp.status, 200)

    def test_icons_reachable_with_a_password_set_and_no_session(self):
        auth_store.set_password("correct horse battery")
        resp, _ = self._get_raw("/icons/icon-192.png")
        self.assertEqual(resp.status, 200)

    def test_service_worker_reachable_with_a_password_set_and_no_session(self):
        auth_store.set_password("correct horse battery")
        resp, _ = self._get_raw("/service-worker.js")
        self.assertEqual(resp.status, 200)


if __name__ == "__main__":
    unittest.main()
