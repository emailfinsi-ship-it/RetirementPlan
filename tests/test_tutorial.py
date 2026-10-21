"""The Tutorial button and page: bundled video tour and written guide."""

from __future__ import annotations

import http.client
import unittest

from tests.test_dashboard import DashboardTestCase


class TestTutorial(DashboardTestCase):
    def _raw(self, path, headers=None, method="GET"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self._HTTP_TIMEOUT)
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp, body

    def test_button_on_every_page_next_to_report_button(self):
        for path in ("/summary.html", "/asset.html", "/setup.html"):
            body = self._get(path).read().decode("utf-8")
            self.assertIn('id="tutorial-btn"', body, path)
            self.assertLess(body.index('id="report-btn"'), body.index('id="tutorial-btn"'))

    def test_page_has_video_and_guide(self):
        body = self._get("/tutorial.html").read().decode("utf-8")
        self.assertIn("/tutorial/tour-setup-dark.mp4", body)
        self.assertIn("/tutorial/tour-screens-dark.mp4", body)
        self.assertIn("User guide", body)
        self.assertIn("Will my money last?", body)
        self.assertIn("/tutorial/screenshots/01-summary.jpg", body)

    def test_about_this_page_links_to_that_screens_part_of_the_video(self):
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn("/tutorial.html?v=screens&amp;t=", body)
        self.assertNotIn("Watch this screen", self._get("/tutorial.html").read().decode("utf-8").split("<video")[0])

    def test_four_videos_are_offered(self):
        body = self._get("/tutorial.html").read().decode("utf-8")
        for name in ("setup-dark", "setup-light", "screens-dark", "screens-light"):
            self.assertIn(f"/tutorial/tour-{name}.mp4", body)

    def test_video_supports_range_requests(self):
        resp, body = self._raw("/tutorial/tour-setup-dark.mp4", {"Range": "bytes=0-99"})
        self.assertEqual(resp.status, 206)
        self.assertEqual(len(body), 100)
        self.assertTrue(resp.getheader("Content-Range").startswith("bytes 0-99/"))
        resp, _ = self._raw("/tutorial/tour-setup-dark.mp4", {"Range": "bytes=999999999999-"})
        self.assertEqual(resp.status, 416)
        resp, body = self._raw("/tutorial/screenshots/01-summary.jpg")
        self.assertEqual((resp.status, resp.getheader("Content-Type")), (200, "image/jpeg"))

    def test_no_path_escape(self):
        for p in ("/tutorial/../../../etc/passwd", "/tutorial/%2e%2e/%2e%2e/dashboard.py", "/tutorial/nope.mp4"):
            resp, _ = self._raw(p)
            self.assertEqual(resp.status, 404, p)


if __name__ == "__main__":
    unittest.main()
