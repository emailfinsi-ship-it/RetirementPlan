"""Best-effort industry classification (e.g. "Consumer Electronics",
"Software - Infrastructure", "Banks - Regional") for your equity
holdings.

Plaid has no industry data -- security_type only distinguishes equity/
etf/mutual fund/..., not what business a company is actually in. This
fills that gap from Yahoo Finance via the yfinance library (pip install
yfinance; see requirements.txt), which needs no account or API key.

Only equities are classified (an ETF or mutual fund holds many
industries at once, so a single label wouldn't mean much -- it just
shows up as "Unknown" on the Linked Positions industry chart/column
instead). Once a security_id has been *attempted* -- classified or not
-- it's cached in source.common.db's security_industries table (industry
left as '' on a failed lookup) and never looked up again: a company's
industry essentially never changes, and a ticker Yahoo Finance doesn't
recognize essentially never starts resolving either (this is common for
a 401k plan's own institutional/CIT share classes, which Plaid still
tags security_type "equity" even though Yahoo has no quote for them at
all). This keeps sync fast and avoids hammering Yahoo Finance with the
exact same failing lookup every single sync forever -- without it, a
handful of unresolvable tickers is enough real network latency (each a
timeout or a 404) to make "Sync now" slow enough for the browser to give
up on the request before the server responds. Stuck on a wrong "Unknown"
forever isn't permanent, though -- clearing a row's industry from the
Linked Positions page's bulk "Clear industry" bar deletes its cached
entry entirely, making it a candidate again on the next sync.

This step never fails the sync: if yfinance isn't installed or there's
no internet at all, nothing gets cached and every pending ticker is
retried on a future sync -- the rest of the sync (balances, holdings) is
unaffected. source.collector.sync.sync_all() calls this right after
holdings are synced.

Usage:
    python3 -m source.collector.sync_industries
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from source.common import config, db


def _fetch_industry(ticker: str) -> str | None:
    """None on any failure -- missing library, no network, unknown
    ticker, or a response with no industry field. Never raises."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        info = yf.Ticker(ticker).get_info()
    except Exception:
        return None
    industry = (info or {}).get("industry")
    industry = str(industry).strip() if industry else ""
    return industry or None


def sync_missing_industries() -> dict:
    """Classifies every equity ticker not already cached. Returns a small
    summary dict (also printed by main()) rather than raising, so a
    partial failure part-way through still keeps what it found."""
    config.ensure_directories()
    db.init_db()
    pending = db.list_unclassified_equity_tickers()

    if not pending:
        return {"checked": 0, "classified": 0, "skipped_no_ticker": 0}

    try:
        import yfinance  # noqa: F401 -- fail fast once, not once per ticker
    except ImportError:
        print(
            "yfinance not installed -- skipping industry classification "
            "(pip install yfinance to enable).",
            file=sys.stderr,
        )
        return {"checked": len(pending), "classified": 0, "error": "yfinance not installed"}

    classified = 0
    skipped_no_ticker = 0
    failed: list[str] = []
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    for row in pending:
        security_id = row["security_id"]
        ticker = row["ticker_symbol"]
        if not ticker:
            skipped_no_ticker += 1
            continue
        industry = _fetch_industry(ticker)
        if industry:
            db.set_security_industry(security_id=security_id, ticker=ticker, industry=industry, updated_at=updated_at)
            classified += 1
        else:
            failed.append(ticker)
            # Cache the attempt too (industry='' -- renders as
            # "Unclassified", same as never having tried), not just a
            # successful one. Without this, list_unclassified_equity_
            # tickers() (which only excludes security_ids already present
            # in security_industries) hands back the exact same
            # unresolvable ticker on every single sync forever -- Plaid
            # sometimes tags an institutional fund/CIT share class as
            # security_type "equity" even though it isn't one, and Yahoo
            # Finance will never have a quote for something like
            # "US.LRG.CAP.VALUE". Left unfixed, that's a real-network
            # lookup (and 404) repeated every sync indefinitely, slow
            # enough on a handful of them to be the difference between
            # "Sync now" finishing before the browser gives up on the
            # request and a BrokenPipeError when it doesn't.
            db.set_security_industry(security_id=security_id, ticker=ticker, industry="", updated_at=updated_at)

    result = {"checked": len(pending), "classified": classified, "skipped_no_ticker": skipped_no_ticker}
    if failed:
        result["unresolved_tickers"] = failed
    return result


def main() -> int:
    result = sync_missing_industries()
    print(f"Industry classification: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
