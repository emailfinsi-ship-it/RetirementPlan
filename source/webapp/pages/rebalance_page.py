"""The Rebalance tab (under Linked Accounts): for each linked investment
account, say in plain words whether its mix of stocks, bonds and cash is
where you want it and, if not, what to sell and buy *inside that account*.
Suggestions only -- nothing places an order."""

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
  <button type="submit" class="primary">Save my goal</button>
  <button type="button" onclick="postJSON('/api/target-allocation', {{use_suggested: true}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">Pick a mix for my age</button>
</form>"""


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


def _render_rebalance_page() -> str:
    # Skip holdings worth under a dollar: an account that shows as $0 has nothing to rebalance.
    positions = [p for p in linked_data.read_linked_portfolio_positions() if (p.get("market_value") or 0) >= 1]
    head = ('<h2 style="margin-top:0">Rebalance</h2>'
            '<p class="muted">Keeping the right mix of stocks, bonds and cash helps protect your retirement. '
            'Below, each account tells you what to do, if anything. These are suggestions only &mdash; '
            'this app never buys or sells for you.</p>')
    if not positions:
        body = head + '<div class="card"><p class="muted" style="margin:0">No linked investment accounts yet. Connect one on the Setup tab and your suggestions will show up here.</p></div>'
        return _shell(title="Rebalance", active="rebalance.html", body=body)
    saved = rebalance.get_target()
    target = saved or rebalance.suggested_target(_age(db.get_assumptions()))
    overrides = rebalance.get_overrides()
    goal_src = ("the goal you saved" if saved else "a starting mix picked for your age &mdash; change it below if you like")
    goal_text = ", ".join(f"{target[c]:.0f}% {c.lower()}" for c in rebalance.CLASSES)
    overall = rebalance.build_plan(positions, target, overrides)
    tiles = "".join(
        f'<div class="tile"><div class="label"><span style="display:inline-block; width:10px; height:10px; border-radius:2px; '
        f'background:{_COLORS[r["cls"]]}; margin-right:6px;"></span>{r["cls"]}</div>'
        f'<div class="value">{r["pct"]:.0f}%</div>'
        f'<div class="muted small">{_money(r["value"])} &middot; goal {r["target_pct"]:.0f}%</div></div>'
        for r in overall["rows"]
    )
    goal = f"""<div class="card">
<h3 class="sub" style="margin-top:0">Your mix today <span class="muted" style="font-weight:normal">&middot; all linked accounts, {_money(overall['total'])}</span></h3>
{_bar(overall['rows'])}
<div class="tiles" style="margin-top:10px">{tiles}</div>
<p class="muted small" style="margin:10px 0 8px">Your goal is {goal_text}. This is {goal_src}.</p>
<details class="how-it-works"><summary>Change my goal</summary>{_goal_form(target)}</details>
</div>"""
    accounts: dict[str, list[dict]] = {}
    labels: dict[str, str] = {}
    for p in positions:
        key = p.get("account_id") or p.get("account") or ""
        accounts.setdefault(key, []).append(p)
        labels.setdefault(key, " - ".join(x for x in (p.get("institution"), p.get("account")) if x) or "Account")
    order = sorted(accounts, key=lambda k: -sum(p["market_value"] for p in accounts[k]))
    cards = "".join(_account_card(labels[k], accounts[k], target, overrides) for k in order if sum(p["market_value"] for p in accounts[k]) >= 1)
    legend = "".join(
        f'<span style="display:inline-flex; align-items:center; gap:4px; margin-right:12px;"><span style="width:10px; height:10px; border-radius:2px; background:{_COLORS[c]}"></span>{c}</span>'
        for c in rebalance.CLASSES
    )
    body = f"""{head}
{goal}
<div class="muted small" style="margin:4px 0 8px">{legend}</div>
{cards}
{_grouping_html(positions, overrides)}
<p class="muted small">Taxable gains shown are estimates from your cost basis.</p>"""
    return _shell(title="Rebalance", active="rebalance.html", body=body)
