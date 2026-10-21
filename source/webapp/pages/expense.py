"""The Income & Expenses tab: editable recurring line-item tables with
per-item inflation handling."""

from __future__ import annotations

import html

from source.common import linked_data
from source.reporting import real_link
from source.reporting.aggregate import build_summary
from source.webapp.pages.benefits_card import double_social_security_html
from source.reporting.monte_carlo import annual_line_item_total, effective_line_item_amount
from source.webapp.render_helpers import (
    _donut_chart_html,
    _editable_checkbox_cell,
    _editable_number_cell,
    _editable_text_cell,
    _grouped_slices,
    _money,
    _pct,
    _shell,
)


def _render_expense_page() -> str:
    s = build_summary()
    assumptions = s["assumptions"]
    this_year = s["this_year"]
    inflation_rate = float(assumptions.get("inflation_rate") or 0.0)

    transactions = linked_data.read_transactions()
    real_cats = real_link.real_categories(transactions)
    expense_section_html = _line_item_section_html(
        section="expenses", title="Expenses", empty_label="expense", rows=s["expenses"],
        this_year=this_year, inflation_rate=inflation_rate, add_label="expense",
        transactions=transactions, real_cats=real_cats["expenses"],
    )
    income_section_html = _line_item_section_html(
        section="income", title="Income", empty_label="income", rows=s["income"],
        this_year=this_year, inflation_rate=inflation_rate, show_include_in_monte_carlo=True,
        transactions=transactions, real_cats=real_cats["income"],
    )

    # By category, nominal (annual_amount, not this-year-inflated) -- same
    # figure the tables' own "Total (nominal)" footer row sums, and the
    # same basis the Summary tab's own "Expenses by category" bar chart
    # already uses (see summary.py's _summary_insight_html), so this
    # doesn't introduce a second, disagreeing way to add up a category.
    # Donut, not bar, since each tab's own category count is normally
    # well under the ~6-7 slice legibility limit _grouped_slices'
    # max_slices default folds anything past into "Other" -- a bar chart
    # is what the Summary tab reaches for once a page has too many
    # distinct categories to read as wedges (dataviz skill).
    expense_chart_html = _donut_chart_html(
        "Expenses by category (annual, nominal)",
        _grouped_slices(s["expenses"], key="category", value_key="annual_amount"),
        dim="expense-category",
    )
    income_chart_html = _donut_chart_html(
        "Income by category (annual, nominal)",
        _grouped_slices(s["income"], key="category", value_key="annual_amount"),
        dim="income-category",
    )

    body = f"""
{_LI_CSS}
<h2 style="margin-top:0">Income &amp; Expenses</h2>
<p class="muted">Each row is an annual amount, optionally scoped to a year range (blank = every year). Inflating rows grow with the Inflation % below; the <a href="/monte-carlo.html">Will my money last?</a> tab nets Income against Expenses each year.</p>
<details class="how-it-works"><summary>How this works</summary><p class="muted">Each row is an annual amount, optionally scoped to a year range (leave blank for "every year"). Check "Inflates" and set a Base Year (e.g. 2026, the year the amount is denominated in) to have a row grow with the Inflation % assumption below every simulated year -- otherwise it stays flat at the typed-in amount, same as before. Setting a row's Category to "Variable" does this for you automatically (checks Inflates and fills in Base Year if it's still blank) -- for both Expenses and Income -- since a Variable-cost row is, by definition, one that's expected to grow with inflation; a Fixed row can still opt in by hand. Change the Inflation % below to update the assumption everywhere it's used (this tab's totals, Summary, and Will my money last?). The Will my money last? tab nets Income against Expenses for each simulated year's withdrawal need -- uncheck an Income row's "In simulation?" to leave it out of that net (e.g. money you don't want to rely on for a projection), while still tracking it here. On by default, since every income row has always counted.</p>
<p class="muted"><strong>Rental income:</strong> any income row whose name or category contains "rent" is treated as rental income. Enter it as the cash you actually receive after property costs (mortgage payment, property tax, insurance, upkeep). For taxes, the plan treats it as untaxed while that property's loan is running (mortgage interest and depreciation shelter it) and as fully taxed ordinary income from the year after the "Loan ends" year you set on the <a href="/real-estate.html">Real Estate</a> tab; a property with no loan end year is taxed every year. Depreciation recapture on a later sale is not modeled.</p>
</details>
<div class="tiles">
  <div class="tile"><div class="label">{this_year} income</div><div class="value">{_money(s["this_year_income"])}</div></div>
  <div class="tile"><div class="label">{this_year} expense need</div><div class="value">{_money(s["this_year_expense_need"])}</div></div>
  <div class="tile"><div class="label">{this_year} net withdrawal need</div><div class="value">{_money(s["this_year_net_need"])}</div></div>
  <div class="tile">
    <div class="label">Inflation %</div>
    <form class="inline" style="margin-top:4px; gap:6px;" onsubmit="event.preventDefault();
      postJSON('/api/assumptions', {{inflation_rate_pct: this.inflation_rate_pct.value}})
        .then(function() {{ location.reload(); }})
        .catch(function(e) {{ alert(e.message); }});">
      <input name="inflation_rate_pct" type="number" step="0.01" value="{_pct(assumptions, 'inflation_rate', 0.03)}" style="width:70px; font-size:13px; padding:3px 5px;">
      <button type="submit" class="primary" style="padding:4px 10px; font-size:12px;">Save</button>
    </form>
  </div>
</div>
{double_social_security_html(s["income"], assumptions)}
<div class="card" id="ss-pointer"><p style="margin:0"><strong>Social Security and Medicare</strong> are set on the <a href="/monte-carlo.html#benefits-planner">Will my money last?</a> tab. Rows marked &ldquo;set by the planner&rdquo; below change when you change them there.</p></div>
{income_section_html}
{expense_section_html}
<div class="group-section">
{income_chart_html}
{expense_chart_html}
</div>
"""
    return _shell(title="Income & Expenses", active="expense.html", body=body)

