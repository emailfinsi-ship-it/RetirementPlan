"""The printable plan report (/report.html): a client-ready review, laid out
the way an adviser hands one over -- a one-page summary with the top
recommendations, goals and where you stand, good / expected / bad market
scenarios, the income and tax picture, then the assumptions and disclosures.

"Report Download" opens it and uses the browser's own Save as PDF
(window.print) -- no PDF library needed, so it works on every machine the app
already runs on. Numbers come from build_plan_views(), the same source the
Summary uses, so the two can never disagree."""

from __future__ import annotations

import html
import re
from datetime import date

from source.common import backup, branding, db, linked_data
from source.reporting import advice, data_check, progress
from source.reporting import presentation as pres
from source.reporting.monte_carlo import run_historical_stress_test
from source.reporting.plan_health import plan_health_items
from source.webapp.pages import summary_blocks as blocks
from source.webapp.pages.summary import build_plan_views
from source.webapp.render_helpers import _money, _pct
from source.webapp.render_helpers.styles import PAGE_CSS

_REPORT_CSS = """
body { max-width: 900px; padding: 24px 28px 40px; }
.report-bar { display: flex; gap: 10px; justify-content: flex-end; margin-bottom: 14px; }
.report-head { display: flex; align-items: center; gap: 14px; border-bottom: 2px solid var(--navy, #1d3557); padding-bottom: 12px; margin-bottom: 6px; }
.report-head h1 { margin: 0; font-size: 24px; }
.report-head .meta { margin-left: auto; text-align: right; font-size: 12px; color: var(--ink-muted); }
.report-for { font-size: 13px; color: var(--ink-muted); margin: 0 0 12px; }
.seg-group, .hero .muted a, .report a { text-decoration: none; }
.seg-group { display: none !important; }
.rep-page { margin-top: 22px; }
.rep-page > h2.rep-title { margin: 0 0 4px; font-size: 20px; border-bottom: 1px solid var(--border, #e5e5e5); padding-bottom: 6px; }
.rep-page h3.rep { margin: 18px 0 6px; font-size: 15px; break-after: avoid; }
.rep-lead { margin: 4px 0 10px; font-size: 14px; }
.report h2.rep { margin-top: 22px; }
table.rep { width: 100%; border-collapse: collapse; font-size: 13px; }
table.rep th, table.rep td { padding: 5px 8px; border-bottom: 1px solid var(--border, #e5e5e5); text-align: left; vertical-align: top; }
table.rep td.num, table.rep th.num { text-align: right; }
table.rep th small { display: block; font-weight: 400; color: var(--ink-muted); }
table.rep th.sc-bad { border-bottom: 3px solid #b45309; }
table.rep th.sc-mid { border-bottom: 3px solid #1d3557; }
table.rep th.sc-good { border-bottom: 3px solid #15803d; }
ol.rep-recs { margin: 6px 0 0; padding-left: 22px; font-size: 14px; }
ol.rep-recs li { margin: 0 0 8px; }
ol.rep-recs .why { display: block; color: var(--ink-muted); font-size: 13px; }
ul.rep-notes { margin: 6px 0 0; padding-left: 20px; font-size: 12.5px; color: var(--ink-muted); }
ul.rep-notes li { margin: 0 0 5px; }
.rep-foot { margin-top: 26px; border-top: 1px solid var(--border, #e5e5e5); padding-top: 8px; font-size: 11.5px; color: var(--ink-muted); }
.card { box-shadow: none !important; }
@media print {
  @page { margin: 14mm 14mm 18mm; @bottom-center { content: "__BRAND__ plan report  |  Page " counter(page); font-size: 9pt; color: #6b7280; } }
  .report-bar { display: none !important; }
  body { padding: 0; background: #fff !important; max-width: none; }
  .card { break-inside: avoid; border: 1px solid #d2d2d7 !important; box-shadow: none !important; }
  .rep-page { break-before: page; margin-top: 0; }
  .rep-page.first { break-before: auto; }
  table.rep tr { break-inside: avoid; }
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


def _unlink(markup: str) -> str:
    """A printed page has nowhere to click: keep the words, drop the anchors."""
    return re.sub(r"<a\b[^>]*>(.*?)</a>", r"\1", markup, flags=re.S)


def _section(number: int, title: str, body: str, *, first: bool = False) -> str:
    cls = "rep-page first" if first else "rep-page"
    return f'<section class="{cls}"><h2 class="rep-title">{number}. {html.escape(title)}</h2>{body}</section>'


def _milestone_years(years: list[int], retirement_year: int | None) -> list[int]:
    """A handful of years to tabulate: the start, the retirement year, every
    ten years, and the last year -- never a wall of 40 rows on paper."""
    if not years:
        return []
    first, last = years[0], years[-1]
    picks = {first, last}
    if retirement_year is not None and first <= retirement_year <= last:
        picks.add(retirement_year)
    picks.update(y for y in years if (y - first) % 10 == 0)
    return sorted(picks)


def _converter(mode: str, assumptions: dict, base_year: int):
    infl = pres.inflation_rate(assumptions)
    if mode == "today":
        return lambda value, year: pres.to_today(value, infl, int(year) - base_year)
    return lambda value, year: value


def _next_review(today_d: date) -> str:
    """A year from today, as "Month Year"."""
    return date(today_d.year + 1, today_d.month, 1).strftime("%B %Y")


def _recommendations_html(actions: list[dict]) -> str:
    if not actions:
        return ('<p class="rep-lead">Nothing needs urgent attention. Keep your numbers up to date and '
                'review the plan again in a year.</p>')
    items = "".join(
        f'<li><strong>{html.escape(a["title"])}</strong>'
        + (f'<span class="why">{html.escape(a["why"])}</span>' if a.get("why") else "")
        + "</li>"
        for a in actions[:3]
    )
    return f'<ol class="rep-recs">{items}</ol>'


def _goals_html(s: dict, v: dict, result: dict, horizon: int) -> str:
    status = pres.plan_status(result["success_rate"])
    rows = [[
        "Your money lasts through the plan",
        f"{pres.percent_display(pres.ON_TRACK_AT)} chance or better",
        pres.percent_display(result["success_rate"]),
        html.escape(status["label"]),
    ]]
    fi = progress.independence_progress(s)
    if fi:
        if fi["reached"]:
            where = "Reached"
        elif fi["year"]:
            where = f"About {fi['year']} at today's pace"
        else:
            where = "Keep saving"
        rows.append([
            "Savings that could pay your yearly costs for life",
            f"{_money(fi['target'])} (25 times the {_money(fi['need'])} a year your income does not cover)",
            f"{_money(fi['savings'])} ({fi['pct']:.0f}%)",
            html.escape(where),
        ])
    rows.append(["Retirement date", html.escape(v["retirement_text"]), "", "Planned" if v["retirement_year"] else "Not set"])
    end_year, end_age = pres.last_year_and_age(result, s["assumptions"])
    if end_year:
        age_part = f", age {end_age}" if end_age else ""
        rows.append(["How long the plan runs", f"{horizon} years", f"Through {end_year}{age_part}", ""])
    return _table(["Goal", "Target", "Where you stand", "Status"], rows, (2,))


def _scenarios_html(s: dict, v: dict, result: dict, mode: str) -> str:
    a = s["assumptions"]
    band = result.get("band") or []
    by_year = {int(r["year"]): r for r in band}
    picks = _milestone_years(sorted(by_year), v["retirement_year"])
    rows = []
    for y in picks:
        r = by_year[y]
        tag = " (retirement)" if v["retirement_year"] == y else ""
        rows.append([
            f"{y}{tag}",
            f'<span class="mny">{_money(r["p10"])}</span>',
            f'<span class="mny">{_money(r["median"])}</span>',
            f'<span class="mny">{_money(r["p90"])}</span>',
        ])
    head = (
        '<table class="rep"><thead><tr><th>Year</th>'
        f'<th class="num sc-bad">Bad market<small>{html.escape(pres.LABEL_CAUTIOUS)}</small></th>'
        f'<th class="num sc-mid">Expected market<small>{html.escape(pres.LABEL_TYPICAL)}</small></th>'
        f'<th class="num sc-good">Good market<small>{html.escape(pres.LABEL_STRONG)}</small></th>'
        "</tr></thead><tbody>"
    )
    table = head + "".join(
        "<tr>" + f"<td>{r[0]}</td>" + "".join(f'<td class="num">{c}</td>' for c in r[1:]) + "</tr>" for r in rows
    ) + "</tbody></table>"

    lead = (
        f'<p class="rep-lead">We tried {int(result["iterations"]):,} possible market futures. In '
        f'{pres.percent_display(result["success_rate"])} of them your money lasts. The table shows what your savings '
        f'could be worth in a bad, an expected and a good market ({html.escape(pres.dollars_caption(mode))}).</p>'
    ) if rows else ""

    stress_html = ""
    try:
        stress = run_historical_stress_test(
            starting_balance=s["net_liquid_asset"], expenses=s["expenses"], income=s["income_for_simulation"],
            assumptions=a, pools=s["retirement_pools"],
        )
        convert = _converter(mode, a, s["this_year"])
        srows = []
        for sc in stress["scenarios"]:
            last_year = sc["path"][-1]["year"] if sc["path"] else s["this_year"]
            srows.append([
                html.escape(sc["label"]),
                "No" if sc["depleted"] else "Yes",
                str(sc["depleted_year"]) if sc["depleted_year"] else "--",
                f'<span class="mny">{_money(convert(sc["ending_balance"], last_year))}</span>',
            ])
        stress_html = (
            '<h3 class="rep">If history repeated</h3>'
            '<p class="muted small" style="margin:0 0 6px">The same spending plan, run through the real market '
            'sequence that followed some of the worst starting years on record.</p>'
            + _table(["Market sequence", "Money lasts?", "Runs out in", "Left at the end"], srows, (3,))
        )
    except Exception:  # a report must still open if the stress replay cannot run
        stress_html = ""
    return lead + table + stress_html


def _income_tax_html(s: dict, v: dict, mode: str) -> str:
    a = s["assumptions"]
    schedule = v["schedule"] or {}
    rows_all = schedule.get("rows") or []
    retire = schedule.get("retirement_year")
    rows_ret = [r for r in rows_all if retire is None or r["year"] >= retire] or rows_all
    convert = _converter(mode, a, s["this_year"])
    by_year = {r["year"]: r for r in rows_ret}
    picks = _milestone_years(sorted(by_year), retire)
    table_rows = []
    for y in picks:
        r = by_year[y]
        social = convert(r.get("income_social_security", 0.0), y)
        other = convert(r.get("income_rental", 0.0) + r.get("income_other", 0.0), y)
        drawn = convert(
            r.get("drawn_taxable", 0.0) + r.get("drawn_tax_deferred", 0.0)
            + r.get("drawn_roth", 0.0) + r.get("drawn_real_estate", 0.0), y)
        table_rows.append([
            str(y), str(r["age"]) if r.get("age") is not None else "--",
            _money(convert(r.get("expenses", 0.0), y)), _money(social), _money(other),
            _money(drawn), _money(convert(r.get("tax", 0.0), y)),
        ])
    total_tax = sum(convert(r.get("tax", 0.0), r["year"]) for r in rows_ret)
    n = len(rows_ret) or 1
    if total_tax > 0.5:
        tax_line = (
            f'<p class="rep-lead">Estimated taxes on your withdrawals and income come to about '
            f'<strong>{_money(total_tax)}</strong> over {len(rows_ret)} years, roughly {_money(total_tax / n)} a year '
            f'({html.escape(pres.dollars_caption(mode))}).</p>'
        )
    else:
        tax_line = ('<p class="rep-lead">This projection does not include a tax estimate, so the figures below are '
                    'before tax.</p>')
    watch = ""
    if rows_ret:
        convert_row = (lambda value, year: convert(value, year))
        sentence = pres.watch_sentence(rows_ret, _money, convert_row)
        if sentence:
            watch = f'<p class="rep-lead"><strong>{html.escape(sentence)}</strong></p>'
    table = _table(
        ["Year", "Age", "Spending", "Social Security", "Rent and other income", "Taken from savings", "Est. tax"],
        table_rows, (2, 3, 4, 5, 6),
    ) if table_rows else "<p class='muted'>No retirement years to show yet.</p>"
    income = _unlink(blocks.income_sources_card_html(v["schedule"], a, mode, s["this_year"])) if v["schedule"] else ""
    return tax_line + watch + table + income


def _disclosures_html() -> str:
    name = html.escape(branding.PRODUCT_NAME)
    notes = [
        "Projections are estimates, not guarantees. They come from computer simulations of possible markets and from "
        "the assumptions listed above; real results will differ.",
        "Past market performance does not predict future results. The historical replays use the recorded annual "
        "returns of the S&P 500 only.",
        "Tax figures are simplified estimates of federal and state income tax on withdrawals. They do not replace a tax "
        "return or advice from a tax professional.",
        "Account balances, spending and income are the figures you entered or linked. A mistake or an out-of-date number "
        "carries straight through to every figure in this report.",
        f"This report is for planning and is not financial, tax or legal advice. {name} is software, not a registered "
        "investment adviser, and has no knowledge of your full circumstances. Talk to a qualified professional before "
        "acting on any of it.",
    ]
    return '<h3 class="rep">Important information</h3><ul class="rep-notes">' + "".join(
        f"<li>{html.escape(n)}</li>" for n in notes) + "</ul>"


def _render_report_page() -> str:
    v = build_plan_views()
    s, mode, result = v["s"], v["mode"], v["display_result"]
    a = s["assumptions"]
    household = s.get("household") or db.household()
    names = html.escape(household["self_name"]) + (
        f" &amp; {html.escape(household['spouse_name'])}" if household.get("has_spouse") else ""
    )
    today_d = date.today()
    today = today_d.strftime("%B %d, %Y").replace(" 0", " ")
    name = html.escape(branding.PRODUCT_NAME)

    if v["empty_plan"]:
        sections = '<div class="card"><p>This plan has no accounts or spending yet, so there is nothing to report. Add them (or use the setup wizard) and come back.</p></div>'
    else:
        horizon = int(float(a.get("plan_horizon_years") or 40))
        positions = linked_data.read_linked_portfolio_positions()
        issues = data_check.run_checks(s, positions, backup.verify_latest())
        items = plan_health_items(s)
        actions = advice.build_actions(s, result["success_rate"], positions, issues, items)

        hero = blocks.hero_html(s, result, v["retirement_text"], mode, v["schedule"])
        hero = re.sub(r"\s*Change assumptions", "", _unlink(hero))
        glance = (
            hero
            + '<h3 class="rep">What we recommend</h3>' + _recommendations_html(actions)
            + f'<p class="muted small" style="margin-top:10px">Suggested next review: {_next_review(today_d)}, or sooner after any big change in your life or the markets.</p>'
        )

        own = _unlink(blocks.own_owe_html(s))
        goals = (
            '<p class="rep-lead">The targets your plan is working toward, and how close you are today.</p>'
            + _goals_html(s, v, result, horizon) + own
        )

        proj = _unlink(blocks.projection_card_html(s, result, mode, v["retirement_year"]))
        scenarios = proj + _scenarios_html(s, v, result, mode)

        income_tax = _income_tax_html(s, v, mode)

        checks = (
            "<ul>" + "".join(f"<li>{html.escape(i['text'])}</li>" for i in items) + "</ul>"
            if items else "<p>Nothing missing &mdash; every input the plan relies on is filled in.</p>"
        )
        cat_rows = [[html.escape(str(c)), f'<span class="mny">{_money(amt)}</span>'] for c, amt in s["asset_category_subtotals"] if amt]
        exp_rows = {}
        for e in s["expenses"]:
            exp_rows[e.get("category") or "Other"] = exp_rows.get(e.get("category") or "Other", 0.0) + float(e.get("annual_amount") or 0)
        expense_rows = [[html.escape(str(c)), _money(v_)] for c, v_ in sorted(exp_rows.items(), key=lambda kv: -kv[1])]
        assumption_rows = [
            ["Average yearly growth", f"{_pct(a, 'expected_return', 0.06)}%"],
            ["Yearly ups and downs (volatility)", f"{_pct(a, 'return_volatility', 0.12)}%"],
            ["Inflation", f"{_pct(a, 'inflation_rate', 0.03)}%"],
            ["Planning horizon", f"{horizon} years"],
            ["Simulated market paths", f"{int(result['iterations']):,}"],
            ["Retirement", html.escape(v["retirement_text"].replace("Retirement year", "Year") if v["retirement_year"] else "Not set")],
            ["Dollar basis", "Today's dollars" if mode == "today" else "Future (inflated) dollars"],
        ]
        back = (
            '<h3 class="rep">Things still to check</h3>' + checks
            + '<h3 class="rep">What you own, by type</h3>'
            + (_table(["Category", "Balance"], cat_rows, (1,)) if cat_rows else "<p class='muted'>No accounts entered.</p>")
            + '<h3 class="rep">Yearly spending, by category</h3>'
            + (_table(["Category", "Per year"], expense_rows, (1,)) if expense_rows else "<p class='muted'>No spending entered.</p>")
            + '<h2 class="rep">Assumptions used</h2>'
            + _table(["Assumption", "Value"], assumption_rows, (1,))
            + _disclosures_html()
        )
        sections = (
            _section(1, "Your plan at a glance", glance, first=True)
            + _section(2, "Goals and where you stand", goals)
            + _section(3, "Good, expected and bad markets", scenarios)
            + _section(4, "Income and tax picture", income_tax)
            + _section(5, "Assumptions and disclosures", back)
        )

    return f"""<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} -- Plan report</title>
<style>{PAGE_CSS}</style>
<style>{_REPORT_CSS.replace('__BRAND__', branding.PRODUCT_NAME)}</style>
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
<p class="report-for">Retirement plan review prepared for {names}</p>
{sections}
<p class="rep-foot">Projections are estimates based on the assumptions above and simulated markets, not guarantees. This report is for planning and is not financial, tax or legal advice. Prepared with {name}.</p>
</body>
</html>
"""
