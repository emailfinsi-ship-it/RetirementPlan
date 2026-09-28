"""The Asset tab: editable per-category asset tables plus the
linked-institution balance sync that keeps them current."""

from __future__ import annotations

import html

from source.common import db, linked_data
from source.reporting.aggregate import (
    category_subtotals,
    effective_loan_balance,
    effective_tax_treatment,
    real_estate_equity,
)
from source.webapp.render_helpers import (
    _account_number_display,
    _asset_category_summary_html,
    _asset_rollup_summary_html,
    _editable_checkbox_cell,
    _editable_number_cell,
    _editable_select_cell,
    _editable_text_cell,
    _effective_balance_html,
    _line_chart_html,
    _link_select_html,
    _money,
    _shell,
    _TAX_TREATMENT_OPTIONS,
)


def _monthly_net_worth_points(snapshots: list[dict]) -> list[tuple[str, float]]:
    """Reduces source.common.db.net_worth_snapshots' one-row-per-day
    history down to one point per calendar month, for the "Net worth
    over time" chart below -- the LAST snapshot recorded in each month
    (i.e. that month's most up to date net worth), labeled "YYYY-MM"
    rather than a specific day since each point now represents a whole
    month, not one day. This is a display-only reduction: capture
    itself is untouched and still writes one row per day (see
    source.reporting.aggregate.capture_net_worth_snapshot), same as
    always -- nothing here changes what's stored, only what the chart
    plots. Relies on list_net_worth_snapshots' own ORDER BY
    snapshot_date (ascending), so simply overwriting each month's entry
    as we go leaves the last (most recent) row for that month."""
    by_month: dict[str, dict] = {}
    for row in snapshots:
        month = row["snapshot_date"][:7]  # "YYYY-MM-DD" -> "YYYY-MM"
        by_month[month] = row
    return [(month, row["net_worth"]) for month, row in sorted(by_month.items())]


_NET_WORTH_CHART_EMPTY_MESSAGE = (
    "Come back next month to see a trend here -- this chart plots one point per calendar month "
    "(this program still captures a snapshot every time it's opened or synced, same as always; "
    "there's just only one month's worth of it so far)."
)


def _render_asset_page() -> str:
    assets = db.list_line_items("assets")
    real_estate_rows = db.list_line_items("real_estate")
    linkable = linked_data.linkable_accounts()
    live_by_account_id = {a["account_id"]: a for a in linkable}
    assets = [_sync_linked_institution_fields(a, live_by_account_id, section="assets") for a in assets]
    assumptions = db.get_assumptions()

    asset_rows = [a for a in assets if a["kind"] != "liability"]
    liability_rows = [a for a in assets if a["kind"] == "liability"]

    # Both Assets and Liabilities share this one datalist (both kinds
    # live in the same "assets" section/table, just filtered by `kind` --
    # see asset_rows/liability_rows above) -- offered on each row's own
    # editable Category cell below, same convenience Expense/Income's
    # own Category column already gives (see expense.py's
    # existing_categories), so recategorizing a row (or fixing one that
    # imported into the wrong category, e.g. a credit card that landed
    # under "Loan") means picking from what already exists instead of
    # re-typing it exactly.
    existing_categories = sorted({(a["category"] or "").strip() for a in assets if (a["category"] or "").strip()})
    category_options_html = "".join(f'<option value="{html.escape(c)}">' for c in existing_categories)

    asset_category_groups = _group_by_category(asset_rows)
    # Sourced from aggregate.category_subtotals() -- the same helper
    # build_summary() uses for the Summary tab's own asset breakdown --
    # so the Asset tab's top Summary table, its per-category detail
    # tables below, and the Summary tab can never disagree with each
    # other.
    asset_category_subtotals = category_subtotals(asset_rows, live_by_account_id)
    asset_tables_html = "".join(
        _category_table_html(cat, rows, linkable, live_by_account_id, is_asset_table=True)
        for cat, rows in asset_category_groups
    ) or '<p class="muted">No asset line items yet -- add one below, or import your old workbook from Setup.</p>'
    asset_tables_html += f'<datalist id="assets-categories">{category_options_html}</datalist>'
    manual_asset_total = sum(subtotal for _, subtotal in asset_category_subtotals)
    real_estate_total = sum(
        real_estate_equity(r, loan_balance=effective_loan_balance(r, live_by_account_id)) for r in real_estate_rows
    )
    real_estate_line_html = _real_estate_summary_line_html(real_estate_total, len(real_estate_rows))
    asset_total = manual_asset_total + real_estate_total

    liability_tables_html = "".join(
        _category_table_html(cat, rows, linkable, live_by_account_id) for cat, rows in _group_by_category(liability_rows)
    ) or '<p class="muted">No liability line items yet.</p>'
    liability_total = sum(_effective_balance_html(a, live_by_account_id)[0] for a in liability_rows)

    # Per-row now, via each Asset row's own "In Monte Carlo?" checkbox --
    # not a category-list match (see source.reporting.aggregate.build_summary
    # for the matching Monte Carlo starting-balance logic).
    retirement_liquid_total = sum(
        _effective_balance_html(a, live_by_account_id)[0] for a in asset_rows if a.get("include_in_monte_carlo")
    )
    net_liquid_asset = retirement_liquid_total - liability_total
    asset_summary_html = _asset_category_summary_html(asset_category_subtotals, liability_total, net_liquid_asset)
    asset_rollup_html = _asset_rollup_summary_html(net_liquid_asset, real_estate_total)

    net_worth_history_html = _line_chart_html(
        "Net worth over time",
        _monthly_net_worth_points(db.list_net_worth_snapshots()),
        note="One point per calendar month (that month's latest value) -- captured automatically "
        "every time this program is opened or synced, nothing to set up.",
        empty_message=_NET_WORTH_CHART_EMPTY_MESSAGE,
    )

    body = f"""
<h2 style="margin-top:0">Assets</h2>
<p class="muted">Your own line items, grouped into their own table by category -- 401(k), brokerage, insurance, cash, anything else. Real estate is edited on its own tab. Use the "+ Add" button (bottom right of any page) to add a new asset or liability -- the Category you type there is what groups it into a table above, so reuse an existing one to add to that table, or type a new name to start a new one. Already have a row in the wrong category (e.g. an imported credit card that landed under "Loan")? Its Category cell is editable too -- change it and the row moves into the right table (and subtotal) on save, no need to delete and re-add it. Check "In Monte Carlo?" on a row to have its balance feed the Monte Carlo / historical stress test simulations' starting pools (Net Liquid Asset below reflects the same checkboxes) -- Tax treatment on a checked row decides which pool (tax-deferred / Roth / taxable) it belongs to.</p>
{asset_rollup_html}
{net_worth_history_html}
{asset_summary_html}
{asset_tables_html}
{real_estate_line_html}
<p class="status-line" style="font-weight:600">Total assets (including real estate equity): {_money(asset_total)}</p>
<div class="add-shortcut-row">
  <button type="button" class="primary" onclick="openAddModal('asset')">+ Add asset</button>
</div>

<h2>Liabilities</h2>
{liability_tables_html}
<p class="status-line" style="font-weight:600">Total liabilities: {_money(liability_total)}</p>
<div class="add-shortcut-row">
  <button type="button" onclick="openAddModal('liability')">+ Add liability</button>
</div>

<p class="muted">Your live linked account balances (read-only, pulled directly from Plaid) are on their own <a href="/linked-accounts.html">Linked Accounts</a> tab; investment holdings are on <a href="/linked-positions.html">Linked Positions</a>.</p>
"""
    return _shell(title="Asset", active="asset.html", body=body)