def _inflation_note_html(e: dict, this_year: int, inflation_rate: float) -> str:
    """A small muted note under an inflating row's Annual Amount cell
    showing what it actually comes out to this year -- e.g. a 2026-basis
    Fixed cost row is worth more by the time the plan's current_year
    rolls around, and this is the number annual_expense_need/
    annual_income_need actually uses (see monte_carlo._effective_line_item_amount)."""
    if not e.get("inflates") or e.get("base_year") is None:
        return ""
    this_year_value = effective_line_item_amount(e, this_year, inflation_rate)
    return f'<br><span class="muted" style="font-size:11px">{this_year} value: {_money(this_year_value)}</span>'

_LI_CSS = """
<style>
.li-card { border:1px solid var(--border); border-radius:var(--radius-lg); background:var(--surface); box-shadow:var(--shadow-sm);
  margin:18px 0; overflow:hidden; }
.li-head { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; padding:14px 18px;
  border-bottom:1px solid var(--border); }
.li-head h2 { margin:0; font-size:18px; letter-spacing:-0.01em; }
.li-chips { display:flex; gap:8px; flex-wrap:wrap; margin-top:6px; }
.li-chip { font-size:12px; color:var(--ink-soft); background:var(--surface-alt); border:1px solid var(--border); border-radius:99px; padding:2px 10px; }
.li-chip strong { color:var(--ink); }
.li-scroll { overflow-x:auto; }
.li-table { margin:0; table-layout:fixed; min-width:980px; }
.li-table th, .li-table td { padding:7px 8px; vertical-align:middle; }
.li-table tbody tr:nth-child(even) { background:var(--surface-alt); }
.li-table tbody tr:hover { background:var(--brand-soft); }
.li-table td input[type=text], .li-table td input[type=number], .li-table td select { width:100%; box-sizing:border-box; font-size:13px; padding:4px 6px; }
.li-table td.num input { text-align:right; font-variant-numeric:tabular-nums; }
.li-years { display:flex; align-items:center; gap:4px; white-space:nowrap; }
.li-years input { width:56px !important; border-color:var(--border) !important; }
.li-sub { font-size:11px; color:var(--ink-muted); margin-top:2px; line-height:1.3; }
.li-link select { font-size:12px !important; }
.li-actual { font-size:11px; color:var(--ink-soft); margin-top:3px; line-height:1.35; }
.li-actual button { font-size:11px; padding:1px 8px; margin-left:4px; border-radius:99px; }
.li-table tfoot td { border-top:2px solid var(--border); }
.li-empty { padding:22px 18px; color:var(--ink-muted); }
</style>
"""


def _actual_html(e: dict, section: str, transactions: list[dict]) -> str:
    """Under the link picker: what the linked real category actually came to
    over the last 12 months, how it compares with the plan, and a button to
    copy it into the plan."""
    cat = (e.get("linked_category") or "").strip()
    if not cat:
        return ""
    actual = real_link.actual_last_12_months(transactions, section, cat)
    if not actual:
        return '<div class="li-actual muted">No matching real transactions in the last 12 months.</div>'
    planned = float(e.get("annual_amount") or 0.0)
    diff = actual["annual"] - planned
    if abs(diff) < 1:
        verdict = "matches the plan"
    elif section == "expenses":
        verdict = f"{_money(abs(diff))} {'over' if diff > 0 else 'under'} the plan"
    else:
        verdict = f"{_money(abs(diff))} {'above' if diff > 0 else 'below'} the plan"
    basis = "" if actual["months"] >= 12 else f" (from {actual['months']} mo)"
    return (
        f'<div class="li-actual">Real: <strong>{_money(actual["annual"])}</strong>/yr{basis} &middot; {verdict}'
        f'<button type="button" class="chip" title="Copy the real figure into Annual Amount" '
        f'onclick="updateField(\'{section}\', {e["id"]}, \'annual_amount\', {round(actual["annual"], 2)})">Use</button></div>'
    )


