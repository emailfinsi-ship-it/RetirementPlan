"""Yahoo Finance as a stand-in price source for the Stock Analysis tab, the watchlist and the order form's price.

Used only when Alpaca's market data cannot be read (no Alpaca keys saved, Alpaca down or rejecting the keys, a
ticker its free IEX feed has no bars for). It goes through the yfinance library the app already bundles for
earnings dates and industries, and returns exactly the shapes source.collector.alpaca does, so the charts and
ratings need no changes. Read-only: nothing here can place or change an order. Yahoo's data is unofficial and can
lag or have gaps, so the screens say when it was the source.

Everything raises MarketDataError (an AlpacaError subclass, so the existing error handling still applies).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from source.collector import alpaca

_SYMBOL = re.compile(r"^[A-Z0-9.\-]{1,12}$")
_INTERVALS = {"1Day": "1d", "5Min": "5m", "1Min": "1m", "15Min": "15m", "1Hour": "60m"}


class MarketDataError(alpaca.AlpacaError):
    """Prices could not be read from Yahoo Finance."""


def _yf():
    try:
        import yfinance as yf
    except ImportError as exc:
        raise MarketDataError("Yahoo Finance is not available (the yfinance library is not installed).") from exc
    return yf


def _symbol(symbol) -> str:
    sym = str(symbol or "").strip().upper()
    if not _SYMBOL.match(sym):
        raise MarketDataError("Enter a stock or ETF ticker, for example AAPL or VTI.")
    return sym


def _ticker(sym: str):
    return _yf().Ticker(sym.replace(".", "-"))      # Yahoo writes BRK.B as BRK-B


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number or number in (float("inf"), float("-inf")) else number      # NaN / inf


def _iso(stamp) -> str:
    """An ISO UTC time like Alpaca's, from a pandas Timestamp / datetime (naive means UTC)."""
    dt = stamp.to_pydatetime() if hasattr(stamp, "to_pydatetime") else stamp
    if not isinstance(dt, datetime):
        return str(stamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bars_from_frame(frame) -> list[dict]:
    """{"t","o","h","l","c","v"} bars, oldest first, from a yfinance history DataFrame (rows without a close are dropped)."""
    out = []
    if frame is None or getattr(frame, "empty", True):
        return out
    for stamp, row in frame.iterrows():
        o, h, l, c = (_num(row.get(k)) for k in ("Open", "High", "Low", "Close"))
        if None in (o, h, l, c) or c <= 0:
            continue
        out.append({"t": _iso(stamp), "o": o, "h": h, "l": l, "c": c, "v": _num(row.get("Volume")) or 0.0})
    out.sort(key=lambda b: b["t"])
    return out


def get_bars(symbol: str, *, timeframe: str = "1Day", start: str, limit: int = 1000) -> list[dict]:
    """Price bars, oldest first (split-adjusted, regular hours). ``start`` is an ISO time like Alpaca's."""
    sym = _symbol(symbol)
    interval = _INTERVALS.get(timeframe)
    if interval is None:
        raise MarketDataError(f"Yahoo Finance bars are not available for {timeframe}.")
    try:
        frame = _ticker(sym).history(start=str(start)[:10], interval=interval, auto_adjust=False, prepost=False, actions=False)
    except MarketDataError:
        raise
    except Exception as exc:    # noqa: BLE001 -- network, rate limit, unknown ticker: all "cannot read prices now"
        raise MarketDataError(f"Couldn't read prices for {sym} from Yahoo Finance ({str(exc) or exc.__class__.__name__}).") from exc
    bars = _bars_from_frame(frame)
    return bars[-int(limit):] if limit else bars


def get_bars_multi(symbols: list[str], *, start: str) -> dict[str, list[dict]]:
    """Daily bars for several symbols: {symbol: bars}. A symbol that fails is empty, not an error, unless all fail."""
    syms = [_symbol(s) for s in symbols]
    out: dict[str, list[dict]] = {s: [] for s in syms}
    if not syms:
        return out
    errors: list[MarketDataError] = []

    def one(sym):
        try:
            return sym, get_bars(sym, timeframe="1Day", start=start)
        except MarketDataError as exc:
            errors.append(exc)
            return sym, []

    with ThreadPoolExecutor(max_workers=6) as pool:
        for sym, bars in pool.map(one, syms):
            out[sym] = bars
    if errors and not any(out.values()):
        raise errors[0]
    return out


def snapshot_from_bars(sym: str, bars: list[dict]) -> dict | None:
    """A quote built from daily bars: the latest bar is today's (or the last session's) and the one before it is the previous day."""
    if not bars:
        return None
    last = bars[-1]
    return {"symbol": sym, "price": last["c"], "trade_time": last["t"], "bid": None, "ask": None, "bid_size": None, "ask_size": None,
            "day": last, "prev_day": bars[-2] if len(bars) >= 2 else None}


def get_snapshot(symbol: str) -> dict:
    """Today's quote for one symbol (no bid / ask: Yahoo's free data doesn't carry them reliably)."""
    sym = _symbol(symbol)
    now = datetime.now(timezone.utc)
    bars = get_bars(sym, timeframe="1Day", start=_iso(now - timedelta(days=10)))
    snap = snapshot_from_bars(sym, bars)
    if snap is None:
        raise MarketDataError(f"No current price is available for {sym}. Check the ticker.")
    return snap


def get_snapshots(symbols: list[str], *, start: str) -> dict[str, dict]:
    bars = get_bars_multi(symbols, start=start)
    return {s: snap for s, b in bars.items() if (snap := snapshot_from_bars(s, b))}


def get_asset_name(symbol: str) -> str | None:
    """The company or fund name, or None (a nicety, never an error)."""
    sym = _symbol(symbol)
    try:
        info = _ticker(sym).info or {}
    except Exception:    # noqa: BLE001
        return None
    name = alpaca.clean_company_name(info.get("longName") or info.get("shortName") or "")
    return name or None


def _news_item(raw: dict) -> dict | None:
    body = raw.get("content") if isinstance(raw.get("content"), dict) else raw          # newer yfinance nests the story under "content"
    headline = " ".join(str(body.get("title") or "").split())
    link = body.get("canonicalUrl") or body.get("clickThroughUrl") or {}
    url = str((link.get("url") if isinstance(link, dict) else link) or body.get("link") or "").strip()
    if not headline or not url.lower().startswith(("https://", "http://")):
        return None
    summary = " ".join(str(body.get("summary") or "").split())
    provider = body.get("provider")
    source = provider.get("displayName") if isinstance(provider, dict) else body.get("publisher")
    when = body.get("pubDate") or body.get("displayTime") or ""
    if not when and body.get("providerPublishTime"):
        when = _iso(datetime.fromtimestamp(float(body["providerPublishTime"]), timezone.utc))
    return {"headline": headline[:240], "summary": summary[:280] + ("..." if len(summary) > 280 else ""),
            "source": str(source or "").strip()[:40], "url": url[:500], "time": str(when)}


def get_news(symbol: str, *, limit: int = 8) -> list[dict]:
    sym = _symbol(symbol)
    try:
        raw = _ticker(sym).news or []
    except MarketDataError:
        raise
    except Exception as exc:    # noqa: BLE001
        raise MarketDataError(f"Couldn't read headlines for {sym} from Yahoo Finance.") from exc
    items = [n for n in (_news_item(x) for x in raw if isinstance(x, dict)) if n]
    return items[: int(limit)]


_SESSION_OF_STATE = {"PRE": "pre", "PREPRE": "pre", "POST": "post", "POSTPOST": "post", "CLOSED": "post"}


def _extended_one(sym: str) -> dict | None:
    """The pre-market or after-hours price for one symbol, or None when the market is open / there is none."""
    try:
        info = _ticker(sym).info or {}
    except Exception:    # noqa: BLE001 -- a nicety: no extended price, no error
        return None
    session = _SESSION_OF_STATE.get(str(info.get("marketState") or "").upper())
    if session is None:
        return None
    pre = session == "pre"
    price = _num(info.get("preMarketPrice" if pre else "postMarketPrice"))
    if not price:
        return None
    change = _num(info.get("preMarketChange" if pre else "postMarketChange"))
    pct = _num(info.get("preMarketChangePercent" if pre else "postMarketChangePercent"))
    regular = _num(info.get("regularMarketPrice"))
    if change is None and regular:
        change = price - regular
    if pct is None and regular:
        pct = (price - regular) / regular * 100.0
    return {"symbol": sym, "session": session, "label": "Pre-market" if pre else "After hours", "price": price,
            "change": change, "change_pct": pct, "regular_price": regular}


def get_extended(symbols: list[str]) -> dict[str, dict]:
    """{symbol: {"session": "pre"|"post", "label", "price", "change", "change_pct", "regular_price"}} for the symbols that
    have an extended-hours price right now (Yahoo has no overnight-session prices)."""
    syms = list(dict.fromkeys(_symbol(s) for s in symbols))
    out: dict[str, dict] = {}
    if not syms:
        return out
    with ThreadPoolExecutor(max_workers=6) as pool:
        for sym, got in zip(syms, pool.map(_extended_one, syms)):
            if got:
                out[sym] = got
    return out


def _frame_for(frame, ysym: str, single: bool):
    """The one symbol's sub-frame of a multi-symbol yf.download() result."""
    if single:
        return frame
    try:
        return frame[ysym]
    except (KeyError, TypeError):
        return None


def get_bars_batch(symbols: list[str], *, start: str, chunk: int = 60) -> dict[str, list[dict]]:
    """Daily bars for many symbols (the screener): {symbol: bars}. Symbols Yahoo has nothing for are left empty. Fetched
    ``chunk`` at a time with yfinance's own bulk download; a chunk that fails is skipped, and only if every chunk fails
    is it an error."""
    syms = [_symbol(s) for s in symbols]
    out: dict[str, list[dict]] = {s: [] for s in syms}
    if not syms:
        return out
    yf = _yf()
    failures, chunks = 0, 0
    for i in range(0, len(syms), chunk):
        part = syms[i:i + chunk]
        chunks += 1
        ys = [s.replace(".", "-") for s in part]
        try:
            frame = yf.download(" ".join(ys), start=str(start)[:10], interval="1d", auto_adjust=False, group_by="ticker",
                                threads=True, progress=False)
        except Exception:    # noqa: BLE001 -- network / rate limit: skip this chunk
            failures += 1
            continue
        for sym, ysym in zip(part, ys):
            try:
                out[sym] = _bars_from_frame(_frame_for(frame, ysym, len(part) == 1))
            except Exception:    # noqa: BLE001
                out[sym] = []
    if failures == chunks:
        raise MarketDataError("Couldn't read prices from Yahoo Finance (network or rate limit). Try again in a minute.")
    return out


def _sum_volume(frame) -> tuple[float, float]:
    vol, oi = 0.0, 0.0
    if frame is None or getattr(frame, "empty", True):
        return vol, oi
    for _i, row in frame.iterrows():
        vol += _num(row.get("volume")) or 0.0
        oi += _num(row.get("openInterest")) or 0.0
    return vol, oi


def get_option_volume(symbol: str, *, max_expiries: int = 3, max_days: int = 45) -> dict | None:
    """Today's option volume for the nearest expiries (up to ``max_days`` out): calls, puts and their ratio. None when
    the symbol has no listed options or Yahoo has none to give."""
    sym = _symbol(symbol)
    try:
        t = _ticker(sym)
        expiries = list(t.options or [])
    except Exception:    # noqa: BLE001
        return None
    today = datetime.now(timezone.utc).date()
    use = []
    for e in expiries:
        try:
            days = (datetime.strptime(e, "%Y-%m-%d").date() - today).days
        except ValueError:
            continue
        if days >= 0 and (days <= max_days or not use):
            use.append(e)
        if len(use) >= max_expiries:
            break
    if not use:
        return None
    cv = pv = coi = poi = 0.0
    for e in use:
        try:
            chain = t.option_chain(e)
        except Exception:    # noqa: BLE001
            continue
        a, b = _sum_volume(chain.calls)
        c, d = _sum_volume(chain.puts)
        cv, pv, coi, poi = cv + a, pv + c, coi + b, poi + d
    if cv + pv <= 0:
        return None
    return {"call_volume": cv, "put_volume": pv, "ratio": (pv / cv) if cv > 0 else None,
            "call_oi": coi, "put_oi": poi, "expiries": use}


def get_option_volumes(symbols: list[str]) -> dict[str, dict]:
    """{symbol: option-volume summary} for the symbols that have one (looked up side by side)."""
    syms = list(dict.fromkeys(_symbol(s) for s in symbols))
    out: dict[str, dict] = {}
    if not syms:
        return out
    with ThreadPoolExecutor(max_workers=6) as pool:
        for sym, got in zip(syms, pool.map(get_option_volume, syms)):
            if got:
                out[sym] = got
    return out
