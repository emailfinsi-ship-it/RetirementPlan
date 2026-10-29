"""Alpaca trading (https://docs.alpaca.markets) for the Trading tab -- a PAPER
(practice) account by default, and a LIVE (real-money) account only when the
caller says ``mode="live"``.

Safety rules, enforced here and in source.common.db.live_trading rather than
in the page so nothing can bypass them:

* **Paper is the default for every call.** Live is reached only by passing
  ``mode="live"`` explicitly; the dashboard does that only while live trading
  has been armed by the owner.
* **Preview, then confirm.** An order is placed only with a single-use token
  that ``preview_order`` issued for exactly those details a few minutes
  earlier, in the same mode, so a stray or replayed request cannot place one.
* **Size limits.** One order may not be worth more than ``MAX_ORDER_NOTIONAL``
  (a market order needs a recent price so the size can be checked), nor more
  than whatever lower per-order or daily-remaining limit the caller passes.

Reading (account, positions, orders) is always allowed once keys are saved;
the dashboard allows previewing and placing live orders only while armed.

Every network call takes an injectable ``urlopen`` so tests never touch the
network. Keys travel only in the request headers and are never logged.
"""

from __future__ import annotations

import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"  # real money -- used only when mode="live"
MODES = ("paper", "live")
DATA_URL = "https://data.alpaca.markets"
MAX_ORDER_NOTIONAL = 25_000.0
MAX_SHARES = 10_000
PREVIEW_SECONDS = 300

_SYMBOL = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
_ORDER_TYPES = ("market", "limit")
_SIDES = ("buy", "sell")
_TIFS = ("day", "gtc")


def _base(mode: str) -> str:
    if mode == "paper":
        return PAPER_URL
    if mode == "live":
        return LIVE_URL
    raise AlpacaError("Unknown trading mode.")


class AlpacaError(Exception):
    """A readable failure (bad key, rejected order, no connection, ...)."""
    status: int | None = None       # the HTTP status when Alpaca answered; 0 when it could not be reached


def _headers(key_id: str, secret: str) -> dict:
    return {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret, "Accept": "application/json"}


def _request(
    method: str, url: str, keys: tuple[str, str], *, body: dict | None = None,
    urlopen=None, timeout: float = 10.0,
):
    headers = _headers(*keys)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urlopen or urllib.request.urlopen  # looked up now so tests can patch it
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        message = ""
        try:
            message = str(json.loads(exc.read().decode("utf-8")).get("message") or "")
        except Exception:  # noqa: BLE001 -- an unreadable error body just means no extra detail
            pass
        reasons = {
            401: "Alpaca rejected the keys. Check that they are the right kind (paper keys for practice, live keys for real trading) and re-enter them.",
            403: "Alpaca refused this request (the key may not be allowed to trade).",
            404: "Alpaca could not find that.",
            422: f"Alpaca rejected the order: {message}" if message else "Alpaca rejected the order.",
            429: "Alpaca's request limit was reached. Try again in a minute.",
        }
        err = AlpacaError(reasons.get(exc.code, f"Alpaca returned an error (HTTP {exc.code}). {message}".strip()))
        err.status = exc.code
        raise err from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        err = AlpacaError("Couldn't reach Alpaca. Check the internet connection.")
        err.status = 0
        raise err from exc
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise AlpacaError("Alpaca sent a response this program couldn't read.") from exc


