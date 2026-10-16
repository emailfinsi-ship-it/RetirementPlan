"""The Drawdown Planning tab: "resources by tax criteria" -- every
dollar this program knows about (manual Asset-tab rows, live-linked
Plaid investment accounts whether or not they've been added to the
Asset tab, and any opted-in real estate equity), bucketed into
Taxable/Tax-deferred/Roth/Real-estate, plus a deterministic year-by-year
projection of the standard tax-efficient withdrawal order (Taxable,
then Tax-deferred, then Roth, then Real estate last), reusing the exact
same pool math the Monte Carlo tab's own three-pool mode runs on.

Two sections, per the user's own request ("include resources by tax
criteria" + a full drawdown *plan*, not just a snapshot):
  1. A snapshot -- tiles, a donut chart, and a per-source table showing
     exactly which account/row lands in which bucket and why, plus a
     "Split a linked account across tax buckets" card (per the user's
     own request, "for fidelity can i segregate the sources manually" /
     "give me option to break up one sum to parts") for the case a
     single linked account actually mixes tax treatments -- a 401k
     holding pre-tax, Roth, and after-tax money all at once, the way an
     institution's own "Sources" breakdown shows it.
  2. A year-by-year detail table tracing RMDs, the withdrawal order, and
     the estimated tax bill forward from today, at the plan's own
     Expected return assumption (no randomness -- see
     deterministic_drawdown_schedule's own docstring for why this is a
     single path rather than a percentile band like the Monte Carlo
     tab's fan chart).
"""

from __future__ import annotations

import html

from source.common import db
from source.reporting.aggregate import build_summary
from source.reporting.rmd import rmd_age_for_birth_year
from source.reporting.monte_carlo import deterministic_drawdown_schedule
from source.reporting.monte_carlo.real_estate_sale_compare import drawdown_sale_comparison
from source.webapp.render_helpers.sale_cards import sale_comparison_card_html
from source.webapp.render_helpers import (
    _donut_chart_html,
    _editable_number_cell,
    _editable_select_cell,
    _editable_text_cell,
    _grouped_slices,
    _money,
    _shell,
    _TAX_TREATMENT_OPTIONS,
    _visible_rows_by_year,
    _withdrawal_parts,
    _withdrawn_ending_cells_html,
    _withdrawn_ending_header_html,
)

_BUCKET_LABELS = {
    "tax_deferred": "Tax-deferred (401k/Traditional)",
    "roth": "Roth (tax-free)",
    "taxable": "Taxable (brokerage)",
    "real_estate": "Real estate (opted in)",
}


def _bucket_label(bucket: str) -> str:
    return _BUCKET_LABELS.get(bucket, bucket.replace("_", " ").title())


def _owner_cell_html(source: dict) -> str:
    """The Owner <select> for one "Resources by source" row. An Asset-tab
    row (or a manually split piece of one) saves through the shared
    updateField() helper onto that row's own owner column; a live account
    that isn't on the Asset tab saves through setAccountOwner() onto
    db.set_account_owner instead. Real estate has no owner (equity isn't
    subject to RMDs) -- shown as "--"."""
    target = source.get("owner_target")
    if not target:
        return "--"
    options = "".join(
        f'<option value="{html.escape(value)}"{" selected" if value == (source.get("owner") or "") else ""}>{html.escape(label)}</option>'
        for value, label in db.OWNER_OPTIONS
    )
    if target["kind"] == "asset":
        handler = f"updateField('assets', {int(target['id'])}, 'owner', this.value)"
    else:
        handler = f"setAccountOwner({html.escape(repr(target['id']))}, this.value)"
    return f'<select style="width:100px; font-size:12px; padding:3px 4px;" onchange="{handler}">{options}</select>'


