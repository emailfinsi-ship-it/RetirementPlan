"""The screener's filter set: one canonical shape that the form, the built-in parser and the Claude parser all produce.

``normalize`` accepts anything (a half-filled form, JSON from Claude) and returns a clean, safe filter dict or raises
ValueError with a plain-language reason; ``describe`` turns it back into short readable phrases."""

from __future__ import annotations

import re

from source.screener import universe

WINDOWS = {"1d": 1, "1w": 5, "2w": 10, "1m": 21, "3m": 63, "6m": 126, "1y": 252}
WINDOW_WORDS = {"1d": "1 day", "1w": "1 week", "2w": "2 weeks", "1m": "1 month", "3m": "3 months", "6m": "6 months", "1y": "1 year"}
DIRECTIONS = ("up", "down", "either")
MACD_CROSS = ("bullish", "bearish", "any")
SMA_WINDOWS = (20, 50, 200)
RATINGS = ("buy", "sell")           # "buy" = Buy or Strong Buy, "sell" = Sell or Strong Sell
SORTS = ("change", "move", "rsi", "volume", "macd", "putcall", "symbol")
MAX_RESULTS = 300

EMPTY = {
    "assets": ["stock", "etf"], "universe": ["market"], "tickers": [], "sectors": [], "industries": [], "theme": "",
    "macd": None, "rsi": None, "swing": [], "price": None, "sma": None, "near_52w": None, "volume_ratio_min": None,
    "put_call": None, "rating": "", "limit": 50, "sort": "change",
}


def _num(value, name: str, *, lo=None, hi=None):
    if value in (None, ""):
        return None
    try:
        n = float(str(value).replace("$", "").replace("%", "").replace(",", ""))
    except ValueError:
        raise ValueError(f"{name} must be a number.") from None
    if n != n:
        raise ValueError(f"{name} must be a number.")
    if lo is not None and n < lo:
        raise ValueError(f"{name} can't be below {lo:g}.")
    if hi is not None and n > hi:
        raise ValueError(f"{name} can't be above {hi:g}.")
    return n


def _pick(values, allowed, name: str) -> list[str]:
    out = []
    for v in values or []:
        v = str(v).strip().lower()
        if v in allowed and v not in out:
            out.append(v)
    return out


