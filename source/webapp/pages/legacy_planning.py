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
the "N even annual distributions" math (spouse and non-spouse alike,
editable "Spread withdrawals over ___ years" per heir type) behind the
"Estimated heir tax" column.

This tab shares its "hide pre-retirement rows"/"describe a row's own
withdrawal"/"Withdrawn: and Ending: table columns" building blocks with
the Drawdown Planning tab -- see source.webapp.render_helpers.drawdown_rows
-- since both tabs walk the same row shape; only the strategy-comparison
and heir-tax content below is unique to this tab.
"""

from __future__ import annotations

import html

from source.common import db
from source.reporting.aggregate import build_summary
from source.reporting.monte_carlo import (
    CUSTOM_BRACKET_CHOICES,
    _resolve_retirement_year,
    compare_roth_conversion_strategies,
    normalize_custom_strategy,
)
from source.webapp.render_helpers import (
    _money,
    _shell,
    _visible_rows_by_year,
    _withdrawal_parts,
    _visible_withdrawn_ending_columns,
    _withdrawn_ending_cells_html,
    _withdrawn_ending_header_html,
)

_HEIR_TYPE_LABELS = {
    "non_spouse": "Non-spouse (adult child, etc.)",
    "spouse": "Spouse",
}


def _heir_assumptions_card_html(result: dict, assumptions: dict) -> str:
    heir_type = result["heir_type"]
    heir_base_income = result["heir_base_income"]
    heir_marginal_rate = result["heir_marginal_rate"]
    heir_spread_years = result["heir_spread_years"]
    raw_base_income = assumptions.get("heir_base_income")
    base_income_value = html.escape(str(raw_base_income)) if raw_base_income not in (None, "") else ""
    raw_spread_years = assumptions.get("heir_spread_years")
    spread_years_value = html.escape(str(raw_spread_years)) if raw_spread_years not in (None, "") else ""
    options_html = "".join(
        f'<option value="{key}"{" selected" if key == heir_type else ""}>{html.escape(label)}</option>'
        for key, label in _HEIR_TYPE_LABELS.items()
    )
    return f"""
<div class="card">
<h2 style="margin-top:0">Heir assumptions</h2>
<details class="how-it-works"><summary>How this works</summary><p class="muted">A spouse can roll an inherited Traditional IRA into their own and take Required Minimum Distributions
on their own schedule -- no forced window at all; a non-spouse heir (an adult child, etc.) must usually empty it within
10 years of your death under the SECURE Act, often stacking on top of their own working-years income. Some non-spouse
heirs (a minor child of yours until they reach majority, a disabled or chronically ill beneficiary) are exempt from that
flat 10-year rule too and can stretch distributions over their own life expectancy instead. Rather than assume one
number fits every case, "Spread withdrawals over" below is editable directly -- right now it's {heir_spread_years} years
for the heir picked below (10 for non-spouse, matching the SECURE Act's own default window; 20 for spouse, a
placeholder for "a long remaining lifetime") -- type over it for your own real situation. "Heir's assumed income" is
what their own inherited distributions are assumed to stack on top of -- auto-filled from this plan's own current
Yearly Drawdown need ("use my own current bracket as a stand-in"), estimated right now at {_money(heir_base_income)}
(about a {heir_marginal_rate * 100:.1f}% combined federal + California marginal rate) -- type over it if you have a
better estimate of your heir's own income.</p></details>
<form class="inline" onsubmit="event.preventDefault();
  var fields = {{}};
  new FormData(this).forEach(function(value, key) {{ fields[key] = value; }});
  postJSON('/api/assumptions', fields).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Heir<select name="heir_type">{options_html}</select></label>
  <label>Spread withdrawals over<input name="heir_spread_years" type="number" step="1" min="1" placeholder="{heir_spread_years}" value="{spread_years_value}"> years</label>
  <label>Heir's assumed income<input name="heir_base_income" type="number" step="0.01" placeholder="{_money(heir_base_income)}" value="{base_income_value}"></label>
  <button type="submit" class="primary">Save &amp; re-run</button>
