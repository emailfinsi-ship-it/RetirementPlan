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
     exactly which account/row lands in which bucket and why.
  2. A year-by-year detail table tracing RMDs, the withdrawal order, and
     the estimated tax bill forward from today, at the plan's own
     Expected return assumption (no randomness -- see
     deterministic_drawdown_schedule's own docstring for why this is a
     single path rather than a percentile band like the Monte Carlo
     tab's fan chart).
"""

from __future__ import annotations

import html

from source.reporting.aggregate import build_summary
from source.reporting.monte_carlo import deterministic_drawdown_schedule
from source.webapp.render_helpers import _donut_chart_html, _grouped_slices, _money, _shell

_BUCKET_LABELS = {
    "tax_deferred": "Tax-deferred (401k/Traditional)",
    "roth": "Roth (tax-free)",
    "taxable": "Taxable (brokerage)",
    "real_estate": "Real estate (opted in)",
}


def _bucket_label(bucket: str) -> str:
    return _BUCKET_LABELS.get(bucket, bucket.replace("_", " ").title())


def _sources_table_html(sources: list[dict]) -> str:
    if not sources:
        return '<p class="muted">No retirement/liquid resources yet -- check "In Monte Carlo?" on an Asset-tab row, link a Plaid investment account, or opt a property in on the Real Estate Analysis tab.</p>'
    rows_html = "".join(
        f'<tr><td>{html.escape(s["name"])}</td>'
        f'<td>{html.escape(s["institution"]) if s["institution"] else "--"}</td>'
        f'<td>{html.escape(s["origin"])}</td>'
        f'<td>{html.escape(_bucket_label(s["tax_bucket"]))}</td>'
        f'<td class="num">{_money(s["balance"])}</td></tr>'
        for s in sorted(sources, key=lambda s: s["balance"], reverse=True)
    )
    total = sum(s["balance"] for s in sources)
    return f"""
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th>Source</th><th>Institution</th><th>Where it's from</th><th>Tax bucket</th><th class="num">Balance</th></tr></thead>
<tbody>{rows_html}</tbody>
<tfoot><tr><td colspan="4">Total</td><td class="num">{_money(total)}</td></tr></tfoot>
</table>
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
    parts = []
    if r["drawn_taxable"] > 0.01:
        parts.append(f"{_money(r['drawn_taxable'])} from Taxable")
    if r["drawn_tax_deferred"] > 0.01:
        rmd_clause = f" (of which {_money(r['rmd'])} is a mandatory RMD)" if r["rmd"] > 0.01 else ""
        parts.append(f"{_money(r['drawn_tax_deferred'])} from Tax-deferred{rmd_clause}")
    elif r["rmd"] > 0.01:
        parts.append(f"{_money(r['rmd'])} from Tax-deferred (a mandatory RMD, even though nothing else is needed this year)")
    if r["drawn_roth"] > 0.01:
        parts.append(f"{_money(r['drawn_roth'])} from Roth")
    if r["drawn_real_estate"] > 0.01:
        parts.append(f"{_money(r['drawn_real_estate'])} from Real estate")
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
    comment for why these rows are hidden rather than shown as $0."""
    rows = schedule["rows"]
    retirement_year = schedule.get("retirement_year")
    if not rows:
        return []
    visible_rows = rows if retirement_year is None else [r for r in rows if r["year"] >= retirement_year]
    return visible_rows or rows


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
        f"{retirement_year} on still reflect those years' own growth.</p>"
        if hidden_row_count else ""
    )
    rows_html = "".join(
        f'<tr><td>{r["year"]}</td>'
        f'<td>{r["age"] if r["age"] is not None else "--"}</td>'
        f'<td class="num">{_money(r["need"])}</td>'
        f'<td class="num">{_money(r["rmd"])}</td>'
        f'<td class="num">{_money(r["tax"])}</td>'
        f'<td class="num">{_money(r["drawn_taxable"])}</td>'
        f'<td class="num">{_money(r["drawn_tax_deferred"])}</td>'
        f'<td class="num">{_money(r["drawn_roth"])}</td>'
        f'<td class="num">{_money(r["drawn_real_estate"])}</td>'
        f'<td class="num">{_money(r["taxable"])}</td>'
        f'<td class="num">{_money(r["tax_deferred"])}</td>'
        f'<td class="num">{_money(r["roth"])}</td>'
        f'<td class="num">{_money(r["real_estate"])}</td>'
        f'<td class="num">{_money(r["total"])}</td>'
        + ('<td class="status-warn">Depleted</td>' if r["shortfall"] > 1e-6 else '<td></td>')
        + '</tr>'
        for r in visible_rows
    )
    return f"""
{hidden_years_note_html}
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th>Year</th><th>Age</th><th class="num">Need</th><th class="num">RMD</th><th class="num">Tax</th>
<th class="num">Withdrawn: Taxable</th><th class="num">Withdrawn: Tax-deferred</th><th class="num">Withdrawn: Roth</th><th class="num">Withdrawn: Real estate</th>
<th class="num">Ending: Taxable</th><th class="num">Ending: Tax-deferred</th><th class="num">Ending: Roth</th><th class="num">Ending: Real estate</th>
<th class="num">Total</th><th></th></tr></thead>
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
    schedule = deterministic_drawdown_schedule(
        pools=pools, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=assumptions,
    )
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
{_early_tax_deferred_card_html(assumptions, early_tax_deferred_age)}
<h2>Year-by-year withdrawal sequence</h2>
<p class="muted">A single deterministic projection (not a random Monte Carlo band -- see the Monte Carlo tab for
that) over the next {horizon} years at your plan's own Expected return assumption ({schedule['expected_return'] * 100:.1f}%,
set on the Monte Carlo tab). Each year withdraws Taxable first, then Tax-deferred, then Roth, then Real estate
last -- the conventional tax-efficient order -- with Required Minimum Distributions forced from the Tax-deferred
pool once you reach RMD age.{rmd_note}{retirement_year_note}{early_tax_deferred_note}</p>
{_this_years_plan_html(_visible_schedule_rows(schedule))}
{_year_by_year_table_html(schedule)}
"""
    return _shell(title="Drawdown Planning", active="drawdown-planning.html", body=body)
