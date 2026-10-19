"""Which account to take this year's money from -- and how much tax a smarter
split could save.

The usual rule is "spend your brokerage first, retirement accounts later".
But in a year when your other income is low, it can cost less tax to pull some
from the 401(k)/IRA, because that income fills up the cheap tax brackets that
would otherwise go unused. This tries every split for ONE year, using the
same tax tables as the rest of the plan, and reports the cheapest one next to
the usual order.

It looks at this year's tax only, and ignores future years (pulling more from
a 401(k)/IRA now also shrinks later forced withdrawals, which is often a plus
but is not counted). An estimate to discuss with a tax professional."""

from __future__ import annotations

import copy
from datetime import date

from source.reporting.monte_carlo.assumptions import (
    _resolve_birth_year,
    _resolve_gains_fraction,
    _resolve_rental_taxable_fraction,
    _resolve_retirement_year,
    _truthy_assumption,
)
from source.reporting.monte_carlo.pools import _apply_year_withdrawal, new_owner_state
from source.reporting.monte_carlo.tax import _pool_year_tax
from source.reporting.monte_carlo.withdrawal import annual_net_withdrawal_need, annual_taxable_income

MIN_SAVING = 200.0  # smaller than this is not worth a message
_STEPS = 80


def _split_for(target_td: float, total: float, avail: dict) -> dict:
    """Take `target_td` from tax-deferred (capped), then the rest from taxable, then Roth."""
    td = min(target_td, total, avail["tax_deferred"])
    rest = total - td
    tx = min(rest, avail["taxable"])
    roth = min(rest - tx, avail["roth"])
    return {"tax_deferred": td, "taxable": tx, "roth": roth}


def _solve(target_td: float, need_after_rmd: float, avail: dict, *, rmd: float, gains_fraction: float,
           year: int, inflation: float, base_income: float, apply_tax: bool) -> dict:
    """The split and tax for one choice of 'how much from tax-deferred'. Paying
    the tax is itself a withdrawal, so this repeats until the amounts settle."""
    tax = 0.0
    split = _split_for(target_td, need_after_rmd, avail)
    for _ in range(12 if apply_tax else 1):
        split = _split_for(target_td, need_after_rmd + tax, avail)
        if not apply_tax:
            break
        tax = _pool_year_tax(ordinary_income=rmd + split["tax_deferred"], gains_income=split["taxable"] * gains_fraction,
                             year=year, inflation_rate=inflation, base_ordinary_income=base_income)
    return {**split, "tax": tax}


def best_split_this_year(*, pools: dict, expenses: list, income: list, assumptions: dict, year: int | None = None) -> dict | None:
    """None when there is nothing to take out this year. Otherwise
    {"year", "need", "rmd", "base_income", "usual": {...}, "best": {...}, "saved"}
    where each split is {"tax_deferred", "taxable", "roth", "tax"} (dollars;
    "tax_deferred" here excludes the forced RMD, which is reported on its own)."""
    inflation = float(assumptions.get("inflation_rate") or 0.0)
    expected = float(assumptions.get("expected_return") or 0.06)
    offset = float(assumptions.get("annual_income_offset") or 0)
    raw_now = assumptions.get("current_year")
    this_year = int(raw_now) if raw_now not in (None, "") else date.today().year
    year = year or this_year
    retirement_year = _resolve_retirement_year(assumptions)
    need = annual_net_withdrawal_need(expenses, income or [], year, inflation, offset, retirement_year)
    grown = {k: float(pools.get(k, 0.0)) * (1 + expected) ** max(0, year - this_year + 1)
             for k in ("tax_deferred", "roth", "taxable")}
    apply_tax = _truthy_assumption(assumptions, "apply_drawdown_tax")
    gains_fraction = _resolve_gains_fraction(assumptions)
    birth_year = _resolve_birth_year(assumptions)
    age = (year - birth_year) if birth_year is not None else None
    base_income = annual_taxable_income(income or [], year, inflation, _resolve_rental_taxable_fraction(assumptions, year))

    # The forced withdrawal (RMD) does not depend on the choice, so read it off the shared engine.
    probe = _apply_year_withdrawal(
        copy.deepcopy({**grown, "real_estate": 0.0}), need=max(need, 0.0), age=age, birth_year=birth_year,
        gains_fraction=gains_fraction, year=year, inflation_rate=inflation, apply_drawdown_tax=False,
        owners=new_owner_state(grown["tax_deferred"], assumptions), base_ordinary_income=base_income)
    rmd = probe["rmd"]
    need_after_rmd = max(0.0, need - rmd)
    if need <= 0 and rmd <= 0:
        return None
    avail = {"tax_deferred": max(0.0, grown["tax_deferred"] - rmd), "taxable": grown["taxable"], "roth": grown["roth"]}
    common = dict(rmd=rmd, gains_fraction=gains_fraction, year=year, inflation=inflation, base_income=base_income, apply_tax=apply_tax)

    usual = _solve(0.0, need_after_rmd, avail, **common)
    ceiling = min(avail["tax_deferred"], need_after_rmd + usual["tax"] + 1.0)
    best = usual
    for i in range(1, _STEPS + 1):
        candidate = _solve(ceiling * i / _STEPS, need_after_rmd, avail, **common)
        if candidate["tax"] < best["tax"] - 1.0:
            best = candidate
    saved = usual["tax"] - best["tax"]
    return {"year": year, "need": need, "rmd": rmd, "base_income": base_income,
            "usual": usual, "best": best, "saved": max(0.0, saved), "apply_tax": apply_tax}
