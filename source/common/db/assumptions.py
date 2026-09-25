"""The Monte Carlo assumptions key/value table (expected return,
volatility, inflation, birth year, ...) -- see schema.DEFAULT_ASSUMPTIONS
for what's seeded on init_db, and source.reporting.monte_carlo for how
each key is used.
"""

from __future__ import annotations

from source.common.db.connection import _now, connect


def get_assumptions() -> dict:
    with connect() as conn:
        rows = conn.execute("SELECT key, value FROM assumptions").fetchall()
        return {r["key"]: r["value"] for r in rows}



def set_assumption(key: str, value) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO assumptions (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, str(value), _now()),
        )



def set_assumptions(values: dict) -> None:
    for key, value in values.items():
        set_assumption(key, value)
