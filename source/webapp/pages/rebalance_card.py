"""The Linked Positions "Rebalancing suggestions" card: compare your mix of
stocks, bonds, cash and other with a target and say what to buy and sell.
Suggestions only -- nothing places an order."""

from __future__ import annotations

import html

from source.reporting import rebalance
from source.webapp.render_helpers import _money


_FUND_WORD = {"Stocks": "stock fund", "Bonds": "bond fund", "Cash": "money market fund", "Other": "fund"}


def _trade_sentence(t: dict) -> str:
    cls = t["cls"].lower()
    fund = _FUND_WORD.get(t["cls"], "fund")
    amount = _money(round(t["amount"], -2) or t["amount"])
    if t["action"] == "sell":
        parts = []
        for p in t["picks"]:
            where = f" in {html.escape(p['account'])}" if p["account"] else ""
            if p["tax_treatment"] == "taxable":
                tax = (f"about {_money(p['est_gain'])} taxable gain" if p["basis_known"]
                       else "gain unknown (no cost basis on file)")
            else:
                tax = "no tax in a retirement account"
            parts.append(f"{_money(round(p['amount'], -2) or p['amount'])} of {html.escape(p['label'])}{where} <span class=\"muted\">({tax})</span>")
        detail = "; ".join(parts) if parts else "from your largest holding in that group"
        return f"<strong>Sell about {amount} of {cls}:</strong> {detail}."
    if t["picks"]:
        names = " or ".join(
            f"{html.escape(p['label'])}" + (f" ({html.escape(p['account'])})" if p["account"] else "") for p in t["picks"]
        )
        return f"<strong>Buy about {amount} of {cls}:</strong> add to {names}, or any low-cost {fund}."
    return f"<strong>Buy about {amount} of {cls}:</strong> you hold none yet, so a broad low-cost {fund} would do."


