"""The Trading tab's POST routes, kept out of dashboard.py so they can be tested
without the HTTP server. ``handle`` returns the JSON body for the route, or
raises ValueError with a message that is safe to show the person (the
dashboard turns that into a 400).

Practice (paper) trading works whenever paper keys are saved. LIVE (real-money)
trading additionally needs: live keys saved, live trading armed by typing the
confirmation phrase (it switches itself off after a few hours), the order
within the per-order and daily limits, and the symbol typed again at the
confirm step. Cancelling an order never needs arming. Every live order sent is
written to the audit log.
"""

from __future__ import annotations

from datetime import date

from source.collector import alpaca
from source.common import db, secrets_store
from source.collector import earnings
from source.webapp import broker_api
from source.webapp.pages import earnings_panel, quote_chart, watchlist

ROUTES = (
    "/api/alpaca-keys", "/api/alpaca-keys/delete", "/api/alpaca/preview", "/api/alpaca/order", "/api/alpaca/cancel",
    "/api/alpaca/live/arm", "/api/alpaca/live/disarm", "/api/alpaca/live/limits", "/api/alpaca/quote", "/api/alpaca/price",
    "/api/watchlist/data", "/api/watchlist/add", "/api/watchlist/remove", "/api/watchlist/note",
    "/api/earnings", "/api/earnings/week", "/api/ratings",
) + broker_api.ROUTES


def _mode(payload: dict) -> str:
    mode = str(payload.get("mode") or "paper")
    if mode not in alpaca.MODES:
        raise ValueError("Unknown trading mode.")
    return mode


def _require_armed(mode: str) -> None:
    if mode == "live" and not db.live_trading.is_armed():
        raise ValueError(
            "Live trading is switched off. Turn it on at the top of the Trading tab (you'll type a confirmation phrase) first."
        )


def handle(path: str, payload: dict) -> dict:
    try:
        return _handle(path, payload)
    except (alpaca.AlpacaError, secrets_store.SecretNotFoundError) as exc:
        raise ValueError(str(exc)) from exc


