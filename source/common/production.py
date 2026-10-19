"""Everyday production safeguards: keep the data files private to your Mac
user, say whether the disk is encrypted, collect a privacy-safe diagnostics
report for support, and (only when you press the button) check for a newer
version. Nothing here sends anything anywhere on its own."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from source.common import app_settings, branding, config


# ---- keeping the data files private -------------------------------------

def protect_files() -> int:
    """Owner-only permissions on the database, its backups and the logs, so
    other accounts on the same Mac cannot read them. Best effort; returns how
    many items it tightened."""
    done = 0
    targets = [(config.DATA_DIR, 0o700), (config.DB_PATH, 0o600), (config.LOG_DIR, 0o700)]
    for sub in ("backups",):
        targets.append((config.DATA_DIR / sub, 0o700))
    try:
        for f in (config.DATA_DIR / "backups").glob("*"):
            targets.append((f, 0o600))
    except OSError:
        pass
    for path, mode in targets:
        try:
            if path.exists() and (path.stat().st_mode & 0o777) != mode:
                os.chmod(path, mode)
                done += 1
        except OSError:
            pass
    return done


def filevault_status() -> bool | None:
    """True/False on a Mac (is the disk encrypted?), None when it can't be told."""
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(["fdesetup", "status"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if "FileVault is On" in out:
        return True
    if "FileVault is Off" in out:
        return False
    return None


# ---- diagnostics -----------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_LONG_NUMBER = re.compile(r"\b\d{6,}\b")
_SECRETISH = re.compile(r"(?i)(secret|token|password|api[_-]?key)(\W+)([^\s,;]+)")


def redact(text: str) -> str:
    """Strips things that must never leave the machine in a support report."""
    home = str(Path.home())
    text = text.replace(home, "~")
    text = _EMAIL.sub("<email>", text)
    text = _SECRETISH.sub(lambda m: f"{m.group(1)}{m.group(2)}<hidden>", text)
    return _LONG_NUMBER.sub("<number>", text)


def _tail(path: Path, lines: int = 150) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(none)"


def diagnostics_text() -> str:
    """A plain-text report you can attach to a support email. It holds versions,
    sizes and recent log lines, never balances, names or passwords."""
    try:
        db_size = config.DB_PATH.stat().st_size
    except OSError:
        db_size = 0
    fv = filevault_status()
    parts = [
        f"{branding.PRODUCT_NAME} diagnostics",
        f"Version: {branding.APP_VERSION}",
        f"Created: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"System: {platform.platform()}",
        f"Python: {platform.python_version()} ({'packaged app' if getattr(sys, 'frozen', False) else 'from source'})",
        f"Data folder: {config.DATA_DIR}",
        f"Database size: {db_size / 1024:.0f} KB",
        f"Disk encryption (FileVault): {'on' if fv else 'off' if fv is False else 'unknown'}",
        "",
        "--- recent app log ---",
        _tail(config.APP_LOG_PATH),
        "",
        "--- recent launch log ---",
        _tail(config.LOG_DIR / "launch.log"),
    ]
    return redact("\n".join(parts)) + "\n"


# ---- update check ---------------------------------------------------------------

def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4]) or (0,)


def newer_than_installed(candidate: str) -> bool:
    return _version_tuple(candidate) > _version_tuple(branding.APP_VERSION)


def check_for_update(*, fetch=None) -> dict:
    """Asks the update feed (one small JSON file you host: {"version": "1.2.0",
    "url": "https://...", "notes": "..."}) whether a newer version exists.
    Only ever runs when the person presses "Check for updates"."""
    url = app_settings.get_update_feed_url()
    if not url:
        return {"ok": True, "configured": False, "message": "No update address is set up, so this copy never checks. You are on version " + branding.APP_VERSION + "."}
    if not url.lower().startswith("https://"):
        return {"ok": False, "configured": True, "message": "The update address must start with https://."}
    try:
        if fetch is not None:
            data = fetch(url)
        else:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": f"{branding.INTERNAL_ID}/{branding.APP_VERSION}"}), timeout=6) as resp:
                data = json.loads(resp.read(100_000).decode("utf-8"))
        latest = str(data["version"])
    except Exception:
        return {"ok": False, "configured": True, "message": "Could not reach the update address just now. Try again later."}
    link = str(data.get("url") or "")
    if not link.lower().startswith("https://"):
        link = ""
    if newer_than_installed(latest):
        return {"ok": True, "configured": True, "update": True, "latest": latest, "url": link, "notes": str(data.get("notes") or "")[:500],
                "message": f"Version {latest} is available (you have {branding.APP_VERSION})."}
    return {"ok": True, "configured": True, "update": False, "latest": latest, "message": f"You are up to date (version {branding.APP_VERSION})."}
