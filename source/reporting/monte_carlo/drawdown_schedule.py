"""A single, non-random year-by-year drawdown projection -- the
Drawdown Planning tab's "what does the standard tax-efficient
withdrawal order actually look like, year by year" view, alongside its
snapshot-by-tax-bucket summary (source.reporting.aggregate.
build_summary's drawdown_pools/drawdown_sources).

Unlike run_simulation/run_historical_bootstrap_simulation (1000+ random
return paths, read off as a p10/median/p90 band), this walks exactly one
path using the plan's own Expected return assumption with no volatility
-- appropriate here because the point isn't "how much uncertainty is
there", it's "trace through RMDs, the taxable-then-tax-deferred-then-
Roth withdrawal order, and the resulting tax bill, one row per year, so
a user can actually see the mechanics of their own plan." Reuses the
exact same three-pool withdrawal/RMD/tax engine (_apply_year_withdrawal)
every other simulation method in this package already shares, so this
never re-implements (and risks drifting from) that logic.
"""

from __future__ import annotations

from datetime import date

from source.reporting.monte_carlo.assumptions import (
    _resolve_birth_year,
    _resolve_gains_fraction,
    _resolve_retirement_year,
    _truthy_assumption,
)
from source.reporting.monte_carlo.pools import _apply_year_withdrawal
from source.reporting.monte_carlo.withdrawal import annual_net_withdrawal_need


def deterministic_drawdown_schedule(
    *, pools: dict, expenses: list, assumptions: dict, income: list | None = None, horizon_years: int | None = None,
) -> dict:
    """Walks `pools` (a {"tax_deferred", "roth", "taxable", "real_estate"}
    dict -- e.g. build_summary's drawdown_pools) forward one year at a
    time for `horizon_years` (defaults to the plan's own
    plan_horizon_years assumption, same as every random simulation),
    applying that year's expected_return, then withdrawing the year's
    net need (Income/Expense tab totals, same as every other simulation
    method) via the shared RMD/withdrawal-order/tax engine.

    Returns {"years": [...], "rows": [...], "expected_return": float,
    "retirement_year": int | None} -- each row is {"year", "age", "need",
    "rmd", "tax", "shortfall", "taxable", "tax_deferred", "roth",
    "real_estate", "total"}, the pool balances AFTER that year's growth
    and withdrawal (so `rows[-1]` is the projection's ending balance by
    pool).

    When the "Retirement year" assumption is set
    (_resolve_retirement_year), every year before it withdraws nothing
    (see annual_net_withdrawal_need's own docstring) -- the pools still
    grow at expected_return every year regardless, retired or not."""
    expected_return = float(assumptions.get("expected_return") or 0.06)
    inflation_rate = float(assumptions.get("inflation_rate") or 0.0)
    income_offset = float(assumptions.get("annual_income_offset") or 0)
    apply_drawdown_tax = _truthy_assumption(assumptions, "apply_drawdown_tax")
    horizon = horizon_years or max(1, int(float(assumptions.get("plan_horizon_years") or 40)))
    current_year_raw = assumptions.get("current_year")
    current_year = int(current_year_raw) if current_year_raw not in (None, "") else date.today().year
    birth_year = _resolve_birth_year(assumptions)
    gains_fraction = _resolve_gains_fraction(assumptions)
    retirement_year = _resolve_retirement_year(assumptions)

    years = [current_year + i for i in range(horizon)]
    path_pools = {
        "tax_deferred": pools.get("tax_deferred", 0.0),
        "roth": pools.get("roth", 0.0),
        "taxable": pools.get("taxable", 0.0),
        "real_estate": pools.get("real_estate", 0.0),
    }
    rows = []
    for year in years:
        for name in path_pools:
            path_pools[name] *= (1 + expected_return)
        need = annual_net_withdrawal_need(expenses, income or [], year, inflation_rate, income_offset, retirement_year)
        age = (year - birth_year) if birth_year is not None else None
        result = _apply_year_withdrawal(
            path_pools, need=need, age=age, birth_year=birth_year, gains_fraction=gains_fraction,
            year=year, inflation_rate=inflation_rate, apply_drawdown_tax=apply_drawdown_tax,
        )
        withdrawn = result["withdrawn"]
        rows.append({
            "year": year,
            "age": age,
            "need": need,
            "rmd": result["rmd"],
            "tax": result["tax"],
            "shortfall": result["shortfall"],
            # How much actually came OUT of each pool this year -- the
            # RMD is folded into "drawn_tax_deferred" (it's a mandatory
            # draw from that same pool, not a separate pot of money), so
            # drawn_taxable + drawn_tax_deferred + drawn_roth +
            # drawn_real_estate + rmd's OWN reinvested surplus (if any
            # wasn't needed for spending) accounts for the whole year's
            # movement out of tax_deferred, taxable, roth, real_estate.
            "drawn_taxable": withdrawn.get("taxable", 0.0),
            "drawn_tax_deferred": result["rmd"] + withdrawn.get("tax_deferred", 0.0),
            "drawn_roth": withdrawn.get("roth", 0.0),
            "drawn_real_estate": withdrawn.get("real_estate", 0.0),
            "taxable": path_pools["taxable"],
            "tax_deferred": path_pools["tax_deferred"],
            "roth": path_pools["roth"],
            "real_estate": path_pools["real_estate"],
            "total": sum(path_pools.values()),
        })

    return {"years": years, "rows": rows, "expected_return": expected_return, "retirement_year": retirement_year}
