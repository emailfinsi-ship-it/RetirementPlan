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

import math
import random
import time
from pathlib import Path

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from source.common import config, db, linked_data
from source.reporting import excel_style as xs
from source.reporting.aggregate import build_summary, effective_balance, effective_loan_balance, real_estate_equity
from source.reporting.monte_carlo import (
    run_historical_bootstrap_simulation,
    run_historical_stress_test,
    run_simulation,
    stable_simulation_seed,
)

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


_PCT_ASSUMPTIONS = {"expected_return", "inflation_rate", "return_volatility", "taxable_gains_fraction"}
_ASSUMPTION_LABELS = {
    "annual_income_offset": "Annual income offset",
    "apply_drawdown_tax": "Apply drawdown tax (1 = yes)",
    "birth_year": "Your birth year",
    "spouse_birth_year": "Anu's birth year",
    "current_year": "Current year",
    "early_tax_deferred_age": "Early tax-deferred draw age",
    "expected_return": "Expected return",
    "inflation_rate": "Inflation rate",
    "iterations": "Simulation iterations",
    "plan_horizon_years": "Plan horizon (years)",
    "retirement_year": "Retirement year",
    "return_volatility": "Return volatility",
    "taxable_gains_fraction": "Taxable gains fraction",
    "heir_base_income": "Heir base income",
    "heir_spread_years": "Heir spread (years)",
    "heir_type": "Heir type",
}


def _assumption_cell(key: str, value):
    """Assumptions are stored as text -- show real numbers (and real
    percentages for the rate-like ones) so the sheet reads cleanly."""
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(number):  # "nan"/"inf" parse as floats but int(number) below would raise
        return value
    if key in _PCT_ASSUMPTIONS:
        return xs.Fmt(number, xs.PCT1)
    if number == int(number):
        return xs.Fmt(int(number), "0")
    return xs.Fmt(number, "0.00")


def _sum_by(items, key_fn, value_fn) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for item in items:
        key = (key_fn(item) or "Uncategorized").strip() or "Uncategorized"
        totals[key] = totals.get(key, 0.0) + float(value_fn(item) or 0.0)
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


def _write_helper_table(ws, *, row: int, col: int, label_header: str, items: list[tuple[str, float]],
                        money_format: str = xs.MONEY0) -> xs.TableInfo:
    """A small aggregated table that sits to the right of a data sheet's
    main table and feeds that sheet's charts (chart series must reference
    cells, so the aggregation has to exist in the workbook). Its header
    names the breakdown itself ("Assets by category"), so there's no
    separate title row to disturb the main table's row heights."""
    return xs.write_table(
        ws, headers=[label_header, "Amount"], rows=[(k, v) for k, v in items],
        money_cols={1}, money_format=money_format, start_row=row, start_col=col, header_height=None,
    )


def _write_band_table(ws, row: int, band: list, *, col: int = 1) -> xs.TableInfo:
    rows = [(b["year"], b["p10"], b["median"], b["p90"]) for b in band]
    return xs.write_table(
        ws, headers=["Year", "P10", "Median", "P90"], rows=rows, year_cols={0}, money_cols={1, 2, 3},
        start_row=row, start_col=col,
    )


def _add_band_chart(ws, info: xs.TableInfo, *, title: str, anchor: str) -> None:
    """The dashboard's fan chart as a native line chart: dashed 10th/90th
    percentile lines around a solid median."""
    if info.last_row < info.first_row:
        return
    c = info.first_col
    xs.add_line_chart(
        ws, title=title, anchor=anchor, cats=(c, info.first_row, info.last_row),
        series=[
            ("90th percentile", (c + 3, info.first_row, info.last_row), xs.PALETTE[0], "dash", 1.5),
            ("Median", (c + 2, info.first_row, info.last_row), xs.PALETTE[0], None, 2.5),
            ("10th percentile", (c + 1, info.first_row, info.last_row), xs.PALETTE[0], "dash", 1.5),
        ],
    )


