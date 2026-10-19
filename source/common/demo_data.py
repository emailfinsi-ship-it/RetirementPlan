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


def seed_sample_household(*, with_history: bool = False, with_linked: bool = False) -> None:
    """Adds the sample household. Safe to call twice (no-op when sample rows exist).
    with_history also writes a year of fake net-worth snapshots -- only for the
    throwaway demo database, since those could not be cleanly removed later.
    with_linked also adds pretend linked accounts, holdings and a year of
    transactions (see seed_sample_linked_accounts) and ties the sample assets
    to them, so every tab has something to show without a Plaid connection."""
    if has_sample_data():
        if with_linked and not has_sample_linked():
            seed_sample_linked_accounts()
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
    if with_linked:
        seed_sample_linked_accounts()
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
    removed = remove_sample_linked_accounts()
    for section in _SECTIONS:
        for row in db.list_line_items(section):
            if row.get("source") == SAMPLE_SOURCE and db.delete_line_item(section, row["id"]):
                removed += 1
    return removed


# ---------------------------------------------------------------- linked test data
SAMPLE_ITEMS = ("sample_brokerage", "sample_bank")
_TXN_PREFIX = "smp-"
# (account_id, item, name, type, subtype, mask, balance)
_ACCOUNTS = (
    ("smp_401k", "sample_brokerage", "Alex 401(k)", "investment", "401k", "1101", 1_180_000.0),
    ("smp_ira", "sample_brokerage", "Sam IRA", "investment", "ira", "2202", 620_000.0),
    ("smp_roth", "sample_brokerage", "Alex Roth IRA", "investment", "roth", "3303", 310_000.0),
    ("smp_brok", "sample_brokerage", "Joint Brokerage", "investment", "brokerage", "4404", 940_000.0),
    ("smp_sav", "sample_bank", "Savings", "depository", "savings", "5505", 180_000.0),
    ("smp_chk", "sample_bank", "Checking", "depository", "checking", "6606", 14_500.0),
    ("smp_card", "sample_bank", "Rewards Card", "credit", "credit card", "7707", 3_200.0),
    ("smp_mort", "sample_bank", "Home Mortgage", "loan", "mortgage", "8808", 310_000.0),
)
# (account_id, security_id, ticker, name, type, value, cost_basis)
_HOLDINGS = (
    ("smp_401k", "smp-sp500", "SMPX", "Sample S&P 500 Index Fund", "mutual fund", 700_000, 420_000),
    ("smp_401k", "smp-bond", "SMPB", "Sample Total Bond Market Index", "mutual fund", 250_000, 240_000),
    ("smp_401k", "smp-tdf", "SMP35", "Sample Target Date 2035 Fund", "mutual fund", 130_000, 100_000),
    ("smp_401k", "smp-cash", "CUR:USD", "Cash", "cash", 100_000, 100_000),
    ("smp_ira", "smp-totstock", "SMPT", "Sample Total Stock Market ETF", "etf", 400_000, 250_000),
    ("smp_ira", "smp-aggbond", "SMPA", "Sample Aggregate Bond ETF", "etf", 150_000, 150_000),
    ("smp_ira", "smp-cash", "CUR:USD", "Cash", "cash", 70_000, 70_000),
    ("smp_roth", "smp-tech", "TECH", "Sample Tech Corp", "equity", 120_000, 30_000),
    ("smp_roth", "smp-semi", "CHIP", "Sample Semiconductor Inc", "equity", 90_000, 40_000),
    ("smp_roth", "smp-growth", "SMPG", "Sample Growth ETF", "etf", 100_000, 60_000),
    ("smp_brok", "smp-tech", "TECH", "Sample Tech Corp", "equity", 300_000, 90_000),
    ("smp_brok", "smp-banks", "BANK", "Sample Bank Corp", "equity", 150_000, 110_000),
    ("smp_brok", "smp-energy", "ENRG", "Sample Energy Co", "equity", 100_000, 95_000),
    ("smp_brok", "smp-sp500", "SMPX", "Sample S&P 500 Index Fund", "mutual fund", 250_000, 170_000),
    ("smp_brok", "smp-mm", "SMPM", "Sample Money Market Fund", "cash", 160_000, 160_000),
    ("smp_brok", "smp-margin", "CUR:USD", "Cash (margin debit)", "cash", -20_000, -20_000),
)
_INDUSTRIES = {
    "smp-tech": "Consumer Electronics", "smp-semi": "Semiconductors", "smp-banks": "Banks - Diversified",
    "smp-energy": "Oil & Gas Integrated", "smp-bond": "Bond", "smp-aggbond": "Bond",
}
# Deliberately wrong, so the Data check card has something real to show.
_MISTAGGED = {"smp-sp500": "International"}


def has_sample_linked() -> bool:
    return any(i.get("item_key") in SAMPLE_ITEMS for i in db.list_plaid_items())


