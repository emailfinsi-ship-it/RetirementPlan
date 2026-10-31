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

def _log_crash(text: str) -> None:
    """Leaves the reason in the log folder so a failed start can be diagnosed
    (the launcher also copies the program's own output into launch.log)."""
    try:
        from datetime import datetime

        from source.common import config

        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.LOG_DIR / "crash.log", "a", encoding="utf-8") as fh:
            fh.write(f"=== {datetime.now():%Y-%m-%d %H:%M:%S}\n{text}\n")
    except Exception:
        pass


if __name__ == "__main__":
    # A bundled app launched without a terminal can have no stdout/stderr;
    # point them at nothing rather than letting a print() raise.
    for _name in ("stdout", "stderr"):
        if getattr(sys, _name) is None:
            setattr(sys, _name, open(os.devnull, "w"))
    if "--selftest" in sys.argv:
        # The import at the top proves the dashboard loads; this also checks the
        # things the stock screener needs at run time (its data file and the
        # price libraries), so a build that dropped any of them fails here and
        # the build script stops instead of shipping a broken app.
        problems = []
        try:
            from source.screener import universe

            if len(universe.market_entries()) < 400:
                problems.append("screener list (sp500.csv) is missing or too short")
        except Exception as exc:        # noqa: BLE001
            problems.append(f"screener: {exc}")
        for mod in ("pandas", "numpy", "yfinance", "requests", "cryptography"):
            try:
                __import__(mod)
            except Exception as exc:    # noqa: BLE001
                problems.append(f"{mod}: {exc}")
        try:
            from source.screener import engine, filters, jobs, parser, saved  # noqa: F401
            from source.reporting import holdings_review  # noqa: F401
        except Exception as exc:        # noqa: BLE001
            problems.append(f"screener modules: {exc}")
        try:
            from source.webapp.pages import tutorial

            for key, _name, _about in tutorial.SECTIONS:
                if not (tutorial.TUTORIAL_DIR / tutorial.video_file(key)).is_file():
                    problems.append(f"tutorial video for {key} is missing from the bundle")
            if not (tutorial.TUTORIAL_DIR / "guide.html").is_file():
                problems.append("tutorial guide is missing from the bundle")
        except Exception as exc:        # noqa: BLE001
            problems.append(f"tutorial: {exc}")
        try:
            from source.reporting import report_pdf

            if not report_pdf.report_pdf("<html><body><h2>Selftest</h2><p>ok</p></body></html>").startswith(b"%PDF"):
                problems.append("report PDF did not come out as a PDF")
        except Exception as exc:        # noqa: BLE001
            problems.append(f"report PDF: {exc}")
        if problems:
            print("selftest FAILED: " + "; ".join(problems), file=sys.stderr)
            sys.exit(1)
        print("selftest ok")
        sys.exit(0)
    try:
        import faulthandler

        faulthandler.enable()    # a hard crash prints where it happened
    except Exception:
        pass
    try:
        dashboard.run(open_browser="--no-browser" not in sys.argv)
    except KeyboardInterrupt:
        raise
    except SystemExit:
        raise
    except BaseException:
        import traceback

        text = traceback.format_exc()
        _log_crash(text)
        print(text, file=sys.stderr)
        sys.exit(1)
