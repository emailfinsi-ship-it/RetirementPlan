"""HTML for the "what if I sold my real estate" what-if -- the settings
form and proceeds breakdown on the Real Estate tab, and the Keep-vs-Sell
comparison card shown on the Monte Carlo, Drawdown Planning and Legacy
Planning tabs. The numbers come from source.reporting.monte_carlo.
real_estate_sale; this module only lays them out.
"""

from __future__ import annotations

import html

from source.webapp.render_helpers.formatting import _money

# How a row's Keep -> Sell difference is coloured: "higher" = a bigger Sell
# number is better (balances, success rate), "lower" = a smaller one is
# better (taxes), None = just show the difference without judging it.
HIGHER, LOWER = "higher", "lower"


def _delta_cell(delta, better, kind: str) -> str:
    if delta is None:
        return '<td class="num muted">--</td>'
    if abs(delta) < (0.0005 if kind == "pct" else 0.5):
        return '<td class="num muted">no change</td>'
    text = f"{delta * 100:+.1f} pts" if kind == "pct" else f"{'+' if delta > 0 else '-'}{_money(abs(delta))}"
    good = (delta > 0) == (better == HIGHER)
    cls = "" if better is None else (' style="color:#1b7f3b;"' if good else ' style="color:#b3261e;"')
    return f'<td class="num"{cls}>{text}</td>'


def comparison_rows_html(rows: list[dict]) -> str:
    """Each row: {"label", "keep", "sell", "kind": "money" | "pct" | "text",
    "better": HIGHER | LOWER | None}. For money/pct, keep/sell are numbers
    (or None for "--"); for text they are already-formatted strings."""
    out = []
    for r in rows:
        kind = r.get("kind", "money")
        keep, sell = r.get("keep"), r.get("sell")
        if kind == "text":
            cells = f'<td class="num">{html.escape(str(keep))}</td><td class="num">{html.escape(str(sell))}</td><td></td>'
        else:
            def fmt(v):
                if v is None:
                    return "--"
                return f"{v * 100:.0f}%" if kind == "pct" else _money(v)
            delta = None if keep is None or sell is None else sell - keep
            cells = (
                f'<td class="num">{fmt(keep)}</td><td class="num">{fmt(sell)}</td>'
                + _delta_cell(delta, r.get("better"), kind)
            )
        weight = ' style="font-weight:600;"' if r.get("strong") else ""
        out.append(f'<tr{weight}><td>{html.escape(r["label"])}</td>{cells}</tr>')
    return "".join(out)


def sale_comparison_card_html(*, sale: dict, rows: list[dict], intro: str, extra_note: str = "") -> str:
    """The card itself. Empty string when there is nothing to sell."""
    if not sale.get("has_properties") or sale.get("gross_value", 0) <= 0:
        return ""
    s = sale["settings"]
    when = "this year" if s["sale_year"] <= s["current_year"] else f"in {s['sale_year']}"
    summary = (
        f"Selling everything {when}: {_money(sale['gross_value'])} sale value, less {_money(sale['loan_payoff'])} loan "
        f"payoff, {_money(sale['selling_costs'])} selling costs and about {_money(sale['gains_tax'])} estimated tax on the "
        f"gain leaves <strong>{_money(sale['net_proceeds'])}</strong> to invest in your Taxable pool"
        + (f", and {_money(sale['rent_lost'])}/yr of rental income stops" if sale["rent_lost"] > 0.5 else "")
        + "."
    )
    return f"""
<div class="card" style="border: 2px solid #1b7f3b;">
<h2 style="margin-top:0">If you sold your real estate</h2>
<p class="muted">{intro} {summary} Change the year, selling cost and appreciation on the
<a href="/real-estate.html">Real Estate</a> tab.</p>
<div style="overflow-x:auto">
<table>
<thead><tr><th></th><th class="num">Keep</th><th class="num">Sell</th><th class="num">Sell vs. Keep</th></tr></thead>
<tbody>{comparison_rows_html(rows)}</tbody>
</table>
</div>
{extra_note}
</div>
"""


