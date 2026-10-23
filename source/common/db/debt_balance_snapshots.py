"""Per-debt daily balance history -- see the debt_balance_snapshots table's own
comment in schema.py. This module is just CRUD; deciding WHICH debts get
snapshotted (and when) is source.reporting.aggregate.capture_debt_balance_snapshots'
job. Mirrors source.common.db.asset_balance_snapshots, keyed per
(source, row_id, snapshot_date).
"""

from __future__ import annotations

from datetime import date

from source.common.db.connection import _now, connect

SOURCES = ("liability", "real_estate")


def record_debt_balance_snapshot(
    *,
    source: str,
    row_id: int,
    balance: float,
    name: str = "",
    category: str = "",
    snapshot_date: str | None = None,
) -> None:
    """Upserts this debt's balance for today (or an explicit snapshot_date) --
    capturing again the same day overwrites that day's value."""
    if source not in SOURCES:
        raise ValueError(f"Unknown debt source: {source!r}")
    snapshot_date = snapshot_date or date.today().isoformat()
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO debt_balance_snapshots (
                source, row_id, snapshot_date, balance, name, category, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, row_id, snapshot_date) DO UPDATE SET
                balance = excluded.balance,
                name = excluded.name,
                category = excluded.category,
                updated_at = excluded.updated_at
            """,
            (source, row_id, snapshot_date, balance, name, category, now, now),
        )


def list_debt_balance_snapshots(source: str | None = None) -> list[dict]:
    """All snapshot rows, oldest first, optionally just one source's."""
    with connect() as conn:
        if source is None:
            rows = conn.execute("SELECT * FROM debt_balance_snapshots ORDER BY snapshot_date").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM debt_balance_snapshots WHERE source = ? ORDER BY snapshot_date", (source,)
            ).fetchall()
        return [dict(r) for r in rows]


def remap_debt_balance_snapshots(source: str, id_map: dict[int, int]) -> None:
    """Re-points snapshot history from old row ids to new ones
    ({old_id: new_id}) -- used when a workbook re-import deletes and re-adds
    imported rows (new ids), so a debt's history follows it. A day that
    already has a snapshot under the new id keeps that one; the old id's
    leftovers are dropped."""
    pairs = [(new, source, old) for old, new in id_map.items() if old != new]
    if not pairs:
        return
    with connect() as conn:
        conn.executemany(
            "UPDATE OR IGNORE debt_balance_snapshots SET row_id = ? WHERE source = ? AND row_id = ?", pairs,
        )
        conn.executemany(
            "DELETE FROM debt_balance_snapshots WHERE source = ? AND row_id = ?", [(src, old) for _new, src, old in pairs],
        )