def _f(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_account(keys: tuple[str, str], *, mode: str = "paper", **kw) -> dict:
    raw = _request("GET", f"{_base(mode)}/v2/account", keys, **kw)
    if not isinstance(raw, dict):
        raise AlpacaError("Alpaca sent an account this program couldn't read.")
    return {
        "status": str(raw.get("status") or ""),
        "account_number": str(raw.get("account_number") or ""),
        "equity": _f(raw.get("equity")),
        "last_equity": _f(raw.get("last_equity")),
        "cash": _f(raw.get("cash")),
        "buying_power": _f(raw.get("buying_power")),
        "trading_blocked": bool(raw.get("trading_blocked") or raw.get("account_blocked")),
    }


def list_positions(keys: tuple[str, str], *, mode: str = "paper", **kw) -> list[dict]:
    raw = _request("GET", f"{_base(mode)}/v2/positions", keys, **kw) or []
    return [
        {
            "symbol": str(p.get("symbol") or ""), "qty": _f(p.get("qty")), "side": str(p.get("side") or "long"),
            "avg_entry_price": _f(p.get("avg_entry_price")), "current_price": _f(p.get("current_price")),
            "market_value": _f(p.get("market_value")), "unrealized_pl": _f(p.get("unrealized_pl")),
            "unrealized_plpc": _f(p.get("unrealized_plpc")),
        }
        for p in raw if isinstance(p, dict)
    ]


def list_orders(keys: tuple[str, str], *, limit: int = 30, mode: str = "paper", **kw) -> list[dict]:
    query = urllib.parse.urlencode({"status": "all", "limit": limit, "direction": "desc"})
    raw = _request("GET", f"{_base(mode)}/v2/orders?{query}", keys, **kw) or []
    return [
        {
            "id": str(o.get("id") or ""), "symbol": str(o.get("symbol") or ""), "side": str(o.get("side") or ""),
            "qty": _f(o.get("qty")), "type": str(o.get("type") or o.get("order_type") or ""),
            "status": str(o.get("status") or ""), "limit_price": _f(o.get("limit_price")),
            "filled_qty": _f(o.get("filled_qty")), "filled_avg_price": _f(o.get("filled_avg_price")),
            "submitted_at": str(o.get("submitted_at") or o.get("created_at") or ""),
            "time_in_force": str(o.get("time_in_force") or ""),
        }
        for o in raw if isinstance(o, dict)
    ]


def last_price(symbol: str, keys: tuple[str, str], **kw) -> float | None:
    """The latest trade price (free IEX feed), or None when unavailable --
    only used to size-check an order, so a miss is not an error."""
    try:
        raw = _request(
            "GET", f"{DATA_URL}/v2/stocks/{urllib.parse.quote(symbol)}/trades/latest?feed=iex", keys, **kw,
        )
    except AlpacaError:
        return None
    price = _f(((raw or {}).get("trade") or {}).get("p")) if isinstance(raw, dict) else None
    return price if price and price > 0 else None


def _symbol(symbol) -> str:
    sym = str(symbol or "").strip().upper()
    if not _SYMBOL.match(sym):
        raise AlpacaError("Enter a stock or ETF ticker, for example AAPL or VTI.")
    return sym


def _bar(raw: dict) -> dict | None:
    o, h, l, c = (_f(raw.get(k)) for k in ("o", "h", "l", "c"))
    if None in (o, h, l, c) or c <= 0:
        return None
    return {"t": str(raw.get("t") or ""), "o": o, "h": h, "l": l, "c": c, "v": _f(raw.get("v")) or 0.0}


def get_bars(symbol: str, keys: tuple[str, str], *, timeframe: str = "1Day", start: str, limit: int = 1000, **kw) -> list[dict]:
    """Price bars, oldest first, from Alpaca's free IEX feed (split-adjusted).
    Each bar is {"t": ISO time, "o", "h", "l", "c", "v"}. Reading prices needs
    keys but never changes anything, so it works for either account."""
    sym = _symbol(symbol)
    query = urllib.parse.urlencode({
        "timeframe": timeframe, "start": start, "limit": int(limit), "adjustment": "split", "feed": "iex", "sort": "asc",
    })
    raw = _request("GET", f"{DATA_URL}/v2/stocks/{urllib.parse.quote(sym)}/bars?{query}", keys, **kw)
    items = (raw or {}).get("bars") if isinstance(raw, dict) else None
    bars = [b for b in (_bar(x) for x in (items or []) if isinstance(x, dict)) if b]
    return bars


def get_snapshot(symbol: str, keys: tuple[str, str], **kw) -> dict:
    """Today's quote for one symbol: last trade, bid/ask, today's bar and the
    previous day's bar (all optional -- a closed market or a thinly traded
    symbol can leave some of them out)."""
    sym = _symbol(symbol)
    raw = _request("GET", f"{DATA_URL}/v2/stocks/{urllib.parse.quote(sym)}/snapshot?feed=iex", keys, **kw)
    if isinstance(raw, dict) and sym in raw and isinstance(raw[sym], dict):
        raw = raw[sym]
    if not isinstance(raw, dict):
        raise AlpacaError("Alpaca sent a quote this program couldn't read.")
    return _snapshot_from(sym, raw)


_NAME_TAIL = re.compile(r"[\s,-]+(Common Stock|Common Shares|Ordinary Shares|Capital Stock)$", re.I)


def clean_company_name(name) -> str:
    """Alpaca names read like "Apple Inc. Common Stock"; the share-type tail is noise here."""
    text = " ".join(str(name or "").split())
    return _NAME_TAIL.sub("", text).strip()


def get_asset_name(symbol: str, keys: tuple[str, str], *, mode: str = "paper", **kw) -> str | None:
    """The company or fund name for a ticker, or None when Alpaca has no such asset or
    can't be reached (the name is a nicety, never an error). Uses the account host for
    ``mode``; reading an asset changes nothing."""
    sym = _symbol(symbol)
    try:
        raw = _request("GET", f"{_base(mode)}/v2/assets/{urllib.parse.quote(sym)}", keys, **kw)
    except AlpacaError:
        return None
    name = clean_company_name((raw or {}).get("name")) if isinstance(raw, dict) else ""
    return name or None


def _news_item(raw: dict) -> dict | None:
    headline = " ".join(str(raw.get("headline") or "").split())
    url = str(raw.get("url") or "").strip()
    if not headline or not url.lower().startswith(("https://", "http://")):
        return None     # only ordinary web links are ever shown
    summary = " ".join(str(raw.get("summary") or "").split())
    return {
        "headline": headline[:240], "summary": summary[:280] + ("..." if len(summary) > 280 else ""),
        "source": str(raw.get("source") or "").strip()[:40], "url": url[:500],
        "time": str(raw.get("created_at") or raw.get("updated_at") or ""),
    }


def get_news(symbol: str, keys: tuple[str, str], *, limit: int = 8, **kw) -> list[dict]:
    """The latest headlines mentioning a ticker (Alpaca's news feed), newest first, as
    {"headline", "summary", "source", "url", "time"}. Read-only."""
    sym = _symbol(symbol)
    query = urllib.parse.urlencode({"symbols": sym, "limit": int(limit), "sort": "desc", "include_content": "false"})
    raw = _request("GET", f"{DATA_URL}/v1beta1/news?{query}", keys, **kw)
    items = (raw or {}).get("news") if isinstance(raw, dict) else None
    return [n for n in (_news_item(x) for x in (items or []) if isinstance(x, dict)) if n]


def get_bars_multi(symbols: list[str], keys: tuple[str, str], *, start: str, max_pages: int = 8, **kw) -> dict[str, list[dict]]:
    """Daily bars for several symbols in as few calls as possible (the watchlist).
    Returns {symbol: bars oldest first}; a symbol Alpaca has no bars for is simply
    missing or empty. Read-only, free IEX feed, split-adjusted."""
    syms = [_symbol(s) for s in symbols]
    out: dict[str, list[dict]] = {s: [] for s in syms}
    if not syms:
        return out
    token = None
    for _ in range(max_pages):
        params = {"symbols": ",".join(syms), "timeframe": "1Day", "start": start, "limit": 10000,
                  "adjustment": "split", "feed": "iex", "sort": "asc"}
        if token:
            params["page_token"] = token
        raw = _request("GET", f"{DATA_URL}/v2/stocks/bars?{urllib.parse.urlencode(params)}", keys, **kw)
        by_sym = (raw or {}).get("bars") if isinstance(raw, dict) else None
        if isinstance(by_sym, dict):
            for sym, items in by_sym.items():
                if sym in out and isinstance(items, list):
                    out[sym].extend(b for b in (_bar(x) for x in items if isinstance(x, dict)) if b)
        token = raw.get("next_page_token") if isinstance(raw, dict) else None
        if not token:
            break
    return out


def _snapshot_from(sym: str, raw: dict) -> dict:
    trade, quote = raw.get("latestTrade") or {}, raw.get("latestQuote") or {}
    daily, prev = raw.get("dailyBar") or {}, raw.get("prevDailyBar") or {}
    return {
        "symbol": sym,
        "price": _f(trade.get("p")),
        "trade_time": str(trade.get("t") or ""),
        "bid": _f(quote.get("bp")), "ask": _f(quote.get("ap")),
        "bid_size": _f(quote.get("bs")), "ask_size": _f(quote.get("as")),
        "day": _bar(daily) if isinstance(daily, dict) else None,
        "prev_day": _bar(prev) if isinstance(prev, dict) else None,
    }


def get_snapshots(symbols: list[str], keys: tuple[str, str], **kw) -> dict[str, dict]:
    """Today's quote for several symbols in one call: {symbol: snapshot} in the
    same shape get_snapshot returns. Symbols with nothing to show are left out."""
    syms = [_symbol(s) for s in symbols]
    if not syms:
        return {}
    query = urllib.parse.urlencode({"symbols": ",".join(syms), "feed": "iex"})
    raw = _request("GET", f"{DATA_URL}/v2/stocks/snapshots?{query}", keys, **kw)
    if isinstance(raw, dict) and isinstance(raw.get("snapshots"), dict):
        raw = raw["snapshots"]
    if not isinstance(raw, dict):
        raise AlpacaError("Alpaca sent a quote this program couldn't read.")
    return {sym: _snapshot_from(sym, raw[sym]) for sym in syms if isinstance(raw.get(sym), dict)}


SESSIONS = ("regular", "extended", "overnight")


def clean_order(order: dict) -> dict:
    """Validates and normalises the order a person typed; raises AlpacaError
    with a plain-language reason."""
    symbol = str(order.get("symbol") or "").strip().upper()
    if not _SYMBOL.match(symbol):
        raise AlpacaError("Enter a stock or fund symbol, such as VTI.")
    side = str(order.get("side") or "").lower()
    if side not in _SIDES:
        raise AlpacaError("Choose buy or sell.")
    try:
        qty = float(order.get("qty"))
    except (TypeError, ValueError):
        raise AlpacaError("Enter how many shares.") from None
    if qty <= 0 or qty != int(qty):
        raise AlpacaError("Shares must be a whole number greater than zero.")
    if qty > MAX_SHARES:
        raise AlpacaError(f"One order can be at most {MAX_SHARES:,} shares.")
    order_type = str(order.get("type") or "market").lower()
    if order_type not in _ORDER_TYPES:
        raise AlpacaError("Choose a market or limit order.")
    limit_price = None
    if order_type == "limit":
        limit_price = _f(order.get("limit_price"))
        if not limit_price or limit_price <= 0:
            raise AlpacaError("A limit order needs a limit price above zero.")
        limit_price = round(limit_price, 2)
    tif = str(order.get("time_in_force") or "day").lower()
    if tif not in _TIFS:
        raise AlpacaError("Choose how long the order stays open.")
    session = str(order.get("session") or "regular").lower()
    if session not in SESSIONS:
        raise AlpacaError("Choose regular hours, extended hours or overnight.")
    if session != "regular":
        if order_type != "limit":
            raise AlpacaError("Outside regular trading hours only limit orders are accepted. Choose Limit and enter your price.")
        tif = "day"
    if order_type == "market":
        tif = "day"
    return {"symbol": symbol, "side": side, "qty": int(qty), "type": order_type,
            "limit_price": limit_price, "time_in_force": tif, "session": session}


_previews: dict[str, tuple[float, dict, str, float]] = {}


def _forget_expired(now: float) -> None:
    for token in [t for t, entry in _previews.items() if entry[0] < now]:
        _previews.pop(token, None)


def _money_text(value: float) -> str:
    return f"${value:,.0f}"


def preview_order(
    order: dict, keys: tuple[str, str], *, mode: str = "paper", max_notional: float | None = None,
    daily_remaining: float | None = None, now: float | None = None, **kw,
) -> dict:
    """Checks an order and prices it, without sending it. Returns the clean
    order, its estimated value, and the single-use token that place_order
    needs. ``max_notional`` (a per-order limit) and ``daily_remaining`` (what
    is left of a daily limit) can only tighten the built-in limit. Raises
    AlpacaError when the order is invalid, too large, or (for a market order)
    cannot be sized."""
    _base(mode)
    clean = clean_order(order)
    price = clean["limit_price"] or last_price(clean["symbol"], keys, **kw)
    if price is None:
        raise AlpacaError(
            "Couldn't get a recent price for that symbol, so the order's size can't be checked. "
            "Check the symbol, or use a limit order with your own price."
        )
    estimate = round(price * clean["qty"], 2)
    limit = MAX_ORDER_NOTIONAL if max_notional is None else max_notional      # real-money limits are the owner's (Setup)
    if estimate > limit:
        raise AlpacaError(f"That order is worth about {_money_text(estimate)}. One order here is limited to {_money_text(limit)}.")
    if daily_remaining is not None and estimate > daily_remaining:
        raise AlpacaError(
            f"That order is worth about {_money_text(estimate)}, which is more than the {_money_text(max(daily_remaining, 0))} "
            "left of today's trading limit."
        )
    stamp = time.time() if now is None else now
    _forget_expired(stamp)
    token = secrets.token_urlsafe(24)
    _previews[token] = (stamp + PREVIEW_SECONDS, clean, mode, estimate)
    return {"order": clean, "price": price, "estimate": estimate, "token": token, "expires_in": PREVIEW_SECONDS, "mode": mode}


def preview_details(token: str, *, now: float | None = None) -> dict | None:
    """The order a still-valid preview token was issued for (without using the
    token up), or None -- lets the caller check what is about to be sent."""
    stamp = time.time() if now is None else now
    entry = _previews.get(str(token or ""))
    if entry is None or entry[0] < stamp:
        return None
    return {**entry[1], "estimate": entry[3], "mode": entry[2]}


def place_order(
    token: str, keys: tuple[str, str], *, mode: str = "paper", daily_remaining: float | None = None,
    now: float | None = None, **kw,
) -> dict:
    """Sends the order a preview token was issued for. The token is single-use,
    expires after a few minutes, and works only in the mode it was issued for."""
    _base(mode)
    stamp = time.time() if now is None else now
    entry = _previews.pop(str(token or ""), None)
    if entry is None or entry[0] < stamp:
        raise AlpacaError("That order's preview has expired. Preview it again, then confirm.")
    _expires, clean, entry_mode, estimate = entry
    if entry_mode != mode:
        raise AlpacaError("That preview was made for a different account. Preview it again, then confirm.")
    if daily_remaining is not None and estimate > daily_remaining:
        raise AlpacaError("That order would go over today's trading limit.")
    body = {
        "symbol": clean["symbol"], "qty": str(clean["qty"]), "side": clean["side"], "type": clean["type"],
        "time_in_force": clean["time_in_force"], "client_order_id": "fs-" + secrets.token_hex(8),
    }
    if clean["limit_price"] is not None:
        body["limit_price"] = str(clean["limit_price"])
    if clean["session"] != "regular":
        body["extended_hours"] = True          # pre-market, after-hours and the overnight session; Alpaca takes limit + day only
    raw = _request("POST", f"{_base(mode)}/v2/orders", keys, body=body, **kw)
    return {"id": str((raw or {}).get("id") or ""), "status": str((raw or {}).get("status") or "accepted"),
            "estimate": estimate, "mode": mode, **clean}


def cancel_order(order_id: str, keys: tuple[str, str], *, mode: str = "paper", **kw) -> None:
    order_id = str(order_id or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", order_id):
        raise AlpacaError("That order id isn't valid.")
    _request("DELETE", f"{_base(mode)}/v2/orders/{order_id}", keys, **kw)
