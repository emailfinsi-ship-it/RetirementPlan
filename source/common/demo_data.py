"""A built-in sample household, for demos, screenshots and first-time
exploration. Every row it adds carries source="sample" so it can be
removed in one click without touching anything the user typed in.

Two ways to use it: the setup wizard's "Load sample household" button
(only offered on an empty install), and demo mode -- start the app with
FINSI_DEMO=1 (scripts/run_demo.sh) and it runs against its own throwaway
data folder, with no login and no connection to the real database.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

from source.common import db

SAMPLE_SOURCE = "sample"
_SECTIONS = ("assets", "real_estate", "expenses", "income")


def demo_mode() -> bool:
    return os.environ.get("FINSI_DEMO") == "1"


def has_sample_data() -> bool:
    return any(r.get("source") == SAMPLE_SOURCE for section in _SECTIONS for r in db.list_line_items(section))


def seed_sample_household(*, with_history: bool = False) -> None:
    """Adds the sample household. Safe to call twice (no-op when sample rows exist).
    with_history also writes a year of fake net-worth snapshots -- only for the
    throwaway demo database, since those could not be cleanly removed later."""
    if has_sample_data():
        return
    year = date.today().year
    db.set_household(self_name="Alex", spouse_name="Sam", has_spouse=True)
    db.set_assumptions({
        "birth_year": str(year - 58), "spouse_birth_year": str(year - 56), "retirement_year": str(year + 5),
        "expected_return": "0.06", "return_volatility": "0.12", "inflation_rate": "0.03", "plan_horizon_years": "40",
    })

    def asset(kind, category, name, balance, treatment, owner, institution):
        db.add_line_item("assets", {
            "kind": kind, "category": category, "name": name, "balance": balance, "tax_treatment": treatment,
            "owner": owner, "institution": institution, "include_in_monte_carlo": 1, "source": SAMPLE_SOURCE,
        })

    asset("asset", "401k / IRA", "Alex 401(k)", 1_180_000, "tax_deferred", "self", "Sample Brokerage")
    asset("asset", "401k / IRA", "Sam IRA", 620_000, "tax_deferred", "spouse", "Sample Brokerage")
    asset("asset", "401k / IRA", "Alex Roth IRA", 310_000, "roth", "self", "Sample Brokerage")
    asset("asset", "Liquid Assets", "Joint brokerage", 940_000, "taxable", "self", "Sample Brokerage")
    asset("asset", "Liquid Assets", "Savings", 180_000, "taxable", "spouse", "Sample Bank")
    db.add_line_item("real_estate", {
        "name": "Primary home", "current_value": 1_250_000, "purchase_price": 700_000, "ownership_pct": 100,
        "loan_balance": 310_000, "loan_end_year": year + 14, "source": SAMPLE_SOURCE,
    })
    for name, category, amount in (("Housing", "Fixed", 54_000), ("Food", "Variable", 18_000),
                                   ("Healthcare", "Variable", 14_000), ("Travel", "Variable", 20_000)):
        db.add_line_item("expenses", {
            "name": name, "category": category, "annual_amount": amount, "inflates": 1, "base_year": year,
            "source": SAMPLE_SOURCE,
        })
    db.add_line_item("income", {
        "name": "Social Security (Alex)", "category": "Social Security", "annual_amount": 36_000,
        "start_year": year + 8, "inflates": 1, "base_year": year, "include_in_monte_carlo": 1, "source": SAMPLE_SOURCE,
    })
    db.add_line_item("income", {
        "name": "Social Security (Sam)", "category": "Social Security", "annual_amount": 24_000,
        "start_year": year + 8, "inflates": 1, "base_year": year, "include_in_monte_carlo": 1, "source": SAMPLE_SOURCE,
    })
    if not with_history:
        return
    # A believable history so the "over time" chart has a trend to show.
    total_now = 3_230_000 + 940_000
    for weeks_ago in range(52, -1, -4):
        growth = 1.0 - 0.11 * (weeks_ago / 52) + (0.012 if weeks_ago % 8 == 0 else -0.006) * (weeks_ago / 52)
        nw = total_now * growth
        db.record_snapshot(
            net_worth=nw, manual_asset_total=nw - 940_000 * growth, linked_asset_total=0.0, liability_total=0.0,
            real_estate_equity_total=940_000 * growth, retirement_liquid_total=3_230_000 * growth,
            snapshot_date=(date.today() - timedelta(weeks=weeks_ago)).isoformat(),
        )


def remove_sample_data() -> int:
    """Deletes every row seeded above. Returns how many were removed."""
    removed = 0
    for section in _SECTIONS:
        for row in db.list_line_items(section):
            if row.get("source") == SAMPLE_SOURCE and db.delete_line_item(section, row["id"]):
                removed += 1
    return removed
