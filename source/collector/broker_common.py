"""Rules shared by the real-money brokers other than Alpaca (Interactive Brokers, E*TRADE).

The same safety model as source.collector.alpaca, kept in one place so neither broker can skip it:

* **Preview, then confirm.** An order is sent only with a single-use token that ``PreviewBook.issue`` handed out
  for exactly those details a few minutes earlier, for the same broker and account.
* **Size limits.** One order may not be worth more than ``alpaca.MAX_ORDER_NOTIONAL`` nor than the lower per-order
  or daily-remaining limit the caller passes (these come from source.common.db.live_trading and are shared with
  Alpaca live trading, so the daily limit counts every broker together).
* Every call that touches the network takes an injectable ``opener`` so tests never reach a real broker.
"""

from __future__ import annotations

import secrets
import time

from source.collector import alpaca

PREVIEW_SECONDS = alpaca.PREVIEW_SECONDS


class BrokerError(Exception):
    """A readable failure (not connected, rejected order, no connection, ...)."""


def clean_order(order: dict) -> dict:
    """Validates and normalises the order a person typed (whole shares, market or limit, day or good-till-cancelled)."""
    try:
        return alpaca.clean_order(order)
    except alpaca.AlpacaError as exc:
        raise BrokerError(str(exc)) from exc


def money_text(value: float) -> str:
    return f"${value:,.0f}"


def check_size(estimate: float, *, max_notional: float | None, daily_remaining: float | None) -> None:
    limit = alpaca.MAX_ORDER_NOTIONAL if max_notional is None else min(alpaca.MAX_ORDER_NOTIONAL, max_notional)
    if estimate > limit:
        raise BrokerError(f"That order is worth about {money_text(estimate)}. One order here is limited to {money_text(limit)}.")
    if daily_remaining is not None and estimate > daily_remaining:
        raise BrokerError(
            f"That order is worth about {money_text(estimate)}, which is more than the {money_text(max(daily_remaining, 0))} "
            "left of today's trading limit."
        )


class PreviewBook:
    """Single-use, short-lived preview tokens (kept in memory only, so a restart voids them)."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, dict]] = {}

    def issue(self, entry: dict, *, now: float | None = None) -> str:
        stamp = time.time() if now is None else now
        for token in [t for t, (expires, _e) in self._items.items() if expires < stamp]:
            self._items.pop(token, None)
        token = secrets.token_urlsafe(24)
        self._items[token] = (stamp + PREVIEW_SECONDS, dict(entry))
        return token

    def claim(self, token: str, *, broker: str, account: str, now: float | None = None) -> dict:
        """Uses the token up and returns what it was issued for, or raises BrokerError."""
        stamp = time.time() if now is None else now
        found = self._items.pop(str(token or ""), None)
        if found is None or found[0] < stamp:
            raise BrokerError("That order's preview has expired. Preview it again, then confirm.")
        entry = found[1]
        if entry.get("broker") != broker or entry.get("account") != account:
            raise BrokerError("That preview was made for a different account. Preview it again, then confirm.")
        return entry

    def peek(self, token: str, *, now: float | None = None) -> dict | None:
        stamp = time.time() if now is None else now
        found = self._items.get(str(token or ""))
        return dict(found[1]) if found and found[0] >= stamp else None
