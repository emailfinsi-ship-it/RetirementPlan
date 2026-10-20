"""The Budget vs Actual tab: compares the Income &amp; Expenses tab's own
assumptions (the annual, inflation-aware planning figures the Monte Carlo
simulation itself draws on -- see source.reporting.monte_carlo.
annual_expense_need/annual_income_need) against what Actual Spending's
synced Plaid transactions say actually happened.

Deliberately a TOTALS-level comparison, not a category-by-category one:
an Expense-tab row's own `category` (e.g. "Fixed"/"Variable", or whatever
an imported ledger used) and a synced transaction's `category` (the
Food/Travel/... rollup from source.common.plaid_categorize) are two
unrelated taxonomies that happen to share a column name -- forcing them
to line up category-for-category would mean silently guessing at a
mapping nobody actually asked for. Total planned spend vs total actual
spend, and the same for income, is the comparison both sides can always
answer honestly.
"""

from __future__ import annotations

import html
from collections import defaultdict
from datetime import date

from source.common import linked_data, plaid_categorize
from source.reporting.aggregate import build_summary
from source.reporting.monte_carlo import annual_expense_need, annual_income_need
from source.webapp.pages.real_expenditure import _month_key
from source.webapp.render_helpers import _money, _shell


def _actual_expense_and_income_by_month(transactions: list[dict]) -> tuple[dict, dict]:
    """Splits every COUNTED transaction (excluded_from_expense already
    left out, same as Actual Spending's own totals) into two month-keyed
    dicts: actual spend and actual income (sign-flipped to a positive
    dollar amount -- Plaid's own convention has money in as negative).

    "Actual income" is broader than a plain `category == "Income"`
    check -- see plaid_categorize.is_real_income -- so a paycheck-like
    deposit Plaid couldn't classify into any real spending category
    still counts as income here even if it landed in some expense-
    sounding category by name-guess alone. Recomputed from each
    transaction's own fields (not read off a precomputed
    `is_real_income` key) so this stays correct for any transaction dict
    that has the plain Plaid/category fields, whatever else it may or
    may not carry."""
    expense_by_month: dict[str, float] = defaultdict(float)
    income_by_month: dict[str, float] = defaultdict(float)
    for t in transactions:
        if t["excluded_from_expense"]:
            continue
        key = _month_key(t["date"])
        if plaid_categorize.is_real_income(
            primary=t.get("plaid_category_primary"), category=t.get("category"),
            amount=t["amount"], excluded_from_expense=t["excluded_from_expense"],
            category_edited_by_user=bool(t.get("category_edited_by_user")),
            income_kind_override=t.get("income_kind_override") or "",
        ):
            income_by_month[key] += -t["amount"]
        else:
            expense_by_month[key] += t["amount"]
    return expense_by_month, income_by_month


def _variance_cell(actual: float, planned: float, *, higher_is_better: bool = False) -> str:
    """actual - planned, colored status-ok/status-warn depending on which
    direction is actually good for this figure -- under budget is good
    for spend (higher_is_better=False, the default), but under plan is
    NOT good for income (higher_is_better=True, since more income than
    planned is the favorable surprise)."""
    variance = actual - planned
    is_good = variance >= 0 if higher_is_better else variance <= 0
    css_class = "status-ok" if is_good else "status-warn"
    sign = "" if variance <= 0 else "+"
    return f'<span class="{css_class}">{sign}{html.escape(_money(variance))}</span>'


def _monthly_table_html(
    *, title: str, planned_by_month: dict, actual_by_month: dict, months: list[str], higher_is_better: bool = False,
) -> str:
    rows = []
    for month in months:
        planned = planned_by_month.get(month, 0.0)
        actual = actual_by_month.get(month, 0.0)
        pct = f"{actual / planned * 100:.0f}%" if planned else "--"
        rows.append(
            f"<tr><td>{html.escape(month)}</td>"
            f'<td class="num">{_money(planned)}</td>'
            f'<td class="num">{_money(actual)}</td>'
            f'<td class="num">{_variance_cell(actual, planned, higher_is_better=higher_is_better)}</td>'
            f'<td class="num">{pct}</td></tr>'
        )
    rows_html = "".join(rows) or '<tr><td colspan="5" class="muted">Not enough data yet.</td></tr>'
    return f"""
<h3 style="font-size:13px;">{html.escape(title)}</h3>
<table class="sortable">
<thead><tr><th>Month</th><th class="num">Budgeted</th><th class="num">Actual</th><th class="num">Variance</th><th class="num">% of budget</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
"""


