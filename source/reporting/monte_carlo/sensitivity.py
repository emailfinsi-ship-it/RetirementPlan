"""Sensitivity analysis for the Monte Carlo simulation: a "what moves
the needle" tornado sweep that holds every other input fixed and
perturbs one lever at a time (a "low" and a "high" nudge) to see how
much the Success rate swings -- so a plan owner gets a sense of which
assumption their plan is actually most fragile to, not just the one
point estimate the Monte Carlo tab's headline numbers give.

Deliberately reuses run_simulation() itself for every perturbed run --
no separate math lives here, so a lever's effect is grounded in the
exact same engine (Gaussian returns, three-pool tax/RMD withdrawal
order if `pools` is passed, ...) as the live Monte Carlo tab, never a
simplified stand-in. Each run is seeded via stable_simulation_seed on
that specific variant's own inputs, so re-opening the page always shows
the same tornado (reproducible across reloads), and a genuinely
different input still draws its own genuinely different set of random
paths rather than reusing another lever's draws.
"""

from __future__ import annotations

import random

from source.reporting.monte_carlo.simulation import run_simulation, stable_simulation_seed


def _scale_line_items(rows: list, factor: float) -> list:
    """A copy of `rows` with every annual_amount scaled by `factor` --
    models "what if expenses/income ran N% higher or lower" without
    touching any other field (base_year, inflates, start_year/end_year
    all carry over unchanged, so a scaled row still inflates/starts/ends
    exactly the way the original did)."""
    scaled = []
    for row in rows:
        new_row = dict(row)
        new_row["annual_amount"] = (row.get("annual_amount") or 0.0) * factor
        scaled.append(new_row)
    return scaled


def _with_assumption_delta(assumptions: dict, key: str, delta: float, *, min_value: float | None = None) -> dict:
    """A copy of `assumptions` with `key` nudged by `delta` from its own
    current value (so "Expected return -1pt" always means relative to
    this plan's own Expected return, not a fixed absolute number).
    `min_value` clamps a nudge that would otherwise push a value past a
    physically-meaningless bound (e.g. a plan horizon below 1 year, or
    negative return volatility) -- run_simulation itself would clamp/
    misbehave on those, so it's clamped here instead, before it ever
    reaches the engine."""
    updated = dict(assumptions)
    current = float(assumptions.get(key) or 0.0)
    new_value = current + delta
    if min_value is not None:
        new_value = max(min_value, new_value)
    updated[key] = new_value
    return updated


# Each lever perturbs exactly one input, relative to the plan's own
# baseline value, holding everything else fixed. `low`/`high` each take
# (assumptions, expenses, income) and return a new
# (assumptions, expenses, income) triple -- most levers only touch
# `assumptions`; expense_level/income_level instead scale the relevant
# line-item list, since "expenses ran 10% higher" isn't a single
# assumptions-table number in this program's data model.
LEVERS = [
    {
        "key": "expected_return",
        "label": "Expected return",
        "swing_label": "±1 percentage point",
        "low": lambda a, e, i: (_with_assumption_delta(a, "expected_return", -0.01), e, i),
        "high": lambda a, e, i: (_with_assumption_delta(a, "expected_return", 0.01), e, i),
    },
    {
        "key": "return_volatility",
        "label": "Return volatility",
        "swing_label": "±2 percentage points",
        "low": lambda a, e, i: (_with_assumption_delta(a, "return_volatility", -0.02, min_value=0.0), e, i),
        "high": lambda a, e, i: (_with_assumption_delta(a, "return_volatility", 0.02), e, i),
    },
    {
        "key": "inflation_rate",
        "label": "Inflation",
        "swing_label": "±1 percentage point",
        "low": lambda a, e, i: (_with_assumption_delta(a, "inflation_rate", -0.01, min_value=0.0), e, i),
        "high": lambda a, e, i: (_with_assumption_delta(a, "inflation_rate", 0.01), e, i),
    },
    {
        "key": "plan_horizon_years",
        "label": "Plan horizon",
        "swing_label": "±5 years",
        "low": lambda a, e, i: (_with_assumption_delta(a, "plan_horizon_years", -5, min_value=1), e, i),
        "high": lambda a, e, i: (_with_assumption_delta(a, "plan_horizon_years", 5), e, i),
    },
    {
        "key": "expense_level",
        "label": "Expense level",
        "swing_label": "±10%",
        "low": lambda a, e, i: (a, _scale_line_items(e, 0.9), i),
        "high": lambda a, e, i: (a, _scale_line_items(e, 1.1), i),
    },
    {
        "key": "income_level",
        "label": "Income level",
        "swing_label": "±10%",
        "low": lambda a, e, i: (a, e, _scale_line_items(i, 0.9)),
        "high": lambda a, e, i: (a, e, _scale_line_items(i, 1.1)),
    },
]


