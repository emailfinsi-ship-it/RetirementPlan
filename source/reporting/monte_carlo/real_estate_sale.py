"""The "what if I sold my real estate" scenario -- Keep vs. Sell.

Selling every property in one chosen year turns into three changes to a
plan's inputs, and nothing else about the engines needs to know a sale is
happening:

  * the net proceeds (sale price, minus the loan paid off, minus selling
    costs, minus an estimate of the tax on the gain) land in the Taxable
    pool -- at the start when the sale year is this year, otherwise as a
    one-time deposit in that year (see assumptions._resolve_taxable_deposit);
  * the Real-estate pool (equity of properties opted into the simulation)
    is emptied, since those properties are the ones being sold;
  * rental income stops from the sale year on.

`estimate_real_estate_sale` works out the proceeds; `apply_sale` returns
the (pools, income, assumptions) a Sell run feeds to the same engines the
Keep run uses. Keep and Sell are meant to be compared on total wealth, so
`property_equity_at` also reports what the properties would be worth if
kept (grown at the appreciation assumption, loan paid down per its
"Loan ends" year) -- otherwise Keep would look poorer simply because
unsold equity isn't in the liquid pools.

Deliberate simplifications (the Real Estate page says so too): gain =
sale price - selling costs - purchase price (no improvements, no
depreciation recapture, no primary-residence exclusion); a missing
purchase price means no gain tax is estimated; the loan pays down in a
straight line to its "Loan ends" year (a flat balance if none is set);
appreciation defaults to the Inflation assumption; the proceeds are taxed
like the rest of the Taxable pool when drawn later (the "Taxable gains %"
assumption), even though they are mostly already-taxed cash.
"""

from __future__ import annotations

import json
from datetime import date

from source.reporting.monte_carlo.assumptions import _resolve_rental_taxable_fraction
from source.reporting.monte_carlo.tax import _pool_year_tax
from source.reporting.monte_carlo.withdrawal import _income_kind, annual_income_breakdown, annual_taxable_income

DEFAULT_SELLING_COST = 0.06
NIIT_RATE = 0.038
NIIT_THRESHOLD_MFJ = 250_000.0   # statutory, not inflation-indexed


def _float(assumptions: dict, key: str, default: float | None) -> float | None:
    raw = assumptions.get(key)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _current_year(assumptions: dict) -> int:
    raw = assumptions.get("current_year")
    try:
        return int(float(raw)) if raw not in (None, "") else date.today().year
    except (TypeError, ValueError):
        return date.today().year


def sale_settings(assumptions: dict) -> dict:
    """{"sale_year", "selling_cost", "appreciation", "current_year",
    "horizon_end_year"} from the Real Estate tab's what-if form. A blank
    or past sale year means "this year"; blank appreciation means the
    Inflation assumption."""
    current_year = _current_year(assumptions)
    horizon = max(1, int(float(assumptions.get("plan_horizon_years") or 40)))
    sale_year = _float(assumptions, "re_sale_year", None)
    sale_year = current_year if sale_year is None else max(current_year, int(sale_year))
    selling_cost = _float(assumptions, "re_selling_cost", DEFAULT_SELLING_COST)
    selling_cost = min(0.5, max(0.0, selling_cost))
    appreciation = _float(assumptions, "re_appreciation", None)
    if appreciation is None:
        appreciation = float(assumptions.get("inflation_rate") or 0.0)
    return {
        "current_year": current_year, "sale_year": sale_year, "selling_cost": selling_cost,
        "appreciation": appreciation, "horizon_end_year": current_year + horizon - 1,
    }


def _loan_at(loan_now: float, loan_end_year, current_year: int, year: int) -> float:
    """The loan balance in `year`: straight-line to zero at `loan_end_year`
    when one is set, otherwise unchanged."""
    if not loan_end_year:
        return loan_now
    loan_end_year = int(loan_end_year)
    if year >= loan_end_year:
        return 0.0
    if loan_end_year <= current_year:
        return loan_now
    return loan_now * (loan_end_year - year) / (loan_end_year - current_year)


def income_after_sale(income: list, sale_year: int) -> list:
    """`income` with every rental row ending the year before the sale."""
    result = []
    for row in income:
        if _income_kind(row) == "rental":
            end = row.get("end_year")
            row = {**row, "end_year": sale_year - 1 if end is None else min(int(end), sale_year - 1)}
        result.append(row)
    return result


