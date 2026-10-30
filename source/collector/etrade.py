"""E*TRADE (https://developer.etrade.com): balances, positions, quotes and orders for the E*TRADE tab.

How it connects: E*TRADE uses OAuth 1.0a. You paste your own consumer key and secret (from E*TRADE's developer
page), this program asks E*TRADE for a one-time sign-in link, you approve it in your browser and paste back the
short code E*TRADE shows, and E*TRADE then gives this program a session. Your E*TRADE password never reaches this
program. A session lasts until midnight US Eastern (and ends after two hours without use), so each day you start
trading you connect again; that is E*TRADE's rule, not something this program can change.

Orders follow source.collector.broker_common: E*TRADE's own preview is called first (it checks the order and gives
a cost estimate), then a single-use token sends exactly that previewed order. E*TRADE states that its Customer
Protection Guarantee does not cover orders sent through the API.

Every network call goes through the client's ``opener`` so tests never touch E*TRADE. The response shapes follow
E*TRADE's published API; the parsers are tolerant and anything unreadable becomes a plain-language error.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from source.collector import broker_common as bc
from source.collector.broker_common import BrokerError

LIVE_BASE = "https://api.etrade.com"
SANDBOX_BASE = "https://apisb.etrade.com"
AUTHORIZE_URL = "https://us.etrade.com/e/t/etws/authorize"

book = bc.PreviewBook()


def _enc(value) -> str:
    return urllib.parse.quote(str(value), safe="~")


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Client:
    def __init__(self, consumer_key: str, consumer_secret: str, token: str = "", token_secret: str = "", *,
                 sandbox: bool = False, opener=None, timeout: float = 15.0, clock=time.time):
        if not consumer_key or not consumer_secret:
            raise BrokerError("Save your E*TRADE consumer key and secret first.")
        self.ck, self.cs, self.token, self.ts = consumer_key, consumer_secret, token, token_secret
        self.base = SANDBOX_BASE if sandbox else LIVE_BASE
        self.opener = opener or urllib.request.urlopen
        self.timeout, self.clock = timeout, clock
        self.renewed = False

    # -- OAuth 1.0a signing (HMAC-SHA1) --
    def _auth_header(self, method: str, url: str, query: dict, extra: dict | None = None) -> str:
        oauth = {"oauth_consumer_key": self.ck, "oauth_nonce": secrets.token_hex(16), "oauth_signature_method": "HMAC-SHA1",
                 "oauth_timestamp": str(int(self.clock())), "oauth_version": "1.0"}
        if self.token:
            oauth["oauth_token"] = self.token
        oauth.update(extra or {})
        pairs = sorted((_enc(k), _enc(v)) for k, v in {**query, **oauth}.items())
        base = "&".join([method.upper(), _enc(url), _enc("&".join(f"{k}={v}" for k, v in pairs))])
        key = f"{_enc(self.cs)}&{_enc(self.ts)}"
        oauth["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
        return "OAuth " + ", ".join(f'{_enc(k)}="{_enc(v)}"' for k, v in sorted(oauth.items()))

    def raw(self, method: str, path: str, *, query: dict | None = None, body=None, extra_oauth: dict | None = None) -> str:
        query = {k: str(v) for k, v in (query or {}).items()}
        url = self.base + path
        full = url + ("?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote) if query else "")
        headers = {"Authorization": self._auth_header(method, url, query, extra_oauth), "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(full, data=data, headers=headers, method=method)
        try:
            with self.opener(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            message, problem = "", ""
            try:
                body = exc.read().decode("utf-8")
                try:
                    payload = json.loads(body)
                    message = str((payload.get("Error") or {}).get("message") or "") if isinstance(payload, dict) else ""
                except ValueError:
                    problem = re.sub(r"[^A-Za-z0-9_ ,.-]", "", str(_form(body).get("oauth_problem") or ""))[:60]
            except Exception:  # noqa: BLE001 -- no readable detail is fine
                pass
            if exc.code == 401:
                why = f" E*TRADE's reason: {problem or message}." if (problem or message) else ""
                raise BrokerError("E*TRADE says the session is not valid (it ends every night). Press Connect to sign in again." + why) from exc
            if exc.code == 429:
                raise BrokerError("E*TRADE's request limit was reached. Try again in a minute.") from exc
            raise BrokerError(f"E*TRADE returned an error (HTTP {exc.code}). {message}".strip()) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BrokerError("Couldn't reach E*TRADE. Check the internet connection.") from exc

    def json(self, method: str, path: str, *, query: dict | None = None, body=None):
        try:
            text = self.raw(method, path + ".json", query=query, body=body)
        except BrokerError as exc:
            # After two idle hours E*TRADE parks a session; renewing wakes it without asking you to sign in again.
            # (A session that has passed midnight US Eastern cannot be renewed, so that still asks you to Connect.)
            if "session is not valid" not in str(exc) or not self.token or self.renewed:
                raise
            self.renewed = True
            try:
                self.raw("GET", "/oauth/renew_access_token")
            except BrokerError:
                raise exc from None
            text = self.raw(method, path + ".json", query=query, body=body)
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise BrokerError("E*TRADE sent a response this program couldn't read.") from exc
        if isinstance(data, dict) and isinstance(data.get("Error"), dict):
            raise BrokerError(f"E*TRADE: {data['Error'].get('message') or 'request refused'}")
        return data


# ---- connecting ----

def _form(text: str) -> dict:
    return {k: v[0] for k, v in urllib.parse.parse_qs(text.strip()).items()}


def start_login(consumer_key: str, consumer_secret: str, *, sandbox: bool = False, opener=None) -> dict:
    """Step 1: asks E*TRADE for a one-time token. Returns it with the address the person opens to approve."""
    c = Client(consumer_key, consumer_secret, sandbox=sandbox, opener=opener)
    got = _form(c.raw("GET", "/oauth/request_token", extra_oauth={"oauth_callback": "oob"}))
    if not got.get("oauth_token"):
        raise BrokerError("E*TRADE did not give a sign-in token. Check the consumer key and secret (sandbox keys only work in sandbox).")
    url = f"{AUTHORIZE_URL}?key={_enc(consumer_key)}&token={_enc(got['oauth_token'])}"
    return {"request_token": got["oauth_token"], "request_secret": got.get("oauth_token_secret", ""), "authorize_url": url}


def finish_login(consumer_key: str, consumer_secret: str, request_token: str, request_secret: str, verifier: str, *,
                 sandbox: bool = False, opener=None) -> dict:
    """Step 2: swaps the one-time token and the code E*TRADE displayed for a session."""
    verifier = str(verifier or "").strip()
    if not verifier:
        raise BrokerError("Paste the verification code E*TRADE showed you.")
    c = Client(consumer_key, consumer_secret, request_token, request_secret, sandbox=sandbox, opener=opener)
    got = _form(c.raw("GET", "/oauth/access_token", extra_oauth={"oauth_verifier": verifier}))
    if not got.get("oauth_token") or not got.get("oauth_token_secret"):
        raise BrokerError("E*TRADE did not accept that code. Start the sign-in again and paste the new code.")
    return {"token": got["oauth_token"], "token_secret": got["oauth_token_secret"]}


def renew(c: Client) -> None:
    """Keeps a session that has been idle alive (it is still cut off at midnight US Eastern)."""
    c.raw("GET", "/oauth/renew_access_token")


# ---- reading ----

def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def list_accounts(c: Client) -> list[dict]:
    data = c.json("GET", "/v1/accounts/list")
    accounts = ((data.get("AccountListResponse") or {}).get("Accounts") or {}).get("Account")
    out = []
    for a in _as_list(accounts):
        if str(a.get("accountStatus") or "ACTIVE").upper() != "ACTIVE" or str(a.get("institutionType") or "BROKERAGE").upper() != "BROKERAGE":
            continue
        key = str(a.get("accountIdKey") or "")
        if key:
            name = " ".join(x for x in (str(a.get("accountDesc") or a.get("accountName") or "").strip(), f"({a.get('accountId')})" if a.get("accountId") else "") if x)
            out.append({"id": key, "name": name or key})
    return out


def _first(*values):
    """The first value that parses as a number (a real 0 counts; a missing field does not)."""
    for v in values:
        n = _f(v)
        if n is not None:
            return n
    return None


def summary(c: Client, account: str) -> dict:
    data = c.json("GET", f"/v1/accounts/{urllib.parse.quote(account)}/balance", query={"instType": "BROKERAGE", "realTimeNAV": "true"})
    bal = data.get("BalanceResponse") or {}
    comp = bal.get("Computed") or {}
    rt = comp.get("RealTimeValues") or {}
    cash_block = bal.get("Cash") or {}
    margin = "MARGIN" in str(bal.get("accountType") or "").upper()
    # Field names differ between cash and margin accounts, and the real-time block is sometimes missing.
    value = _first(rt.get("totalAccountValue"), comp.get("accountBalance"), bal.get("accountValue"))
    if value is None:
        net_mv, net_cash = _f(rt.get("netMv")), _f(comp.get("netCash"))
        value = (net_mv or 0.0) + (net_cash or 0.0) if (net_mv is not None or net_cash is not None) else None
    cash = _first(comp.get("cashAvailableForInvestment"), comp.get("settledCashForInvestment"), comp.get("cashBalance"),
                  comp.get("netCash"), cash_block.get("moneyMktBalance"))
    power = _first(*( (comp.get("marginBuyingPower"), comp.get("cashBuyingPower")) if margin else (comp.get("cashBuyingPower"), comp.get("marginBuyingPower")) ),
                   cash)
    return {"value": value, "cash": cash, "buying_power": power, "currency": "USD"}


def positions(c: Client, account: str) -> list[dict]:
    data = c.json("GET", f"/v1/accounts/{urllib.parse.quote(account)}/portfolio", query={"count": 250})
    out = []
    for block in _as_list((data.get("PortfolioResponse") or {}).get("AccountPortfolio")):
        for p in _as_list(block.get("Position")):
            prod = p.get("Product") or {}
            if str(prod.get("securityType") or "EQ").upper() != "EQ":
                continue
            qty = _f(p.get("quantity"))
            if not qty:
                continue
            if str(p.get("positionType") or "LONG").upper() == "SHORT":
                qty = -abs(qty)
            paid = _f(p.get("pricePaid"))
            quick = p.get("Quick") or {}
            out.append({"position_id": str(p.get("positionId") or ""), "symbol": str(prod.get("symbol") or "").upper(),
                        "name": str(p.get("symbolDescription") or ""), "qty": qty,
                        "avg_cost": paid, "price": _f(quick.get("lastTrade")), "market_value": _f(p.get("marketValue")),
                        "gain": _f(p.get("totalGain")), "gain_pct": _f(p.get("totalGainPct")),
                        "change": _f(quick.get("change")), "change_pct": _f(quick.get("changePct")),
                        "day_gain": _f(p.get("daysGain")), "day_gain_pct": _f(p.get("daysGainPct")),
                        "pct_of_portfolio": _f(p.get("pctOfPortfolio")), "cost_basis": _f(p.get("totalCost")),
                        "acquired": _day(p.get("dateAcquired"))})
    return sorted(out, key=lambda r: -(r["market_value"] or 0))


def _day(ms) -> str:
    """E*TRADE gives dates as milliseconds since 1970; shown as YYYY-MM-DD."""
    n = _f(ms)
    if not n:
        return ""
    try:
        return datetime.fromtimestamp(n / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def lots(c: Client, account: str, symbol: str | None = None) -> list[dict]:
    """Every tax lot of every stock position in the account (or just one symbol's): when it was bought, how many shares
    remain, the price paid per share, the total cost basis, today's value, the gain (today's and total), and whether it is
    short or long term."""
    out = []
    want = str(symbol or "").strip().upper()
    for pos in positions(c, account):
        if not pos.get("position_id") or (want and pos["symbol"] != want):
            continue
        data = c.json("GET", f"/v1/accounts/{urllib.parse.quote(account)}/portfolio/{urllib.parse.quote(pos['position_id'])}")
        for lot in _as_list((data.get("PositionLotsResponse") or {}).get("PositionLot")):
            qty = _first(lot.get("remainingQty"), lot.get("availableQty"), lot.get("originalQty"))
            price = _f(lot.get("price"))
            cost = _first(lot.get("totalCost"), (qty * price) if (qty is not None and price is not None) else None)
            term = str(lot.get("termCode") or "").upper()
            out.append({"symbol": pos["symbol"], "acquired": _day(lot.get("acquiredDate")), "qty": qty, "cost_per_share": price,
                        "cost_basis": cost, "market_value": _f(lot.get("marketValue")), "gain": _f(lot.get("totalGain")),
                        "gain_pct": _first(lot.get("totalGainPct"), (_f(lot.get("totalGain")) / cost * 100) if (cost and _f(lot.get("totalGain")) is not None) else None),
                        "day_gain": _f(lot.get("daysGain")), "day_gain_pct": _f(lot.get("daysGainPct")),
                        "term": "long" if term in ("LONG", "LONG_TERM", "2") or "LONG" in term else "short" if term else ""})
    return sorted(out, key=lambda r: (r["symbol"], r["acquired"]))


def _order_row(o: dict) -> dict:
    detail = (_as_list(o.get("OrderDetail")) or [{}])[0]
    inst = (_as_list(detail.get("Instrument")) or [{}])[0]
    status = str(detail.get("status") or "").upper()
    price_type = str(detail.get("priceType") or "").upper()
    return {"id": str(o.get("orderId") or ""), "symbol": str((inst.get("Product") or {}).get("symbol") or "").upper(),
            "side": str(inst.get("orderAction") or "").lower().replace("_", " "),
            "qty": _f(inst.get("orderedQuantity") or inst.get("quantity")), "filled": _f(inst.get("filledQuantity")) or 0.0,
            "type": "limit" if price_type == "LIMIT" else "market" if price_type == "MARKET" else price_type.lower(),
            "limit_price": _f(detail.get("limitPrice")), "status": status.lower().replace("_", " "),
            "open": status in ("OPEN", "PARTIAL", "INDIVIDUAL_FILLS", "PENDING", "OPEN_PENDING")}


def open_orders(c: Client, account: str) -> list[dict]:
    rows = []
    for status_name in ("OPEN", "EXECUTED"):
        try:
            data = c.json("GET", f"/v1/accounts/{urllib.parse.quote(account)}/orders", query={"status": status_name, "count": 25})
        except BrokerError:
            if status_name == "OPEN":
                raise
            continue
        rows += [_order_row(o) for o in _as_list((data.get("OrdersResponse") or {}).get("Order"))]
    return rows


def last_price(c: Client, symbol: str) -> float | None:
    data = c.json("GET", f"/v1/market/quote/{urllib.parse.quote(symbol)}")
    for q in _as_list((data.get("QuoteResponse") or {}).get("QuoteData")):
        price = _f((q.get("All") or {}).get("lastTrade"))
        if price:
            return price
    return None


# ---- trading ----

def _order_request(clean: dict, client_order_id: str, preview_id=None) -> dict:
    limit = clean["type"] == "limit"
    order = {
        "allOrNone": "false", "priceType": "LIMIT" if limit else "MARKET",
        "orderTerm": "GOOD_UNTIL_CANCEL" if clean["time_in_force"] == "gtc" and clean.get("session") != "extended" else "GOOD_FOR_DAY",
        "marketSession": "EXTENDED" if clean.get("session") == "extended" else "REGULAR", "stopPrice": "", "limitPrice": f"{clean['limit_price']:.2f}" if limit else "",
        "Instrument": [{"Product": {"securityType": "EQ", "symbol": clean["symbol"]}, "orderAction": clean["side"].upper(),
                        "quantityType": "QUANTITY", "quantity": clean["qty"]}],
    }
    body = {"orderType": "EQ", "clientOrderId": client_order_id, "Order": [order]}
    if preview_id is not None:
        body["PreviewIds"] = [{"previewId": preview_id}]
    return body


SESSIONS = ("regular", "extended")           # E*TRADE's API: regular or extended hours (no overnight session)


def preview(c: Client, account: str, order: dict, *, max_notional=None, daily_remaining=None) -> dict:
    clean = bc.clean_order(order, sessions=SESSIONS)
    cid = secrets.token_hex(8)
    data = c.json("POST", f"/v1/accounts/{urllib.parse.quote(account)}/orders/preview",
                  body={"PreviewOrderRequest": _order_request(clean, cid)})
    resp = data.get("PreviewOrderResponse") or {}
    ids = _as_list(resp.get("PreviewIds"))
    if not ids or ids[0].get("previewId") in (None, ""):
        raise BrokerError("E*TRADE did not accept that order for preview" + _messages(resp) + ".")
    detail = (_as_list(resp.get("Order")) or [{}])[0]
    price = clean["limit_price"] or last_price(c, clean["symbol"])
    estimate = _f(detail.get("estimatedTotalAmount")) or (round(price * clean["qty"], 2) if price else None)
    if estimate is None:
        raise BrokerError("Couldn't work out what that order is worth, so its size can't be checked. Use a limit order with your own price.")
    estimate = round(abs(estimate), 2)
    bc.check_size(estimate, max_notional=max_notional, daily_remaining=daily_remaining)
    token = book.issue({"broker": "etrade", "account": account, "order": clean, "estimate": estimate, "client_order_id": cid,
                        "preview_id": ids[0]["previewId"]})
    return {"order": clean, "price": price, "estimate": estimate, "commission": _f(detail.get("estimatedCommission")),
            "notes": _messages(resp, plain=True), "token": token, "expires_in": bc.PREVIEW_SECONDS, "broker": "etrade"}


def _messages(resp: dict, *, plain: bool = False):
    msgs = []
    for o in _as_list(resp.get("Order")):
        for m in _as_list((o.get("messages") or {}).get("Message")):
            if m.get("description"):
                msgs.append(str(m["description"]))
    if plain:
        return msgs
    return (": " + "; ".join(msgs)) if msgs else ""


def place(c: Client, account: str, token: str, *, daily_remaining=None) -> dict:
    entry = book.claim(token, broker="etrade", account=account)
    if daily_remaining is not None and entry["estimate"] > daily_remaining:
        raise BrokerError("That order would go over today's trading limit.")
    data = c.json("POST", f"/v1/accounts/{urllib.parse.quote(account)}/orders/place",
                  body={"PlaceOrderRequest": _order_request(entry["order"], entry["client_order_id"], entry["preview_id"])})
    resp = data.get("PlaceOrderResponse") or {}
    ids = _as_list(resp.get("OrderIds"))
    if not ids or ids[0].get("orderId") in (None, ""):
        raise BrokerError("E*TRADE did not confirm the order" + _messages(resp) + ". Check E*TRADE before trying again.")
    return {"id": str(ids[0]["orderId"]), "status": "submitted", "estimate": entry["estimate"], **entry["order"], "broker": "etrade"}


def cancel(c: Client, account: str, order_id: str) -> None:
    order_id = str(order_id or "")
    if not re.fullmatch(r"\d{1,20}", order_id):
        raise BrokerError("That order id isn't valid.")
    c.json("PUT", f"/v1/accounts/{urllib.parse.quote(account)}/orders/cancel", body={"CancelOrderRequest": {"orderId": int(order_id)}})


def option_volume(c: Client, symbol: str, *, max_expiries: int = 3, max_days: int = 45) -> dict | None:
    """Option volume for the nearest expiries (up to ``max_days`` out): {"call_volume","put_volume","ratio","call_oi","put_oi",
    "expiries"}, or None when the symbol has no listed options. Read-only."""
    from datetime import date
    data = c.json("GET", "/v1/market/optionexpiredate", query={"symbol": symbol, "expiryType": "ALL"})
    today, use = date.today(), []
    for d in _as_list((data.get("OptionExpireDateResponse") or {}).get("ExpirationDate")):
        try:
            day = date(int(d["year"]), int(d["month"]), int(d["day"]))
        except (KeyError, TypeError, ValueError):
            continue
        if day >= today and ((day - today).days <= max_days or not use):
            use.append(day)
    use = sorted(set(use))[:max_expiries]
    if not use:
        return None
    cv = pv = coi = poi = 0.0
    for day in use:
        chain = c.json("GET", "/v1/market/optionchains", query={
            "symbol": symbol, "expiryYear": day.year, "expiryMonth": day.month, "expiryDay": day.day, "chainType": "CALLPUT", "noOfStrikes": 60})
        for pair in _as_list((chain.get("OptionChainResponse") or {}).get("OptionPair")):
            call, put = pair.get("Call") or {}, pair.get("Put") or {}
            cv += _f(call.get("volume")) or 0.0
            pv += _f(put.get("volume")) or 0.0
            coi += _f(call.get("openInterest")) or 0.0
            poi += _f(put.get("openInterest")) or 0.0
    if cv + pv <= 0:
        return None
    return {"call_volume": cv, "put_volume": pv, "ratio": (pv / cv) if cv > 0 else None, "call_oi": coi, "put_oi": poi,
            "expiries": [d.isoformat() for d in use]}
