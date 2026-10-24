"""The Risk & Suggestions tab (under Linked Accounts): pick a risk appetite,
see today's mix overall and by institution, and for each linked investment
account get plain-words advice on what to sell and buy *inside that account*
to reach the goal mix. Suggestions only -- nothing places an order."""

from __future__ import annotations

import html
from datetime import date

from source.common import db, linked_data
from source.reporting import rebalance
from source.webapp.render_helpers import _money, _shell

_COLORS = {"Stocks": "#3b82f6", "Bonds": "#f59e0b", "Cash": "#10b981", "Other": "#9ca3af"}
_FUND_WORD = {"Stocks": "stock fund", "Bonds": "bond fund", "Cash": "money market fund", "Other": "fund"}
_TREATMENT_NOTE = {
    "tax_deferred": "Retirement account: buying and selling here costs no tax.",
    "roth": "Roth account: buying and selling here costs no tax.",
    "taxable": "Regular (taxable) account: selling at a profit can mean a tax bill.",
}


def _age(assumptions: dict) -> int | None:
    try:
        return date.today().year - int(float(assumptions.get("birth_year")))
    except (TypeError, ValueError):
        return None


def _round(amount: float) -> float:
    return round(amount, -2) or amount


def _mix_text(rows: list[dict], key: str) -> str:
    return ", ".join(f"{r[key]:.0f}% {r['cls'].lower()}" for r in rows)


def _bar(rows: list[dict]) -> str:
    segs = "".join(
        f'<span title="{r["cls"]} {r["pct"]:.0f}%" style="width:{r["pct"]:.2f}%; background:{_COLORS[r["cls"]]};"></span>'
        for r in rows if r["pct"] > 0
    )
    return (f'<div style="display:flex; height:12px; border-radius:6px; overflow:hidden; gap:2px; margin:8px 0 4px;" '
            f'role="img" aria-label="Current mix">{segs}</div>')


def _trade_line(t: dict) -> str:
    amount = _money(_round(t["amount"]))
    cls = t["cls"].lower()
    if t["action"] == "sell":
        names = ", ".join(html.escape(p["label"]) for p in t["picks"]) or f"some of your {cls}"
        gain = sum(p["est_gain"] for p in t["picks"])
        tax = f' <span class="muted">(about {_money(_round(gain))} of that would be taxable profit)</span>' if gain > 0 else ""
        return f"<strong>Sell</strong> about {amount} of {names}.{tax}"
    fund = _FUND_WORD.get(t["cls"], "fund")
    if t["picks"]:
        names = " or ".join(html.escape(p["label"]) for p in t["picks"])
        return f"<strong>Buy</strong> about {amount} of {names} (or any low-cost {fund})."
    return f"<strong>Buy</strong> about {amount} of a low-cost {fund}."


def _account_card(label: str, positions: list[dict], target: dict, overrides: dict) -> str:
    plan = rebalance.build_plan(positions, target, overrides)
    if plan["total"] <= 0:
        return ""
    treatment = positions[0].get("tax_treatment") or "taxable"
    note = _TREATMENT_NOTE.get(treatment, "")
    if plan["needs_action"] and plan["trades"]:
        badge = '<span class="status-warn">Needs a change</span>'
        items = "".join(f"<li>{_trade_line(t)}</li>" for t in plan["trades"])
        todo = f'<p style="margin:8px 0 2px"><strong>What to do</strong></p><ul style="margin:0 0 0 18px; padding:0;">{items}</ul>'
    else:
        badge = '<span class="status-ok">Looks good</span>'
        todo = '<p style="margin:8px 0 0">Nothing to do here. This account is close to your goal.</p>'
    return f"""<div class="card">
<div style="display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; align-items:baseline;">
<h3 class="sub" style="margin:0">{html.escape(label)} <span class="muted" style="font-weight:normal">&middot; {_money(plan['total'])}</span></h3>
<div>{badge}</div></div>
{_bar(plan['rows'])}
<div class="muted small">Now: {_mix_text(plan['rows'], 'pct')}. Goal: {_mix_text(plan['rows'], 'target_pct')}.</div>
{todo}
<p class="muted small" style="margin:8px 0 0">{note}</p>
</div>"""


def _goal_form(target: dict) -> str:
    fields = "".join(
        f'<label>{c} %<input name="{c}" type="number" step="1" min="0" max="100" value="{target[c]:g}"></label>'
        for c in rebalance.CLASSES
    )
    return f"""<form class="inline" onsubmit="event.preventDefault();
  var f = {{}}; new FormData(this).forEach(function(v, k) {{ f[k] = v; }});
  postJSON('/api/target-allocation', f).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  {fields}
  <button type="submit" class="primary">Save my own mix</button>
</form>"""