def property_equity_at(real_estate: list, loan_balances: dict, assumptions: dict, year: int) -> list[dict]:
    """Each property's [{"id", "name", "equity", "opted_in"}] in `year` if
    kept: the owned share of its appreciated value minus its remaining
    loan. `loan_balances` is {row id: current effective loan balance}."""
    s = sale_settings(assumptions)
    growth = (1.0 + s["appreciation"]) ** max(0, year - s["current_year"])
    out = []
    for r in real_estate:
        share = (r.get("ownership_pct") if r.get("ownership_pct") is not None else 100.0) / 100.0
        value = (r.get("current_value") or 0.0) * growth
        loan = _loan_at(loan_balances.get(r["id"], r.get("loan_balance") or 0.0), r.get("loan_end_year"),
                        s["current_year"], year)
        out.append({
            "id": r["id"], "name": r.get("name") or "(unnamed property)",
            "equity": share * (value - loan), "opted_in": bool(r.get("include_in_monte_carlo")),
        })
    return out


def estimate_real_estate_sale(*, real_estate: list, loan_balances: dict, assumptions: dict, income: list) -> dict:
    """What selling every property in the chosen year would net.

    Returns {"settings", "properties": [...per property...], "gross_value",
    "loan_payoff", "selling_costs", "gain", "gains_tax", "net_proceeds",
    "rent_lost" (the first sale-year's rental income that stops),
    "equity_today_not_in_pools", "has_properties", "missing_purchase_price"
    (names with no purchase price)}."""
    s = sale_settings(assumptions)
    sale_year, current_year = s["sale_year"], s["current_year"]
    inflation_rate = float(assumptions.get("inflation_rate") or 0.0)
    growth = (1.0 + s["appreciation"]) ** (sale_year - current_year)
    properties = []
    missing_purchase_price = []
    for r in real_estate:
        share = (r.get("ownership_pct") if r.get("ownership_pct") is not None else 100.0) / 100.0
        value = (r.get("current_value") or 0.0) * growth
        loan = _loan_at(loan_balances.get(r["id"], r.get("loan_balance") or 0.0), r.get("loan_end_year"),
                        current_year, sale_year)
        gross, payoff = share * value, share * loan
        costs = gross * s["selling_cost"]
        purchase = r.get("purchase_price") or 0.0
        if purchase > 0:
            gain = max(0.0, gross - costs - share * purchase)
        else:
            gain = 0.0
            missing_purchase_price.append(r.get("name") or "(unnamed property)")
        properties.append({
            "id": r["id"], "name": r.get("name") or "(unnamed property)", "gross_value": gross,
            "loan_payoff": payoff, "selling_costs": costs, "gain": gain, "gains_tax": 0.0,
            "net_proceeds": 0.0,
        })
    total_gain = sum(p["gain"] for p in properties)
    after_sale_income = income_after_sale(income, sale_year)
    base = annual_taxable_income(
        after_sale_income, sale_year, inflation_rate, _resolve_rental_taxable_fraction(assumptions, sale_year),
    )
    gains_tax = 0.0
    if total_gain > 0:
        gains_tax = _pool_year_tax(
            ordinary_income=0.0, gains_income=total_gain, year=sale_year, inflation_rate=inflation_rate,
            base_ordinary_income=base,
        )
        gains_tax += NIIT_RATE * min(total_gain, max(0.0, base + total_gain - NIIT_THRESHOLD_MFJ))
    for p in properties:
        p["gains_tax"] = gains_tax * (p["gain"] / total_gain) if total_gain > 0 else 0.0
        p["net_proceeds"] = p["gross_value"] - p["loan_payoff"] - p["selling_costs"] - p["gains_tax"]
    gross_value = sum(p["gross_value"] for p in properties)
    net = max(0.0, sum(p["net_proceeds"] for p in properties))
    rent_lost = annual_income_breakdown(income, sale_year, inflation_rate)["rental"]
    return {
        "settings": s,
        "properties": properties,
        "has_properties": bool(properties),
        "gross_value": gross_value,
        "loan_payoff": sum(p["loan_payoff"] for p in properties),
        "selling_costs": sum(p["selling_costs"] for p in properties),
        "gain": total_gain,
        "gains_tax": gains_tax,
        "net_proceeds": net,
        "rent_lost": rent_lost,
        "missing_purchase_price": missing_purchase_price,
    }


def apply_sale(*, pools: dict, income: list, assumptions: dict, sale: dict) -> tuple[dict, list, dict]:
    """The (pools, income, assumptions) of the Sell run -- see the module
    docstring. `sale` is estimate_real_estate_sale's result."""
    s = sale["settings"]
    sell_pools = {**pools, "real_estate": 0.0}
    sell_assumptions = dict(assumptions)
    if s["sale_year"] <= s["current_year"]:
        sell_pools["taxable"] = sell_pools.get("taxable", 0.0) + sale["net_proceeds"]
    elif sale["net_proceeds"] > 0:
        sell_assumptions["taxable_deposits"] = json.dumps({str(s["sale_year"]): sale["net_proceeds"]})
    return sell_pools, income_after_sale(income, s["sale_year"]), sell_assumptions
