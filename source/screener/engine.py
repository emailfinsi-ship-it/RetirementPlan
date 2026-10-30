"""Runs a screen: price history for each stock / ETF in the chosen universe, the indicators the Stock Analysis tab uses
(source.reporting.technicals), then the filters. Put/call volume (from option chains, which are slow to read) is looked at
only for the names that already passed the price-based filters.

Pure computation plus two injectable readers (``load_bars`` and ``load_options``), so tests never touch the network.
Read-only: nothing here can place an order and none of it is advice."""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

from source.reporting import technicals as ta
from source.screener import filters as flt
from source.screener import universe

MIN_BARS = 30
HISTORY_DAYS = 420
OPTION_CANDIDATE_CAP = 60       # option chains are read for at most this many names
RATING_BUY = ("Buy", "Strong Buy")
RATING_SELL = ("Sell", "Strong Sell")

_BARS: dict[str, tuple[float, list[dict]]] = {}
BARS_TTL = 15 * 60.0


def _last(values, back: int = 0):
    i = len(values) - 1 - back
    return values[i] if 0 <= i < len(values) else None


def metrics(bars: list[dict]) -> dict | None:
    """Everything the filters and the results table need, from daily bars (oldest first); None with too little history."""
    if len(bars) < MIN_BARS:
        return None
    closes = [b["c"] for b in bars]
    price = closes[-1]
    last = bars[-1]
    prev = closes[-2]
    ind = ta.series(bars)
    macd = ta.macd_status(bars)
    moves = {}
    for key, n in flt.WINDOWS.items():
        if len(closes) > n:
            base = closes[-1 - n]
            moves[key] = {"usd": price - base, "pct": (price - base) / base * 100.0 if base else None}
    year = bars[-252:]
    hi, lo = max(b["h"] for b in year), min(b["l"] for b in year)
    avg_vol = _last(ind["vol_avg20"])
    rating = ta.rating(bars)
    return {
        "price": price, "prev_close": prev, "change": price - prev, "change_pct": (price - prev) / prev * 100.0 if prev else None,
        "rsi": _last(ind["rsi"]), "macd_state": macd["state"], "macd_cross": macd["cross"], "macd_ago": macd["bars_ago"],
        "moves": moves, "day_range_usd": last["h"] - last["l"], "day_range_pct": (last["h"] - last["l"]) / prev * 100.0 if prev else None,
        "sma": {n: _last(ind[f"sma{n}"]) for n in flt.SMA_WINDOWS},
        "high_52w": hi, "low_52w": lo, "from_high_pct": (hi - price) / hi * 100.0 if hi else None,
        "from_low_pct": (price - lo) / lo * 100.0 if lo else None,
        "volume": last["v"], "volume_ratio": (last["v"] / avg_vol) if avg_vol else None,
        "rating": rating["label"], "buy_votes": rating["buy_votes"], "sell_votes": rating["sell_votes"], "signals": rating["of"],
    }


def _passes_swing(m: dict, s: dict) -> str | None:
    """A reason string when the swing filter ``s`` is met, else None."""
    if s["kind"] == "range":
        pct, usd = m["day_range_pct"], m["day_range_usd"]
        label = "today's range"
    else:
        mv = m["moves"].get(s["window"])
        if not mv or mv["pct"] is None:
            return None
        pct, usd = mv["pct"], mv["usd"]
        if s["direction"] == "up" and not (usd > 0):
            return None
        if s["direction"] == "down" and not (usd < 0):
            return None
        label = f"{flt.WINDOW_WORDS[s['window']]} move"
    pct_abs, usd_abs = abs(pct or 0), abs(usd or 0)
    if s["pct"] and pct_abs < s["pct"]:
        return None
    if s["usd"] and usd_abs < s["usd"]:
        return None
    sign = "+" if (usd or 0) >= 0 and s["kind"] == "move" else ("-" if s["kind"] == "move" else "")
    return f"{label} {sign}{pct_abs:.1f}% ({sign}${usd_abs:,.2f})"


