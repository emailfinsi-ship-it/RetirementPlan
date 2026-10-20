"""The Actual Spending tab: every transaction Plaid has synced for a
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
)


def _month_key(date: str) -> str:
    return (date or "")[:7] or "Unknown"


def _year_key(date: str) -> str:
    return (date or "")[:4] or "Unknown"


def _duplicate_counts(transactions: list[dict]) -> dict[str, int]:
    """transaction_id -> how many transactions share its exact account_id/
    date/amount/name -- Plaid still assigns each one its own distinct
    transaction_id (so our sync correctly stores both as separate rows,
    same as any two genuinely different transactions), but two this
    alike are worth flagging for a person's own judgment call: a real
    second charge that day, or a look-alike that should be excluded so
    it isn't double-counted. Only ever a *flag* -- nothing here is
    hidden or auto-excluded; see the row's own "Exclude this one" quick
    action (excludeOneTransaction() in shell.py) for that."""
    groups: dict[tuple, list[str]] = defaultdict(list)
    for t in transactions:
        key = (t["account_id"], t["date"], t["amount"], t["name"])
        groups[key].append(t["transaction_id"])
    return {tid: len(ids) for ids in groups.values() if len(ids) > 1 for tid in ids}


def _render_real_expenditure_page() -> str:
    transactions = linked_data.read_transactions()
    included = [t for t in transactions if not t["excluded_from_expense"]]
    duplicate_counts = _duplicate_counts(transactions)

    # Split every counted transaction into real expense vs real income
    # (see linked_data.read_transactions' own "is_real_income" field,
    # which is broader than a plain category=="Income" check -- it also
    # catches inbound money Plaid couldn't classify into any real
    # spending category at all, rather than letting it silently vanish
    # into whatever expense-sounding category a name-only guess picked).
    monthly_totals: dict[str, float] = defaultdict(float)
    monthly_income_totals: dict[str, float] = defaultdict(float)
    monthly_counts: dict[str, int] = defaultdict(int)
    for t in included:
        key = _month_key(t["date"])
        monthly_counts[key] += 1
        if t["is_real_income"]:
            monthly_income_totals[key] += -t["amount"]
        else:
            monthly_totals[key] += t["amount"]
    months_desc = sorted(set(monthly_totals) | set(monthly_income_totals), reverse=True)

    annual_totals: dict[str, float] = defaultdict(float)
    annual_income_totals: dict[str, float] = defaultdict(float)
    annual_counts: dict[str, int] = defaultdict(int)
    for t in included:
        key = _year_key(t["date"])
        annual_counts[key] += 1
        if t["is_real_income"]:
            annual_income_totals[key] += -t["amount"]
        else:
            annual_totals[key] += t["amount"]
    years_desc = sorted(set(annual_totals) | set(annual_income_totals), reverse=True)

    total_real_expenditure = sum(monthly_totals.values())
    total_real_income = sum(monthly_income_totals.values())
    excluded_total = sum(t["amount"] for t in transactions if t["excluded_from_expense"])

    # Chart-only spend value -- clamped at 0 rather than left negative
    # (_bar_chart_html assumes non-negative magnitudes, same as every
    # other bar chart in this app). The summary tables below always show
    # the true signed net (spend minus refunds); this clamp only affects
    # how a refund-heavy category/month draws as a bar. Real-income
    # transactions are left out of this chart entirely -- they're not
    # spending, whatever category they happen to carry.
    chart_rows = [{**t, "spend_for_chart": max(t["amount"], 0.0)} for t in included if not t["is_real_income"]]
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
        (month, max(monthly_totals.get(month, 0.0), 0.0), [month]) for month in sorted(monthly_totals)[-12:]
    ]
    monthly_chart_html = _bar_chart_html("Real expenditure by month (last 12)", month_slices, dim="expense-month")

    # Mirrors the two expense charts above, but for real income -- a
    # category breakdown here is worth more than it sounds: most rows
    # in it should just be "Income", so a category showing up here that
    # ISN'T "Income" (a deposit Plaid couldn't classify, see is_real_
    # income) is a direct visual pointer at exactly the kind of
    # transaction "Categorize similar" (below) exists to fix.
    income_chart_rows = [{**t, "income_for_chart": -t["amount"]} for t in included if t["is_real_income"]]
    income_category_chart_html = _bar_chart_html(
        "Real income by category",
        _grouped_slices(income_chart_rows, key="category", value_key="income_for_chart", max_slices=None),
        dim="income-category",
    )
    # Chronological, same reasoning as month_slices above. Real income
    # is never negative by construction (each entry is already sign-
    # flipped positive), so there's no refund-style clamp needed here.
    income_month_slices = [
        (month, monthly_income_totals.get(month, 0.0), [month]) for month in sorted(monthly_income_totals)[-12:]
    ]
    income_monthly_chart_html = _bar_chart_html(
        "Real income by month (last 12)", income_month_slices, dim="income-month",
    )

    monthly_rows_html = "".join(
        f'<tr><td>{html.escape(month)}</td><td class="num">{_money(monthly_totals.get(month, 0.0))}</td>'
        f'<td class="num">{_money(monthly_income_totals.get(month, 0.0))}</td>'
        f'<td class="num">{monthly_counts[month]}</td></tr>'
        for month in months_desc
    ) or '<tr><td colspan="4" class="muted">No transactions yet.</td></tr>'

    annual_rows_html = "".join(
        f'<tr><td>{html.escape(year)}</td><td class="num">{_money(annual_totals.get(year, 0.0))}</td>'
        f'<td class="num">{_money(annual_income_totals.get(year, 0.0))}</td>'
        f'<td class="num">{annual_counts[year]}</td></tr>'
        for year in years_desc
    ) or '<tr><td colspan="4" class="muted">No transactions yet.</td></tr>'

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
        dup_count = duplicate_counts.get(t["transaction_id"])
        if dup_count:
            # Flag only -- never hides or auto-excludes anything (see
            # _duplicate_counts' own docstring). The quick-exclude action
            # is only offered when this row is still counted; an already-
            # excluded one has nothing left to do here.
            exclude_link = (
                f' <a href="#" class="muted" style="font-size:11px;" '
                f'onclick="excludeOneTransaction(\'{html.escape(t["transaction_id"])}\'); return false;">'
                f'exclude this one</a>' if not t["excluded_from_expense"] else ""
            )
            duplicate_badge = (
                f' <span class="muted" style="font-size:11px;" '
                f'title="{dup_count} transactions on this account share the same date, amount, and name">'
                f'possible duplicate ({dup_count}){exclude_link}</span>'
            )
        else:
            duplicate_badge = ""
        # A person's own explicit override (set via the bulk bar's "Mark
        # as income"/"Mark as expense") always wins in is_real_income()
        # itself, so it's worth surfacing on the row too -- otherwise
        # there'd be no visible difference between "counted as income
        # because of an override" and "counted as income because the
        # heuristic guessed right," and no way to tell at a glance which
        # rows to revisit if the override was a mistake.
        if t["income_kind_override"] == "income":
            override_badge = ' <span class="muted" style="font-size:11px;" title="Manually marked as income.">★ marked income</span>'
        elif t["income_kind_override"] == "expense":
            override_badge = ' <span class="muted" style="font-size:11px;" title="Manually marked as expense.">★ marked expense</span>'
        else:
            override_badge = ""
        if t["is_real_income"]:
            # Displayed as a plain positive figure (Plaid's own raw
            # convention has money-in as negative, which read as
            # confusing for what's obviously a deposit/paycheck) --
            # display-only: the signed amount is still what every total/
            # chart on this page and Budget vs Actual actually sums.
            amount_html = f'<span class="status-ok">+{html.escape(_money(-t["amount"], cents=True))}</span>'
            # Only flagged when the category itself doesn't already say
            # "Income" (and there's no override badge already saying so)
            # -- otherwise this would just repeat information already on
            # the row. This is exactly the case that used to go
            # uncounted: an inbound deposit Plaid couldn't classify,
            # guessed into some expense-sounding category by name alone.
            income_badge = (
                '' if t["category"].strip() == "Income" or override_badge else
                ' <span class="muted" style="font-size:11px;" '
                'title="Counted as real income even though its category isn\'t &quot;Income&quot; -- '
                'Plaid couldn\'t classify this one, and it\'s inbound money.">counted as income</span>'
            )
        else:
            amount_html = html.escape(_money(t["amount"], cents=True))
            income_badge = ""
        # "Categorize similar" -- one-click shortcut for source.common.
        # db.transactions.apply_category_rule_from_transaction: takes
        # THIS row's own already-set Category (retype it first with the
        # bulk-classify bar above if it isn't right yet) and saves it as
        # a keyword rule derived from this row's own merchant/name, then
        # applies it immediately to every other matching transaction
        # already synced (see categorizeSimilarTransactions() in
        # shell.py). Exactly the follow-up action for the bug this
        # page's own "Total real income" card exists to catch: fix one
        # occurrence, then propagate it to every other month's copy of
        # the same deposit/charge in one click.
        categorize_similar_link = (
            f' <a href="#" class="muted" style="font-size:11px;" '
            f'onclick="categorizeSimilarTransactions(\'{html.escape(t["transaction_id"])}\'); return false;" '
            f'title="Apply this transaction\'s own category to every other transaction whose name/merchant '
            f'matches -- now, and on future syncs.">categorize similar</a>'
        )
        # data-expense-category/data-expense-month and data-income-category/
        # data-income-month are only ever set on a row that actually
        # contributes its dollars to that specific chart (counted, i.e.
        # not excluded_from_expense, and split by is_real_income) -- kept
        # separate from the plain data-category/data-month below (every
        # row gets those, counted or not) precisely so clicking an
        # income-chart bar can never pull in an excluded or expense-side
        # row that merely happens to share the same category text (see
        # applyExpenditureFilters() in shell.py).
        month_key = html.escape(_month_key(t["date"]))
        contributes = not t["excluded_from_expense"]
        if contributes and t["is_real_income"]:
            split_attrs = f' data-income-category="{html.escape(t["category"])}" data-income-month="{month_key}"'
        elif contributes:
            split_attrs = f' data-expense-category="{html.escape(t["category"])}" data-expense-month="{month_key}"'
        else:
            split_attrs = ""
        # data-kind backs the "Income only"/"Expense only" quick filter
        # (applyExpenditureFilters' 'kind' dim) -- same "contributes" gate
        # as the split attrs above, so an excluded row (never counted as
        # either) simply has no data-kind and is left out of both filtered
        # views rather than guessed into one.
        kind_attr = f' data-kind="{"income" if t["is_real_income"] else "expense"}"' if contributes else ""
        return (
            f'<tr data-category="{html.escape(t["category"])}" data-month="{month_key}"{split_attrs}{kind_attr}>'
            f'<td class="check-col"><input type="checkbox" class="transaction-check" '
            f'data-transaction-id="{html.escape(t["transaction_id"])}"></td>'
            f'<td>{html.escape(t["date"])}</td>'
            f'<td>{html.escape(t["institution"])}</td><td>{html.escape(t["account_name"])}</td>'
            f'<td>{description}{pending_badge}{duplicate_badge}</td>'
            f'<td>{category_label}{income_badge}{override_badge}{categorize_similar_link}</td>'
            f'<td class="num">{amount_html}</td>'
            f'<td>{excluded_badge}</td></tr>'
        )

    transactions_rows_html = "".join(_row_html(t) for t in transactions) or (
        '<tr><td colspan="8" class="muted">No transactions synced yet -- connect a credit card, checking, or '
        'investment account with the "transactions" product on <a href="/setup.html">Setup</a>, then press '
        '"Sync now" (top right).</td></tr>'
    )

    included_count = len(included)
    excluded_count = len(transactions) - included_count
    duplicate_flagged_count = len(duplicate_counts)

    duplicate_note = (
        f'<p class="muted" style="margin:0;">{duplicate_flagged_count} transaction'
        f'{"s" if duplicate_flagged_count != 1 else ""} flagged "possible duplicate" below -- same account, date, '
        f'amount, and name as another transaction, but Plaid gave each its own distinct ID, so both are kept and '
        f'counted unless you exclude one by hand.</p>'
    ) if duplicate_flagged_count else ""

    body = f"""
