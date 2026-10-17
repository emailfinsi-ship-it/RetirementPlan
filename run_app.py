"""Standalone entry point for the packaged (PyInstaller) build -- see
scripts/build_standalone_app.sh. Not used for the plain-source /
run_dashboard.sh path (that runs "python -m source.webapp.dashboard"
directly); this file exists only because PyInstaller needs a real,
top-level script to point at, rather than a "-m package.module" target.
Deliberately as thin as possible -- source.webapp.dashboard.run() is the
one real entry point both paths share, so behavior never drifts between
"run from source" and "run as a packaged app"."""

from __future__ import annotations

import os
import sys

from source.webapp import dashboard

if __name__ == "__main__":
    # A bundled app launched without a terminal can have no stdout/stderr;
    # point them at nothing rather than letting a print() raise.
    for _name in ("stdout", "stderr"):
        if getattr(sys, _name) is None:
            setattr(sys, _name, open(os.devnull, "w"))
    dashboard.run(open_browser="--no-browser" not in sys.argv)
