"""The Stock Analysis tab's watchlist: a short list of tickers (and an optional
one-line note for each). Only the ticker and note are kept here; prices are read
from Alpaca every time the table is shown."""

from __future__ import annotations

import re
from datetime import datetime

from source.common.db.connection import connect

MAX_SYMBOLS = 50
MAX_NOTE = 120
_SYMBOL = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")  # same shape Alpaca's client accepts


def clean_symbol(value) -> str:
    sym = str(value or "").strip().upper()
    if not _SYMBOL.match(sym):
        raise ValueError(f"'{str(value or '').strip()[:12]}' is not a ticker. Use a stock or ETF symbol such as AAPL or VTI.")
    return sym


def list_items() -> list[dict]:
    """Oldest-added first, so the table keeps the order the owner built it in."""
    with connect() as conn:
        rows = conn.execute("SELECT symbol, note, added_at FROM watchlist ORDER BY added_at, symbol").fetchall()
    return [{"symbol": r["symbol"], "note": r["note"], "added_at": r["added_at"]} for r in rows]


def list_symbols() -> list[str]:
    return [i["symbol"] for i in list_items()]


def add(symbols) -> list[str]:
    """Adds one or several tickers (a list, or text separated by commas, spaces or
    new lines). Already-listed tickers are skipped. Returns the ones newly added;
    raises ValueError for a bad ticker (nothing is added then) or a full list."""
    if isinstance(symbols, str):
        symbols = re.split(r"[,\s;]+", symbols)
    wanted: list[str] = []
    for raw in symbols or []:
        if str(raw or "").strip():
            sym = clean_symbol(raw)
            if sym not in wanted:
                wanted.append(sym)
    if not wanted:
        raise ValueError("Type a ticker to add, for example AAPL.")
    have = set(list_symbols())
    fresh = [s for s in wanted if s not in have]
    if len(have) + len(fresh) > MAX_SYMBOLS:
        raise ValueError(f"The watchlist holds up to {MAX_SYMBOLS} tickers. Remove one first.")
    stamp = datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        for sym in fresh:
            conn.execute("INSERT INTO watchlist (symbol, added_at) VALUES (?, ?)", (sym, stamp))
    return fresh


def remove(symbol) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM watchlist WHERE symbol = ?", (clean_symbol(symbol),))


def set_note(symbol, note) -> None:
    sym = clean_symbol(symbol)
    with connect() as conn:
        conn.execute("UPDATE watchlist SET note = ? WHERE symbol = ?", (str(note or "").strip()[:MAX_NOTE], sym))


def cached_names(symbols) -> dict[str, str]:
    """{symbol: company name} for the symbols whose name was looked up before."""
    syms = [clean_symbol(x) for x in symbols]
    if not syms:
        return {}
    marks = ",".join("?" * len(syms))
    with connect() as conn:
        rows = conn.execute(f"SELECT symbol, name FROM symbol_names WHERE symbol IN ({marks})", syms).fetchall()
    return {r["symbol"]: r["name"] for r in rows}


def remember_name(symbol, name) -> None:
    name = str(name or "").strip()[:120]
    if not name:
        return
    with connect() as conn:
        conn.execute(
            "INSERT INTO symbol_names (symbol, name) VALUES (?, ?) ON CONFLICT(symbol) DO UPDATE SET name = excluded.name",
            (clean_symbol(symbol), name),
        )
