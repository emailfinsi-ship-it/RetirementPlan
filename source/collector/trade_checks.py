"""Plain-language safety checks shown with every order preview (Alpaca, IBKR and E*TRADE): how big the order is next to the
account, whether it sells more than is held, a sale below your cost (wash-sale reminder), thin or wide markets, and a limit price
far from the current price. Pure arithmetic over numbers the caller already has -- nothing here sends or blocks an order (the
size limits in Setup do that); these are heads-ups, not advice."""

from __future__ import annotations

BIG_ORDER = 0.25            # share of the account's value at which an order is flagged as large
NOTABLE_ORDER = 0.10
BIG_POSITION = 0.15         # a buy that would make one stock more than this share of the account
WIDE_SPREAD = 0.005         # gap between buy and sell price, as a share of the price (0.5%)
FAR_LIMIT = 0.02            # a limit this far on the generous side of the market fills at once, maybe at a worse price
STALE_LIMIT = 0.10          # a limit this far on the stingy side may sit unfilled
WASH_DAYS = 30


def _usd(v: float) -> str:
    return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%" if v >= 0.1 else f"{v * 100:.1f}%"


def evaluate(order: dict, *, estimate: float, price: float | None = None, market_price: float | None = None, bid: float | None = None,
             ask: float | None = None, account_value: float | None = None, held_qty: float | None = None,
             held_avg_cost: float | None = None, recent_sells: list | None = None) -> dict:
    """``order`` is the cleaned order (symbol, side, qty, type, limit_price, session). ``price`` is what the estimate used (the limit
    price for a limit order); ``market_price`` the current market price when known; ``recent_sells`` the symbols/dates of sales made
    from this app in the last month: [{"symbol", "days_ago"}].

    Returns {"checks": [{"level": "warn"|"info", "text"}], "pct_of_account": share or None}; warnings come first."""
    side, sym, qty = order.get("side"), order.get("symbol"), float(order.get("qty") or 0)
    out: list[dict] = []
    pct = None

    def add(level: str, text: str) -> None:
        out.append({"level": level, "text": text})

    if account_value and account_value > 0 and estimate:
        pct = estimate / account_value
        if pct >= BIG_ORDER:
            add("warn", f"This order is {_pct(pct)} of the account's value ({_usd(estimate)} of {_usd(account_value)}). That is a large single trade.")
        elif pct >= NOTABLE_ORDER:
            add("info", f"This order is {_pct(pct)} of the account's value.")
        if side == "buy":
            ref = market_price or price
            held_value = (held_qty or 0.0) * ref if ref else 0.0
            after = (held_value + estimate) / account_value
            if after > BIG_POSITION:
                add("warn", f"After this buy, {sym} would be about {_pct(after)} of the account. Many people keep one stock under {_pct(BIG_POSITION)}.")

    if side == "sell" and held_qty is not None:
        if qty > held_qty + 1e-9:
            add("warn", f"You hold {held_qty:g} share{'s' if held_qty != 1 else ''} of {sym} here but this sells {qty:g}. "
                        "Selling more than you own is a short sale, which the broker may reject or treat as a margin trade.")
        elif abs(qty - held_qty) < 1e-9:
            add("info", f"This sells your whole {sym} position in this account.")
        sale_price = (order.get("limit_price") if order.get("type") == "limit" else None) or market_price or price
        if held_avg_cost and sale_price and sale_price < held_avg_cost * 0.9995:
            loss = (held_avg_cost - sale_price) * min(qty, held_qty)
            add("info", f"At about {_usd(sale_price)} this sells below your average cost of {_usd(held_avg_cost)} (a loss of roughly {_usd(loss)}). "
                        f"In a taxable account, buying {sym} (or something nearly identical) within {WASH_DAYS} days before or after can disallow that loss "
                        "(a wash sale). Which shares are sold depends on the account's lot method.")

    if side == "buy":
        for s in recent_sells or []:
            if s.get("symbol") == sym and (s.get("days_ago") or 0) <= WASH_DAYS:
                days = s["days_ago"]
                add("info", f"You sold {sym} from this app {days} day{'s' if days != 1 else ''} ago. If that sale was at a loss and this is a taxable account, "
                            f"buying it back within {WASH_DAYS} days can disallow the loss (a wash sale).")
                break

    if order.get("session") and order["session"] != "regular":
        add("info", "Extended hours: fewer people trade, so prices can jump and the gap between buy and sell prices is wide. Your limit price protects you.")

    if bid and ask and bid > 0 and ask >= bid:
        mid = (bid + ask) / 2
        spread = (ask - bid) / mid
        if spread >= WIDE_SPREAD:
            tip = "A limit price protects you." if order.get("type") == "limit" else "Consider a limit order so you do not pay the wide gap."
            add("warn", f"The gap between the buy price ({_usd(bid)}) and sell price ({_usd(ask)}) is {_pct(spread)}, which is wide. {tip}")

    if order.get("type") == "limit" and order.get("limit_price") and market_price and market_price > 0:
        off = order["limit_price"] / market_price - 1
        generous = off if side == "buy" else -off           # positive = more generous than the market
        if generous >= FAR_LIMIT:
            way = "above" if side == "buy" else "below"
            add("warn", f"Your limit ({_usd(order['limit_price'])}) is {_pct(abs(off))} {way} the current price ({_usd(market_price)}), so it will fill right away "
                        f"and can fill at up to your limit if the price moves.")
        elif generous <= -STALE_LIMIT:
            way = "below" if side == "buy" else "above"
            add("info", f"Your limit ({_usd(order['limit_price'])}) is {_pct(abs(off))} {way} the current price ({_usd(market_price)}), so it may not fill for a while.")

    out.sort(key=lambda c: 0 if c["level"] == "warn" else 1)
    return {"checks": out, "pct_of_account": pct}


def recent_sells(orders: list[dict], *, today=None, days: int = WASH_DAYS) -> list[dict]:
    """From the app's own order log (db.live_trading.list_live_orders): sales in the last ``days`` days, as [{"symbol","days_ago"}]."""
    from datetime import date, datetime
    today = today or date.today()
    out = []
    for o in orders or []:
        if str(o.get("side") or "").lower() != "sell" or str(o.get("status") or "").lower() in ("canceled", "cancelled", "rejected", "expired"):
            continue
        stamp = str(o.get("placed_at") or "")[:10]
        try:
            ago = (today - datetime.strptime(stamp, "%Y-%m-%d").date()).days
        except ValueError:
            continue
        if 0 <= ago <= days:
            out.append({"symbol": str(o.get("symbol") or "").upper(), "days_ago": ago})
    return out