def technical_match(m: dict, f: dict) -> list[str] | None:
    """The reasons ``m`` matches the price-based filters in ``f``, or None when it does not."""
    why: list[str] = []
    mf = f["macd"]
    if mf:
        if "cross" in mf:
            if m["macd_cross"] is None or m["macd_ago"] is None or m["macd_ago"] > mf["within_days"]:
                return None
            if mf["cross"] != "any" and m["macd_cross"] != mf["cross"]:
                return None
            ago = "today" if m["macd_ago"] == 0 else f"{m['macd_ago']} day(s) ago"
            why.append(f"MACD {m['macd_cross']} crossover {ago}")
        elif m["macd_state"] != mf["state"]:
            return None
        else:
            why.append(f"MACD {mf['state']} signal line")
    r = f["rsi"]
    if r:
        v = m["rsi"]
        if v is None or (r["min"] is not None and v < r["min"]) or (r["max"] is not None and v > r["max"]):
            return None
        why.append(f"RSI {v:.0f}")
    for s in f["swing"]:
        got = _passes_swing(m, s)
        if got is None:
            return None
        why.append(got)
    p = f["price"]
    if p and ((p["min"] is not None and m["price"] < p["min"]) or (p["max"] is not None and m["price"] > p["max"])):
        return None
    if f["sma"]:
        avg = m["sma"].get(f["sma"]["window"])
        if avg is None or (m["price"] > avg) != (f["sma"]["relation"] == "above"):
            return None
        why.append(f"price {f['sma']['relation']} {f['sma']['window']}-day average")
    n = f["near_52w"]
    if n:
        dist = m["from_high_pct"] if n["side"] == "high" else m["from_low_pct"]
        if dist is None or dist > n["within_pct"]:
            return None
        why.append(f"{dist:.1f}% from 52-week {n['side']}")
    if f["volume_ratio_min"] and (m["volume_ratio"] is None or m["volume_ratio"] < f["volume_ratio_min"]):
        return None
    if f["volume_ratio_min"]:
        why.append(f"volume {m['volume_ratio']:.1f}x average")
    if f["rating"] == "buy" and m["rating"] not in RATING_BUY:
        return None
    if f["rating"] == "sell" and m["rating"] not in RATING_SELL:
        return None
    return why


def _entry_ok(e: dict, f: dict) -> bool:
    if e["type"] not in f["assets"]:
        return False
    if f["sectors"] and e["sector"] not in f["sectors"]:
        return False
    theme = universe.THEMES.get(f["theme"]) if f["theme"] else None
    words = list(f["industries"]) + list((theme or {}).get("industries") or ())
    if theme or f["industries"]:
        in_theme = e["symbol"] in ((theme or {}).get("tickers") or ())
        in_words = any(w.lower() in (e["industry"] + " " + e["name"]).lower() for w in words)
        if not (in_theme or in_words):
            return False
    return True


def candidates(f: dict) -> list[dict]:
    """The entries worth fetching prices for, after the cheap filters (asset type, sector, theme / industry words)."""
    entries = universe.entries_for(f["universe"], f["tickers"])
    if f["theme"] and "market" in f["universe"]:
        have = {e["symbol"] for e in entries}                  # themed tickers outside the bundled list still get scanned
        entries += universe.custom_entries([t for t in universe.THEMES[f["theme"]].get("tickers", ()) if t not in have])
    return [e for e in entries if _entry_ok(e, f)]


SOURCES: dict[str, int] = {}       # which feed supplied the prices of the last scan: {"alpaca": n, "yahoo": n}


def _alpaca_keys():
    from source.common import secrets_store
    for mode in ("paper", "live"):
        try:
            return secrets_store.get_alpaca_keys(mode=mode)
        except secrets_store.SecretNotFoundError:
            continue
    return None


_ALPACA_SYMBOL = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def default_load_bars(symbols: list[str], progress=None) -> dict[str, list[dict]]:
    """Daily bars for ``symbols`` (kept 15 minutes). Alpaca's free feed is used when Alpaca keys are saved (about 100 symbols
    per call); anything it has no bars for, or everything if Alpaca cannot be reached, comes from Yahoo Finance."""
    from source.collector import alpaca, yahoo
    now = time.time()
    out, need = {}, []
    for s in symbols:
        hit = _BARS.get(s)
        if hit and now - hit[0] < BARS_TTL:
            out[s] = hit[1]
        else:
            need.append(s)
    SOURCES.clear()
    start = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    keys = _alpaca_keys()
    todo = list(need)
    done = len(symbols) - len(need)
    if keys and todo:
        # One ticker Alpaca cannot take (a fund with digits in its name, say) would make it refuse the whole batch: send those to Yahoo.
        left = [x for x in todo if not _ALPACA_SYMBOL.match(universe.yahoo_symbol(x).replace("-", "."))]
        todo = [x for x in todo if x not in left]
        for i in range(0, len(todo), 100):
            part = todo[i:i + 100]
            try:
                got = alpaca.get_bars_multi([universe.yahoo_symbol(x).replace("-", ".") for x in part], keys, start=start, max_pages=8)
            except alpaca.AlpacaError:
                left += part
                continue
            for x in part:
                bars = got.get(x) or got.get(x.replace(".", "-")) or []
                if len(bars) >= MIN_BARS:
                    _BARS[x] = (time.time(), bars)
                    out[x] = bars
                    SOURCES["alpaca"] = SOURCES.get("alpaca", 0) + 1
                else:
                    left.append(x)
            done += len(part)
            if progress:
                progress(min(done, len(symbols)))
        todo = left
    for i in range(0, len(todo), 60):
        part = todo[i:i + 60]
        got = yahoo.get_bars_batch(part, start=start, chunk=60)
        for x in part:
            _BARS[x] = (time.time(), got.get(x) or [])
            out[x] = _BARS[x][1]
            if out[x]:
                SOURCES["yahoo"] = SOURCES.get("yahoo", 0) + 1
        if progress:
            progress(min(len(symbols) - len(todo) + i + 60, len(symbols)))
    if progress:
        progress(len(symbols))
    return out


