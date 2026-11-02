"""Market-wide news for the Trading tab: what is moving the broader market (indexes, the Fed and interest rates, the
economy, oil, trade and world events), not news about one company. Alpaca's news feed (headlines tagged with broad index
funds) is used when keys are saved; Yahoo Finance fills in or takes over (index, bond and oil headlines).

The list is kept for MAX_AGE seconds so the page can ask again every hour without hammering either source, and the last good
list is kept (and marked stale) when a refresh fails. Each headline gets a topic label from simple keyword matching on its
headline and summary. Read-only; headlines are not advice."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from source.collector import alpaca, market_data, yahoo

REFRESH_SECONDS = 3600          # how often the page asks for fresh headlines
MAX_AGE = 3300                  # a list younger than this is served as is (a little under an hour, so the hourly ask is fresh)
MIN_MANUAL_GAP = 60             # a Refresh button press inside this many seconds of the last fetch is served from memory
ALPACA_SYMBOLS = ["SPY", "QQQ", "DIA", "IWM", "TLT"]                  # broad stock, small-cap and bond funds: market-wide stories
YAHOO_SYMBOLS = ["^GSPC", "^DJI", "^IXIC", "^TNX", "CL=F"]             # S&P 500, Dow, Nasdaq, 10-year yield, oil
LIMIT = 24

TOPICS = (
    ("Fed & rates", ("fed ", "federal reserve", "powell", "fomc", "rate cut", "rate hike", "interest rate", "treasury yield", "yields", "bond market", "mortgage rate")),
    ("Economy", ("inflation", "cpi", "jobs report", "payroll", "unemployment", "gdp", "retail sales", "consumer spending", "consumer confidence", "recession", "economy", "economic", "housing", "pmi", "jobless")),
    ("Oil & energy", ("oil", "crude", "opec", "gasoline", "natural gas", "energy prices")),
    ("World & trade", ("tariff", "trade war", "trade deal", "china", "europe", "ukraine", "russia", "middle east", "israel", "iran", "geopolit", "sanction", "election", "white house", "congress", "shutdown", "debt ceiling", "global")),
    ("Earnings season", ("earnings season", "earnings", "profit", "quarterly results", "guidance")),
)

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "items": [], "source": "", "fetched": ""}


def topic_of(item: dict) -> str:
    """The first topic whose keywords appear in the headline or summary, else "Markets"."""
    text = f" {item.get('headline', '')} {item.get('summary', '')} ".lower()
    for name, words in TOPICS:
        if any(w in text for w in words):
            return name
    return "Markets"


def _merge(*lists: list[dict]) -> list[dict]:
    seen_url, seen_head, out = set(), set(), []
    for lst in lists:
        for n in lst:
            head = " ".join(n["headline"].lower().split())[:90]
            if n["url"] in seen_url or head in seen_head:
                continue
            seen_url.add(n["url"])
            seen_head.add(head)
            out.append({**n, "topic": topic_of(n)})
    out.sort(key=lambda n: n.get("time") or "", reverse=True)
    return out[:LIMIT]


def _fetch(keys) -> tuple[list[dict], str]:
    """(headlines, source) from Alpaca and/or Yahoo. Raises MarketDataError / AlpacaError when nothing could be read."""
    from_alpaca, from_yahoo, err = [], [], None
    if keys is not None:
        try:
            from_alpaca = alpaca.get_news_for(ALPACA_SYMBOLS, keys, limit=LIMIT)
        except alpaca.AlpacaError as exc:
            err = exc
    if market_data.yahoo_enabled() and len(from_alpaca) < 12:
        try:
            from_yahoo = yahoo.get_topic_news(YAHOO_SYMBOLS, limit=LIMIT)
        except yahoo.MarketDataError as exc:
            err = err or exc
    items = _merge(from_alpaca, from_yahoo)
    if not items:
        if err is not None:
            raise err
        return [], ""
    source = "Alpaca and Yahoo Finance" if from_alpaca and from_yahoo else ("Alpaca" if from_alpaca else "Yahoo Finance")
    return items, source


def get(keys, *, force: bool = False, now: float | None = None) -> dict:
    """{"items", "source", "fetched" (ISO time), "stale" (a refresh failed, so these are older), "error", "refresh_seconds"}."""
    clock = time.time() if now is None else now
    with _lock:
        age = clock - _cache["at"]
        fresh = _cache["items"] and (age < (MIN_MANUAL_GAP if force else MAX_AGE))
        if not fresh:
            try:
                items, source = _fetch(keys)
                _cache.update(at=clock, items=items, source=source, fetched=datetime.fromtimestamp(clock, timezone.utc).isoformat(timespec="seconds"))
                error = ""
            except (alpaca.AlpacaError, yahoo.MarketDataError) as exc:
                error = str(exc) or "Market news could not be loaded."
        else:
            error = ""
        return {"items": list(_cache["items"]), "source": _cache["source"], "fetched": _cache["fetched"],
                "stale": bool(error and _cache["items"]), "error": error, "refresh_seconds": REFRESH_SECONDS}


def reset() -> None:
    with _lock:
        _cache.update(at=0.0, items=[], source="", fetched="")