def _risk_card(target: dict, risk: str, age: int | None, overall: dict, goal_src: str) -> str:
    options = ""
    for key, (label, _off, _cash, desc) in rebalance.RISK_LEVELS.items():
        t = rebalance.risk_target(key, age)
        on = " risk-on" if risk == key else ""
        options += (
            f'<button type="button" class="risk-opt{on}" onclick="postJSON(\'/api/risk-appetite\', {{level: \'{key}\'}})'
            f'.then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">'
            f'<strong>{label}</strong><span class="risk-mix">{t["Stocks"]:.0f}% stocks &middot; {t["Bonds"]:.0f}% bonds &middot; {t["Cash"]:.0f}% cash</span>'
            f'<span class="muted small">{desc}</span></button>'
        )
    tiles = "".join(
        f'<div class="tile"><div class="label"><span style="display:inline-block; width:10px; height:10px; border-radius:2px; '
        f'background:{_COLORS[r["cls"]]}; margin-right:6px;"></span>{r["cls"]}</div>'
        f'<div class="value">{r["pct"]:.0f}%</div>'
        f'<div class="muted small">{_money(r["value"])} &middot; goal {r["target_pct"]:.0f}%</div></div>'
        for r in overall["rows"]
    )
    loss = rebalance.worst_year_loss_pct(target)
    if risk == "custom":
        chosen = "You are using your own mix."
    elif risk in rebalance.RISK_LEVELS:
        chosen = f"You chose {rebalance.RISK_LEVELS[risk][0]}."
    else:
        chosen = "Not chosen yet, so Moderate is shown."
    goal_text = ", ".join(f"{target[c]:.0f}% {c.lower()}" for c in rebalance.CLASSES)
    return f"""<div class="card">
<h3 class="sub" style="margin-top:0">How much risk are you comfortable with?</h3>
<p class="muted small" style="margin:0 0 8px">Pick one. It sets your goal mix of stocks, bonds and cash. {chosen}</p>
<div class="risk-grid">{options}</div>
<p style="margin:12px 0 2px"><strong>Your goal:</strong> {goal_text}.</p>
<p class="muted small" style="margin:0">In a very bad year (like 2008) a mix like this could lose roughly {loss:.0f}% of its value. {goal_src}</p>
<details class="how-it-works" style="margin-top:8px"><summary>Or type my own mix</summary>{_goal_form(target)}</details>
<h3 class="sub">Your mix today <span class="muted" style="font-weight:normal">&middot; all linked accounts, {_money(overall['total'])}</span></h3>
{_bar(overall['rows'])}
<div class="tiles" style="margin-top:10px">{tiles}</div>
</div>"""


def _institution_card(positions: list[dict], overrides: dict) -> str:
    groups: dict[str, list[dict]] = {}
    for p in positions:
        groups.setdefault(p.get("institution") or "Other", []).append(p)
    if len(groups) < 1:
        return ""
    rows = ""
    for name in sorted(groups, key=lambda k: -sum(p["market_value"] for p in groups[k])):
        plan = rebalance.build_plan(groups[name], {}, overrides)
        text = " &middot; ".join(
            f'<span style="white-space:nowrap"><span style="display:inline-block; width:8px; height:8px; border-radius:2px; background:{_COLORS[r["cls"]]}"></span> '
            f'{r["cls"]} {r["pct"]:.0f}%</span>' for r in plan["rows"]
        )
        rows += (
            f'<div class="inst-row"><div style="display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap;">'
            f'<strong>{html.escape(name)}</strong><span class="muted">{_money(plan["total"])}</span></div>'
            f'{_bar(plan["rows"])}<div class="small muted">{text}</div></div>'
        )
    return f"""<details class="fold" id="fold-mix-inst"><summary><span class="fold-title">Your mix by institution</span><span class="fold-hint">stocks, bonds and cash at each firm</span></summary><div class="card">
<h3 class="sub" style="margin-top:0">Your mix by institution</h3>
{rows}
</div></details>"""



def _grouping_html(positions: list[dict], overrides: dict) -> str:
    rows = "".join(
        f'<tr><td>{html.escape(p.get("ticker") or p.get("security_name") or "")}</td>'
        f'<td class="muted">{html.escape(p.get("account") or "")}</td><td class="num">{_money(p["market_value"])}</td>'
        f'<td><select onchange="postJSON(\'/api/asset-class\', {{security_id: this.getAttribute(\'data-sid\'), asset_class: this.value}})'
        f'.then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});" data-sid="{html.escape(p["security_id"] or "")}">'
        + "".join(
            f'<option value="{v}"{" selected" if v == (overrides.get(p["security_id"]) or "auto") else ""}>{label}</option>'
            for v, label in (("auto", f"Auto ({rebalance.classify(p)})"), *((c, c) for c in rebalance.CLASSES))
        )
        + "</select></td></tr>"
        for p in sorted(positions, key=lambda p: -(p.get("market_value") or 0)) if (p.get("market_value") or 0) > 0
    )
    return f"""<details class="how-it-works"><summary>Does a holding look like it's in the wrong group?</summary>
<p class="muted small">I sort each holding into stocks, bonds, cash or other by its name and type. If one is wrong (for example a bond fund counted as stocks), pick the right group and everything updates.</p>
<table><thead><tr><th>Holding</th><th>Account</th><th class="num">Value</th><th>Group</th></tr></thead><tbody>{rows}</tbody></table></details>"""