def default_load_options(symbols: list[str]) -> dict[str, dict]:
    """Option volume: from E*TRADE when it is signed in (one symbol at a time; it is left off after three failures in a row),
    from Yahoo Finance for the rest."""
    from source.collector import etrade, yahoo
    from source.collector.broker_common import BrokerError
    out: dict[str, dict] = {}
    rest = list(symbols)
    client = None
    try:
        from source.webapp import broker_api
        client = broker_api._etrade_client()
    except Exception:    # noqa: BLE001 -- not connected: Yahoo it is
        client = None
    if client is not None:
        rest, misses = [], 0
        for sym in symbols:
            if misses >= 3:
                rest.append(sym)
                continue
            try:
                got = etrade.option_volume(client, sym.replace(".", "/") if False else sym)
                misses = 0
            except BrokerError:
                misses += 1
                rest.append(sym)
                continue
            if got:
                out[sym] = {**got, "source": "etrade"}
    if rest:
        for sym, got in yahoo.get_option_volumes(rest).items():
            out[sym] = {**got, "source": "yahoo"}
    return out


def _row(e: dict, m: dict, why: list[str]) -> dict:
    return {
        "symbol": e["symbol"], "name": e["name"], "type": e["type"], "sector": e["sector"], "price": m["price"],
        "change_pct": m["change_pct"], "change": m["change"],
        "move_1d": (m["moves"].get("1d") or {}).get("pct"), "move_1w": (m["moves"].get("1w") or {}).get("pct"),
        "move_1m": (m["moves"].get("1m") or {}).get("pct"), "day_range_pct": m["day_range_pct"],
        "rsi": m["rsi"], "macd_state": m["macd_state"], "macd_cross": m["macd_cross"], "macd_ago": m["macd_ago"],
        "rating": m["rating"], "buy_votes": m.get("buy_votes"), "sell_votes": m.get("sell_votes"), "signals": m.get("signals"),
        "volume_ratio": m["volume_ratio"], "from_high_pct": m["from_high_pct"],
        "put_call": None, "why": why,
    }


RATING_RANK = {"Strong Buy": 4, "Buy": 3, "Hold": 2, "Sell": 1, "Strong Sell": 0}      # best to worst


def _sort_key(row: dict, key: str):
    pc = (row.get("put_call") or {}).get("ratio")
    table = {
        "change": -abs(row["change_pct"] or 0), "move": -abs(row["move_1w"] or 0), "rsi": row["rsi"] if row["rsi"] is not None else 999,
        "volume": -(row["volume_ratio"] or 0), "macd": row["macd_ago"] if row["macd_ago"] is not None else 999,
        "putcall": -(pc or 0), "symbol": row["symbol"],
        "rating": -RATING_RANK.get(row.get("rating"), -1), "rating_low": RATING_RANK.get(row.get("rating"), 99),
    }
    return table[key]


def scan(f: dict, *, load_bars=None, load_options=None, progress=None, cancelled=lambda: False) -> dict:
    """Runs filters ``f`` (from filters.normalize). ``progress(done, total, stage)`` is called as it goes.
    Returns {"rows", "scanned", "no_data", "matched", "options_checked", "truncated"}."""
    load_bars, load_options = load_bars or default_load_bars, load_options or default_load_options      # looked up now, so tests can swap them
    cands = candidates(f)
    total = len(cands)
    if progress:
        progress(0, total, "Reading prices")
    bars = load_bars([e["symbol"] for e in cands], (lambda n: progress(n, total, "Reading prices")) if progress else None)
    rows, no_data = [], 0
    for e in cands:
        if cancelled():
            break
        m = metrics(bars.get(e["symbol"]) or [])
        if m is None:
            no_data += 1
            continue
        why = technical_match(m, f)
        if why is not None:
            rows.append(_row(e, m, why))
    matched = len(rows)
    options_checked = 0
    pc = f["put_call"]
    if pc and rows and not cancelled():
        if progress:
            progress(total, total, "Reading option volume")
        rows.sort(key=lambda r: _sort_key(r, f["sort"] if f["sort"] != "putcall" else "change"))
        pool = rows[:OPTION_CANDIDATE_CAP]
        got = load_options([r["symbol"] for r in pool])
        options_checked = len(pool)
        kept = []
        for r in pool:
            o = got.get(r["symbol"])
            ratio = (o or {}).get("ratio")
            if ratio is None:
                continue
            if (pc["min"] is not None and ratio < pc["min"]) or (pc["max"] is not None and ratio > pc["max"]):
                continue
            r["put_call"] = o
            r["why"].append(f"put/call volume {ratio:.2f}")
            kept.append(r)
        rows = kept
    rows.sort(key=lambda r: _sort_key(r, f["sort"]))
    return {"rows": rows[:f["limit"]], "sources": dict(SOURCES), "scanned": total, "no_data": no_data, "matched": len(rows),
            "options_checked": options_checked, "truncated": len(rows) > f["limit"],
            "options_capped": bool(pc) and matched > OPTION_CANDIDATE_CAP}