def seed_sample_linked_accounts() -> None:
    """Pretend Plaid accounts, holdings and 12 months of transactions for the
    sample household (environment "sample": the real sync skips them).
    The numbers add up to the sample assets, which are linked to them so
    nothing is counted twice. A negative cash line and a mis-tagged fund are
    left in on purpose to demonstrate the Data check card."""
    if has_sample_linked():
        return
    now = date.today().isoformat()
    for key, name, inst in (("sample_brokerage", "Sample Brokerage", "ins_sample_1"), ("sample_bank", "Sample Bank", "ins_sample_2")):
        db.upsert_plaid_item(
            item_key=key, plaid_item_id=f"{key}-id", institution_id=inst, institution_name=name,
            products=["investments", "transactions"], environment="sample", linked_at=now,
        )
    for account_id, item, name, kind, subtype, mask, balance in _ACCOUNTS:
        db.upsert_plaid_account(item_key=item, account={
            "account_id": account_id, "name": name, "official_name": name, "type": kind, "subtype": subtype,
            "mask": mask, "balances": {"current": balance, "available": balance, "iso_currency_code": "USD"},
        })
    for account_id, sid, ticker, name, kind, value, basis in _HOLDINGS:
        db.upsert_plaid_holding(item_key="sample_brokerage", holding={
            "account_id": account_id, "security_id": sid, "ticker_symbol": ticker, "security_name": name,
            "security_type": kind, "quantity": 1, "institution_price": value, "institution_value": value,
            "cost_basis": basis, "iso_currency_code": "USD",
        })
    for sid, industry in _INDUSTRIES.items():
        db.set_security_industry(security_id=sid, ticker=None, industry=industry, updated_at=now)
    for sid, sector in _MISTAGGED.items():
        db.set_security_sector(security_id=sid, ticker=None, sector=sector, updated_at=now)
    _seed_transactions()
    # Tie the sample line items to the pretend accounts (live balances, no double counting).
    by_name = {"Alex 401(k)": "smp_401k", "Sam IRA": "smp_ira", "Alex Roth IRA": "smp_roth",
               "Joint brokerage": "smp_brok", "Savings": "smp_sav"}
    for row in db.list_line_items("assets"):
        if row.get("source") == SAMPLE_SOURCE and row["name"] in by_name:
            db.update_line_item("assets", row["id"], {"linked_account_id": by_name[row["name"]]})
    for row in db.list_line_items("real_estate"):
        if row.get("source") == SAMPLE_SOURCE:
            db.update_line_item("real_estate", row["id"], {"linked_account_id": "smp_mort"})
    for row in db.list_line_items("expenses"):
        cat = {"Housing": "Housing & Utilities", "Food": "Food", "Healthcare": "Medical & Health", "Travel": "Travel"}.get(row["name"])
        if row.get("source") == SAMPLE_SOURCE and cat:
            db.update_line_item("expenses", row["id"], {"linked_category": cat})


def _seed_transactions() -> None:
    today = date.today()
    n = 0

    def add(day: date, amount: float, name: str, category: str, primary: str):
        nonlocal n
        n += 1
        db.upsert_plaid_transaction(item_key="sample_bank", transaction={
            "transaction_id": f"{_TXN_PREFIX}{n:04d}", "account_id": "smp_chk", "date": day.isoformat(),
            "amount": amount, "iso_currency_code": "USD", "name": name, "merchant_name": name, "pending": False,
            "plaid_category_primary": primary, "plaid_category_detailed": primary, "category": category,
            "excluded_from_expense": False,
        })

    for m in range(12):
        first = (today.replace(day=1) - timedelta(days=30 * m)).replace(day=1)
        add(first.replace(day=3), 4_500.0, "Home mortgage and utilities", "Housing & Utilities", "RENT_AND_UTILITIES")
        add(first.replace(day=9), 1_350.0 + 40 * (m % 4), "Grocery Market", "Food", "FOOD_AND_DRINK")
        add(first.replace(day=17), 520.0 + 25 * (m % 3), "Restaurants", "Food", "FOOD_AND_DRINK")
        add(first.replace(day=21), 1_150.0 + 60 * (m % 5), "Medical & pharmacy", "Medical & Health", "MEDICAL")
        if m in (1, 4, 8, 10):
            add(first.replace(day=12), 4_800.0, "Airline and hotel", "Travel", "TRAVEL")
        add(first.replace(day=1), -7_400.0, "Payroll deposit", "Income", "INCOME")
        add(first.replace(day=15), -7_400.0, "Payroll deposit", "Income", "INCOME")


def remove_sample_linked_accounts() -> int:
    """Deletes the pretend linked accounts and their transactions. Returns how many items were removed."""
    removed = 0
    ids = [t["transaction_id"] for t in db.list_plaid_transactions() if str(t["transaction_id"]).startswith(_TXN_PREFIX)]
    if ids:
        db.delete_plaid_transactions(ids)
    for item in list(db.list_plaid_items()):
        if item["item_key"] in SAMPLE_ITEMS:
            db.delete_plaid_item(item["item_key"])
            removed += 1
    db.clear_security_industries([sid for sid in set(_INDUSTRIES) | set(_MISTAGGED)])
    return removed
