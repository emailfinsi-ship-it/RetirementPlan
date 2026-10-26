"""Interactive Brokers through IBKR's own **Client Portal Gateway** (their REST "Web API" run on your own computer).

How it connects: you download and start IBKR's Client Portal Gateway (a small Java program, usually listening on
https://localhost:5000), open that address in a browser and sign in to your IBKR account there. This program then
talks to the gateway on the same computer; your IBKR password never reaches this program, and nothing here can work
while the gateway is stopped or signed out. The gateway uses a self-made certificate, so the certificate is not
checked, which is why the address is only ever accepted when it points at this computer.

Orders follow source.collector.broker_common: preview first, then a single-use token to send. IBKR sometimes asks
a question before accepting an order (for example about price or market data); this module never answers those on
its own: it hands the question back so the person can read it and choose to send anyway.

Every network call goes through ``Gateway.opener`` so tests never touch a real gateway. The response shapes below
follow IBKR's published Web API; the parsers are tolerant, and anything unreadable becomes a plain-language error.
"""

from __future__ import annotations

import json
import re
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request

from source.collector import broker_common as bc
from source.collector.broker_common import BrokerError
from source.common import branding

DEFAULT_URL = "https://localhost:5000"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
_NAME = "Interactive Brokers"

book = bc.PreviewBook()

# Ports a Client Portal Gateway is commonly set to listen on (its own default is 5000, but macOS uses 5000 for AirPlay,
# so many people change it). Tried only on this computer, only when the saved address does not answer.
COMMON_PORTS = (5000, 5001, 5500, 5555, 8888, 8443)


class GatewayDown(BrokerError):
    """Nothing answered at the gateway address (not started, wrong port, or blocked)."""


def clean_gateway_url(value) -> str:
    """The gateway address, only if it points at this computer."""
    text = str(value or "").strip() or DEFAULT_URL
    if "://" not in text:
        text = "https://" + text
    parts = urllib.parse.urlsplit(text)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("https", "http") or (host not in _LOCAL_HOSTS and f"[{host}]" not in _LOCAL_HOSTS):
        raise BrokerError("The IBKR gateway must run on this computer (https://localhost:5000 is usual).")
    port = f":{parts.port}" if parts.port else ""
    shown = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown}{port}"


def _default_opener():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False                    # the gateway's certificate is self-made, and only localhost is allowed
    ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx)).open


