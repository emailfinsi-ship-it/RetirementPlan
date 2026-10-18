"""The Summary page's building blocks, in the order a first-time reader
asks their questions: am I OK, what do I own and owe, will it last, where
does the money come from, what should I do next, can I trust it."""

from __future__ import annotations

import html
from datetime import date

from source.reporting import presentation as pres
from source.reporting.monte_carlo import render_fan_svg
from source.webapp.render_helpers import _money, _pct

_SEG_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#7a5af8", "#8e8e93")


def dollars_toggle_html(mode: str) -> str:
    """Segmented "Today's dollars | Future dollars" control (saves the choice, reloads)."""
    def btn(value: str, label: str) -> str:
        on = " on" if mode == value else ""
        return (
            f'<button type="button" class="seg{on}" onclick="setDollarsMode(\'{value}\')">{html.escape(label)}</button>'
        )
    today_label = "Today's dollars"
    future_label = "Future dollars"
    return (
        '<div class="seg-group" role="group" aria-label="Dollar basis">'
        + btn("today", today_label) + btn("future", future_label) + "</div>"
    )


def _tile(label: str, value: str, *, hero: bool = False) -> str:
    cls = "tile hero-tile" if hero else "tile"
    return f'<div class="{cls}"><div class="label">{html.escape(label)}</div><div class="value">{value}</div></div>'


def welcome_card_html() -> str:
    return (
        '<div class="card hero"><h2 class="hero-title" style="margin-top:0">Welcome &mdash; let&#x27;s build your plan</h2>'
        '<p class="hero-verdict">Add your accounts, spending and dates and this page will tell you, in plain words, '
        'whether your money is on track to last.</p>'
        '<p><a href="/setup-wizard.html"><button type="button" class="primary">Start the setup wizard</button></a></p></div>'
    )


def hero_html(s: dict, result: dict, retirement_text: str, mode: str) -> str:
    assumptions = s["assumptions"]
    status = pres.plan_status(result["success_rate"])
    titles = {
        "on_track": "Your plan is on track",
        "review": "Your plan is worth a second look",
        "at_risk": "Your plan needs attention",
    }
    verdict = pres.verdict_sentence(result, assumptions, s["next_year_expense_need"], _money)
    tiles = "".join((
        _tile("Net worth", _money(s["net_worth"]), hero=True),
        _tile("Investable savings", _money(s["net_liquid_asset"]), hero=True),
        _tile(f"Yearly spending in {s['next_year']}", _money(s["next_year_expense_need"]), hero=True),
    ))
    return f"""
<div class="card hero tone-{status['tone']}">
<div class="hero-top"><span class="badge badge-{status['tone']}">&#9679; {html.escape(status['label'])}</span>
<span class="muted small">Plan check &middot; {date.today().strftime('%b %d, %Y').replace(' 0', ' ')}</span></div>
<h2 class="hero-title">{titles[status['key']]}</h2>
<p class="hero-verdict">{html.escape(verdict)}</p>
<div class="tiles">{tiles}</div>
<p class="muted small" style="margin-bottom:0">{html.escape(retirement_text)}. Based on {int(result['iterations']):,} simulated market paths,
{_pct(assumptions, 'expected_return', 0.06)}% average yearly growth and {_pct(assumptions, 'inflation_rate', 0.03)}% inflation.
<a href="/monte-carlo.html#assumptions">Change assumptions</a></p>
</div>
"""


def own_owe_html(s: dict) -> str:
    total_assets = max(s["total_asset"], 0.0)
    liquid = max(s["net_liquid_asset"], 0.0)
    home = max(s["real_estate_equity_total"], 0.0)
    other = max(total_assets - liquid - home, 0.0)
    parts = [("Investments & savings", liquid), ("Home & property equity", home), ("Other assets", other)]
    parts = [(n, v) for n, v in parts if v > 0.5]
    denom = sum(v for _, v in parts) or 1.0
    bar = "".join(
        f'<span class="segbar-part" style="width:{v / denom * 100:.2f}%; background:{_SEG_COLORS[i]}" '
        f'title="{html.escape(n)}: {_money(v)}"></span>'
        for i, (n, v) in enumerate(parts)
    )
    legend = "".join(
        f'<li><span class="dot" style="background:{_SEG_COLORS[i]}"></span>{html.escape(n)}'
        f'<span class="grow"></span><strong>{_money(v)}</strong> <span class="muted">({v / denom * 100:.0f}%)</span></li>'
        for i, (n, v) in enumerate(parts)
    )
    tiles = "".join((
        _tile("Everything you own", _money(s["total_asset"])),
        _tile("What you owe", _money(-s["liability_total"])),
        _tile("Home & property equity", _money(s["real_estate_equity_total"])),
    ))
    return f"""
<div class="card">
<h2 style="margin-top:0">What you own and owe</h2>
<div class="segbar">{bar}</div>
<ul class="legend-list">{legend}</ul>
<div class="tiles">{tiles}</div>
<p class="muted small" style="margin-bottom:0">Net worth = everything you own minus what you owe. Details are on the <a href="/asset.html">Asset</a> tab.</p>
</div>
"""