def _sources_table_html(sources: list[dict]) -> str:
    if not sources:
        return '<p class="muted">No retirement/liquid resources yet -- check "In Monte Carlo?" on an Asset-tab row, link a Plaid investment account, or opt a property in on the Real Estate Analysis tab.</p>'
    rows_html = "".join(
        f'<tr><td>{html.escape(s["name"])}</td>'
        f'<td>{html.escape(s["institution"]) if s["institution"] else "--"}</td>'
        f'<td>{html.escape(s["origin"])}</td>'
        f'<td>{html.escape(_bucket_label(s["tax_bucket"]))}</td>'
        f'<td>{_owner_cell_html(s)}</td>'
        f'<td class="num">{_money(s["balance"])}</td></tr>'
        for s in sorted(sources, key=lambda s: s["balance"], reverse=True)
    )
    total = sum(s["balance"] for s in sources)
    return f"""
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th>Source</th><th>Institution</th><th>Where it's from</th><th>Tax bucket</th><th>Owner</th><th class="num">Balance</th></tr></thead>
<tbody>{rows_html}</tbody>
<tfoot><tr><td colspan="5">Total</td><td class="num">{_money(total)}</td></tr></tfoot>
</table>
</div>
"""


def _account_splits_card_html(
    splittable_investment_accounts: list[dict], account_tax_splits: list[dict], account_split_mismatches: list[dict],
) -> str:
    """"Split a linked account across tax buckets" -- per the user's own
    request ("for fidelity can i segregate the sources manually" / "give
    me option to break up one sum to parts"). A single Plaid investment
    account has exactly one subtype (see linked_data.detected_tax_
    treatment), so the "Resources by source" table above puts its WHOLE
    balance in one tax bucket -- but a real 401k often holds several at
    once (an institution's own "Sources" breakdown, e.g. Fidelity's Base
    Pay Traditional/Apple Match/Rollover/Roth In-Plan Conversion/Base Pay
    Roth/Catch-up/After-tax). This card lets the user name and bucket
    each piece by hand; source.reporting.aggregate.build_summary then
    replaces that account's single lumped entry with these split pieces
    instead, everywhere the Drawdown Planning tab uses them -- and, if
    that account is also linked to a manual Asset-tab row, in the Monte
    Carlo simulation's own starting pools too (source.reporting.aggregate.
    row_bucket_amounts).

    Offers every live investment account (splittable_investment_accounts),
    whether or not it's been added to the Asset tab -- the two cases only
    differ in which of build_summary()'s totals the split ends up
    feeding."""
    mismatch_by_account = {m["account_id"]: m for m in account_split_mismatches}
    splittable_by_id = {acc["account_id"]: acc for acc in splittable_investment_accounts}

    splits_by_account: dict[str, list[dict]] = {}
    for split in account_tax_splits:
        splits_by_account.setdefault(split["account_id"], []).append(split)

    groups_html = ""
    for account_id, splits in splits_by_account.items():
        acc = splittable_by_id.get(account_id)
        header = (
            f'{html.escape(acc["institution"])} -- {html.escape(acc["label"])}' if acc else
            f"(account no longer linked -- id {html.escape(account_id[:12])}...)"
        )
        split_total = sum(s["amount"] or 0.0 for s in splits)
        mismatch = mismatch_by_account.get(account_id)
        reconcile_note = (
            f'<p class="status-warn" style="margin:2px 0 8px 0;">Your splits add up to {_money(split_total)}, '
            f'but this account\'s own live balance is {_money(mismatch["live_balance"])} -- adjust the amounts '
            f"below so they match (new contributions since you last set this up are the usual cause).</p>"
            if mismatch else
            f'<p class="muted" style="margin:2px 0 8px 0;">Splits total {_money(split_total)}'
            + (f', matching this account\'s own live balance.' if acc else '.') + '</p>'
        )
        rows_html = "".join(
            f'<tr><td class="check-col"><input type="checkbox" class="row-check" '
            f'data-section="account_tax_splits" data-id="{s["id"]}"></td>'
            f'<td>{_editable_text_cell("account_tax_splits", s["id"], "name", s["name"], width="160px")}</td>'
            f'<td>{_editable_select_cell("account_tax_splits", s["id"], "tax_treatment", s["tax_treatment"], _TAX_TREATMENT_OPTIONS)}</td>'
            f'<td class="num">{_editable_number_cell("account_tax_splits", s["id"], "amount", s["amount"])}</td></tr>'
            for s in splits
        )
        groups_html += f"""
<div style="font-weight:600; font-size:13px; margin:16px 0 4px 0; color:var(--ink-soft);">{header}</div>
{reconcile_note}
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th class="check-col"></th><th>Name</th><th>Tax bucket</th><th class="num">Amount</th></tr></thead>
<tbody>{rows_html}</tbody>
<tfoot><tr><td colspan="3">Total</td><td class="num">{_money(split_total)}</td></tr></tfoot>
</table>
</div>
"""

    if splittable_investment_accounts:
        account_options = "".join(
            f'<option value="{html.escape(acc["account_id"])}">{html.escape(acc["institution"])} -- {html.escape(acc["label"])} '
            f'({_money(acc["balance"])})</option>'
            for acc in splittable_investment_accounts
        )
        add_form_html = f"""
<form class="inline" onsubmit="event.preventDefault(); addLineItem('account_tax_splits', this);">
  <label>Account<select name="account_id" required>{account_options}</select></label>
  <label>Name<input name="name" placeholder="e.g. Roth in-plan conversion" required></label>
  <label>Tax bucket<select name="tax_treatment">{"".join(f'<option value="{v}">{html.escape(l)}</option>' for v, l in _TAX_TREATMENT_OPTIONS)}</select></label>
  <label>Amount<input name="amount" type="number" step="0.01" required></label>
  <button type="submit" class="primary">Add split</button>
</form>
"""
    else:
        add_form_html = (
            '<p class="muted">No linked investment accounts are available to split yet -- link one first on the '
            '<a href="/linked-accounts.html">Linked Accounts</a> tab.</p>'
        )

    return f"""
<div class="card">
<h3 style="font-size:13px; margin-top:0;">Split a linked account across tax buckets</h3>
<p class="muted">One linked account has exactly one auto-detected tax bucket above -- but a real 401k often mixes
pre-tax, Roth, and after-tax money in a single account (check your institution's own "Sources" breakdown to see the
split, e.g. Fidelity's NetBenefits). Name each piece and its amount below, and the tax bucket you pick for it
replaces that account's single lumped entry everywhere on this tab.</p>
{groups_html}
{add_form_html}
</div>
"""


