"""Saved screens: keep a screen under a name, re-run it in one click, and (optionally) be told when it finds something new.

A saved screen is the normalized filter set (see filters.normalize) plus the words you typed. Everything is a small JSON list in
the ``meta`` table. A screen marked "watch" is re-run by the app's once-a-day background job (``run_due``); symbols that match
now but did not at the last look are its "new matches", which show up in the alerts bell (``alert_items``) and, when switched
on in the alert settings, as a Mac notification. Looking at a screen yourself (``mark_seen``) clears its new matches."""

from __future__ import annotations

import json
import secrets
from datetime import datetime

from source.common import db
from source.screener import engine, filters

_KEY = "screener_saved"
MAX_SAVED = 20
MAX_NAME = 40
MAX_KEPT = 300          # symbols remembered per screen for the "what is new" comparison


def _load() -> list[dict]:
    raw = db.get_meta(_KEY)
    try:
        data = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [d for d in data if isinstance(d, dict) and d.get("id") and isinstance(d.get("filters"), dict)] if isinstance(data, list) else []


def _store(items: list[dict]) -> None:
    db.set_meta(_KEY, json.dumps(items))


def _public(item: dict) -> dict:
    return {"id": item["id"], "name": item.get("name") or "Saved screen", "text": item.get("text") or "", "filters": item["filters"],
            "summary": filters.describe(item["filters"]), "watch": bool(item.get("watch")), "last_run": item.get("last_run") or "",
            "matches": len(item.get("matches") or []), "new": list(item.get("new") or []), "error": item.get("error") or ""}


def list_scans() -> list[dict]:
    return [_public(i) for i in _load()]


def get(scan_id: str) -> dict | None:
    for i in _load():
        if i["id"] == str(scan_id or ""):
            return i
    return None


def save(name: str, raw_filters, text: str = "", watch: bool = False) -> dict:
    """Saves (or replaces the screen with the same name). Raises ValueError for a missing name or a full list."""
    name = " ".join(str(name or "").split())[:MAX_NAME]
    if not name:
        raise ValueError("Give the screen a short name first, for example \"Oversold tech\".")
    f = filters.normalize(raw_filters)
    items = _load()
    same = next((i for i in items if i["name"].lower() == name.lower()), None)
    if same is None and len(items) >= MAX_SAVED:
        raise ValueError(f"You can keep up to {MAX_SAVED} saved screens. Delete one first.")
    if same is None:
        same = {"id": secrets.token_hex(4), "matches": [], "new": [], "last_run": "", "error": ""}
        items.append(same)
    else:
        same["matches"], same["new"] = [], []           # different filters now: start the comparison again
    same.update({"name": name, "filters": f, "text": str(text or "")[:600], "watch": bool(watch)})
    _store(items)
    return _public(same)


def delete(scan_id: str) -> None:
    _store([i for i in _load() if i["id"] != str(scan_id or "")])


def set_watch(scan_id: str, watch: bool) -> dict:
    items = _load()
    for i in items:
        if i["id"] == str(scan_id or ""):
            i["watch"] = bool(watch)
            if not watch:
                i["new"] = []
            _store(items)
            return _public(i)
    raise ValueError("That saved screen no longer exists.")


def mark_seen(scan_id: str, symbols) -> dict:
    """You have looked at this screen's results: remember them as the comparison point and clear its new matches."""
    items = _load()
    syms = [str(s).upper() for s in (symbols or []) if str(s).strip()][:MAX_KEPT]
    for i in items:
        if i["id"] == str(scan_id or ""):
            i["matches"], i["new"] = syms, []
            i["last_run"] = datetime.now().isoformat(timespec="minutes")
            _store(items)
            return _public(i)
    raise ValueError("That saved screen no longer exists.")


def check(scan_id: str, *, scan=None, today: str | None = None) -> dict:
    """Re-runs one saved screen now and records what is new since it was last looked at. The first look only sets the baseline
    (everything that matches today would otherwise be "new")."""
    scan = scan or engine.scan
    items = _load()
    for i in items:
        if i["id"] != str(scan_id or ""):
            continue
        first = not i.get("last_run")
        try:
            result = scan({**i["filters"], "limit": max(i["filters"].get("limit") or 50, 50)})
            now = [r["symbol"] for r in result.get("rows") or []][:MAX_KEPT]
            had = set(i.get("matches") or [])
            fresh = [] if first else [s for s in now if s not in had]
            i["new"] = list(dict.fromkeys((i.get("new") or []) + fresh))[:MAX_KEPT] if not first else []
            i["matches"], i["error"] = now, ""
        except Exception as exc:        # noqa: BLE001 -- a data hiccup must not stop the other screens being checked
            i["error"] = (str(exc) or exc.__class__.__name__)[:200]
        i["last_run"] = (today + "T00:00") if today else datetime.now().isoformat(timespec="minutes")
        _store(items)
        return _public(i)
    raise ValueError("That saved screen no longer exists.")


def run_due(*, scan=None, today: str | None = None) -> list[dict]:
    """Checks every watched screen that has not been checked today. Called from the daily background job."""
    today = today or datetime.now().date().isoformat()
    out = []
    for i in _load():
        if i.get("watch") and (i.get("last_run") or "")[:10] != today:
            out.append(check(i["id"], scan=scan, today=today))
    return out


def alert_items() -> list[dict]:
    """One alert per watched screen with new matches (for the alerts bell). Reads what was stored; never scans."""
    out = []
    for i in _load():
        new = i.get("new") or []
        if i.get("watch") and new:
            more = f" (+{len(new) - 6} more)" if len(new) > 6 else ""
            out.append({"id": f"scan:{i['id']}:{(i.get('last_run') or '')[:10]}", "level": "info",
                        "title": f"Your screen \"{i['name']}\" has {len(new)} new match{'es' if len(new) != 1 else ''}",
                        "detail": ", ".join(new[:6]) + more, "href": f"/screener.html?scan={i['id']}"})
    return out