def build_workbook(summary: dict, *, monte_carlo_result: dict | None = None) -> Workbook:
    wb = Workbook()
    # Same live-balance lookup source.reporting.aggregate.build_summary()
    # uses -- so a row linked to a Plaid account exports its current live
    # balance rather than whatever was last typed in, matching what the
    # dashboard itself shows for that row.
    live_by_account_id = {a["account_id"]: a for a in linked_data.linkable_accounts()}

    if monte_carlo_result is None:
        monte_carlo_result = _default_monte_carlo_result(summary)

    generated = time.strftime("%Y-%m-%d %H:%M")

    # ---------------------------------------------------------------- Summary
    ws = wb.active
    ws.title = "Summary"
    xs.write_title(ws, "Retirement Plan", f"Snapshot generated {generated}  |  all figures in US dollars")
    row = xs.write_section_header(ws, 4, 1, "Key figures", span=2)
    metrics = [
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
    ]
    info = xs.write_table(ws, headers=["Metric", "Value"], rows=metrics, money_cols={1}, start_row=row, key_rows={0, 6, 7})
    skip = {1, 2, 4}

    row = xs.write_section_header(ws, info.next_row + 1, 1, "Assets by category", span=2)
    cat_items = [(cat, total) for cat, total in summary["asset_category_subtotals"]]
    cat_info = xs.write_table(ws, headers=["Asset category", "Balance"], rows=cat_items, money_cols={1}, start_row=row)
    skip.add(row - 1)

    row = xs.write_section_header(ws, cat_info.next_row + 1, 1, "Net worth components", span=2)
    skip.add(row - 1)
    comp_rows = [
        ("Manual assets", summary["manual_asset_total"]),
        ("Linked accounts", summary["linked_asset_total"]),
        ("Real estate equity", summary["real_estate_equity_total"]),
        ("Liabilities", -summary["liability_total"]),
    ]
    comp_info = xs.write_table(ws, headers=["Component", "Amount"], rows=comp_rows, money_cols={1}, start_row=row)

    if cat_items and len(cat_items) <= len(xs.PALETTE) and all(v > 0 for _, v in cat_items):
        # the category table above already holds exactly the slices
        xs.add_doughnut_chart(
            ws, title="Assets by category", anchor="D4",
            cats=(1, cat_info.first_row, cat_info.last_row), values=(2, cat_info.first_row, cat_info.last_row),
        )
    elif any(v > 0 for _, v in cat_items):
        # chart series must reference cells, so fold the tail into "Other" in a small table below the content
        pie_items = xs.top_n_with_other(cat_items)
        pinfo = _write_helper_table(
            ws, row=comp_info.next_row + 2, col=1, label_header="Assets by category (tail folded into Other)", items=pie_items,
        )
        skip.add(comp_info.next_row + 2)
        xs.add_doughnut_chart(
            ws, title="Assets by category", anchor="D4",
            cats=(1, pinfo.first_row, pinfo.last_row), values=(2, pinfo.first_row, pinfo.last_row),
        )
    xs.add_bar_chart(
        ws, title="Net worth components", anchor="D24", cats=(1, comp_info.first_row, comp_info.last_row),
        series=[("Amount", (2, comp_info.first_row, comp_info.last_row), xs.PALETTE[0])], data_labels=True,
        width=13, height=8, y_format=xs.MONEY0,
    )
    xs.autosize(ws, skip_rows=skip)
    ws.column_dimensions["A"].width = 62
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 3
    for c in range(4, 12):
        ws.column_dimensions[get_column_letter(c)].width = 9.5
    xs.finish_sheet(ws, tab_color=xs.BRAND, gridlines=False, one_page=True)

    # -------------------------------------------------------- Net Worth History
    ws = wb.create_sheet("Net Worth History")
    snapshots = db.list_net_worth_snapshots()
    nw_rows = [
        (
            sn["snapshot_date"], sn["net_worth"],
            (sn["manual_asset_total"] or 0) + (sn["linked_asset_total"] or 0),
            -(sn["liability_total"] or 0), sn["real_estate_equity_total"], sn["retirement_liquid_total"],
        )
        for sn in snapshots
    ]
    info = xs.write_table(
        ws, headers=["Date", "Net worth", "Assets (manual + linked)", "Liabilities", "Real estate equity", "Retirement/Liquid"],
        rows=nw_rows, money_cols={1, 2, 3, 4, 5}, freeze=True, autofilter=True,
    )
    if len(nw_rows) >= 2:
        xs.add_line_chart(
            ws, title="Net worth over time", anchor="H2", cats=(1, info.first_row, info.last_row),
            series=[("Net worth", (2, info.first_row, info.last_row), xs.PALETTE[0], None, 2.5)],
            y_format='$#,##0.0,,"M"', x_title="Date", y_min=xs.fitted_axis_min([r[1] for r in nw_rows]),
        )
    else:
        ws.cell(row=info.next_row + 1, column=1, value=(
            "One snapshot is captured automatically per day while the dashboard is running -- "
            "this sheet (and its chart) fills in as days accumulate."
        )).font = xs.font(color=xs.MUTED, italic=True)
    xs.finish_sheet(ws, tab_color="1BAF7A")

    # ------------------------------------------------------------------- Asset
    ws = wb.create_sheet("Asset")
    asset_rows = [
        (
            a["kind"], a["category"], a["name"], a["institution"], a["last4"],
            effective_balance(a, live_by_account_id), a["source"], a["notes"],
        )
        for a in summary["assets"]
    ]
    info = xs.write_table(
        ws,
        headers=["Kind", "Category", "Name", "Institution", "Last 4", "Balance", "Source", "Notes"],
        rows=asset_rows, money_cols={5}, money_format=xs.MONEY2, wrap_cols={7}, freeze=True, autofilter=True,
    )
    asset_only = [(a, r[5]) for a, r in zip(summary["assets"], asset_rows) if a["kind"] == "asset"]
    by_category = _sum_by(asset_only, lambda t: t[0]["category"], lambda t: t[1])
    by_institution = _sum_by(asset_only, lambda t: t[0]["institution"], lambda t: t[1])
    helper_col = 10
    if any(v > 0 for _, v in by_category):
        cat_pie = xs.top_n_with_other(by_category)
        cinfo = _write_helper_table(ws, row=1, col=helper_col, label_header="Assets by category", items=cat_pie)
        xs.add_doughnut_chart(
            ws, title="Assets by category", anchor=f"{get_column_letter(helper_col + 3)}1",
            cats=(helper_col, cinfo.first_row, cinfo.last_row), values=(helper_col + 1, cinfo.first_row, cinfo.last_row),
        )
        inst_top = xs.top_n_with_other(by_institution, n=8)
        iinfo = _write_helper_table(
            ws, row=cinfo.next_row + 2, col=helper_col, label_header="Assets by institution", items=inst_top,
        )
        xs.add_bar_chart(
            ws, title="Assets by institution", anchor=f"{get_column_letter(helper_col + 3)}21",
            cats=(helper_col, iinfo.first_row, iinfo.last_row),
            series=[("Balance", (helper_col + 1, iinfo.first_row, iinfo.last_row), xs.PALETTE[0])],
            horizontal=True, width=16, height=9,
        )
    xs.finish_sheet(ws, tab_color="2A78D6")

    # --------------------------------------------------------- Expense / Income
    ws = wb.create_sheet("Expense")
    expense_rows = [
        (
            e["name"], e["category"], e["annual_amount"], e["start_year"], e["end_year"],
            e["base_year"], "Yes" if e["inflates"] else "No", e["source"], e["notes"],
        )
        for e in summary["expenses"]
    ]
    xs.write_table(
        ws,
        headers=["Name", "Category", "Annual Amount", "Start Year", "End Year", "Base Year", "Inflates?", "Source", "Notes"],
        rows=expense_rows, money_cols={2}, year_cols={3, 4, 5}, wrap_cols={8}, freeze=True, autofilter=True,
    )
    exp_by_cat = _sum_by(summary["expenses"], lambda e: e["category"], lambda e: e["annual_amount"])
    if any(v > 0 for _, v in exp_by_cat):
        einfo = _write_helper_table(ws, row=1, col=11, label_header="Annual expense by category", items=exp_by_cat)
        xs.add_bar_chart(
            ws, title="Annual expense by category", anchor="N1", cats=(11, einfo.first_row, einfo.last_row),
            series=[("Annual amount", (12, einfo.first_row, einfo.last_row), xs.PALETTE[1])], horizontal=True,
        )
    xs.finish_sheet(ws, tab_color="EB6834")

    ws = wb.create_sheet("Income")
    income_rows = [
        (
            i["name"], i["category"], i["annual_amount"], i["start_year"], i["end_year"],
            i["base_year"], "Yes" if i["inflates"] else "No",
            "Yes" if i.get("include_in_monte_carlo") else "No", i["source"], i["notes"],
        )
        for i in summary["income"]
    ]
    xs.write_table(
        ws,
        headers=["Name", "Category", "Annual Amount", "Start Year", "End Year", "Base Year", "Inflates?", "In Simulation?", "Source", "Notes"],
        rows=income_rows, money_cols={2}, year_cols={3, 4, 5}, wrap_cols={9}, freeze=True, autofilter=True,
    )
    inc_by_cat = _sum_by(summary["income"], lambda i: i["category"], lambda i: i["annual_amount"])
    if any(v > 0 for _, v in inc_by_cat):
        iinfo = _write_helper_table(ws, row=1, col=12, label_header="Annual income by category", items=inc_by_cat)
        xs.add_bar_chart(
            ws, title="Annual income by category", anchor="O1", cats=(12, iinfo.first_row, iinfo.last_row),
            series=[("Annual amount", (13, iinfo.first_row, iinfo.last_row), xs.PALETTE[2])], horizontal=True,
        )
    xs.finish_sheet(ws, tab_color="1BAF7A")

    # ------------------------------------------------------ Real Estate Analysis
    ws = wb.create_sheet("Real Estate Analysis")
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
    info = xs.write_table(
        ws,
        headers=[
            "Property", "Purchase Price", "Current Value", "Ownership %", "Loan Balance", "Your Loan Share",
            "Equity", "Annual Income", "Source",
        ],
        rows=re_rows, money_cols={1, 2, 4, 5, 6, 7}, freeze=True, autofilter=True,
    )
    if re_rows:
        xs.add_bar_chart(
            ws, title="Property value, your loan share and equity", anchor=f"A{info.next_row + 2}",
            cats=(1, info.first_row, info.last_row),
            series=[
                ("Current value", (3, info.first_row, info.last_row), xs.PALETTE[0]),
                ("Your loan share", (6, info.first_row, info.last_row), xs.PALETTE[1]),
                ("Equity", (7, info.first_row, info.last_row), xs.PALETTE[2]),
            ],
            width=22, height=10,
        )
    xs.finish_sheet(ws, tab_color="EDA100")

    # Linked Positions / Linked Accounts -- live Plaid data shown on the
    # dashboard's own Linked Positions page, but never previously part of
    # this export at all (the export only ever covered this program's own
    # manually-entered line items, plus the Asset tab's already-netted
    # live balance for a *linked* asset row -- the raw brokerage holdings
    # and account list behind those balances had no sheet of their own).
    positions = linked_data.read_linked_portfolio_positions()
    ws = wb.create_sheet("Linked Positions")
    position_rows = [
        (
            p["institution"], p["account"], p["security_name"], p["ticker"],
            p["security_type"], p["industry"] or "Unclassified", p["market_value"], p["position_as_of"],
        )
        for p in positions
    ]
    position_rows.append(("TOTAL", "", "", "", "", "", sum(p["market_value"] or 0 for p in positions), ""))
    xs.write_table(
        ws,
        headers=["Institution", "Account", "Security", "Ticker", "Type", "Industry", "Market Value", "As Of"],
        rows=position_rows, money_cols={6}, money_format=xs.MONEY2, total_rows=1, freeze=True, autofilter=True,
    )
    by_type = _sum_by(positions, lambda p: (p["security_type"] or "").title(), lambda p: p["market_value"])
    by_industry = _sum_by(positions, lambda p: p["industry"] or "Unclassified", lambda p: p["market_value"])
    if any(v > 0 for _, v in by_type):
        pie = xs.top_n_with_other(by_type)
        tinfo = _write_helper_table(ws, row=1, col=10, label_header="Market value by security type", items=pie)
        xs.add_doughnut_chart(
            ws, title="Holdings by security type", anchor="M1",
            cats=(10, tinfo.first_row, tinfo.last_row), values=(11, tinfo.first_row, tinfo.last_row),
        )
        ind_top = xs.top_n_with_other(by_industry, n=9)
        if len(ind_top) > 1:  # a single "Unclassified" bar says nothing
            ninfo = _write_helper_table(
                ws, row=tinfo.next_row + 2, col=10, label_header="Market value by industry", items=ind_top,
            )
            xs.add_bar_chart(
                ws, title="Holdings by industry", anchor="M21", cats=(10, ninfo.first_row, ninfo.last_row),
                series=[("Market value", (11, ninfo.first_row, ninfo.last_row), xs.PALETTE[0])], horizontal=True,
                width=16, height=10,
            )
    xs.finish_sheet(ws, tab_color="2A78D6")

    accounts = linked_data.read_linked_account_balances()
    ws = wb.create_sheet("Linked Accounts")
    account_rows = [
        (a["institution"], a["account_type"], a["last4"], a["balance"], a["last_update"])
        for a in accounts
    ]
    account_rows.append(("TOTAL", "", "", sum(a["balance"] or 0 for a in accounts), ""))
    xs.write_table(
        ws,
        headers=["Institution", "Account Type", "Last 4", "Balance", "Last Update"],
        rows=account_rows, money_cols={3}, money_format=xs.MONEY2, total_rows=1, freeze=True, autofilter=True,
    )
    by_inst = _sum_by(accounts, lambda a: a["institution"], lambda a: a["balance"])
    if len(by_inst) > 1:
        binfo = _write_helper_table(
            ws, row=1, col=8, label_header="Net balance by institution", items=by_inst,
        )
        xs.add_bar_chart(
            ws, title="Net balance by institution", anchor="K1", cats=(8, binfo.first_row, binfo.last_row),
            series=[("Balance", (9, binfo.first_row, binfo.last_row), xs.PALETTE[0])], horizontal=True,
        )
    xs.finish_sheet(ws, tab_color="2A78D6")

    # Monte Carlo Simulation -- assumptions, then the Gaussian and S&P
    # 500 historical-bootstrap simulations' summary figures and
    # p10/median/p90 bands (mirrors the Monte Carlo tab's top two
    # sections). The historical stress test (a third, deterministic view
    # on that same tab) gets its own sheet below since its per-scenario
    # detail table is much wider.
    ws = wb.create_sheet("Monte Carlo Simulation")
    xs.write_title(ws, "Monte Carlo Simulation", "Percentile bands of ending balance by year; dashed lines are the 10th and 90th percentiles")
    skip = {1, 2}
    row = xs.write_section_header(ws, 4, 1, "Assumptions", span=2)
    skip.add(row - 1)
    assumption_rows = [
        (_ASSUMPTION_LABELS.get(k, k), _assumption_cell(k, v))
        for k, v in sorted(summary["assumptions"].items())
        if k not in ("spouse_tax_deferred_share", "rental_taxable_schedule")  # derived, not user settings
    ]
    ainfo = xs.write_table(ws, headers=["Assumption", "Value"], rows=assumption_rows, start_row=row)
    row = ainfo.next_row + 1

    gaussian = monte_carlo_result.get("gaussian")
    if gaussian:
        top = row
        row = xs.write_section_header(ws, row, 1, "Gaussian simulation (Expected return / Volatility)", span=4)
        skip.add(top)
        minfo = xs.write_table(
            ws,
            headers=["Metric", "Value"],
            rows=[
                ("Success rate", xs.Fmt(gaussian.get("success_rate", 0.0), xs.PCT1)),
                ("Iterations", xs.Fmt(gaussian.get("iterations", 0), xs.INT)),
                ("10th percentile ending balance", gaussian.get("p10_ending_balance", 0.0)),
                ("Median ending balance", gaussian.get("median_ending_balance", 0.0)),
                ("90th percentile ending balance", gaussian.get("p90_ending_balance", 0.0)),
            ],
            money_cols={1}, start_row=row, key_rows={0},
        )
        row = minfo.next_row + 1
        binfo = _write_band_table(ws, row, gaussian.get("band") or [])
        _add_band_chart(ws, binfo, title="Gaussian simulation: ending balance percentiles", anchor=f"G{top}")
        row = max(binfo.next_row, top + 22) + 1

    sp500 = monte_carlo_result.get("sp500_bootstrap")
    if sp500:
        top = row
        row = xs.write_section_header(ws, row, 1, "S&P 500 historical-returns simulation", span=4)
        skip.add(top)
        minfo = xs.write_table(
            ws,
            headers=["Metric", "Value"],
            rows=[
                ("Success rate", xs.Fmt(sp500.get("success_rate", 0.0), xs.PCT1)),
                ("Iterations", xs.Fmt(sp500.get("iterations", 0), xs.INT)),
                ("Sample size (recorded years)", xs.Fmt(sp500.get("sample_size", 0), xs.INT)),
                ("10th percentile ending balance", sp500.get("p10_ending_balance", 0.0)),
                ("Median ending balance", sp500.get("median_ending_balance", 0.0)),
                ("90th percentile ending balance", sp500.get("p90_ending_balance", 0.0)),
            ],
            money_cols={1}, start_row=row, key_rows={0},
        )
        row = minfo.next_row + 1
        binfo = _write_band_table(ws, row, sp500.get("band") or [])
        _add_band_chart(ws, binfo, title="S&P 500 history: ending balance percentiles", anchor=f"G{top}")
        row = max(binfo.next_row, top + 22) + 1

    # Backward-compatible fallback: a caller (or an older test) that
    # supplies just {"band": [...]} with no "gaussian"/"sp500_bootstrap"
    # keys still gets that band written, rather than silently dropped.
    if not gaussian and not sp500 and monte_carlo_result.get("band"):
        top = row
        row = xs.write_section_header(ws, row, 1, "Simulation", span=4)
        skip.add(top)
        binfo = _write_band_table(ws, row, monte_carlo_result["band"])
        _add_band_chart(ws, binfo, title="Simulation: ending balance percentiles", anchor=f"G{top}")

    xs.autosize(ws, skip_rows=skip, min_width=12)
    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 0, 32)
    xs.finish_sheet(ws, tab_color="E87BA4", gridlines=False)

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
        balance_offsets: list[tuple[str, int]] = []  # (scenario label, 0-based column offset of its Balance)
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
            for i, sc in enumerate(scenarios):
                return_col = 6 + i * 2
                balance_col = 7 + i * 2
                pct_cols.add(return_col)
                money_cols.add(balance_col)
                balance_offsets.append((sc["label"], balance_col))
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
            for i, sc in enumerate(scenarios):
                base = 4 + i * 4  # 0-based row offset of this scenario's Return column (Year/Total Expense/Total Income/Yearly Drawdown take offsets 0-3)
                pct_cols.add(base)
                money_cols |= {base + 1, base + 2, base + 3}
                balance_offsets.append((sc["label"], base + 3))
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
        info = xs.write_table(
            ws_stress, headers=headers, rows=rows, money_cols=money_cols, pct_cols=pct_cols, pct_format=xs.PCT1,
            year_cols={0}, freeze=True,
        )
        ws_stress.freeze_panes = "B2"
        chart_row = info.next_row + 2
        if rows:
            xs.add_line_chart(
                ws_stress, title="Portfolio balance by historical scenario", anchor=f"A{chart_row}",
                cats=(1, info.first_row, info.last_row),
                series=[
                    (label, (off + 1, info.first_row, info.last_row), xs.PALETTE[i % len(xs.PALETTE)], None, 2.0)
                    for i, (label, off) in enumerate(balance_offsets)
                ],
                width=24, height=11,
            )
            xs.add_line_chart(
                ws_stress, title="Yearly expense, income and drawdown", anchor=f"K{chart_row}",
                cats=(1, info.first_row, info.last_row),
                series=[
                    ("Total expense", (2, info.first_row, info.last_row), xs.PALETTE[1], None, 2.0),
                    ("Total income", (3, info.first_row, info.last_row), xs.PALETTE[2], None, 2.0),
                    ("Yearly drawdown", (4, info.first_row, info.last_row), xs.PALETTE[0], None, 2.5),
                ],
                y_format='$#,##0,"K"', width=20, height=11,
            )
        xs.finish_sheet(ws_stress, tab_color="E87BA4")

    for name in ("Net Worth History", "Asset", "Expense", "Income", "Real Estate Analysis", "Linked Positions", "Linked Accounts"):
        xs.autosize(wb[name])
    if "Monte Carlo Stress Test" in wb.sheetnames:
        xs.autosize(wb["Monte Carlo Stress Test"], min_width=11, max_width=22)
        wb["Monte Carlo Stress Test"].row_dimensions[1].height = 42
    return wb


def export_current_state(*, monte_carlo_result: dict | None = None) -> Path:
    summary = build_summary()
    wb = build_workbook(summary, monte_carlo_result=monte_carlo_result)
    config.ensure_directories()
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    path = config.OUTPUT_DIR / f"retirement_plan_export_{timestamp}.xlsx"
    wb.save(str(path))
    db.set_meta("last_export_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    db.set_meta("last_export_path", str(path))
    return path
