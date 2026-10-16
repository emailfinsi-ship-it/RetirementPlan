"""The Income/Expense tab: editable recurring line-item tables with
per-item inflation handling."""

from __future__ import annotations

import html

from source.reporting.aggregate import build_summary
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

    expense_section_html = _line_item_section_html(
        section="expenses", title="Expenses", empty_label="expense", rows=s["expenses"],
        this_year=this_year, inflation_rate=inflation_rate, add_label="expense",
    )
    income_section_html = _line_item_section_html(
        section="income", title="Income", empty_label="income", rows=s["income"],
        this_year=this_year, inflation_rate=inflation_rate, show_include_in_monte_carlo=True,
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
<h2 style="margin-top:0">Expense &amp; income</h2>
<p class="muted">Each row is an annual amount, optionally scoped to a year range (blank = every year). Inflating rows grow with the Inflation % below; the Monte Carlo tab nets Income against Expenses each year.</p>
<details class="how-it-works"><summary>How this works</summary><p class="muted">Each row is an annual amount, optionally scoped to a year range (leave blank for "every year"). Check "Inflates" and set a Base Year (e.g. 2026, the year the amount is denominated in) to have a row grow with the Inflation % assumption below every simulated year -- otherwise it stays flat at the typed-in amount, same as before. Setting a row's Category to "Variable" does this for you automatically (checks Inflates and fills in Base Year if it's still blank) -- for both Expenses and Income -- since a Variable-cost row is, by definition, one that's expected to grow with inflation; a Fixed row can still opt in by hand. Change the Inflation % below to update the assumption everywhere it's used (this tab's totals, Summary, and Monte Carlo). The Monte Carlo tab nets Income against Expenses for each simulated year's withdrawal need -- uncheck an Income row's "In simulation?" to leave it out of that net (e.g. money you don't want to rely on for a projection), while still tracking it here. On by default, since every income row has always counted.</p>
<p class="muted"><strong>Rental income:</strong> any income row whose name or category contains "rent" is treated as rental income. Enter it as the cash you actually receive after property costs (mortgage payment, property tax, insurance, upkeep). For taxes, the plan treats it as untaxed while that property's loan is running (mortgage interest and depreciation shelter it) and as fully taxed ordinary income from the year after the "Loan ends" year you set on the <a href="/real-estate.html">Real Estate</a> tab; a property with no loan end year is taxed every year. Depreciation recapture on a later sale is not modeled.</p>
</details>
<div class="tiles">
  <div class="tile"><div class="label">{this_year} expense need</div><div class="value">{_money(s["this_year_expense_need"])}</div></div>
  <div class="tile"><div class="label">{this_year} income</div><div class="value">{_money(s["this_year_income"])}</div></div>
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
<div class="group-section">
{expense_chart_html}
{income_chart_html}
</div>
{expense_section_html}
{income_section_html}
"""
    return _shell(title="Income/Expense", active="expense.html", body=body)

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

def _line_item_section_html(
    *, section: str, title: str, empty_label: str, rows: list, this_year: int, inflation_rate: float,
    add_label: str | None = None, show_include_in_monte_carlo: bool = False,
) -> str:
    """Shared table markup for the Expense tab's two line-item sections
    (Expenses and Income) -- same columns, same inflation controls, just a
    different section name/title/empty-state text, so the two can never
    drift into different shapes. Adding a new row goes through the
    shared "+ Add" modal (see PAGE_SHELL) rather than a form of its own
    here -- category_placeholder/name_placeholder for that kind live in
    the modal's own ADD_LINE_TEXT JS map now.

    show_include_in_monte_carlo adds one extra column -- "In simulation?"
    -- only meaningful (and only passed True) for Income: whether a row
    nets against the withdrawal need in the Monte Carlo / historical
    stress test simulations (income.include_in_monte_carlo, defaults on
    -- see source.reporting.aggregate.build_summary's
    income_for_simulation). Expense rows have no such toggle -- every
    expense always counts toward the need."""
    existing_categories = sorted({(e["category"] or "").strip() for e in rows if (e["category"] or "").strip()})
    category_options_html = "".join(f'<option value="{html.escape(c)}">' for c in existing_categories)
    mc_th = '<th>In simulation?</th>' if show_include_in_monte_carlo else ""

    def row_html(e):
        # Every field here (except Source, which is bookkeeping --
        # "manual" vs "imported") is inline-editable via the shared
        # updateField()/updateCategoryField() JS -- so correcting a typo
        # or reclassifying a row never requires deleting and re-adding
        # it. start_year/end_year/base_year use blank_if_none so an
        # unset year shows as an empty box, not a misleading "0" (which
        # would also look "already filled" to the Variable auto-inflate
        # JS's emptiness check).
        name_cell = _editable_text_cell(section, e["id"], "name", e["name"], width="120px")
        category_cell = _editable_category_cell(section, e["id"], e["category"], current_year=this_year)
        amount_cell = (
            _editable_number_cell(section, e["id"], "annual_amount", e["annual_amount"], width="95px")
            + _inflation_note_html(e, this_year, inflation_rate)
        )
        start_cell = _editable_number_cell(
            section, e["id"], "start_year", e["start_year"], width="58px", step="1", blank_if_none=True,
        )
        end_cell = _editable_number_cell(
            section, e["id"], "end_year", e["end_year"], width="58px", step="1", blank_if_none=True,
        )
        base_year_cell = _editable_number_cell(
            section, e["id"], "base_year", e["base_year"], width="70px", step="1", blank_if_none=True,
        )
        notes_cell = _editable_text_cell(section, e["id"], "notes", e["notes"], width="110px")
        mc_td = (
            f'<td>{_editable_checkbox_cell(section, e["id"], "include_in_monte_carlo", e.get("include_in_monte_carlo"))}</td>'
            if show_include_in_monte_carlo else ""
        )
        return (
            f'<tr><td class="check-col"><input type="checkbox" class="row-check" '
            f'data-section="{section}" data-id="{e["id"]}"></td>'
            f'<td>{name_cell}</td><td>{category_cell}</td>'
            f'<td class="num">{amount_cell}</td>'
            f'<td class="num">{start_cell}&ndash;{end_cell}</td>'
            f'<td class="num">{base_year_cell}</td>'
            f'<td>{_editable_checkbox_cell(section, e["id"], "inflates", e["inflates"])}</td>'
            f'{mc_td}'
            f'<td>{html.escape(e["source"])}</td><td>{notes_cell}</td></tr>'
        )

    rows_html = "".join(row_html(e) for e in rows) or (
        f'<tr><td colspan="{10 if show_include_in_monte_carlo else 9}" class="muted">No {html.escape(empty_label)} line items yet.</td></tr>'
    )
    annual_total = sum(e["annual_amount"] or 0 for e in rows)
    # Same rule annual_expense_need/annual_income_need apply (a row with
    # a year range only counts within it, e.g. Social Security before it
    # starts) -- not just a raw sum of every row's inflated amount
    # regardless of whether it's even in effect this year.
    this_year_total = annual_line_item_total(rows, this_year, inflation_rate)
    footer_trailing_colspan = 6 if show_include_in_monte_carlo else 5

    return f"""
<h2>{html.escape(title)}</h2>
<table class="sortable">
<thead><tr><th class="check-col"><input type="checkbox" class="select-all-check"></th><th>Name</th><th>Category</th>
<th class="num">Annual Amount</th><th>Years</th><th class="num">Base Year</th><th>Inflates?</th>{mc_th}<th>Source</th><th>Notes</th></tr></thead>
<tbody>{rows_html}</tbody>
<tfoot><tr><td colspan="3">Total (nominal)</td><td class="num">{_money(annual_total)}</td><td colspan="{footer_trailing_colspan}"></td></tr>
<tr><td colspan="3">Total ({this_year} value)</td><td class="num">{_money(this_year_total)}</td><td colspan="{footer_trailing_colspan}"></td></tr></tfoot>
</table>
<datalist id="{section}-categories">{category_options_html}</datalist>
<div class="add-shortcut-row">
  <button type="button" class="primary" onclick="openAddModal('{section}')">+ Add {html.escape(add_label or title.lower())}</button>
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
