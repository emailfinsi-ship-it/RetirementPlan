"""POST routes for the IBKR and E*TRADE tabs (real money). Kept apart from trading_api (Alpaca) but with the same rules:

* Reading (balances, positions, orders) works whenever the broker is connected.
* **Previewing, sending and cancelling** need live trading to be switched on (the same switch, phrase, per-order limit
  and daily limit as the Alpaca Live Account page; the daily limit counts every broker together).
* Sending also needs the order's symbol typed again, and uses a single-use preview token.
* Every order sent is written to the audit log (``live_order_log``, with the broker's name).
* The account id sent by the page must be one of the accounts the broker itself lists for this login.

``handle`` returns a JSON body or raises ValueError with a message that is safe to show.
"""

from __future__ import annotations

from source.collector import etrade, ibkr, ibkr_gateway
from source.collector.broker_common import BrokerError
from source.common import db, secrets_store
from source.common.db.meta import get_meta, set_meta

ROUTES = (
    "/api/broker/data", "/api/broker/preview", "/api/broker/order", "/api/broker/cancel",
    "/api/broker/ibkr/gateway", "/api/broker/ibkr/start", "/api/broker/ibkr/stop", "/api/broker/ibkr/autostart", "/api/broker/etrade/keys", "/api/broker/etrade/start", "/api/broker/etrade/finish",
    "/api/broker/etrade/disconnect", "/api/broker/diagnose", "/api/broker/lots",
)

BROKERS = ("ibkr", "etrade")
LABELS = {"ibkr": "Interactive Brokers", "etrade": "E*TRADE"}
_GATEWAY_META = "ibkr_gateway_url"

# tests replace these to reach a fake broker instead of the real one
OPENERS: dict = {"ibkr": None, "etrade": None}


def handle(path: str, payload: dict) -> dict:
    try:
        return _handle(path, payload)
    except (BrokerError, secrets_store.SecretNotFoundError) as exc:
        raise ValueError(str(exc)) from exc


def _broker(payload: dict) -> str:
    b = str(payload.get("broker") or "").strip().lower()
    if b not in BROKERS:
        raise ValueError("Unknown broker.")
    return b


def _require_armed() -> None:
    if not db.live_trading.is_armed():
        raise ValueError(
            "Live trading is switched off. Turn it on at the top of the Alpaca tab (you'll type a confirmation phrase) first."
        )


def gateway_url() -> str:
    return ibkr.clean_gateway_url(get_meta(_GATEWAY_META, ibkr.DEFAULT_URL))


def _gateway() -> ibkr.Gateway:
    return ibkr.Gateway(gateway_url(), opener=OPENERS["ibkr"])


def etrade_state() -> dict:
    sec = secrets_store.get_broker_secret("etrade")
    return {"has_keys": bool(sec.get("consumer_key") and sec.get("consumer_secret")), "has_session": bool(sec.get("token")),
            "pending": bool(sec.get("request_token")),
            "key_hint": ("\u2026" + sec["consumer_key"][-4:]) if sec.get("consumer_key") else "",
            "has_secret": bool(sec.get("consumer_secret"))}


def _etrade_client(*, need_session: bool = True) -> etrade.Client:
    sec = secrets_store.get_broker_secret("etrade")
    if not sec.get("consumer_key") or not sec.get("consumer_secret"):
        raise BrokerError("Save your E*TRADE consumer key and secret first.")
    if need_session and not sec.get("token"):
        raise BrokerError("E*TRADE is not signed in. Press Connect.")
    return etrade.Client(sec["consumer_key"], sec["consumer_secret"], sec.get("token", ""), sec.get("token_secret", ""),
                         opener=OPENERS["etrade"])


def _client(broker: str):
    return _gateway() if broker == "ibkr" else _etrade_client()


def _module(broker: str):
    return ibkr if broker == "ibkr" else etrade


def _account(broker: str, client, payload: dict) -> str:
    """The account id the page asked for, only if the broker lists it for this login."""
    wanted = str(payload.get("account") or "").strip()
    ids = [a["id"] for a in _module(broker).list_accounts(client)]
    if wanted not in ids:
        raise BrokerError("That account isn't one of the accounts this login can trade. Reload the page and pick one.")
    return wanted


def _limits() -> dict:
    lt = db.live_trading
    until = lt.armed_until()
    return {"armed": until is not None, "armed_until": until, "persistent": lt.is_persistent(), "per_order": lt.per_order_limit(),
            "daily_remaining": lt.daily_remaining()}


