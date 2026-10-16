"""The random Monte Carlo engine: Gaussian returns (run_simulation) and
S&P 500 historical-bootstrap returns (run_historical_bootstrap_simulation)
both drive the same underlying path-simulation loop
(_run_random_simulation) -- only how each year's random return is drawn
differs between the two. stable_simulation_seed lets two independent
callers (the Summary tab's "What if" card and the Monte Carlo tab) agree
on the exact same 1000 random paths for the same plan data, so they
never show two different numbers for what the user expects to be "the
same" simulation.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date

from source.reporting.monte_carlo.assumptions import (
    _percentile,
    _resolve_birth_year,
    _resolve_gains_fraction,
    _resolve_retirement_year,
    _truthy_assumption,
)
from source.reporting.monte_carlo.pools import _apply_year_withdrawal, new_owner_state
from source.reporting.monte_carlo.stress_test import _SP500_ANNUAL_RETURNS
from source.reporting.monte_carlo.withdrawal import (
    annual_net_withdrawal_need,
    annual_taxable_income,
    yearly_withdrawal_schedule,
)


def _run_random_simulation(
    *, starting_balance: float, expenses: list, assumptions: dict, income: list, rng, draw_return, pools: dict | None = None,
) -> dict:
    """Shared mechanics behind run_simulation() and
    run_historical_bootstrap_simulation() below -- both draw
    `iterations` random annual-return paths over the plan horizon and
    withdraw each year's annual_net_withdrawal_need; the only thing that
    differs between "Gaussian" and "S&P 500 historical bootstrap" is
    *how* draw_return(rng) picks that year's return, so that's the one
    thing each caller supplies. Returns the p10/median/p90 band plus a
    few summary figures (success rate, median/p10/p90 ending balance)
    shared by both callers' result dicts.

    `pools` is None by default -- the single-balance model below (every
    withdrawal taxed as if it's 100% pre-tax/401k income, one combined
    balance walked down each path) runs completely unchanged in that
    case, so this stays byte-for-byte what it's always been for any
    existing caller. Passed a {"tax_deferred", "roth", "taxable"} dict
    instead, it engages the three-pool withdrawal/RMD/tax engine (see
    that section's own comment above _pool_year_tax) -- the same return
    is applied to all three pools each simulated year (one blended
    portfolio return, not a separate one per account), and the band this
    returns is still each path's COMBINED balance across all three
    pools, so render_fan_svg and every other reader of `band`/
    `median_ending_balance`/etc. need no changes either way."""
    iterations = max(1, int(float(assumptions.get("iterations") or 1000)))
    horizon = max(1, int(float(assumptions.get("plan_horizon_years") or 40)))
    inflation_rate = float(assumptions.get("inflation_rate") or 0.0)
    # annual_income_offset is a manual flat top-up (any pension/rental
    # figure not worth its own line item); itemized income rows (Rental,
    # Social Security, ...) stack on top of it, not instead of it.
    income_offset = float(assumptions.get("annual_income_offset") or 0)
    apply_drawdown_tax = _truthy_assumption(assumptions, "apply_drawdown_tax")
    current_year_raw = assumptions.get("current_year")
    current_year = int(current_year_raw) if current_year_raw not in (None, "") else date.today().year

    years = [current_year + i for i in range(horizon)]
    retirement_year = _resolve_retirement_year(assumptions)

    if pools is None:
        # Scenario/return-independent (see yearly_withdrawal_schedule) --
        # computed once per year, not once per (path, year) pair, both for
        # speed (iterations x horizon calls collapse to just horizon) and
        # because that's genuinely what every path withdraws that year.
        schedule = yearly_withdrawal_schedule(
            expenses, income, years, inflation_rate, income_offset, apply_drawdown_tax, retirement_year,
        )
        withdrawals = schedule["totals"]
        paths = []
        depleted_count = 0
        for _ in range(iterations):
            balance = max(starting_balance, 0.0)
            path = []
            depleted = False
            for i in range(horizon):
                r = draw_return(rng)
                balance = balance * (1 + r)
                balance -= withdrawals[i]
                if balance < 0:
                    balance = 0.0
                    depleted = True
                path.append(balance)
            paths.append(path)
            if depleted:
                depleted_count += 1
        yearly_tax_total = sum(schedule["taxes"])
        first_year_tax = schedule["taxes"][0] if schedule["taxes"] else 0.0
    else:
        # Every path's own RMD depends on its own running tax-deferred
        # balance (which depends on that path's own random returns), so
        # unlike the single-balance model above this genuinely can't be
        # precomputed once per year and shared across paths -- tax is
        # path-dependent here.
        birth_year = _resolve_birth_year(assumptions)
        gains_fraction = _resolve_gains_fraction(assumptions)
        needs = [
            annual_net_withdrawal_need(expenses, income, year, inflation_rate, income_offset, retirement_year)
            for year in years
        ]
        # Taxable income under each year's withdrawal (rent, pension, taxable
        # Social Security) -- the same for every path, so computed once.
        base_incomes = [annual_taxable_income(income, year, inflation_rate) for year in years]
        paths = []
        path_total_taxes = []
        path_first_year_taxes = []
        depleted_count = 0
        for _ in range(iterations):
            path_pools = {
                "tax_deferred": pools.get("tax_deferred", 0.0),
                "roth": pools.get("roth", 0.0),
                "taxable": pools.get("taxable", 0.0),
                "real_estate": pools.get("real_estate", 0.0),
            }
            owners = new_owner_state(path_pools["tax_deferred"], assumptions)
            path = []
            path_tax_total = 0.0
            depleted = False
            for i, year in enumerate(years):
                r = draw_return(rng)
                for name in path_pools:
                    path_pools[name] *= (1 + r)
                age = (year - birth_year) if birth_year is not None else None
                year_result = _apply_year_withdrawal(
                    path_pools, need=needs[i], age=age, birth_year=birth_year, gains_fraction=gains_fraction,
                    year=year, inflation_rate=inflation_rate, apply_drawdown_tax=apply_drawdown_tax, owners=owners,
                    base_ordinary_income=base_incomes[i],
                )
                path_tax_total += year_result["tax"]
                if i == 0:
                    path_first_year_taxes.append(year_result["tax"])
                if year_result["shortfall"] > 1e-6:
                    depleted = True
                path.append(sum(path_pools.values()))
            paths.append(path)
            path_total_taxes.append(path_tax_total)
            if depleted:
                depleted_count += 1
        # Tax is now path-dependent (see above), so the single "here's
        # the tax bill" figures the single-balance model reports exactly
        # become a statistic across paths instead -- the median path's
        # total/first-year tax, same percentile-of-paths spirit as
        # median_ending_balance below.
        yearly_tax_total = _percentile(sorted(path_total_taxes), 50)
        first_year_tax = _percentile(sorted(path_first_year_taxes), 50) if path_first_year_taxes else 0.0

    band = []
    for i, year in enumerate(years):
        values = sorted(p[i] for p in paths)
        band.append({
            "year": year,
            "p10": _percentile(values, 10),
            "median": _percentile(values, 50),
            "p90": _percentile(values, 90),
        })

    return {
        "years": years,
        "band": band,
        "iterations": iterations,
        "starting_balance": starting_balance,
        "success_rate": 1.0 - (depleted_count / iterations),
        "median_ending_balance": band[-1]["median"] if band else 0.0,
        "p10_ending_balance": band[-1]["p10"] if band else 0.0,
        "p90_ending_balance": band[-1]["p90"] if band else 0.0,
        "apply_drawdown_tax": apply_drawdown_tax,
        "yearly_tax_total": yearly_tax_total,
        "first_year_tax": first_year_tax,
        "pools": bool(pools),
    }



def stable_simulation_seed(
    *, starting_balance: float, expenses: list, assumptions: dict, income: list | None = None, pools: dict | None = None,
) -> int:
    """A deterministic seed derived from every input that actually affects
    a random simulation (starting balance, pools, assumptions, expenses,
    income) -- pass it as `random.Random(seed)` to run_simulation's/
    run_historical_bootstrap_simulation's `rng` kwarg.

    Both of those default to a fresh, unseeded random.Random() when no
    `rng` is given, which means two independent calls over the exact same
    plan data -- e.g. the Summary tab's "What if" card and the Monte
    Carlo tab, which both call build_summary() and then run_simulation()
    with the same starting_balance/pools/assumptions/expenses/income --
    land on two different sets of 1000 random paths, and so two different
    (if both directionally-plausible) success-rate/ending-balance
    figures. That's expected variance for two truly independent Monte
    Carlo runs, but it reads as a bug when it shows up as two different
    numbers for what the user reasonably expects to be "the same"
    simulation of "the same" plan on two different tabs.

    Seeding both callers with this instead makes the result reproducible
    (same inputs -> byte-identical run_simulation()/
    run_historical_bootstrap_simulation() output, on every page load, on
    every tab) without losing genuine randomness across an actual change
    -- the seed itself changes the moment any input it's built from does
    (a new asset balance, a different assumption, ...), so it's not a
    frozen/stale result either."""
    payload = json.dumps(
        {
            "starting_balance": starting_balance,
            "pools": pools,
            "assumptions": assumptions,
            "expenses": expenses,
            "income": income,
        },
        sort_keys=True, default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)



def run_simulation(
    *, starting_balance: float, expenses: list, assumptions: dict, income: list | None = None, rng=None,
    pools: dict | None = None,
) -> dict:
    expected_return = float(assumptions.get("expected_return") or 0.06)
    volatility = float(assumptions.get("return_volatility") or 0.12)
    result = _run_random_simulation(
        starting_balance=starting_balance, expenses=expenses, assumptions=assumptions, income=income or [],
        rng=rng or random.Random(), draw_return=lambda r: r.gauss(expected_return, volatility), pools=pools,
    )
    result["method"] = "gaussian"
    return result



def run_historical_bootstrap_simulation(
    *, starting_balance: float, expenses: list, assumptions: dict, income: list | None = None, rng=None,
    pools: dict | None = None,
) -> dict:
    """A second random Monte Carlo run, alongside run_simulation()'s
    Gaussian one: instead of drawing each simulated year's return from
    Normal(expected_return, return_volatility), it draws (with
    replacement) from the real recorded S&P 500 annual total returns in
    _SP500_ANNUAL_RETURNS (defined below, next to the historical stress
    test that also uses it) -- a standard "historical bootstrap"
    resampling method. This reflects the market's actual historical
    distribution (fat tails, real crash years like 1931/2008/2022 mixed
    in with real boom years) rather than a bell curve shaped entirely by
    this plan's own Expected return/Volatility assumptions, so its
    p10/median/p90 band answers "how bad/good could it get" grounded in
    what markets have actually done, independent of what you assumed.
    (_SP500_ANNUAL_RETURNS is looked up at call time, not def time, so
    it being defined later in this module is fine.)"""
    historical_returns = list(_SP500_ANNUAL_RETURNS.values())
    result = _run_random_simulation(
        starting_balance=starting_balance, expenses=expenses, assumptions=assumptions, income=income or [],
        rng=rng or random.Random(), draw_return=lambda r: r.choice(historical_returns), pools=pools,
    )
    result["method"] = "sp500_historical_bootstrap"
    result["sample_size"] = len(historical_returns)
    return result
