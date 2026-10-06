"""Generates a fresh .xlsx snapshot of this program's current data --
"import from Excel once, generate this Excel going forward". Unlike the
one-time importer (which reads fixed, hand-built cell coordinates from
the user's old workbook), this writes a plain, clearly-labelled table per
tab: Summary, Asset, Expense, Income, Real Estate Analysis, Linked
Positions, Linked Accounts, Monte Carlo Simulation, Monte Carlo Stress
Test. It's meant to be opened, skimmed, or handed to someone else -- not
re-imported (this program is the system of record; there's no
read-back-in path, by design, so editing the generated file never has any
effect on the running program)."""

from __future__ import annotations

import random
import time
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from source.common import config, linked_data
from source.reporting.aggregate import build_summary, effective_balance, effective_loan_balance, real_estate_equity
from source.reporting.monte_carlo import (
    run_historical_bootstrap_simulation,
    run_historical_stress_test,
    run_simulation,
    stable_simulation_seed,
)

_HEADER_FONT = Font(bold=True)
_SECTION_FONT = Font(bold=True, size=12)
_MONEY_FORMAT = "#,##0.00"
_PCT_FORMAT = "0.00%"


def _write_table(
    ws, *, headers: list, rows: list, money_cols: set = frozenset(), pct_cols: set = frozenset(),
    start_row: int = 1, start_col: int = 1,
) -> int:
    """Writes a bold header row followed by its data rows, starting at
    (start_row, start_col) -- start_row/start_col let a single sheet hold
    several stacked tables (e.g. the Monte Carlo sheet's assumptions
    table followed by its Gaussian and S&P 500 band tables) rather than
    always starting at A1. Returns the row just past the last one
    written, so a caller can chain sections without hand-tracking row
    math."""
    for c, header in enumerate(headers, start=start_col):
        cell = ws.cell(row=start_row, column=c, value=header)
        cell.font = _HEADER_FONT
    r = start_row
    for r_offset, row in enumerate(rows, start=1):
        r = start_row + r_offset
        for c_offset, value in enumerate(row):
            c = start_col + c_offset
            cell = ws.cell(row=r, column=c, value=value)
            if c_offset in money_cols and isinstance(value, (int, float)):
                cell.number_format = _MONEY_FORMAT
            elif c_offset in pct_cols and isinstance(value, (int, float)):
                cell.number_format = _PCT_FORMAT
    for c_offset, header in enumerate(headers):
        c = start_col + c_offset
        width = max(12, len(str(header)) + 2)
        letter = get_column_letter(c)
        current = ws.column_dimensions[letter].width
        if current is None or width > current:
            ws.column_dimensions[letter].width = width
    return r + 1


def _write_section_header(ws, row: int, col: int, text: str) -> int:
    ws.cell(row=row, column=col, value=text).font = _SECTION_FONT
    return row + 2


def _default_monte_carlo_result(summary: dict) -> dict:
    """Runs all three Monte Carlo views fresh from the plan's current
    data -- the exact same starting balance/expenses/income/assumptions/
    pools the Monte Carlo tab itself uses (source.webapp.pages.
    monte_carlo_page._render_monte_carlo_page) -- so the export always
    has real numbers in it, and those numbers match what the tab shows
    on screen. A caller (tests, mainly) can still hand in its own
    already-computed result instead.

    Passes `pools=` (the {"tax_deferred", "roth", "taxable"} split) the
    same way the live tab does, engaging the three-pool withdrawal/RMD/
    tax engine. build_workbook()'s stress-test sheet writer below
    branches on the result's `per_scenario_tax` flag (see
    run_historical_stress_test's docstring) to write per-scenario Tax/
    Withdrawal columns instead of the legacy shared ones when pools are
    in play -- the same branch source.webapp.pages.monte_carlo_page.
    _historical_stress_test_html makes for the on-screen table.

    Also seeds the Gaussian/bootstrap runs via stable_simulation_seed --
    the exact same seed the Monte Carlo tab and the Summary tab's "What
    if" card derive from this same starting_balance/pools/assumptions/
    expenses/income -- so this export's own numbers don't just match the
    same *kind* of figure the tab shows, they match the tab's actual
    current numbers exactly (an unseeded call here would run its own
    independent 1000-path simulation and land on a plausible-but-
    different figure than what's on screen)."""
    starting_balance = summary["net_liquid_asset"]
    expenses = summary["expenses"]
    income = summary["income_for_simulation"]
    assumptions = summary["assumptions"]
    pools = summary["retirement_pools"]
    seed = stable_simulation_seed(
        starting_balance=starting_balance, expenses=expenses, income=income, assumptions=assumptions, pools=pools,
    )
    return {
        "gaussian": run_simulation(
            starting_balance=starting_balance, expenses=expenses, income=income, assumptions=assumptions, pools=pools,
            rng=random.Random(seed),
        ),
        "sp500_bootstrap": run_historical_bootstrap_simulation(
            starting_balance=starting_balance, expenses=expenses, income=income, assumptions=assumptions, pools=pools,
            rng=random.Random(seed ^ 0x5DEECE66D),
        ),
        "stress_test": run_historical_stress_test(
            starting_balance=starting_balance, expenses=expenses, income=income, assumptions=assumptions, pools=pools,
        ),
    }