def projection_card_html(s: dict, display_result: dict, mode: str, retirement_year: int | None) -> str:
    assumptions = s["assumptions"]
    end_year, _age = pres.last_year_and_age(display_result, assumptions)
    try:
        birth = int(float(assumptions.get("birth_year")))
    except (TypeError, ValueError):
        birth = None
    chart = render_fan_svg(
        display_result, width=980, height=340, plain=True, responsive=True,
        retirement_year=retirement_year, birth_year=birth,
    )
    # The simulation walks down every opted-in pool (incl. property equity
    # marked "In Monte Carlo?"), so say what it actually starts from.
    start = sum(float(v or 0) for v in (s.get("retirement_pools") or {}).values())
    tiles = "".join((
        _tile("Starting balance", _money(start)),
        _tile(pres.LABEL_CHANCE, pres.percent_display(display_result["success_rate"])),
        _tile(pres.LABEL_CAUTIOUS, _money(display_result["p10_ending_balance"])),
        _tile(pres.LABEL_TYPICAL, _money(display_result["median_ending_balance"])),
        _tile(pres.LABEL_STRONG, _money(display_result["p90_ending_balance"])),
    ))
    return f"""
<div class="card">
<div class="card-head"><h2 style="margin:0">Will your money last?</h2>{dollars_toggle_html(mode)}</div>
<p class="muted small">Each line is one possible future for the markets. The shaded band holds the middle 8 in 10 outcomes; the solid line is the typical one. Figures are {html.escape(pres.dollars_caption(mode))}.</p>
{chart}
<div class="tiles tiles-five">{tiles}</div>
</div>
"""


def _trim_reinvested(r: dict) -> dict:
    """Copy of a drawdown row where withdrawals beyond the year's spending
    (required distributions that were reinvested) are taken off the
    401(k)/IRA draw first, then the others, so bars never exceed spending."""
    r = dict(r)
    income = r["income_social_security"] + r["income_rental"] + r["income_other"]
    target = max(0.0, r["expenses"] + r["tax"] - income)
    drawn_keys = ("drawn_tax_deferred", "drawn_taxable", "drawn_roth", "drawn_real_estate")
    surplus = sum(r[k] for k in drawn_keys) - target
    for k in drawn_keys:
        if surplus <= 1e-9:
            break
        cut = min(r[k], surplus)
        r[k] -= cut
        surplus -= cut
    return r