</form>
</div>
"""


def _this_years_plan_html(result: dict, retirement_year: int | None) -> str:
    """A plain-language callout naming the RECOMMENDED strategy's first
    VISIBLE year in one place -- which source to draw from and how
    much, PLUS how much to convert to Roth this year -- so the direct
    answer to the user's own question ("how much I need to plan to
    convert to Roth") doesn't require reading the 6-strategy comparison
    table below it. Per the user's own feedback on the first version of
    this page ("I dont know this tab. All I wanted to know..."), this
    is deliberately the very first thing on the page, before even the
    Heir assumptions card."""
    strategies = result["strategies"]
    if not strategies:
        return ""
    top = strategies[0]
    rows = _visible_rows_by_year(top["rows"], retirement_year)
    if not rows:
        return ""
    r = rows[0]
    parts = _withdrawal_parts(r)
    if parts:
        withdrawal_text = "Withdraw " + ", plus ".join(parts) + " to cover this year's spending."
    else:
        withdrawal_text = "Nothing needs to come out of the portfolio for spending this year."
    if r["conversion"] > 0.01:
        conversion_text = (
            f"Convert {_money(r['conversion'])} from Tax-deferred to Roth "
            f"(costs about {_money(r['conversion_tax'])} in tax today, paid from Taxable)."
        )
    else:
        conversion_text = "No Roth conversion this year under the recommended strategy."
    baseline_key = result["baseline_key"]
    strategy_clause = (
        "" if top["key"] == baseline_key
        else f" -- the recommended strategy is “{html.escape(top['label'])}”, not {_baseline_phrase(result)}"
    )
    return f"""
<div class="card" style="border: 2px solid #2a78d6;">
<h2 style="margin-top:0">Your plan for {r['year']}{strategy_clause}</h2>
<p style="font-size:15px;">{withdrawal_text}</p>
<p style="font-size:15px; margin-bottom:0;">{conversion_text}</p>
</div>
"""


def _baseline_phrase(result: dict) -> str:
    """What to call the baseline row: "today's default" normally, "your
    current plan" once the plan's own early Tax-deferred draw age is set
    (the baseline then follows that setting -- see
    compare_roth_conversion_strategies)."""
    return "your current plan" if result.get("plan_early_tax_deferred_age") is not None else "today's default"


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
    return f"""<div style="position:relative; height:14px; background:var(--border); border-radius:4px;">
<div style="position:absolute; left:0; width:{width_pct:.1f}%; height:100%; border-radius:4px; background:#2a78d6;"></div>
</div>"""


def _early_age_note_html(result: dict) -> str:
    age = result.get("plan_early_tax_deferred_age")
    if age is None:
        return ""
    return (
        f'<p class="muted">Your plan starts spending Tax-deferred first at age {age} (Drawdown Planning tab), so that '
        "applies to the baseline and to every conversion row below -- each is compared with the plan you're "
        "actually running, not with a Taxable-first plan you aren't.</p>"
    )


_CLOSE_CALL_PCT = 2.0


def _gap_pct(strategies: list[dict]) -> float | None:
    """How far ahead #1 is of #2, as a percent of #1's net after-tax legacy."""
    if len(strategies) < 2 or strategies[0]["net_after_tax_legacy"] <= 0:
        return None
    return (strategies[0]["net_after_tax_legacy"] - strategies[1]["net_after_tax_legacy"]) / strategies[0]["net_after_tax_legacy"] * 100.0


def _is_close_call(strategies: list[dict]) -> bool:
    gap = _gap_pct(strategies)
    return gap is not None and gap < _CLOSE_CALL_PCT


def _short_label(s: dict, result: dict) -> str:
    if s["key"] == result["baseline_key"]:
        return "Your current plan" if result.get("plan_early_tax_deferred_age") is not None else "No conversions"
    if s.get("is_custom"):
        return "Your what-if"
    label = s["label"]
    return label.replace("Convert up to the ", "Fill the ").replace(" federal bracket each year", " bracket")


