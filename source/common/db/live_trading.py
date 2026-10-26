"""Settings and audit log for LIVE (real-money) Alpaca trading.

Live trading is off until the owner types the confirmation phrase, switches
itself off again after ``ARM_HOURS`` (unless the owner chose "keep on until I
turn it off"), and is bounded by a per-order limit and
a daily limit the owner sets in Setup (one setting for every broker; either can be "no limit"). Every live
order that was sent is written to ``live_order_log``; the daily limit counts
what that log says was already sent today. Practice (paper) trading uses none
of this.
"""

from __future__ import annotations

import time
from datetime import date, datetime

from source.common.db.connection import connect
from source.common.db.meta import get_meta, set_meta

CONFIRM_PHRASE = "TRADE REAL MONEY"
ARM_HOURS = 8
STAY_ON_DAYS = 3650  # "keep on until I turn it off": a far-future switch-off time
_PERSISTENT_AFTER = 30 * 86400
DEFAULT_PER_ORDER = 2_000.0
DEFAULT_DAILY = 5_000.0
NO_LIMIT = float("inf")      # stored as the word "none"; sent to pages as null

_ARMED_UNTIL = "live_trading_armed_until"
_PER_ORDER = "live_trading_per_order_limit"
_DAILY = "live_trading_daily_limit"


def arm(phrase: str, *, now: float | None = None, stay_on: bool = False) -> float:
    """Turns live trading on for ARM_HOURS, or until switched off when ``stay_on``.

    The phrase must be typed exactly. The limits, the typed-symbol check and
    the audit log apply the same either way."""
    if (phrase or "").strip() != CONFIRM_PHRASE:
        raise ValueError(f"To turn on live trading, type {CONFIRM_PHRASE} exactly.")
    hours = STAY_ON_DAYS * 24 if stay_on else ARM_HOURS
    until = (time.time() if now is None else now) + hours * 3600
    set_meta(_ARMED_UNTIL, f"{until:.0f}")
    return until


def disarm() -> None:
    set_meta(_ARMED_UNTIL, "0")


def armed_until(*, now: float | None = None) -> float | None:
    """The epoch time live trading switches itself off, or None when it is off."""
    try:
        until = float(get_meta(_ARMED_UNTIL, "0") or 0)
    except (TypeError, ValueError):
        return None
    return until if until > (time.time() if now is None else now) else None


def is_persistent(*, now: float | None = None) -> bool:
    """True when live trading was left on until the owner turns it off."""
    until = armed_until(now=now)
    return until is not None and until - (time.time() if now is None else now) > _PERSISTENT_AFTER


def is_armed(*, now: float | None = None) -> bool:
    return armed_until(now=now) is not None


def _limit(key: str, default: float) -> float:
    raw = get_meta(key, default)
    if str(raw).strip().lower() in ("none", "off", "unlimited", "inf"):
        return NO_LIMIT
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 1.0 else default


def per_order_limit() -> float:
    """The most one real-money order may be worth, in dollars (``NO_LIMIT`` when the owner chose none)."""
    return _limit(_PER_ORDER, DEFAULT_PER_ORDER)


def daily_limit() -> float:
    """The most that may be sent in one day across every broker (``NO_LIMIT`` when the owner chose none)."""
    return _limit(_DAILY, DEFAULT_DAILY)


def is_limited(value: float) -> bool:
    return value != NO_LIMIT


def as_json(value: float):
    """A limit as a page can read it: the dollar amount, or None for no limit."""
    return value if is_limited(value) else None


def _parse_limit(value, what: str) -> float:
    if value is None or str(value).strip().lower() in ("", "none", "off", "unlimited", "inf"):
        return NO_LIMIT
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Enter the {what} limit as a dollar amount, or choose no limit.") from None
    if number < 1:
        raise ValueError(f"The {what} limit must be at least $1, or choose no limit.")
    return number


def set_limits(per_order, daily) -> None:
    """Saves the limits. ``None`` (or "none") for either means no limit."""
    per_order, daily = _parse_limit(per_order, "per-order"), _parse_limit(daily, "daily")
    if is_limited(per_order) and is_limited(daily) and per_order > daily:
        raise ValueError("The per-order limit can't be larger than the daily limit.")
    set_meta(_PER_ORDER, f"{per_order:.2f}" if is_limited(per_order) else "none")
    set_meta(_DAILY, f"{daily:.2f}" if is_limited(daily) else "none")


def log_live_order(*, symbol: str, side: str, qty: int, order_type: str, estimate: float, order_id: str, status: str,
                   placed_at: datetime | None = None, broker: str = "alpaca") -> None:
    when = placed_at or datetime.now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO live_order_log (placed_at, day, symbol, side, qty, order_type, estimate, order_id, status, broker) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (when.isoformat(timespec="seconds"), when.date().isoformat(), symbol, side, int(qty), order_type,
             float(estimate), order_id, status, broker),
        )


def spent_today(*, today: date | None = None) -> float:
    day = (today or date.today()).isoformat()
    with connect() as conn:
        row = conn.execute("SELECT COALESCE(SUM(estimate), 0) AS total FROM live_order_log WHERE day = ?", (day,)).fetchone()
        return float(row["total"])


def daily_remaining(*, today: date | None = None) -> float:
    limit = daily_limit()
    return limit if not is_limited(limit) else max(0.0, limit - spent_today(today=today))


def list_live_orders(limit: int = 20, broker: str | None = None) -> list[dict]:
    with connect() as conn:
        if broker:
            rows = conn.execute("SELECT * FROM live_order_log WHERE broker = ? ORDER BY id DESC LIMIT ?", (broker, int(limit))).fetchall()
        else:
            rows = conn.execute("SELECT * FROM live_order_log ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(r) for r in rows]


def sync_statuses(orders: list[dict]) -> int:
    """Brings the saved status of each real-money order up to date from Alpaca's own list
    (``orders`` as returned by alpaca.list_orders). The status saved when an order is sent is
    only what Alpaca said at that instant ("pending_new"); a fill happens later. Returns how many changed."""
    changed = 0
    with connect() as conn:
        for o in orders or []:
            oid, status = str(o.get("id") or ""), str(o.get("status") or "")
            if not oid or not status:
                continue
            cur = conn.execute("UPDATE live_order_log SET status = ? WHERE order_id = ? AND status != ? AND broker = 'alpaca'", (status, oid, status))
            changed += cur.rowcount
    return changed
