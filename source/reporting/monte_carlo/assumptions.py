"""Small, generic helpers for reading a plan's `assumptions` dict and
for computing a percentile of a sorted list of path/scenario values --
used by both simulation.py (the random Monte Carlo runs) and
stress_test.py (the deterministic historical replay), so parsing an
assumption or reading off a percentile behaves identically in both.
"""

from __future__ import annotations

import math


def _resolve_birth_year(assumptions: dict) -> int | None:
    raw = assumptions.get("birth_year")
    if raw in (None, ""):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None



def _resolve_retirement_year(assumptions: dict) -> int | None:
    """Same blank-is-None/garbage-is-None parsing as _resolve_birth_year
    above, for the "Retirement year" assumption -- None means "not set",
    which every caller (annual_net_withdrawal_need and friends) treats
    as "no retirement-year gating at all" (every simulated year is
    eligible for a withdrawal, the original behavior), not as an error
    or as "already retired"."""
    raw = assumptions.get("retirement_year")
    if raw in (None, ""):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None



def _resolve_gains_fraction(assumptions: dict) -> float:
    raw = assumptions.get("taxable_gains_fraction")
    if raw in (None, ""):
        return 0.4
    try:
        return min(1.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return 0.4



def _truthy_assumption(assumptions: dict, key: str, default: bool = True) -> bool:
    """Parses an assumptions-table value (always stored as a string,
    e.g. '1'/'0') as a boolean, same convention as _pct-suffixed numeric
    assumptions elsewhere -- missing/blank falls back to `default`."""
    raw = assumptions.get(key)
    if raw in (None, ""):
        return default
    return str(raw).strip().lower() not in ("0", "false", "no")



def _percentile(sorted_values: list, pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[int(f)] * (c - k) + sorted_values[int(c)] * (k - f)