def _how_we_arrived_html(result: dict) -> str:
    """The math behind the Recommended badge, with the plan's own numbers:
    the ranking rule, the recommended strategy's net-legacy sum side by
    side with the baseline's, the tax paid today versus legacy gained,
    how close the call is, and what the model leaves out."""
    strategies = result["strategies"]
    if len(strategies) < 2:
        return ""
    top = strategies[0]
    base = next(s for s in strategies if s["key"] == result["baseline_key"])
    top_is_base = top["key"] == base["key"]
    gap = _gap_pct(strategies)
    second = strategies[1]

    def row(label: str, a: float, b: float, *, strong: bool = False, sign: str = "") -> str:
        fmt = (lambda v: f"<strong>{_money(v)}</strong>") if strong else _money
        diff = a - b
        diff_txt = f"{'+' if diff >= 0 else '-'}{_money(abs(diff))}"
        return (
            f'<tr><td>{label}</td><td class="num">{sign}{fmt(a)}</td>'
            + ('' if top_is_base else f'<td class="num">{sign}{fmt(b)}</td><td class="num">{diff_txt}</td>')
            + '</tr>'
        )

    head_cols = (
        f'<th class="num">{html.escape(_short_label(top, result))} (recommended)</th>'
        if top_is_base else
        f'<th class="num">{html.escape(_short_label(top, result))} (recommended)</th>'
        f'<th class="num">{html.escape(_short_label(base, result))}</th><th class="num">Difference</th>'
    )
    sum_rows = (
        row("Ending Roth balance (tax-free to your heirs)", top["ending_roth"], base["ending_roth"])
        + row("+ Ending Taxable balance", top["ending_taxable"], base["ending_taxable"])
        + row("+ Ending real estate", top["ending_real_estate"], base["ending_real_estate"])
        + row("+ Ending Tax-deferred (401k/IRA) balance", top["ending_tax_deferred"], base["ending_tax_deferred"])
        + row("&minus; Tax your heirs would owe on that Tax-deferred balance", top["estimated_heir_tax"], base["estimated_heir_tax"])
        + row("= Net after-tax legacy", top["net_after_tax_legacy"], base["net_after_tax_legacy"], strong=True)
    )
    price_html = ""
    if not top_is_base:
        extra_tax = top["total_lifetime_tax"] - base["total_lifetime_tax"]
        gain = top["net_after_tax_legacy"] - base["net_after_tax_legacy"]
        if extra_tax > 0:
            ratio = f" -- about ${gain / extra_tax:,.1f} of extra legacy for every $1 of extra tax" if gain > 0 else ""
            price_html = (
                f"<p><strong>What it costs and what it buys.</strong> Over your lifetime you pay about "
                f"{_money(extra_tax)} more tax than under {html.escape(_short_label(base, result)).lower()}, "
                f"and your heirs end up with about {_money(gain)} more after their tax{ratio}.</p>"
            )
        else:
            price_html = (
                f"<p><strong>What it costs and what it buys.</strong> It also lowers your own lifetime tax, by about "
                f"{_money(-extra_tax)}, while leaving your heirs about {_money(gain)} more after their tax.</p>"
            )
    if gap is None:
        close_html = ""
    elif gap < _CLOSE_CALL_PCT:
        tied = [s for s in strategies if (top["net_after_tax_legacy"] - s["net_after_tax_legacy"]) / top["net_after_tax_legacy"] * 100.0 < _CLOSE_CALL_PCT]
        names = ", ".join(html.escape(_short_label(s, result)) for s in tied)
        close_html = (
            f'<p><strong>How close is it?</strong> A close call. The winner is only {gap:.1f}% ahead of the runner-up '
            f"({html.escape(_short_label(second, result))}, {_money(top['net_after_tax_legacy'] - second['net_after_tax_legacy'])} less). "
            f"Treat these as roughly tied: {names}. A projection this far out can't separate them, so choose on the "
            "things the model does not capture (below) and on how comfortable you are with the tax you'd pay now.</p>"
        )
    else:
        close_html = (
            f'<p><strong>How close is it?</strong> The winner is {gap:.1f}% ahead of the runner-up '
            f"({html.escape(_short_label(second, result))}, {_money(top['net_after_tax_legacy'] - second['net_after_tax_legacy'])} less) "
            "-- a clear but not overwhelming lead. Small changes to the assumptions can still move it.</p>"
        )
    spread = result["heir_spread_years"]
    heir_html = (
        f"<p><strong>Heir assumptions used.</strong> {_HEIR_TYPE_LABELS.get(result['heir_type'], result['heir_type'])}, "
        f"withdrawing the inherited Tax-deferred balance evenly over {spread} years on top of an assumed "
        f"{_money(result['heir_base_income'])} of their own income (about a {result['heir_marginal_rate'] * 100:.1f}% "
        "combined federal + California marginal rate). You can change all three in the Heir assumptions card above.</p>"
    )
    return f"""
<details class="card" id="how-we-arrived" style="padding:12px 16px;">
<summary style="font-weight:600; cursor:pointer;">How we arrived at this recommendation</summary>
<p style="margin-top:10px;"><strong>The rule.</strong> Every strategy replays your plan year by year with the same engine as the Drawdown
Planning tab, then is scored on one number: <em>net after-tax legacy</em> -- what is left for your heirs after their own tax.
Roth and Taxable money counts in full (Roth is tax-free; Taxable gets a stepped-up cost basis at death), and Tax-deferred money
counts after the income tax your heirs would owe on it. The highest score is marked Recommended; a tie goes to the strategy
that costs you less tax.</p>
<div style="overflow-x:auto"><table class="sortable">
<thead><tr><th>Net legacy, added up</th>{head_cols}</tr></thead>
<tbody>{sum_rows}</tbody>
</table></div>
{price_html}
{close_html}
{heir_html}
<p><strong>What this does not model.</strong> One steady average return (no market ups and downs), 2026 federal and California
married-filing-jointly brackets grown with inflation (no law changes), Medicare premium surcharges (IRMAA) and ACA subsidy effects
that a big conversion can trigger, state moves, and your heir's actual circumstances. Treat it as a way to compare strategies
against each other, not as a forecast of exact dollars -- and check with a tax professional before converting.</p>
</details>
"""


