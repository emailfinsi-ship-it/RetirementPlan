"""The Income & Expenses tab's "Social Security & Medicare planner" card --
inputs, a claiming-age comparison per person, and the Medicare/IRMAA tier
for the income entered. Calculations live in source.reporting.benefits."""

from __future__ import annotations

import html

from source.reporting import benefits
from source.webapp.render_helpers import _money


def _value(assumptions: dict, key: str) -> str:
    return html.escape(str(assumptions.get(key) or ""))


def _claim_select(name: str, selected: int | None) -> str:
    options = "".join(
        f'<option value="{age}"{" selected" if age == selected else ""}>{age}</option>' for age in benefits.CLAIM_AGES
    )
    placeholder = '<option value=""' + ("" if selected else " selected") + ">--</option>"
    return f'<select name="{name}">{placeholder}{options}</select>'


def _table_html(person: dict) -> str:
    if not (person["birth_year"] and person["benefit"]):
        return ""
    chosen = person["claim_age"]
    rows = []
    for r in benefits.claiming_table(person["benefit"], person["birth_year"]):
        be = f"{r['break_even_vs_62']:.1f}" if r["break_even_vs_62"] else "--"
        mark = ' style="font-weight:600;"' if r["age"] == chosen else ""
        rows.append(
            f"<tr{mark}><td>{r['age']}</td><td>{r['start_year']}</td><td class=\"num\">{r['factor'] * 100:.0f}%</td>"
            f"<td class=\"num\">{_money(r['annual'])}</td><td class=\"num\">{_money(r['total_to_85'])}</td>"
            f"<td class=\"num\">{be}</td></tr>"
        )
    return f"""
<h3 style="font-size:13px; margin-bottom:0;">{html.escape(person['name'])}: claiming age comparison
<span class="muted">(full retirement age {benefits.fra_text(person['birth_year'])})</span></h3>
<div style="overflow-x:auto"><table>
<thead><tr><th>Claim at</th><th>First year</th><th class="num">% of full benefit</th><th class="num">Per year</th>
<th class="num">Total by age 85</th><th class="num">Break-even vs. 62 (age)</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p style="margin:10px 0 4px"><button type="button" class="primary" id="claim-btn-{person['key']}" onclick="analyzeClaiming('{person['key']}')">Which age is best for {html.escape(person['name'])}, based on my plan?</button></p>
<div id="claim-result-{person['key']}"></div>"""


