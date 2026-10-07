"""Per-Asset-row daily balance history -- see the asset_balance_snapshots
table's own comment in schema.py. This module is just CRUD; deciding
WHICH rows get snapshotted (and when) is source.reporting.aggregate.
capture_asset_balance_snapshots' job, since that module already owns
build_summary()'s shape and the live-balance lookup.

Mirrors source.common.db.account_balance_snapshots, keyed per
(asset_id, snapshot_date).
"""

from __future__ import annotations

from datetime import date

from source.common.db.connection import _now, connect


def record_asset_balance_snapshot(
    *,
    asset_id: int,
    balance: float,
    name: str = "",
    category: str = "",
    snapshot_date: str | None = None,
) -> None:
    """Upserts this asset row's balance for today (or an explicit
    snapshot_date) -- capturing again the same day overwrites that day's
    value rather than adding a second point."""
    snapshot_date = snapshot_date or date.today().isoformat()
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO asset_balance_snapshots (
                asset_id, snapshot_date, balance, name, category, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id, snapshot_date) DO UPDATE SET
                balance = excluded.balance,
                name = excluded.name,
                category = excluded.category,
                updated_at = excluded.updated_at
            """,
            (asset_id, snapshot_date, balance, name, category, now, now),
        )


def list_asset_balance_snapshots(asset_id: int | None = None) -> list[dict]:
    """All snapshot rows, oldest first, optionally just one asset's."""
    with connect() as conn:
        if asset_id is None:
            rows = conn.execute("SELECT * FROM asset_balance_snapshots ORDER BY snapshot_date").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM asset_balance_snapshots WHERE asset_id = ? ORDER BY snapshot_date", (asset_id,)
            ).fetchall()
        return [dict(r) for r in rows]
