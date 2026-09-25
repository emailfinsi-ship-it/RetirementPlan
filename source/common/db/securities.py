"""Best-effort industry classification for equity holdings, via Yahoo
Finance (source.collector.sync_industries) -- Plaid has no industry
data. Cached indefinitely once found (an industry essentially never
changes for a given security): sync_industries only looks up a
security_id it hasn't already classified.

`sector` is a separate, optional manual override for the Linked
Positions page's "Positions by sector" chart (source.webapp.dashboard.
_sector_for_industry normally derives a sector from `industry`, but a
mutual fund/ETF/target-date fund never gets an `industry` in the first
place -- see sync_industries's own docstring -- so there's nothing to
derive from; setting `sector` here directly is how one of those gets
out of the "Unknown" bucket without inventing a fake industry for it).
A row can have `industry` set with no `sector` (the common case --
sector is derived), `sector` set with no `industry` (industry stays ''
-- a fund tagged straight into a sector), or both.
"""

from __future__ import annotations

from source.common.db.connection import connect


def set_security_industry(*, security_id: str, ticker: str | None, industry: str, updated_at: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO security_industries (security_id, ticker, industry, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(security_id) DO UPDATE SET
                ticker=excluded.ticker, industry=excluded.industry, updated_at=excluded.updated_at
            """,
            (security_id, ticker, industry, updated_at),
        )



def get_security_industries() -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute("SELECT security_id, industry FROM security_industries").fetchall()
        return {r["security_id"]: r["industry"] for r in rows}



def set_security_sector(*, security_id: str, ticker: str | None, sector: str, updated_at: str) -> None:
    """Manual sector override -- lets a mutual fund/ETF/target-date fund
    (which source.collector.sync_industries never gives an `industry` to,
    since a fund holds many industries at once -- see that module's own
    docstring) be tagged straight into a sector bucket for
    the Linked Positions page's "Positions by sector" chart, without
    inventing a fake industry just to get there. Preserves any existing
    `industry` value already cached for this security_id (only ticker/
    sector/updated_at are touched on conflict) -- a brand-new row for a
    security with no prior classification gets industry='' (NOT NULL-safe;
    renders as "Unclassified", same as any other unclassified security)."""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO security_industries (security_id, ticker, industry, sector, updated_at)
            VALUES (?, ?, '', ?, ?)
            ON CONFLICT(security_id) DO UPDATE SET
                ticker=excluded.ticker, sector=excluded.sector, updated_at=excluded.updated_at
            """,
            (security_id, ticker, sector, updated_at),
        )



def get_security_sectors() -> dict[str, str]:
    """Only security_ids with a manual sector override set -- everything
    else derives its sector from `industry` at render time (see
    source.webapp.dashboard._sector_for_industry)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT security_id, sector FROM security_industries WHERE sector IS NOT NULL AND sector != ''"
        ).fetchall()
        return {r["security_id"]: r["sector"] for r in rows}



def clear_security_sectors(security_ids: list[str]) -> int:
    """Clears just the manual sector override for the given security_ids,
    leaving any `industry` classification on that row untouched (unlike
    clear_security_industries below, which deletes the whole row) --
    backs the Linked Positions page's "Clear sector" bulk action. Returns
    how many rows actually had a sector cleared."""
    if not security_ids:
        return 0
    with connect() as conn:
        placeholders = ", ".join("?" for _ in security_ids)
        cur = conn.execute(
            f"UPDATE security_industries SET sector = NULL "
            f"WHERE security_id IN ({placeholders}) AND sector IS NOT NULL",
            list(security_ids),
        )
        return cur.rowcount



def clear_security_industries(security_ids: list[str]) -> int:
    """Deletes any cached/manual classification for the given security_ids
    (a no-op for one that was never classified) -- backs the Linked
    Positions page's "Clear industry" bulk action, e.g. to undo a
    mis-typed manual label or reset an ETF back to "Unknown" so a future
    Yahoo Finance sync can try again. Returns how many rows were
    actually removed."""
    if not security_ids:
        return 0
    with connect() as conn:
        placeholders = ", ".join("?" for _ in security_ids)
        cur = conn.execute(
            f"DELETE FROM security_industries WHERE security_id IN ({placeholders})",
            list(security_ids),
        )
        return cur.rowcount



def list_unclassified_equity_tickers() -> list[dict]:
    """Every distinct equity security currently held that doesn't already
    have a cached security_industries row. One row per security_id even
    if held in several accounts. Only equities are candidates -- an ETF
    or mutual fund holds many industries at once, so a single label
    wouldn't mean much (it just shows up as "Unknown" on the Linked
    Positions industry chart/column instead)."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT h.security_id AS security_id, h.ticker_symbol AS ticker_symbol
            FROM plaid_holdings h
            WHERE LOWER(COALESCE(h.security_type, '')) = 'equity'
              AND h.ticker_symbol IS NOT NULL AND h.ticker_symbol != ''
              AND h.security_id NOT IN (SELECT security_id FROM security_industries)
            """
        ).fetchall()
        return [dict(r) for r in rows]
