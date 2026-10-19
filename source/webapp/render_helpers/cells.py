"""Editable table-cell HTML builders (text/number/select/checkbox inputs
that save via the shared updateField() JS in shell.py's PAGE_SHELL), plus
the linked-account dropdown and the two "effective balance" cell
renderers that show a live Plaid figure in place of the stored one when
a row is linked.
"""

from __future__ import annotations

import html

from source.reporting.aggregate import effective_loan_balance
from source.webapp.render_helpers.formatting import (
    _account_number_display,
    _format_money_input_value,
    _format_number_input_value,
    _money,
)


def _link_select_html(row: dict, linkable: list[dict], *, section: str = "assets") -> str:
    """The "Linked account" cell for one Asset-tab or Real Estate Analysis
    row: a dropdown of every currently-connected Plaid account,
    pre-selected to whichever one (if any) this line item is linked to.
    Picking one wires this row to that account's live balance (see
    _effective_balance_html / effective_loan_balance); picking
    "-- Not linked --" clears it back to the typed-in balance."""
    current = row.get("linked_account_id") or ""
    options = ['<option value="">-- Not linked --</option>']
    matched_current = False
    for acc in linkable:
        number = _account_number_display(
            acc["mask"], acc.get("account_number"), acc.get("is_tokenized_account_number", False), mask_prefix="...",
        )
        label = f'{acc["institution"]} -- {acc["label"]}' + (f' ({number})' if number else "")
        selected = " selected" if acc["account_id"] == current else ""
        if selected:
            matched_current = True
        options.append(f'<option value="{html.escape(acc["account_id"])}"{selected}>{html.escape(label)}</option>')
    if current and not matched_current:
        # Linked to an account that's since been unlinked/removed on Setup
        # -- keep it selectable so the user can see it and clear it,
        # rather than silently dropping back to "-- Not linked --".
        options.append(f'<option value="{html.escape(current)}" selected>(account removed -- click to unlink)</option>')
    options_html = "".join(options)
    return (
        f'<select onchange="linkAccount(\'{section}\', {row["id"]}, this.value)" '
        f'style="font-size:12px; padding:3px 4px;">{options_html}</select>'
    )


def _editable_text_cell(
    section: str, item_id: int, field: str, value: str, *, width: str = "100%", placeholder: str = "",
) -> str:
    """A plain text <input> that saves on blur/change via the shared
    updateField() JS helper -- same generic /api/line-item/update endpoint
    the Real Estate tab's Ownership %/Annual Income fields already use,
    just parameterized by section now instead of hardcoded to
    real_estate."""
    escaped = html.escape(value or "")
    placeholder_attr = f' placeholder="{html.escape(placeholder)}"' if placeholder else ""
    return (
        f'<input type="text" value="{escaped}"{placeholder_attr} data-field="{field}" '
        f'style="width:{width}; font-size:12px; padding:3px 4px; box-sizing:border-box;" '
        f'onchange="updateField(\'{section}\', {item_id}, \'{field}\', this.value)">'
    )


def _editable_number_cell(
    section: str, item_id: int, field: str, value, *, width: str = "90px", step: str = "0.01",
    min_attr: str | None = None, max_attr: str | None = None, blank_if_none: bool = False,
    money: bool = False,
) -> str:
    """blank_if_none=True renders an unset (None) value as an empty input
    instead of "0" -- for a genuinely optional numeric field like
    start_year/end_year/base_year, where 0 isn't a valid value and would
    otherwise look like (and be mistaken by JS emptiness checks for) a
    real, deliberately-typed 0. Fields where 0 is itself a legitimate
    value (balance, annual_amount, ...) keep the old default.

    money=True renders a dollar amount with thousands commas ("1,290,000")
    in a text input (a number input cannot show commas); updateMoneyField()
    strips them before saving."""
    if money:
        try:
            shown = _format_money_input_value(value)
        except (TypeError, ValueError):
            shown = "0"
        return (
            f'<input type="text" inputmode="decimal" value="{shown}" data-field="{field}" data-money="1" '
            f'style="width:{width}; font-size:12px; padding:3px 4px; text-align:right; box-sizing:border-box;" '
            f'onchange="updateMoneyField(\'{section}\', {item_id}, \'{field}\', this)">'
        )
    if value is None and blank_if_none:
        display_value = ""
    else:
        try:
            display_value = _format_number_input_value(value or 0)
        except (TypeError, ValueError):
            display_value = "0"
    extra = ""
    if min_attr is not None:
        extra += f' min="{min_attr}"'
    if max_attr is not None:
        extra += f' max="{max_attr}"'
    return (
        f'<input type="number" step="{step}"{extra} value="{display_value}" data-field="{field}" '
        f'style="width:{width}; font-size:12px; padding:3px 4px; text-align:right; box-sizing:border-box;" '
        f'onchange="updateField(\'{section}\', {item_id}, \'{field}\', this.value)">'
    )


