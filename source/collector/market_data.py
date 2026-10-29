"""Where the Stock Analysis tab, the watchlist and the order form's price get their numbers: Alpaca first, Yahoo Finance
when Alpaca cannot supply them.

Alpaca is used when keys are saved and it answers. It is skipped for a minute after it proves unreachable, rejects the keys
or rate-limits (so a down feed does not make every screen wait), and a ticker its free IEX feed has no bars for is filled in
from Yahoo. With no Alpaca keys at all, Yahoo is used straight away. Every function has the same shape as its
source.collector.alpaca twin but takes ``keys=None``; ``last_source()`` says which feed answered the most recent call in
this thread ("alpaca" or "yahoo"), so the screens can say so. Read-only: nothing here can place or change an order.

Under the test runner Yahoo is off unless a test switches ``YAHOO_ENABLED`` on, so tests never touch the network.
"""

from __future__ import annotations

import sys
import threading
import time

from source.collector import alpaca, yahoo
from source.collector.yahoo import MarketDataError

YAHOO_ENABLED: bool | None = None      # None = on, except under the test runner
BREAK_SECONDS = 60.0
_TRIP_STATUS = (0, 401, 403, 429)       # unreachable, bad keys, forbidden, rate-limited (and any 5xx)

_state = threading.local()
_lock = threading.Lock()
_down_until = 0.0


def yahoo_enabled() -> bool:
    return YAHOO_ENABLED if YAHOO_ENABLED is not None else "unittest" not in sys.modules


def _note(source: str) -> None:
    _state.source = source


def last_source() -> str:
    return getattr(_state, "source", "alpaca")


def reset() -> None:
    """Forget the Alpaca breaker and the noted source (tests, and a fresh start after new keys are saved)."""
    global _down_until
    with _lock:
        _down_until = 0.0
    _state.source = "alpaca"


def _alpaca_usable(keys) -> bool:
    return keys is not None and (time.monotonic() >= _down_until or not yahoo_enabled())


def _trip_if_down(exc: alpaca.AlpacaError) -> None:
    global _down_until
    status = getattr(exc, "status", None)
    if status in _TRIP_STATUS or (isinstance(status, int) and status >= 500):
        with _lock:
            _down_until = time.monotonic() + BREAK_SECONDS


def _try_alpaca(keys, call):
    """(result, None) from Alpaca, or (None, the AlpacaError) when it failed and Yahoo may take over."""
    if not _alpaca_usable(keys):
        return None, None
    try:
        return call(), None
    except alpaca.AlpacaError as exc:
        if not yahoo_enabled():
            raise
        _trip_if_down(exc)
        return None, exc


def _yahoo_or(err, call):
    """Run the Yahoo twin; if it fails too, report Alpaca's error when there was one (it is the more actionable)."""
    try:
        result = call()
    except MarketDataError:
        if err is not None:
            raise err
        raise
    _note("yahoo")
    return result


def get_bars(symbol: str, keys, *, timeframe: str = "1Day", start: str, limit: int = 1000, **kw) -> list[dict]:
    got, err = _try_alpaca(keys, lambda: alpaca.get_bars(symbol, keys, timeframe=timeframe, start=start, limit=limit, **kw))
    if got:
        _note("alpaca")
        return got
    if not yahoo_enabled():
        return got or []
    try:
        return _yahoo_or(err, lambda: yahoo.get_bars(symbol, timeframe=timeframe, start=start, limit=limit))
    except MarketDataError:
        if err is None and got is not None:
            return got          # Alpaca answered "no bars" and Yahoo could not help: report no bars, not an outage
        raise


def get_bars_multi(symbols: list[str], keys, *, start: str, **kw) -> dict[str, list[dict]]:
    got, err = _try_alpaca(keys, lambda: alpaca.get_bars_multi(symbols, keys, start=start, **kw))
    out = dict(got or {})
    if got is not None:
        _note("alpaca")
    missing = [s for s in dict.fromkeys(alpaca._symbol(x) for x in symbols) if not out.get(s)]
    if missing and yahoo_enabled():
        try:
            filled = _yahoo_or(err, lambda: yahoo.get_bars_multi(missing, start=start))
        except MarketDataError:
            if got is None:
                raise
            filled = {}
        for sym, bars in filled.items():
            if bars:
                out[sym] = bars
                _note("yahoo")
    for s in missing:
        out.setdefault(s, [])
    return out


def get_snapshot(symbol: str, keys, **kw) -> dict:
    got, err = _try_alpaca(keys, lambda: alpaca.get_snapshot(symbol, keys, **kw))
    if got is not None:
        _note("alpaca")
        return got
    if not yahoo_enabled():
        raise alpaca.AlpacaError("No price source is available.")
    return _yahoo_or(err, lambda: yahoo.get_snapshot(symbol))


def get_snapshots(symbols: list[str], keys, *, start: str | None = None, **kw) -> dict[str, dict]:
    """Quotes for several symbols. Only Alpaca can answer here; callers fall back to each symbol's daily bars,
    which Yahoo supplies, so with no Alpaca this returns {} and the last price comes from those bars."""
    if not _alpaca_usable(keys):
        return {}
    return alpaca.get_snapshots(symbols, keys, **kw)


def get_asset_name(symbol: str, keys, *, mode: str = "paper", **kw) -> str | None:
    name = None
    if _alpaca_usable(keys):
        name = alpaca.get_asset_name(symbol, keys, mode=mode, **kw)
    if name or not yahoo_enabled():
        return name
    try:
        return yahoo.get_asset_name(symbol)
    except MarketDataError:
        return None


def get_news(symbol: str, keys, *, limit: int = 8, **kw) -> list[dict]:
    got, err = _try_alpaca(keys, lambda: alpaca.get_news(symbol, keys, limit=limit, **kw))
    if got:
        return got
    if not yahoo_enabled():
        return got or []
    try:
        return _yahoo_or(err, lambda: yahoo.get_news(symbol, limit=limit))
    except MarketDataError:
        if got is not None:
            return got
        raise


_ext_cache: dict[str, tuple[float, dict | None]] = {}
EXTENDED_TTL = 60.0


def get_extended(symbols: list[str]) -> dict[str, dict]:
    """Pre-market / after-hours prices from Yahoo for the symbols that have one right now (kept for a minute per
    symbol). Empty when Yahoo is off or cannot be read: it is an extra, never an error."""
    if not yahoo_enabled():
        return {}
    now = time.monotonic()
    syms = list(dict.fromkeys(alpaca._symbol(s) for s in symbols))
    need = [s for s in syms if s not in _ext_cache or now - _ext_cache[s][0] > EXTENDED_TTL]
    if need:
        try:
            got = yahoo.get_extended(need)
        except MarketDataError:
            got = {}
        for s in need:
            _ext_cache[s] = (now, got.get(s))
    return {s: _ext_cache[s][1] for s in syms if _ext_cache.get(s) and _ext_cache[s][1]}
