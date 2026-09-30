"""Per-account daily balance history for linked investment accounts -- see
the account_balance_snapshots table's own comment in schema.py for exactly
when/why a row gets written. This module is just CRUD; deciding WHICH
accounts get snapshotted (and calling this on a startup/sync cadence) is
source.reporting.aggregate.capture_investment_account_balances's job, kept
there since that's the module that already owns linked_data.linkable_
accounts()'s shape -- this module has no idea that function even exists.

Mirrors source.common.db.net_worth_snapshots, just keyed per (account_id,
snapshot_date) instead of per snapshot_date alone.
"""

from __future__ import annotations

from datetime import date

from source.common.db.connection import _now, connect


def record_account_balance_snapshot(
    *,
    account_id: str,
    balance: float,
    snapshot_date: str | None = None,
) -> None:
    """Upserts this account's row for today (or an explicitly given
    snapshot_date) -- calling this again for the same account on the same
    day (e.g. opening the app, then syncing later) always overwrites that
    day's balance with the latest rather than adding a second point for
    the same day."""
    snapshot_date = snapshot_date or date.today().isoformat()
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO account_balance_snapshots (
                account_id, snapshot_date, balance, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account_id, snapshot_date) DO UPDATE SET
                balance = excluded.balance,
                updated_at = excluded.updated_at
            """,
            (account_id, snapshot_date, balance, now, now),
        )


def list_account_balance_snapshots(account_id: str | None = None) -> list[dict]:
    """All snapshot rows, oldest first, optionally restricted to one
    account_id."""
    with connect() as conn:
        if account_id is None:
            rows = conn.execute(
                "SELECT * FROM account_balance_snapshots ORDER BY snapshot_date"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM account_balance_snapshots WHERE account_id = ? "
                "ORDER BY snapshot_date",
                (account_id,),
            ).fetchall()
        return [dict(r) for r in rows]
