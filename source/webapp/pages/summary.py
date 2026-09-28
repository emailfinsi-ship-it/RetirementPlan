"""The Summary tab: net worth tiles, asset/liability breakdown, and the
"what does this actually mean" insight cards underneath them."""

from __future__ import annotations

import html

import random

from source.reporting.aggregate import build_summary
from source.reporting.monte_carlo import _resolve_retirement_year, render_fan_svg, run_simulation, stable_simulation_seed
from source.webapp.render_helpers import (
    _asset_category_summary_html,
    _asset_rollup_summary_html,
    _bar_chart_html,
    _donut_chart_html,
    _grouped_slices,
    _money,
    _pct,
    _shell,
    _sync_now_button_html,
)


def _render_summary_page() -> str:
    s = build_summary()
    assumptions = s["assumptions"]
    # "Manual asset total" used to be its own separate figure here and
    # didn't line up with what the Asset tab itself shows (it folded in
    # live-linked balances but was still labeled "manual"). Net Liquid
    # Asset and Total Asset below are the same real, Asset-tab-sourced
    # totals as the "Assets by category" tables further down the page --
    # see aggregate.build_summary()'s asset_category_subtotals.
    tiles = [
        ("Net worth", _money(s["net_worth"])),
        ("Net Liquid Asset", _money(s["net_liquid_asset"])),
        ("Total Asset", _money(s["total_asset"])),
        ("Real estate equity", _money(s["real_estate_equity_total"])),
        ("Liabilities", _money(-s["liability_total"])),
        (f"{s['next_year']} expense need", _money(s["next_year_expense_need"])),
        ("Expected rate of return", f"{_pct(assumptions, 'expected_return', 0.06)}%"),
    ]
    tiles_html = "".join(
        f'<div class="tile"><div class="label">{html.escape(label)}</div>'
        f'<div class="value">{value}</div></div>'
        for label, value in tiles
    )
    asset_summary_html = _asset_category_summary_html(
        s["asset_category_subtotals"], s["liability_total"], s["net_liquid_asset"]
    )
    asset_rollup_html = _asset_rollup_summary_html(s["net_liquid_asset"], s["real_estate_equity_total"])

    linked = s["linked_status"]
    if not linked["configured"]:
        linked_line = '<p class="status-line status-warn">No Plaid accounts linked yet -- see Setup to connect a bank/brokerage account.</p>'
    elif linked["last_synced_at"]:
        linked_line = (
            f'<p class="status-line status-ok">{linked["item_count"]} linked Plaid account(s) -- '
            f'last synced {html.escape(linked["last_synced_at"])}.</p>'
        )
    else:
        linked_line = (
            f'<p class="status-line status-warn">{linked["item_count"]} linked Plaid account(s) -- '
            f'not synced yet. Sync now below.</p>'
        )

    import_status = s["import_status"]
    if import_status["last_import_at"]:
        import_line = (
            f'<p class="status-line status-ok">Last imported from workbook: '
            f'{html.escape(import_status["last_import_at"])}</p>'
        )
    else:
        import_line = '<p class="status-line status-warn">No workbook imported yet -- see Setup for the one-time import.</p>'

    starting_balance = s["net_liquid_asset"]
    # Seeded deterministically (see stable_simulation_seed's own
    # docstring) so this "What if" card's Success rate/Median ending
    # balance always match the Monte Carlo tab's own top simulation --
    # both call run_simulation with identical starting_balance/pools/
    # assumptions/expenses/income, so an unseeded call here would run an
    # independent random 1000-path simulation and land on a different
    # (if similarly plausible) number purely by chance.
    mc_seed = stable_simulation_seed(
        starting_balance=starting_balance, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=assumptions,
        pools=s["retirement_pools"],
    )
    mc_result = run_simulation(
        starting_balance=starting_balance, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=assumptions,
        pools=s["retirement_pools"], rng=random.Random(mc_seed),
    )
    mc_chart = render_fan_svg(mc_result)
    # Real estate opted in on the Real Estate Analysis tab is a 4th pool
    # run_simulation actually draws from (it ignores `starting_balance`
    # entirely once `pools` is passed -- see monte_carlo_page.py's own
    # comment on this) -- so the true money this card simulates is
    # starting_balance + re_pool, not just starting_balance.
    re_pool = s["retirement_pools"].get("real_estate", 0.0)
    total_simulated_balance = starting_balance + re_pool
    real_estate_pool_clause = (
        f' Plus {_money(re_pool)} of real estate equity opted in on the Real Estate Analysis tab -- '
        f'{_money(total_simulated_balance)} simulated in total.'
    ) if re_pool else ""
    excluded_from_net_liquid = (
        "insurance cash value and any other unchecked Asset-tab row" if re_pool
        else "real estate equity, insurance cash value, and any unchecked Asset-tab row"
    )
    insight_html = _summary_insight_html(s)
    retirement_year_html = _retirement_year_card_html(assumptions, s["this_year"])
    sync_html = (
        _sync_now_button_html(note='Pulls current balances (and holdings, for accounts that requested "investments") from Plaid.')
        if linked["configured"] else ""
    )

    body = f"""
<div class="tiles">{tiles_html}</div>
<div class="card">
<h2 style="margin-top:0">Assets by category</h2>
<p class="muted">Same balances as the <a href="/asset.html">Asset</a> tab's own Summary tables above its line items -- add, edit, or link an account there.</p>
{asset_rollup_html}
{asset_summary_html}
</div>
{insight_html}
{retirement_year_html}
<div class="card">
<h2 style="margin-top:0">Data sources</h2>
{import_line}
{linked_line}
{sync_html}
<form class="inline" onsubmit="event.preventDefault(); postJSON('/api/export', {{}}).then(function(d) {{ alert('Exported: ' + d.path); }}).catch(function(e) {{ alert(e.message); }});">
  <button type="submit" class="primary">Generate Excel export</button>
</form>
<p class="muted">Writes a fresh .xlsx snapshot of everything currently in this program to the output folder.</p>
</div>
<div class="card">
<h2 style="margin-top:0">What if: expected return</h2>
<p class="muted">Change the rate and re-run -- this updates the same assumption the Monte Carlo tab uses, so the projection and balance below (and that tab) all move together. Starting balance is your Net Liquid Asset ({_money(starting_balance)}) -- the total of every Asset-tab row checked "In Monte Carlo?", net of liabilities (see the Net Liquid Asset tile above) -- not full net worth, since {excluded_from_net_liquid} aren't money you'd draw down in retirement unless you opt them in.{real_estate_pool_clause}</p>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/assumptions', {{expected_return_pct: this.expected_return_pct.value}})
    .then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Expected return %<input name="expected_return_pct" type="number" step="0.01" value="{_pct(assumptions, 'expected_return', 0.06)}"></label>
  <button type="submit" class="primary">Save &amp; re-run</button>
</form>
<div class="tiles" style="margin-top:12px">
  <div class="tile"><div class="label">Starting balance</div><div class="value">{_money(total_simulated_balance)}</div></div>
  <div class="tile"><div class="label">Success rate</div><div class="value">{mc_result['success_rate'] * 100:.0f}%</div></div>
  <div class="tile"><div class="label">Median ending balance</div><div class="value">{_money(mc_result['median_ending_balance'])}</div></div>
</div>
{mc_chart}
</div>
"""
    return _shell(title="Summary", active="summary.html", body=body)

