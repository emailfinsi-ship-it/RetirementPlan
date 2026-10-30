"""The "How early could I stop working?" card on the Will my money last? tab. It asks /api/earliest-retirement (a couple of seconds the
first time) which retirement year is the earliest that still keeps the chance your money lasts at the level picked under "How much can
I safely spend?", and shows the chance for the years around it. Plain text, not an f-string, because of all the script braces."""

from __future__ import annotations

from source.common import db

_HTML = """
<div class="card" id="earliest-retirement">
<h3 class="sub" style="margin-top:0">How early could I stop working?</h3>
<p id="er-text" data-target="__TARGET__" style="margin:2px 0 0">Calculating...</p>
<div id="er-table" style="overflow-x:auto"></div>
<p class="muted small" style="margin:8px 0 0">This runs your own plan again with only the retirement year changed, using the same &ldquo;chance of lasting&rdquo;
level you pick under safe spending above. Your spending, savings and income lines stay as they are, so a salary that ends in a fixed year is not
moved by this test. It checks your numbers; it is not advice.</p>
</div>
<script>
document.addEventListener('DOMContentLoaded', function () {
  var text = document.getElementById('er-text'), table = document.getElementById('er-table');
  if (!text) { return; }
  function pct(v) { return Math.round(v * 100) + '%'; }
  function when(year, age) { return '<strong>' + year + '</strong>' + (age != null ? ' (age ' + age + ')' : ''); }
  function show(d) {
    var level = pct(d.target);
    if (d.limit === 'none') {
      text.innerHTML = 'Even waiting 30 more years does not reach a ' + level + ' chance your money lasts. See <a href="/monte-carlo.html#levers">what moves your plan most</a>.';
    } else if (d.limit === 'now') {
      text.innerHTML = 'Even stopping work this year keeps at least a ' + level + ' chance your money lasts.';
    } else {
      text.innerHTML = 'The earliest you could stop working and still keep at least a ' + level + ' chance your money lasts is ' + when(d.earliest_year, d.earliest_age) + '.';
    }
    if (d.chosen_year != null && d.earliest_year != null) {
      var diff = d.chosen_year - d.earliest_year;
      text.innerHTML += ' You plan to stop in ' + d.chosen_year + (diff > 0 ? ', ' + diff + ' year' + (diff === 1 ? '' : 's') + ' after that.'
        : diff < 0 ? ', ' + (-diff) + ' year' + (diff === -1 ? '' : 's') + ' before that.' : ', the same year.');
    }
    var ages = d.birth_year != null;
    var h = '<table><thead><tr><th>Stop working in</th>' + (ages ? '<th class="num">Age</th>' : '') + '<th class="num">Chance your money lasts</th><th></th></tr></thead><tbody>';
    d.rows.forEach(function (r) {
      var tag = (r.is_earliest ? 'earliest that works' : '') + (r.is_earliest && r.is_chosen ? ', ' : '') + (r.is_chosen ? 'your plan' : '');
      var ok = r.success_rate >= d.target;
      h += '<tr' + (r.is_chosen || r.is_earliest ? ' style="font-weight:600"' : '') + '><td>' + r.year + '</td>' + (ages ? '<td class="num">' + r.age + '</td>' : '')
        + '<td class="num" style="color:var(' + (ok ? '--success' : '--danger') + ')">' + pct(r.success_rate) + '</td><td class="muted small">' + tag + '</td></tr>';
    });
    table.innerHTML = h + '</tbody></table>';
  }
  function load() {
    var sel = document.getElementById('ss-target');
    var target = sel ? parseFloat(sel.value) : parseFloat(text.getAttribute('data-target') || '0.9');
    text.textContent = 'Calculating...'; table.innerHTML = '';
    postJSON('/api/earliest-retirement', {target: target}).then(show).catch(function (e) { text.textContent = e.message; });
  }
  var sel = document.getElementById('ss-target');
  if (sel) { sel.addEventListener('change', load); }
  load();
});
</script>
"""


def earliest_retirement_html() -> str:
    return _HTML.replace("__TARGET__", f"{db.safe_spend_target():g}")
