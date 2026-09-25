"""One-time-import and last-export bookkeeping -- a small key/value
table separate from `assumptions` (which is Monte Carlo inputs, not
bookkeeping).
"""

from __future__ import annotations

from source.common.db.connection import connect


def get_meta(key: str, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default



def set_meta(key: str, value) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
