"""Keep-vs-Sell comparisons for the real estate liquidation what-if, one
per tab that shows it: Monte Carlo, Drawdown Planning and Legacy
Planning. Each takes the Keep numbers the tab already computed, runs the
same engine again on the Sell inputs (real_estate_sale.apply_sale), and
returns the row dicts sale_cards.comparison_rows_html lays out.

"Total" rows add the equity of properties that are NOT already inside the
simulated pools (the default -- a property only joins the Real-estate
pool when its "In Monte Carlo?" box is ticked) to the Keep side, so Keep
and Sell are compared on total wealth rather than on liquid money alone.
"""

from __future__ import annotations

import random

from source.reporting.monte_carlo.drawdown_schedule import deterministic_drawdown_schedule
from source.reporting.monte_carlo.legacy_planning import compare_roth_conversion_strategies
from source.reporting.monte_carlo.real_estate_sale import apply_sale, property_equity_at
from source.reporting.monte_carlo.simulation import run_historical_bootstrap_simulation, run_simulation

HIGHER, LOWER = "higher", "lower"


def _outside_pool_equity(sale: dict, real_estate: list, loan_balances: dict, assumptions: dict, year: int) -> float:
    """Equity at `year` of kept properties that are not already in the
    Real-estate pool."""
    if not sale.get("has_properties"):
        return 0.0
    return sum(
        p["equity"] for p in property_equity_at(real_estate, loan_balances, assumptions, year) if not p["opted_in"]
    )


def monte_carlo_sale_comparison(
    *, keep: dict, keep_bootstrap: dict | None, starting_balance: float, expenses: list, income: list,
    assumptions: dict, pools: dict, sale: dict, real_estate: list, loan_balances: dict, seed: int,
) -> list[dict]:
    """`keep` / `keep_bootstrap` are the Monte Carlo tab's own Gaussian /
    S&P-bootstrap results. The Sell runs reuse the same random seeds, so
    both sides face identical market paths and the difference is the sale
    alone."""
    sell_pools, sell_income, sell_assumptions = apply_sale(pools=pools, income=income, assumptions=assumptions, sale=sale)
    sell_start = sum(sell_pools.values())
    sell = run_simulation(
        starting_balance=sell_start, expenses=expenses, assumptions=sell_assumptions, income=sell_income,
        rng=random.Random(seed), pools=sell_pools,
    )
    sell_bootstrap = None
    if keep_bootstrap is not None:
        sell_bootstrap = run_historical_bootstrap_simulation(
            starting_balance=sell_start, expenses=expenses, assumptions=sell_assumptions, income=sell_income,
            rng=random.Random(seed ^ 0x5DEECE66D), pools=sell_pools,
        )
    s = sale["settings"]
    keep_outside = _outside_pool_equity(sale, real_estate, loan_balances, assumptions, s["horizon_end_year"])
    immediate = s["sale_year"] <= s["current_year"]
    rows = [
        {"label": "Starting liquid resources", "keep": sum(pools.values()), "sell": sell_start, "better": HIGHER},
    ]
    if not immediate:
        rows.append({"label": f"Sale proceeds invested in {s['sale_year']}", "keep": 0.0, "sell": sale["net_proceeds"], "better": HIGHER})
    rows += [
        {"label": "Success rate (random returns)", "kind": "pct", "keep": keep["success_rate"], "sell": sell["success_rate"], "better": HIGHER, "strong": True},
    ]
    if sell_bootstrap is not None:
        rows.append({"label": "Success rate (S&P 500 history)", "kind": "pct", "keep": keep_bootstrap["success_rate"], "sell": sell_bootstrap["success_rate"], "better": HIGHER})
    rows += [
        {"label": "Median ending liquid balance", "keep": keep["median_ending_balance"], "sell": sell["median_ending_balance"], "better": HIGHER},
        {"label": "10th percentile ending liquid balance", "keep": keep["p10_ending_balance"], "sell": sell["p10_ending_balance"], "better": HIGHER},
        {"label": f"Property equity if kept, in {s['horizon_end_year']} (not in the simulation)", "keep": keep_outside, "sell": 0.0, "better": None},
        {"label": "Median ending total incl. property", "keep": keep["median_ending_balance"] + keep_outside, "sell": sell["median_ending_balance"], "better": HIGHER, "strong": True},
        {"label": "Typical total tax paid over the plan", "keep": keep["yearly_tax_total"], "sell": sell["yearly_tax_total"], "better": LOWER},
    ]
    return rows


