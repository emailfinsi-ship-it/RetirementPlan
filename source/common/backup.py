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

from source.common import app_settings, config

BACKUP_DIR_NAME = "backups"
# Default number of backups kept on disk. The user can change it on the
# Setup page (stored in app_settings); keep_count() is what code uses.
KEEP_BACKUPS = 3
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
    down to keep_count() afterward, so a caller never has to remember to
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
    """Only ever returns files that were still really there at the
    moment this ran -- glob() itself only matches what's currently on
    disk, but the gap between that and the stat() call below (needed to
    sort by mtime) is a real window: source.webapp.dashboard.run() uses
    a ThreadingHTTPServer, so one request's create_backup() (which
    prunes old backups right after writing the new one) can delete a
    file a concurrent request is in the middle of listing here. Rather
    than letting a vanished file's stat() blow up the whole page with a
    500, just leave it out -- it's not a real backup anymore either
    way."""
    if not target_dir.exists():
        return []
    dated: list[tuple[Path, float]] = []
    for p in target_dir.glob(f"{_FILENAME_PREFIX}*{_FILENAME_SUFFIX}"):
        try:
            dated.append((p, p.stat().st_mtime))
        except FileNotFoundError:
            continue
    dated.sort(key=lambda pair: pair[1], reverse=True)
    return [p for p, _ in dated]


def keep_count() -> int:
    """How many backups to keep: the user's Setup-page choice when they
    made one, else the KEEP_BACKUPS default."""
    if app_settings._read().get("backup_keep"):
        return app_settings.get_backup_keep()
    return KEEP_BACKUPS


def _prune_backups(target_dir: Path) -> None:
    for stale in _existing_backups(target_dir)[keep_count():]:
        stale.unlink(missing_ok=True)


def prune_backups() -> None:
    """Deletes backups beyond keep_count(), oldest first."""
    _prune_backups(backup_dir())


def list_backups() -> list[dict]:
    """Newest first -- each entry has path/filename/size_bytes/
    modified_at, for the Setup page's Backups card (and for a future
    in-app "restore" action, if this ever grows one). Only ever lists
    files that actually exist -- see _existing_backups' own docstring
    on the concurrent-prune race this (and the second stat() call here,
    guarded the same way) protects against."""
    rows = []
    for p in _existing_backups(backup_dir()):
        try:
            stat = p.stat()
        except FileNotFoundError:
            continue
        rows.append({
            "path": str(p),
            "filename": p.name,
            "size_bytes": stat.st_size,
            "modified_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
        })
    return rows


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
        prune_backups()
        return None
    return create_backup(reason="startup")