<h2 style="margin-top:0">Actual Spending</h2>
<details class="how-it-works"><summary>How this works</summary><p class="muted">Every transaction Plaid has synced for a credit card, checking, or investment account that requested the "transactions" product -- auto-categorized from Plaid's own classification where it has one; select one or more rows below and use the bar that appears to retype the Category (already-used categories autocomplete). A transfer between your own linked accounts, or a credit card bill payment, is automatically left out of the totals below (so paying a credit card from checking doesn't get counted as spending twice) but still shown in the full list, marked "excluded" -- select it and use "Include in total" to correct it if Plaid got one wrong, or "Exclude from total"/"Reset to automatic" the other way. A new Item linked today can request "transactions" directly on Setup; one linked before this existed needs its own one-time "Enable Transactions" re-authorization there first.</p></details>
<div class="group-section">
<div class="card" style="flex:1 1 220px;">
<h3 style="margin-top:0; font-size:13px;">Total real expenditure</h3>
<p style="font-size:22px; font-weight:600; margin:4px 0;">{_money(total_real_expenditure)}</p>
<p class="muted" style="margin:0;">Across {included_count} counted transaction{'s' if included_count != 1 else ''} -- {excluded_count} more excluded as transfers/card payments ({_money(excluded_total)}, not counted above).</p>
{duplicate_note}
</div>
<div class="card" style="flex:1 1 220px;">
<h3 style="margin-top:0; font-size:13px;">Total real income</h3>
<p style="font-size:22px; font-weight:600; margin:4px 0;">{_money(total_real_income)}</p>
<p class="muted" style="margin:0;">Every counted deposit -- anything already categorized "Income," plus inbound money Plaid couldn't classify into a real spending category (so it can't silently disappear into an expense category by name-guess alone). The table below flags a row counted this second way, since its own category won't say "Income."</p>
</div>
{category_chart_html}
</div>
<div class="group-section">
{monthly_chart_html}
</div>
<div class="group-section">
{income_category_chart_html}
{income_monthly_chart_html}
</div>

