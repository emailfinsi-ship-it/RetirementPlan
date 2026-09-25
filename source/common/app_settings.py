"""Tiny settings file living OUTSIDE this app's own folder, so a setting
survives replacing/re-unzipping the app -- same pattern and same reasoning
as FamilyFinanceTracker's source.common.app_settings (that module's
docstring explains the "why" in full; this is a trimmed copy for this
standalone program, deliberately not sharing a package with that app).

Stores three things, plain (never secrets -- the login password itself
lives in the Keychain, see source.common.auth_store):
  - data_dir: where retirement_plan.db lives
  - output_dir: where generated .xlsx/CSV/HTML exports land
  - bind_host: which network interface the dashboard's HTTP server
    listens on -- "127.0.0.1" (default, this Mac only) or "0.0.0.0"
    (every interface, so a Wi-Fi LAN address or a Tailscale Funnel can
    reach it too). Read once at server startup (source.webapp.
    dashboard.run), so changing it takes effect on the next restart,
    not live.
"""

from __future__ import annotations

import json
from pathlib import Path

_SETTINGS_DIR = Path.home() / "Library" / "Application Support" / "RetirementPlan"
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
