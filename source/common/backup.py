"""Automatic backups of retirement_plan.db.

This is a single-user program with no undo for its own database: a bad
one-time import, a bulk delete, a stray "Clear industry", or an outright
bug could otherwise silently corrupt or lose real financial line items
with nothing to recover from. This module gives every day the app is
opened (and every workbook import -- the single riskiest write this
program does) its own timestamped copy in data/backups/, pruned to a
bounded number of generations so that folder doesn't grow forever.

No cron job, no background thread -- source.webapp.dashboard.run() calls
ensure_daily_backup() once at startup, which is a no-op after the first
time the app is opened on a given calendar day, and
source.webapp.dashboard's /api/import handler calls create_backup(
reason="pre-import") right before every import. A "Back up now" button
on the Setup page also calls create_backup(reason="manual") directly.
There's currently no in-app "restore" action (list_backups() below is
read-only, for display) -- restoring means closing the app and copying
the chosen backup file over data/retirement_plan.db by hand; see the
Setup page's Backups card for exactly where both live.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from source.common import config

BACKUP_DIR_NAME = "backups"
# How many backups to keep on disk at once. In practice this is roughly
# one per calendar day the app is opened plus one per import, so this
# comfortably covers a month-plus of ordinary daily use before the
# oldest backups start rolling off -- generous for how little a small
# SQLite file costs to keep around.
KEEP_BACKUPS = 30
_FILENAME_PREFIX = "retirement_plan-"
_FILENAME_SUFFIX = ".db"


def backup_dir() -> Path:
    """Lives inside the (possibly relocated) data directory, not a fixed
    path relative to the app -- so backups travel with the data if it's
    ever moved via the Setup page's data-location picker (config.
    set_data_dir), and restoring one never means hunting across two
    different folders."""
    return config.DATA_DIR / BACKUP_DIR_NAME


def _timestamp_slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_reason(reason: str) -> str:
    cleaned = "".join(c if (c.isalnum() or c in "-_") else "-" for c in reason).strip("-")
    return cleaned or "backup"


def _copy_db_safely(db_path: Path, dest: Path) -> None:
    """Uses sqlite3's own online backup API (Connection.backup) rather
    than a plain file copy. This program's connect() (source.common.db)
    uses SQLite's default rollback-journal mode, where a plain
    shutil.copy2 of the main .db file is normally fine since nothing is
    left uncommitted in a sidecar file -- but the backup API is used
    anyway because it's correct regardless of journal mode (including
    if this ever moves to WAL, where a raw file copy could silently
    miss pages still sitting in a separate -wal file) and costs nothing
    extra for a database this size."""
    source_conn = sqlite3.connect(str(db_path))
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()


def create_backup(reason: str = "manual") -> Path | None:
    """Copies the current database into backup_dir() with a timestamped,
    reason-tagged filename (e.g. retirement_plan-20260923-110200-
    startup.db). Returns None and does nothing if there's no database
    yet -- a brand-new install with nothing to back up. Always prunes
    down to KEEP_BACKUPS afterward, so a caller never has to remember to
    clean up itself."""
    db_path = config.DB_PATH
    if not db_path.exists():
        return None
    target_dir = backup_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / f"{_FILENAME_PREFIX}{_timestamp_slug()}-{_safe_reason(reason)}{_FILENAME_SUFFIX}"
    _copy_db_safely(db_path, dest)
    _prune_backups(target_dir)
    return dest


def _existing_backups(target_dir: Path) -> list[Path]:
    if not target_dir.exists():
        return []
    return sorted(
        target_dir.glob(f"{_FILENAME_PREFIX}*{_FILENAME_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _prune_backups(target_dir: Path) -> None:
    for stale in _existing_backups(target_dir)[KEEP_BACKUPS:]:
        stale.unlink(missing_ok=True)


def list_backups() -> list[dict]:
    """Newest first -- each entry has path/filename/size_bytes/
    modified_at, for the Setup page's Backups card (and for a future
    in-app "restore" action, if this ever grows one)."""
    return [
        {
            "path": str(p),
            "filename": p.name,
            "size_bytes": p.stat().st_size,
            "modified_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
        }
        for p in _existing_backups(backup_dir())
    ]


def has_backup_today() -> bool:
    """True if any backup (any reason) already exists whose filename
    carries today's date -- lets ensure_daily_backup() below take at
    most one "just opened the app" backup per calendar day rather than
    one on every restart during the same day's use."""
    today_slug = time.strftime("%Y%m%d")
    return any(
        b["filename"].startswith(f"{_FILENAME_PREFIX}{today_slug}-")
        for b in list_backups()
    )


def ensure_daily_backup() -> Path | None:
    """Called once at server startup (source.webapp.dashboard.run) --
    takes a backup tagged "startup" the first time the app is opened
    each calendar day, and does nothing (returns None, no-op) on a
    same-day restart. This is the "automatic" half of this module: no
    cron, no background thread, just "the first time you open the app
    today, today gets backed up" -- which is reliable precisely because
    this program only ever runs while someone's actually using it."""
    if has_backup_today():
        return None
    return create_backup(reason="startup")
