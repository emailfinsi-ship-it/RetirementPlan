"""Made-up broker and market data for recording the tour videos (tools/video/make_tour.py). Nothing here is used by the app itself.

``install(stack)`` swaps Alpaca's web call for a stand-in that answers account, positions, orders, quotes and price history with
invented (but repeatable) numbers, so the Alpaca tab, Stock Analysis, the Screener and the ratings all run their real code against it.
``broker_routes(context)`` does the same for the IBKR and E*TRADE tabs by answering their page's data calls."""

from __future__ import annotations

import hashlib
import json
import random
import re
import urllib.parse
from datetime import date, datetime, timedelta
from unittest.mock import patch

KEYS = ("PKFAKEKEYID", "fakesecret")
_CACHE: dict[str, list[dict]] = {}


def _seed(sym: str) -> tuple[random.Random, int]:
    h = hashlib.md5(sym.encode()).hexdigest()
    return random.Random(int(h[:8], 16)), int(h[8:10], 16)


def _weekdays(n: int) -> list[date]:
    d, out = date.today(), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def bars(sym: str, n: int = 320) -> list[dict]:
    if sym in _CACHE:
        return _CACHE[sym]
    rnd, tag = _seed(sym)
    p = 20 + rnd.random() * 380
    drift, vol = (rnd.random() - 0.42) * 0.0012, 0.011 + rnd.random() * 0.013
    closes = []
    for _ in range(n):
        p *= 1 + drift + rnd.gauss(0, vol)
        closes.append(p)
    kind = tag % 10
    if kind == 0:                                # a sharp recent drop: shows up as oversold
        for i in range(12):
            closes[n - 12 + i] = closes[n - 13] * (0.982 ** (i + 1))
        closes[-1] *= 1.012
    elif kind == 2:                             # a fast run-up: shows up as overbought
        for i in range(10):
            closes[n - 10 + i] = closes[n - 11] * (1.017 ** (i + 1))
    out, prev = [], closes[0]
    for day, c in zip(_weekdays(n), closes):
        hi = max(prev, c) * (1 + abs(rnd.gauss(0, 0.004)))
        lo = min(prev, c) * (1 - abs(rnd.gauss(0, 0.004)))
        out.append({"t": day.isoformat() + "T05:00:00Z", "o": round(prev, 2), "h": round(hi, 2), "l": round(lo, 2), "c": round(c, 2),
                    "v": int(900_000 * (1 + rnd.random() * 5))})
        prev = c
    out[-1]["v"] = int(out[-1]["v"] * (1.8 if kind in (0, 1, 2) else 1))
    _CACHE[sym] = out
    return out


def price(sym: str) -> float:
    return bars(sym)[-1]["c"]


HOLDINGS = [("AAPL", 120, 0.62), ("MSFT", 40, 0.78), ("NVDA", 60, 0.45), ("VTI", 85, 0.9), ("KO", 150, 1.08), ("JPM", 30, 0.85)]


def _snap(sym: str) -> dict:
    b = bars(sym)
    last, prev = b[-1], b[-2]
    c = last["c"]
    return {"latestTrade": {"p": c, "t": last["t"]}, "latestQuote": {"bp": round(c * 0.9996, 2), "ap": round(c * 1.0004, 2), "bs": 2, "as": 3},
            "dailyBar": {"t": last["t"], "o": last["o"], "h": last["h"], "l": last["l"], "c": c, "v": last["v"]},
            "prevDailyBar": {"t": prev["t"], "o": prev["o"], "h": prev["h"], "l": prev["l"], "c": prev["c"], "v": prev["v"]}}


def _names() -> dict[str, str]:
    from source.screener import universe
    return {e["symbol"]: e["name"] for e in universe.market_entries()}


ORDER_IDS = {"AAPL": "o-aapl-1", "NVDA": "o-nvda-1", "VTI": "o-vti-1"}


