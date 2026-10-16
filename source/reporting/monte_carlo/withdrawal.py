"""Expense/income line-item math: a single row's effective dollar
amount in a given year (flat, or inflated from its base_year), summed
across a section's rows for that year, and netted (Expense - Income -
flat offset) into the year's actual withdrawal need. Shared by every
simulation method in this package (simulation.py, stress_test.py) so
"what does this plan need to withdraw in year Y" is computed exactly
the same way everywhere it's asked.
"""

from __future__ import annotations

from source.reporting.monte_carlo.tax import estimate_annual_drawdown_tax


def effective_line_item_amount(row: dict, year: int, inflation_rate: float) -> float:
    """A single expense/income row's dollar amount in `year`: flat
    (annual_amount as typed) unless the row has inflates set AND a
    base_year -- then it grows from base_year to `year` by
    inflation_rate, compounded annually. Matches the original workbook's
    "(2026 basis)" budget table, whose Fixed/Variable cost rows all grow
    by a single inflation assumption every simulated year."""
    amount = row.get("annual_amount") or 0.0
    base_year = row.get("base_year")
    if row.get("inflates") and base_year is not None:
        amount *= (1 + inflation_rate) ** (year - int(base_year))
    return amount


# Share of Social Security benefits that is federally taxable at the income
# levels this plan models (IRS caps it at 85%; reaching it requires combined
# income of roughly $44K for a joint return, which any retiree with a
# six-figure withdrawal need is past).
SOCIAL_SECURITY_TAXABLE_FRACTION = 0.85


def _amount_in_year(row: dict, year: int, inflation_rate: float) -> float:
    """A row's dollar amount in `year` -- 0.0 outside its start_year/
    end_year range, otherwise effective_line_item_amount."""
    start = row.get("start_year")
    end = row.get("end_year")
    if start is not None and year < start:
        return 0.0
    if end is not None and year > end:
        return 0.0
    return effective_line_item_amount(row, year, inflation_rate)


def annual_line_item_total(rows: list, year: int, inflation_rate: float = 0.0) -> float:
    """The building block behind annual_expense_need/annual_income_need,
    exposed directly for a caller (the Expense tab's own table totals)
    that needs a section-agnostic "what does this list of rows add up to
    in `year`, honoring each row's year range and inflation" -- both a
    Fixed/Variable expense row and a Rental/Social Security income row
    use the exact same rule, just netted in opposite directions by
    run_simulation/run_historical_stress_test."""
    return sum(_amount_in_year(row, year, inflation_rate) for row in rows)


def annual_expense_need(expenses: list, year: int, inflation_rate: float = 0.0) -> float:
    """Sums every expense line item that covers `year`: a row with both
    start_year and end_year set only applies within that range (e.g. an
    imported "Year 2031" drawdown-ledger row, start=end=2031); a row with
    neither set is treated as recurring every simulated year (e.g. a
    hand-added "Healthcare" line with no year range). A row with
    inflates set grows from its own base_year by inflation_rate first
    (see effective_line_item_amount) -- inflation_rate defaults to 0.0
    so a caller that doesn't pass one (or a row with inflates unset)
    keeps behaving exactly as a flat annual_amount."""
    return annual_line_item_total(expenses, year, inflation_rate)


def annual_income_need(income: list, year: int, inflation_rate: float = 0.0) -> float:
    """Same rules as annual_expense_need, for income line items (rental,
    Social Security, a pension, ...) that offset the withdrawal need --
    see run_simulation / run_historical_stress_test, which subtract this
    from annual_expense_need's result for the same year."""
    return annual_line_item_total(income, year, inflation_rate)


def annual_taxable_income(income: list, year: int, inflation_rate: float = 0.0) -> float:
    """The part of `year`'s Income-tab total that is ordinary taxable
    income: every row in full (rental, pension, ...) except Social
    Security, of which only SOCIAL_SECURITY_TAXABLE_FRACTION counts.
    The three-pool engine stacks a year's withdrawals on top of this
    figure when it works out their tax (pools._apply_year_withdrawal's
    base_ordinary_income) -- without it every withdrawal would be taxed as
    if it were the household's only income, understating the bracket it
    actually lands in whenever rent or benefits are also coming in. (Tax
    on the income itself is not modeled: the Income tab's figures are
    treated as already net of it, exactly as they always were.)"""
    total = 0.0
    for row in income:
        amount = _amount_in_year(row, year, inflation_rate)
        if "social security" in f"{row.get('category') or ''} {row.get('name') or ''}".lower():
            amount *= SOCIAL_SECURITY_TAXABLE_FRACTION
        total += amount
    return total