def _retirement_year_card_html(assumptions: dict, this_year: int) -> str:
    """The one place "Retirement year" gets entered -- stored as the same
    `retirement_year` assumption source.reporting.monte_carlo.
    _resolve_retirement_year reads (also editable from the Monte Carlo
    tab's own Assumptions form, same shared-storage pattern as birth_year/
    expected_return). Once set, it doesn't just sit here: Monte Carlo,
    the historical stress test, and Drawdown Planning's year-by-year
    projection all stop withdrawing from the portfolio for any year
    before it (see annual_net_withdrawal_need's own docstring) -- this
    card's note and the countdown tile below are what make that
    "reflected everywhere" visible from the one place most people will
    look first."""
    retirement_year = _resolve_retirement_year(assumptions)
    if retirement_year is None:
        status_tile = ('<div class="tile"><div class="label">Retirement year</div><div class="value">Not set</div></div>')
        note = (
            'Not set yet -- Monte Carlo, the historical stress test, and Drawdown Planning all withdraw from '
            'your portfolio starting this year, same as before this field existed. Set a year below to model '
            'working (and living off income, not the portfolio) until then.'
        )
    else:
        years_away = retirement_year - this_year
        if years_away > 0:
            countdown_label, countdown_value = "Years until retirement", str(years_away)
        elif years_away == 0:
            countdown_label, countdown_value = "Years until retirement", "This year"
        else:
            countdown_label, countdown_value = "Years into retirement", str(-years_away)
        status_tile = (
            f'<div class="tile"><div class="label">Retirement year</div><div class="value">{retirement_year}</div></div>'
            f'<div class="tile"><div class="label">{countdown_label}</div><div class="value">{countdown_value}</div></div>'
        )
        note = (
            f'Every simulated year before {retirement_year} withdraws nothing from the portfolio in Monte Carlo, '
            'the historical stress test, and Drawdown Planning\'s year-by-year projection -- income is assumed to '
            'cover expenses until then. Required Minimum Distributions (if a Birth year is set) still apply '
            'regardless of this setting.'
        )
    return f"""
<div class="card">
<h2 style="margin-top:0">Retirement year</h2>
<p class="muted">{note}</p>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/assumptions', {{retirement_year: this.retirement_year.value}})
    .then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Retirement year<input name="retirement_year" type="number" step="1" placeholder="e.g. 2035" value="{html.escape(str(assumptions.get('retirement_year') or ''))}"></label>
  <button type="submit" class="primary">Save</button>
</form>
<div class="tiles" style="margin-top:12px">{status_tile}</div>
</div>
"""