def _handle(path: str, payload: dict) -> dict:
    lt = db.live_trading
    if path in broker_api.ROUTES:          # the IBKR and E*TRADE tabs (same arming and limits, own module)
        return broker_api.handle(path, payload)
    if path == "/api/alpaca-keys":
        mode = _mode(payload)
        keys = (str(payload.get("key_id") or "").strip(), str(payload.get("secret") or "").strip())
        if not keys[0] or not keys[1]:
            raise secrets_store.SecretNotFoundError("Both the Alpaca key ID and the secret are needed.")
        alpaca.get_account(keys, mode=mode)  # a wrong key is refused now, not saved
        secrets_store.set_alpaca_keys(*keys, mode=mode)
        return {}
    if path == "/api/alpaca-keys/delete":
        mode = _mode(payload)
        secrets_store.delete_alpaca_keys(mode=mode)
        if mode == "live":
            lt.disarm()  # no live keys, nothing to be armed
        return {}
    if path == "/api/alpaca/live/arm":
        if str(payload.get("broker") or "") not in broker_api.BROKERS and not secrets_store.has_alpaca_keys(mode="live"):
            raise ValueError("Save your live Alpaca keys first.")
        until = lt.arm(str(payload.get("phrase") or ""))
        return {"armed_until": until}
    if path == "/api/alpaca/live/disarm":
        lt.disarm()
        return {}
    if path == "/api/alpaca/live/limits":
        lt.set_limits(payload.get("per_order"), payload.get("daily"))
        return {"per_order": lt.per_order_limit(), "daily": lt.daily_limit()}
    # Stock Analysis tab: read-only market data. Prices are the same for either account, so
    # these use whichever saved keys are there (practice first) and never need arming.
    if path == "/api/alpaca/quote":
        keys, data_mode = quote_chart.market_data_source(payload.get("mode"))
        return quote_chart.build_quote(payload.get("symbol"), keys, str(payload.get("range") or "3M"), mode=data_mode)
    if path == "/api/alpaca/price":
        # The order form's current price: read-only, uses the page's own account keys.
        return quote_chart.build_price(payload.get("symbol"), quote_chart.market_data_keys(payload.get("mode")))
    if path == "/api/watchlist/data":
        items = db.watchlist.list_items()
        if not items:
            return {"rows": []}
        # The saved list is what matters: if prices cannot be read (feed down, no keys, offline),
        # still return every saved ticker, with a message, rather than failing the whole call.
        try:
            keys, data_mode = quote_chart.market_data_source()
            return {"rows": watchlist.build_rows(items, keys, mode=data_mode)}
        except (alpaca.AlpacaError, secrets_store.SecretNotFoundError, OSError, ValueError) as exc:
            return {"rows": watchlist.stored_rows(items, "Price not available right now."), "warning": str(exc) or exc.__class__.__name__}
    if path == "/api/ratings":
        # Technical rating and the numbers behind it for stocks you hold (read-only; same data as Stock Analysis).
        syms = []
        for raw in (payload.get("symbols") or [])[:40]:
            try:
                sym = db.watchlist.clean_symbol(raw)
            except ValueError:
                continue
            if sym not in syms:
                syms.append(sym)
        if not syms:
            return {"items": []}
        keys, data_mode = quote_chart.market_data_source(payload.get("mode"))
        rows = watchlist.build_rows([{"symbol": s_, "note": ""} for s_ in syms], keys, mode=data_mode)
        return {"items": rows}
    if path == "/api/earnings":
        syms = []
        for raw in (payload.get("symbols") or [])[:earnings.MAX_SYMBOLS]:
            try:
                syms.append(db.watchlist.clean_symbol(raw))
            except ValueError:
                continue
        found = earnings.lookup(syms)
        return {"items": list(found["items"].values()), "pending": found["pending"], "error": found["error"]}
    if path == "/api/earnings/week":
        out = earnings_panel.build_week()
        out["today"] = date.today().isoformat()
        return out
    if path == "/api/watchlist/add":
        return {"added": db.watchlist.add(payload.get("symbol") if "symbol" in payload else payload.get("symbols"))}
    if path == "/api/watchlist/remove":
        db.watchlist.remove(payload.get("symbol"))
        return {}
    if path == "/api/watchlist/note":
        db.watchlist.set_note(payload.get("symbol"), payload.get("note"))
        return {}
    mode = _mode(payload)
    keys = secrets_store.get_alpaca_keys(mode=mode)
    if path == "/api/alpaca/cancel":
        alpaca.cancel_order(payload.get("id"), keys, mode=mode)
        return {}
    if path == "/api/alpaca/preview":
        _require_armed(mode)
        if mode == "live":
            return alpaca.preview_order(
                payload, keys, mode="live", max_notional=lt.per_order_limit(), daily_remaining=lt.daily_remaining(),
            )
        return alpaca.preview_order(payload, keys, mode="paper")
    if path == "/api/alpaca/order":
        _require_armed(mode)
        token = payload.get("token")
        if mode == "paper":
            return alpaca.place_order(token, keys, mode="paper")
        details = alpaca.preview_details(token)
        if details is None or details["mode"] != "live":
            raise ValueError("That order's preview has expired. Preview it again, then confirm.")
        if str(payload.get("confirm_symbol") or "").strip().upper() != details["symbol"]:
            raise ValueError(f"To send this real-money order, type its symbol ({details['symbol']}) in the box.")
        placed = alpaca.place_order(token, keys, mode="live", daily_remaining=lt.daily_remaining())
        lt.log_live_order(
            symbol=placed["symbol"], side=placed["side"], qty=placed["qty"], order_type=placed["type"],
            estimate=placed["estimate"], order_id=placed["id"], status=placed["status"],
        )
        return placed
    raise ValueError("Not found")