def _render_budget_vs_actual_page() -> str:
    s = build_summary()
    expenses = s["expenses"]
    income = s["income"]
    assumptions = s["assumptions"]
    inflation_rate = float(assumptions.get("inflation_rate") or 0.0)

    transactions = linked_data.read_transactions()
    expense_by_month, income_by_month = _actual_expense_and_income_by_month(transactions)
    # Every month that has EITHER a transaction or falls in the current
    # year (so a just-started year with no spend yet still shows up,
    # rather than the table looking empty until the first sync) --
    # capped to the trailing 12, same window Actual Spending's own
    # monthly chart uses, so a person doesn't have to scroll years of
    # history to see the recent trend.
    today = date.today()
    all_months = sorted(set(expense_by_month) | set(income_by_month) | {today.strftime("%Y-%m")})[-12:]

    def planned_expense_for_month(month: str) -> float:
        return annual_expense_need(expenses, int(month[:4]), inflation_rate) / 12

    def planned_income_for_month(month: str) -> float:
        return annual_income_need(income, int(month[:4]), inflation_rate) / 12

    planned_expense_by_month = {m: planned_expense_for_month(m) for m in all_months}
    planned_income_by_month = {m: planned_income_for_month(m) for m in all_months}

    this_year = today.year
    planned_this_year_expense = annual_expense_need(expenses, this_year, inflation_rate)
    planned_this_year_income = annual_income_need(income, this_year, inflation_rate)
    actual_this_year_expense = sum(v for m, v in expense_by_month.items() if m.startswith(str(this_year)))
    actual_this_year_income = sum(v for m, v in income_by_month.items() if m.startswith(str(this_year)))

    days_in_year = 366 if (this_year % 4 == 0 and (this_year % 100 != 0 or this_year % 400 == 0)) else 365
    days_elapsed = (today - date(this_year, 1, 1)).days + 1
    pace_factor = days_in_year / days_elapsed if days_elapsed > 0 else 1.0
    projected_expense = actual_this_year_expense * pace_factor
    projected_income = actual_this_year_income * pace_factor

    tiles = [
        (f"{this_year} expense budget", _money(planned_this_year_expense)),
        ("Actual spend so far", _money(actual_this_year_expense)),
        ("Projected full-year spend", _money(projected_expense)),
        ("Spend variance vs budget", _variance_cell(projected_expense, planned_this_year_expense)),
        (f"{this_year} income plan", _money(planned_this_year_income)),
        ("Actual income so far", _money(actual_this_year_income)),
        ("Projected full-year income", _money(projected_income)),
        ("Income variance vs plan", _variance_cell(projected_income, planned_this_year_income, higher_is_better=True)),
    ]
    tiles_html = "".join(
        f'<div class="tile"><div class="label">{html.escape(label)}</div>'
        f'<div class="value">{value}</div></div>'
        for label, value in tiles
    )

    expense_table_html = _monthly_table_html(
        title="Expense: budgeted vs actual, by month",
        planned_by_month=planned_expense_by_month, actual_by_month=expense_by_month, months=all_months,
    )
    income_table_html = _monthly_table_html(
        title="Income: planned vs actual, by month",
        planned_by_month=planned_income_by_month, actual_by_month=income_by_month, months=all_months,
        higher_is_better=True,
    )

    no_transactions_note = (
        "" if transactions else
        '<p class="muted">No transactions synced yet -- connect a credit card, checking, or investment '
        'account with the "transactions" product on <a href="/setup.html">Setup</a>, then press "Sync now" (top right) '
        'below, to see actuals here. Until then, "Actual" is $0 everywhere.</p>'
    )

    body = f"""
<h2 style="margin-top:0">Budget vs Actual</h2>
<p class="muted">Compares the <a href="/expense.html">Income &amp; Expenses</a> tab's own planning assumptions -- the same inflation-aware annual figures the plan's simulation draws its withdrawal need from -- against what <a href="/real-expenditure.html">Actual Spending</a>'s synced transactions say actually happened. This is a TOTALS comparison, not category-by-category: an expense row's category (Fixed/Variable/...) and a transaction's category (Food/Travel/...) are two different taxonomies that were never meant to line up one-to-one.</p>
{no_transactions_note}
<div class="tiles">{tiles_html}</div>
<p class="muted">"Projected full-year" paces this year's actual-so-far figure out to a full year ({days_elapsed} of {days_in_year} days elapsed) -- a rough estimate early in the year, more accurate as it goes. The current (still in progress) month in the tables below will naturally look under budget until it's over.</p>
<div class="card">
{expense_table_html}
{income_table_html}
</div>
"""
    return _shell(title="Budget vs Actual", active="budget-vs-actual.html", body=body)