def _data(payload: dict) -> dict:
    broker = _broker(payload)
    out: dict = {"broker": broker, "label": LABELS[broker], "connected": False, "message": "", "accounts": [], "account": "",
                 "summary": None, "positions": [], "orders": [], "errors": [], **_limits()}
    if broker == "ibkr":
        out["gateway_url"] = gateway_url()
        out["gateway_files"] = ibkr_gateway.bundled_dir() is not None or (ibkr_gateway.run_dir() / "bin").is_dir()
        out["gateway_started_here"] = ibkr_gateway.running()
        out["gateway_autostart"] = ibkr_gateway.autostart_enabled()
        gw = _gateway()
        st = ibkr.status(gw)
        if st.get("down"):
            # The saved address does not answer. People often run the gateway on another port (macOS uses 5000
            # for AirPlay), so look for it on this computer's usual ports and remember the one that answers.
            found = ibkr.find_gateway(out["gateway_url"], opener=OPENERS["ibkr"])
            if found:
                set_meta(_GATEWAY_META, found)
                out["gateway_url"] = found
                gw = ibkr.Gateway(found, opener=OPENERS["ibkr"])
                st = ibkr.status(gw)
                out["found_note"] = f"Found the IBKR gateway at {found} and saved that address."
        out["connected"], out["message"] = st["connected"], st["message"]
        client = gw
    else:
        state = etrade_state()
        out.update(etrade=state)
        if not state["has_keys"] or not state["has_session"]:
            out["message"] = ("Save your E*TRADE keys, then press Connect." if not state["has_keys"]
                              else "Press Connect to sign in to E*TRADE.")
            return out
        client = _etrade_client()
        out["connected"] = True
    if not out["connected"]:
        return out
    mod = _module(broker)
    try:
        out["accounts"] = mod.list_accounts(client)
    except BrokerError as exc:
        out["connected"], out["message"] = False, str(exc)
        return out
    ids = [a["id"] for a in out["accounts"]]
    out["account"] = str(payload.get("account") or "") if str(payload.get("account") or "") in ids else (ids[0] if ids else "")
    if not out["account"]:
        out["message"] = "No tradable brokerage account was found for this login."
        return out
    for key, fn in (("summary", mod.summary), ("positions", mod.positions), ("orders", mod.open_orders)):
        try:
            out[key] = fn(client, out["account"])
        except BrokerError as exc:
            out["errors"].append(str(exc))
    if broker == "ibkr":
        _add_currencies(out, client)
    if len(out["accounts"]) > 1:
        out["overview"] = _overview(mod, client, out["accounts"])
    return out


def _add_currencies(out: dict, client) -> None:
    """IBKR accounts can hold several currencies: add the per-currency balances, and the base-currency value of each
    position (so a euro holding and a dollar holding can be compared and summed)."""
    try:
        rows = ibkr.ledger(client, out["account"])
    except BrokerError as exc:
        out["errors"].append(f"Currency balances: {exc}")
        return
    out["currencies"] = rows
    rate = {r["currency"]: r["rate"] for r in rows if r.get("rate")}
    for p in out["positions"]:
        r = rate.get(p.get("currency") or "")
        if r and p.get("market_value") is not None:
            p["base_value"] = p["market_value"] * r


def _overview(mod, client, accounts: list[dict]) -> dict:
    """Every account's balances and holdings, plus the totals and the holdings added up across accounts."""
    rows, held = [], {}
    total = {"value": 0.0, "cash": 0.0, "buying_power": 0.0}
    for acct in accounts:
        row = {"id": acct["id"], "name": acct["name"], "summary": None, "positions": [], "error": ""}
        for key, fn in (("summary", mod.summary), ("positions", mod.positions)):
            try:
                row[key] = fn(client, acct["id"])
            except BrokerError as exc:
                row["error"] = str(exc)
        for k in total:
            total[k] += float((row["summary"] or {}).get(k) or 0.0)
        for p in row["positions"]:
            h = held.setdefault(p["symbol"], {"symbol": p["symbol"], "name": p.get("name", ""), "qty": 0.0, "market_value": 0.0,
                                              "gain": 0.0, "has_gain": False, "accounts": 0})
            h["qty"] += float(p.get("qty") or 0.0)
            h["market_value"] += float(p.get("market_value") or 0.0)
            if p.get("gain") is not None:
                h["gain"] += float(p["gain"])
                h["has_gain"] = True
            h["accounts"] += 1
        row["positions"] = [{"symbol": p["symbol"], "qty": p["qty"], "market_value": p.get("market_value")} for p in row["positions"]]
        rows.append(row)
    holdings = sorted(({**h, "gain": h["gain"] if h["has_gain"] else None} for h in held.values()), key=lambda r: -r["market_value"])
    for h in holdings:
        h.pop("has_gain", None)
    return {"accounts": rows, "total": total, "holdings": holdings}


