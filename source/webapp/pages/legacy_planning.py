"""The Legacy Planning tab: compares today's default withdrawal order
(no Roth conversions at all) against a handful of named Roth-conversion
strategies on two numbers -- your own lifetime tax bill, and an
estimated after-tax legacy once what's left passes to an heir -- per
the user's own request ("best choices of sources for drawdown
minimizing tax strategy and maximizing transfer of asset to heir").

See source.reporting.monte_carlo.legacy_planning's own module docstring
for the modeling: why a Roth-heavy ending balance beats a Tax-deferred-
heavy one for legacy purposes even though today's default order
(Taxable first) is the one that minimizes YOUR OWN lifetime tax, and
the spouse-vs-non-spouse-heir/10-year-SECURE-Act-window math behind the
"Estimated heir tax" column.
"""

from __future__ import annotations

import html

from source.reporting.aggregate import build_summary
from source.reporting.monte_carlo import compare_roth_conversion_strategies
from source.webapp.render_helpers import _money, _shell

_HEIR_TYPE_LABELS = {
    "non_spouse": "Non-spouse (adult child, etc.)",
    "spouse": "Spouse",
}


def _heir_assumptions_card_html(result: dict, assumptions: dict) -> str:
    heir_type = result["heir_type"]
    heir_base_income = result["heir_base_income"]
    heir_marginal_rate = result["heir_marginal_rate"]
    raw_base_income = assumptions.get("heir_base_income")
    base_income_value = html.escape(str(raw_base_income)) if raw_base_income not in (None, "") else ""
    options_html = "".join(
        f'<option value="{key}"{" selected" if key == heir_type else ""}>{html.escape(label)}</option>'
        for key, label in _HEIR_TYPE_LABELS.items()
    )
    return f"""
<div class="card">
<h2 style="margin-top:0">Heir assumptions</h2>
<p class="muted">A spouse can roll an inherited Traditional IRA into their own and take Required Minimum Distributions
on their own schedule; a non-spouse heir (an adult child, etc.) must empty it within 10 years of your death under the
SECURE Act, often stacking on top of their own working-years income -- so which one applies changes the estimated tax
below a lot. "Heir's assumed income" is what their own inherited distributions are assumed to stack on top of --
auto-filled from this plan's own current Yearly Drawdown need ("use my own current bracket as a stand-in"), estimated
right now at {_money(heir_base_income)} (about a {heir_marginal_rate * 100:.1f}% combined federal + California marginal
rate) -- type over it if you have a better estimate of your heir's own income.</p>
<form class="inline" onsubmit="event.preventDefault();
  var fields = {{}};
  new FormData(this).forEach(function(value, key) {{ fields[key] = value; }});
  postJSON('/api/assumptions', fields).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Heir<select name="heir_type">{options_html}</select></label>
  <label>Heir's assumed income<input name="heir_base_income" type="number" step="0.01" placeholder="{_money(heir_base_income)}" value="{base_income_value}"></label>
  <button type="submit" class="primary">Save &amp; re-run</button>
</form>
</div>
"""


def _strategy_bar_html(value: float, max_value: float) -> str:
    """A single horizontal magnitude bar for one strategy's net
    after-tax legacy -- same "div bar on a shared axis" construction as
    monte_carlo_page._tornado_track_html's sensitivity tornado, just a
    single sequential-hue bar (one measure -- dollars of legacy -- being
    compared across strategies, not several distinct categories that
    would need distinct hues) rather than a low/high range."""
    if max_value <= 0:
        width_pct = 0.0
    else:
        width_pct = max(0.0, min(100.0, value / max_value * 100.0))
    return f"""<div style="position:relative; height:14px; background:#eef1f5; border-radius:4px;">
<div style="position:absolute; left:0; width:{width_pct:.1f}%; height:100%; border-radius:4px; background:#2a78d6;"></div>
</div>"""


def _comparison_table_html(result: dict) -> str:
    strategies = result["strategies"]
    baseline_key = result["baseline_key"]
    recommended_key = strategies[0]["key"] if strategies else None
    max_legacy = max((s["net_after_tax_legacy"] for s in strategies), default=0.0)

    rows_html = "".join(
        f'<tr><td>{html.escape(s["label"])}'
        + (' <span class="status-ok">Recommended</span>' if s["key"] == recommended_key else "")
        + (' <span class="muted">(today\'s default)</span>' if s["key"] == baseline_key else "")
        + (' <span class="status-warn">Depleted</span>' if s["depletes"] else "")
        + '</td>'
        f'<td class="num">{_money(s["total_converted"])}</td>'
        f'<td class="num">{_money(s["total_lifetime_tax"])}</td>'
        f'<td class="num">{_money(s["ending_tax_deferred"])}</td>'
        f'<td class="num">{_money(s["ending_roth"])}</td>'
        f'<td class="num">{_money(s["ending_taxable"] + s["ending_real_estate"])}</td>'
        f'<td class="num">{_money(s["estimated_heir_tax"])}</td>'
        f'<td class="num"><strong>{_money(s["net_after_tax_legacy"])}</strong></td>'
        f'<td class="num">{"+" if s["legacy_gain_vs_baseline"] >= 0 else ""}{_money(s["legacy_gain_vs_baseline"])}</td>'
        '<td style="min-width:120px">' + _strategy_bar_html(s["net_after_tax_legacy"], max_legacy) + '</td>'
        '</tr>'
        for s in strategies
    )
    return f"""
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th>Strategy</th><th class="num">Total converted</th><th class="num">Your lifetime tax</th>
<th class="num">Ending Tax-deferred</th><th class="num">Ending Roth</th><th class="num">Ending Taxable + Real estate</th>
<th class="num">Estimated heir tax</th><th class="num">Net after-tax legacy</th><th class="num">vs. today's default</th>
<th>Net after-tax legacy</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
</div>
"""


