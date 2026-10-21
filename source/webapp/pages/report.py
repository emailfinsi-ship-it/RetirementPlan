"""The printable plan report (/report.html): the Summary story laid out as a
clean, light-theme document. "Report Download" opens it and uses
the browser's own Save as PDF (window.print) -- no PDF library needed, so
it works on every machine the app already runs on."""

from __future__ import annotations

import html
import re
from datetime import date

from source.common import branding, db
from source.webapp.pages import summary_blocks as blocks
from source.webapp.pages.summary import build_plan_views
from source.webapp.render_helpers import _money, _pct
from source.webapp.render_helpers.styles import PAGE_CSS
from source.reporting.plan_health import plan_health_items

_REPORT_CSS = """
body { max-width: 900px; padding: 24px 28px 40px; }
.report-bar { display: flex; gap: 10px; justify-content: flex-end; margin-bottom: 14px; }
.report-head { display: flex; align-items: center; gap: 14px; border-bottom: 2px solid var(--navy, #1d3557); padding-bottom: 12px; margin-bottom: 14px; }
.report-head h1 { margin: 0; font-size: 24px; }
.report-head .meta { margin-left: auto; text-align: right; font-size: 12px; color: var(--ink-muted); }
.seg-group, .hero .muted a, .report a { text-decoration: none; }
.seg-group { display: none !important; }
.report h2.rep { margin-top: 22px; }
table.rep { width: 100%; border-collapse: collapse; font-size: 13px; }
table.rep th, table.rep td { padding: 5px 8px; border-bottom: 1px solid var(--border, #e5e5e5); text-align: left; }
table.rep td.num, table.rep th.num { text-align: right; }
.card { box-shadow: none !important; }
@media print {
  @page { margin: 14mm; }
  .report-bar { display: none !important; }
  body { padding: 0; background: #fff !important; max-width: none; }
  .card { break-inside: avoid; border: 1px solid #d2d2d7 !important; box-shadow: none !important; }
  .report-pagebreak { break-before: page; }
}
"""


def _table(headers: list[str], rows: list[list[str]], num_cols: tuple[int, ...] = ()) -> str:
    head = "".join(f'<th class="{"num" if i in num_cols else ""}">{html.escape(h)}</th>' for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f'<td class="{"num" if i in num_cols else ""}">{c}</td>' for i, c in enumerate(r)) + "</tr>"
        for r in rows
    )
    return f'<table class="rep"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _render_report_page() -> str:
    v = build_plan_views()
    s, mode, result = v["s"], v["mode"], v["display_result"]
    a = s["assumptions"]
    household = s.get("household") or db.household()
    names = html.escape(household["self_name"]) + (
        f" &amp; {html.escape(household['spouse_name'])}" if household.get("has_spouse") else ""
    )
    today = date.today().strftime("%B %d, %Y").replace(" 0", " ")
    name = html.escape(branding.PRODUCT_NAME)

    if v["empty_plan"]:
        sections = '<div class="card"><p>This plan has no accounts or spending yet, so there is nothing to report. Add them (or use the setup wizard) and come back.</p></div>'
    else:
        hero = blocks.hero_html(s, result, v["retirement_text"], mode, v["schedule"])
        hero = re.sub(r'<a href="/monte-carlo.html#assumptions">Change assumptions</a>', "", hero)
        proj = blocks.projection_card_html(s, result, mode, v["retirement_year"])
        income = blocks.income_sources_card_html(v["schedule"], a, mode, s["this_year"])
        own = blocks.own_owe_html(s)
        items = plan_health_items(s)
        checks = (
            "<ul>" + "".join(f"<li>{html.escape(i['text'])}</li>" for i in items) + "</ul>"
            if items else "<p>Nothing missing &mdash; every input the plan relies on is filled in.</p>"
        )
        cat_rows = [[html.escape(str(c)), f'<span class="mny">{_money(amt)}</span>'] for c, amt in s["asset_category_subtotals"] if amt]
        exp_rows = {}
        for e in s["expenses"]:
            exp_rows[e.get("category") or "Other"] = exp_rows.get(e.get("category") or "Other", 0.0) + float(e.get("annual_amount") or 0)
        expense_rows = [[html.escape(str(c)), _money(v_)] for c, v_ in sorted(exp_rows.items(), key=lambda kv: -kv[1])]
        horizon = int(float(a.get("plan_horizon_years") or 40))
        assumption_rows = [
            ["Average yearly growth", f"{_pct(a, 'expected_return', 0.06)}%"],
            ["Yearly ups and downs (volatility)", f"{_pct(a, 'return_volatility', 0.12)}%"],
            ["Inflation", f"{_pct(a, 'inflation_rate', 0.03)}%"],
            ["Planning horizon", f"{horizon} years"],
            ["Simulated market paths", f"{int(result['iterations']):,}"],
            ["Retirement", html.escape(v["retirement_text"].replace("Retirement year", "Year") if v["retirement_year"] else "Not set")],
            ["Dollar basis", "Today's dollars" if mode == "today" else "Future (inflated) dollars"],
        ]
        sections = f"""
{hero}
{own}
{proj}
{income}
<div class="card"><h2 style="margin-top:0">Things to check</h2>{checks}</div>
<div class="report-pagebreak"></div>
<h2 class="rep">What you own, by type</h2>
{_table(["Category", "Balance"], cat_rows, (1,)) if cat_rows else "<p class='muted'>No accounts entered.</p>"}
<h2 class="rep">Yearly spending, by category</h2>
{_table(["Category", "Per year"], expense_rows, (1,)) if expense_rows else "<p class='muted'>No spending entered.</p>"}
<h2 class="rep">Assumptions used</h2>
{_table(["Assumption", "Value"], assumption_rows, (1,))}
"""

    return f"""<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} -- Plan report</title>
<style>{PAGE_CSS}</style>
<style>{_REPORT_CSS}</style>
</head>
<body class="report">
<div class="report-bar">
  <button type="button" class="primary" onclick="window.print()">Save as PDF / Print</button>
  <a href="/summary.html"><button type="button">Back to Summary</button></a>
</div>
<div class="report-head">
  <img src="/icons/logo.svg" alt="" width="56" height="56" style="border-radius:12px;">
  <div><h1>{name} plan report</h1><div class="brand-tagline" style="font-size:13px;">{html.escape(branding.PRODUCT_TAGLINE)}</div></div>
  <div class="meta"><strong>{names}</strong><br>Prepared {today}</div>
</div>
{sections}
<p class="muted" style="margin-top:18px">Projections are estimates based on the assumptions above and simulated markets, not guarantees. This report is for planning and is not financial, tax or legal advice.</p>
</body>
</html>
"""
