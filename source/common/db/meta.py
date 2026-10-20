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


_META_VIEW_MODE = "view_mode"


def view_mode() -> str:
    """"simple" (default: the everyday pages and plain wording only) or
    "full" (every tool and setting). A display preference only -- it never
    changes a calculated number."""
    return "full" if get_meta(_META_VIEW_MODE) == "full" else "simple"


def set_view_mode(mode: str) -> None:
    if mode not in ("simple", "full"):
        raise ValueError("View must be 'simple' or 'full'.")
    set_meta(_META_VIEW_MODE, mode)


_META_TOUR_SEEN = "tour_seen"


def tour_seen() -> bool:
    """Whether the short first-use tour has been shown (finished or skipped)."""
    return get_meta(_META_TOUR_SEEN) == "1"


def set_tour_seen(seen: bool = True) -> None:
    set_meta(_META_TOUR_SEEN, "1" if seen else "0")


_META_SAFE_SPEND_TARGET = "safe_spend_target"


def safe_spend_target() -> float:
    """The chance of lasting ("confidence") behind "How much can I safely
    spend?" -- 0.9 unless the person picked another level. Shared by the
    Summary and the Will my money last? tab."""
    try:
        value = float(get_meta(_META_SAFE_SPEND_TARGET) or 0.9)
    except (TypeError, ValueError):
        return 0.9
    return value if 0.5 <= value <= 0.99 else 0.9


def set_safe_spend_target(target: float) -> None:
    target = float(target)
    if not 0.5 <= target <= 0.99:
        raise ValueError("Target must be between 50% and 99%.")
    set_meta(_META_SAFE_SPEND_TARGET, f"{target:g}")


_META_LEGACY_WHATIF = "legacy_whatif"


def legacy_whatif() -> dict | None:
    """The saved "Try your own" Roth-conversion what-if (see
    reporting.monte_carlo.legacy_planning.normalize_custom_strategy), or
    None when there isn't one."""
    import json

    raw = get_meta(_META_LEGACY_WHATIF)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def set_legacy_whatif(spec: dict | None) -> None:
    import json

    set_meta(_META_LEGACY_WHATIF, json.dumps(spec) if spec else "")