def _group_by_category(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Groups line items by their category, preserving the order each
    category first appears in (import order, then whatever order the
    user has since typed new ones in) -- no hardcoded category list to
    keep in sync, and it stays stable as new categories show up."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        cat = (row["category"] or "").strip() or "Uncategorized"
        groups.setdefault(cat, []).append(row)
    return list(groups.items())

def _sync_linked_institution_fields(row: dict, live_by_account_id: dict, *, section: str) -> dict:
    """Auto-populates Institution/Account # from the linked Plaid
    account's real institution name and account number the moment a row
    is linked -- so picking "Fidelity -- APPLE 401(K) PLAN" from the
    dropdown fills in "Fidelity"/"1234" instead of leaving the user to
    type it in by hand. Uses the full account number when Plaid's Auth
    product returned one for this account (checking/savings only --
    everything else only ever has the mask), same fallback as
    _account_number_display. Runs on every page load rather than only at
    link time, so it also self-heals rows that were linked before this
    existed (e.g. via the earlier link-account endpoint, which only set
    linked_account_id) and rows whose Auth data arrived on a later sync
    than the one that first linked them. Persists the correction so it
    sticks (and the editable Institution/Account # inputs show it);
    returns the row with the corrected values already applied in memory
    so this same render sees it immediately."""
    account_id = row.get("linked_account_id")
    if not account_id or account_id not in live_by_account_id:
        return row
    acc = live_by_account_id[account_id]
    institution = acc["institution"] or ""
    last4 = _account_number_display(acc["mask"], acc.get("account_number"), acc.get("is_tokenized_account_number", False))
    if (row.get("institution") or "") != institution or (row.get("last4") or "") != last4:
        db.update_line_item(section, row["id"], {"institution": institution, "last4": last4})
        row = {**row, "institution": institution, "last4": last4}
    return row

def _category_table_html(
    category: str, rows: list[dict], linkable: list[dict], live_by_account_id: dict, *, is_asset_table: bool = False,
) -> str:
    # Tax treatment and the "In Monte Carlo?" checkbox only apply to
    # asset tables -- a liability row is never one of the simulation's
    # starting pools, so it skips both columns entirely rather than
    # showing controls that wouldn't do anything.
    tax_treatment_th = '<th>Tax treatment</th>' if is_asset_table else ""
    mc_th = '<th>In Monte Carlo?</th>' if is_asset_table else ""

    def row_html(a):
        balance, balance_cell = _effective_balance_html(a, live_by_account_id)
        is_linked = bool(a.get("linked_account_id")) and a["linked_account_id"] in live_by_account_id
        # A linked row's balance tracks Plaid automatically -- editing it
        # by hand would just get silently overwritten next page load, so
        # only an unlinked row's Balance becomes an editable input.
        balance_display = (
            balance_cell if is_linked else _editable_number_cell("assets", a["id"], "balance", a["balance"])
        )
        tax_treatment_td = (
            f'<td>{_editable_select_cell("assets", a["id"], "tax_treatment", effective_tax_treatment(a, live_by_account_id), _TAX_TREATMENT_OPTIONS)}</td>'
            if is_asset_table else ""
        )
        mc_td = (
            f'<td>{_editable_checkbox_cell("assets", a["id"], "include_in_monte_carlo", a.get("include_in_monte_carlo"))}</td>'
            if is_asset_table else ""
        )
        return (
            f'<tr><td class="check-col"><input type="checkbox" class="row-check" '
            f'data-section="assets" data-id="{a["id"]}"></td>'
            f'<td>{_editable_text_cell("assets", a["id"], "name", a["name"], width="120px")}</td>'
            f'<td>{_editable_category_cell(a["id"], a["category"])}</td>'
            f'<td>{_editable_text_cell("assets", a["id"], "institution", a["institution"], width="110px")}</td>'
            f'<td>{_editable_text_cell("assets", a["id"], "last4", a["last4"], width="90px")}</td>'
            f'<td class="num">{balance_display}</td>'
            f'<td class="link-col">{_link_select_html(a, linkable)}</td>'
            f'{tax_treatment_td}{mc_td}'
            f'<td>{html.escape(a["source"])}</td></tr>'
        ), balance

    rendered = [row_html(a) for a in rows]
    rows_html = "".join(r for r, _ in rendered)
    subtotal = sum(b for _, b in rendered)
    footer_colspan = 5
    footer_trailing_cols = "<td colspan=\"2\"></td>" if not is_asset_table else "<td colspan=\"4\"></td>"
    return f"""
<div style="font-weight:600; font-size:13px; margin:16px 0 4px 0; color:#333;">{html.escape(category)}</div>
<table class="sortable">
<thead><tr><th class="check-col"><input type="checkbox" class="select-all-check"></th><th>Name</th><th>Category</th><th>Institution</th><th>Account #</th><th class="num">Balance</th><th class="link-col">Linked account</th>{tax_treatment_th}{mc_th}<th>Source</th></tr></thead>
<tbody>{rows_html}</tbody>
<tfoot><tr><td colspan="{footer_colspan}">Subtotal</td><td class="num">{_money(subtotal)}</td>{footer_trailing_cols}</tr></tfoot>
</table>
"""

def _editable_category_cell(item_id: int, category: str) -> str:
    """Like _editable_text_cell, but with the "assets-categories"
    datalist (built once in _render_asset_page from every category
    already in use, across both Assets and Liabilities) wired up for
    autocomplete -- same pattern as Expense/Income's own
    _editable_category_cell, minus that tab's Variable-inflation side
    effect (nothing here needs one). Lets any row -- including one that
    imported into the wrong category, e.g. a credit card filed under
    "Loan" -- be moved into the right category (and therefore the right
    subtotal table, since _group_by_category groups by this field) in
    place, the same way Name/Institution/Balance already are, instead of
    requiring a delete-and-re-add."""
    escaped = html.escape(category or "")
    return (
        f'<input type="text" value="{escaped}" list="assets-categories" data-field="category" '
        f'style="width:100px; font-size:12px; padding:3px 4px; box-sizing:border-box;" '
        f'onchange="updateField(\'assets\', {item_id}, \'category\', this.value)">'
    )


def _real_estate_summary_line_html(real_estate_total: float, count: int) -> str:
    """A single collapsed line on the Asset tab for real estate --
    equity total and property count, linking to the Real Estate
    Analysis tab -- instead of a second full table that repeated every
    property's name/value/loan/equity right below it (that table's own
    rows already live, editable, on that dedicated tab; showing the same
    nine properties again here was pure duplication of *view*, even
    though the underlying data was never duplicated in storage -- see
    that tab's own docstring). real_estate_total is computed by the
    caller (_render_asset_page) with the same real_estate_equity() +
    effective_loan_balance() combination the Real Estate Analysis tab
    itself uses, so this figure can never drift from that tab's own
    subtotal."""
    if count == 0:
        return '<p class="muted">Real estate: no properties yet -- add one on the <a href="/real-estate.html">Real Estate Analysis</a> tab.</p>'
    plural = "property" if count == 1 else "properties"
    return (
        f'<p class="status-line">Real estate equity: <strong>{_money(real_estate_total)}</strong> '
        f'across {count} {plural} -- see <a href="/real-estate.html">Real Estate Analysis</a> for detail.</p>'
    )

