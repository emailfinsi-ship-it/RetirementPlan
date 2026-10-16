"""The Monte Carlo tab's "Saved scenarios" card: save the current
assumptions under a name, load or delete one, and compare them all side by
side. The comparison runs on demand (each scenario is a full simulation),
via /api/scenarios/compare, and is drawn in the browser."""

from __future__ import annotations

import html

from source.reporting.scenarios import SCENARIO_KEYS, snapshot_assumptions


def _summary_text(values: dict) -> str:
    return ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in values.items()) or "defaults"


def saved_scenarios_card_html(scenarios: list[dict], assumptions: dict) -> str:
    rows = "".join(
        f'<tr><td>{html.escape(sc["name"])}</td>'
        f'<td class="muted" style="font-size:12px;">{html.escape(_summary_text(snapshot_assumptions(sc["assumptions"])))}</td>'
        f'<td><span class="rule-actions"><button onclick="loadScenario({sc["id"]})">Load</button>'
        f'<button class="danger" onclick="deleteScenario({sc["id"]})">Delete</button></span></td></tr>'
        for sc in scenarios
    ) or '<tr><td colspan="3" class="muted">Nothing saved yet.</td></tr>'
    compare_button = (
        '<button class="primary" id="scenario-compare-btn" style="margin:12px 0;" onclick="compareScenarios()">Compare all scenarios</button>'
        if scenarios else ""
    )
    return f"""
<div class="card" id="scenarios">
<h2 style="margin-top:0">Saved scenarios</h2>
<details class="how-it-works"><summary>How this works</summary><p class="muted">Set the Assumptions below (for example Retirement year
2035, or a 4% expected return), then save them under a name. Change them, save again under another name, and
compare. A scenario holds only the assumptions on this form plus the real estate sale settings; your Asset, Income and
Expense tables are shared by all of them. "Load" puts a saved scenario's assumptions back as the current plan.
Comparing runs each scenario's Monte Carlo and Drawdown projections, so it takes a few seconds per scenario.</p></details>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/scenarios/save', {{name: this.scenario_name.value}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Scenario name<input name="scenario_name" type="text" placeholder="e.g. Retire at 60" required></label>
  <button type="submit">Save current assumptions</button>
</form>
<table><thead><tr><th>Name</th><th>Assumptions</th><th></th></tr></thead><tbody>{rows}</tbody></table>
{compare_button}
<div id="scenario-compare-result" style="overflow-x:auto"></div>
<script>
function loadScenario(id) {{
  if (!confirm('Replace the current assumptions with this scenario?')) return;
  postJSON('/api/scenarios/load', {{id: id}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});
}}
function deleteScenario(id) {{
  if (!confirm('Delete this saved scenario?')) return;
  postJSON('/api/scenarios/delete', {{id: id}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});
}}
function compareScenarios() {{
  var btn = document.getElementById('scenario-compare-btn');
  btn.disabled = true; btn.textContent = 'Running...';
  var money = function(v) {{ return '$' + Math.round(v).toLocaleString('en-US'); }};
  var esc = function(t) {{ var d = document.createElement('div'); d.textContent = t; return d.innerHTML; }};
  postJSON('/api/scenarios/compare', {{}}).then(function(d) {{
    var rows = d.results.map(function(r) {{
      return '<tr' + (r.current ? ' style="font-weight:600;"' : '') + '><td>' + esc(r.name) + '</td>' +
        '<td class="num">' + Math.round(r.success_rate * 100) + '%</td>' +
        '<td class="num">' + money(r.median_ending_balance) + '</td>' +
        '<td class="num">' + money(r.p10_ending_balance) + '</td>' +
        '<td class="num">' + money(r.tax_total) + '</td>' +
        '<td class="num">' + money(r.drawdown_ending_total) + '</td>' +
        '<td class="num">' + (r.drawdown_depleted_year || 'Never') + '</td></tr>';
    }}).join('');
    document.getElementById('scenario-compare-result').innerHTML =
      '<table><thead><tr><th>Scenario</th><th class="num">Success rate</th><th class="num">Median ending balance</th>' +
      '<th class="num">10th percentile ending</th><th class="num">Tax (median path)</th>' +
      '<th class="num">Drawdown ending total</th><th class="num">Drawdown runs out</th></tr></thead><tbody>' + rows + '</tbody></table>';
    btn.disabled = false; btn.textContent = 'Compare all scenarios';
  }}).catch(function(e) {{ alert(e.message); btn.disabled = false; btn.textContent = 'Compare all scenarios'; }});
}}
</script>
</div>
"""
