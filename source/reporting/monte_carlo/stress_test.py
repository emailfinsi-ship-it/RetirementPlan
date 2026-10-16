"""Historical stress test -- a deterministic replay of real market
history, as a second view alongside simulation.py's random Monte Carlo
run: instead of `iterations` random draws, each named historical crash
sequence (Great Depression, dot-com, the 2007-08 financial crisis,
1970s stagflation, plus a flat no-crash baseline) is replayed exactly
once, starting at the plan's first year, against the same starting
balance and the same per-year withdrawal need -- so every scenario
faces an identical withdrawal schedule and only the return sequence
differs. Same feature as the original workbook's "Historical Stress
Test" tab.
"""

from __future__ import annotations

from datetime import date

from source.reporting.monte_carlo.assumptions import (
    _resolve_birth_year,
    _resolve_gains_fraction,
    _resolve_rental_taxable_fraction,
    _resolve_retirement_year,
    _truthy_assumption,
)
from source.reporting.monte_carlo.pools import _apply_year_withdrawal, new_owner_state
from source.reporting.monte_carlo.withdrawal import (
    annual_expense_need,
    annual_income_need,
    annual_net_withdrawal_need,
    annual_taxable_income,
    yearly_withdrawal_schedule,
)


_SP500_ANNUAL_RETURNS: dict[int, float] = {
    1929: -0.0842, 1930: -0.249, 1931: -0.4334, 1932: -0.0819, 1933: 0.5399,
    1934: -0.0144, 1935: 0.4767, 1936: 0.3392, 1937: -0.3503, 1938: 0.3112,
    1939: -0.0041, 1940: -0.0978, 1941: -0.1159, 1942: 0.2034, 1943: 0.259,
    1944: 0.1975, 1945: 0.3644, 1946: -0.0807, 1947: 0.0571, 1948: 0.055,
    1949: 0.1879, 1950: 0.3171, 1951: 0.2402, 1952: 0.1837, 1953: -0.0099,
    1954: 0.5262, 1955: 0.3156, 1956: 0.0656, 1957: -0.1078, 1958: 0.4336,
    1959: 0.1196, 1960: 0.0047, 1961: 0.2689,
    1973: -0.1466, 1974: -0.2647, 1975: 0.372, 1976: 0.2384, 1977: -0.0718,
    1978: 0.0656, 1979: 0.1844, 1980: 0.3242, 1981: -0.0491, 1982: 0.2155,
    1983: 0.2256, 1984: 0.0627, 1985: 0.3173, 1986: 0.1867, 1987: 0.0525,
    1988: 0.1661, 1989: 0.3169, 1990: -0.031, 1991: 0.3047, 1992: 0.0762,
    1993: 0.1008, 1994: 0.0132, 1995: 0.3758, 1996: 0.2296, 1997: 0.3336,
    1998: 0.2858, 1999: 0.2104,
    2000: -0.091, 2001: -0.1189, 2002: -0.221, 2003: 0.2868, 2004: 0.1088,
    2005: 0.0491, 2006: 0.1579, 2007: 0.0549, 2008: -0.37, 2009: 0.2646,
    2010: 0.1506, 2011: 0.0211, 2012: 0.16, 2013: 0.3239, 2014: 0.1369,
    2015: 0.0138, 2016: 0.1196, 2017: 0.2183, 2018: -0.0438, 2019: 0.3149,
    2020: 0.184, 2021: 0.2871, 2022: -0.1811, 2023: 0.2629, 2024: 0.2502,
    2025: 0.1788, 2026: 0.1338,
}

_LAST_RECORDED_YEAR = max(_SP500_ANNUAL_RETURNS)  # 2026 as of this writing

_LONG_RUN_AVERAGE_RETURN = 0.10  # placeholder for any year not on record yet


HISTORICAL_STRESS_SCENARIOS: tuple[tuple[str, int | None], ...] = (
    ("Great Depression (1929)", 1929),
    ("Dot-com Crash (2000)", 2000),
    ("Global Financial Crisis (2007)", 2007),
    ("Stagflation (1973)", 1973),
    ("No-crash baseline (10%/yr)", None),
)



