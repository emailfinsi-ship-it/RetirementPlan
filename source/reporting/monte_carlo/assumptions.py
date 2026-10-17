"""Small, generic helpers for reading a plan's `assumptions` dict and
for computing a percentile of a sorted list of path/scenario values --
used by both simulation.py (the random Monte Carlo runs) and
stress_test.py (the deterministic historical replay), so parsing an
assumption or reading off a percentile behaves identically in both.
"""

from __future__ import annotations

import json
import math


def _resolve_birth_year(assumptions: dict) -> int | None:
    raw = assumptions.get("birth_year")
    if raw in (None, ""):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None



def _resolve_spouse_birth_year(assumptions: dict) -> int | None:
    """Same blank-is-None/garbage-is-None parsing as _resolve_birth_year,
    for the spouse's own "spouse's birth year" assumption -- what her own
    RMD start age (73 vs 75) and her own age each simulated year come
    from, independent of the plan owner's. None means "not set", which
    skips RMD modeling for her accounts only (just like an unset birth
    year already skips it for the plan owner)."""
    raw = assumptions.get("spouse_birth_year")
    if raw in (None, ""):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None



def _resolve_spouse_tax_deferred_share(assumptions: dict) -> float:
    """The fraction (0..1) of the starting Tax-deferred pool that sits in
    accounts assigned to the spouse -- NOT a user-entered assumption, but
    a derived figure source.reporting.aggregate.build_summary computes
    from each account's Owner and injects into the `assumptions` dict it
    hands back (and the Drawdown/Legacy pages inject their own, since
    their starting pools also include unlinked Plaid accounts), so every
    simulation entry point -- which all already take `assumptions` --
    picks it up without a new parameter threaded through each one. 0.0
    (missing, blank, garbage, or no spouse-owned Tax-deferred money at
    all) means "no per-owner tracking": every engine behaves exactly as
    it did before owners existed."""
    raw = assumptions.get("spouse_tax_deferred_share")
    if raw in (None, ""):
        return 0.0
    try:
        return min(1.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0



def _resolve_rental_taxable_fraction(assumptions: dict, year: int) -> float:
    """The share (0..1) of rental income that counts as taxable ordinary
    income in `year`. NOT a user-entered assumption: source.reporting.
    aggregate.build_summary derives `rental_taxable_schedule` from the
    Real Estate tab's "Loan ends" column and injects it (a JSON list of
    [loan_end_year | null, weight] pairs, one per property -- weight is the
    property's annual income) into the assumptions dict, the same way
    `spouse_tax_deferred_share` is. A property's rent is sheltered by
    mortgage interest and depreciation while its loan runs, so it only
    counts once `year` is AFTER its loan_end_year; a property with no
    loan end year is taxable every year. 1.0 (missing, blank, garbage)
    means "fully taxable every year", the original behavior."""
    raw = assumptions.get("rental_taxable_schedule")
    if not raw:
        return 1.0
    try:
        entries = json.loads(raw) if isinstance(raw, str) else raw
        total = taxable = 0.0
        for end_year, weight in entries:
            weight = float(weight)
            total += weight
            if end_year is None or year > int(end_year):
                taxable += weight
    except (TypeError, ValueError):
        return 1.0
    return taxable / total if total > 0 else 1.0


def _resolve_taxable_deposit(assumptions: dict, year: int) -> float:
    """A one-time cash deposit into the Taxable pool in `year` (after that
    year's growth, before its withdrawal) -- NOT a user assumption: the
    real-estate sale what-if (reporting.monte_carlo.real_estate_sale)
    injects `taxable_deposits`, a JSON {"<year>": dollars} object, when
    the sale happens in a future year rather than today. 0.0 for a
    missing, blank or garbage value."""
    raw = assumptions.get("taxable_deposits")
    if not raw:
        return 0.0
    try:
        deposits = json.loads(raw) if isinstance(raw, str) else raw
        return float(deposits.get(str(year), 0.0))
    except (TypeError, ValueError, AttributeError):
        return 0.0


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



def _resolve_early_tax_deferred_age(assumptions: dict) -> int | None:
    """Same blank-is-None/garbage-is-None parsing as _resolve_birth_year
    above, for the "Start drawing Tax-deferred at age" assumption --
    None means "not set", which drawdown_schedule.py treats as "use the
    default Taxable-first withdrawal order for the whole plan" (the
    original behavior, unchanged unless a user explicitly opts in by
    setting an age on the Drawdown Planning tab)."""
    raw = assumptions.get("early_tax_deferred_age")
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
