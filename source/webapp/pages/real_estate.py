"""The Real Estate Analysis tab: property values, loan balances, and
equity, in one editable table."""

from __future__ import annotations

import html

from source.common import db, linked_data
from source.reporting.aggregate import build_summary, real_estate_equity
from source.webapp.render_helpers.sale_cards import sale_settings_card_html
from source.webapp.render_helpers import (
    _editable_checkbox_cell,
    _editable_number_cell,
    _editable_text_cell,
    _link_select_html,
    _loan_cell_html,
    _money,
    _shell,
)


def _render_real_estate_page() -> str:
    rows = db.list_line_items("real_estate")
    linkable = linked_data.linkable_accounts()
    live_by_account_id = {a["account_id"]: a for a in linkable}

    def row_html(r):
        loan_balance, loan_cell = _loan_cell_html(r, live_by_account_id)
        equity = real_estate_equity(r, loan_balance=loan_balance)
        is_linked = bool(r.get("linked_account_id")) and r["linked_account_id"] in live_by_account_id
        # A linked property's loan balance tracks Plaid automatically, same
        # rule as an Asset-tab linked row -- only an unlinked property's
        # Loan Balance becomes an editable input.
        loan_display = (
            loan_cell if is_linked
            else _editable_number_cell("real_estate", r["id"], "loan_balance", r["loan_balance"], width="115px", money=True)
        )
        name_cell = _editable_text_cell("real_estate", r["id"], "name", r["name"], width="110px")
        updated = r.get("value_updated_at")
        address_cell = (
            _editable_text_cell(
                "real_estate", r["id"], "address", r.get("address") or "", width="170px",
                placeholder="street, city, ST ZIP",
            )
            + f'<br><button type="button" style="padding:2px 8px; font-size:11px;" onclick="refreshPropertyValue({r["id"]}, this)">Update value</button>'
            + (f' <span class="muted" style="font-size:11px;">updated {html.escape(updated)}</span>' if updated else "")
        )
        # Wider than the 90px default -- a property's Purchase Price/
        # Current Value/Loan Balance commonly runs 7+ digits (into the
        # millions), which the 90px default was too narrow to
        # comfortably show once _format_number_input_value stopped
        # abbreviating those values to scientific notation.
        purchase_cell = _editable_number_cell("real_estate", r["id"], "purchase_price", r["purchase_price"], width="115px", money=True)
        value_cell = _editable_number_cell("real_estate", r["id"], "current_value", r["current_value"], width="115px", money=True)
        ownership_cell = _editable_number_cell(
            "real_estate", r["id"], "ownership_pct", r["ownership_pct"],
            width="56px", min_attr="0", max_attr="100",
        ) + "%"
        income_cell = _editable_number_cell(
            "real_estate", r["id"], "annual_income", r["annual_income"], width="90px", money=True,
        )
        loan_end_cell = _editable_number_cell(
            "real_estate", r["id"], "loan_end_year", r.get("loan_end_year"), width="70px", step="1",
            min_attr="1900", max_attr="2200", blank_if_none=True,
        )
        mc_cell = _editable_checkbox_cell("real_estate", r["id"], "include_in_monte_carlo", r.get("include_in_monte_carlo"))
        return (
            f'<tr><td class="check-col"><input type="checkbox" class="row-check" '
            f'data-section="real_estate" data-id="{r["id"]}"></td>'
            f'<td>{name_cell}</td><td>{address_cell}</td><td class="num">{purchase_cell}</td>'
            f'<td class="num">{value_cell}</td><td class="num">{ownership_cell}</td>'
            f'<td class="num">{loan_display}</td><td class="num">{loan_end_cell}</td>'
            f'<td class="link-col">{_link_select_html(r, linkable, section="real_estate")}</td>'
            f'<td class="num">{_money(equity)}</td><td class="num">{income_cell}</td>'
            f'<td>{mc_cell}</td></tr>'
        ), equity, r["purchase_price"] or 0, r["current_value"] or 0, loan_balance

    rendered = [row_html(r) for r in rows]
    rows_html = "".join(r for r, _, _, _, _ in rendered) or (
        '<tr><td colspan="12" class="muted">No properties yet.</td></tr>'
    )
    total_equity = sum(e for _, e, _, _, _ in rendered)
    total_income = sum(r["annual_income"] or 0 for r in rows)
    total_purchase = sum(p for _, _, p, _, _ in rendered)
    total_value = sum(v for _, _, _, v, _ in rendered)
    total_loan = sum(loan for _, _, _, _, loan in rendered)
    mc_equity_total = sum(
        e for r, (_, e, _, _, _) in zip(rows, rendered) if r.get("include_in_monte_carlo")
    )

    summary = build_summary()
    sale_card = sale_settings_card_html(summary["real_estate_sale"], summary["assumptions"])

    body = f"""
<h2 style="margin-top:0">Real estate analysis</h2>
<details class="how-it-works"><summary>How this works</summary><p class="muted">Link a property's loan to a live Plaid mortgage/HELOC account (its "Linked account" column) to have Loan Balance -- and equity everywhere else in the app -- track that balance automatically. Equity is your Ownership % share of (Current Value minus Loan Balance). Every field except Equity and the live-linked Loan Balance is editable right in the table below -- changes save immediately. Check "In Monte Carlo?" to have a property's equity added as a 4th pool the Monte Carlo / historical stress test simulations can draw from -- last, after your 401k/Roth/taxable pools are exhausted, and with no tax modeled on those draws (unlike the other three pools). Off by default: real estate equity has never been part of a plan's projected drawdown until you opt a property in here.</p></details>
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th class="check-col"><input type="checkbox" class="select-all-check"></th><th>Property</th><th>Address (for value lookup)</th><th class="num">Purchase Price</th><th class="num">Current Value</th>
<th class="num">Ownership %</th><th class="num">Loan Balance</th><th class="num">Loan ends (year)</th><th class="link-col">Linked account</th><th class="num">Equity</th>
<th class="num">Annual Income</th><th>In Monte Carlo?</th></tr></thead>
<tbody>{rows_html}</tbody>
<tfoot><tr><td colspan="3">Totals</td><td class="num">{_money(total_purchase)}</td><td class="num">{_money(total_value)}</td><td></td>
<td class="num">{_money(total_loan)}</td><td></td><td></td><td class="num">{_money(total_equity)}</td>
<td class="num">{_money(total_income)}</td><td></td></tr></tfoot>
</table>
</div>
<p class="status-line">Included in Monte Carlo simulations: <strong>{_money(mc_equity_total)}</strong> of equity above.</p>
<p class="muted">Loan ends (year): the year each property's loan is paid off. The tax estimates on the Drawdown, Legacy and Monte Carlo tabs treat Rental income as sheltered by mortgage interest and depreciation until then and as fully taxable after it (weighted by each property's Annual Income when several properties have different years). Leave it blank and rent is taxable every year.</p>
<p class="muted">Annual income (e.g. rental income) isn't automatically netted against the Monte Carlo withdrawal need -- if you want that, add it to "Annual income offset" on the Monte Carlo tab yourself.</p>
<script>
function refreshPropertyValue(id, btn) {{
  btn.disabled = true; var label = btn.textContent; btn.textContent = 'Looking up...';
  postJSON('/api/real-estate/refresh-value', {{id: id}})
    .then(function(d) {{ location.reload(); }})
    .catch(function(e) {{ alert(e.message); btn.disabled = false; btn.textContent = label; }});
}}
</script>
<div class="add-shortcut-row">
  <button type="button" class="primary" onclick="openAddModal('real_estate')">+ Add property</button>
</div>
{sale_card}
"""
    return _shell(title="Real Estate Analysis", active="real-estate.html", body=body)
