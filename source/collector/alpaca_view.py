"""What the Alpaca trading pages show (account, positions, recent orders), kept for a short while so coming back to the tab
is instant instead of waiting for three Alpaca calls.

* Under 20 seconds old: served as is.
* Older but under 15 minutes: served at once, and a background refresh starts so the next look (or the page's own one-time
  reload) is current.
* Older than that, or nothing kept: fetched now (the three calls run side by side, not one after another).
* If Alpaca cannot be reached, the last copy is shown with its time instead of an empty page.

``invalidate`` drops the copy; it is called after an order is sent or cancelled and when the keys change, so those screens
are never behind. Reading changes nothing at Alpaca. Off under the test runner unless ``ENABLED`` is switched on.
"""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from source.collector import alpaca

FRESH_SECONDS = 20.0
MAX_AGE_SECONDS = 15 * 60.0
ENABLED: bool | None = None            # None = on, except under the test runner

_lock = threading.Lock()
_cache: dict[str, dict] = {}
_refreshing: set[str] = set()


def enabled() -> bool:
    return ENABLED if ENABLED is not None else "unittest" not in sys.modules


def invalidate(mode: str | None = None) -> None:
    with _lock:
        if mode is None:
            _cache.clear()
        else:
            _cache.pop(mode, None)


def _fetch(keys, mode: str, **kw) -> dict:
    with ThreadPoolExecutor(max_workers=3) as pool:
        acct = pool.submit(alpaca.get_account, keys, mode=mode, **kw)
        positions = pool.submit(alpaca.list_positions, keys, mode=mode, **kw)
        orders = pool.submit(alpaca.list_orders, keys, mode=mode, **kw)
        return {"account": acct.result(), "positions": positions.result(), "orders": orders.result(), "at": time.time()}


def _store(mode: str, entry: dict) -> None:
    with _lock:
        _cache[mode] = entry


def _refresh_in_background(keys, mode: str) -> None:
    with _lock:
        if mode in _refreshing:
            return
        _refreshing.add(mode)

    def work():
        try:
            _store(mode, _fetch(keys, mode))
        except Exception:    # noqa: BLE001 -- the stale copy stays; the next look tries again
            pass
        finally:
            with _lock:
                _refreshing.discard(mode)

    threading.Thread(target=work, daemon=True).start()


def get(keys, mode: str, **kw) -> dict:
    """{"account","positions","orders","at": epoch seconds, "stale": bool, "error": str}. Raises AlpacaError when
    there is nothing to show and Alpaca cannot be read."""
    if not enabled():
        return {**_fetch(keys, mode, **kw), "stale": False, "error": ""}
    with _lock:
        entry = _cache.get(mode)
    age = None if entry is None else time.time() - entry["at"]
    if entry is not None and age < FRESH_SECONDS:
        return {**entry, "stale": False, "error": ""}
    if entry is not None and age < MAX_AGE_SECONDS:
        _refresh_in_background(keys, mode)
        return {**entry, "stale": True, "error": ""}
    try:
        fresh = _fetch(keys, mode, **kw)
    except alpaca.AlpacaError as exc:
        if entry is not None:
            return {**entry, "stale": True, "error": str(exc)}
        raise
    _store(mode, fresh)
    return {**fresh, "stale": False, "error": ""}
