"""One-click "what if" checks for the Summary: re-run the plan's own
Monte Carlo simulation with a single change and report the new chance the
money lasts. Reuses run_simulation (no separate math), seeded per variant
so repeated clicks give the same answer."""

from __future__ import annotations

import random

from source.reporting.monte_carlo import _resolve_retirement_year, run_simulation, stable_simulation_seed
from source.reporting.monte_carlo.sensitivity import _scale_line_items

_ITERATIONS = 300


def _success(*, balance: float, expenses: list, income: list, assumptions: dict, pools: dict | None) -> float:
    seed = stable_simulation_seed(
        starting_balance=balance, expenses=expenses, income=income, assumptions=assumptions, pools=pools,
    )
    return run_simulation(
        starting_balance=balance, expenses=expenses, income=income, assumptions=assumptions, pools=pools,
        rng=random.Random(seed),
    )["success_rate"]


def run_what_ifs(summary: dict, iterations: int = _ITERATIONS) -> list[dict]:
    """[{"key", "label", "success_rate", "change"}]: the plan as it is, then
    spending 10% less, retiring a year later (only when a retirement year is
    set) and both. `change` is in percentage points versus the first row,
    measured at the same iteration count so the comparison is fair."""
    assumptions = dict(summary["assumptions"])
    assumptions["iterations"] = iterations
    expenses, income = summary["expenses"], summary["income_for_simulation"]
    pools, balance = summary["retirement_pools"], summary["net_liquid_asset"]

    def run(a, e):
        return _success(balance=balance, expenses=e, income=income, assumptions=a, pools=pools)

    leaner = _scale_line_items(expenses, 0.9)
    retire_year = _resolve_retirement_year(assumptions)
    later = {**assumptions, "retirement_year": retire_year + 1} if retire_year is not None else None

    rows = [
        ("now", "Plan as it is today", run(assumptions, expenses)),
        ("spend_less", "Spend 10% less each year", run(assumptions, leaner)),
    ]
    if later is not None:
        rows.append(("retire_later", f"Retire a year later ({retire_year + 1})", run(later, expenses)))
        rows.append(("both", "Spend 10% less and retire a year later", run(later, leaner)))
    base = rows[0][2]
    return [
        {"key": k, "label": label, "success_rate": rate, "change": round((rate - base) * 100, 1)}
        for k, label, rate in rows
    ]
