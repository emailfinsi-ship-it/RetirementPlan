"""Next earnings report dates, for the Stock Analysis tab.

Dates come from Yahoo Finance through the yfinance library (already used for industry
names; no account or key). Alpaca's market data has no earnings calendar. Results are
cached in the database (db.earnings_db) and refreshed when older than ``MAX_AGE``, so the
page is quick and Yahoo is not asked on every look. Reading dates never places an order.

Everything here fails soft: if the library is missing or Yahoo cannot be reached the
cached date (if any) is kept and the caller is told the lookup was unavailable."""

from __future__ import annotations

import warnings
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta

from source.common import db

warnings.filterwarnings("ignore", message=r"Timestamp\.utcnow is deprecated")

MAX_AGE = timedelta(hours=12)
MAX_SYMBOLS = 80
_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="earnings")
_inflight: dict[str, object] = {}


class EarningsUnavailable(Exception):
    """The earnings source cannot be used right now (library missing or no network)."""


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_calendar(calendar, floor: date) -> str | None:
    """The first date on or after ``floor`` in a yfinance ``Ticker.calendar`` result, as
    YYYY-MM-DD, or None. (Callers pass the Monday of this week, so a report from earlier this week still counts.) Older yfinance returns a DataFrame, newer a dict; both are read."""
    raw = None
    if isinstance(calendar, dict):
        raw = calendar.get("Earnings Date")
    elif calendar is not None and hasattr(calendar, "get"):
        raw = calendar.get("Earnings Date")
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        try:
            raw = list(raw)
        except TypeError:
            raw = [raw]
    days = sorted(d for d in (_as_date(x) for x in raw) if d is not None and d >= floor)
    return days[0].isoformat() if days else None


def fetch_next(symbol: str, today: date | None = None) -> str | None:
    """Ask Yahoo for one ticker's next earnings date. None means nothing upcoming (an ETF, or
    none announced); raises EarningsUnavailable if Yahoo cannot be asked at all."""
    today = today or date.today()
    try:
        import yfinance as yf
    except ImportError as exc:
        raise EarningsUnavailable("yfinance is not installed (pip install yfinance)") from exc
    try:
        calendar = yf.Ticker(symbol.replace(".", "-")).calendar
    except Exception as exc:     # network, rate limit, unknown ticker: all just "cannot say now"
        raise EarningsUnavailable(str(exc) or exc.__class__.__name__) from exc
    return parse_calendar(calendar, week_bounds(today)[0])


def _is_fresh(entry: dict | None, today: date, now: datetime) -> bool:
    if not entry:
        return False
    try:
        checked = datetime.fromisoformat(entry["checked_at"])
    except (ValueError, TypeError):
        return False
    if now - checked >= MAX_AGE:
        return False
    d = _as_date(entry.get("date"))
    if d is not None and d < today and checked.date() <= d:
        return False        # looked up on or before the report day, which has now passed: ask for the next one
    return True


def _result(symbol: str, entry: dict | None, today: date) -> dict:
    d = _as_date((entry or {}).get("date"))
    last = _as_date((entry or {}).get("last_date"))
    return {"symbol": symbol, "known": entry is not None, "date": d.isoformat() if d else None,
            "days": (d - today).days if d else None, "last_date": last.isoformat() if last else None}


def lookup(symbols, *, today: date | None = None, now: datetime | None = None, fetch=None, wait_seconds: float = 20.0) -> dict:
    """{"items": {symbol: {"symbol","known","date","days"}}, "pending": n, "error": text}.

    Cached dates are used when fresh. Stale or unknown ones are fetched in the background
    pool for up to ``wait_seconds``; any not finished by then count as ``pending`` and will be
    in the cache for the next call. ``known`` is False until a lookup has ever succeeded."""
    fetch = fetch or fetch_next
    today = today or date.today()
    now = now or datetime.now()
    wanted = []
    for raw in symbols or []:
        sym = str(raw or "").strip().upper()
        if sym and sym not in wanted:
            wanted.append(sym)
    wanted = wanted[:MAX_SYMBOLS]
    cached = db.earnings_db.get_many(wanted)
    stale = [s for s in wanted if not _is_fresh(cached.get(s), today, now)]
    error = ""
    futures = {}
    for sym in stale:
        fut = _inflight.get(sym)
        if fut is None or fut.done():
            def job(s=sym):
                try:
                    result = fetch(s, today)
                except EarningsUnavailable as exc:
                    return ("error", str(exc))
                except Exception as exc:      # never let one ticker break the rest
                    return ("error", str(exc) or exc.__class__.__name__)
                db.earnings_db.save(s, result, now=now)
                return ("ok", result)
            fut = _pool.submit(job)
            _inflight[sym] = fut
        futures[sym] = fut
    if futures:
        wait(list(futures.values()), timeout=wait_seconds)
    pending = 0
    for sym, fut in futures.items():
        if not fut.done():
            pending += 1
        else:
            kind, value = fut.result()
            if kind == "error":
                error = value
    fresh = db.earnings_db.get_many(wanted) if futures else cached
    items = {s: _result(s, fresh.get(s), today) for s in wanted}
    return {"items": items, "pending": pending, "error": error}


def week_bounds(today: date | None = None) -> tuple[date, date]:
    """Monday and Sunday of the week containing ``today``."""
    today = today or date.today()
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def this_week(universe: dict[str, list[str]], *, today: date | None = None, **kw) -> dict:
    """Tickers from ``universe`` ({symbol: ["watchlist", "holding"]}) reporting this week, by date."""
    today = today or date.today()
    start, end = week_bounds(today)
    found = lookup(list(universe), today=today, **kw)
    items = []
    for sym, info in found["items"].items():
        for raw in (info["date"], info["last_date"]):
            d = _as_date(raw)
            if d is not None and start <= d <= end:
                items.append({"symbol": sym, "date": d.isoformat(), "weekday": d.strftime("%A"), "days": (d - today).days,
                              "sources": universe.get(sym, [])})
                break
    items.sort(key=lambda i: (i["date"], i["symbol"]))
    unknown = sum(1 for i in found["items"].values() if not i["known"])
    return {"start": start.isoformat(), "end": end.isoformat(), "items": items, "pending": found["pending"],
            "unknown": unknown, "checked": len(found["items"]), "error": found["error"]}