def _whatif_card_html(result: dict) -> str:
    """The "Try your own" form: one extra strategy row, saved with the plan."""
    custom = result.get("custom")
    strategies = result["strategies"]
    bracket = custom["bracket"] if custom else 0.24
    options = "".join(
        f'<option value="{rate}"{" selected" if custom and bracket == rate or (not custom and rate == 0.24) else ""}>'
        f'{rate * 100:g}% bracket</option>'
        for rate in CUSTOM_BRACKET_CHOICES
    ) + f'<option value="none"{" selected" if custom and bracket == "none" else ""}>No bracket limit (use the yearly cap)</option>'
    cap_value = f"{custom['annual_cap']:.0f}" if custom and custom.get("annual_cap") else ""
    stop_value = str(custom["stop_age"]) if custom and custom.get("stop_age") else ""
    status_html = ""
    if custom:
        mine = next((s for s in strategies if s.get("is_custom")), None)
        base = next(s for s in strategies if s["key"] == result["baseline_key"])
        if mine:
            rank = strategies.index(mine) + 1
            delta = mine["net_after_tax_legacy"] - base["net_after_tax_legacy"]
            status_html = (
                f'<p class="status-line" style="margin:10px 0 0;">Your what-if ranks <strong>#{rank} of {len(strategies)}</strong>: '
                f"net after-tax legacy {_money(mine['net_after_tax_legacy'])} "
                f"({'+' if delta >= 0 else '-'}{_money(abs(delta))} versus {html.escape(_short_label(base, result)).lower()}), "
                f"converting {_money(mine['total_converted'])} in total and paying {_money(mine['total_lifetime_tax'])} in lifetime tax.</p>"
            )
    clear_btn = (
        '<button type="button" onclick="postJSON(\'/api/legacy-whatif\', {clear: true}).then(function() { location.reload(); })'
        '.catch(function(e) { alert(e.message); });">Remove my what-if</button>'
        if custom else ""
    )
    return f"""
<div class="card" id="legacy-whatif">
<h3 style="margin:0 0 4px 0;">Try your own strategy</h3>
<p class="muted">Adds one extra row to the table below, ranked against the others. Federal brackets are 10, 12, 22, 24, 32, 35
and 37% (there is no 25% bracket -- 24% is the closest), so to land between two of the rows use the yearly cap: for example
fill the 24% bracket but never convert more than $200,000 a year. The cap is in today's dollars and grows with inflation.</p>
<form class="inline" onsubmit="event.preventDefault();
  var f = this;
  postJSON('/api/legacy-whatif', {{bracket: f.bracket.value, annual_cap: f.annual_cap.value, stop_age: f.stop_age.value}})
    .then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Convert up to<select name="bracket">{options}</select></label>
  <label>Yearly cap (optional)<input name="annual_cap" type="number" min="1" step="1000" placeholder="no cap" value="{cap_value}"></label>
  <label>Stop converting after age (optional)<input name="stop_age" type="number" min="30" max="120" step="1" placeholder="no stop" value="{stop_value}"></label>
  <button type="submit" class="primary">Add to comparison</button>
  {clear_btn}
</form>
{status_html}
</div>
"""


