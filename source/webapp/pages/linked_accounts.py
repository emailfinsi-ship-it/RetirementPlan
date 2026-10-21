"""The Linked Accounts tab: one row per Plaid-linked account, its
current balance, and separate Assets/Liabilities donut-chart breakdowns
by institution and by account type (kept apart so a mortgage or credit
line's debt is never counted as a positive dollar amount alongside
actual cash/investment balances -- see the comment on asset_rows/
liability_rows below for why that used to make a clicked chart slice's
number disagree with the accounts table's own filtered Total)."""

from __future__ import annotations

import html

from source.common import db, linked_data
from source.webapp.render_helpers import (
    _account_number_display,
    _donut_chart_html,
    _grouped_slices,
    _money,
    _multi_line_chart_html,
    _shell,
)


def _investment_balance_history_series(investment_accounts: list[dict]) -> list[dict]:
    """Builds the `series` list _multi_line_chart_html expects for the
    "Investment balance over time" chart below: one series per currently
    -linked investment account (investment_accounts is linked_data.
    linkable_accounts() already filtered to type == "investment"), from
    db.list_account_balance_snapshots -- plus an emphasized combined
    "Total" series (added only when there's more than one account, since
    a lone account's own line already IS the total) summing whichever
    accounts have a snapshot on each given date.

    Sorted by institution/label before assigning colors so the color a
    given account gets stays stable across a page reload regardless of
    Plaid's own return order (_multi_line_chart_html's own docstring:
    color follows the entity, never its rank).

    An account that's since been unlinked simply won't appear in
    investment_accounts and so won't get a series here -- its past
    snapshot rows are left alone in the database (nothing here deletes
    them) in case it's ever relinked."""
    series = []
    totals_by_date: dict[str, float] = {}
    for a in sorted(investment_accounts, key=lambda a: (a["institution"], a["label"])):
        rows = db.list_account_balance_snapshots(a["account_id"])
        points = [(r["snapshot_date"], r["balance"]) for r in rows]
        for d, v in points:
            totals_by_date[d] = totals_by_date.get(d, 0.0) + v
        number = _account_number_display(
            a["mask"], a.get("account_number"), a.get("is_tokenized_account_number", False), mask_prefix="...",
        )
        name = f'{a["institution"]} -- {a["label"]}' + (f' ({number})' if number else "")
        series.append({"name": name, "points": points, "emphasize": False})
    if len(series) > 1:
        series.append({"name": "Total", "points": sorted(totals_by_date.items()), "emphasize": True})
    return series


def _tax_buckets_section_html() -> str:
    """Where each account's tax bucket and owner are set, and where one
    account can be split across buckets (a 401k that mixes pre-tax, Roth
    and after-tax money). The Drawdown Planning, Will my money last? and
    Legacy pages all read these. The pieces are built by drawdown_planning
    (where they started) and shown here."""
    from source.reporting.aggregate import build_summary
    from source.webapp.pages import drawdown_planning as dd

    s = build_summary()
    sources = s["drawdown_sources"]
    return f"""
<h2 id="tax-buckets">Tax buckets and owners</h2>
<p class="muted">Each account is placed in a tax bucket (taxable, tax-deferred or Roth) and given an owner. This decides how withdrawals are taxed and whose required withdrawals apply. Drawdown Planning and Will my money last? use it.</p>
<details class="how-it-works" id="resources-by-source"><summary>Show table: resources by source ({len(sources)})</summary>
{dd._sources_table_html(sources)}</details>
{dd._account_splits_card_html(s["splittable_investment_accounts"], s["account_tax_splits"], s["account_split_mismatches"])}
"""


