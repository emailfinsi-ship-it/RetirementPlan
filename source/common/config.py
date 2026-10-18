"""Configuration and paths for the standalone Retirement Plan program.

BASE_DIR walks back up to the project root (the folder containing
source/, data/, output/, config/, logs/), so paths stay correct
regardless of how deep this file is nested -- same pattern as
FamilyFinanceTracker's source.common.config (this app is deliberately
independent of that one, not a sub-package of it, per the "standalone
new program" decision).

When bundled into a standalone app (PyInstaller -- see
scripts/build_mac_app.sh), __file__ points inside the bundle's
internal, temp-extracted library folder instead, which has no sibling
data/output/config/logs folders and (for a onefile build) may not even
persist between runs -- sys.frozen is PyInstaller's own flag for "yes,
we're running from a frozen bundle", and sys.executable is then the
actual launched binary's path, so basing BASE_DIR on that instead keeps
data/config/logs/output next to wherever the user put the app, exactly
like the plain-source layout this same code supports."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from source.common import app_settings, branding

def resolve_base_dir(*, frozen: bool, executable: str, module_file: str) -> Path:
    """Where data/, logs/, output/ and config/ live: the project root when
    running from source; next to the executable for a plain PyInstaller
    folder; and, inside a Mac app bundle, the user's own Application
    Support folder (the bundle itself must stay read-only and may live in
    /Applications)."""
    if not frozen:
        return Path(module_file).resolve().parent.parent.parent
    exe_dir = Path(executable).resolve().parent
    if any(part.endswith(".app") for part in exe_dir.parts):
        return Path.home() / "Library" / "Application Support" / branding.INTERNAL_ID
    return exe_dir


BASE_DIR = resolve_base_dir(
    frozen=bool(getattr(sys, "frozen", False)), executable=sys.executable, module_file=__file__,
)

# Demo mode (FINSI_DEMO=1, see scripts/run_demo.sh): everything lives in a
# throwaway folder, so a demo can never touch or show the real database.
DEMO = os.environ.get("FINSI_DEMO") == "1"
_DEMO_ROOT = Path(tempfile.gettempdir()) / "finsi-demo"

if DEMO:
    DATA_DIR = _DEMO_ROOT / "data"
    OUTPUT_DIR = _DEMO_ROOT / "output"
    LOG_DIR = _DEMO_ROOT / "logs"
    CONFIG_DIR = _DEMO_ROOT / "config"
else:
    _data_override = app_settings.get_data_dir()
    DATA_DIR = Path(_data_override) if _data_override else BASE_DIR / "data"

    _output_override = app_settings.get_output_dir()
    OUTPUT_DIR = Path(_output_override) if _output_override else BASE_DIR / "output"

    LOG_DIR = BASE_DIR / "logs"
    CONFIG_DIR = BASE_DIR / "config"

DB_PATH = DATA_DIR / "retirement_plan.db"
APP_LOG_PATH = LOG_DIR / "app.log"

# The dashboard's HTTP port (source.webapp.dashboard.run) -- one below
# FamilyFinanceTracker's 8899, so both can run side by side. Lives here
# (rather than as a plain constant in dashboard.py) so other modules
# that need to print/link to the dashboard's own URL (e.g. the Setup
# page's Network access card) don't have to import dashboard.py itself
# and risk a circular import (dashboard.py already imports the Setup
# page module).
DASHBOARD_PORT = int(os.environ.get("FINSI_PORT") or (8897 if DEMO else 8898))

# The user's own hand-built retirement/asset workbook -- used only for the
# ONE-TIME import into this program's own database (see
# source.importer.xlsx_import). Not read again after that; this program
# becomes the system of record going forward, and can regenerate a fresh
# .xlsx export any time (source.reporting.excel_export).
IMPORT_XLSX_NAME = "retirement_plan_import.xlsx"


def import_xlsx_path() -> Path:
    return DATA_DIR / IMPORT_XLSX_NAME


# Plaid environment: "sandbox" (fake data, safe to develop against) or
# "production" (real accounts, real money). Defaults to sandbox on purpose
# -- switching to production must be a deliberate opt-in, never accidental
# -- same convention as FamilyFinanceTracker's own config.PLAID_ENV.
PLAID_ENV = os.getenv("PLAID_ENV", "sandbox").strip().lower()

# This program's own Plaid-synced snapshot, written by source.plaid.sync
# after every sync -- portable CSV + a formatted HTML sibling, same shape
# and column names as FamilyFinanceTracker's own exports (see
# source.plaid.export for the writer).
ACCOUNT_BALANCES_CSV_NAME = "account_balances.csv"
ACCOUNT_BALANCES_HTML_NAME = "account_balances.html"
PORTFOLIO_POSITIONS_CSV_NAME = "portfolio_positions.csv"
PORTFOLIO_POSITIONS_HTML_NAME = "portfolio_positions.html"


def account_balances_csv_path() -> Path:
    return OUTPUT_DIR / ACCOUNT_BALANCES_CSV_NAME


def account_balances_html_path() -> Path:
    return OUTPUT_DIR / ACCOUNT_BALANCES_HTML_NAME


def portfolio_positions_csv_path() -> Path:
    return OUTPUT_DIR / PORTFOLIO_POSITIONS_CSV_NAME


def portfolio_positions_html_path() -> Path:
    return OUTPUT_DIR / PORTFOLIO_POSITIONS_HTML_NAME


def ensure_directories() -> None:
    for d in (DATA_DIR, OUTPUT_DIR, LOG_DIR, CONFIG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def data_dir_status() -> dict:
    default_dir = BASE_DIR / "data"
    return {"current": str(DATA_DIR), "is_custom": DATA_DIR != default_dir, "default": str(default_dir)}


def set_data_dir(new_dir) -> Path:
    global DATA_DIR, DB_PATH
    if new_dir:
        resolved = Path(new_dir).expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        old_db = DATA_DIR / "retirement_plan.db"
        new_db = resolved / "retirement_plan.db"
        if old_db.exists() and not new_db.exists():
            import shutil

            shutil.copy2(old_db, new_db)
        app_settings.set_data_dir(str(resolved))
        DATA_DIR = resolved
    else:
        app_settings.clear_data_dir()
        DATA_DIR = BASE_DIR / "data"
    DB_PATH = DATA_DIR / "retirement_plan.db"
    ensure_directories()
    return DATA_DIR


def output_dir_status() -> dict:
    default_dir = BASE_DIR / "output"
    return {"current": str(OUTPUT_DIR), "is_custom": OUTPUT_DIR != default_dir, "default": str(default_dir)}


def set_output_dir(new_dir) -> Path:
    global OUTPUT_DIR
    if new_dir:
        resolved = Path(new_dir).expanduser().resolve()
        app_settings.set_output_dir(str(resolved))
        OUTPUT_DIR = resolved
    else:
        app_settings.clear_output_dir()
        OUTPUT_DIR = BASE_DIR / "output"
    ensure_directories()
    return OUTPUT_DIR


