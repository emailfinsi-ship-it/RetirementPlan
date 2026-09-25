"""The Real Expenditure tab: every transaction Plaid has synced for a
credit card, checking, or investment account (any linked Item whose own
`products` includes "transactions" -- see source.collector.sync._sync_
transactions_for_item), auto-categorized where Plaid's own personal_
finance_category has an opinion (source.common.plaid_categorize),
rolled up into monthly and annual real-spend totals, alongside the full
transaction list itself.

A transfer between the user's own linked accounts, or a credit card
bill payment, is automatically left out of the totals (so paying a
credit card from checking doesn't get counted as spending twice) --
still shown in the full list, just marked "excluded", and correctable
by hand via the bulk bar below if Plaid's own tagging ever gets one
wrong. See tests.test_dashboard for the coverage on both the rendering
here and the /api/classify-transaction-* endpoints in dashboard.py that
back the bulk bar's buttons.
"""

from __future__ import annotations

import html
from collections import defaultdict

from source.common import linked_data
from source.webapp.render_helpers import (
    _bar_chart_html,
    _grouped_slices,
    _money,
    _shell,
    _sync_now_button_html,
)


def _month_key(date: str) -> str:
    return (date or "")[:7] or "Unknown"


def _year_key(date: str) -> str:
    return (date or "")[:4] or "Unknown"


