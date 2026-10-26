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

from source.collector import etrade, ibkr
from source.collector.broker_common import BrokerError
from source.common import db, secrets_store
from source.common.db.meta import get_meta, set_meta

ROUTES = (
    "/api/broker/data", "/api/broker/preview", "/api/broker/order", "/api/broker/cancel",
    "/api/broker/ibkr/gateway", "/api/broker/etrade/keys", "/api/broker/etrade/start", "/api/broker/etrade/finish",
    "/api/broker/etrade/disconnect",
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
            "pending": bool(sec.get("request_token")), "sandbox": sec.get("sandbox") == "1"}


def _etrade_client(*, need_session: bool = True) -> etrade.Client:
    sec = secrets_store.get_broker_secret("etrade")
    if not sec.get("consumer_key") or not sec.get("consumer_secret"):
        raise BrokerError("Save your E*TRADE consumer key and secret first.")
    if need_session and not sec.get("token"):
        raise BrokerError("E*TRADE is not signed in. Press Connect.")
    return etrade.Client(sec["consumer_key"], sec["consumer_secret"], sec.get("token", ""), sec.get("token_secret", ""),
                         sandbox=sec.get("sandbox") == "1", opener=OPENERS["etrade"])


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
    return {"armed": until is not None, "armed_until": until, "per_order": lt.per_order_limit(),
            "daily_remaining": lt.daily_remaining()}


def _data(payload: dict) -> dict:
    broker = _broker(payload)
    out: dict = {"broker": broker, "label": LABELS[broker], "connected": False, "message": "", "accounts": [], "account": "",
                 "summary": None, "positions": [], "orders": [], "errors": [], **_limits()}
    if broker == "ibkr":
        out["gateway_url"] = gateway_url()
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
    return out


def _handle(path: str, payload: dict) -> dict:
    lt = db.live_trading
    if path == "/api/broker/data":
        return _data(payload)
    if path == "/api/broker/ibkr/gateway":
        url = ibkr.clean_gateway_url(payload.get("url"))
        set_meta(_GATEWAY_META, url)
        return {"url": url}
    if path == "/api/broker/etrade/keys":
        key, secret = str(payload.get("consumer_key") or "").strip(), str(payload.get("consumer_secret") or "").strip()
        if not key or not secret:
            raise BrokerError("Both the consumer key and the consumer secret are needed.")
        secrets_store.set_broker_secret("etrade", {"consumer_key": key, "consumer_secret": secret,
                                                   "sandbox": "1" if payload.get("sandbox") else ""})
        return {}
    if path == "/api/broker/etrade/start":
        sec = secrets_store.get_broker_secret("etrade")
        if not sec.get("consumer_key") or not sec.get("consumer_secret"):
            raise BrokerError("Save your E*TRADE consumer key and secret first.")
        got = etrade.start_login(sec["consumer_key"], sec["consumer_secret"], sandbox=sec.get("sandbox") == "1", opener=OPENERS["etrade"])
        secrets_store.set_broker_secret("etrade", {**sec, "token": "", "token_secret": "",
                                                   "request_token": got["request_token"], "request_secret": got["request_secret"]})
        return {"authorize_url": got["authorize_url"]}
    if path == "/api/broker/etrade/finish":
        sec = secrets_store.get_broker_secret("etrade")
        if not sec.get("request_token"):
            raise BrokerError("Press Connect first to get a sign-in link.")
        got = etrade.finish_login(sec["consumer_key"], sec["consumer_secret"], sec["request_token"], sec.get("request_secret", ""),
                                  payload.get("verifier"), sandbox=sec.get("sandbox") == "1", opener=OPENERS["etrade"])
        keep = {k: v for k, v in sec.items() if k in ("consumer_key", "consumer_secret", "sandbox")}
        secrets_store.set_broker_secret("etrade", {**keep, "token": got["token"], "token_secret": got["token_secret"]})
        return {}
    if path == "/api/broker/etrade/disconnect":
        if payload.get("forget_keys"):
            secrets_store.delete_broker_secret("etrade")
        else:
            sec = secrets_store.get_broker_secret("etrade")
            secrets_store.set_broker_secret("etrade", {k: v for k, v in sec.items() if k in ("consumer_key", "consumer_secret", "sandbox")})
        return {}

    broker = _broker(payload)
    mod, client = _module(broker), _client(broker)
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