def _rmd_by_person_card_html(summary: dict, assumptions: dict) -> str:
    """"Required Minimum Distributions, by person": each spouse's own
    birth year / RMD start age / Tax-deferred balance, plus the form for
    the wife's birth year (the plan owner's own lives on the Monte Carlo
    tab's Assumptions, same as before). Which account belongs to whom is
    set in the Owner column of "Resources by source" above (or on the
    Asset tab). Surfaces the two things that would otherwise silently
    skew the numbers: Tax-deferred money still Unassigned (modeled under
    the plan owner's birth year until assigned), and spouse-owned money
    with no birth year to compute her RMD from."""
    by_owner = summary["drawdown_tax_deferred_by_owner"]
    me_raw, wife_raw = (assumptions.get("birth_year") or "").strip(), (assumptions.get("spouse_birth_year") or "").strip()

    def _row(label: str, raw_birth_year: str, balance: float) -> str:
        try:
            birth_year = int(float(raw_birth_year)) if raw_birth_year else None
        except ValueError:
            birth_year = None
        start_age = f"{rmd_age_for_birth_year(birth_year)}" if birth_year is not None else "--"
        return (
            f"<tr><td>{html.escape(label)}</td><td>{birth_year if birth_year is not None else '--'}</td>"
            f'<td>{start_age}</td><td class="num">{_money(balance)}</td></tr>'
        )

    unassigned = by_owner.get("unassigned", 0.0)
    unassigned_row = (
        f'<tr><td>Unassigned <span class="muted">(modeled under Me)</span></td><td>--</td><td>--</td>'
        f'<td class="num">{_money(unassigned)}</td></tr>' if unassigned > 0.005 else ""
    )
    warnings = ""
    if unassigned > 0.005:
        warnings += (
            f'<p class="status-line status-warn">{_money(unassigned)} of Tax-deferred money has no Owner yet -- it is modeled under '
            "your own birth year until you set one in the Owner column above.</p>"
        )
    if by_owner.get("spouse", 0.0) > 0.005 and not wife_raw:
        warnings += (
            '<p class="status-line status-warn">Her accounts hold Tax-deferred money but no Wife\'s birth year is set -- enter it '
            "below so her RMDs can be modeled (until then she has no RMD at all).</p>"
        )
    if not me_raw and (by_owner.get("self", 0.0) + unassigned) > 0.005:
        warnings += (
            '<p class="status-line status-warn">Set your own Birth year on the Monte Carlo tab\'s Assumptions to model your RMDs.</p>'
        )
    return f"""
<div class="card">
<h3 style="font-size:13px; margin-top:0;">Required Minimum Distributions, by person</h3>
<p class="muted">Each person's RMD is calculated on THEIR OWN Tax-deferred accounts, starting at THEIR OWN RMD age
(73 if born 1959 or earlier, 75 if 1960 or later) -- so one spouse's RMDs don't wait on the other's birthday. Assign
each account to Me or Wife in the Owner column above. Spending beyond the RMDs draws the older spouse's Tax-deferred
accounts first.</p>
{warnings}
<table>
<thead><tr><th>Person</th><th>Birth year</th><th>RMD starts at</th><th class="num">Tax-deferred balance</th></tr></thead>
<tbody>{_row("Me", me_raw, by_owner.get("self", 0.0))}{_row("Wife", wife_raw, by_owner.get("spouse", 0.0))}{unassigned_row}</tbody>
</table>
<form class="inline" onsubmit="event.preventDefault();
  var fields = {{}};
  new FormData(this).forEach(function(value, key) {{ fields[key] = value; }});
  postJSON('/api/assumptions', fields).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Wife's birth year<input name="spouse_birth_year" type="number" step="1" placeholder="e.g. 1962" value="{html.escape(wife_raw)}"></label>
  <button type="submit" class="primary">Save &amp; re-run</button>
</form>
</div>
"""