def alpaca_request(method, url, keys, *, body=None, urlopen=None, timeout=10.0):
    u = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(u.query)
    path = u.path
    if path == "/v2/account":
        return {"status": "ACTIVE", "account_number": "PA3EXAMPLE", "equity": "184250.55", "last_equity": "182100.10", "cash": "22140.20",
                "buying_power": "44280.40"}
    if path == "/v2/positions":
        out = []
        for sym, qty, f in HOLDINGS:
            c = price(sym)
            avg = round(c * f, 2)
            out.append({"symbol": sym, "qty": str(qty), "side": "long", "avg_entry_price": str(avg), "current_price": str(c),
                        "market_value": str(round(qty * c, 2)), "unrealized_pl": str(round(qty * (c - avg), 2)),
                        "unrealized_plpc": str(round(c / avg - 1, 4))})
        return out
    if path == "/v2/orders" and method == "GET":
        return [{"id": oid, "symbol": s, "side": "buy", "qty": "10", "type": "market", "status": "filled", "filled_qty": "10",
                 "filled_avg_price": str(price(s)), "submitted_at": (datetime.now() - timedelta(days=3 + i)).isoformat(), "time_in_force": "day"}
                for i, (s, oid) in enumerate(ORDER_IDS.items())]
    if path == "/v2/stocks/bars":
        syms = (q.get("symbols") or [""])[0].split(",")
        return {"bars": {s: bars(s) for s in syms if s}, "next_page_token": None}
    m = re.match(r"^/v2/stocks/([^/]+)/(bars|trades/latest|snapshot)$", path)
    if m:
        sym, what = m.group(1), m.group(2)
        if what == "bars":
            return {"bars": bars(sym)[-int((q.get("limit") or ["400"])[0]):]}
        if what == "trades/latest":
            return {"trade": {"p": price(sym)}}
        return {sym: _snap(sym)}
    if path == "/v2/stocks/snapshots":
        syms = (q.get("symbols") or [""])[0].split(",")
        return {"snapshots": {s: _snap(s) for s in syms if s}}
    m = re.match(r"^/v2/assets/([^/]+)$", path)
    if m:
        return {"symbol": m.group(1), "name": _names().get(m.group(1), m.group(1)) + " Common Stock"}
    if path.endswith("/news"):
        return {"news": []}
    return {}


def install(stack) -> None:
    """Patches Alpaca for the rest of ``stack`` (a contextlib.ExitStack)."""
    from source.collector import alpaca
    from source.common import secrets_store
    stack.enter_context(patch.object(alpaca, "_request", alpaca_request))
    from source.collector import yahoo
    stack.enter_context(patch.object(yahoo, "get_bars_batch", lambda symbols, start=None, chunk=60, **kw: {s: bars(s) for s in symbols}))
    stack.enter_context(patch.object(secrets_store, "has_alpaca_keys", lambda mode="paper": True))
    stack.enter_context(patch.object(secrets_store, "get_alpaca_keys", lambda mode="paper": KEYS))


def seed_orders() -> None:
    """A month of real-money orders for the Orders tab (all made up)."""
    from source.common import db
    now = datetime.now()
    rows = [("AAPL", "buy", 10, "market", 1820.0, ORDER_IDS["AAPL"], "filled", 3, "alpaca"),
            ("NVDA", "buy", 10, "market", 1310.0, ORDER_IDS["NVDA"], "filled", 4, "alpaca"),
            ("VTI", "buy", 10, "market", 2850.0, ORDER_IDS["VTI"], "filled", 5, "alpaca"),
            ("MSFT", "sell", 5, "limit", 2210.0, "e-1", "executed", 9, "etrade"),
            ("KO", "buy", 40, "limit", 2430.0, "i-1", "Filled", 12, "ibkr"),
            ("JPM", "buy", 8, "market", 1760.0, "e-2", "executed", 18, "etrade"),
            ("TSLA", "sell", 6, "limit", 1490.0, "i-2", "Filled", 24, "ibkr")]
    for sym, side, qty, typ, est, oid, status, ago, broker in rows:
        db.live_trading.log_live_order(symbol=sym, side=side, qty=qty, order_type=typ, estimate=est, order_id=oid, status=status,
                                       placed_at=now - timedelta(days=ago, hours=2), broker=broker)


# ---- IBKR and E*TRADE: the page asks the app for its data; answer with a made-up login -------------------------------------------
def _pos(sym, qty, f, name=""):
    c = price(sym)
    avg = round(c * f, 2)
    mv = round(qty * c, 2)
    return {"symbol": sym, "name": name or _names().get(sym, sym), "qty": qty, "avg_cost": avg, "price": c, "market_value": mv,
            "gain": round(mv - qty * avg, 2), "gain_pct": round((c / avg - 1) * 100, 2), "change": round(c - bars(sym)[-2]["c"], 2),
            "change_pct": round((c / bars(sym)[-2]["c"] - 1) * 100, 2), "day_gain": round(qty * (c - bars(sym)[-2]["c"]), 2),
            "day_gain_pct": None, "pct_of_portfolio": None}


def _lots(sym, qty, f):
    c = price(sym)
    half = qty // 2
    out = []
    for acq, n, ff, term in (((date.today() - timedelta(days=900)).isoformat(), half, f, "long"),
                             ((date.today() - timedelta(days=120)).isoformat(), qty - half, f * 1.12, "short")):
        cps = round(c * ff, 3)
        out.append({"symbol": sym, "acquired": acq, "qty": n, "cost_per_share": cps, "cost_basis": round(cps * n, 2), "market_value": round(c * n, 2),
                    "gain": round((c - cps) * n, 2), "gain_pct": round((c / cps - 1) * 100, 2), "day_gain": 0.0, "day_gain_pct": None, "term": term})
    return out


