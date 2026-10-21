"""The Summary page's building blocks, in the order a first-time reader
asks their questions: am I OK, what do I own and owe, will it last, where
does the money come from, what should I do next, can I trust it."""

from __future__ import annotations

import html
import json
from datetime import date

from source.common import db
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
        '<div class="seg-group" role="group" aria-label="Dollar basis" title="Today\'s dollars show what the money would buy now. Future dollars show the larger numbers you would see after inflation.">'
        + btn("today", today_label) + btn("future", future_label) + "</div>"
    )


_GAUGE_R = 54


def gauge_html(rate: float, tone: str) -> str:
    """A ring that fills to the chance your money lasts -- the number you read
    first, the way a car shows its range. `tone` is ok / warn / bad."""
    circumference = 2 * 3.14159265 * _GAUGE_R
    frac = min(1.0, max(0.0, float(rate)))
    offset = circumference * (1 - frac)
    return (
        f'<div class="gauge tone-{tone}" role="img" aria-label="{html.escape(pres.LABEL_CHANCE)}: {pres.percent_display(rate)}">'
        f'<svg viewBox="0 0 132 132" aria-hidden="true"><circle class="g-track" cx="66" cy="66" r="{_GAUGE_R}"/>'
        f'<circle class="g-ring" cx="66" cy="66" r="{_GAUGE_R}" stroke-dasharray="{circumference:.1f}" '
        f'stroke-dashoffset="{offset:.1f}" style="--full:{circumference:.1f}"/></svg>'
        f'<div class="g-num"><strong>{pres.percent_display(rate)}</strong><span>chance your money lasts</span></div></div>'
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


def hero_html(s: dict, result: dict, retirement_text: str, mode: str, schedule: dict | None = None, change_text: str = "") -> str:
    assumptions = s["assumptions"]
    status = pres.plan_status(result["success_rate"])
    titles = {
        "on_track": "Your plan is on track",
        "review": "Your plan is worth a second look",
        "at_risk": "Your plan needs attention",
    }
    verdict = pres.verdict_sentence(result, assumptions, s["next_year_expense_need"], _money)
    watch = ""
    if schedule and schedule.get("rows"):
        infl = pres.inflation_rate(assumptions)
        base = s["this_year"]
        convert = (lambda v, y: pres.to_today(v, infl, y - base)) if mode == "today" else None
        retire = schedule.get("retirement_year")
        rows = [r for r in schedule["rows"] if retire is None or r["year"] >= retire]
        sentence = pres.watch_sentence(rows, _money, convert)
        if sentence:
            watch = f'<p class="hero-watch small" style="margin:6px 0 0"><strong>{html.escape(sentence)}</strong></p>'
    change_line = f'<p class="hero-change small" style="margin:6px 0 0">{html.escape(change_text)}</p>' if change_text else ""
    tiles = "".join((
        _tile("Net worth", _money(s["net_worth"]), hero=True),
        _tile("Investable savings", _money(s["net_liquid_asset"]), hero=True),
        _tile(f"Yearly spending in {s['next_year']}", _money(s["next_year_expense_need"]), hero=True),
    ))
    re_in_plan = float((s.get("retirement_pools") or {}).get("real_estate") or 0.0)
    in_plan_line = (
        f'<p class="small" style="margin:8px 0 0">Plus <strong>{_money(re_in_plan)}</strong> of home equity you marked '
        f'&ldquo;In the plan?&rdquo; on <a href="/real-estate.html">Real Estate</a>. Investable savings above are your accounts only; '
        f'the simulation below can also draw on that equity, last and with no tax modelled.</p>'
    ) if re_in_plan > 0 else ""
    return f"""
<div class="card hero tone-{status['tone']}">
<div class="hero-top"><span class="badge badge-{status['tone']}">&#9679; {html.escape(status['label'])}</span>
<span class="muted small">Plan check &middot; {date.today().strftime('%b %d, %Y').replace(' 0', ' ')}</span></div>
<div class="hero-main">
{gauge_html(result["success_rate"], status["tone"])}
<div class="hero-text">
<h2 class="hero-title">{titles[status['key']]}</h2>
<p class="hero-verdict">{html.escape(verdict)}</p>
{change_line}
{watch}
</div>
</div>
<div class="tiles">{tiles}</div>
{in_plan_line}
<p class="hero-note">{html.escape(retirement_text)}. We tried {int(result['iterations']):,} possible market futures, assuming
{_pct(assumptions, 'expected_return', 0.06)}% yearly growth and {_pct(assumptions, 'inflation_rate', 0.03)}% price rises. Amounts are in {"today&#x27;s dollars (what the money buys now)" if mode == "today" else "future dollars (grown by inflation)"}.
<a href="/monte-carlo.html#assumptions">Change assumptions</a></p>
</div>
"""


def own_owe_html(s: dict) -> str:
    """A plain balance sheet: everything you own at full value (property at
    market value, not just equity), everything you owe (mortgages and other
    debts), and net worth as the difference. The lines add up to the Net
    worth tile at the top of the page."""
    re_value = s["real_estate_value_total"]
    mortgages = max(re_value - s["real_estate_equity_total"], 0.0)
    other_debts = s["liability_total"]
    all_assets = s["manual_asset_total"] + s["linked_asset_total"]
    investments = max(s["retirement_liquid_total"], 0.0)
    other_assets = all_assets - investments
    own_lines = [("Investments & savings", investments), ("Real estate (market value)", re_value), ("Other assets", other_assets)]
    own_total = sum(v for _, v in own_lines)
    owe_lines = [("Mortgages & property loans", mortgages), ("Other debts (cards, loans)", other_debts)]
    owe_total = sum(v for _, v in owe_lines)
    positive = [(n, v) for n, v in own_lines if v > 0.5]
    denom = sum(v for _, v in positive) or 1.0
    colors = {"Investments & savings": _SEG_COLORS[0], "Real estate (market value)": _SEG_COLORS[1], "Other assets": _SEG_COLORS[2]}
    bar = "".join(
        f'<span class="segbar-part" style="width:{v / denom * 100:.2f}%; background:{colors[n]}" '
        f'title="{html.escape(n)}: {_money(v)}"></span>'
        for n, v in positive
    )

    def rows(lines, *, with_dots: bool, note: dict | None = None) -> str:
        out = []
        for n, v in lines:
            dot = f'<span class="dot" style="background:{colors[n]}"></span>' if with_dots and n in colors else ""
            extra = f'<div class="muted small ledger-note">{note[n]}</div>' if note and n in note and v > 0.5 else ""
            out.append(f'<li><div class="ledger-row">{dot}<span>{html.escape(n)}</span><span class="grow"></span><strong>{_money(v)}</strong></div>{extra}</li>')
        return "".join(out)

    re_note = {"Real estate (market value)": f"Your equity after the mortgage is {_money(s['real_estate_equity_total'])}."}
    net = own_total - owe_total
    return f"""
<div class="card">
<h2 style="margin-top:0">What you own and owe</h2>
<div class="segbar">{bar}</div>
<div class="ledger">
  <div>
    <h3 class="sub" style="margin-top:6px">You own</h3>
    <ul class="ledger-list">{rows(own_lines, with_dots=True, note=re_note)}
      <li class="ledger-total"><div class="ledger-row"><span>Total you own</span><span class="grow"></span><strong>{_money(own_total)}</strong></div></li>
    </ul>
  </div>
  <div>
    <h3 class="sub" style="margin-top:6px">You owe</h3>
    <ul class="ledger-list">{rows(owe_lines, with_dots=False)}
      <li class="ledger-total"><div class="ledger-row"><span>Total you owe</span><span class="grow"></span><strong>{_money(owe_total)}</strong></div></li>
    </ul>
  </div>
</div>
<div class="ledger-net"><span>Net worth = what you own &minus; what you owe</span><span class="grow"></span><strong>{_money(net)}</strong></div>
<p class="muted small" style="margin-bottom:0">Property is shown at full market value here and its mortgage on the owe side; your plan uses the equity. Details are on the <a href="/asset.html">Asset</a> tab.</p>
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
    # marked "In the plan?"), so say what it actually starts from.
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


_SRC_JS = r"""
(function () {
  var el = document.getElementById('src-data');
  if (!el) return;
  var D = JSON.parse(el.textContent);
  var svg = document.getElementById('src-svg'), panel = document.getElementById('src-detail'), hl = document.getElementById('src-hl');
  var pinned = null, focus = null;
  function money(v) { return '$' + Math.round(v).toLocaleString('en-US'); }
  function short(v) { return v >= 1e6 ? '$' + (v / 1e6).toFixed(1) + 'M' : '$' + Math.round(v / 1e3) + 'K'; }
  function dot(k) { return '<span class="dot" style="background:' + D.colors[k] + '"></span>'; }
  function showYear(i) {
    var r = D.rows[i], parts = [], total = 0;
    D.names.forEach(function (n, k) {
      if (r.v[k] > 0.5) {
        total += r.v[k];
        parts.push('<span class="src-chip' + (focus === k ? ' on' : '') + '">' + dot(k) + n + ': <strong>' + money(r.v[k]) + '</strong></span>');
      }
    });
    panel.innerHTML = '<strong>' + r.year + (r.age != null ? ' &middot; age ' + r.age : '') + '</strong> &mdash; ' + parts.join(' ') +
      ' <span class="src-chip">Spending + taxes: <strong>' + money(r.spend) + '</strong></span>';
  }
  function showDefault() {
    if (focus === null) {
      panel.innerHTML = '<span class="muted">Hover or tap a year to see exactly where that year\'s money comes from. Click a source in the key to focus on it.</span>';
      return;
    }
    var yrs = 0, tot = 0, peak = 0, peakYear = null, first = null;
    D.rows.forEach(function (r) {
      var v = r.v[focus];
      if (v > 0.5) { yrs++; tot += v; if (first === null) first = r.year; if (v > peak) { peak = v; peakYear = r.year; } }
    });
    panel.innerHTML = dot(focus) + '<strong>' + D.names[focus] + '</strong>: used in ' + yrs + ' of ' + D.rows.length + ' years' +
      (first !== null ? ', starting ' + first : '') + '; total <strong>' + money(tot) + '</strong>; biggest year <strong>' + money(peak) + '</strong> (' + peakYear + '). Hover a year for the exact amount.';
  }
  function place(i) {
    hl.setAttribute('x', D.x0 + i * D.slot); hl.setAttribute('width', D.slot); hl.style.display = '';
  }
  function clearLabels() {
    Array.prototype.slice.call(svg.querySelectorAll('.vlabel')).forEach(function (t) { t.parentNode.removeChild(t); });
  }
  function applyFocus() {
    clearLabels();
    svg.classList.toggle('focusing', focus !== null);
    Array.prototype.forEach.call(svg.querySelectorAll('rect.seg'), function (r) {
      r.classList.toggle('on', focus !== null && +r.getAttribute('data-s') === focus);
    });
    Array.prototype.forEach.call(document.querySelectorAll('.legend-btn'), function (li) {
      li.classList.toggle('on', focus !== null && +li.getAttribute('data-s') === focus);
    });
    if (focus !== null) {
      Array.prototype.forEach.call(svg.querySelectorAll('rect.seg.on'), function (r) {
        var h = parseFloat(r.getAttribute('height'));
        if (h < 26) return;
        var i = +r.getAttribute('data-i'), cx = parseFloat(r.getAttribute('x')) + parseFloat(r.getAttribute('width')) / 2;
        var cy = parseFloat(r.getAttribute('y')) + h / 2;
        var t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        t.setAttribute('class', 'vlabel'); t.setAttribute('x', cx); t.setAttribute('y', cy);
        t.setAttribute('text-anchor', 'middle'); t.setAttribute('dominant-baseline', 'middle');
        t.setAttribute('transform', 'rotate(-90 ' + cx + ' ' + cy + ')');
        t.setAttribute('font-size', '9'); t.setAttribute('fill', '#fff'); t.style.pointerEvents = 'none';
        t.textContent = short(D.rows[i].v[focus]);
        svg.insertBefore(t, svg.querySelector('.yr-hit'));
      });
    }
    if (pinned !== null) showYear(pinned); else showDefault();
  }
  Array.prototype.forEach.call(svg.querySelectorAll('.yr-hit'), function (h) {
    var i = +h.getAttribute('data-i');
    h.addEventListener('mouseenter', function () { if (pinned === null) { showYear(i); place(i); } });
    h.addEventListener('mouseleave', function () { if (pinned === null) { hl.style.display = 'none'; showDefault(); } });
    h.addEventListener('click', function () {
      pinned = pinned === i ? null : i;
      if (pinned === null) { hl.style.display = 'none'; showDefault(); } else { showYear(i); place(i); }
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll('.legend-btn'), function (li) {
    function toggle() { var k = +li.getAttribute('data-s'); focus = focus === k ? null : k; applyFocus(); }
    li.addEventListener('click', toggle);
    li.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
  });
  showDefault();
})();
"""


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
    bars, labels, pts, hits, data_rows = [], [], [], [], []
    stride = max(1, n // 8)
    # Only series that are ever non-zero get a legend entry / table column;
    # index them so the page script can refer to a series by number.
    used_series = [(name, f, color) for name, f, color in series if any(conv(f(r), r["year"]) > 0.5 for r in rows)]
    index_of = {name: k for k, (name, _f, _c) in enumerate(used_series)}
    for i, r in enumerate(rows):
        x = ml + slot * i + (slot - bar_w) / 2
        y_cursor = mt + ph
        year_vals = [0.0] * len(used_series)
        for name, f, color in series:
            v = conv(f(r), r["year"])
            if v <= 0.5:
                continue
            h = v / top * ph
            y_cursor -= h
            year_vals[index_of[name]] = v
            bars.append(
                f'<rect class="seg" data-s="{index_of[name]}" data-i="{i}" x="{x:.1f}" y="{y_cursor:.1f}" width="{bar_w:.1f}" '
                f'height="{h:.1f}" fill="{color}"><title>{html.escape(name)} {r["year"]}: {short(v)}</title></rect>'
            )
        data_rows.append({"year": r["year"], "age": r.get("age"), "v": year_vals, "spend": spend[i]})
        hits.append(
            f'<rect class="yr-hit" data-i="{i}" x="{ml + slot * i:.1f}" y="{mt}" width="{slot:.1f}" height="{ph}" '
            f'fill="transparent"><title>{r["year"]}</title></rect>'
        )
        pts.append(f"{x + bar_w / 2:.1f},{y_for(spend[i]):.1f}")
        if i % stride == 0 or (i == n - 1 and (n - 1) % stride >= max(2, stride // 2)):
            age = f"<tspan x=\"{x + bar_w / 2:.1f}\" dy=\"11\" font-size=\"9\">age {r['age']}</tspan>" if r.get("age") is not None else ""
            labels.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{height - 18}" text-anchor="middle" font-size="11" '
                f'style="fill:var(--ink-muted,#777);">{r["year"]}{age}</text>'
            )
    line = f'<polyline points="{" ".join(pts)}" fill="none" stroke="var(--ink,#111)" stroke-width="1.8" stroke-dasharray="4 3"/>'
    svg = (
        f'<svg id="src-svg" width="100%" style="max-width:{width}px; height:auto;" viewBox="0 0 {width} {height}" font-family="-apple-system, sans-serif">'
        + grid + '<rect id="src-hl" style="display:none; fill:var(--ink,#111);" fill-opacity="0.07" y="' + str(mt) + '" height="' + str(ph) + '"/>'
        + "".join(bars) + line + "".join(labels) + "".join(hits) + "</svg>"
    )
    legend = "".join(
        f'<li class="legend-btn" role="button" tabindex="0" data-s="{k}" title="Click to focus on this source">'
        f'<span class="dot" style="background:{c}"></span>{html.escape(n)}</li>'
        for k, (n, _f, c) in enumerate(used_series)
    ) + '<li><span class="dash"></span>Spending + taxes</li>'
    import json as _json

    payload = _json.dumps({
        "names": [n for n, _f, _c in used_series], "colors": [c for _n, _f, c in used_series],
        "rows": data_rows, "x0": ml, "slot": slot, "mt": mt, "ph": ph,
    }).replace("</", "<\\/")
    table_head = "".join(f"<th class=\"num\">{html.escape(n)}</th>" for n, _f, _c in used_series)
    table_rows = "".join(
        f"<tr><td>{d['year']}</td><td>{d['age'] if d['age'] is not None else '--'}</td>"
        + "".join(f'<td class="num">{_money(v) if v > 0.5 else "--"}</td>' for v in d["v"])
        + f'<td class="num">{_money(d["spend"])}</td></tr>'
        for d in data_rows
    )
    table_html = (
        '<details class="how-it-works" style="margin-top:8px"><summary>Show the numbers as a table</summary>'
        '<div style="overflow-x:auto"><table class="whatif-table"><thead><tr><th>Year</th><th>Age</th>'
        f'{table_head}<th class="num">Spending + taxes</th></tr></thead><tbody>{table_rows}</tbody></table></div></details>'
    )
    return f"""
<div class="card">
<h2 style="margin-top:0">Where your retirement spending comes from</h2>
<p class="muted small">Each bar is one year, in {html.escape("today's" if mode == "today" else "future")} dollars. Colors show whether it is paid from income or from which savings; the dashed line is that year&#x27;s spending plus taxes. Hover or tap a year for the exact amounts; click a source in the key to focus on it. Required withdrawals beyond spending are reinvested and not shown. Detail is on the <a href="/drawdown-planning.html">Drawdown</a> tab.</p>
{svg}
<ul class="legend-inline">{legend}</ul>
<div id="src-detail" class="src-detail small"></div>
{table_html}
<script type="application/json" id="src-data">{payload}</script>
<script>{_SRC_JS}</script>
</div>
"""


def safe_spending_html(selector: bool = False) -> str:
    """"How much can I safely spend?" -- filled in by loadSafeSpending() in
    the page shell JS (it calls /api/safe-spending, a few seconds the first
    time). With `selector`, the reader can pick the confidence level; the
    pick is remembered, so the Summary shows the same level."""
    target = db.safe_spend_target()

    def opt(value: float) -> str:
        on = " selected" if abs(value - target) < 1e-9 else ""
        return f'<option value="{value:g}"{on}>{value * 100:.0f}%</option>'

    choices = [0.8, 0.9, 0.95]
    if all(abs(c - target) > 1e-9 for c in choices):
        choices = sorted(choices + [target])
    sel = (
        '<label class="small muted" style="display:inline-flex; gap:6px; align-items:center; margin-bottom:6px;">Keep my chance of lasting at '
        '<select id="ss-target" onchange="loadSafeSpending(parseFloat(this.value), true)">'
        + "".join(opt(c) for c in choices) + '</select></label>'
        if selector else ""
    )
    return f"""{sel}
<p id="ss-text" data-target="{target:g}" style="margin:2px 0 0">Calculating...</p>"""


def standing_card_html(s: dict, snapshots: list, history: dict, plan_rate: float) -> str:
    """Three plain "where you stand" boxes: progress toward financial
    independence, the most you could safely spend, and what changed since
    about a month ago."""
    from source.reporting import progress

    fi = progress.independence_progress(s)
    if fi:
        shown = min(fi["pct"], 100.0)
        if fi["reached"]:
            line = "You have reached this number."
        elif fi["year"]:
            line = f"At your assumed growth and adding nothing new, about <strong>{fi['year']}</strong>."
        else:
            line = "Add to savings or raise growth to see a date."
        if fi["need"] <= 0:
            what = (f"Your income of {_money(fi['income'])} a year already covers your spending of "
                    f"{_money(fi['spending'])}, so your savings are not needed to pay the bills.")
        else:
            what = (f"Savings of {_money(fi['savings'])} toward about {_money(fi['target'])}: 25 times the "
                    f"{_money(fi['need'])} a year your income does not cover "
                    f"(spending {_money(fi['spending'])}, income {_money(fi['income'])}).")
        cushion = ""
        if fi.get("in_plan_equity", 0) > 0:
            cushion += (f'<p class="small" style="margin:6px 0 0">Includes <strong>{_money(fi["in_plan_equity"])}</strong> of home equity '
                        f'you marked &ldquo;In the plan?&rdquo; on Real Estate.</p>')
        if fi["equity"] > 0:
            cushion += (f'<p class="small" style="margin:6px 0 0">Not counted above: <strong>{_money(fi["equity"])}</strong> of home equity '
                       f'&mdash; an extra cushion you could tap by selling or borrowing. Its rent is already in your income.</p>')
        fi_box = f"""<div class="box"><h3>Financial independence</h3>
<div class="big">{fi['pct']:.0f}%</div>
<div class="fi-bar" role="img" aria-label="{shown:.0f}% of the way"><i style="width:{shown:.1f}%"></i></div>
<p class="small muted" style="margin:0">{what} {line}</p>{cushion}</div>"""
    else:
        fi_box = ""
    ss_box = f"""<div class="box"><h3>How much can I safely spend?</h3>
{safe_spending_html()}
<p class="small muted" style="margin:6px 0 0">Based on your simulation. <a href="/monte-carlo.html#safe-spending">Change the confidence level</a>.</p></div>"""
    change = progress.since_then(snapshots, s, history, asset_rows=db.list_asset_balance_snapshots())
    if change:
        d = change["net_change"]
        word = "up" if d >= 0 else "down"
        since = change["since"].strftime("%b %d").replace(" 0", " ")
        items = "".join(
            f'<li>{html.escape(name)}: {"+" if v >= 0 else "&minus;"}{_money(abs(v))}</li>' for name, v in change["parts"]
        )
        why_line = ""
        if change.get("movers"):
            moves = "; ".join(
                f'{html.escape(m["name"])} {"up" if m["change"] >= 0 else "down"} {_money(abs(m["change"]))}'
                for m in change["movers"])
            why_line = f'<p class="small" style="margin:6px 0 0"><strong>Biggest moves:</strong> {moves}.</p>'
        rate_line = ""
        rate_then = change["rate_then"]
        if rate_then is not None:
            rate_line = (
                f'<p class="small" style="margin:6px 0 0">Chance your money lasts: {pres.percent_display(rate_then)} &rarr; '
                f'<strong>{pres.percent_display(plan_rate)}</strong></p>'
            )
        change_box = f"""<div class="box"><h3>Since {since}</h3>
<div class="big">{"+" if d >= 0 else "&minus;"}{_money(abs(d))}</div>
<p class="small muted" style="margin:0">Net worth is {word} {_money(abs(d))}.</p>
<ul>{items}</ul>{why_line}{rate_line}</div>"""
    else:
        change_box = """<div class="box"><h3>Since last month</h3>
<p class="small muted" style="margin:0">Your history builds up automatically, one point a day. Check back in a couple of days to see what changed.</p></div>"""
    return f"""
<div class="card">
<h2 style="margin-top:0">Where you stand</h2>
<div class="standing">{fi_box}{ss_box}{change_box}</div>
</div>
"""


def alerts_card_html(alerts: list[dict]) -> str:
    """Open alerts (see source.reporting.alerts) with a Dismiss button each.
    Renders nothing when there are none, so a quiet plan stays quiet."""
    if not alerts:
        return ""
    rows = ""
    for a in alerts:
        aid = html.escape(json.dumps(a["id"]), quote=True)
        rows += (
            f'<li class="{"status-warn" if a["level"] == "warn" else "muted"}"><strong>{html.escape(a["title"])}</strong>'
            f'<div class="small muted" style="margin-top:2px">{html.escape(a["detail"])} '
            f'<a href="{html.escape(a["href"])}">Open</a> '
            f'<button type="button" class="chip" onclick="postJSON(\'/api/alerts-dismiss\', {{id: {aid}}})'
            f'.then(function() {{ location.reload(); }});">Dismiss</button></div></li>'
        )
    return f"""
<div class="card" id="alerts">
<h3 class="sub" style="margin-top:0">Alerts ({len(alerts)})</h3>
<ul style="margin:6px 0 0 18px; padding:0; font-size:13px;">{rows}</ul>
</div>"""


_TOP_STEPS = 3


def next_steps_html(actions: list[dict]) -> str:
    """The Summary's "What should I do next?" card: a short numbered list,
    most important first (see source.reporting.advice). Nothing is changed
    from here; each step opens the tab where it can be dealt with."""
    if actions:
        def item(a: dict) -> str:
            why = f'<div class="small muted" style="margin-top:2px">{html.escape(a["why"])}</div>' if a.get("why") else ""
            return (
                f'<li class="ns-item"><span class="ns-num {"ns-warn" if a["level"] == "warn" else ""}">{a["rank"]}</span>'
                f'<div><strong>{html.escape(a["title"])}</strong> '
                f'<a href="{html.escape(a["href"])}">Open</a>{why}</div></li>'
            )

        rows = "".join(item(a) for a in actions[:_TOP_STEPS])
        more = ""
        if len(actions) > _TOP_STEPS:
            more = (
                f'<details class="ns-more"><summary>Show {len(actions) - _TOP_STEPS} more</summary>'
                f'<ol class="ns-list" start="{_TOP_STEPS + 1}">{"".join(item(a) for a in actions[_TOP_STEPS:])}</ol></details>'
            )
        body = (
            '<style>.ns-list{list-style:none;margin:8px 0 0;padding:0}.ns-item{display:flex;gap:10px;align-items:flex-start;'
            'padding:8px 0;border-top:1px solid var(--line,#e5e7eb);font-size:14px}.ns-item:first-child{border-top:0}'
            '.ns-num{flex:0 0 24px;height:24px;border-radius:50%;background:#e5e7eb;color:#374151;font-weight:700;'
            'font-size:12px;display:flex;align-items:center;justify-content:center}.ns-num.ns-warn{background:#fde68a;color:#7c2d12}'
            '.ns-more{margin-top:6px;font-size:13px}.ns-more summary{cursor:pointer;color:var(--brand)}</style>'
            f'<ol class="ns-list">{rows}</ol>{more}'
        )
    else:
        body = '<p class="status-line status-ok">&#10003; Nothing needs your attention right now. Nice work.</p>'
    return f"""
<div class="card" id="next-steps">
<h2 style="margin-top:0">What should I do next?</h2>
<p class="muted small" style="margin:0">The most important ones first.</p>
{body}
<p class="muted small" style="margin:10px 0 0">Want to test a change before committing to it? Try a what-if next to your
<a href="/monte-carlo.html#assumptions">Assumptions</a>.</p>
</div>
"""


def whatif_quick_html(assumptions: dict, can_vary_retirement: bool, ss_ready: bool) -> str:
    """The Summary's "What if...?" card: one-tap questions with the answer
    shown right under the chips. Nothing is saved."""
    growth = float(assumptions.get("expected_return") or 0.06) * 100.0
    retire_attr = "" if can_vary_retirement else " disabled"
    claim = (
        '<button type="button" class="chip" onclick="wiClaim(this, 70)">Claim Social Security at 70</button>'
        if ss_ready else ""
    )
    retire_slider = (
        f'<label>Retirement <strong id="wq-retire-val">as planned</strong>'
        f'<input type="range" id="wq-retire" min="-5" max="10" step="1" value="0" oninput="wiLive()" aria-label="Retire earlier or later"{retire_attr}></label>'
    )
    return f"""
<div class="card" id="whatif-quick" data-growth="{growth:g}">
<h2 style="margin-top:0">What if&hellip;?</h2>
<p class="muted small" style="margin:0 0 4px">Drag a slider or tap an idea. The answer updates as you go. Nothing is saved.</p>
<div class="wq-sliders">
<label>Spending <strong id="wq-spend-val">as planned</strong>
<input type="range" id="wq-spend" min="-30" max="30" step="5" value="0" oninput="wiLive()" aria-label="Spend less or more"></label>
{retire_slider}
</div>
<p style="margin:6px 0 0">
  <button type="button" class="chip" onclick="wiQuick(this, -10, 0)">I spend 10% less</button>
  <button type="button" class="chip" onclick="wiQuick(this, 10, 0)">I spend 10% more</button>
  <button type="button" class="chip" onclick="wiQuick(this, 0, 2)"{retire_attr}>I retire 2 years later</button>
  {claim}
</p>
<div id="whatif-quick-result" class="small" style="margin-top:10px" aria-live="polite"><span class="muted">Move a slider to try a change.</span></div>
</div>
"""


def whatif_form_html(can_vary_retirement: bool, growth_pct: float = 6.0) -> str:
    """The interactive "Try a what-if" block (spending / retire later /
    growth, plus quick-try chips and a result area filled by runWhatIf in
    the page shell JS). Nothing is saved. Rendered inside the Monte Carlo
    tab's combined Assumptions & what-if panel."""
    retire_attr = "" if can_vary_retirement else " disabled"
    retire_hint = (
        "" if can_vary_retirement
        else '<span class="muted small">(set a retirement year below first to try this)</span>'
    )
    return f"""
<h3 class="sub" style="margin-top:0">Try a what-if <span class="badge-whatif">nothing is saved</span></h3>
<p class="muted small" style="margin-top:0">Change any of the boxes and press Compare. Your plan is re-simulated with your change and set next to the plan as it is today.</p>
<div class="whatif-form">
  <label>Spending change (%)<input id="wi-spend" type="number" step="1" min="-90" max="200" value="-10" title="Negative = spend less, positive = spend more"></label>
  <label>Retire later by (years)<input id="wi-retire" type="number" step="1" min="-20" max="30" value="0"{retire_attr} title="Negative = retire earlier"></label>
  <label>Average yearly growth (%)<input id="wi-growth" type="number" step="0.1" min="-5" max="20" value="{growth_pct:g}"></label>
  <button type="button" class="primary" id="whatif-btn" onclick="runWhatIf(this)">Compare</button>
</div>
<p class="small muted" style="margin:6px 0 0">Quick tries:
  <button type="button" class="chip" onclick="wiPreset(-10, 0)">Spend 10% less</button>
  <button type="button" class="chip" onclick="wiPreset(10, 0)">Spend 10% more</button>
  <button type="button" class="chip" onclick="wiPreset(0, 2)"{retire_attr}>Retire 2 years later</button>
  <button type="button" class="chip" onclick="wiPreset(-10, 2)"{retire_attr}>Both</button> {retire_hint}
</p>
<div id="whatif-result"></div>
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


def data_check_card_html(issues: list[dict]) -> str:
    """The Summary's "Data check": problems that quietly skew the numbers, each
    with what is wrong, what to do, and a one-click fix where one is safe."""
    if not issues:
        return """
<div class="card" id="data-check">
<h3 class="sub" style="margin-top:0">Data check</h3>
<p class="status-line status-ok" style="margin:0">&#10003; No data problems found. Your balances, tags and backups look healthy.</p>
</div>"""
    rows = ""
    for i in issues:
        fix = ""
        if i.get("fix"):
            f = i["fix"]
            payload = html.escape(json.dumps(f["payload"]), quote=True)
            fix = (f' <button type="button" class="chip" onclick="postJSON(\'{html.escape(f["url"])}\', {payload})'
                   f'.then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">{html.escape(f["label"])}</button>')
        rows += (
            f'<li class="{"status-warn" if i["level"] == "warn" else "muted"}"><strong>{html.escape(i["title"])}</strong>'
            f'<div class="small muted" style="margin-top:2px">{html.escape(i["detail"])} '
            f'<a href="{html.escape(i["href"])}">Open</a>{fix}</div></li>'
        )
    return f"""
<div class="card" id="data-check">
<h3 class="sub" style="margin-top:0">Data check ({len(issues)})</h3>
<ul class="dc-list" style="margin:6px 0 0 18px; padding:0; font-size:13px;">{rows}</ul>
</div>"""