def _run_variant(*, starting_balance: float, expenses: list, income: list, assumptions: dict, pools: dict | None, seed: int) -> dict:
    return run_simulation(
        starting_balance=starting_balance, expenses=expenses, income=income,
        assumptions=assumptions, pools=pools, rng=random.Random(seed),
    )


_DEFAULT_SENSITIVITY_ITERATIONS = 50


def run_sensitivity_analysis(
    *, starting_balance: float, expenses: list, income: list, assumptions: dict, pools: dict | None = None,
    iterations: int = _DEFAULT_SENSITIVITY_ITERATIONS,
) -> dict:
    """Runs the tornado sweep: one baseline Monte Carlo run at the
    plan's actual assumptions, then a low/high pair for every lever in
    LEVERS, each holding every other input fixed at baseline. Returns
    {"baseline_success_rate": ..., "rows": [...]}, `rows` already sorted
    by swing size (biggest first) so the tornado shape falls straight
    out of the list order -- the page renderer doesn't need to re-sort.

    Every run in the sweep -- baseline included -- overrides the plan's
    own `iterations` assumption with `iterations` here (default 50,
    deliberately much smaller). 6 levers x 2 sides + 1 baseline is
    already 13 full Monte Carlo runs on a single page load, and the
    three-pool tax/RMD engine (engaged whenever `pools` is passed, which
    is the common case) cannot precompute a shared withdrawal schedule
    the way the single-balance model does -- its per-path, per-year tax
    calculation makes each iteration meaningfully more expensive.
    Measured against a realistic plan (40-year horizon, three pools,
    1000 iterations), running this sweep at the plan's own iteration
    count took ~6s on top of the ~4.7s the Monte Carlo tab's own two
    simulations already take; at 50 iterations it's ~1.5s -- a
    worthwhile trade for a view whose job is "which lever matters most",
    not a precise headline number the way the tab's own tiles are. Pass
    a larger `iterations` explicitly if a more precise sweep is ever
    needed.

    Each row is {"key", "label", "swing_label", "low_success_rate",
    "high_success_rate", "swing"} -- `swing` is the larger of the two
    perturbations' distance from baseline, in success-rate terms (0..1),
    used only for sorting/display, not itself a simulation output."""
    base_assumptions = dict(assumptions)
    base_assumptions["iterations"] = iterations

    baseline_seed = stable_simulation_seed(
        starting_balance=starting_balance, expenses=expenses, income=income, assumptions=base_assumptions, pools=pools,
    )
    baseline_rate = _run_variant(
        starting_balance=starting_balance, expenses=expenses, income=income,
        assumptions=base_assumptions, pools=pools, seed=baseline_seed,
    )["success_rate"]

    rows = []
    for lever in LEVERS:
        rates = {}
        for side in ("low", "high"):
            a, e, i = lever[side](base_assumptions, expenses, income)
            seed = stable_simulation_seed(starting_balance=starting_balance, expenses=e, income=i, assumptions=a, pools=pools)
            rates[side] = _run_variant(starting_balance=starting_balance, expenses=e, income=i, assumptions=a, pools=pools, seed=seed)["success_rate"]
        swing = max(abs(rates["low"] - baseline_rate), abs(rates["high"] - baseline_rate))
        rows.append({
            "key": lever["key"],
            "label": lever["label"],
            "swing_label": lever["swing_label"],
            "low_success_rate": rates["low"],
            "high_success_rate": rates["high"],
            "swing": swing,
        })
    rows.sort(key=lambda r: r["swing"], reverse=True)
    return {"baseline_success_rate": baseline_rate, "rows": rows}