def _early_tax_deferred_card_html(assumptions: dict, early_tax_deferred_age: int | None) -> str:
    """The selector for the "start withdrawing 401k/Tax-deferred early"
    lever, per the user's own request ("if it makes sense we can start
    withdraw of 401k from 60" -- "Can you add option to select and
    see"). Unlike the Legacy Planning tab's own version of this idea
    (a what-if comparison against several strategies, unrelated to this
    plan's own actual numbers), setting an age here changes THIS page's
    own "Your plan" callout and year-by-year table directly -- the plan
    the user actually sees is the plan that reflects their choice."""
    raw = assumptions.get("early_tax_deferred_age")
    value = html.escape(str(raw)) if raw not in (None, "") else ""
    status = (
        f"Right now, spending draws Tax-deferred FIRST (instead of Taxable first) starting at age {early_tax_deferred_age} -- "
        "see the plan and table below reflect it."
        if early_tax_deferred_age is not None else
        "Right now the plan uses the default order below -- Taxable first, Tax-deferred only once Taxable runs out -- "
        "leave this blank to keep that."
    )
    return f"""
<div class="card">
<h3 style="font-size:13px; margin-top:0;">Withdrawal order</h3>
<p class="muted">401k/IRA withdrawals are already penalty-free from age 59&#189;, well before Required Minimum
Distributions would force them at 73 or 75. Set an age below to have this plan draw Tax-deferred money FIRST
starting then, instead of waiting until Taxable runs out. {status}</p>
<form class="inline" onsubmit="event.preventDefault();
  var fields = {{}};
  new FormData(this).forEach(function(value, key) {{ fields[key] = value; }});
  postJSON('/api/assumptions', fields).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Start drawing Tax-deferred at age<input name="early_tax_deferred_age" type="number" step="1" min="0" placeholder="e.g. 60" value="{value}"></label>
  <button type="submit" class="primary">Save &amp; re-run</button>
</form>
</div>
"""


