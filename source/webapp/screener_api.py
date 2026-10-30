"""The Screener tab's routes: understand a typed request, run a screen in the background, report progress, and look up
put/call volume for the rows on screen, and keep saved screens. Nothing here places an order."""

from __future__ import annotations

from source.screener import engine, filters, jobs, parser, saved, universe

ROUTES = ("/api/screener/config", "/api/screener/parse", "/api/screener/run", "/api/screener/status", "/api/screener/cancel",
          "/api/screener/options", "/api/screener/saved/list", "/api/screener/saved/save", "/api/screener/saved/delete",
          "/api/screener/saved/watch", "/api/screener/saved/seen", "/api/holdings/review/start", "/api/holdings/review/result")
_REVIEWS: dict[str, dict] = {}      # job id -> the holdings it was started for (so the result is judged against the same snapshot)

CATEGORIES = ("Broad market", "Dividend", "Thematic", "Commodities", "Bonds", "International", "Crypto", "Leveraged")
EXAMPLES = (
    "ETFs where MACD crossed up in the last 3 days and RSI is under 40",
    "Technology stocks up at least 5% this week with RSI over 60",
    "Oversold semiconductor stocks with high volume",
    "AI stocks within 5% of their 52-week high, price under $300",
    "Stocks that moved down $20 or more in a month, Health Care and Energy",
    "Stocks with more calls than puts, MACD bullish, above the 50-day average",
    "ETFs whose day range is at least 3% today",
)


def _sources_note() -> str:
    keys = engine._alpaca_keys() is not None
    return ("Prices: Alpaca's free feed (Yahoo Finance for anything it lacks). " if keys else "Prices: Yahoo Finance (save Alpaca keys on the Trading tab to use Alpaca first). ") + \
        "Put/call volume: E*TRADE when signed in, otherwise Yahoo Finance."


def handle(path: str, payload: dict) -> dict:
    if path == "/api/screener/config":
        return {"sectors": list(universe.SECTORS), "categories": list(CATEGORIES),
                "themes": {k: v["label"] for k, v in universe.THEMES.items()}, "windows": flt_windows(),
                "examples": list(EXAMPLES), "sources": _sources_note(), "universe_size": len(universe.market_entries())}
    if path == "/api/screener/parse":
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("Type what you are looking for first.")
        out = parser.parse(text[:600])
        if not out["understood"]:
            out["message"] = "I couldn't find any filters in that. Try something like: " + EXAMPLES[0]
        return out
    if path == "/api/screener/run":
        f = filters.normalize(payload.get("filters"))
        if not engine.candidates(f):
            raise ValueError("Nothing to scan with those choices (check the sector, stock / ETF and where-to-scan settings).")
        return {"job": jobs.start(f), "filters": f, "understood": filters.describe(f)}
    if path == "/api/screener/status":
        return jobs.status(payload.get("job"))
    if path == "/api/screener/cancel":
        jobs.cancel(payload.get("job"))
        return {}
    if path == "/api/screener/options":
        syms = [s for s in dict.fromkeys(universe.clean_symbol(x) for x in (payload.get("symbols") or [])) if s][:40]
        return {"items": engine.default_load_options(syms) if syms else {}}
    if path == "/api/screener/saved/list":
        return {"items": saved.list_scans()}
    if path == "/api/screener/saved/save":
        return {"item": saved.save(payload.get("name"), payload.get("filters"), payload.get("text") or "", bool(payload.get("watch")))}
    if path == "/api/screener/saved/delete":
        saved.delete(payload.get("id"))
        return {}
    if path == "/api/screener/saved/watch":
        return {"item": saved.set_watch(payload.get("id"), bool(payload.get("watch")))}
    if path == "/api/screener/saved/seen":
        return {"item": saved.mark_seen(payload.get("id"), payload.get("symbols"))}
    if path == "/api/holdings/review/start":
        from source.reporting import holdings_review
        held = holdings_review.collect_held()
        if not held:
            raise ValueError("No holdings with a ticker were found. Link your investment accounts in Setup, or open the Alpaca, IBKR or E*TRADE tab once.")
        f = filters.normalize({"universe": ["custom"], "tickers": list(held)[:400], "limit": 300, "sort": "symbol"})
        job = jobs.start(f)
        for old in list(_REVIEWS)[:max(0, len(_REVIEWS) - 5)]:
            _REVIEWS.pop(old, None)
        _REVIEWS[job] = held
        return {"job": job, "count": len(held)}
    if path == "/api/holdings/review/result":
        from source.reporting import holdings_review
        job = str(payload.get("job") or "")
        st = jobs.status(job)
        held = _REVIEWS.get(job)
        if held is None:
            raise ValueError("That review is no longer available. Run it again.")
        out = {k: st[k] for k in ("state", "done", "total", "stage", "error", "seconds")}
        if st["state"] == "done":
            out["review"] = holdings_review.review(held, (st.get("result") or {}).get("rows") or [])
            out["sources"] = (st.get("result") or {}).get("sources") or {}
        return out
    raise ValueError("Not found")


def flt_windows() -> dict:
    return dict(filters.WINDOW_WORDS)
