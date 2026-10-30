"""The Screener tab's routes: understand a typed request, run a screen in the background, report progress, and look up
put/call volume for the rows on screen. Read-only; nothing here places an order."""

from __future__ import annotations

from source.screener import engine, filters, jobs, parser, universe

ROUTES = ("/api/screener/config", "/api/screener/parse", "/api/screener/run", "/api/screener/status", "/api/screener/cancel",
          "/api/screener/options")

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
    raise ValueError("Not found")


def flt_windows() -> dict:
    return dict(filters.WINDOW_WORDS)