def _this_years_plan_html(rows: list[dict]) -> str:
    """A plain-language callout for the FIRST visible row -- "withdraw
    $X from here, $Y from there, this year" -- so the direct answer to
    "which source do I draw from and how much" doesn't require reading
    the whole year-by-year table below it. Per the user's own request
    ("All I wanted to know from which source I need to draw down and
    how much each year"), this is deliberately the first thing on the
    page after the intro paragraph, not the last."""
    if not rows:
        return ""
    r = rows[0]
    parts = _withdrawal_parts(r)
    tax_clause = f" (that total already includes {_money(r['tax'])} of estimated tax on the withdrawal itself)" if r["tax"] > 0.01 else ""
    if not parts:
        plan_text = "Nothing needs to come out of the portfolio this year -- Income-tab rows are assumed to cover spending on their own."
    else:
        plan_text = "Withdraw " + ", plus ".join(parts) + f".{tax_clause}"
    return f"""
<div class="card" style="border: 2px solid #2a78d6;">
<h2 style="margin-top:0">Your plan for {r['year']}</h2>
<p style="font-size:15px; margin-bottom:0;">{plan_text}</p>
</div>
"""


def _visible_schedule_rows(schedule: dict) -> list[dict]:
    """The rows _year_by_year_table_html actually renders -- shared here so
    _this_years_plan_html's "first visible row" agrees with the table
    below it (both hide pre-retirement $0-need rows the same way, with
    the same empty-table fallback). See _year_by_year_table_html's own
    comment for why these rows are hidden rather than shown as $0. The
    actual hiding rule lives in render_helpers._visible_rows_by_year,
    shared with the Legacy Planning tab's own equivalent."""
    return _visible_rows_by_year(schedule["rows"], schedule.get("retirement_year"))


def _year_by_year_table_html(schedule: dict) -> str:
    rows = schedule["rows"]
    if not rows:
        return '<p class="muted">No projection yet.</p>'
    # Rows actually rendered below. Every year in `rows` is still walked in
    # order by deterministic_drawdown_schedule (so a shown year's pool
    # balances still reflect every pre-retirement year's own growth), but
    # once a Retirement year is set, the pre-retirement rows themselves --
    # need is always $0 for them by design -- are hidden rather than shown,
    # per the user's own request. Falls back to every row if that would
    # hide the whole table (e.g. a Retirement year past this plan's
    # horizon), so the table is never left empty.
    visible_rows = _visible_schedule_rows(schedule)
    retirement_year = schedule.get("retirement_year")
    hidden_row_count = len(rows) - len(visible_rows)
    hidden_years_note_html = (
        f'<p class="muted">Years before {retirement_year} (your set Retirement year) are omitted below -- '
        "need is always $0.00 for them, so there's nothing to see, though the pool balances from "
        f"{retirement_year} on still reflect those years' own growth ({hidden_row_count} year"
        f"{'s' if hidden_row_count != 1 else ''} at {schedule.get('expected_return', 0) * 100:.1f}% before the first "
        "row below, which is why its Total is higher than today's resource total above -- see the Today row).</p>"
        if hidden_row_count else ""
    )
    has_spouse = bool(schedule.get("has_spouse"))

    def _spouse_cells(r: dict) -> str:
        if not has_spouse:
            return ""
        spouse_age = r.get("spouse_age")
        return (
            f'<td>{spouse_age if spouse_age is not None else "--"}</td>'
            f'<td class="num">{_money(r["rmd_self"])}</td><td class="num">{_money(r["rmd_spouse"])}</td>'
        )

    spouse_header = (
        '<th>Wife age</th><th class="num">RMD: Me</th><th class="num">RMD: Wife</th>' if has_spouse else ""
    )
    # "Other income" (a pension, say) only gets a column when some visible
    # year actually has any -- most plans just have rent and Social Security.
    show_other_income = any(abs(r.get("income_other", 0.0)) > 0.005 for r in visible_rows)
    other_header = '<th class="num">Other income</th>' if show_other_income else ""
    rows_html = "".join(
        f'<tr><td>{r["year"]}</td>'
        f'<td>{r["age"] if r["age"] is not None else "--"}</td>'
        + _spouse_cells(r)
        + f'<td class="num">{_money(r.get("expenses", 0.0))}</td>'
        f'<td class="num">{_money(r.get("income_rental", 0.0))}</td>'
        f'<td class="num">{_money(r.get("income_social_security", 0.0))}</td>'
        + (f'<td class="num">{_money(r.get("income_other", 0.0))}</td>' if show_other_income else "")
        + f'<td class="num">{_money(r["need"])}</td>'
        f'<td class="num">{_money(r["rmd"])}</td>'
        f'<td class="num">{_money(r["tax"])}</td>'
        + _withdrawn_ending_cells_html(r)
        + f'<td class="num">{_money(r["total"])}</td>'
        + ('<td class="status-warn">Depleted</td>' if r["shortfall"] > 1e-6 else '<td></td>')
        + '</tr>'
        for r in visible_rows
    )
    start = schedule.get("starting_pools")
    leading_cols = 2 + (3 if has_spouse else 0) + 3 + (1 if show_other_income else 0) + 3
    today_row_html = (
        f'<tr style="background:var(--surface-alt); font-style:italic;"><td colspan="{leading_cols}">'
        "Today (starting balances, before any growth)</td>"
        '<td class="num">--</td><td class="num">--</td><td class="num">--</td><td class="num">--</td>'
        f'<td class="num">{_money(start["taxable"])}</td><td class="num">{_money(start["tax_deferred"])}</td>'
        f'<td class="num">{_money(start["roth"])}</td><td class="num">{_money(start["real_estate"])}</td>'
        f'<td class="num">{_money(sum(start.values()))}</td><td></td></tr>'
        if start else ""
    )
    return f"""
{hidden_years_note_html}
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th>Year</th><th>Age</th>{spouse_header}<th class="num">Expenses</th><th class="num">Rental income</th><th class="num">Social Security</th>{other_header}<th class="num">Need</th><th class="num">RMD</th><th class="num">Tax</th>
{_withdrawn_ending_header_html()}
<th class="num">Total</th><th></th></tr>{today_row_html}</thead>
<tbody>{rows_html}</tbody>
</table>
</div>
"""


