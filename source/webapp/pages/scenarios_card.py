"""The Will my money last? tab's "Saved scenarios" card: save the current
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
    var cur = null; d.results.forEach(function(r) {{ if (r.current) {{ cur = r; }} }});
    var bestRate = Math.max.apply(null, d.results.map(function(r) {{ return r.success_rate; }}));
    var pts = function(r) {{
      if (!cur || r.current) {{ return ''; }}
      var x = Math.round((r.success_rate - cur.success_rate) * 1000) / 10;
      return Math.abs(x) < 0.05 ? ' <span class="muted small">same as now</span>'
        : ' <span class="small ' + (x > 0 ? 'up' : 'down') + '">' + (x > 0 ? '+' : '') + x.toFixed(1) + ' pts vs now</span>';
    }};
    var cards = d.results.map(function(r) {{
      var best = d.results.length > 1 && r.success_rate >= bestRate - 1e-9;
      return '<div class="compare-card' + (best ? ' best' : '') + '">' +
        '<div class="nm">' + esc(r.name) + (r.current ? ' <span class="muted small">(your plan now)</span>' : '') + (best ? ' <span class="small" style="color:var(--success)">best odds</span>' : '') + '</div>' +
        '<div class="pct">' + Math.round(r.success_rate * 100) + '%</div><div class="muted small" style="margin-top:-2px">chance your money lasts' + pts(r) + '</div>' +
        '<div class="fi-bar"><i style="width:' + Math.round(r.success_rate * 100) + '%"></i></div>' +
        '<dl><dt>Typical case</dt><dd>' + money(r.median_ending_balance) + '</dd>' +
        '<dt>Cautious case</dt><dd>' + money(r.p10_ending_balance) + '</dd>' +
        '<dt>Tax (typical path)</dt><dd>' + money(r.tax_total) + '</dd>' +
        '<dt>Money runs out</dt><dd>' + (r.drawdown_depleted_year || 'Never') + '</dd></dl></div>';
    }}).join('');
    document.getElementById('scenario-compare-result').innerHTML = '<div class="compare-grid">' + cards + '</div>';
    btn.disabled = false; btn.textContent = 'Compare all scenarios';
  }}).catch(function(e) {{ alert(e.message); btn.disabled = false; btn.textContent = 'Compare all scenarios'; }});
}}
</script>
</div>
"""