def _margin_card(summary: dict | None) -> str:
    if not summary:
        return ""
    where = f" ({html.escape(', '.join(summary['where']))})" if summary["where"] else ""
    return f"""<div class="card" id="margin-loan">
<h3 class="sub" style="margin-top:0">Margin loan{where}</h3>
<p style="margin:0 0 6px">You have borrowed <strong>{_money(summary['loan'])}</strong> against your holdings, which is {summary['pct_of_holdings']:.0f}% of them.</p>
<p style="margin:0 0 6px">Your holdings add up to {_money(summary['holdings'])}. After the loan you own <strong>{_money(summary['net'])}</strong>.</p>
<p class="muted small" style="margin:0">The mixes below are worked out on the holdings before the loan, so they show what you are really exposed to. Borrowing makes a market drop hurt more: a 10% fall in your holdings is a {summary['holdings'] * 0.10 / summary['net'] * 100 if summary['net'] > 0 else 0:.0f}% fall in what you own.</p>
</div>"""


def _render_rebalance_page() -> str:
    all_positions = linked_data.read_linked_portfolio_positions()
    margin = rebalance.margin_loan_summary(all_positions)
    # Skip holdings worth under a dollar: an account that shows as $0 has nothing to rebalance.
    positions = [p for p in all_positions if (p.get("market_value") or 0) >= 1]
    head = ('<h2 style="margin-top:0">Risk &amp; Suggestions</h2>'
            '<p class="muted">Pick how much risk you are comfortable with. Below, each account tells you what to do, '
            'if anything, to match it. These are suggestions only &mdash; this app never buys or sells for you.</p>')
    if not positions:
        body = head + '<div class="card"><p class="muted" style="margin:0">No linked investment accounts yet. Connect one on the Setup tab and your suggestions will show up here.</p></div>'
        return _shell(title="Risk & Suggestions", active="rebalance.html", body=body)
    age = _age(db.get_assumptions())
    saved = rebalance.get_target()
    risk = rebalance.get_risk() if saved else ""
    target = saved or rebalance.risk_target("moderate", age)
    overrides = rebalance.get_overrides()
    goal_src = "" if saved else "This is a starting mix picked for your age."
    overall = rebalance.build_plan(positions, target, overrides)
    risk_card = _risk_card(target, risk, age, overall, goal_src)
    inst_card = _institution_card(positions, overrides)
    accounts: dict[str, list[dict]] = {}
    labels: dict[str, str] = {}
    for p in positions:
        key = p.get("account_id") or p.get("account") or ""
        accounts.setdefault(key, []).append(p)
        labels.setdefault(key, " - ".join(x for x in (p.get("institution"), p.get("account")) if x) or "Account")
    order = sorted(accounts, key=lambda k: (labels[k].split(" - ")[0], -sum(p["market_value"] for p in accounts[k])))
    cards = "".join(_account_card(labels[k], accounts[k], target, overrides) for k in order if sum(p["market_value"] for p in accounts[k]) >= 1)
    legend = "".join(
        f'<span style="display:inline-flex; align-items:center; gap:4px; margin-right:12px;"><span style="width:10px; height:10px; border-radius:2px; background:{_COLORS[c]}"></span>{c}</span>'
        for c in rebalance.CLASSES
    )
    body = f"""{head}
<style>
.risk-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:10px; }}
.risk-opt {{ text-align:left; display:flex; flex-direction:column; gap:3px; padding:12px 14px; border:1px solid var(--border);
  border-radius:12px; background:var(--surface); cursor:pointer; font:inherit; color:var(--ink); }}
.risk-opt:hover {{ border-color:var(--brand); }}
.risk-opt.risk-on {{ border-color:var(--brand); background:var(--brand-soft); box-shadow:0 0 0 1px var(--brand) inset; }}
.risk-mix {{ font-size:12.5px; color:var(--ink-soft); }}
.inst-row {{ padding:8px 0; border-bottom:1px solid var(--border); }} .inst-row:last-child {{ border-bottom:0; }}
</style>
{risk_card}
{_margin_card(margin)}
<h3 class="sub">What to do in each account</h3>
<div class="muted small" style="margin:4px 0 8px">{legend}</div>
{cards}
{inst_card}
{_grouping_html(positions, overrides)}
<p class="muted small">Taxable gains shown are estimates from your cost basis.</p>"""
    return _shell(title="Risk & Suggestions", active="rebalance.html", body=body)