def _historical_return(start_year: int | None, offset: int) -> float:
    """The return a scenario applies `offset` years after its own start
    (offset 0 = the scenario's first year) -- the no-crash baseline
    (start_year=None) is just a flat _LONG_RUN_AVERAGE_RETURN every
    year; a named crash looks up the real historical year it's
    replaying (start_year + offset) and falls back to that same flat
    average once it runs past recorded history."""
    if start_year is None:
        return _LONG_RUN_AVERAGE_RETURN
    return _SP500_ANNUAL_RETURNS.get(start_year + offset, _LONG_RUN_AVERAGE_RETURN)



def run_historical_stress_test(
    *, starting_balance: float, expenses: list, assumptions: dict, income: list | None = None, pools: dict | None = None,
) -> dict:
    """Deterministic counterpart to run_simulation() above: instead of
    `iterations` random draws, replays each named historical crash
    sequence exactly once, starting at the plan's first year, against
    the same starting balance and the same per-year withdrawal need
    (annual_expense_need, net of annual_income_need -- see run_simulation)
    -- so every scenario faces an identical withdrawal schedule and only
    the return sequence differs, same "not re-solved dynamically"
    comparability rule the original workbook's note called out.

    `pools` is None by default, running the single-balance model exactly
    as before (unchanged). Passed a {"tax_deferred", "roth", "taxable"}
    dict, it engages the three-pool withdrawal/RMD/tax engine -- but
    unlike run_simulation/run_historical_bootstrap_simulation, tax and
    total withdrawal genuinely become PER-SCENARIO here rather than
    shared across every scenario: an RMD depends on that scenario's own
    running tax-deferred balance, which depends on that scenario's own
    historical return sequence, so two scenarios facing the identical
    yearly *need* can still owe different tax and withdraw different
    total amounts. The result's `per_scenario_tax` flag tells a caller
    (see source.webapp.pages.monte_carlo_page._historical_stress_test_html)
    which shape to expect: False means the shared top-level yearly_tax/
    yearly_total_withdrawal lists apply to every scenario (legacy mode);
    True means those top-level lists are None and each scenario dict
    carries its own yearly_tax/yearly_total_withdrawal/yearly_rmd
    instead. yearly_needs/yearly_income/yearly_total_expense stay
    shared either way -- none of those three depend on pool balances."""
    horizon = max(1, int(float(assumptions.get("plan_horizon_years") or 40)))
    inflation_rate = float(assumptions.get("inflation_rate") or 0.0)
    income_offset = float(assumptions.get("annual_income_offset") or 0)
    apply_drawdown_tax = _truthy_assumption(assumptions, "apply_drawdown_tax")
    income = income or []
    current_year_raw = assumptions.get("current_year")
    current_year = int(current_year_raw) if current_year_raw not in (None, "") else date.today().year
    years = [current_year + i for i in range(horizon)]
    # Same idea, but just the Income-tab side of that subtraction --
    # exposed on its own so a caller can show income right alongside
    # Yearly Drawdown (need = expenses - income - offset), rather than
    # only the already-netted figure.
    yearly_income = [annual_income_need(income, year, inflation_rate) for year in years]
    # Ordinary taxable income under each year's withdrawal -- see
    # withdrawal.annual_taxable_income (pools mode only).
    yearly_taxable_income = [
        annual_taxable_income(income, year, inflation_rate, _resolve_rental_taxable_fraction(assumptions, year))
        for year in years
    ]
    # And the Expense-tab side on its own too -- the un-netted "Total
    # Expense" a caller can show right next to Total Income (both are the
    # two raw, un-netted tab totals) so Total Expense - Total Income
    # (- the flat offset, if any) can be checked against Yearly Drawdown
    # directly: yearly_total_expense[i] - yearly_income[i] - offset ==
    # yearly_needs[i], every year.
    yearly_total_expense = [annual_expense_need(expenses, year, inflation_rate) for year in years]
    retirement_year = _resolve_retirement_year(assumptions)

    if pools is None:
        # Scenario/return-independent -- the same withdrawal schedule every
        # scenario below faces, so it's computed once per year rather than
        # once per (scenario, year) pair, and handed back as its own lists
        # (aligned with `years`) for a caller that wants to show them
        # directly, e.g. the Monte Carlo tab's Yearly Drawdown/Tax columns.
        # (yearly_total_withdrawal[i] is yearly_needs[i] plus that year's
        # estimated drawdown tax -- the amount actually subtracted from
        # the balance below.)
        schedule = yearly_withdrawal_schedule(
            expenses, income, years, inflation_rate, income_offset, apply_drawdown_tax, retirement_year,
        )
        yearly_needs = schedule["needs"]
        yearly_tax = schedule["taxes"]
        yearly_total_withdrawal = schedule["totals"]

        scenarios = []
        for label, start_year in HISTORICAL_STRESS_SCENARIOS:
            balance = max(starting_balance, 0.0)
            depleted = False
            depleted_year = None
            path = []
            for offset, year in enumerate(years):
                r = _historical_return(start_year, offset)
                balance = balance * (1 + r)
                balance -= yearly_total_withdrawal[offset]
                if balance < 0:
                    balance = 0.0
                    if not depleted:
                        depleted, depleted_year = True, year
                path.append({"year": year, "return": r, "balance": balance})
            scenarios.append({
                "label": label,
                "start_year": start_year,
                "path": path,
                "depleted": depleted,
                "depleted_year": depleted_year,
                "ending_balance": path[-1]["balance"] if path else max(starting_balance, 0.0),
            })
    else:
        # yearly_needs is still shared/scenario-independent (it doesn't
        # depend on returns or pool balances at all), but tax and total
        # withdrawal are not -- see the docstring above.
        yearly_needs = [
            annual_net_withdrawal_need(expenses, income, year, inflation_rate, income_offset, retirement_year)
            for year in years
        ]
        yearly_tax = None
        yearly_total_withdrawal = None
        birth_year = _resolve_birth_year(assumptions)
        gains_fraction = _resolve_gains_fraction(assumptions)

        scenarios = []
        for label, start_year in HISTORICAL_STRESS_SCENARIOS:
            scen_pools = {
                "tax_deferred": pools.get("tax_deferred", 0.0),
                "roth": pools.get("roth", 0.0),
                "taxable": pools.get("taxable", 0.0),
                "real_estate": pools.get("real_estate", 0.0),
            }
            owners = new_owner_state(scen_pools["tax_deferred"], assumptions)
            depleted = False
            depleted_year = None
            path = []
            scen_tax = []
            scen_total_withdrawal = []
            scen_rmd = []
            for offset, year in enumerate(years):
                r = _historical_return(start_year, offset)
                for name in scen_pools:
                    scen_pools[name] *= (1 + r)
                age = (year - birth_year) if birth_year is not None else None
                year_result = _apply_year_withdrawal(
                    scen_pools, need=yearly_needs[offset], age=age, birth_year=birth_year, gains_fraction=gains_fraction,
                    year=year, inflation_rate=inflation_rate, apply_drawdown_tax=apply_drawdown_tax, owners=owners,
                    base_ordinary_income=yearly_taxable_income[offset],
                )
                scen_tax.append(year_result["tax"])
                scen_rmd.append(year_result["rmd"])
                scen_total_withdrawal.append(yearly_needs[offset] + year_result["tax"])
                if year_result["shortfall"] > 1e-6 and not depleted:
                    depleted, depleted_year = True, year
                path.append({"year": year, "return": r, "balance": sum(scen_pools.values())})
            scenarios.append({
                "label": label,
                "start_year": start_year,
                "path": path,
                "depleted": depleted,
                "depleted_year": depleted_year,
                "ending_balance": path[-1]["balance"] if path else sum(scen_pools.values()),
                "yearly_tax": scen_tax,
                "yearly_total_withdrawal": scen_total_withdrawal,
                "yearly_rmd": scen_rmd,
            })

    return {
        "years": years,
        "retirement_year": retirement_year,
        "yearly_needs": yearly_needs,
        "yearly_tax": yearly_tax,
        "yearly_total_withdrawal": yearly_total_withdrawal,
        "yearly_income": yearly_income,
        "yearly_total_expense": yearly_total_expense,
        "scenarios": scenarios,
        "starting_balance": starting_balance,
        "last_recorded_year": _LAST_RECORDED_YEAR,
        "apply_drawdown_tax": apply_drawdown_tax,
        "per_scenario_tax": pools is not None,
    }