BROKER_POSITIONS = {"etrade": [("MSFT", 40, 0.78), ("AAPL", 80, 0.7), ("JPM", 30, 0.85)], "ibkr": [("VTI", 120, 0.88), ("KO", 150, 1.08), ("NVDA", 40, 0.5)]}


def broker_data(broker: str, account: str | None = None) -> dict:
    pos = [_pos(*p) for p in BROKER_POSITIONS[broker]]
    value = sum(p["market_value"] for p in pos)
    acct_id = "A1"
    row = {"id": acct_id, "name": "Individual Brokerage (…4821)" if broker == "etrade" else "Interactive Brokers (U1234567)",
           "summary": {"value": round(value + 8200, 2), "cash": 8200.0, "buying_power": 16400.0}, "positions": pos,
           "orders": [{"id": "1", "symbol": "KO", "side": "buy", "qty": 20, "filled": 0, "type": "limit", "limit_price": round(price("KO") * 0.97, 2),
                       "status": "open", "open": True}], "currencies": [], "error": "", "errors": []}
    out = {"broker": broker, "label": "E*TRADE" if broker == "etrade" else "Interactive Brokers", "connected": True, "message": "",
           "accounts": [{"id": acct_id, "name": row["name"]}], "account": acct_id, "summary": row["summary"], "positions": pos, "orders": row["orders"],
           "errors": [], "armed": True, "armed_until": 4_102_444_800, "persistent": True, "per_order": 5000, "daily_remaining": 20000,
           "view": "one", "overview": {"accounts": [row], "total": row["summary"],
                                       "holdings": [{"symbol": p["symbol"], "name": p["name"], "qty": p["qty"], "market_value": p["market_value"],
                                                     "gain": p["gain"], "accounts": 1} for p in pos]}}
    if broker == "etrade":
        out["etrade"] = {"has_keys": True, "has_session": True}
    else:
        out.update(gateway_url="https://localhost:5000", gateway_files=True, gateway_started_here=True, gateway_autostart=True)
    return out


def broker_preview(order: dict, broker: str) -> dict:
    sym = order.get("symbol", "KO")
    qty = float(order.get("qty") or 10)
    px = price(sym)
    est = round(qty * px, 2)
    held = {p[0]: p[1] for p in BROKER_POSITIONS[broker]}.get(sym, 0)
    checks = []
    acct = 120000.0
    if est / acct >= 0.1:
        checks.append({"level": "warn" if est / acct >= 0.25 else "info", "text": f"This order is {est / acct * 100:.0f}% of the account's value (${est:,.0f} of ${acct:,.0f})."})
    if order.get("side") == "sell" and held and abs(qty - held) < 1e-9:
        checks.append({"level": "info", "text": f"This sells your whole {sym} position in this account."})
    if order.get("side") == "sell":
        checks.append({"level": "info", "text": f"At about ${px:,.2f} this sells above your average cost. In a taxable account the gain is taxed; which shares are sold depends on the account's lot method."})
    if not checks:
        checks.append({"level": "info", "text": "Nothing unusual about this order's size or price."})
    return {"order": {**order, "type": order.get("type") or "market", "time_in_force": "day", "session": "regular"}, "price": px, "estimate": est,
            "commission": 0, "notes": [], "token": "tour", "expires_in": 300, "broker": broker, "pct_of_account": est / acct, "checks": checks}


async def broker_routes(context) -> None:
    """Answers the IBKR and E*TRADE pages' data calls for every page in ``context``."""
    async def handle(route):
        req = route.request
        u = req.url
        broker = "etrade" if "/etrade" in (req.headers.get("referer") or "") else "ibkr"
        try:
            body = json.loads(req.post_data or "{}")
        except ValueError:
            body = {}
        broker = body.get("broker") or broker
        if broker not in BROKER_POSITIONS:
            broker = "ibkr"
        if u.endswith("/api/broker/data"):
            data = broker_data(broker)
        elif u.endswith("/api/broker/lots"):
            sym = body.get("symbol")
            held = {p[0]: p for p in BROKER_POSITIONS[broker]}
            lots = [l for s, p in held.items() if not sym or s == sym for l in _lots(*p)]
            data = {"account": "A1", "lots": lots}
        elif u.endswith("/api/broker/preview"):
            data = broker_preview(body.get("order") or body, broker)
        else:
            data = {}
        await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
    await context.route(re.compile(r".*/api/broker/(data|lots|preview)$"), handle)