def annual_income_breakdown(income: list, year: int, inflation_rate: float = 0.0) -> dict:
    """`year`'s Income-tab total split into {"rental", "social_security",
    "other"} (a row counts as Social Security when its category or name
    says so, as rental when it says "rent", otherwise other) -- for the
    Drawdown tab's year-by-year table, so a person can see how much of
    each year's spending these cover before anything is drawn from the
    portfolio. The three always add up to annual_income_need's total."""
    parts = {"rental": 0.0, "social_security": 0.0, "other": 0.0}
    for row in income:
        label = f"{row.get('category') or ''} {row.get('name') or ''}".lower()
        key = "social_security" if "social security" in label else "rental" if "rent" in label else "other"
        parts[key] += _amount_in_year(row, year, inflation_rate)
    return parts


def annual_net_withdrawal_need(
    expenses: list, income: list, year: int, inflation_rate: float = 0.0, income_offset: float = 0.0,
    retirement_year: int | None = None,
) -> float:
    """The dollar amount a plan actually needs to withdraw for `year`:
    that year's inflation-adjusted Expense total minus its
    inflation-adjusted Income total minus the flat Annual income offset
    assumption -- the exact "need" every simulated year subtracts from
    the balance, in run_simulation, run_historical_bootstrap_simulation,
    and run_historical_stress_test alike. Exposed on its own so a caller
    that just wants the year-by-year withdrawal schedule itself (e.g.
    the Monte Carlo tab's Yearly Drawdown column) doesn't have to run a
    full simulation to get it -- it's scenario/return-independent, so it
    only needs to be computed once per year, not once per path.

    `retirement_year` (the "Retirement year" assumption --
    source.reporting.monte_carlo.assumptions._resolve_retirement_year)
    is None by default, leaving every existing caller that doesn't pass
    it byte-for-byte unchanged. Passed an actual year, any `year` before
    it returns 0.0 outright -- no portfolio withdrawal at all pre-
    retirement, on the assumption that while still working, income
    covers expenses (the Expense/Income tabs' own totals for those years
    are simply not consulted, rather than netted and possibly landing on
    a small positive number). RMDs are a separate mechanism
    (source.reporting.monte_carlo.pools._apply_year_withdrawal) and are
    NOT gated by this -- the IRS doesn't care whether you've retired."""
    if retirement_year is not None and year < retirement_year:
        return 0.0
    return (
        annual_expense_need(expenses, year, inflation_rate)
        - annual_income_need(income, year, inflation_rate)
        - income_offset
    )


def yearly_withdrawal_schedule(
    expenses: list, income: list, years: list, inflation_rate: float = 0.0, income_offset: float = 0.0,
    apply_drawdown_tax: bool = True, retirement_year: int | None = None,
) -> dict:
    """The full year-by-year withdrawal picture for a plan horizon,
    shared by every simulation method below (run_simulation,
    run_historical_bootstrap_simulation, run_historical_stress_test) so
    it's computed once per year, not once per (path, year) or
    (scenario, year) pair -- none of this depends on a path's random
    returns or a scenario's running balance, only on the year itself.
    Returns three parallel lists (one entry per `years`):
      needs  -- annual_net_withdrawal_need (Expense - Income - offset,
                0.0 for any year before `retirement_year`, if set)
      taxes  -- estimate_annual_drawdown_tax on that year's need (every
                entry 0.0 when apply_drawdown_tax is False, or when that
                year's need is already 0.0 pre-retirement)
      totals -- needs[i] + taxes[i]: the actual dollar amount every
                simulated year withdraws from the balance
    """
    needs = [
        annual_net_withdrawal_need(expenses, income, year, inflation_rate, income_offset, retirement_year)
        for year in years
    ]
    if apply_drawdown_tax:
        taxes = [estimate_annual_drawdown_tax(need, year, inflation_rate) for need, year in zip(needs, years)]
    else:
        taxes = [0.0 for _ in years]
    totals = [n + t for n, t in zip(needs, taxes)]
    return {"needs": needs, "taxes": taxes, "totals": totals}
