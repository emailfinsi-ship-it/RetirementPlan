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

from source.collector import alpaca
from source.common import db, secrets_store
from source.webapp.pages import quote_chart

ROUTES = (
    "/api/alpaca-keys", "/api/alpaca-keys/delete", "/api/alpaca/preview", "/api/alpaca/order", "/api/alpaca/cancel",
    "/api/alpaca/live/arm", "/api/alpaca/live/disarm", "/api/alpaca/live/limits", "/api/alpaca/quote",
)


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
        if not secrets_store.has_alpaca_keys(mode="live"):
            raise ValueError("Save your live Alpaca keys first.")
        until = lt.arm(str(payload.get("phrase") or ""))
        return {"armed_until": until}
    if path == "/api/alpaca/live/disarm":
        lt.disarm()
        return {}
    if path == "/api/alpaca/live/limits":
        lt.set_limits(payload.get("per_order"), payload.get("daily"))
        return {"per_order": lt.per_order_limit(), "daily": lt.daily_limit()}
    mode = _mode(payload)
    keys = secrets_store.get_alpaca_keys(mode=mode)
    if path == "/api/alpaca/quote":
        # Read-only market data: needs saved keys for the page's account, never arming.
        return quote_chart.build_quote(payload.get("symbol"), keys, str(payload.get("range") or "3M"))
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