def _render_linked_accounts_page() -> str:
    linked_accounts = linked_data.read_linked_account_balances()
    investment_accounts = [a for a in linked_data.linkable_accounts() if a.get("type") == "investment"]
    assets = db.list_line_items("assets")
    real_estate_rows = db.list_line_items("real_estate")

    # account_id -> name of the manual line item(s)/property(ies) linked
    # to it, so the table below can show which of these are already
    # folded into an Assets-tab category table (and therefore already
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
        picking a Kind/Category and hitting Classify creates the Assets-tab
        line item and links it to this account in one step (see
        classifyLinkedAccount() / /api/line-item/classify-linked-account),
        instead of requiring a trip to the Assets tab to add a row by hand
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

    # Split into an Assets breakdown and a Liabilities breakdown rather
    # than one combined "balance" chart -- a single chart summing
    # abs(balance) used to count a mortgage or credit line's debt as a
    # positive dollar amount right alongside cash/investment balances,
    # so an institution or account type that's mostly debt (e.g. a HELOC-
    # heavy bank) could show as a large slice here while actually being
    # *negative* net worth, and clicking that slice to filter the table
    # below (whose Total nets liabilities against assets, correctly)
    # would show a much smaller, sometimes even negative-looking, number
    # than the slice just claimed -- a real user-reported mismatch, not
    # just a rounding difference. Splitting by is_liability means every
    # number here is unambiguous: a slice's value is the plain, correctly
    # -signed magnitude of exactly the accounts it represents, so a
    # filtered Total always matches. Same donut click-to-filter contract
    # as before -- a click filters the accounts table below via
    # applyAccountsFilters() (shell.py's shared script), matching each
    # row's own data-institution/data-account-type attributes below; the
    # asset and liability version of a chart deliberately share the same
    # dim ("account-institution"/"account-type") since they're two views
    # of the same underlying dimension, so clicking "Fidelity" in either
    # one filters the table to every Fidelity account, assets and
    # liabilities alike.
    asset_rows = [{**r, "asset_value": max(r["balance"] or 0.0, 0.0)} for r in linked_accounts if not r["is_liability"]]
    liability_rows = [{**r, "liability_value": abs(r["balance"] or 0.0)} for r in linked_accounts if r["is_liability"]]
    institution_assets_chart_html = _donut_chart_html(
        "Assets by institution",
        _grouped_slices(asset_rows, key="institution", value_key="asset_value"),
        dim="account-institution",
    )
    institution_liabilities_chart_html = _donut_chart_html(
        "Liabilities by institution",
        _grouped_slices(liability_rows, key="institution", value_key="liability_value"),
        dim="account-institution",
    )
    type_assets_chart_html = _donut_chart_html(
        "Assets by account type",
        _grouped_slices(asset_rows, key="account_type", value_key="asset_value"),
        dim="account-type",
    )
    type_liabilities_chart_html = _donut_chart_html(
        "Liabilities by account type",
        _grouped_slices(liability_rows, key="account_type", value_key="liability_value"),
        dim="account-type",
    )
    total_assets = sum(r["asset_value"] for r in asset_rows)
    total_liabilities = sum(r["liability_value"] for r in liability_rows)

    linked_accounts_html = "".join(
        f'<tr data-institution="{html.escape(r["institution"])}" data-account-type="{html.escape(r["account_type"])}" '
        f'data-balance="{r["balance"] or 0}">'
        f'<td>{html.escape(r["institution"])}</td><td>{html.escape(r["item_key"])}</td>'
        f'<td>{html.escape(r["account_type"])}</td>'
        f'<td><span class="acct-num">{html.escape(_account_number_display(r["last4"], r.get("account_number"), r.get("is_tokenized_account_number", False)))}</span></td>'
        f'<td class="num">{_money(r["balance"])}</td>'
        f'<td>{html.escape(r["last_update"])}</td><td>{_linked_to_cell(r)}</td></tr>'
        for r in linked_accounts
    ) or '<tr><td colspan="7" class="muted">No linked account data yet -- connect a Plaid account on Setup.</td></tr>'
    linked_balance_total = sum(r["balance"] or 0 for r in linked_accounts)

    investment_history_chart_html = _multi_line_chart_html(
        "Investment balance over time",
        _investment_balance_history_series(investment_accounts),
        # Log scale: accounts of very different sizes (a small IRA next
        # to a much larger brokerage) otherwise squash the smaller one's
        # own movement flat near the bottom of a linear axis -- see
        # _multi_line_chart_html's own docstring on log_scale for how
        # this is disclosed on the chart itself.
        log_scale=True,
        empty_message="Balance history accumulates one point per linked investment account each day this app is opened or synced -- check back after a day or two.",
    )

    tax_buckets_html = _tax_buckets_section_html()
    body = f"""
<h2 style="margin-top:0">Linked Accounts <span class="muted" style="font-size:13px; font-weight:400">(live, read-only)</span></h2>
<p class="muted">Account balances pulled directly from Plaid each time this page loads. An account not yet counted anywhere shows a Classify control in its Line item column below -- pick a Kind/Category and hit Classify to create that Assets-tab line item and link this account's live balance to it in one step. (You can also link one to an existing category row yourself, from that row's own "Linked account" column on the Assets tab.) An account linked either way is already counted in its category table, so it's excluded from the total below to avoid double-counting. See <a href="/account-balances.html">account-balances.html</a> for the standalone export.</p>
<p class="muted">Assets ({_money(total_assets)}) and liabilities ({_money(total_liabilities)}) are charted separately below -- net worth across every linked account is {_money(total_assets - total_liabilities)}.</p>
<p class="muted small" style="margin:6px 0;">Account numbers are blurred by default. Hover one to read it, or <button type="button" onclick="document.documentElement.classList.toggle('show-acct')" style="font-size:12px; padding:2px 8px;">show / hide all</button>.</p>
<div id="accounts-filter-bar" class="filter-bar"></div>
<p id="linked-accounts-shown-count" class="muted"></p>
<table id="linked-accounts-table" class="sortable">
<thead><tr><th>Institution</th><th>Item Key</th><th>Account Type</th><th>Account #</th><th class="num">Balance</th><th>Last Update</th><th>Line item</th></tr></thead>
<tbody>{linked_accounts_html}</tbody>
<tfoot><tr><td colspan="4">Total</td><td class="num" id="linked-accounts-balance-total">{_money(linked_balance_total)}</td><td colspan="2"></td></tr></tfoot>
</table>
<datalist id="linked-accounts-categories">{category_options_html}</datalist>
<p class="muted">Investment holdings (and their own charts) are on the <a href="/linked-positions.html">Linked Positions</a> tab.</p>
{tax_buckets_html}
<h2 id="account-charts" style="margin-top:26px">Where the money is, in charts</h2>
<h3 style="font-size:13px;">Assets</h3>
<div class="group-section">
{institution_assets_chart_html}
{type_assets_chart_html}
</div>
<h3 style="font-size:13px;">Liabilities</h3>
<div class="group-section">
{institution_liabilities_chart_html}
{type_liabilities_chart_html}
</div>
<p class="muted">Click a slice of any chart below to filter the accounts list above down to that institution or account type -- click it again (or "Clear all") to go back to everything.</p>
<details>
<summary style="cursor:pointer; font-size:13px; font-weight:650; color:var(--ink);">Investment balance history</summary>
<div class="group-section" style="margin-top:10px;">
{investment_history_chart_html}
</div>
</details>
"""
    return _shell(title="Linked Accounts", active="linked-accounts.html", body=body)