def sale_settings_card_html(sale: dict, assumptions: dict) -> str:
    """The Real Estate tab's what-if form plus the per-property proceeds
    breakdown."""
    s = sale["settings"]

    def pct(key, fallback):
        raw = assumptions.get(key)
        try:
            return f"{float(raw) * 100:.2f}" if raw not in (None, "") else fallback
        except (TypeError, ValueError):
            return fallback

    sale_year_value = html.escape(str(assumptions.get("re_sale_year") or ""))
    cost_value = pct("re_selling_cost", f"{s['selling_cost'] * 100:.2f}")
    appreciation_value = pct("re_appreciation", "")
    rows = "".join(
        f'<tr><td>{html.escape(p["name"])}</td><td class="num">{_money(p["gross_value"])}</td>'
        f'<td class="num">{_money(p["loan_payoff"])}</td><td class="num">{_money(p["selling_costs"])}</td>'
        f'<td class="num">{_money(p["gain"])}</td><td class="num">{_money(p["gains_tax"])}</td>'
        f'<td class="num">{_money(p["net_proceeds"])}</td></tr>'
        for p in sale["properties"]
    ) or '<tr><td colspan="7" class="muted">No properties yet.</td></tr>'
    missing = (
        '<p class="muted">No purchase price for ' + html.escape(", ".join(sale["missing_purchase_price"]))
        + " -- no tax on the gain is estimated for it. Fill in Purchase Price above for a better estimate.</p>"
        if sale["missing_purchase_price"] else ""
    )
    return f"""
<div class="card">
<h2 style="margin-top:0">What if I sold? (liquidation scenario)</h2>
<p class="muted">Selling every property in one year turns each into cash in your Taxable pool and stops its rental income.
The Monte Carlo, Drawdown Planning and Legacy Planning tabs each show Keep vs. Sell side by side using the numbers below.
Estimates only: gain = sale price minus selling costs minus purchase price (no improvements, no depreciation recapture, no
primary-residence exclusion), federal long-term gains + California + 3.8% net investment income tax. The loan pays down in a
straight line to its "Loan ends" year (flat if blank).</p>
<form class="inline" onsubmit="event.preventDefault();
  var fields = {{}};
  new FormData(this).forEach(function(value, key) {{ fields[key] = value; }});
  postJSON('/api/assumptions', fields).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Sale year<input name="re_sale_year" type="number" step="1" min="1900" placeholder="{s['current_year']}" value="{sale_year_value}"></label>
  <label>Selling costs %<input name="re_selling_cost_pct" type="number" step="0.1" min="0" max="50" value="{cost_value}"></label>
  <label>Appreciation % / yr<input name="re_appreciation_pct" type="number" step="0.1" placeholder="{s['appreciation'] * 100:.1f} (inflation)" value="{appreciation_value}"></label>
  <button type="submit" class="primary">Save &amp; re-run</button>
</form>
<div style="overflow-x:auto">
<table>
<thead><tr><th>Property</th><th class="num">Sale value (owned share)</th><th class="num">Loan payoff</th><th class="num">Selling costs</th>
<th class="num">Taxable gain</th><th class="num">Est. tax on gain</th><th class="num">Net proceeds</th></tr></thead>
<tbody>{rows}</tbody>
<tfoot><tr><td>Total</td><td class="num">{_money(sale['gross_value'])}</td><td class="num">{_money(sale['loan_payoff'])}</td>
<td class="num">{_money(sale['selling_costs'])}</td><td class="num">{_money(sale['gain'])}</td>
<td class="num">{_money(sale['gains_tax'])}</td><td class="num">{_money(sale['net_proceeds'])}</td></tr></tfoot>
</table>
</div>
{missing}
</div>
"""
