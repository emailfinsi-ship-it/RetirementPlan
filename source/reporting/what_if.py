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


def _number(raw, label: str, low: float, high: float, default: float | None) -> float | None:
    if raw in (None, ""):
        return default
    try:
        value = float(str(raw).replace(",", "").replace("%", ""))
    except ValueError:
        raise ValueError(f"{label} must be a number.") from None
    if not low <= value <= high:
        raise ValueError(f"{label} must be between {low:g} and {high:g}.")
    return value


def run_custom_what_if(summary: dict, payload: dict, mode: str = "today") -> dict:
    """Plan as it is versus ONE change you choose: spend X% more or less
    (negative = less), retire N years later (negative = earlier) and/or a
    different average yearly growth. Both runs use the plan's own simulation
    settings, so the baseline matches the Summary's headline figure exactly.
    Returns {"label", "base", "whatif"}, each a dict of success_rate and the
    cautious/typical/strong ending balances in the Summary's dollar basis."""
    from source.reporting import presentation as pres

    spend_pct = _number(payload.get("spend_change_pct"), "Spending change", -90, 200, 0.0)
    shift_years = _number(payload.get("retire_shift_years"), "Retirement shift", -20, 30, 0.0)
    growth_pct = _number(payload.get("expected_return_pct"), "Average yearly growth", -5, 20, None)
    shift_years = int(round(shift_years))

    assumptions = dict(summary["assumptions"])
    expenses, income = summary["expenses"], summary["income_for_simulation"]
    pools, balance = summary["retirement_pools"], summary["net_liquid_asset"]
    base_year = summary["this_year"]

    def run(a, e) -> dict:
        seed = stable_simulation_seed(starting_balance=balance, expenses=e, income=income, assumptions=a, pools=pools)
        raw = run_simulation(
            starting_balance=balance, expenses=e, income=income, assumptions=a, pools=pools, rng=random.Random(seed),
        )
        r = pres.convert_result(raw, a, base_year, mode)
        return {
            "success_rate": r["success_rate"], "p10": r["p10_ending_balance"],
            "median": r["median_ending_balance"], "p90": r["p90_ending_balance"],
        }

    changed_a, changed_e = dict(assumptions), expenses
    parts = []
    if spend_pct:
        changed_e = _scale_line_items(expenses, 1.0 + spend_pct / 100.0)
        parts.append(f"spend {abs(spend_pct):g}% {'less' if spend_pct < 0 else 'more'}")
    if shift_years:
        retire_year = _resolve_retirement_year(assumptions)
        if retire_year is None:
            raise ValueError("Set a retirement year first (Summary > Change assumptions) to try retiring earlier or later.")
        changed_a["retirement_year"] = retire_year + shift_years
        parts.append(f"retire {abs(shift_years)} year{'s' if abs(shift_years) != 1 else ''} {'later' if shift_years > 0 else 'earlier'}"
                     f" ({retire_year + shift_years})")
    if growth_pct is not None and abs(growth_pct / 100.0 - float(assumptions.get("expected_return") or 0.06)) > 1e-9:
        changed_a["expected_return"] = growth_pct / 100.0
        parts.append(f"{growth_pct:g}% average yearly growth")
    if not parts:
        raise ValueError("Change at least one of spending, retirement year or growth to compare.")
    return {"label": "If you " + ", ".join(parts), "base": run(assumptions, expenses), "whatif": run(changed_a, changed_e)}
