"""The Tutorial button and page: five narrated videos (one per tab), the written guide, and the Watch this video link on every tab."""

from __future__ import annotations

import http.client
import json
import re
import unittest

from source.webapp.pages import tutorial
from source.webapp.render_helpers import shell
from tests.test_dashboard import DashboardTestCase

KEYS = ("setup", "today", "myplan", "explore", "trading")


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

    def test_page_offers_one_video_per_section_and_the_guide(self):
        body = self._get("/tutorial.html").read().decode("utf-8")
        for key in KEYS:
            self.assertIn(f"/tutorial/help-{key}.mp4", body)
            self.assertIn(f'data-sec="{key}"', body)
        self.assertLess(body.index('data-sec="setup"'), body.index('data-sec="today"'))        # a new person starts with Setup
        self.assertIn("Full user guide", body)
        self.assertIn("Review my holdings", body)             # new in this version, so the guide was rebuilt
        self.assertIn("/tutorial/screenshots/01-summary.jpg", body)
        self.assertNotIn("tour-setup-dark", body)             # the earlier two long videos are gone

    def test_every_page_belongs_to_one_video(self):
        pages = [h for g in shell.NAV_GROUPS for h, _ in g] + ["summary.html", "setup.html", "setup-wizard.html", "trading.html"]
        for page in pages:
            self.assertIn(tutorial.section_for(page), KEYS, page)
        self.assertEqual(tutorial.section_for("summary.html"), "today")
        self.assertEqual(tutorial.section_for("linked-positions.html"), "myplan")
        self.assertEqual(tutorial.section_for("monte-carlo.html"), "explore")
        for page in ("trading-live.html", "etrade.html", "ibkr.html", "stock-analysis.html", "screener.html", "orders.html"):
            self.assertEqual(tutorial.section_for(page), "trading", page)
        self.assertEqual(tutorial.section_for("setup.html"), "setup")
        self.assertIsNone(tutorial.section_for("tutorial.html"))

    def test_each_tab_links_to_its_video_at_the_right_moment(self):
        chapters = json.loads((tutorial.TUTORIAL_DIR / "chapters.json").read_text(encoding="utf-8"))
        for path, key in (("/summary.html", "today"), ("/linked-positions.html", "myplan"), ("/monte-carlo.html", "explore"),
                          ("/screener.html", "trading"), ("/orders.html", "trading"), ("/setup.html", "setup")):
            body = self._get(path).read().decode("utf-8")
            m = re.search(r'href="/tutorial\.html\?s=([a-z]+)&amp;t=(\d+)#videos"', body)
            self.assertIsNotNone(m, path)
            self.assertEqual(m.group(1), key, path)
            want = ([int(c["start"]) for c in chapters[key]["chapters"] if c["page"].lstrip("/") == path.lstrip("/")] or [0])[-1]
            self.assertEqual(int(m.group(2)), want, path)
            # The About-this-page script swallows clicks on anything with the ex-btn class, so the link must not carry it.
            link = body.split('/tutorial.html?s=')[0].rsplit("<a ", 1)[1]
            self.assertNotIn("ex-btn", link)

    def test_chapters_cover_every_video(self):
        data = json.loads((tutorial.TUTORIAL_DIR / "chapters.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(data), sorted(KEYS))
        for key in KEYS:
            starts = [c["start"] for c in data[key]["chapters"]]
            self.assertTrue(starts and starts == sorted(starts), key)
            self.assertLess(starts[-1], data[key]["duration"], key)
            self.assertTrue((tutorial.TUTORIAL_DIR / f"help-{key}.mp4").is_file(), key)

    def test_video_supports_range_requests(self):
        resp, body = self._raw("/tutorial/help-setup.mp4", {"Range": "bytes=0-99"})
        self.assertEqual(resp.status, 206)
        self.assertEqual(len(body), 100)
        self.assertTrue(resp.getheader("Content-Range").startswith("bytes 0-99/"))
        resp, _ = self._raw("/tutorial/help-setup.mp4", {"Range": "bytes=999999999999-"})
        self.assertEqual(resp.status, 416)
        resp, body = self._raw("/tutorial/screenshots/01-summary.jpg")
        self.assertEqual((resp.status, resp.getheader("Content-Type")), (200, "image/jpeg"))

    def test_no_path_escape(self):
        for p in ("/tutorial/../../../etc/passwd", "/tutorial/%2e%2e/%2e%2e/dashboard.py", "/tutorial/nope.mp4"):
            resp, _ = self._raw(p)
            self.assertEqual(resp.status, 404, p)


if __name__ == "__main__":
    unittest.main()
