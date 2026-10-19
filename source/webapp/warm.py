"""Gets the slow pages ready in the background.

The "Will my money last?" tab runs about sixteen simulations, roughly five
seconds, every time it opens. dashboard.run() switches this on (the tests
never do): it turns on the simulation memory (see
source.reporting.monte_carlo.simulation.enable_memo) and, a moment after the
app starts or anything is saved, quietly builds the slow pages once on a
background thread so the answers are already remembered when you click.
It only ever reads; a failure is ignored and the page simply takes its
normal time.
"""

from __future__ import annotations

import threading

from source.common import first_run

_enabled = False
_lock = threading.Lock()
_timer: threading.Timer | None = None
_running = False
_again = False


def enable(on: bool = True) -> None:
    global _enabled
    from source.reporting.monte_carlo import simulation

    _enabled = bool(on)
    simulation.enable_memo(_enabled)


def schedule(delay: float = 3.0) -> None:
    """Wait `delay` seconds (so a burst of saves counts once), then warm up."""
    global _timer
    if not _enabled:
        return
    with _lock:
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(delay, _start)
        _timer.daemon = True
        _timer.start()


def _start() -> None:
    global _running, _again
    with _lock:
        if _running:
            _again = True
            return
        _running = True
    threading.Thread(target=_work, daemon=True).start()


def _work() -> None:
    global _running, _again
    try:
        while True:
            try:
                if not first_run.required():
                    run_once()
            except Exception:
                pass
            with _lock:
                if not _again:
                    _running = False
                    return
                _again = False
    except BaseException:
        with _lock:
            _running = False


def run_once() -> None:
    """Builds the pages whose numbers come from the simulations."""
    from source.webapp.pages.monte_carlo_page import _render_monte_carlo_page
    from source.webapp.pages.summary import _render_summary_page

    _render_summary_page()
    _render_monte_carlo_page()