def _editable_select_cell(
    section: str, item_id: int, field: str, value: str, options: tuple[tuple[str, str], ...], *, width: str = "120px",
) -> str:
    """A <select> that saves via the same shared updateField() JS helper
    (and /api/line-item/update endpoint) as _editable_text_cell/
    _editable_number_cell above -- e.g. the Asset tab's Tax treatment
    column. `options` is (stored_value, label) pairs; a `value` that
    doesn't match any option's stored_value (blank/legacy row) renders
    with nothing selected, so the browser shows the first option --
    callers that want a specific fallback selected should put it first."""
    opts_html = "".join(
        f'<option value="{html.escape(opt_value)}"{" selected" if opt_value == (value or "") else ""}>'
        f"{html.escape(label)}</option>"
        for opt_value, label in options
    )
    return (
        f'<select data-field="{field}" style="width:{width}; font-size:12px; padding:3px 4px;" '
        f'onchange="updateField(\'{section}\', {item_id}, \'{field}\', this.value)">{opts_html}</select>'
    )


def _editable_checkbox_cell(section: str, item_id: int, field: str, checked) -> str:
    """A checkbox that saves via the shared updateField() JS helper, same
    /api/line-item/update endpoint as _editable_text_cell/_editable_number_cell
    -- used for the Expense/Income tabs' "Inflates?" column and the Real
    Estate Analysis tab's "In the plan?" column. Moved here (out of
    expense.py, its original single caller) so real_estate.py can reuse
    it without a cross-page-module import."""
    is_checked = " checked" if checked else ""
    return (
        f'<input type="checkbox"{is_checked} data-field="{field}" '
        f'onchange="updateField(\'{section}\', {item_id}, \'{field}\', this.checked ? 1 : 0)">'
    )


def _effective_balance_html(row: dict, live_by_account_id: dict) -> tuple[float, str]:
    """Returns (balance to sum/display, the <td> markup for it). Linked
    rows show the live Plaid balance with a small "live" tag instead of
    the stored balance column -- see source.reporting.aggregate.
    effective_balance for the matching logic net worth uses."""
    account_id = row.get("linked_account_id")
    if account_id and account_id in live_by_account_id:
        value = live_by_account_id[account_id]["balance"] or 0.0
        if row["kind"] == "liability":
            value = abs(value)
        cell = f'{_money(value)} <span class="muted" style="font-size:11px">live</span>'
        return value, cell
    return row["balance"] or 0.0, _money(row["balance"])


def _loan_cell_html(row: dict, live_by_account_id: dict) -> tuple[float, str]:
    """Returns (full loan balance, the <td> markup for it). Shows the
    full balance -- live from Plaid when linked, so it matches what the
    bank itself reports rather than a derived number -- plus a small
    "your share" note when Ownership % isn't 100, since that's the
    amount actually netted into Equity (see real_estate_equity)."""
    loan_balance = effective_loan_balance(row, live_by_account_id)
    is_live = bool(row.get("linked_account_id")) and row["linked_account_id"] in live_by_account_id
    cell = _money(loan_balance) + (' <span class="muted" style="font-size:11px">live</span>' if is_live else "")
    ownership_pct = row.get("ownership_pct")
    if ownership_pct is not None and round(ownership_pct, 6) != 100:
        share = ownership_pct / 100.0
        cell += f'<br><span class="muted" style="font-size:11px">your share: {_money(loan_balance * share)}</span>'
    return loan_balance, cell