def normalize(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    f = {k: (list(v) if isinstance(v, list) else v) for k, v in EMPTY.items()}

    f["assets"] = _pick(raw.get("assets"), ("stock", "etf"), "assets") or ["stock", "etf"]
    f["universe"] = _pick(raw.get("universe"), ("market", "holdings", "watchlist", "custom"), "universe") or ["market"]
    raw_tickers = raw.get("tickers") or []
    if isinstance(raw_tickers, str):
        raw_tickers = re.split(r"[\s,;]+", raw_tickers)
    f["tickers"] = [t for t in dict.fromkeys(universe.clean_symbol(x) for x in raw_tickers) if t][:400]
    if f["tickers"] and "custom" not in f["universe"]:
        f["universe"].append("custom")
    by_lower = {s.lower(): s for s in universe.SECTORS}
    by_lower.update({c.lower(): c for c in ("Broad market", "Dividend", "Thematic", "Commodities", "Bonds", "International", "Crypto", "Leveraged")})
    f["sectors"] = [by_lower[s.strip().lower()] for s in (raw.get("sectors") or []) if str(s).strip().lower() in by_lower]
    f["sectors"] = list(dict.fromkeys(f["sectors"]))
    f["industries"] = [str(s).strip()[:40] for s in (raw.get("industries") or []) if str(s).strip()][:8]
    theme = str(raw.get("theme") or "").strip().lower()
    f["theme"] = theme if theme in universe.THEMES else ""

    macd = raw.get("macd")
    if isinstance(macd, dict) and (macd.get("cross") or macd.get("state")):
        cross = str(macd.get("cross") or "").lower()
        state = str(macd.get("state") or "").lower()
        if cross in MACD_CROSS:
            days = _num(macd.get("within_days"), "MACD crossover days", lo=1, hi=60)
            f["macd"] = {"cross": cross, "within_days": int(days or 5)}
        elif state in ("above", "below"):
            f["macd"] = {"state": state}

    rsi = raw.get("rsi")
    if isinstance(rsi, dict):
        lo, hi = _num(rsi.get("min"), "RSI minimum", lo=0, hi=100), _num(rsi.get("max"), "RSI maximum", lo=0, hi=100)
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("RSI minimum is above its maximum.")
        if lo is not None or hi is not None:
            f["rsi"] = {"min": lo, "max": hi}

    swings = raw.get("swing") or []
    if isinstance(swings, dict):
        swings = [swings]
    for s in swings[:4]:
        if not isinstance(s, dict):
            continue
        pct, usd = _num(s.get("pct"), "Swing percent", lo=0, hi=1000), _num(s.get("usd"), "Swing dollars", lo=0, hi=1_000_000)
        if not pct and not usd:
            continue
        kind = "range" if str(s.get("kind") or "").lower() == "range" else "move"
        window = str(s.get("window") or "1w").lower()
        if window not in WINDOWS:
            window = "1w"
        direction = str(s.get("direction") or "either").lower()
        f["swing"].append({"kind": kind, "window": "1d" if kind == "range" else window,
                           "direction": "either" if kind == "range" else (direction if direction in DIRECTIONS else "either"),
                           "pct": pct or None, "usd": usd or None})

    price = raw.get("price")
    if isinstance(price, dict):
        lo, hi = _num(price.get("min"), "Minimum price", lo=0), _num(price.get("max"), "Maximum price", lo=0)
        if lo is not None or hi is not None:
            f["price"] = {"min": lo, "max": hi}

    sma = raw.get("sma")
    if isinstance(sma, dict) and int(_num(sma.get("window"), "Average window", lo=1, hi=400) or 0) in SMA_WINDOWS \
            and str(sma.get("relation") or "").lower() in ("above", "below"):
        f["sma"] = {"window": int(sma["window"]), "relation": str(sma["relation"]).lower()}

    near = raw.get("near_52w")
    if isinstance(near, dict) and str(near.get("side") or "").lower() in ("high", "low"):
        f["near_52w"] = {"side": str(near["side"]).lower(), "within_pct": _num(near.get("within_pct"), "52-week distance", lo=0, hi=100) or 5.0}

    vol = _num(raw.get("volume_ratio_min"), "Volume multiple", lo=0, hi=100)
    f["volume_ratio_min"] = vol or None

    pc = raw.get("put_call")
    if isinstance(pc, dict):
        lo, hi = _num(pc.get("min"), "Put/call minimum", lo=0, hi=100), _num(pc.get("max"), "Put/call maximum", lo=0, hi=100)
        if lo is not None or hi is not None:
            f["put_call"] = {"min": lo, "max": hi}

    rating = str(raw.get("rating") or "").lower()
    f["rating"] = rating if rating in RATINGS else ""
    limit = _num(raw.get("limit"), "Result limit", lo=1, hi=MAX_RESULTS)
    f["limit"] = int(limit or 50)
    sort = str(raw.get("sort") or "change").lower()
    f["sort"] = sort if sort in SORTS else "change"
    return f


def _money(n) -> str:
    return f"${n:,.0f}" if float(n).is_integer() else f"${n:,.2f}"


def describe(f: dict) -> list[str]:
    """Short phrases for the filters in use, for the "what I understood" line."""
    out = []
    if f["assets"] != ["stock", "etf"]:
        out.append("only " + ("ETFs" if f["assets"] == ["etf"] else "stocks"))
    if f.get("theme"):
        out.append(f"theme: {universe.THEMES[f['theme']]['label']}")
    if f["sectors"]:
        out.append("sectors: " + ", ".join(f["sectors"]))
    if f["industries"]:
        out.append("industry: " + ", ".join(f["industries"]))
    names = {"market": "S&P 500, big stocks and ETFs", "holdings": "my holdings", "watchlist": "my watchlist", "custom": "my typed tickers"}
    if f["universe"] != ["market"]:
        out.append("scanning " + ", ".join(names[u] for u in f["universe"]))
    m = f["macd"]
    if m:
        out.append(f"MACD {m['cross']} crossover in the last {m['within_days']} day{'s' if m['within_days'] != 1 else ''}" if "cross" in m and m["cross"] != "any"
                   else f"MACD crossed (either way) in the last {m['within_days']} day{'s' if m['within_days'] != 1 else ''}" if "cross" in m else f"MACD {m['state']} its signal line")
    r = f["rsi"]
    if r:
        out.append("RSI " + (f"between {r['min']:g} and {r['max']:g}" if r["min"] is not None and r["max"] is not None
                              else f"above {r['min']:g}" if r["min"] is not None else f"below {r['max']:g}"))
    for s in f["swing"]:
        size = " and ".join(x for x in (f"{s['pct']:g}%" if s["pct"] else "", _money(s["usd"]) if s["usd"] else "") if x)
        if s["kind"] == "range":
            out.append(f"today's high-to-low range at least {size}")
        else:
            way = {"up": "up", "down": "down", "either": "up or down"}[s["direction"]]
            out.append(f"{way} at least {size} over {WINDOW_WORDS[s['window']]}")
    p = f["price"]
    if p:
        out.append("price " + (f"{_money(p['min'])} to {_money(p['max'])}" if p["min"] is not None and p["max"] is not None
                               else f"above {_money(p['min'])}" if p["min"] is not None else f"below {_money(p['max'])}"))
    if f["sma"]:
        out.append(f"price {f['sma']['relation']} its {f['sma']['window']}-day average")
    if f["near_52w"]:
        out.append(f"within {f['near_52w']['within_pct']:g}% of its 52-week {f['near_52w']['side']}")
    if f["volume_ratio_min"]:
        out.append(f"volume at least {f['volume_ratio_min']:g}x its 20-day average")
    pc = f["put_call"]
    if pc:
        out.append("put/call volume " + (f"between {pc['min']:g} and {pc['max']:g}" if pc["min"] is not None and pc["max"] is not None
                                          else f"above {pc['min']:g}" if pc["min"] is not None else f"below {pc['max']:g}"))
    if f["rating"]:
        out.append("technical rating " + f["rating"])
    return out