def _write_band_table(ws, row: int, band: list) -> int:
    rows = [(b["year"], b["p10"], b["median"], b["p90"]) for b in band]
    return _write_table(ws, headers=["Year", "P10", "Median", "P90"], rows=rows, money_cols={1, 2, 3}, start_row=row)


def build_workbook(summary: dict, *, monte_carlo_result: dict | None = None) -> Workbook:
    wb = Workbook()
    # Same live-balance lookup source.reporting.aggregate.build_summary()
    # uses -- so a row linked to a Plaid account exports its current live
    # balance rather than whatever was last typed in, matching what the
    # dashboard itself shows for that row.
    live_by_account_id = {a["account_id"]: a for a in linked_data.linkable_accounts()}

    if monte_carlo_result is None:
        monte_carlo_result = _default_monte_carlo_result(summary)

    ws_summary = wb.active
    ws_summary.title = "Summary"
    next_row = _write_table(
        ws_summary,
        headers=["Metric", "Value"],
        rows=[
            ("Generated at", time.strftime("%Y-%m-%d %H:%M:%S")),
            ("Net worth", summary["net_worth"]),
            ("Manual asset total", summary["manual_asset_total"]),
            ("Linked account balance total", summary["linked_asset_total"]),
            ("Liability total", -summary["liability_total"]),
            ("Real estate equity total", summary["real_estate_equity_total"]),
            ("Retirement/Liquid total (Asset rows checked \"In Monte Carlo?\")", summary["retirement_liquid_total"]),
            ("Net Liquid Asset (Monte Carlo starting balance)", summary["net_liquid_asset"]),
            ("Total Asset (Net Liquid Asset + Real estate equity)", summary["total_asset"]),
            (f"This year's ({summary['this_year']}) expense need", summary["this_year_expense_need"]),
            (f"This year's ({summary['this_year']}) income (rows checked \"In simulation?\")", summary["this_year_income"]),
            (f"This year's ({summary['this_year']}) net withdrawal need", summary["this_year_net_need"]),
        ],
        money_cols={1},
    )
    next_row += 1
    _write_table(
        ws_summary,
        headers=["Asset category", "Balance"],
        rows=[(cat, total) for cat, total in summary["asset_category_subtotals"]],
        money_cols={1},
        start_row=next_row,
    )

    ws_asset = wb.create_sheet("Asset")
    asset_rows = [
        (
            a["kind"], a["category"], a["name"], a["institution"], a["last4"],
            effective_balance(a, live_by_account_id), a["source"], a["notes"],
        )
        for a in summary["assets"]
    ]
    _write_table(
        ws_asset,
        headers=["Kind", "Category", "Name", "Institution", "Last 4", "Balance", "Source", "Notes"],
        rows=asset_rows,
        money_cols={5},
    )

    ws_expense = wb.create_sheet("Expense")
    expense_rows = [
        (
            e["name"], e["category"], e["annual_amount"], e["start_year"], e["end_year"],
            e["base_year"], "Yes" if e["inflates"] else "No", e["source"], e["notes"],
        )
        for e in summary["expenses"]
    ]
    _write_table(
        ws_expense,
        headers=["Name", "Category", "Annual Amount", "Start Year", "End Year", "Base Year", "Inflates?", "Source", "Notes"],
        rows=expense_rows,
        money_cols={2},
    )

    ws_income = wb.create_sheet("Income")
    income_rows = [
        (
            i["name"], i["category"], i["annual_amount"], i["start_year"], i["end_year"],
            i["base_year"], "Yes" if i["inflates"] else "No",
            "Yes" if i.get("include_in_monte_carlo") else "No", i["source"], i["notes"],
        )
        for i in summary["income"]
    ]
    _write_table(
        ws_income,
        headers=["Name", "Category", "Annual Amount", "Start Year", "End Year", "Base Year", "Inflates?", "In Simulation?", "Source", "Notes"],
        rows=income_rows,
        money_cols={2},
    )

    ws_re = wb.create_sheet("Real Estate Analysis")
    re_rows = [
        (
            r["name"],
            r["purchase_price"],
            r["current_value"],
            r["ownership_pct"],
            effective_loan_balance(r, live_by_account_id),
            effective_loan_balance(r, live_by_account_id) * ((r["ownership_pct"] or 100.0) / 100.0),
            real_estate_equity(r, loan_balance=effective_loan_balance(r, live_by_account_id)),
            r["annual_income"],
            r["source"],
        )
        for r in summary["real_estate"]
    ]
    _write_table(
        ws_re,
        headers=[
            "Property", "Purchase Price", "Current Value", "Ownership %", "Loan Balance", "Your Loan Share",
            "Equity", "Annual Income", "Source",
        ],
        rows=re_rows,
        money_cols={1, 2, 4, 5, 6, 7},
    )

    # Linked Positions / Linked Accounts -- live Plaid data shown on the
    # dashboard's own Linked Positions page, but never previously part of
    # this export at all (the export only ever covered this program's own
    # manually-entered line items, plus the Asset tab's already-netted
    # live balance for a *linked* asset row -- the raw brokerage holdings
    # and account list behind those balances had no sheet of their own).
    positions = linked_data.read_linked_portfolio_positions()
    ws_positions = wb.create_sheet("Linked Positions")
    position_rows = [
        (
            p["institution"], p["account"], p["security_name"], p["ticker"],
            p["security_type"], p["industry"] or "Unclassified", p["market_value"], p["position_as_of"],
        )
        for p in positions
    ]
    position_rows.append(("TOTAL", "", "", "", "", "", sum(p["market_value"] or 0 for p in positions), ""))
    _write_table(
        ws_positions,
        headers=["Institution", "Account", "Security", "Ticker", "Type", "Industry", "Market Value", "As Of"],
        rows=position_rows,
        money_cols={6},
    )

    accounts = linked_data.read_linked_account_balances()
    ws_accounts = wb.create_sheet("Linked Accounts")
    account_rows = [
        (a["institution"], a["account_type"], a["last4"], a["balance"], a["last_update"])
        for a in accounts
    ]
    account_rows.append(("TOTAL", "", "", sum(a["balance"] or 0 for a in accounts), ""))
    _write_table(
        ws_accounts,
        headers=["Institution", "Account Type", "Last 4", "Balance", "Last Update"],
        rows=account_rows,
        money_cols={3},
    )

    # Monte Carlo Simulation -- assumptions, then the Gaussian and S&P
    # 500 historical-bootstrap simulations' summary figures and
    # p10/median/p90 bands (mirrors the Monte Carlo tab's top two
    # sections). The historical stress test (a third, deterministic view
    # on that same tab) gets its own sheet below since its per-scenario
    # detail table is much wider.
    ws_mc = wb.create_sheet("Monte Carlo Simulation")
    assumption_rows = [(k, v) for k, v in sorted(summary["assumptions"].items()) if k != "spouse_tax_deferred_share"]  # derived, not a user setting
    row = _write_table(ws_mc, headers=["Assumption", "Value"], rows=assumption_rows, start_row=1)
    row += 1

    gaussian = monte_carlo_result.get("gaussian")
    if gaussian:
        row = _write_section_header(ws_mc, row, 1, "Gaussian simulation (Expected return / Volatility)")
        row = _write_table(
            ws_mc,
            headers=["Metric", "Value"],
            rows=[
                ("Success rate", gaussian.get("success_rate", 0.0)),
                ("Iterations", gaussian.get("iterations", 0)),
                ("10th percentile ending balance", gaussian.get("p10_ending_balance", 0.0)),
                ("Median ending balance", gaussian.get("median_ending_balance", 0.0)),
                ("90th percentile ending balance", gaussian.get("p90_ending_balance", 0.0)),
            ],
            money_cols={1},
            start_row=row,
        )
        row += 1
        row = _write_band_table(ws_mc, row, gaussian.get("band") or [])
        row += 1

    sp500 = monte_carlo_result.get("sp500_bootstrap")
    if sp500:
        row = _write_section_header(ws_mc, row, 1, "S&P 500 historical-returns simulation")
        row = _write_table(
            ws_mc,
            headers=["Metric", "Value"],
            rows=[
                ("Success rate", sp500.get("success_rate", 0.0)),
                ("Iterations", sp500.get("iterations", 0)),
                ("Sample size (recorded years)", sp500.get("sample_size", 0)),
                ("10th percentile ending balance", sp500.get("p10_ending_balance", 0.0)),
                ("Median ending balance", sp500.get("median_ending_balance", 0.0)),
                ("90th percentile ending balance", sp500.get("p90_ending_balance", 0.0)),
            ],
            money_cols={1},
            start_row=row,
        )
        row += 1
        row = _write_band_table(ws_mc, row, sp500.get("band") or [])

    # Backward-compatible fallback: a caller (or an older test) that
    # supplies just {"band": [...]} with no "gaussian"/"sp500_bootstrap"
    # keys still gets that band written, rather than silently dropped.
    if not gaussian and not sp500 and monte_carlo_result.get("band"):
        row = _write_section_header(ws_mc, row, 1, "Simulation")
        _write_band_table(ws_mc, row, monte_carlo_result["band"])

    stress_test = monte_carlo_result.get("stress_test")
    if stress_test and stress_test.get("years"):
        ws_stress = wb.create_sheet("Monte Carlo Stress Test")
        years = stress_test["years"]
        yearly_total_expense = stress_test.get("yearly_total_expense") or []
        yearly_income = stress_test.get("yearly_income") or []
        yearly_needs = stress_test.get("yearly_needs") or []
        scenarios = stress_test.get("scenarios") or []
        # Mirrors the branch source.webapp.pages.monte_carlo_page.
        # _historical_stress_test_html makes for the on-screen table:
        # per_scenario_tax=False (pools=None, legacy) means every
        # scenario shares one Tax/Total Withdrawal column; True (pools=
        # engaged) means tax and total withdrawal are genuinely
        # per-scenario (an RMD depends on that scenario's own running
        # tax-deferred balance), so each scenario gets its own Tax/
        # Withdrawal columns instead of the shared pair -- see
        # run_historical_stress_test's own docstring for why.
        per_scenario_tax = bool(stress_test.get("per_scenario_tax"))
        headers = ["Year", "Total Expense", "Total Income", "Yearly Drawdown"]
        money_cols = {1, 2, 3}
        pct_cols = set()
        rows = []
        if not per_scenario_tax:
            # yearly_tax/yearly_total_withdrawal are new (source.reporting.
            # monte_carlo.estimate_annual_drawdown_tax) -- absent on an
            # older caller's dict (or with "Apply drawdown tax" off, all
            # zeros), in which case these two columns are just all-None/
            # all-zero rather than missing, same graceful-fallback style
            # as the other yearly_* lists here.
            yearly_tax = stress_test.get("yearly_tax") or []
            yearly_total_withdrawal = stress_test.get("yearly_total_withdrawal") or []
            headers += ["Tax (Fed+CA)", "Total Withdrawal"]
            money_cols |= {4, 5}
            for sc in scenarios:
                headers.append(f"{sc['label']} Return")
                headers.append(f"{sc['label']} Balance")
            for i in range(len(scenarios)):
                return_col = 6 + i * 2
                balance_col = 7 + i * 2
                pct_cols.add(return_col)
                money_cols.add(balance_col)
            for i, year in enumerate(years):
                row_values = [
                    year,
                    yearly_total_expense[i] if i < len(yearly_total_expense) else None,
                    yearly_income[i] if i < len(yearly_income) else None,
                    yearly_needs[i] if i < len(yearly_needs) else None,
                    yearly_tax[i] if i < len(yearly_tax) else None,
                    yearly_total_withdrawal[i] if i < len(yearly_total_withdrawal) else None,
                ]
                for sc in scenarios:
                    point = sc["path"][i] if i < len(sc["path"]) else {}
                    row_values.append(point.get("return"))
                    row_values.append(point.get("balance"))
                rows.append(tuple(row_values))
        else:
            for sc in scenarios:
                label = sc["label"]
                headers += [f"{label} Return", f"{label} Tax", f"{label} Withdrawal", f"{label} Balance"]
            for i in range(len(scenarios)):
                base = 4 + i * 4  # 0-based row offset of this scenario's Return column (Year/Total Expense/Total Income/Yearly Drawdown take offsets 0-3)
                pct_cols.add(base)
                money_cols |= {base + 1, base + 2, base + 3}
            for i, year in enumerate(years):
                row_values = [
                    year,
                    yearly_total_expense[i] if i < len(yearly_total_expense) else None,
                    yearly_income[i] if i < len(yearly_income) else None,
                    yearly_needs[i] if i < len(yearly_needs) else None,
                ]
                for sc in scenarios:
                    point = sc["path"][i] if i < len(sc["path"]) else {}
                    sc_tax = sc.get("yearly_tax") or []
                    sc_withdrawal = sc.get("yearly_total_withdrawal") or []
                    row_values.append(point.get("return"))
                    row_values.append(sc_tax[i] if i < len(sc_tax) else None)
                    row_values.append(sc_withdrawal[i] if i < len(sc_withdrawal) else None)
                    row_values.append(point.get("balance"))
                rows.append(tuple(row_values))
        _write_table(ws_stress, headers=headers, rows=rows, money_cols=money_cols, pct_cols=pct_cols)

    return wb


def export_current_state(*, monte_carlo_result: dict | None = None) -> Path:
    summary = build_summary()
    wb = build_workbook(summary, monte_carlo_result=monte_carlo_result)
    config.ensure_directories()
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    path = config.OUTPUT_DIR / f"retirement_plan_export_{timestamp}.xlsx"
    wb.save(str(path))
    from source.common import db

    db.set_meta("last_export_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    db.set_meta("last_export_path", str(path))
    return path
