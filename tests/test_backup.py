"""source.common.backup -- automatic timestamped copies of
retirement_plan.db, added per the user's "implement automatic backup"
request. TempConfigTestCase already points config.DATA_DIR/DB_PATH at a
fresh temp dir with an initialized database for every test here."""

from __future__ import annotations

import os
import sqlite3
import time

from source.common import backup, config, db
from tests.testing_utils import TempConfigTestCase


class TestCreateBackup(TempConfigTestCase):
    def test_returns_none_when_no_database_exists_yet(self):
        config.DB_PATH.unlink()
        self.assertIsNone(backup.create_backup())

    def test_creates_a_file_in_backup_dir(self):
        dest = backup.create_backup(reason="test")
        self.assertIsNotNone(dest)
        self.assertTrue(dest.exists())
        self.assertEqual(dest.parent, backup.backup_dir())

    def test_filename_carries_the_reason(self):
        dest = backup.create_backup(reason="pre-import")
        self.assertIn("pre-import", dest.name)

    def test_reason_is_sanitized_to_safe_characters(self):
        dest = backup.create_backup(reason="weird/reason with spaces!")
        # No path separators or spaces made it into the filename -- it's
        # still a single file directly inside backup_dir().
        self.assertEqual(dest.parent, backup.backup_dir())
        self.assertNotIn(" ", dest.name)
        self.assertNotIn("/", dest.name.replace(str(dest.parent), ""))

    def test_backup_is_a_real_copy_of_the_database_contents(self):
        db.set_assumptions({"expected_return": "0.08"})
        dest = backup.create_backup(reason="test")
        conn = sqlite3.connect(str(dest))
        try:
            row = conn.execute("SELECT value FROM assumptions WHERE key = 'expected_return'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "0.08")

    def test_backup_dir_follows_a_relocated_data_dir(self):
        # backup_dir() reads config.DATA_DIR live, not a value captured
        # at import time -- so it moves if the Setup page's data
        # location is ever changed (config.set_data_dir).
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as other:
            other_path = Path(other) / "data"
            other_path.mkdir()
            with self._patch(config, "DATA_DIR", other_path):
                self.assertEqual(backup.backup_dir(), other_path / "backups")

    def _patch(self, obj, attr, value):
        from unittest.mock import patch

        return patch.object(obj, attr, value)


class TestPruneBackups(TempConfigTestCase):
    def test_keeps_at_most_keep_backups_entries(self):
        original_keep = backup.KEEP_BACKUPS
        backup.KEEP_BACKUPS = 3
        try:
            for i in range(5):
                backup.create_backup(reason=f"r{i}")
            self.assertEqual(len(backup.list_backups()), 3)
        finally:
            backup.KEEP_BACKUPS = original_keep

    def test_pruning_removes_the_oldest_first(self):
        original_keep = backup.KEEP_BACKUPS
        # High enough that create_backup's own internal prune (it prunes
        # after every call) doesn't remove anything while these 4 are
        # being created -- pruning down to just 2 is done explicitly,
        # once, below, so the assertion is against a single deterministic
        # prune rather than 4 interleaved ones.
        backup.KEEP_BACKUPS = 100
        try:
            paths = [backup.create_backup(reason=f"r{i}") for i in range(4)]
            # Force a deterministic mtime order (1-second filename
            # resolution means creation order alone isn't reliable to
            # assert against) -- oldest (r0) gets the smallest mtime.
            now = time.time()
            for i, p in enumerate(paths):
                os.utime(p, (now + i, now + i))
            backup.KEEP_BACKUPS = 2
            backup._prune_backups(backup.backup_dir())
            remaining = {b["filename"] for b in backup.list_backups()}
            self.assertEqual(remaining, {paths[2].name, paths[3].name})
        finally:
            backup.KEEP_BACKUPS = original_keep


class TestListBackups(TempConfigTestCase):
    def test_empty_when_none_taken_yet(self):
        self.assertEqual(backup.list_backups(), [])

    def test_newest_first(self):
        p1 = backup.create_backup(reason="first")
        p2 = backup.create_backup(reason="second")
        now = time.time()
        os.utime(p1, (now, now))
        os.utime(p2, (now + 10, now + 10))
        entries = backup.list_backups()
        self.assertEqual(entries[0]["filename"], p2.name)
        self.assertEqual(entries[1]["filename"], p1.name)

    def test_entries_report_filename_size_and_modified_at(self):
        backup.create_backup(reason="test")
        entries = backup.list_backups()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertIn("filename", entry)
        self.assertIn("modified_at", entry)
        self.assertGreater(entry["size_bytes"], 0)


class TestEnsureDailyBackup(TempConfigTestCase):
    def test_first_call_of_the_day_creates_a_backup(self):
        self.assertEqual(backup.list_backups(), [])
        dest = backup.ensure_daily_backup()
        self.assertIsNotNone(dest)
        self.assertEqual(len(backup.list_backups()), 1)

    def test_a_second_call_the_same_day_is_a_no_op(self):
        backup.ensure_daily_backup()
        result = backup.ensure_daily_backup()
        self.assertIsNone(result)
        self.assertEqual(len(backup.list_backups()), 1)

    def test_does_not_interfere_with_a_manual_backup_taken_the_same_day(self):
        backup.ensure_daily_backup()
        backup.create_backup(reason="manual")
        # Both the startup and the manual backup exist -- ensure_daily_
        # backup only skips *itself* on a repeat call, it doesn't
        # prevent other reasons from adding their own backups.
        self.assertEqual(len(backup.list_backups()), 2)
        self.assertIsNone(backup.ensure_daily_backup())
        self.assertEqual(len(backup.list_backups()), 2)


if __name__ == "__main__":
    import unittest

    unittest.main()
