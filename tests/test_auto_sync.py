import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from source.common import app_settings, db
from source.collector import auto_sync
from tests.testing_utils import TempConfigTestCase


class AutoSyncTestCase(TempConfigTestCase):
    """TempConfigTestCase gives auto_sync.py's db.* calls a clean temp
    database; app_settings.py stores its own settings.json OUTSIDE that
    (see its own module docstring -- deliberately survives a data_dir
    change), so it needs its own patch here too, same pattern
    tests.test_dashboard.DashboardTestCase already uses for the same
    reason."""

    def setUp(self):
        super().setUp()
        tmp = Path(self._tmpdir.name)
        self._settings_patches = [
            patch.object(app_settings, "_SETTINGS_DIR", tmp / "app_settings"),
            patch.object(app_settings, "_SETTINGS_PATH", tmp / "app_settings" / "settings.json"),
        ]
        for p in self._settings_patches:
            p.start()

    def tearDown(self):
        for p in self._settings_patches:
            p.stop()
        super().tearDown()

    def _link_item(self, *, last_synced_at=None):
        db.upsert_plaid_item(
            item_key="k", plaid_item_id="item-1", institution_id=None, institution_name="Bank",
            products=["investments"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        if last_synced_at:
            db.mark_plaid_item_synced("k", last_synced_at)


class TestAppSettingsAutoSyncDefaults(AutoSyncTestCase):
    def test_defaults(self):
        self.assertTrue(app_settings.get_auto_sync_enabled())
        self.assertEqual(app_settings.get_auto_sync_interval_days(), 30)

    def test_round_trips(self):
        app_settings.set_auto_sync_enabled(False)
        app_settings.set_auto_sync_interval_days(7)
        self.assertFalse(app_settings.get_auto_sync_enabled())
        self.assertEqual(app_settings.get_auto_sync_interval_days(), 7)

    def test_interval_days_is_never_zero_or_negative(self):
        app_settings.set_auto_sync_interval_days(0)
        self.assertEqual(app_settings.get_auto_sync_interval_days(), 1)
        app_settings.set_auto_sync_interval_days(-5)
        self.assertEqual(app_settings.get_auto_sync_interval_days(), 1)


class TestDaysSinceLastSync(AutoSyncTestCase):
    def test_none_when_nothing_linked(self):
        self.assertIsNone(auto_sync.days_since_last_sync())

    def test_none_when_linked_but_never_synced(self):
        self._link_item(last_synced_at=None)
        self.assertIsNone(auto_sync.days_since_last_sync())

    def test_computes_days_since_the_most_recent_sync(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        self._link_item(last_synced_at=(now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        self.assertAlmostEqual(auto_sync.days_since_last_sync(now=now), 5.0, places=3)

    def test_uses_the_most_recently_synced_item_across_several(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        self._link_item(last_synced_at=(now - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        db.upsert_plaid_item(
            item_key="k2", plaid_item_id="item-2", institution_id=None, institution_name="Other Bank",
            products=["investments"], environment="sandbox", linked_at="2026-09-01T00:00:00+00:00",
        )
        db.mark_plaid_item_synced("k2", (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        self.assertAlmostEqual(auto_sync.days_since_last_sync(now=now), 2.0, places=3)


class TestIsSyncDue(AutoSyncTestCase):
    def test_false_when_disabled(self):
        self._link_item(last_synced_at=None)
        app_settings.set_auto_sync_enabled(False)
        self.assertFalse(auto_sync.is_sync_due())

    def test_false_when_nothing_linked(self):
        self.assertFalse(auto_sync.is_sync_due())

    def test_true_when_linked_but_never_synced(self):
        self._link_item(last_synced_at=None)
        self.assertTrue(auto_sync.is_sync_due())

    def test_false_when_recently_synced(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        self._link_item(last_synced_at=(now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        self.assertFalse(auto_sync.is_sync_due(now=now))

    def test_true_once_past_the_interval(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        self._link_item(last_synced_at=(now - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        self.assertTrue(auto_sync.is_sync_due(now=now))

    def test_custom_interval_is_respected(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        app_settings.set_auto_sync_interval_days(7)
        self._link_item(last_synced_at=(now - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        self.assertTrue(auto_sync.is_sync_due(now=now))


class TestSyncIfDue(AutoSyncTestCase):
    def test_does_nothing_and_returns_false_when_not_due(self):
        with patch("source.collector.sync.sync_all") as mock_sync:
            result = auto_sync.sync_if_due()
        self.assertFalse(result)
        mock_sync.assert_not_called()

    def test_runs_a_sync_and_snapshot_when_due(self):
        self._link_item(last_synced_at=None)
        with patch("source.collector.sync.sync_all") as mock_sync, \
             patch("source.reporting.aggregate.capture_net_worth_snapshot") as mock_snapshot:
            result = auto_sync.sync_if_due()
        self.assertTrue(result)
        mock_sync.assert_called_once()
        mock_snapshot.assert_called_once()


if __name__ == "__main__":
    unittest.main()
