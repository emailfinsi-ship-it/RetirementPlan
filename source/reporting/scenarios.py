"""Saved scenarios: which assumptions a scenario holds, and the side-by-side
comparison. A scenario only varies the assumptions below -- the Asset,
Income and Expense tables are shared by every scenario, so "retire at 60
vs 65" or "6% vs 4% returns" compare like with like.

Each scenario is run twice, the same way the tabs do: the random Monte
Carlo simulation (seeded, so re-running gives the same numbers) and the
deterministic Drawdown schedule at the scenario's expected return.
"""

from __future__ import annotations

import random

from source.common import db
from source.reporting.monte_carlo import (
    deterministic_drawdown_schedule,
    run_simulation,
    stable_simulation_seed,
)

SCENARIO_KEYS = (
    "expected_return", "return_volatility", "inflation_rate", "plan_horizon_years", "iterations",
    "annual_income_offset", "birth_year", "spouse_birth_year", "retirement_year", "taxable_gains_fraction",
    "apply_drawdown_tax", "early_tax_deferred_age", "heir_type", "heir_base_income", "heir_spread_years",
    "re_sale_year", "re_selling_cost", "re_appreciation",
)


def snapshot_assumptions(assumptions: dict) -> dict:
    """The scenario-relevant, non-blank part of an assumptions dict."""
    return {k: assumptions[k] for k in SCENARIO_KEYS if assumptions.get(k) not in (None, "")}


def restore_scenario(scenario_id: int) -> bool:
    """Writes a saved scenario back as the current assumptions; scenario
    keys it doesn't hold are cleared so the result is exactly the saved
    one."""
    scenario = db.get_scenario(scenario_id)
    if not scenario:
        return False
    values = {k: "" for k in SCENARIO_KEYS}
    values.update({k: v for k, v in scenario["assumptions"].items() if k in SCENARIO_KEYS})
    db.set_assumptions(values)
    return True


def _run(summary: dict, overrides: dict) -> dict:
    assumptions = {**summary["assumptions"]}
    for key in SCENARIO_KEYS:
        assumptions.pop(key, None)
    assumptions.update(overrides)
    pools = summary["retirement_pools"]
    seed = stable_simulation_seed(
        starting_balance=summary["net_liquid_asset"], expenses=summary["expenses"],
        income=summary["income_for_simulation"], assumptions=assumptions, pools=pools,
    )
    mc = run_simulation(
        starting_balance=summary["net_liquid_asset"], expenses=summary["expenses"], assumptions=assumptions,
        income=summary["income_for_simulation"], pools=pools, rng=random.Random(seed),
    )
    dd = deterministic_drawdown_schedule(
        pools=summary["drawdown_pools"], expenses=summary["expenses"], income=summary["income_for_simulation"],
        assumptions=assumptions,
    )
    rows = dd["rows"]
    depleted = next((r["year"] for r in rows if r["shortfall"] > 1e-6), None)
    return {
        "success_rate": mc["success_rate"],
        "median_ending_balance": mc["median_ending_balance"],
        "p10_ending_balance": mc["p10_ending_balance"],
        "tax_total": mc["yearly_tax_total"],
        "drawdown_ending_total": rows[-1]["total"] if rows else 0.0,
        "drawdown_depleted_year": depleted,
        "drawdown_tax_total": sum(r["tax"] for r in rows),
    }


def compare_scenarios(summary: dict, scenarios: list[dict]) -> list[dict]:
    """[{"name", "current": bool, "assumptions", **results}] -- the plan as
    it is now first, then each saved scenario."""
    current = snapshot_assumptions(summary["assumptions"])
    out = [{"name": "Current plan", "current": True, "assumptions": current, **_run(summary, current)}]
    for sc in scenarios:
        overrides = {k: v for k, v in sc["assumptions"].items() if k in SCENARIO_KEYS}
        out.append({"id": sc["id"], "name": sc["name"], "current": False, "assumptions": overrides, **_run(summary, overrides)})
    return out
