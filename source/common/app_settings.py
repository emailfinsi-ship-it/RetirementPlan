"""Tiny settings file living OUTSIDE this app's own folder, so a setting
survives replacing/re-unzipping the app -- same pattern and same reasoning
as FamilyFinanceTracker's source.common.app_settings (that module's
docstring explains the "why" in full; this is a trimmed copy for this
standalone program, deliberately not sharing a package with that app).

Stores these things, plain (never secrets -- the login password itself
lives in the Keychain, see source.common.auth_store):
  - data_dir: where retirement_plan.db lives
  - output_dir: where generated .xlsx/CSV/HTML exports land
  - bind_host: which network interface the dashboard's HTTP server
    listens on -- "127.0.0.1" (default, this Mac only) or "0.0.0.0"
    (every interface, so a Wi-Fi LAN address or a Tailscale Funnel can
    reach it too). Read once at server startup (source.webapp.
    dashboard.run), so changing it takes effect on the next restart,
    not live.
  - auto_sync_enabled / auto_sync_interval_days: whether source.collector.
    auto_sync.sync_if_due() should pull fresh Plaid data on its own once
    this program has gone stale for that many days -- see that module's
    own docstring for exactly when it fires (only when the app is
    actually opened; this program is a plain foreground process, not a
    background daemon, so it can't do anything on a day nobody opens it).
"""

from __future__ import annotations

import json
from pathlib import Path

from source.common import branding

_SETTINGS_DIR = Path.home() / "Library" / "Application Support" / branding.INTERNAL_ID
_SETTINGS_PATH = _SETTINGS_DIR / "settings.json"


def _read() -> dict:
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write(data: dict) -> None:
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_data_dir() -> str | None:
    return _read().get("data_dir") or None


def set_data_dir(path: str) -> None:
    data = _read()
    data["data_dir"] = path
    _write(data)


def clear_data_dir() -> None:
    data = _read()
    data.pop("data_dir", None)
    _write(data)


def get_output_dir() -> str | None:
    return _read().get("output_dir") or None


def set_output_dir(path: str) -> None:
    data = _read()
    data["output_dir"] = path
    _write(data)


def clear_output_dir() -> None:
    data = _read()
    data.pop("output_dir", None)
    _write(data)


_DEFAULT_BIND_HOST = "127.0.0.1"


def get_bind_host() -> str:
    return _read().get("bind_host") or _DEFAULT_BIND_HOST


def set_bind_host(host: str) -> None:
    data = _read()
    data["bind_host"] = host
    _write(data)


_DEFAULT_AUTO_SYNC_INTERVAL_DAYS = 30


def get_auto_sync_enabled() -> bool:
    # On by default -- a person who's never touched this setting gets
    # the "don't let this go stale" behavior automatically, same as
    # every other Setup-page default in this program.
    value = _read().get("auto_sync_enabled")
    return True if value is None else bool(value)


def set_auto_sync_enabled(enabled: bool) -> None:
    data = _read()
    data["auto_sync_enabled"] = bool(enabled)
    _write(data)


def get_auto_sync_interval_days() -> int:
    try:
        days = int(_read().get("auto_sync_interval_days") or _DEFAULT_AUTO_SYNC_INTERVAL_DAYS)
    except (TypeError, ValueError):
        return _DEFAULT_AUTO_SYNC_INTERVAL_DAYS
    return days if days > 0 else _DEFAULT_AUTO_SYNC_INTERVAL_DAYS


def set_auto_sync_interval_days(days: int) -> None:
    data = _read()
    data["auto_sync_interval_days"] = max(1, int(days))
    _write(data)


_DEFAULT_BACKUP_KEEP = 3
_MAX_BACKUP_KEEP = 100


def get_backup_keep() -> int:
    """How many automatic backups of the database to keep (default 3)."""
    try:
        keep = int(_read().get("backup_keep") or _DEFAULT_BACKUP_KEEP)
    except (TypeError, ValueError):
        return _DEFAULT_BACKUP_KEEP
    return min(max(keep, 1), _MAX_BACKUP_KEEP)


def set_backup_keep(keep: int) -> None:
    data = _read()
    data["backup_keep"] = min(max(int(keep), 1), _MAX_BACKUP_KEEP)
    _write(data)
