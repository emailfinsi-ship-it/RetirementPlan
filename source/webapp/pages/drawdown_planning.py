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


def _phase_cell_html(year: int, retirement_year: int | None) -> str:
    """Blank when no Retirement year is set at all (nothing to show);
    otherwise "Retirement" on the exact retirement year's own row (a
    visual anchor so the table reads at a glance where the working/
    retired split falls) and "Working"/"Retired" muted labels either
    side of it."""
    if retirement_year is None:
        return ""
    if year == retirement_year:
        return '<td><strong>Retirement</strong></td>'
    if year < retirement_year:
        return '<td class="muted">Working</td>'
    return '<td class="muted">Retired</td>'


def _year_by_year_table_html(schedule: dict) -> str:
    rows = schedule["rows"]
    retirement_year = schedule.get("retirement_year")
    if not rows:
        return '<p class="muted">No projection yet.</p>'
    phase_th = '<th>Phase</th>' if retirement_year is not None else ""
    rows_html = "".join(
        f'<tr><td>{r["year"]}</td>'
        f'<td>{r["age"] if r["age"] is not None else "--"}</td>'
        + _phase_cell_html(r["year"], retirement_year)
        + f'<td class="num">{_money(r["need"])}</td>'
        f'<td class="num">{_money(r["rmd"])}</td>'
        f'<td class="num">{_money(r["tax"])}</td>'
        f'<td class="num">{_money(r["taxable"])}</td>'
        f'<td class="num">{_money(r["tax_deferred"])}</td>'
        f'<td class="num">{_money(r["roth"])}</td>'
        f'<td class="num">{_money(r["real_estate"])}</td>'
        f'<td class="num">{_money(r["total"])}</td>'
        + ('<td class="status-warn">Depleted</td>' if r["shortfall"] > 1e-6 else '<td></td>')
        + '</tr>'
        for r in rows
    )
    return f"""
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th>Year</th><th>Age</th>{phase_th}<th class="num">Need</th><th class="num">RMD</th><th class="num">Tax</th>
<th class="num">Taxable</th><th class="num">Tax-deferred</th><th class="num">Roth</th><th class="num">Real estate</th>
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
        f' <span class="muted">No withdrawal happens before {retirement_year} (your set Retirement year, marked '
        "Retirement in the Phase column below) -- income is assumed to cover expenses until then.</span>"
        if retirement_year is not None else
        ' <span class="muted">Set a Retirement year on the Summary or Monte Carlo tab to skip withdrawals for '
        "the years before you retire.</span>"
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
<h2>Year-by-year withdrawal sequence</h2>
<p class="muted">A single deterministic projection (not a random Monte Carlo band -- see the Monte Carlo tab for
that) over the next {horizon} years at your plan's own Expected return assumption ({schedule['expected_return'] * 100:.1f}%,
set on the Monte Carlo tab). Each year withdraws Taxable first, then Tax-deferred, then Roth, then Real estate
last -- the conventional tax-efficient order -- with Required Minimum Distributions forced from the Tax-deferred
pool once you reach RMD age.{rmd_note}{retirement_year_note}</p>
{_year_by_year_table_html(schedule)}
"""
    return _shell(title="Drawdown Planning", active="drawdown-planning.html", body=body)