def income_sources_card_html(schedule: dict, assumptions: dict, mode: str, base_year: int) -> str:
    rows = schedule.get("rows") or []
    start = schedule.get("retirement_year")
    if start is not None:
        rows = [r for r in rows if r["year"] >= start]
    rows = [r for r in rows if r["expenses"] > 0 or r["drawn_taxable"] or r["drawn_tax_deferred"] or r["drawn_roth"]]
    if not rows:
        return ""
    infl = pres.inflation_rate(assumptions)
    rows = [_trim_reinvested(r) for r in rows]

    def conv(value: float, year: int) -> float:
        return pres.to_today(value, infl, year - base_year) if mode == "today" else value

    series = (
        ("Social Security & other income", lambda r: r["income_social_security"] + r["income_other"], _SEG_COLORS[2]),
        ("Rental income", lambda r: r["income_rental"], _SEG_COLORS[3]),
        ("Brokerage savings", lambda r: r["drawn_taxable"], _SEG_COLORS[0]),
        ("401(k)/IRA savings", lambda r: r["drawn_tax_deferred"], _SEG_COLORS[1]),
        ("Roth savings", lambda r: r["drawn_roth"], _SEG_COLORS[4]),
        ("Home equity", lambda r: r["drawn_real_estate"], _SEG_COLORS[5]),
    )
    width, height, ml, mr, mt, mb = 980, 300, 62, 12, 14, 30
    pw, ph = width - ml - mr, height - mt - mb
    totals = [sum(conv(f(r), r["year"]) for _, f, _ in series) for r in rows]
    spend = [conv(r["expenses"] + r["tax"], r["year"]) for r in rows]
    top = max(max(totals), max(spend), 1.0) * 1.05
    n = len(rows)
    slot = pw / n
    bar_w = max(2.0, slot * 0.72)

    def y_for(v):
        return mt + ph - v / top * ph

    def short(v):
        return f"${v / 1_000_000:.1f}M" if v >= 1_000_000 else f"${v / 1_000:.0f}K"

    grid = "".join(
        f'<line x1="{ml}" y1="{y_for(top * k / 4):.1f}" x2="{width - mr}" y2="{y_for(top * k / 4):.1f}" '
        f'style="stroke:var(--border,#e5e5e5);" stroke-width="1"/>'
        f'<text x="{ml - 8}" y="{y_for(top * k / 4) + 4:.1f}" text-anchor="end" font-size="11" '
        f'style="fill:var(--ink-muted,#777);">{short(top * k / 4)}</text>'
        for k in range(5)
    )
    bars, labels, pts = [], [], []
    stride = max(1, n // 8)
    for i, r in enumerate(rows):
        x = ml + slot * i + (slot - bar_w) / 2
        y_cursor = mt + ph
        tip_lines = [f"{r['year']}"]
        for name, f, color in series:
            v = conv(f(r), r["year"])
            if v <= 0.5:
                continue
            h = v / top * ph
            y_cursor -= h
            bars.append(f'<rect x="{x:.1f}" y="{y_cursor:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{color}"><title>{html.escape(name)} {r["year"]}: {short(v)}</title></rect>')
            tip_lines.append(f"{name}: {short(v)}")
        pts.append(f"{x + bar_w / 2:.1f},{y_for(spend[i]):.1f}")
        if i % stride == 0 or (i == n - 1 and (n - 1) % stride >= max(2, stride // 2)):
            age = f"<tspan x=\"{x + bar_w / 2:.1f}\" dy=\"11\" font-size=\"9\">age {r['age']}</tspan>" if r.get("age") is not None else ""
            labels.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{height - 18}" text-anchor="middle" font-size="11" '
                f'style="fill:var(--ink-muted,#777);">{r["year"]}{age}</text>'
            )
    line = f'<polyline points="{" ".join(pts)}" fill="none" stroke="var(--ink,#111)" stroke-width="1.8" stroke-dasharray="4 3"/>'
    svg = (
        f'<svg width="100%" style="max-width:{width}px; height:auto;" viewBox="0 0 {width} {height}" font-family="-apple-system, sans-serif">'
        + grid + "".join(bars) + line + "".join(labels) + "</svg>"
    )
    used = [(name, color) for name, f, color in series if any(conv(f(r), r["year"]) > 0.5 for r in rows)]
    legend = "".join(
        f'<li><span class="dot" style="background:{c}"></span>{html.escape(n)}</li>' for n, c in used
    ) + '<li><span class="dash"></span>Spending + taxes</li>'
    return f"""
<div class="card">
<h2 style="margin-top:0">Where your retirement spending comes from</h2>
<p class="muted small">Each bar is one year. Colors show whether it is paid from income or from which savings; the dashed line is that year&#x27;s spending plus taxes. In {html.escape("today's" if mode == "today" else "future")} dollars. Required withdrawals beyond spending are reinvested and not shown. Detail is on the <a href="/drawdown-planning.html">Drawdown</a> tab.</p>
{svg}
<ul class="legend-inline">{legend}</ul>
</div>
"""


def next_steps_html(items: list[dict], can_vary_retirement: bool) -> str:
    if items:
        rows = "".join(
            f'<li class="{"status-warn" if i["level"] == "warn" else "muted"}">{html.escape(i["text"])} '
            f'<a href="{html.escape(i["href"])}">Fix</a></li>'
            for i in items
        )
        checks = f'<ul style="margin:6px 0 0 18px; padding:0; font-size:13px;">{rows}</ul>'
        heading = f"Things to check ({len(items)})"
    else:
        checks = '<p class="status-line status-ok">Nothing missing &mdash; every input the plan relies on is filled in.</p>'
        heading = "Things to check"
    hint = "" if can_vary_retirement else " Set a retirement year to also try retiring later."
    return f"""
<div class="card">
<h2 style="margin-top:0">What should I do next?</h2>
<h3 class="sub">{heading}</h3>
{checks}
<h3 class="sub">Try a what-if</h3>
<p class="muted small" style="margin-top:0">See how a change would move the chance your money lasts.{hint}</p>
<div id="whatif-result"></div>
<button type="button" class="primary" id="whatif-btn" onclick="runWhatIf(this)">Run what-if check</button>
</div>
"""


def footer_html(s: dict, linked_summary: str, mode: str) -> str:
    a = s["assumptions"]
    horizon = int(float(a.get("plan_horizon_years") or 40))
    return f"""
<div class="trust-footer muted small">
<strong>How to read this:</strong> projections use {_pct(a, 'expected_return', 0.06)}% average yearly growth,
{_pct(a, 'inflation_rate', 0.03)}% inflation, a {horizon}-year horizon and {html.escape(str(a.get('iterations') or 1000))} simulated markets;
dollars shown are {"today&#x27;s" if mode == "today" else "future (inflated)"}. {linked_summary}
<br>Projections are estimates, not guarantees, and this is not financial advice.
</div>
"""