<h2>Monthly summary</h2>
<table class="sortable">
<thead><tr><th>Month</th><th class="num">Real expenditure</th><th class="num">Real income</th><th class="num">Transactions</th></tr></thead>
<tbody>{monthly_rows_html}</tbody>
</table>

<h2>Annual summary</h2>
<table class="sortable">
<thead><tr><th>Year</th><th class="num">Real expenditure</th><th class="num">Real income</th><th class="num">Transactions</th></tr></thead>
<tbody>{annual_rows_html}</tbody>
</table>

<h2>All transactions</h2>
<p class="muted">Click a bar in any chart above (expense or income) to filter this list down to that category or month -- click it again (or "Clear all") to go back to everything.</p>
<div style="display:flex; align-items:center; gap:6px; margin:6px 0;">
<span class="muted">Show:</span>
<button type="button" id="expenditure-kind-filter-all" class="kind-filter-btn active" onclick="setExpenditureKindFilter('')">All</button>
<button type="button" id="expenditure-kind-filter-income" class="kind-filter-btn" onclick="setExpenditureKindFilter('income')">Income only</button>
<button type="button" id="expenditure-kind-filter-expense" class="kind-filter-btn" onclick="setExpenditureKindFilter('expense')">Expense only</button>
</div>
<div id="expenditure-filter-bar" class="filter-bar"></div>
<p id="real-expenditure-shown-count" class="muted"></p>
<div id="transaction-bulk-bar" class="industry-bulk-bar">
  <span class="bulk-count">0 selected</span>
  <input type="text" id="transaction-category-input" list="transaction-categories" placeholder="e.g. Groceries, Dining, Travel" disabled>
  <datalist id="transaction-categories">{category_datalist_html}</datalist>
  <button type="button" onclick="classifySelectedTransactions()" disabled>Set category</button>
  <button type="button" onclick="resetSelectedTransactionCategories()" disabled>Reset category</button>
  <button type="button" onclick="setSelectedTransactionsExcluded(true)" disabled>Exclude from total</button>
  <button type="button" onclick="setSelectedTransactionsExcluded(false)" disabled>Include in total</button>
  <button type="button" onclick="resetSelectedTransactionsExpenseFlag()" disabled>Reset to automatic</button>
  <button type="button" onclick="setSelectedTransactionsIncomeKind('income')" disabled title="Counts these rows as real income no matter what their category text says -- fixes a hand-typed category like &quot;salary&quot; or &quot;Rental-mp&quot; that doesn't happen to contain the word &quot;income&quot;.">Mark as income</button>
  <button type="button" onclick="setSelectedTransactionsIncomeKind('expense')" disabled>Mark as expense</button>
  <button type="button" onclick="setSelectedTransactionsIncomeKind('')" disabled title="Clears a manual income/expense override and goes back to the automatic category-text heuristic.">Auto-detect income/expense</button>
  <button type="button" onclick="clearTransactionSelection()" disabled>Clear selection</button>
</div>
<table id="real-expenditure-table" class="sortable">
<thead><tr><th class="check-col"><input type="checkbox" class="transaction-select-all"></th><th>Date</th><th>Institution</th><th>Account</th><th>Description</th><th>Category</th><th class="num">Amount</th><th>Status</th></tr></thead>
<tbody>{transactions_rows_html}</tbody>
</table>
<p class="muted">A category marked with * was set by hand and won't be overwritten by a future sync. A deposit/paycheck counted as real income (see "Total real income" above) displays here as a plain positive amount for readability; every other amount follows Plaid's own convention -- positive is money out, negative is money in/a refund -- so a category or month's expenditure total already nets a refund against the spending it reverses.</p>
<p class="muted">See <a href="/budget-vs-actual.html">Budget vs Actual</a> to compare this against what the Income &amp; Expenses tab's own assumptions planned for.</p>
"""
    return _shell(title="Actual Spending", active="real-expenditure.html", body=body)
