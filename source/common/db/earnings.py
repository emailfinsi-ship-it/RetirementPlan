"""Cached next-earnings dates for the Stock Analysis tab (see source.collector.earnings).
Only a date and when it was last checked are kept; nothing here touches the network."""

from __future__ import annotations

from datetime import datetime

from source.common.db.connection import connect


def get_many(symbols) -> dict[str, dict]:
    """{symbol: {"date", "last_date", "checked_at"}} for the symbols checked before."""
    syms = [str(s).strip().upper() for s in symbols if str(s or "").strip()]
    if not syms:
        return {}
    marks = ",".join("?" * len(syms))
    with connect() as conn:
        rows = conn.execute(
            f"SELECT symbol, next_date, last_date, checked_at FROM earnings_dates WHERE symbol IN ({marks})", syms).fetchall()
    return {r["symbol"]: {"date": r["next_date"], "last_date": r["last_date"], "checked_at": r["checked_at"]} for r in rows}


def save(symbol, date_text, *, now: datetime | None = None) -> None:
    """Remember a lookup result (date_text None = "checked, nothing upcoming"). A report date that has
    gone by is moved to last_date when a newer lookup replaces it."""
    now = now or datetime.now()
    sym = str(symbol).strip().upper()
    with connect() as conn:
        old = conn.execute("SELECT next_date, last_date FROM earnings_dates WHERE symbol = ?", (sym,)).fetchone()
        last = old["last_date"] if old else None
        if old and old["next_date"] and old["next_date"] != date_text and old["next_date"] <= now.date().isoformat():
            last = old["next_date"]
        conn.execute(
            "INSERT INTO earnings_dates (symbol, next_date, last_date, checked_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET next_date = excluded.next_date, last_date = excluded.last_date, "
            "checked_at = excluded.checked_at",
            (sym, date_text, last, now.isoformat(timespec="seconds")),
        )