class Gateway:
    def __init__(self, url: str = DEFAULT_URL, opener=None, timeout: float = 10.0):
        self.base = clean_gateway_url(url) + "/v1/api"
        self.opener = opener or _default_opener()
        self.timeout = timeout

    def call(self, method: str, path: str, body=None):
        data = None
        headers = {"Accept": "application/json", "User-Agent": branding.PRODUCT_NAME}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with self.opener(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = str(payload.get("error") or payload.get("message") or "") if isinstance(payload, dict) else ""
            except Exception:  # noqa: BLE001 -- no readable detail is fine
                pass
            if exc.code in (401, 403):
                raise BrokerError("IBKR's gateway is not signed in. Open the gateway address in your browser and sign in, then try again.") from exc
            raise BrokerError(f"IBKR returned an error (HTTP {exc.code}). {detail}".strip()) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GatewayDown("Couldn't reach the IBKR gateway on this computer. Start the Client Portal Gateway and sign in to it first.") from exc
        if not raw.strip():
            return None
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise BrokerError("IBKR's gateway sent a response this program couldn't read.") from exc


def _f(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(value))
    try:
        return float(m.group(0).replace(",", "")) if m else None
    except ValueError:
        return None


# ---- reading ----

def status(gw: Gateway) -> dict:
    """{"connected": bool, "message": text}: is the gateway up and signed in?"""
    try:
        raw = gw.call("GET", "/iserver/auth/status")
    except BrokerError as exc:
        return {"connected": False, "message": str(exc), "down": isinstance(exc, GatewayDown)}
    if isinstance(raw, dict) and raw.get("authenticated"):
        return {"connected": True, "message": "Connected to the IBKR gateway.", "down": False}
    return {"connected": False, "down": False,
            "message": "The IBKR gateway is running but not signed in. Open its address in your browser and sign in."}


def find_gateway(skip: str = "", *, opener=None, ports=COMMON_PORTS) -> str | None:
    """The address of a gateway that answers on this computer at one of the usual ports, or None."""
    skip = clean_gateway_url(skip) if skip else ""
    for port in ports:
        url = f"https://localhost:{port}"
        if url == skip:
            continue
        try:
            raw = Gateway(url, opener=opener, timeout=1.5).call("GET", "/iserver/auth/status")
        except GatewayDown:
            continue
        except BrokerError:
            return url              # something answered with an error (for example "not signed in"): it is the gateway
        if isinstance(raw, dict) and "authenticated" in raw:
            return url
    return None


def list_accounts(gw: Gateway) -> list[dict]:
    raw = gw.call("GET", "/iserver/accounts")
    names = (raw or {}).get("aliases") or {} if isinstance(raw, dict) else {}
    ids = (raw or {}).get("accounts") or [] if isinstance(raw, dict) else []
    return [{"id": str(a), "name": str(names.get(a) or a)} for a in ids]


def summary(gw: Gateway, account: str) -> dict:
    gw.call("GET", "/portfolio/accounts")        # the portfolio calls only work after this one has been made
    raw = gw.call("GET", f"/portfolio/{urllib.parse.quote(account)}/summary")
    raw = raw if isinstance(raw, dict) else {}

    def amount(*keys):
        for k in keys:
            item = raw.get(k)
            value = _f(item.get("amount") if isinstance(item, dict) else item)
            if value is not None:
                return value
        return None

    return {"value": amount("netliquidation"), "cash": amount("totalcashvalue", "settledcash"),
            "buying_power": amount("buyingpower", "availablefunds"), "currency": "USD"}


def positions(gw: Gateway, account: str) -> list[dict]:
    gw.call("GET", "/portfolio/accounts")
    out = []
    page = 0
    while page < 10:
        raw = gw.call("GET", f"/portfolio/{urllib.parse.quote(account)}/positions/{page}")
        if not isinstance(raw, list) or not raw:
            break
        for p in raw:
            qty = _f(p.get("position"))
            if not qty or str(p.get("assetClass") or "STK").upper() not in ("STK", "ETF", ""):
                continue
            symbol = str(p.get("ticker") or p.get("contractDesc") or "").split()[0].upper()
            price, value, cost = _f(p.get("mktPrice")), _f(p.get("mktValue")), _f(p.get("avgCost"))
            out.append({"symbol": symbol, "name": str(p.get("name") or p.get("contractDesc") or ""), "qty": qty, "avg_cost": cost,
                        "price": price, "market_value": value,
                        "gain": _f(p.get("unrealizedPnl")), "conid": p.get("conid")})
        if len(raw) < 100:
            break
        page += 1
    return sorted(out, key=lambda r: -(r["market_value"] or 0))


_DONE = {"filled", "cancelled", "inactive", "rejected"}


def open_orders(gw: Gateway, account: str | None = None) -> list[dict]:
    gw.call("GET", "/iserver/accounts")
    raw = gw.call("GET", "/iserver/account/orders")
    items = raw.get("orders") if isinstance(raw, dict) else raw
    out = []
    for o in items or []:
        if account and str(o.get("acct") or account) != account:
            continue
        status_text = str(o.get("status") or o.get("order_ccp_status") or "")
        qty = _f(o.get("totalSize") or o.get("remainingQuantity"))
        out.append({
            "id": str(o.get("orderId") or ""), "symbol": str(o.get("ticker") or o.get("description1") or "").upper(),
            "side": str(o.get("side") or "").lower().replace("buy", "buy").replace("sell", "sell"),
            "qty": qty, "filled": _f(o.get("filledQuantity")) or 0.0,
            "type": str(o.get("orderType") or o.get("origOrderType") or "").lower(),
            "limit_price": _f(o.get("price")), "status": status_text,
            "open": status_text.lower() not in _DONE,
        })
    return out


def find_conid(gw: Gateway, symbol: str) -> int:
    raw = gw.call("GET", f"/trsrv/stocks?symbols={urllib.parse.quote(symbol)}")
    for item in (raw or {}).get(symbol) or [] if isinstance(raw, dict) else []:
        contracts = item.get("contracts") or []
        for c in contracts:
            if c.get("isUS") and c.get("conid"):
                return int(c["conid"])
        if contracts and contracts[0].get("conid"):
            return int(contracts[0]["conid"])
    raise BrokerError(f"IBKR could not find a stock or fund called {symbol}.")


def last_price(gw: Gateway, conid: int) -> float | None:
    for _ in range(2):                            # the first request only starts the data; the second has it
        raw = gw.call("GET", f"/iserver/marketdata/snapshot?conids={conid}&fields=31")
        if isinstance(raw, list) and raw:
            price = _f(raw[0].get("31"))
            if price:
                return price
    return None


# ---- trading ----

def preview(gw: Gateway, account: str, order: dict, *, max_notional=None, daily_remaining=None) -> dict:
    clean = bc.clean_order(order)
    conid = find_conid(gw, clean["symbol"])
    price = clean["limit_price"] or last_price(gw, conid)
    if price is None:
        raise BrokerError(
            "Couldn't get a recent price for that symbol (your IBKR market-data subscription may not cover it), so the order's size "
            "can't be checked. Use a limit order with your own price."
        )
    estimate = round(price * clean["qty"], 2)
    bc.check_size(estimate, max_notional=max_notional, daily_remaining=daily_remaining)
    token = book.issue({"broker": "ibkr", "account": account, "order": clean, "conid": conid, "estimate": estimate})
    return {"order": clean, "price": price, "estimate": estimate, "token": token, "expires_in": bc.PREVIEW_SECONDS, "broker": "ibkr"}


def _order_body(account: str, clean: dict, conid: int) -> dict:
    body = {"acctId": account, "conid": conid, "secType": f"{conid}:STK", "cOID": "fs-" + secrets.token_hex(8),
            "orderType": "LMT" if clean["type"] == "limit" else "MKT", "side": clean["side"].upper(),
            "tif": clean["time_in_force"].upper(), "quantity": clean["qty"], "outsideRTH": False}
    if clean["limit_price"] is not None:
        body["price"] = clean["limit_price"]
    return {"orders": [body]}


def _questions(raw) -> tuple[str | None, list[str]]:
    """(reply id, messages) when IBKR is asking a question before it accepts the order."""
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("id") and (item.get("message") or item.get("messageIds")):
                msgs = item.get("message") or []
                return str(item["id"]), [str(m) for m in (msgs if isinstance(msgs, list) else [msgs])]
    return None, []


def _result(raw, entry: dict) -> dict:
    items = raw if isinstance(raw, list) else [raw]
    for item in items:
        if isinstance(item, dict) and item.get("order_id"):
            return {"id": str(item["order_id"]), "status": str(item.get("order_status") or "submitted"), "estimate": entry["estimate"],
                    **entry["order"], "broker": "ibkr"}
    for item in items:
        if isinstance(item, dict) and item.get("error"):
            raise BrokerError(f"IBKR rejected the order: {item['error']}")
    raise BrokerError("IBKR answered, but this program could not tell whether the order was accepted. Check IBKR before trying again.")


def _handle_reply(gw: Gateway, account: str, raw, entry: dict) -> dict:
    reply_id, messages = _questions(raw)
    if reply_id:
        token = book.issue({**entry, "reply_id": reply_id, "messages": messages})
        return {"ack_required": True, "messages": messages, "token": token, "broker": "ibkr"}
    return _result(raw, entry)


def place(gw: Gateway, account: str, token: str, *, daily_remaining=None) -> dict:
    """Sends the order a preview token was issued for. If IBKR asks a question first, nothing is sent yet: the
    answer comes back with ``ack_required`` and a new token to use if the person chooses to go ahead."""
    entry = book.claim(token, broker="ibkr", account=account)
    if entry.get("reply_id"):                      # the person has read IBKR's question and chose to send anyway
        raw = gw.call("POST", f"/iserver/reply/{urllib.parse.quote(entry['reply_id'])}", {"confirmed": True})
        return _handle_reply(gw, account, raw, {k: v for k, v in entry.items() if k not in ("reply_id", "messages")})
    if daily_remaining is not None and entry["estimate"] > daily_remaining:
        raise BrokerError("That order would go over today's trading limit.")
    raw = gw.call("POST", f"/iserver/account/{urllib.parse.quote(account)}/orders", _order_body(account, entry["order"], entry["conid"]))
    return _handle_reply(gw, account, raw, entry)


def cancel(gw: Gateway, account: str, order_id: str) -> None:
    order_id = str(order_id or "")
    if not re.fullmatch(r"[0-9A-Za-z_.-]{1,64}", order_id):
        raise BrokerError("That order id isn't valid.")
    gw.call("GET", "/iserver/accounts")
    gw.call("DELETE", f"/iserver/account/{urllib.parse.quote(account)}/order/{urllib.parse.quote(order_id)}")
