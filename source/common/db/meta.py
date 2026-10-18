"""One-time-import and last-export bookkeeping -- a small key/value
table separate from `assumptions` (which is Monte Carlo inputs, not
bookkeeping).
"""

from __future__ import annotations

from source.common.db.connection import connect


def get_meta(key: str, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default



def set_meta(key: str, value) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


_META_SETUP_COMPLETE = "setup_complete"


def setup_complete() -> bool:
    """True once the first-run wizard was finished (or dismissed)."""
    return get_meta(_META_SETUP_COMPLETE) == "1"


def set_setup_complete(done: bool = True) -> None:
    set_meta(_META_SETUP_COMPLETE, "1" if done else "0")


def setup_needed() -> bool:
    """A brand-new install: wizard never finished AND nothing entered yet.
    An existing install that already has accounts or line items is never
    sent to the wizard, even if it predates the flag."""
    if setup_complete():
        return False
    from source.common.db.line_items import list_line_items
    from source.common.db.plaid import list_plaid_items

    if list_plaid_items():
        return False
    return not any(list_line_items(section) for section in ("assets", "real_estate", "expenses", "income"))


_META_DOLLARS_MODE = "dollars_mode"


def dollars_mode() -> str:
    """"today" (default: future amounts shown in today's purchasing power)
    or "future" (nominal, inflated dollars)."""
    return "future" if get_meta(_META_DOLLARS_MODE) == "future" else "today"


def set_dollars_mode(mode: str) -> None:
    if mode not in ("today", "future"):
        raise ValueError("Dollars mode must be 'today' or 'future'.")
    set_meta(_META_DOLLARS_MODE, mode)