def rebalance_card_html(positions: list[dict], assumptions: dict) -> str:
    if not any((p.get("market_value") or 0) > 0 for p in positions):
        return ""
    overrides = rebalance.get_overrides()
    all_positions = positions
    accounts = rebalance.accounts_in(all_positions)
    scope = [a for a in rebalance.get_scope() if a in {x["account_id"] for x in accounts}]
    if scope:
        positions = [p for p in all_positions if (p.get("account_id") or p.get("account") or "") in scope]
    target = rebalance.get_target()
    inputs_t = target or rebalance.suggested_target(_age(assumptions))
    plan = rebalance.build_plan(positions, inputs_t, overrides)
    fields = "".join(
        f'<label>{c} %<input name="{c}" type="number" step="1" min="0" max="100" value="{inputs_t[c]:g}"></label>'
        for c in rebalance.CLASSES
    )
    form = f"""<form class="inline" onsubmit="event.preventDefault();
  var f = {{}}; new FormData(this).forEach(function(v, k) {{ f[k] = v; }});
  postJSON('/api/target-allocation', f).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  {fields}
  <button type="submit" class="primary">Save target</button>
  <button type="button" onclick="postJSON('/api/target-allocation', {{use_suggested: true}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">Use a suggested mix for my age</button>
</form>"""
    boxes = "".join(
        f'<label style="display:inline-flex; flex-direction:row; align-items:center; gap:6px; margin:2px 12px 2px 0; font-size:13px; color:var(--ink);">'
        f'<input type="checkbox" class="rb-acct" value="{html.escape(a["account_id"])}"{" checked" if a["account_id"] in scope else ""} style="width:auto;"> '
        f'{html.escape(a["label"])} <span class="muted">({_money(a["value"])})</span></label>'
        for a in accounts
    )
    if len(accounts) > 1:
        scope_note = (
            f"Showing only the {len(scope)} selected account{'s' if len(scope) != 1 else ''}." if scope
            else "Showing all accounts together. Tick one or more to get suggestions for just those."
        )
        scope_html = f"""<div style="margin:8px 0 4px">
<div class="muted small" style="margin-bottom:2px">Which accounts? {scope_note}</div>
<div>{boxes}</div>
<button type="button" class="chip" onclick="var ids = Array.prototype.map.call(document.querySelectorAll('.rb-acct:checked'), function(c) {{ return c.value; }}); postJSON('/api/rebalance-accounts', {{accounts: ids}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">Use selected accounts</button>
<button type="button" class="chip" onclick="postJSON('/api/rebalance-accounts', {{accounts: []}}).then(function() {{ location.reload(); }});">All accounts</button>
</div>"""
    else:
        scope_html = ""
    rows = ""
    for r in plan["rows"]:
        drift = r["drift_pts"]
        todo = "On target"
        css = "status-ok"
        if target and abs(drift) >= rebalance.DRIFT_THRESHOLD_PTS:
            css = "status-warn"
            todo = f"{'Sell' if r['delta'] < 0 else 'Buy'} about {_money(abs(r['delta']))}"
        elif not target:
            todo, css = "&mdash;", "muted"
        rows += (
            f'<tr><td>{r["cls"]}</td><td class="num">{_money(r["value"])}</td><td class="num">{r["pct"]:.0f}%</td>'
            f'<td class="num">{r["target_pct"]:.0f}%</td><td class="num">{"+" if drift >= 0 else "&minus;"}{abs(drift):.0f} pts</td>'
            f'<td class="{css}">{todo}</td></tr>'
        )
    if not target:
        verdict = ('<p class="muted">The target below is only a starting suggestion. Adjust it and press Save target '
                   "to see what to buy and sell.</p>")
        trades_html = ""
    elif not plan["needs_action"]:
        verdict = '<p class="status-line status-ok">You are within 5 points of your target in every group. Nothing to do.</p>'
        trades_html = ""
    else:
        verdict = f'<p class="status-line status-warn">Your mix has drifted at least {rebalance.DRIFT_THRESHOLD_PTS:g} points from your target.</p>'
        items = "".join(f"<li>{_trade_sentence(t)}</li>" for t in plan["trades"])
        trades_html = (
            f'<ul style="margin:6px 0 0 18px; padding:0; font-size:13px;">{items}</ul>'
            '<p class="muted small" style="margin:8px 0 0">Trades inside a retirement account cost no tax, so they come first. '
            "Directing new savings and dividends to the under-weight group can close the gap without selling anything. "
            "You place any trades yourself.</p>"
        )
    sorting = "".join(
        f'<tr><td>{html.escape(p.get("ticker") or p.get("security_name") or "")}</td>'
        f'<td class="muted">{html.escape(p.get("account") or "")}</td><td class="num">{_money(p["market_value"])}</td>'
        f'<td><select onchange="postJSON(\'/api/asset-class\', {{security_id: this.getAttribute(\'data-sid\'), asset_class: this.value}})'
        f'.then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});" data-sid="{html.escape(p["security_id"] or "")}">'
        + "".join(
            f'<option value="{v}"{" selected" if v == (overrides.get(p["security_id"]) or "auto") else ""}>{label}</option>'
            for v, label in (("auto", f"Auto ({rebalance.classify(p)})"), *((c, c) for c in rebalance.CLASSES))
        )
        + "</select></td></tr>"
        for p in sorted(all_positions, key=lambda p: -(p.get("market_value") or 0)) if (p.get("market_value") or 0) > 0
    )
    return f"""
<div class="card" id="rebalance">
<h3 class="sub" style="margin-top:0">Rebalancing suggestions</h3>
<p class="muted small" style="margin-top:0">Compares your linked investments ({_money(plan['total'])}) with the mix you want, and lists what to buy and sell to get back. Suggestions only &mdash; this app never places an order.</p>
{form}
{scope_html}
<div style="overflow-x:auto"><table><thead><tr><th>Group</th><th class="num">Now</th><th class="num">Share</th><th class="num">Target</th><th class="num">Off by</th><th>To do</th></tr></thead><tbody>{rows}</tbody></table></div>
{verdict}{trades_html}
<details class="how-it-works" style="margin-top:10px"><summary>How I grouped your holdings (change any that look wrong)</summary>
<p class="muted small">Funds are grouped by name and type, so a bond fund can be mistaken for a stock fund, or a target-date fund may fit better as "Other". Pick the right group and the numbers above update.</p>
<table><thead><tr><th>Holding</th><th>Account</th><th class="num">Value</th><th>Group</th></tr></thead><tbody>{sorting}</tbody></table></details>
<p class="muted small" style="margin:8px 0 0">General information, not personal investment, tax or legal advice. Selling in a taxable account can trigger capital-gains tax; gains shown are estimates from your cost basis.</p>
</div>
"""


def _age(assumptions: dict) -> int | None:
    from datetime import date

    try:
        return date.today().year - int(float(assumptions.get("birth_year")))
    except (TypeError, ValueError):
        return None