def _comparison_table_html(result: dict) -> str:
    strategies = result["strategies"]
    baseline_key = result["baseline_key"]
    recommended_key = strategies[0]["key"] if strategies else None
    max_legacy = max((s["net_after_tax_legacy"] for s in strategies), default=0.0)
    close_call = _is_close_call(strategies)

    rows_html = "".join(
        f'<tr><td>{html.escape(s["label"])}'
        + (' <span class="status-ok">Recommended</span>' if s["key"] == recommended_key else "")
        + (' <span class="muted">(close call)</span>' if s["key"] == recommended_key and close_call else "")
        + (' <span class="badge-whatif">Your what-if</span>' if s.get("is_custom") else "")
        + (f' <span class="muted">({_baseline_phrase(result)})</span>' if s["key"] == baseline_key else "")
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
<th class="num">Estimated heir tax</th><th class="num">Net after-tax legacy</th><th class="num">vs. {_baseline_phrase(result)}</th>
<th>Net after-tax legacy</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
</div>
"""


def _recommended_year_by_year_html(result: dict, retirement_year: int | None) -> str:
    strategies = result["strategies"]
    if not strategies:
        return ""
    top = strategies[0]
    all_rows = top["rows"]
    rows = _visible_rows_by_year(all_rows, retirement_year)
    hidden_row_count = len(all_rows) - len(rows)
    hidden_years_note_html = (
        f'<p class="muted">Years before {retirement_year} (your set Retirement year) are omitted below, same as the '
        "Drawdown Planning tab -- the balances shown from there on still reflect those years' own growth (and any "
        "conversion that happened before retirement).</p>"
        if hidden_row_count else ""
    )
    columns = _visible_withdrawn_ending_columns(rows)
    rows_html = "".join(
        f'<tr><td>{r["year"]}</td>'
        f'<td>{r["age"] if r["age"] is not None else "--"}</td>'
        f'<td class="num">{_money(r["rmd"])}</td>'
        f'<td class="num">{_money(r["conversion"])}</td>'
        f'<td class="num">{_money(r["tax"] + r["conversion_tax"])}</td>'
        + _withdrawn_ending_cells_html(r, columns)
        + f'<td class="num">{_money(r["total"])}</td>'
        + ('<td class="status-warn">Depleted</td>' if r["shortfall"] > 1e-6 else '<td></td>')
        + '</tr>'
        for r in rows
    )
    return f"""
<h3 style="font-size:13px; margin:20px 0 4px 0;">Year-by-year: {html.escape(top["label"])}</h3>
<p class="muted">The recommended strategy's own projection, same mechanics as the Drawdown Planning tab's year-by-year
table, with two added columns: Conversion (how much moved Tax-deferred -&gt; Roth that year) and Tax (drawdown tax plus
that year's conversion tax combined).</p>
{hidden_years_note_html}
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th>Year</th><th>Age</th><th class="num">RMD</th><th class="num">Conversion</th><th class="num">Tax</th>
{_withdrawn_ending_header_html(columns)}
<th class="num">Total</th><th></th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
</div>
"""


def _render_legacy_planning_page() -> str:
    s = build_summary()
    assumptions = s["assumptions"]
    pools = s["drawdown_pools"]
    # Same starting pools as the Drawdown Planning tab (unlinked live
    # accounts included), so the same drawdown-wide spouse share of the
    # Tax-deferred pool applies -- see that page for why.
    assumptions = {**assumptions, "spouse_tax_deferred_share": s["drawdown_spouse_tax_deferred_share"]}

    try:
        custom = normalize_custom_strategy(db.legacy_whatif())
    except ValueError:
        custom = None
    result = compare_roth_conversion_strategies(
        pools=pools, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=assumptions, custom=custom,
    )
    total_pool = sum(pools.values())
    sale_card = (
        '<p class="muted small" style="margin:10px 0"><strong>Thinking of selling your real estate?</strong> '
        'The side-by-side keep-vs-sell comparison is on the <a href="/monte-carlo.html#sell-real-estate">'
        'Will my money last?</a> tab.</p>'
    ) if s["real_estate_sale"]["has_properties"] else ""
    retirement_year = _resolve_retirement_year(assumptions)
    retirement_year_note = (
        f' <span class="muted">No withdrawal happens before {retirement_year} (your set Retirement year), same as '
        "the Drawdown Planning tab -- years before it are left out of the callout and table below.</span>"
        if retirement_year is not None else
        ' <span class="muted">Set a Retirement year on the Summary or Will my money last? tab to have this tab match the '
        "Drawdown Planning tab's own pre-retirement gating.</span>"
    )

    body = f"""
<h2 style="margin-top:0">Legacy Planning</h2>
<details class="how-it-works"><summary>How this works</summary><p class="muted">Today's default withdrawal order (Taxable, then Tax-deferred, then Roth, then Real estate -- see the
Drawdown Planning tab) is built to minimize YOUR OWN lifetime tax bill. It isn't necessarily what leaves the most
after-tax money to an heir: a Roth balance passes to any heir 100% tax-free, a Taxable balance gets a full step-up in
cost basis at death (no capital-gains tax on the appreciation up to your death), but a Tax-deferred (401k/Traditional)
balance is taxed as the heir's own ordinary income -- often within a forced 10-year window for a non-spouse heir under
the SECURE Act. Converting some Tax-deferred money to Roth now, at a real tax cost today, can leave more after-tax
money in the family's hands than doing nothing would -- but not always, since that tax comes out of money that would
otherwise keep compounding. A related but different lever: 401k/IRA withdrawals are already penalty-free from age 59&#189;,
well before RMDs would force them at 73 or 75 -- spending Tax-deferred money earlier, in the lower-income years before
then, is compared below too, alongside the Roth-conversion strategies. The table below runs the actual numbers for your
plan (starting from {_money(total_pool)} across Taxable/Tax-deferred/Roth/Real estate, same starting point as the
Drawdown Planning tab) rather than assuming any one answer.{retirement_year_note}</p></details>
{_this_years_plan_html(result, retirement_year)}
<h2>Strategy comparison</h2>
<details class="how-it-works"><summary>How this works</summary><p class="muted">Each row replays your plan's own deterministic projection (same engine as Drawdown Planning, no
randomness) once per strategy, converting Tax-deferred to Roth every year up to that strategy's target -- capped so the
conversion's own tax can be paid from the Taxable pool without an extra tax-deferred withdrawal, which would give away
much of the point of converting. "Net after-tax legacy" is Taxable + Roth + Real estate at full value, plus whatever
Tax-deferred survives net of the Estimated heir tax column. A depleted strategy (ran out of money during your own
lifetime) is flagged rather than hidden -- a smaller legacy from a strategy that never ran out beats a larger one on
paper that only looks that way because the money ran out.</p></details>
{_early_age_note_html(result)}
{_comparison_table_html(result)}
{_recommended_year_by_year_html(result, retirement_year)}
{_how_we_arrived_html(result)}
{_whatif_card_html(result)}
{_heir_assumptions_card_html(result, assumptions)}
{sale_card}
<p class="muted">This compares strategies against each other for legacy purposes. For your day-to-day plan under
today's default order (or your own Withdrawal order choice), see the <a href="/drawdown-planning.html">Drawdown
Planning</a> tab.</p>
"""
    return _shell(title="Legacy Planning", active="legacy-planning.html", body=body)
