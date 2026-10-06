"""The two Asset/Summary-tab rollup tables (category subtotals -> Net
Liquid Asset, and Net Liquid Asset + real estate -> Total Asset) shared
between the Asset tab and the Summary tab.
"""

from __future__ import annotations

import html

from source.webapp.render_helpers.formatting import _money


def _asset_category_summary_html(category_subtotals: list[tuple[str, float]], liability_total: float, net_liquid_asset: float) -> str:
    """The first top-of-page table: one row per asset category (401k,
    Liquid, Insurance, whatever else exists -- same categories as the
    detail tables below, same order), a Liabilities row, and a
    Net Liquid Asset total -- only the rows checked "In Monte Carlo?"
    (the same per-row selection the Monte Carlo tab's starting balance
    uses -- see source.reporting.aggregate.build_summary), net of
    liabilities. A category with nothing checked in it (e.g. Insurance,
    left unchecked by default) still shows its own row above, but
    contributes nothing to this total; real estate is the second top
    table below."""
    category_rows = "".join(
        f'<tr><td>{html.escape(cat)}</td><td class="num">{_money(subtotal)}</td></tr>'
        for cat, subtotal in category_subtotals
    )
    return f"""
<div style="font-weight:600; font-size:13px; margin:0 0 4px 0; color:var(--ink-soft);">Summary</div>
<table class="sortable">
<thead><tr><th>Category</th><th class="num">Amount</th></tr></thead>
<tbody>
{category_rows}
<tr><td>Liabilities</td><td class="num">{_money(-liability_total)}</td></tr>
</tbody>
<tfoot><tr><td>Net Liquid Asset</td><td class="num">{_money(net_liquid_asset)}</td></tr></tfoot>
</table>
<p class="muted">Net Liquid Asset = the balance of every asset row checked "In Monte Carlo?", minus total liabilities -- not an unchecked row above, and not real estate (see the next table).</p>
"""


def _asset_rollup_summary_html(net_liquid_asset: float, real_estate_total: float) -> str:
    """The second top-of-page table: Net Liquid Asset (from the table
    above) plus real estate's effective equity (current value minus its
    live-if-linked loan balance -- same figure as the Real Estate Asset
    section's own Equity subtotal below) rolled up into one Total Asset
    figure. A narrower, liquid-plus-real-estate net worth -- distinct
    from the "Total assets (including real estate equity)" line further
    down the page, which also folds in Insurance and any other
    non-liquid categories without netting out liabilities."""
    total_asset = net_liquid_asset + real_estate_total
    return f"""
<table class="sortable">
<thead><tr><th>Item</th><th class="num">Amount</th></tr></thead>
<tbody>
<tr><td>Net Liquid Asset</td><td class="num">{_money(net_liquid_asset)}</td></tr>
<tr><td>Effective Equity on Real Estate</td><td class="num">{_money(real_estate_total)}</td></tr>
</tbody>
<tfoot><tr><td>Total Asset</td><td class="num">{_money(total_asset)}</td></tr></tfoot>
</table>
"""