def social_security_medicare_card_html(assumptions: dict) -> str:
    people = benefits.planner_people(assumptions)
    married = len(people) > 1 and bool(people[1]["birth_year"])
    magi_raw = assumptions.get("medicare_magi")
    magi = benefits._number(magi_raw)
    tier_text = ""
    if magi is not None:
        tier = benefits.medicare_tier(magi, married=married)
        tier_text = (
            f'<p class="status-line">At {_money(magi)} of income, you are in {benefits.MEDICARE_TABLE_YEAR} IRMAA tier '
            f'{tier["tier"] + 1} of 6: Part B {_money(tier["part_b_monthly"], cents=True)}/mo plus a Part D surcharge of '
            f'{_money(tier["part_d_surcharge"], cents=True)}/mo per person ({_money(tier["annual"])}/yr each).</p>'
        )
    planned = benefits.planned_rows(assumptions)
    status = ""
    if planned["income"] or planned["expenses"]:
        names = ", ".join(r["name"] for r in planned["income"] + planned["expenses"])
        status = f'<p class="muted">"Save &amp; apply" will create or update these rows: {html.escape(names)}.</p>'
    missing = [f"{p['name']}'s birth year" for p in people if not p["birth_year"]]
    missing_text = (
        f'<p class="status-line status-warn">Set {" and ".join(missing)} on the Will my money last? tab\'s Assumptions '
        "for the matching person's rows and tables.</p>" if missing else ""
    )

    def person_fields(p: dict) -> str:
        return (
            f'<label>{html.escape(p["name"])}: benefit at full retirement age ($/yr, today\'s dollars)'
            f'<input name="ss_benefit_{p["key"]}" type="number" step="100" placeholder="from ssa.gov" '
            f'value="{_value(assumptions, "ss_benefit_" + p["key"])}"></label>'
            f'<label>{html.escape(p["name"])}: claim at age{_claim_select("ss_claim_age_" + p["key"], p["claim_age"])}</label>'
        )

    return f"""
<details class="how-it-works card" style="padding:12px 16px;">
<summary style="font-weight:600;">Social Security &amp; Medicare planner</summary>
<p class="muted">Pick when each of you claims Social Security and see what it does to the yearly benefit; then
"Save &amp; apply" writes the result onto the tables below as ordinary rows (Social Security under Income, Medicare
under Expenses), so the money-lasts forecast, Drawdown and Legacy all pick it up. Benefits are in today's dollars and grow with
the Inflation assumption. The comparison ignores taxes, spousal and survivor benefits, and discounting. Medicare
premiums use the {benefits.MEDICARE_TABLE_YEAR} Part B/D amounts (Part B {_money(benefits.PART_B_STANDARD_MONTHLY, cents=True)}/mo)
and one income estimate; the real IRMAA rule looks at your income from two years earlier and can change each year. Add your
Part D plan and Medigap premiums under "Other monthly Medicare costs".</p>
{missing_text}
<form class="inline" id="benefits-form" onsubmit="event.preventDefault();">
  {"".join(person_fields(p) for p in people)}
  <label>Expected retirement income for Medicare (MAGI, $/yr)<input name="medicare_magi" type="number" step="1000" placeholder="e.g. 150000" value="{html.escape(str(magi_raw or ''))}"></label>
  <label>Other monthly Medicare costs per person ($)<input name="medicare_other_monthly" type="number" step="10" placeholder="Part D plan, Medigap" value="{_value(assumptions, 'medicare_other_monthly')}"></label>
  <button type="button" onclick="saveBenefits(false)">Save</button>
  <button type="button" class="primary" onclick="saveBenefits(true)">Save &amp; apply to the tables</button>
</form>
{tier_text}
{status}
{"".join(_table_html(p) for p in people)}
<script>
function analyzeClaiming(key) {{
  var btn = document.getElementById('claim-btn-' + key), out = document.getElementById('claim-result-' + key);
  var label = btn.textContent;
  btn.disabled = true; btn.textContent = 'Running your plan nine times...';
  postJSON('/api/benefits/claiming-analysis', {{person: key}}).then(function(d) {{
    var byAge = {{}}; d.rows.forEach(function(r) {{ byAge[r.age] = r; }});
    var rec = byAge[d.recommended_age], first = byAge[62], best = byAge[d.best_odds_age], chosen = d.chosen_age ? byAge[d.chosen_age] : null;
    var msg = 'For ' + d.person + ', claiming at <strong>' + rec.age + '</strong> looks best in your plan: a ' + wiPct(rec.success_rate) +
      ' chance your money lasts and a typical ending balance of ' + wiMoney(rec.median) + ', versus ' + wiPct(first.success_rate) + ' and ' + wiMoney(first.median) +
      ' if claiming at 62. It pays ' + wiMoney(rec.annual) + ' a year in today&#39;s dollars from ' + rec.start_year + '.';
    if (d.best_odds_age !== d.recommended_age) {{ msg += ' The very highest odds are at age ' + best.age + ' (' + wiPct(best.success_rate) + ').'; }}
    if (chosen && d.chosen_age !== d.recommended_age) {{ msg += ' You currently have ' + chosen.age + ' selected (' + wiPct(chosen.success_rate) + ' chance).'; }}
    if (d.rows.every(function(r) {{ return r.success_rate >= 0.99; }})) {{ msg += ' Your plan is strong enough that the claiming age barely changes whether the money lasts, so it comes down to preference: more income sooner, or a larger check later (and for couples, a larger survivor benefit).'; }}
    var rows = d.rows.map(function(r) {{
      var tags = (r.age === d.recommended_age ? ' <span class="status-ok">suggested</span>' : '') + (r.age === d.chosen_age ? ' <span class="muted">(your choice)</span>' : '');
      return '<tr' + (r.age === d.recommended_age ? ' style="font-weight:600;"' : '') + '><td>' + r.age + tags + '</td><td class="num">' + wiMoney(r.annual) + '</td><td class="num">' +
        wiPct(r.success_rate) + '</td><td class="num">' + wiMoney(r.median) + '</td><td class="num">' + wiMoney(r.p10) + '</td></tr>';
    }}).join('');
    var survivor = d.married ? '<p class="muted small">For couples, the larger benefit also becomes the surviving spouse&#39;s benefit, so delaying the higher earner&#39;s claim often matters more than this single-person comparison shows. Survivor benefits are not modelled here.</p>' : '';
    out.innerHTML = '<div class="card" style="margin:8px 0"><p style="margin-top:0">' + msg + '</p>' +
      '<table><thead><tr><th>Claim at</th><th class="num">Per year</th><th class="num">Chance money lasts</th><th class="num">Typical ending balance</th><th class="num">Cautious ending balance</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '<p style="margin:10px 0 4px"><button type="button" onclick="var s = document.querySelector(\\'[name=ss_claim_age_' + key + ']\\'); s.value = ' + d.recommended_age + '; s.scrollIntoView({{block: \\'center\\'}});">Use ' + d.recommended_age + ' in the form above</button> <span class="muted small">then Save &amp; apply</span></p>' +
      '<p class="muted small">Every age runs your whole plan on the same random markets, so only the claiming age differs. Balances are in today&#39;s dollars. Estimates, not advice: taxes on benefits, spousal benefits and health are not modelled, and your own Social Security statement has the real amounts.</p>' + survivor + '</div>';
    btn.disabled = false; btn.textContent = label;
  }}).catch(function(e) {{ out.innerHTML = '<p class="status-line status-warn">' + e.message + '</p>'; btn.disabled = false; btn.textContent = label; }});
}}
function saveBenefits(apply) {{
  var fields = {{}};
  new FormData(document.getElementById('benefits-form')).forEach(function(value, key) {{ fields[key] = value; }});
  postJSON('/api/assumptions', fields)
    .then(function() {{ return apply ? postJSON('/api/benefits/apply', {{}}) : null; }})
    .then(function() {{ location.reload(); }})
    .catch(function(e) {{ alert(e.message); }});
}}
</script>
</details>
"""
