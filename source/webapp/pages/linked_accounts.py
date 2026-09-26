"""The Linked Accounts tab: one row per Plaid-linked account, its
current balance, and its donut-chart breakdown by institution."""

from __future__ import annotations

import html

from source.common import db, linked_data
from source.webapp.render_helpers import (
    _account_number_display,
    _donut_chart_html,
    _grouped_slices,
    _money,
    _shell,
    _sync_now_button_html,
)


def _render_linked_accounts_page() -> str:
    linked_accounts = linked_data.read_linked_account_balances()
    assets = db.list_line_items("assets")
    real_estate_rows = db.list_line_items("real_estate")

    # account_id -> name of the manual line item(s)/property(ies) linked
    # to it, so the table below can show which of these are already
    # folded into an Asset-tab category table (and therefore already
    # counted there) versus still sitting there un-linked.
    linked_to_by_account_id: dict[str, list[str]] = {}
    for a in assets:
        if a.get("linked_account_id"):
            linked_to_by_account_id.setdefault(a["linked_account_id"], []).append(a["name"])
    for r in real_estate_rows:
        if r.get("linked_account_id"):
            linked_to_by_account_id.setdefault(r["linked_account_id"], []).append(r["name"])

    # Existing categories across every asset/liability row (both kinds
    # share the assets table) -- offered as a datalist on the classify
    # form's Category input below, same convenience the Expense/Income
    # tab's own category datalist gives (see expense.py's
    # existing_categories), so classifying a second brokerage account
    # doesn't mean re-typing "Liquid" from scratch.
    existing_categories = sorted({(a["category"] or "").strip() for a in assets if (a["category"] or "").strip()})
    category_options_html = "".join(f'<option value="{html.escape(c)}">' for c in existing_categories)

    def _linked_to_cell(r):
        names = linked_to_by_account_id.get(r["account_id"])
        if names:
            return f'Linked to: {html.escape(", ".join(names))}'
        return _classify_form_html(r)

    def _classify_form_html(r) -> str:
        """A small inline form replacing "Not linked to a line item" --
        picking a Kind/Category and hitting Classify creates the Asset-tab
        line item and links it to this account in one step (see
        classifyLinkedAccount() / /api/line-item/classify-linked-account),
        instead of requiring a trip to the Asset tab to add a row by hand
        first. Kind defaults from the account's own Plaid type (a credit
        card or loan starts on Liability, everything else on Asset) --
        still just a default, changeable before hitting Classify."""
        account_id_attr = html.escape(r["account_id"])
        name_default = html.escape(r["account_name"] or r["institution"])
        is_liability = r.get("is_liability", False)
        asset_selected = "" if is_liability else " selected"
        liability_selected = " selected" if is_liability else ""
        return f"""<div class="classify-row" style="display:flex; gap:4px; align-items:center; flex-wrap:wrap;">
<select class="classify-kind" style="font-size:11px; padding:2px 3px;">
<option value="asset"{asset_selected}>Asset</option>
<option value="liability"{liability_selected}>Liability</option>
</select>
<input class="classify-category" type="text" list="linked-accounts-categories" placeholder="Category" style="width:90px; font-size:11px; padding:2px 3px;">
<input class="classify-name" type="text" value="{name_default}" style="width:120px; font-size:11px; padding:2px 3px;">
<button type="button" class="classify-btn" style="font-size:11px; padding:2px 8px;" onclick="classifyLinkedAccount('{account_id_attr}', this.closest('.classify-row'))">Classify</button>
</div>"""

    # Charted by magnitude (|balance|), not the signed balance the table
    # below shows -- a credit card's -$5,000 balance should still draw a
    # normal, positively-sized "$5,000 at Amex" wedge instead of either
    # vanishing (a negative slice) or silently netting against an asset
    # account's positive balance in the same "by institution" total,
    # which would misrepresent both. Same donut mark/click-to-filter
    # contract as the Linked Positions/Real Expenditure charts -- a click
    # here filters the accounts table below via applyAccountsFilters()
    # (shell.py's shared script), matching each row's own data-
    # institution/data-account-type attributes below.
    chart_rows = [{**r, "abs_balance": abs(r["balance"] or 0)} for r in linked_accounts]
    institution_chart_html = _donut_chart_html(
        "Accounts by institution (balance)",
        _grouped_slices(chart_rows, key="institution", value_key="abs_balance"),
        dim="account-institution",
    )
    account_type_chart_html = _donut_chart_html(
        "Accounts by account type (balance)",
        _grouped_slices(chart_rows, key="account_type", value_key="abs_balance"),
        dim="account-type",
    )

    linked_accounts_html = "".join(
        f'<tr data-institution="{html.escape(r["institution"])}" data-account-type="{html.escape(r["account_type"])}" '
        f'data-balance="{r["balance"] or 0}">'
        f'<td>{html.escape(r["institution"])}</td><td>{html.escape(r["item_key"])}</td>'
        f'<td>{html.escape(r["account_type"])}</td>'
        f'<td>{html.escape(_account_number_display(r["last4"], r.get("account_number"), r.get("is_tokenized_account_number", False)))}</td>'
        f'<td class="num">{_money(r["balance"])}</td>'
        f'<td>{html.escape(r["last_update"])}</td><td>{_linked_to_cell(r)}</td></tr>'
        for r in linked_accounts
    ) or '<tr><td colspan="7" class="muted">No linked account data yet -- connect a Plaid account on Setup.</td></tr>'
    linked_balance_total = sum(r["balance"] or 0 for r in linked_accounts)

    body = f"""
<h2 style="margin-top:0">Linked accounts (live, read-only)</h2>
<p class="muted">Account balances pulled directly from Plaid each time this page loads. An account not yet counted anywhere shows a Classify control in its Line item column below -- pick a Kind/Category and hit Classify to create that Asset-tab line item and link this account's live balance to it in one step. (You can also link one to an existing category row yourself, from that row's own "Linked account" column on the Asset tab.) An account linked either way is already counted in its category table, so it's excluded from the total below to avoid double-counting. See <a href="/account-balances.html">account-balances.html</a> for the standalone export.</p>
{_sync_now_button_html()}
<div class="group-section">
{institution_chart_html}
{account_type_chart_html}
</div>
<p class="muted">Click a slice of either chart above to filter the accounts list down to that institution or account type -- click it again (or "Clear all") to go back to everything.</p>
<div id="accounts-filter-bar" class="filter-bar"></div>
<p id="linked-accounts-shown-count" class="muted"></p>
<table id="linked-accounts-table" class="sortable">
<thead><tr><th>Institution</th><th>Item Key</th><th>Account Type</th><th>Account #</th><th class="num">Balance</th><th>Last Update</th><th>Line item</th></tr></thead>
<tbody>{linked_accounts_html}</tbody>
<tfoot><tr><td colspan="4">Total</td><td class="num" id="linked-accounts-balance-total">{_money(linked_balance_total)}</td><td colspan="2"></td></tr></tfoot>
</table>
<datalist id="linked-accounts-categories">{category_options_html}</datalist>
<p class="muted">Investment holdings (and their own charts) are on the <a href="/linked-positions.html">Linked Positions</a> tab.</p>
"""
    return _shell(title="Linked Accounts", active="linked-accounts.html", body=body)
