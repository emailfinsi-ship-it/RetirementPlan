"""Alerts: what raises them, dismissing, settings, e-mail and the daily job."""

from __future__ import annotations

import json
import unittest
from datetime import date
from unittest import mock

from source.common import db, secrets_store
from source.reporting import alerts
from tests.test_dashboard import DashboardTestCase

TODAY = date(2026, 10, 14)
SUMMARY = {"assumptions": {"birth_year": 1980}, "net_worth": 1_234_567}


def reset():
    for k in ("alerts_state", "alert_settings", "target_allocation", "risk_appetite"):
        db.set_meta(k, "")
    secrets_store.set_smtp_password("")


class TestEvaluate(DashboardTestCase):
    def setUp(self):
        reset()

    tearDown = setUp

    def test_chance_drop_and_low(self):
        hist = {"2026-10-07": 0.92}
        a = alerts.evaluate(SUMMARY, 0.84, [], [], hist, today=TODAY)
        self.assertEqual([x["id"] for x in a], ["chance-drop"])
        a = alerts.evaluate(SUMMARY, 0.6, [], [], {}, today=TODAY)
        self.assertEqual([x["id"] for x in a], ["chance-low"])
        self.assertEqual(alerts.evaluate(SUMMARY, 0.93, [], [], {"2026-10-07": 0.95}, today=TODAY), [])

    def test_data_check_warns_become_alerts(self):
        issues = [{"id": "x", "level": "warn", "title": "T", "detail": "D", "href": "/h"},
                  {"id": "y", "level": "info", "title": "I", "detail": "D", "href": "/h"}]
        a = alerts.evaluate(SUMMARY, 0.95, [], issues, {}, today=TODAY)
        self.assertEqual([x["id"] for x in a], ["dc:x"])

    def test_dismiss_stays_until_alert_goes_away(self):
        one = [{"id": "a", "level": "warn", "title": "t", "detail": "d", "href": "/"}]
        self.assertEqual(len(alerts.refresh(one, today=TODAY)), 1)
        alerts.dismiss("a")
        self.assertEqual(alerts.count(), 0)
        self.assertEqual(alerts.refresh(one, today=TODAY), [])  # still dismissed
        alerts.refresh([], today=TODAY)  # alert went away
        self.assertEqual(len(alerts.refresh(one, today=TODAY)), 1)  # comes back


class TestSettingsAndEmail(DashboardTestCase):
    def setUp(self):
        reset()

    tearDown = setUp

    def test_save_settings_validation_and_password_not_in_db(self):
        with self.assertRaises(ValueError):
            alerts.save_settings({"smtp_port": "abc"})
        with self.assertRaises(ValueError):
            alerts.save_settings({"email_to": "nope"})
        alerts.save_settings({"email_to": "a@b.com", "smtp_host": "smtp.x.com", "smtp_user": "a@b.com",
                              "smtp_password": "s3cret", "digest": True})
        self.assertNotIn("s3cret", db.get_meta("alert_settings"))
        self.assertEqual(secrets_store.get_smtp_password(), "s3cret")
        self.assertTrue(alerts.email_ready())

    def test_send_email_uses_smtp(self):
        alerts.save_settings({"email_to": "a@b.com", "smtp_host": "smtp.x.com", "smtp_user": "a@b.com", "smtp_password": "pw"})
        with mock.patch("source.reporting.alerts.smtplib.SMTP") as smtp:
            server = smtp.return_value
            server.__enter__.return_value = server
            alerts.send_test()
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("a@b.com", "pw")
        self.assertEqual(server.send_message.call_args[0][0]["To"], "a@b.com")

    def test_send_requires_setup(self):
        with self.assertRaises(ValueError):
            alerts.send_email("s", "b")

    def test_endpoints(self):
        status, d = self._post("/api/alert-settings", {"email_to": "z@y.com", "digest": True})
        self.assertEqual(status, 200)
        self.assertTrue(d["settings"]["digest"])
        status, _ = self._post("/api/alert-settings", {"smtp_port": "x"})
        self.assertEqual(status, 400)
        status, _ = self._post("/api/alert-test-email", {})
        self.assertEqual(status, 400)  # no server set up
        status, _ = self._post("/api/alerts-dismiss", {"all": True})
        self.assertEqual(status, 200)


class TestDailyJob(DashboardTestCase):
    def setUp(self):
        reset()

    tearDown = setUp

    def test_digest_weekly_and_mac_notice_once(self):
        alerts.save_settings({"email_to": "a@b.com", "smtp_host": "h", "smtp_user": "a@b.com", "digest": True, "mac_notify": True})
        issues = [{"id": "x", "level": "warn", "title": "Fix me", "detail": "D", "href": "/h"}]
        with mock.patch("source.reporting.alerts.send_email") as send, mock.patch("source.reporting.alerts.notify_mac", return_value=True) as mac:
            r = alerts.run_daily(SUMMARY, 0.95, [], issues, [], today=TODAY)
            self.assertTrue(r["digest"])
            self.assertEqual(r["notified"], 1)
            alerts.run_daily(SUMMARY, 0.95, [], issues, [], today=date(2026, 10, 15))
            self.assertEqual(send.call_count, 1)  # not due again for a week
            self.assertEqual(mac.call_count, 1)  # already told you about it
            alerts.run_daily(SUMMARY, 0.95, [], issues, [], today=date(2026, 10, 21))
            self.assertEqual(send.call_count, 2)
        body = send.call_args_list[0][0][1]
        self.assertIn("Fix me", body)
        self.assertIn("Not financial", body)

    def test_summary_shows_card_and_bell(self):
        self._post("/api/sample-data", {"with_linked": True})
        try:
            body = self._get("/summary.html").read().decode("utf-8")
            self.assertIn('id="alerts"', body)
            self.assertIn('id="alert-bell"', body)
            self.assertIn("Alerts &amp; weekly email", self._get("/setup.html").read().decode("utf-8"))
        finally:
            self._post("/api/sample-data", {"action": "remove"})


if __name__ == "__main__":
    unittest.main()
