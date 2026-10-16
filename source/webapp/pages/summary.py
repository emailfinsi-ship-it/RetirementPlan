"""The Summary tab: net worth tiles, asset/liability breakdown, and the
"what does this actually mean" insight cards underneath them."""

from __future__ import annotations

import html

import random

from source.reporting.aggregate import build_summary
from source.reporting.monte_carlo import _resolve_retirement_year, render_fan_svg, run_simulation, stable_simulation_seed
from source.webapp.render_helpers import (
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
    linked = s["linked_status"]
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
    linked_summary = (
        "No Plaid accounts linked yet." if not linked["configured"]
        else f"{linked['item_count']} linked Plaid account(s)"
        + (f", last synced {html.escape(linked['last_synced_at'])}." if linked["last_synced_at"] else ", not synced yet.")
    ) + ' Workbook import and Excel export are on the <a href="/setup.html">Setup</a> tab.'
    sync_html = (
        _sync_now_button_html(note='Pulls current balances (and holdings, for accounts that requested "investments") from Plaid.')
        if linked["configured"] else ""
    )

    retirement_year = _resolve_retirement_year(assumptions)
    if retirement_year is None:
        retirement_text = "Retirement year not set"
    else:
        years_away = retirement_year - s["this_year"]
        retirement_text = f"Retirement year {retirement_year} (" + (
            f"{years_away} year{'s' if years_away != 1 else ''} away" if years_away > 0
            else "this year" if years_away == 0 else f"{-years_away} year{'s' if years_away != -1 else ''} into retirement"
        ) + ")"

    body = f"""
<div class="tiles">{tiles_html}</div>
<div class="card">
<h2 style="margin-top:0">Plan outlook</h2>
<div class="tiles">
  <div class="tile"><div class="label">Starting balance</div><div class="value">{_money(total_simulated_balance)}</div></div>
  <div class="tile"><div class="label">Success rate</div><div class="value">{mc_result['success_rate'] * 100:.0f}%</div></div>
  <div class="tile"><div class="label">Median ending balance</div><div class="value">{_money(mc_result['median_ending_balance'])}</div></div>
</div>
<p class="muted" style="margin-bottom:0;">{html.escape(retirement_text)}, expected return {_pct(assumptions, 'expected_return', 0.06)}%.
Change these (and the other assumptions) under <a href="/monte-carlo.html#assumptions">Monte Carlo &rarr; Assumptions</a>;
the full simulation chart is on that tab. Balances by category are on the <a href="/asset.html">Asset</a> tab.</p>
</div>
{insight_html}
<p class="muted">{linked_summary}</p>
{sync_html}
"""
    return _shell(title="Summary", active="summary.html", body=body)

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
        _grouped_slices(s["expenses"], key="category", value_key="annual_amount", max_slices=None),
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