def _render_drawdown_planning_page() -> str:
    s = build_summary()
    assumptions = s["assumptions"]
    pools = s["drawdown_pools"]
    sources = s["drawdown_sources"]
    total = sum(pools.values())

    tiles = "".join(
        f'<div class="tile"><div class="label">{html.escape(_bucket_label(bucket))}</div>'
        f'<div class="value">{_money(pools.get(bucket, 0.0))}</div></div>'
        for bucket in ("taxable", "tax_deferred", "roth", "real_estate")
    ) + f'<div class="tile"><div class="label">Total</div><div class="value">{_money(total)}</div></div>'

    donut_rows = [
        {"bucket_label": _bucket_label(bucket), "value": value}
        for bucket, value in pools.items() if value
    ]
    donut = _donut_chart_html(
        "Resources by tax bucket", _grouped_slices(donut_rows, key="bucket_label", value_key="value", max_slices=None),
        dim="tax_bucket",
    )

    unlinked_note = (
        f' <span class="muted">Includes {_money(s["drawdown_unlinked_total"])} from linked accounts '
        'not yet added to the Asset tab, auto-classified from each account\'s own Plaid subtype '
        '(Roth/IRA/401k/brokerage/...) -- add one to the Asset tab and set its Tax treatment there '
        'if you\'d rather classify it by hand.</span>'
        if s["drawdown_unlinked_total"] else ""
    )

    horizon = max(1, int(float(assumptions.get("plan_horizon_years") or 40)))
    # This page's starting pools also include unlinked live investment
    # accounts, so the spouse's share of the Tax-deferred pool is the
    # drawdown-wide one, not the Asset-rows-only figure build_summary put
    # in `assumptions` for the Monte Carlo tab.
    schedule_assumptions = {**assumptions, "spouse_tax_deferred_share": s["drawdown_spouse_tax_deferred_share"]}
    schedule = deterministic_drawdown_schedule(
        pools=pools, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=schedule_assumptions,
    )
    rental_tax_note = (
        '<p class="muted">Rental income is treated as sheltered by mortgage interest and depreciation until each '
        "property's <em>Loan ends (year)</em> on the Real Estate tab, and as taxable income after it -- so it only "
        "pushes your withdrawals into higher brackets from then on.</p>"
        if assumptions.get("rental_taxable_schedule") else ""
    )
    sale = s["real_estate_sale"]
    sale_card = sale_comparison_card_html(
        sale=sale,
        intro=(
            "Your year-by-year plan below re-run with every property sold: the proceeds join the Taxable pool, "
            "rental income stops, and everything else stays the same."
        ),
        rows=drawdown_sale_comparison(
            keep_schedule=schedule, pools=pools, expenses=s["expenses"], income=s["income_for_simulation"],
            assumptions=schedule_assumptions, sale=sale, real_estate=s["real_estate"],
            loan_balances=s["real_estate_loan_balances"],
        ),
    ) if sale["has_properties"] else ""
    has_birth_year = (assumptions.get("birth_year") or "").strip() != ""
    rmd_note = (
        "" if has_birth_year else
        ' <span class="muted">Set a Birth year in the Monte Carlo tab\'s Assumptions to also model Required '
        "Minimum Distributions (RMDs) once you reach RMD age.</span>"
    )
    retirement_year = schedule.get("retirement_year")
    retirement_year_note = (
        f' <span class="muted">No withdrawal happens before {retirement_year} (your set Retirement year) -- '
        "income is assumed to cover expenses until then, so those years are left out of the table below.</span>"
        if retirement_year is not None else
        ' <span class="muted">Set a Retirement year on the Summary or Monte Carlo tab to skip withdrawals for '
        "the years before you retire.</span>"
    )
    early_tax_deferred_age = schedule.get("early_tax_deferred_age")
    early_tax_deferred_note = (
        f' <span class="muted">Once you reach age {early_tax_deferred_age}, spending draws Tax-deferred first '
        "instead of Taxable first (see the Withdrawal order card above).</span>"
        if early_tax_deferred_age is not None else ""
    )

    body = f"""
<h2 style="margin-top:0">Drawdown planning</h2>
<p class="muted">Every retirement/liquid resource this program knows about, classified by tax treatment -- Taxable
(brokerage, taxed on gains as you withdraw), Tax-deferred (401k/Traditional IRA, taxed as ordinary income and
subject to RMDs), Roth (already taxed, grows and withdraws tax-free, never forces an RMD), and Real estate equity
opted in on the Real Estate Analysis tab (drawn last of all, untaxed here).{unlinked_note}</p>
<div class="tiles">{tiles}</div>
{donut}
<h3 style="font-size:13px; margin:20px 0 4px 0;">Resources by source</h3>
{_sources_table_html(sources)}
{_rmd_by_person_card_html(s, assumptions)}
{_account_splits_card_html(s["splittable_investment_accounts"], s["account_tax_splits"], s["account_split_mismatches"])}
{_early_tax_deferred_card_html(assumptions, early_tax_deferred_age)}
{sale_card}
<h2>Year-by-year withdrawal sequence</h2>
<p class="muted">A single deterministic projection (not a random Monte Carlo band -- see the Monte Carlo tab for
that) over the next {horizon} years at your plan's own Expected return assumption ({schedule['expected_return'] * 100:.1f}%,
set on the Monte Carlo tab). Each year withdraws Taxable first, then Tax-deferred, then Roth, then Real estate
last -- the conventional tax-efficient order -- with Required Minimum Distributions forced from the Tax-deferred
pool once you reach RMD age.{rmd_note}{retirement_year_note}{early_tax_deferred_note}</p>
{_this_years_plan_html(_visible_schedule_rows(schedule))}
{rental_tax_note}{_year_by_year_table_html(schedule)}
<p class="muted">This is the plan under today's default order (with your own Withdrawal order choice above, if set).
Looking to also minimize what an heir owes in tax, or considering a Roth conversion? See the
<a href="/legacy-planning.html">Legacy Planning</a> tab, which compares several strategies against this one.</p>
"""
    return _shell(title="Drawdown Planning", active="drawdown-planning.html", body=body)