def _render_real_expenditure_page() -> str:
    transactions = linked_data.read_transactions()
    included = [t for t in transactions if not t["excluded_from_expense"]]

    monthly_totals: dict[str, float] = defaultdict(float)
    monthly_counts: dict[str, int] = defaultdict(int)
    for t in included:
        key = _month_key(t["date"])
        monthly_totals[key] += t["amount"]
        monthly_counts[key] += 1
    months_desc = sorted(monthly_totals, reverse=True)

    annual_totals: dict[str, float] = defaultdict(float)
    annual_counts: dict[str, int] = defaultdict(int)
    for t in included:
        key = _year_key(t["date"])
        annual_totals[key] += t["amount"]
        annual_counts[key] += 1
    years_desc = sorted(annual_totals, reverse=True)

    total_real_expenditure = sum(monthly_totals.values())
    excluded_total = sum(t["amount"] for t in transactions if t["excluded_from_expense"])

    # Chart-only spend value -- clamped at 0 rather than left negative
    # (_bar_chart_html assumes non-negative magnitudes, same as every
    # other bar chart in this app). The summary tables below always show
    # the true signed net (spend minus refunds); this clamp only affects
    # how a refund-heavy category/month draws as a bar.
    chart_rows = [{**t, "spend_for_chart": max(t["amount"], 0.0)} for t in included]
    category_chart_html = _bar_chart_html(
        "Real expenditure by category",
        _grouped_slices(chart_rows, key="category", value_key="spend_for_chart", max_slices=None),
        dim="expense-category",
    )
    # Chronological (oldest to newest), not magnitude-ranked like every
    # other chart on this page/app -- a spend trend reads left-to-right
    # by month, so this is built directly rather than through
    # _grouped_slices (which always sorts by value descending).
    month_slices = [
        (month, max(monthly_totals[month], 0.0), [month]) for month in sorted(monthly_totals)[-12:]
    ]
    monthly_chart_html = _bar_chart_html("Real expenditure by month (last 12)", month_slices, dim="expense-month")

    monthly_rows_html = "".join(
        f'<tr><td>{html.escape(month)}</td><td class="num">{_money(monthly_totals[month])}</td>'
        f'<td class="num">{monthly_counts[month]}</td></tr>'
        for month in months_desc
    ) or '<tr><td colspan="3" class="muted">No transactions yet.</td></tr>'

    annual_rows_html = "".join(
        f'<tr><td>{html.escape(year)}</td><td class="num">{_money(annual_totals[year])}</td>'
        f'<td class="num">{annual_counts[year]}</td></tr>'
        for year in years_desc
    ) or '<tr><td colspan="3" class="muted">No transactions yet.</td></tr>'

    # Every category already in use (across ALL transactions, including
    # excluded ones -- a transfer might still be worth a specific label),
    # offered as a <datalist> on the bulk-classify bar below, same
    # convenience every other category field in this app gets.
    known_categories = sorted({t["category"].strip() for t in transactions if t["category"].strip()})
    category_datalist_html = "".join(f"<option>{html.escape(c)}</option>" for c in known_categories)

    def _row_html(t):
        if t["excluded_from_expense"]:
            excluded_badge = (
                '<span class="muted" style="font-size:11px;">excluded'
                + (' (manual)' if t["excluded_edited_by_user"] else '') + '</span>'
            )
        else:
            excluded_badge = ""
        pending_badge = ' <span class="muted" style="font-size:11px;">pending</span>' if t["pending"] else ""
        category_label = html.escape(t["category"]) + (" *" if t["category_edited_by_user"] else "")
        description = html.escape(t["merchant_name"] or t["name"])
        return (
            f'<tr><td class="check-col"><input type="checkbox" class="transaction-check" '
            f'data-transaction-id="{html.escape(t["transaction_id"])}"></td>'
            f'<td>{html.escape(t["date"])}</td>'
            f'<td>{html.escape(t["institution"])}</td><td>{html.escape(t["account_name"])}</td>'
            f'<td>{description}{pending_badge}</td>'
            f'<td>{category_label}</td>'
            f'<td class="num">{_money(t["amount"])}</td>'
            f'<td>{excluded_badge}</td></tr>'
        )

    transactions_rows_html = "".join(_row_html(t) for t in transactions) or (
        '<tr><td colspan="8" class="muted">No transactions synced yet -- connect a credit card, checking, or '
        'investment account with the "transactions" product on <a href="/setup.html">Setup</a>, then use '
        '"Sync now" below.</td></tr>'
    )

    included_count = len(included)
    excluded_count = len(transactions) - included_count

    body = f"""
<h2 style="margin-top:0">Real Expenditure</h2>
<p class="muted">Every transaction Plaid has synced for a credit card, checking, or investment account that requested the "transactions" product -- auto-categorized from Plaid's own classification where it has one; select one or more rows below and use the bar that appears to retype the Category (already-used categories autocomplete). A transfer between your own linked accounts, or a credit card bill payment, is automatically left out of the totals below (so paying a credit card from checking doesn't get counted as spending twice) but still shown in the full list, marked "excluded" -- select it and use "Include in total" to correct it if Plaid got one wrong, or "Exclude from total"/"Reset to automatic" the other way. A new Item linked today can request "transactions" directly on Setup; one linked before this existed needs its own one-time "Enable Transactions" re-authorization there first.</p>
{_sync_now_button_html()}
<div class="group-section">
<div class="card" style="flex:1 1 220px;">
<h3 style="margin-top:0; font-size:13px;">Total real expenditure</h3>
<p style="font-size:22px; font-weight:600; margin:4px 0;">{_money(total_real_expenditure)}</p>
<p class="muted" style="margin:0;">Across {included_count} counted transaction{'s' if included_count != 1 else ''} -- {excluded_count} more excluded as transfers/card payments ({_money(excluded_total)}, not counted above).</p>
</div>
{category_chart_html}
</div>
<div class="group-section">
{monthly_chart_html}
</div>

<h2>Monthly summary</h2>
<table class="sortable">
<thead><tr><th>Month</th><th class="num">Real expenditure</th><th class="num">Transactions</th></tr></thead>
<tbody>{monthly_rows_html}</tbody>
</table>

<h2>Annual summary</h2>
<table class="sortable">
<thead><tr><th>Year</th><th class="num">Real expenditure</th><th class="num">Transactions</th></tr></thead>
<tbody>{annual_rows_html}</tbody>
</table>

<h2>All transactions</h2>
<div id="transaction-bulk-bar" class="industry-bulk-bar">
  <span class="bulk-count">0 selected</span>
  <input type="text" id="transaction-category-input" list="transaction-categories" placeholder="e.g. Groceries, Dining, Travel" disabled>
  <datalist id="transaction-categories">{category_datalist_html}</datalist>
  <button type="button" onclick="classifySelectedTransactions()" disabled>Set category</button>
  <button type="button" onclick="resetSelectedTransactionCategories()" disabled>Reset category</button>
  <button type="button" onclick="setSelectedTransactionsExcluded(true)" disabled>Exclude from total</button>
  <button type="button" onclick="setSelectedTransactionsExcluded(false)" disabled>Include in total</button>
  <button type="button" onclick="resetSelectedTransactionsExpenseFlag()" disabled>Reset to automatic</button>
  <button type="button" onclick="clearTransactionSelection()" disabled>Clear selection</button>
</div>
<table class="sortable">
<thead><tr><th class="check-col"><input type="checkbox" class="transaction-select-all"></th><th>Date</th><th>Institution</th><th>Account</th><th>Description</th><th>Category</th><th class="num">Amount</th><th>Status</th></tr></thead>
<tbody>{transactions_rows_html}</tbody>
</table>
<p class="muted">A category marked with * was set by hand and won't be overwritten by a future sync. Amounts follow Plaid's own convention -- positive is money out, negative is money in/a refund -- so a category or month's total already nets a refund against the spending it reverses.</p>
"""
    return _shell(title="Real Expenditure", active="real-expenditure.html", body=body)