def _all_lots(mod, client) -> dict:
    """Every tax lot in every account this login can see, with totals per account and overall. An account that
    fails is reported by name instead of hiding the others."""
    rows, per_account, problems = [], [], []
    keys = ("cost_basis", "market_value", "gain")
    for acct in mod.list_accounts(client):
        try:
            got = mod.lots(client, acct["id"])
        except BrokerError as exc:
            problems.append(f"{acct['name']}: {exc}")
            continue
        for r in got:
            rows.append({**r, "account": acct["name"]})
        per_account.append({"account": acct["name"], "lots": len(got), **{k: sum(r[k] or 0.0 for r in got) for k in keys}})
    by = {}
    for r in rows:
        t = by.setdefault(r["symbol"], {"symbol": r["symbol"], "qty": 0.0, "cost_basis": 0.0, "market_value": 0.0, "gain": 0.0, "lots": 0})
        t["qty"] += r["qty"] or 0.0
        t["cost_basis"] += r["cost_basis"] or 0.0
        t["market_value"] += r["market_value"] or 0.0
        t["gain"] += r["gain"] or 0.0
        t["lots"] += 1
    return {"lots": rows, "by_account": per_account, "by_symbol": sorted(by.values(), key=lambda t: -t["market_value"]),
            "total": {k: sum(r[k] or 0.0 for r in rows) for k in keys}, "problems": problems}


def _shape(obj, depth: int = 4):
    """The structure of a reply with every value left out (names, types and list lengths only), so it can be shown and
    shared without exposing balances, account numbers or tokens."""
    if depth <= 0:
        return "..."
    if isinstance(obj, dict):
        # a name containing a digit is data (for example an account id used as a key), not structure, so it is hidden
        return {("<id>" if any(ch.isdigit() for ch in str(k)) else str(k)): _shape(v, depth - 1) for k, v in list(obj.items())[:25]}
    if isinstance(obj, list):
        return [f"{len(obj)} item(s)"] + ([_shape(obj[0], depth - 1)] if obj else [])
    return type(obj).__name__ if obj is not None else "null"


def _diagnose(payload: dict) -> dict:
    """Runs each read call the tab makes, one by one, and reports what happened to each (never values)."""
    broker = _broker(payload)
    steps: list[dict] = []

    def run(name, fn):
        try:
            steps.append({"step": name, "ok": True, "shape": _shape(fn())})
        except BrokerError as exc:
            steps.append({"step": name, "ok": False, "error": str(exc)})
        except Exception as exc:        # a diagnostic must never fail with a stack trace
            steps.append({"step": name, "ok": False, "error": f"{exc.__class__.__name__}: {exc}"})

    if broker == "ibkr":
        gw = _gateway()
        run("Gateway sign-in status", lambda: gw.call("GET", "/iserver/auth/status"))
        run("Accounts", lambda: gw.call("GET", "/iserver/accounts"))
        run("Portfolio accounts", lambda: gw.call("GET", "/portfolio/accounts"))
    else:
        state = etrade_state()
        steps.append({"step": "Saved keys / session", "ok": state["has_keys"] and state["has_session"],
                      "shape": {"keys_saved": state["has_keys"], "signed_in": state["has_session"]}})
        if state["has_keys"] and state["has_session"]:
            c = _etrade_client()
            run("Account list", lambda: c.json("GET", "/v1/accounts/list"))
            accounts = []
            try:
                accounts = etrade.list_accounts(c)
            except BrokerError:
                pass
            steps.append({"step": "Accounts the app would show", "ok": bool(accounts), "shape": f"{len(accounts)} account(s)"})
            if accounts:
                key = accounts[0]["id"]
                run("Balance", lambda: c.json("GET", f"/v1/accounts/{key}/balance", query={"instType": "BROKERAGE", "realTimeNAV": "true"}))
                run("Portfolio", lambda: c.json("GET", f"/v1/accounts/{key}/portfolio", query={"count": 250}))
                run("Open orders", lambda: c.json("GET", f"/v1/accounts/{key}/orders", query={"status": "OPEN", "count": 25}))
    return {"broker": broker, "steps": steps}