def _safe_pct(numerator: float, denominator: float) -> str:
    """Formats numerator/denominator as a whole-number percent, "--" when
    the denominator is zero/negative (an empty plan, or a debt-to-asset
    ratio with no assets yet) rather than dividing by zero."""
    if not denominator or denominator <= 0:
        return "--"
    return f"{numerator / denominator * 100:.0f}%"

def _summary_insight_html(s: dict) -> str:
    """"Summary insight" card -- a quick-read financial-health strip (three
    ratio tiles) plus two breakdowns (asset allocation, top expense
    categories) built from the same build_summary()/build_summary()-derived
    figures the tiles above already use, so nothing here can disagree with
    the rest of the page. Skips entirely once every input is empty (a
    fresh, unpopulated plan) rather than showing a wall of "--"/empty
    charts."""
    if not s["assets"] and not s["real_estate"] and not s["expenses"]:
        return ""

    income_coverage = _safe_pct(s["this_year_income"], s["this_year_expense_need"])
    liquid_share = _safe_pct(s["net_liquid_asset"], s["net_worth"])
    gross_liquid_and_re = s["total_asset"] + s["liability_total"]
    debt_ratio = _safe_pct(s["liability_total"], gross_liquid_and_re)

    ratio_tiles = "".join(
        f'<div class="tile"><div class="label">{html.escape(label)}</div><div class="value">{value}</div></div>'
        for label, value in (
            (f"{s['this_year']} income covers expenses", income_coverage),
            ("Liquid share of net worth", liquid_share),
            ("Debt-to-asset ratio", debt_ratio),
        )
    )

    asset_alloc_rows = [{"category": cat, "amount": amt} for cat, amt in s["asset_category_subtotals"] if amt]
    asset_alloc_chart = _donut_chart_html(
        "Asset allocation by category",
        _grouped_slices(asset_alloc_rows, key="category", value_key="amount"),
        dim="summary-asset-category",
    )
    expense_chart = _bar_chart_html(
        "Expenses by category (annual, nominal)",
        _grouped_slices(s["expenses"], key="category", value_key="annual_amount", max_slices=8),
        dim="summary-expense-category",
    )

    return f"""
<div class="card">
<h2 style="margin-top:0">Summary insight</h2>
<p class="muted">A quick read on the plan as a whole -- how much of this year's expenses your income already covers, how liquid your net worth is, how leveraged you are, and where your assets and expenses are concentrated.</p>
<div class="tiles">{ratio_tiles}</div>
<div class="insight-row">
{asset_alloc_chart}
{expense_chart}
</div>
</div>
"""