def _recommended_year_by_year_html(result: dict) -> str:
    strategies = result["strategies"]
    if not strategies:
        return ""
    top = strategies[0]
    rows = top["rows"]
    rows_html = "".join(
        f'<tr><td>{r["year"]}</td>'
        f'<td>{r["age"] if r["age"] is not None else "--"}</td>'
        f'<td class="num">{_money(r["rmd"])}</td>'
        f'<td class="num">{_money(r["conversion"])}</td>'
        f'<td class="num">{_money(r["tax"] + r["conversion_tax"])}</td>'
        f'<td class="num">{_money(r["taxable"])}</td>'
        f'<td class="num">{_money(r["tax_deferred"])}</td>'
        f'<td class="num">{_money(r["roth"])}</td>'
        f'<td class="num">{_money(r["total"])}</td>'
        + ('<td class="status-warn">Depleted</td>' if r["shortfall"] > 1e-6 else '<td></td>')
        + '</tr>'
        for r in rows
    )
    return f"""
<h3 style="font-size:13px; margin:20px 0 4px 0;">Year-by-year: {html.escape(top["label"])}</h3>
<p class="muted">The recommended strategy's own projection, same mechanics as the Drawdown Planning tab's year-by-year
table, with two added columns: Conversion (how much moved Tax-deferred -&gt; Roth that year) and Tax (drawdown tax plus
that year's conversion tax combined).</p>
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th>Year</th><th>Age</th><th class="num">RMD</th><th class="num">Conversion</th><th class="num">Tax</th>
<th class="num">Taxable</th><th class="num">Tax-deferred</th><th class="num">Roth</th><th class="num">Total</th><th></th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
</div>
"""


def _render_legacy_planning_page() -> str:
    s = build_summary()
    assumptions = s["assumptions"]
    pools = s["drawdown_pools"]

    result = compare_roth_conversion_strategies(
        pools=pools, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=assumptions,
    )
    total_pool = sum(pools.values())

    body = f"""
<h2 style="margin-top:0">Legacy planning</h2>
<p class="muted">Today's default withdrawal order (Taxable, then Tax-deferred, then Roth, then Real estate -- see the
Drawdown Planning tab) is built to minimize YOUR OWN lifetime tax bill. It isn't necessarily what leaves the most
after-tax money to an heir: a Roth balance passes to any heir 100% tax-free, a Taxable balance gets a full step-up in
cost basis at death (no capital-gains tax on the appreciation up to your death), but a Tax-deferred (401k/Traditional)
balance is taxed as the heir's own ordinary income -- often within a forced 10-year window for a non-spouse heir under
the SECURE Act. Converting some Tax-deferred money to Roth now, at a real tax cost today, can leave more after-tax
money in the family's hands than doing nothing would -- but not always, since that tax comes out of money that would
otherwise keep compounding. The table below runs the actual numbers for your plan (starting from
{_money(total_pool)} across Taxable/Tax-deferred/Roth/Real estate, same starting point as the Drawdown Planning tab)
rather than assuming either answer.</p>
{_heir_assumptions_card_html(result, assumptions)}
<h2>Strategy comparison</h2>
<p class="muted">Each row replays your plan's own deterministic projection (same engine as Drawdown Planning, no
randomness) once per strategy, converting Tax-deferred to Roth every year up to that strategy's target -- capped so the
conversion's own tax can be paid from the Taxable pool without an extra tax-deferred withdrawal, which would give away
much of the point of converting. "Net after-tax legacy" is Taxable + Roth + Real estate at full value, plus whatever
Tax-deferred survives net of the Estimated heir tax column. A depleted strategy (ran out of money during your own
lifetime) is flagged rather than hidden -- a smaller legacy from a strategy that never ran out beats a larger one on
paper that only looks that way because the money ran out.</p>
{_comparison_table_html(result)}
{_recommended_year_by_year_html(result)}
"""
    return _shell(title="Legacy Planning", active="legacy-planning.html", body=body)
