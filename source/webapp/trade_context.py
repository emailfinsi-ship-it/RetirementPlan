"""Adds the safety checks (source.collector.trade_checks) to an order preview. Looks up the account's value, what is already held,
the recent sales made from this app and (when it can) the current bid / ask, then attaches ``checks`` and ``pct_of_account`` to the
preview. Anything that fails here is skipped quietly: the checks are heads-ups and must never stop a preview."""

from __future__ import annotations

from source.collector import trade_checks
from source.common import db


def _num(*values):
    for v in values:
        try:
            if v is not None and float(v) == float(v):
                return float(v)
        except (TypeError, ValueError):
            continue
    return None


def attach(result: dict, *, account_value=None, positions=None, market_price=None, bid=None, ask=None) -> dict:
    """Returns ``result`` with ``checks`` (list) and ``pct_of_account`` added."""
    try:
        order = result["order"]
        held = next((p for p in positions or [] if str(p.get("symbol") or "").upper() == order["symbol"]), None)
        held_qty = (_num(held.get("qty")) or 0.0) if held is not None else (0.0 if positions is not None else None)
        got = trade_checks.evaluate(
            order, estimate=result.get("estimate") or 0.0, price=result.get("price"), market_price=market_price, bid=bid, ask=ask,
            account_value=_num(account_value), held_qty=held_qty,
            held_avg_cost=_num(held.get("avg_cost"), held.get("avg_entry_price")) if held else None,
            recent_sells=trade_checks.recent_sells(db.live_trading.list_live_orders(60)))
        result["checks"], result["pct_of_account"] = got["checks"], got["pct_of_account"]
    except Exception:       # noqa: BLE001 -- heads-ups only
        result.setdefault("checks", [])
    return result


def for_broker(mod, client, account: str, result: dict) -> dict:
    """IBKR / E*TRADE: the account value and positions come from the broker (two light calls)."""
    value = positions = market = None
    try:
        value = _num((mod.summary(client, account) or {}).get("value"))
    except Exception:       # noqa: BLE001
        pass
    try:
        positions = mod.positions(client, account)
    except Exception:       # noqa: BLE001
        pass
    order = result.get("order") or {}
    if order.get("type") == "limit" and hasattr(mod, "last_price") and mod.__name__.endswith("etrade"):
        try:
            market = mod.last_price(client, order["symbol"])
        except Exception:   # noqa: BLE001
            pass
    elif order.get("type") != "limit":
        market = result.get("price")
    return attach(result, account_value=value, positions=positions, market_price=market)


def for_alpaca(result: dict, keys, mode: str) -> dict:
    """Alpaca: the account and positions come from the page's cached copy; bid / ask from the market-data feed."""
    from source.collector import alpaca_view
    value = positions = bid = ask = market = None
    try:
        view = alpaca_view.get(keys, mode)
        value = (view.get("account") or {}).get("equity")
        positions = view.get("positions")
    except Exception:       # noqa: BLE001
        pass
    try:
        from source.webapp.pages import quote_chart
        px = quote_chart.build_price(result["order"]["symbol"], keys)
        bid, ask, market = px.get("bid"), px.get("ask"), px.get("price")
    except Exception:       # noqa: BLE001
        pass
    return attach(result, account_value=value, positions=positions, market_price=market, bid=bid, ask=ask)
