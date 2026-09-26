"""One net-worth snapshot per calendar day -- see the net_worth_snapshots
table's own comment in schema.py for exactly when/why a row gets written.
This module is just CRUD; deciding WHICH numbers go into a snapshot (and
calling this on a startup/sync cadence) is source.reporting.aggregate.
capture_net_worth_snapshot's job, kept there since that's the module that
already owns build_summary()'s shape -- this module has no idea build_
summary even exists.
"""

from __future__ import annotations

from datetime import date

from source.common.db.connection import _now, connect


def record_snapshot(
    *,
    net_worth: float,
    manual_asset_total: float,
    linked_asset_total: float,
    liability_total: float,
    real_estate_equity_total: float,
    retirement_liquid_total: float,
    snapshot_date: str | None = None,
) -> None:
    """Upserts today's (or an explicitly given) snapshot_date's row --
    calling this again on the same day (e.g. opening the app, then
    syncing later) always overwrites that day's numbers with the latest
    rather than adding a second point for the same day."""
    snapshot_date = snapshot_date or date.today().isoformat()
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO net_worth_snapshots (
                snapshot_date, net_worth, manual_asset_total, linked_asset_total,
                liability_total, real_estate_equity_total, retirement_liquid_total,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                net_worth = excluded.net_worth,
                manual_asset_total = excluded.manual_asset_total,
                linked_asset_total = excluded.linked_asset_total,
                liability_total = excluded.liability_total,
                real_estate_equity_total = excluded.real_estate_equity_total,
                retirement_liquid_total = excluded.retirement_liquid_total,
                updated_at = excluded.updated_at
            """,
            (
                snapshot_date, net_worth, manual_asset_total, linked_asset_total,
                liability_total, real_estate_equity_total, retirement_liquid_total,
                now, now,
            ),
        )


def list_net_worth_snapshots() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM net_worth_snapshots ORDER BY snapshot_date").fetchall()
        return [dict(r) for r in rows]