def _line_item_section_html(
    *, section: str, title: str, empty_label: str, rows: list, this_year: int, inflation_rate: float,
    add_label: str | None = None, show_include_in_monte_carlo: bool = False,
    transactions: list[dict] | None = None, real_cats: list[str] | None = None,
) -> str:
    """Shared table markup for the Income & Expenses tab's two line-item sections
    (Income and Expenses) -- same columns, same inflation controls, just a
    different section name/title/empty-state text, so the two can never
    drift into different shapes. Adding a new row goes through the shared
    "+ Add" modal (see PAGE_SHELL) -- the button sits in the card header, so
    it is always at the top of its table.

    show_include_in_monte_carlo adds one extra column -- "In plan?" -- only
    meaningful (and only passed True) for Income: whether a row nets
    against the withdrawal need in the Monte Carlo / historical stress test
    simulations (income.include_in_monte_carlo). Expense rows have no such
    toggle -- every expense always counts toward the need.

    Each row can optionally be linked to a real (synced) category -- see
    source.reporting.real_link -- to compare plan against actual spending
    or income."""
    transactions = transactions or []
    real_cats = real_cats or []
    existing_categories = sorted({(e["category"] or "").strip() for e in rows if (e["category"] or "").strip()})
    category_options_html = "".join(f'<option value="{html.escape(c)}">' for c in existing_categories)

    def link_cell(e):
        current = (e.get("linked_category") or "").strip()
        cats = list(real_cats)
        if current and current not in cats:
            cats.append(current)
        opts = '<option value="">Not linked</option>' + "".join(
            f'<option value="{html.escape(c)}"{" selected" if c == current else ""}>{html.escape(c)}</option>' for c in cats
        )
        return (
            f'<div class="li-link"><select data-field="linked_category" '
            f'onchange="updateField(\'{section}\', {e["id"]}, \'linked_category\', this.value)">{opts}</select></div>'
            + _actual_html(e, section, transactions)
        )

    def row_html(e):
        # Rows the Social Security planner writes are read-only here: it
        # replaces them every time it saves, so an edit would be lost.
        locked = e.get("source") == "benefits-planner"

        def plain(value, *, money=False):
            if value in (None, ""):
                return ""
            return html.escape(_money(value) if money else str(value))

        if locked:
            name_cell = plain(e["name"])
            category_cell = plain(e["category"])
            amount_cell = plain(e["annual_amount"], money=True) + _inflation_note_html(e, this_year, inflation_rate)
            start_cell = plain(e["start_year"])
            end_cell = plain(e["end_year"])
            base_year_cell = plain(e["base_year"])
            notes_cell = html.escape(e["notes"] or "")
        else:
            name_cell = _editable_text_cell(section, e["id"], "name", e["name"])
            category_cell = _editable_category_cell(section, e["id"], e["category"], current_year=this_year)
            amount_cell = (
                _editable_number_cell(section, e["id"], "annual_amount", e["annual_amount"], width="100%", money=True)
                + _inflation_note_html(e, this_year, inflation_rate)
            )
            start_cell = _editable_number_cell(
                section, e["id"], "start_year", e["start_year"], width="62px", step="1", blank_if_none=True,
            )
            end_cell = _editable_number_cell(
                section, e["id"], "end_year", e["end_year"], width="62px", step="1", blank_if_none=True,
            )
            base_year_cell = _editable_number_cell(
                section, e["id"], "base_year", e["base_year"], width="100%", step="1", blank_if_none=True,
            )
            notes_cell = _editable_text_cell(section, e["id"], "notes", e["notes"])
        # Both ends blank means "applies every year" -- say so rather than
        # leaving two empty boxes that read as missing data.
        every_year_note = (
            '<div class="li-sub">every year</div>'
            if e["start_year"] in (None, "") and e["end_year"] in (None, "") else ""
        )
        imported_tag = (
            '<div class="li-sub">set by the planner &middot; <a href="/monte-carlo.html#benefits-planner">change</a></div>'
            if locked else
            f'<div class="li-sub">{html.escape(e["source"])}</div>' if e.get("source") and e["source"] != "manual" else ""
        )
        mc_td = (
            f'<td style="text-align:center">{_editable_checkbox_cell(section, e["id"], "include_in_monte_carlo", e.get("include_in_monte_carlo"))}</td>'
            if show_include_in_monte_carlo else ""
        )
        return (
            f'<tr><td class="check-col"><input type="checkbox" class="row-check" '
            f'data-section="{section}" data-id="{e["id"]}"></td>'
            f'<td>{name_cell}{imported_tag}</td><td>{category_cell}</td>'
            f'<td class="num">{amount_cell}</td>'
            f'<td><div class="li-years">{start_cell}&ndash;{end_cell}</div>{every_year_note}</td>'
            f'<td class="num">{base_year_cell}</td>'
            f'<td style="text-align:center">{_editable_checkbox_cell(section, e["id"], "inflates", e["inflates"])}</td>'
            f'{mc_td}'
            f'<td>{link_cell(e)}</td>'
            f'<td>{notes_cell}</td></tr>'
        )

    ncols = 10 if show_include_in_monte_carlo else 9
    rows_html = "".join(row_html(e) for e in rows) or (
        f'<tr><td colspan="{ncols}" class="li-empty">No {html.escape(empty_label)} line items yet. Use the Add button above.</td></tr>'
    )
    annual_total = sum(e["annual_amount"] or 0 for e in rows)
    # Same rule annual_expense_need/annual_income_need apply (a row with
    # a year range only counts within it, e.g. Social Security before it
    # starts) -- not just a raw sum of every row's inflated amount
    # regardless of whether it's even in effect this year.
    this_year_total = annual_line_item_total(rows, this_year, inflation_rate)
    trailing = ncols - 4
    mc_th = '<th>In simulation?</th>' if show_include_in_monte_carlo else ""
    mc_col = '<col style="width:84px">' if show_include_in_monte_carlo else ""
    word = "item" if len(rows) == 1 else "items"

    return f"""
<div class="li-card" id="{section}-card">
<div class="li-head">
  <div>
    <h2>{html.escape(title)}</h2>
    <div class="li-chips">
      <span class="li-chip"><strong>{len(rows)}</strong> {word}</span>
      <span class="li-chip">Per year (nominal) <strong>{_money(annual_total)}</strong></span>
      <span class="li-chip">{this_year} value <strong>{_money(this_year_total)}</strong></span>
    </div>
  </div>
  <div style="display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
    <button type="button" class="danger li-del" data-section="{section}" onclick="deleteSelectedRows('{section}')">Delete selected (0)</button>
    <button type="button" class="primary" onclick="openAddModal('{section}')">+ Add {html.escape(add_label or title.lower())}</button>
  </div>
</div>
<div class="li-scroll">
<table class="sortable li-table">
<colgroup><col style="width:34px"><col style="width:17%"><col style="width:12%"><col style="width:104px"><col style="width:128px"><col style="width:72px"><col style="width:70px">{mc_col}<col style="width:156px"><col></colgroup>
<thead><tr><th class="check-col"><input type="checkbox" class="select-all-check"></th><th>Name</th><th>Category</th>
<th class="num">Annual Amount</th><th>Years</th><th class="num">Base Year</th><th>Inflates?</th>{mc_th}<th>Link to real {html.escape(empty_label)}</th><th>Notes</th></tr></thead>
<tbody>{rows_html}</tbody>
<tfoot><tr><td colspan="3">Total (nominal)</td><td class="num">{_money(annual_total)}</td><td colspan="{trailing}"></td></tr>
<tr><td colspan="3">Total ({this_year} value)</td><td class="num">{_money(this_year_total)}</td><td colspan="{trailing}"></td></tr></tfoot>
</table>
</div>
<datalist id="{section}-categories">{category_options_html}</datalist>
</div>
"""


def _editable_category_cell(section: str, item_id: int, category: str, *, current_year: int) -> str:
    """Like _editable_text_cell, but for the Expense/Income tabs' Category
    column specifically -- typing/selecting "Variable" (case-insensitive,
    matching the xlsx importer's own "Fixed"/"Variable" expense labels)
    also flips that row's Inflates checkbox on and, if Base Year is still
    blank, fills it with the plan's current year, so a Variable-cost row
    starts growing with inflation right away instead of silently staying
    flat until the user separately checks "Inflates" and types a base
    year. Goes through the dedicated updateCategoryField() JS helper
    (not the generic updateField()) so this one extra side effect stays
    in a single place rather than duplicated per caller."""
    escaped = html.escape(category or "")
    return (
        f'<input type="text" value="{escaped}" list="{section}-categories" data-field="category" '
        f'style="width:100%; font-size:12px; padding:3px 4px; box-sizing:border-box;" '
        f'onchange="updateCategoryField(\'{section}\', {item_id}, this, {current_year})">'
    )