def drawdown_sale_comparison(
    *, keep_schedule: dict, pools: dict, expenses: list, income: list, assumptions: dict, sale: dict,
    real_estate: list, loan_balances: dict,
) -> list[dict]:
    """Rows for the Drawdown Planning tab. `keep_schedule` is that tab's
    own deterministic_drawdown_schedule result."""
    sell_pools, sell_income, sell_assumptions = apply_sale(pools=pools, income=income, assumptions=assumptions, sale=sale)
    sell_schedule = deterministic_drawdown_schedule(
        pools=sell_pools, expenses=expenses, income=sell_income, assumptions=sell_assumptions,
    )
    s = sale["settings"]
    immediate = s["sale_year"] <= s["current_year"]

    def depletion_year(schedule):
        for r in schedule["rows"]:
            if r["shortfall"] > 1e-6:
                return r["year"]
        return None

    def depletion_text(schedule):
        year = depletion_year(schedule)
        return "Never" if year is None else str(year)

    def tax_total(schedule):
        return sum(r["tax"] for r in schedule["rows"])

    def balance_at(schedule, year):
        for r in schedule["rows"]:
            if r["year"] == year:
                return r["total"]
        return schedule["rows"][-1]["total"] if schedule["rows"] else 0.0

    retirement_year = keep_schedule.get("retirement_year")
    first_year = keep_schedule["rows"][0]["year"] if keep_schedule["rows"] else s["current_year"]
    checkpoint_year = retirement_year if retirement_year is not None and retirement_year >= first_year else first_year
    keep_outside_now = _outside_pool_equity(sale, real_estate, loan_balances, assumptions, s["current_year"])
    keep_outside_end = _outside_pool_equity(sale, real_estate, loan_balances, assumptions, s["horizon_end_year"])
    keep_end = keep_schedule["rows"][-1]["total"] if keep_schedule["rows"] else 0.0
    sell_end = sell_schedule["rows"][-1]["total"] if sell_schedule["rows"] else 0.0
    keep_start = sum(pools.values())
    sell_start = sum(sell_pools.values())
    rows = [
        {"label": "Liquid savings today", "keep": keep_start, "sell": sell_start, "better": HIGHER},
    ]
    if not immediate:
        rows.append({"label": f"Sale proceeds added in {s['sale_year']}", "keep": 0.0, "sell": sale["net_proceeds"], "better": HIGHER})
    rows += [
        {"label": "Property equity today (outside the pools)", "keep": keep_outside_now, "sell": 0.0, "better": None},
        {"label": "Total savings today incl. property", "keep": keep_start + keep_outside_now,
         # Until a future sale year nothing has changed yet: the properties are still owned.
         "sell": sell_start if immediate else keep_start + keep_outside_now,
         "better": HIGHER, "strong": True},
        {"label": f"Rental income lost per year from {s['sale_year']}", "kind": "text", "keep": "$0", "sell": f"-${sale['rent_lost']:,.0f}"},
        {"label": f"Liquid balance in {checkpoint_year}" + (" (your retirement year)" if checkpoint_year == retirement_year else ""),
         "keep": balance_at(keep_schedule, checkpoint_year), "sell": balance_at(sell_schedule, checkpoint_year), "better": HIGHER},
        {"label": f"Liquid balance at the end ({s['horizon_end_year']})", "keep": keep_end, "sell": sell_end, "better": HIGHER},
        {"label": "Property equity if kept, at the end", "keep": keep_outside_end, "sell": 0.0, "better": None},
        {"label": "Total savings at the end incl. property", "keep": keep_end + keep_outside_end, "sell": sell_end, "better": HIGHER, "strong": True},
        {"label": "Total tax over the plan", "keep": tax_total(keep_schedule), "sell": tax_total(sell_schedule), "better": LOWER},
        {"label": "Year liquid savings run out", "kind": "text", "keep": depletion_text(keep_schedule), "sell": depletion_text(sell_schedule)},
    ]
    return rows


def legacy_sale_comparison(
    *, keep_result: dict, pools: dict, expenses: list, income: list, assumptions: dict, sale: dict,
    real_estate: list, loan_balances: dict,
) -> list[dict]:
    """Rows for the Legacy Planning tab, comparing the "no conversions"
    baseline (your current plan) of the Keep result against the same
    baseline run on the Sell inputs. `keep_result` is
    compare_roth_conversion_strategies' own result."""
    sell_pools, sell_income, sell_assumptions = apply_sale(pools=pools, income=income, assumptions=assumptions, sale=sale)
    sell_result = compare_roth_conversion_strategies(
        pools=sell_pools, expenses=expenses, assumptions=sell_assumptions, income=sell_income,
    )

    def baseline(result):
        return next(r for r in result["strategies"] if r["key"] == result["baseline_key"])

    keep_b, sell_b = baseline(keep_result), baseline(sell_result)
    s = sale["settings"]
    death_year = keep_result.get("death_year", s["horizon_end_year"])
    keep_outside = _outside_pool_equity(sale, real_estate, loan_balances, assumptions, death_year)
    return [
        {"label": "Liquid savings left, before heir tax", "keep": keep_b["ending_total"], "sell": sell_b["ending_total"], "better": HIGHER},
        {"label": "Estimated tax your heir owes on the Tax-deferred balance", "keep": keep_b["estimated_heir_tax"], "sell": sell_b["estimated_heir_tax"], "better": LOWER},
        {"label": "After-tax liquid legacy", "keep": keep_b["net_after_tax_legacy"], "sell": sell_b["net_after_tax_legacy"], "better": HIGHER},
        {"label": f"Property equity passed on if kept, {death_year} (heirs get a stepped-up basis)", "keep": keep_outside, "sell": 0.0, "better": None},
        {"label": "Total legacy incl. property", "keep": keep_b["net_after_tax_legacy"] + keep_outside, "sell": sell_b["net_after_tax_legacy"], "better": HIGHER, "strong": True},
        {"label": "Tax you pay over the plan", "keep": keep_b["total_lifetime_tax"], "sell": sell_b["total_lifetime_tax"], "better": LOWER},
    ]
