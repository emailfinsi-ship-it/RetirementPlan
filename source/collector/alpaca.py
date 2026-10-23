"""Alpaca PAPER trading (https://docs.alpaca.markets) for the Trading tab.

Safety rules, enforced here rather than in the page so nothing can bypass them:

* **Paper only.** The only trading host this module can talk to is
  ``PAPER_URL``. There is no parameter, setting or key that switches it to the
  live host, so no real money can move through this program.
* **Preview, then confirm.** An order is placed only with a single-use token
  that ``preview_order`` issued for exactly those details a few minutes
  earlier, so a stray or replayed request cannot place one.
* **Size limit.** One order may not be worth more than ``MAX_ORDER_NOTIONAL``
  (a market order needs a recent price so the size can be checked).

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
DATA_URL = "https://data.alpaca.markets"
MAX_ORDER_NOTIONAL = 25_000.0
MAX_SHARES = 10_000
PREVIEW_SECONDS = 300

_SYMBOL = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
_ORDER_TYPES = ("market", "limit")
_SIDES = ("buy", "sell")
_TIFS = ("day", "gtc")


class AlpacaError(Exception):
    """A readable failure (bad key, rejected order, no connection, ...)."""


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
            401: "Alpaca rejected the keys. Check that they are PAPER keys and re-enter them.",
            403: "Alpaca refused this request (the key may not be allowed to trade).",
            404: "Alpaca could not find that.",
            422: f"Alpaca rejected the order: {message}" if message else "Alpaca rejected the order.",
            429: "Alpaca's request limit was reached. Try again in a minute.",
        }
        raise AlpacaError(reasons.get(exc.code, f"Alpaca returned an error (HTTP {exc.code}). {message}".strip())) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AlpacaError("Couldn't reach Alpaca. Check the internet connection.") from exc
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


def get_account(keys: tuple[str, str], **kw) -> dict:
    raw = _request("GET", f"{PAPER_URL}/v2/account", keys, **kw)
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


def list_positions(keys: tuple[str, str], **kw) -> list[dict]:
    raw = _request("GET", f"{PAPER_URL}/v2/positions", keys, **kw) or []
    return [
        {
            "symbol": str(p.get("symbol") or ""), "qty": _f(p.get("qty")), "side": str(p.get("side") or "long"),
            "avg_entry_price": _f(p.get("avg_entry_price")), "current_price": _f(p.get("current_price")),
            "market_value": _f(p.get("market_value")), "unrealized_pl": _f(p.get("unrealized_pl")),
            "unrealized_plpc": _f(p.get("unrealized_plpc")),
        }
        for p in raw if isinstance(p, dict)
    ]


def list_orders(keys: tuple[str, str], *, limit: int = 30, **kw) -> list[dict]:
    query = urllib.parse.urlencode({"status": "all", "limit": limit, "direction": "desc"})
    raw = _request("GET", f"{PAPER_URL}/v2/orders?{query}", keys, **kw) or []
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
    if order_type == "market":
        tif = "day"
    return {"symbol": symbol, "side": side, "qty": int(qty), "type": order_type,
            "limit_price": limit_price, "time_in_force": tif}


_previews: dict[str, tuple[float, dict]] = {}


def _forget_expired(now: float) -> None:
    for token in [t for t, (expires, _o) in _previews.items() if expires < now]:
        _previews.pop(token, None)


def preview_order(order: dict, keys: tuple[str, str], *, now: float | None = None, **kw) -> dict:
    """Checks an order and prices it, without sending it. Returns the clean
    order, its estimated value, and the single-use token that place_order
    needs. Raises AlpacaError when the order is invalid, too large, or (for a
    market order) cannot be sized."""
    clean = clean_order(order)
    price = clean["limit_price"] or last_price(clean["symbol"], keys, **kw)
    if price is None:
        raise AlpacaError(
            "Couldn't get a recent price for that symbol, so the order's size can't be checked. "
            "Check the symbol, or use a limit order with your own price."
        )
    estimate = round(price * clean["qty"], 2)
    if estimate > MAX_ORDER_NOTIONAL:
        raise AlpacaError(
            f"That order is worth about ${estimate:,.0f}. One paper order here is limited to ${MAX_ORDER_NOTIONAL:,.0f}."
        )
    stamp = time.time() if now is None else now
    _forget_expired(stamp)
    token = secrets.token_urlsafe(24)
    _previews[token] = (stamp + PREVIEW_SECONDS, clean)
    return {"order": clean, "price": price, "estimate": estimate, "token": token, "expires_in": PREVIEW_SECONDS}


def place_order(token: str, keys: tuple[str, str], *, now: float | None = None, **kw) -> dict:
    """Sends the order a preview token was issued for. The token is single-use
    and expires after a few minutes."""
    stamp = time.time() if now is None else now
    entry = _previews.pop(str(token or ""), None)
    if entry is None or entry[0] < stamp:
        raise AlpacaError("That order's preview has expired. Preview it again, then confirm.")
    clean = entry[1]
    body = {
        "symbol": clean["symbol"], "qty": str(clean["qty"]), "side": clean["side"], "type": clean["type"],
        "time_in_force": clean["time_in_force"], "client_order_id": "fs-" + secrets.token_hex(8),
    }
    if clean["limit_price"] is not None:
        body["limit_price"] = str(clean["limit_price"])
    raw = _request("POST", f"{PAPER_URL}/v2/orders", keys, body=body, **kw)
    return {"id": str((raw or {}).get("id") or ""), "status": str((raw or {}).get("status") or "accepted"), **clean}


def cancel_order(order_id: str, keys: tuple[str, str], **kw) -> None:
    order_id = str(order_id or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", order_id):
        raise AlpacaError("That order id isn't valid.")
    _request("DELETE", f"{PAPER_URL}/v2/orders/{order_id}", keys, **kw)
