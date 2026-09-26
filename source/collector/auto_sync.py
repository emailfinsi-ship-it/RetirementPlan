"""Runs a Plaid sync on its own once this program has gone stale for too
long, instead of only ever syncing when a person remembers to click "Sync
now" -- see source.common.app_settings' own docstring for the two knobs
(auto_sync_enabled/auto_sync_interval_days) the Setup page's "Automatic
sync" card exposes.

IMPORTANT limitation, stated plainly rather than buried: this program is
a plain foreground process (source.webapp.dashboard.run(), started by
double-clicking the app or running scripts/run_dashboard.sh) -- it is
NOT a background daemon, and this module doesn't turn it into one. It can
only ever check "is a sync overdue?" at moments this process is already
running, which today means once at startup (see dashboard.run()'s own
call to sync_if_due(), on a background thread so a slow sync never
delays the dashboard itself from becoming reachable). If this Mac goes a
full month without the app being opened even once, nothing here runs
during that time -- the very next time it IS opened, sync_if_due() sees
how overdue it is and catches up immediately, but there's no way for a
plain foreground process to wake itself up while nobody's running it.

A person who wants a sync to happen on a real, unattended monthly
schedule -- even on a day they never open this app at all -- needs an
actual OS-level scheduler for that (macOS's launchd, the standard
mechanism a launch agent would use), which is a one-time setup step in
their own Terminal that this program can't perform on their behalf (it
would mean this program modifying this Mac's system-level scheduled
tasks on its own, which is deliberately outside what it does to itself).
scripts/install_launchd_auto_sync.sh generates and explains that setup
for anyone who wants it; sync_if_due() here is the lighter-weight,
zero-setup version that already covers the common case of "I open this
dashboard every so often" without needing that.
"""

from __future__ import annotations

from datetime import datetime, timezone

from source.common import app_settings, db


def _days_since(iso_timestamp: str, *, now: datetime) -> float:
    parsed = datetime.fromisoformat(iso_timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (now - parsed).total_seconds() / 86400.0


def days_since_last_sync(*, now: datetime | None = None) -> float | None:
    """None if no linked Item has ever completed a sync (or none are
    linked at all) -- "never synced" and "synced 9999 days ago" are
    different states a caller (the Setup page's status line) should be
    able to tell apart, rather than both collapsing to some giant
    number."""
    items = db.list_plaid_items()
    synced_at = [i["last_synced_at"] for i in items if i.get("last_synced_at")]
    if not synced_at:
        return None
    now = now or datetime.now(timezone.utc)
    return min(_days_since(ts, now=now) for ts in synced_at)


def is_sync_due(*, now: datetime | None = None) -> bool:
    """True when auto-sync is on, at least one Item is linked, and either
    nothing has ever been synced or the most recent sync is at least
    auto_sync_interval_days old. False (never "due") with nothing linked
    at all -- there'd be nothing for sync_all() to do."""
    if not app_settings.get_auto_sync_enabled():
        return False
    if not db.list_plaid_items():
        return False
    age = days_since_last_sync(now=now)
    if age is None:
        return True
    return age >= app_settings.get_auto_sync_interval_days()


def sync_if_due(*, now: datetime | None = None) -> bool:
    """Runs a full Plaid sync (plus a fresh net-worth snapshot, same as a
    manual "Sync now") if and only if is_sync_due() -- otherwise a cheap
    no-op. Returns whether it actually synced, so a caller (dashboard.run,
    a test) can tell the two cases apart. Imports source.collector.sync
    and source.reporting.aggregate lazily, inside the function, to avoid
    a module-load-time import cycle with source.webapp.dashboard (which
    imports this module directly, and both of those modules already
    import dashboard indirectly via other paths)."""
    if not is_sync_due(now=now):
        return False
    from source.collector import sync as plaid_sync
    from source.reporting.aggregate import capture_net_worth_snapshot

    plaid_sync.sync_all()
    capture_net_worth_snapshot()
    return True
