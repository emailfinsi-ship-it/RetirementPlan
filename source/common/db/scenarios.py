"""Saved assumption scenarios -- CRUD over the saved_scenarios table (see
its comment in schema.py). Which assumption keys a scenario holds, and how
scenarios are compared, lives in source.reporting.scenarios."""

from __future__ import annotations

import json

from source.common.db.connection import _now, connect


def _decode(row) -> dict:
    out = dict(row)
    try:
        out["assumptions"] = json.loads(out.pop("assumptions_json"))
    except (TypeError, ValueError):
        out["assumptions"] = {}
    return out


def list_scenarios() -> list[dict]:
    with connect() as conn:
        return [_decode(r) for r in conn.execute("SELECT * FROM saved_scenarios ORDER BY id").fetchall()]


def get_scenario(scenario_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM saved_scenarios WHERE id = ?", (scenario_id,)).fetchone()
        return _decode(row) if row else None


def save_scenario(name: str, assumptions: dict) -> int:
    """Creates a scenario, or overwrites the one with the same name."""
    name = (name or "").strip()
    if not name:
        raise ValueError("A scenario needs a name.")
    now = _now()
    payload = json.dumps({k: v for k, v in assumptions.items()}, sort_keys=True)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO saved_scenarios (name, assumptions_json, created_at, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET assumptions_json = excluded.assumptions_json, updated_at = excluded.updated_at
            """,
            (name, payload, now, now),
        )
        return conn.execute("SELECT id FROM saved_scenarios WHERE name = ?", (name,)).fetchone()["id"]


def delete_scenario(scenario_id: int) -> bool:
    with connect() as conn:
        return conn.execute("DELETE FROM saved_scenarios WHERE id = ?", (scenario_id,)).rowcount > 0