def _handle(path: str, payload: dict) -> dict:
    lt = db.live_trading
    if path == "/api/broker/diagnose":
        return _diagnose(payload)
    if path == "/api/broker/data":
        return _data(payload)
    if path == "/api/broker/ibkr/gateway":
        url = ibkr.clean_gateway_url(payload.get("url"))
        set_meta(_GATEWAY_META, url)
        return {"url": url}
    if path == "/api/broker/ibkr/start":
        out = ibkr_gateway.start()
        port = ibkr_gateway.listen_port()
        if port:                                   # sign in at the port the gateway really uses
            set_meta(_GATEWAY_META, f"https://localhost:{port}")
        return {**out, "url": gateway_url()}
    if path == "/api/broker/ibkr/autostart":
        ibkr_gateway.set_autostart(bool(payload.get("on")))
        return {"on": ibkr_gateway.autostart_enabled()}
    if path == "/api/broker/ibkr/stop":
        return {"stopped": ibkr_gateway.stop()}
    if path == "/api/broker/etrade/keys":
        key, secret = str(payload.get("consumer_key") or "").strip(), str(payload.get("consumer_secret") or "").strip()
        if not key or not secret:
            raise BrokerError("Both the consumer key and the consumer secret are needed.")
        secrets_store.set_broker_secret("etrade", {"consumer_key": key, "consumer_secret": secret})
        return {}
    if path == "/api/broker/etrade/start":
        sec = secrets_store.get_broker_secret("etrade")
        if not sec.get("consumer_key") or not sec.get("consumer_secret"):
            raise BrokerError("Save your E*TRADE consumer key and secret first.")
        got = etrade.start_login(sec["consumer_key"], sec["consumer_secret"], opener=OPENERS["etrade"])
        secrets_store.set_broker_secret("etrade", {**sec,   # the current session is kept until the new one is confirmed
                                                   "request_token": got["request_token"], "request_secret": got["request_secret"]})
        return {"authorize_url": got["authorize_url"]}
    if path == "/api/broker/etrade/finish":
        sec = secrets_store.get_broker_secret("etrade")
        if not sec.get("request_token"):
            raise BrokerError("Press Connect first to get a sign-in link.")
        got = etrade.finish_login(sec["consumer_key"], sec["consumer_secret"], sec["request_token"], sec.get("request_secret", ""),
                                  payload.get("verifier"), opener=OPENERS["etrade"])
        keep = {k: v for k, v in sec.items() if k in ("consumer_key", "consumer_secret")}
        secrets_store.set_broker_secret("etrade", {**keep, "token": got["token"], "token_secret": got["token_secret"]})
        return {}
    if path == "/api/broker/etrade/disconnect":
        if payload.get("forget_keys"):
            secrets_store.delete_broker_secret("etrade")
        else:
            sec = secrets_store.get_broker_secret("etrade")
            secrets_store.set_broker_secret("etrade", {k: v for k, v in sec.items() if k in ("consumer_key", "consumer_secret")})
        return {}

    broker = _broker(payload)
    mod, client = _module(broker), _client(broker)
    if path == "/api/broker/lots":
        if not hasattr(mod, "lots"):
            raise BrokerError("IBKR's gateway reports one average cost per position, not individual lots (IBKR gives lots only in its "
                              "Flex reports). The Positions table shows that average cost.")
        return _all_lots(mod, client)
    account = _account(broker, client, payload)
    if path == "/api/broker/cancel":
        _require_armed()
        mod.cancel(client, account, payload.get("order_id"))
        return {}
    if path == "/api/broker/preview":
        _require_armed()
        return mod.preview(client, account, payload.get("order") or {}, max_notional=lt.per_order_limit(),
                           daily_remaining=lt.daily_remaining())
    if path == "/api/broker/order":
        _require_armed()
        token = payload.get("token")
        details = mod.book.peek(token)
        if details is None or details.get("broker") != broker:
            raise ValueError("That order's preview has expired. Preview it again, then confirm.")
        symbol = details["order"]["symbol"]
        if str(payload.get("confirm_symbol") or "").strip().upper() != symbol:
            raise ValueError(f"To send this real-money order, type its symbol ({symbol}) in the box.")
        placed = mod.place(client, account, token, daily_remaining=lt.daily_remaining())
        if placed.get("id"):
            lt.log_live_order(symbol=placed["symbol"], side=placed["side"], qty=placed["qty"], order_type=placed["type"],
                              estimate=placed["estimate"], order_id=placed["id"], status=placed["status"], broker=broker)
        return placed
    raise ValueError("Not found")
