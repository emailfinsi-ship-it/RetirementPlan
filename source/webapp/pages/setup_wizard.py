"""First-run setup wizard, shown at the top of the Setup page.

Five short steps -- who the plan is for, the dates that drive it, the
growth assumptions, where the money data comes from, done. Each step saves
through the same endpoints the rest of the app uses (/api/household,
/api/assumptions), so nothing here is a second source of truth; the wizard
is only a guided path through settings that also live on their own pages.
"""

from __future__ import annotations

import html

from source.common import branding, db
from source.webapp.render_helpers import _pct

_STEPS = ("Household", "Your dates", "Assumptions", "Your money", "Finish")


def _field_value(assumptions: dict, key: str) -> str:
    return html.escape(str(assumptions.get(key) or ""))


def _wizard_card_html() -> str:
    household = db.household()
    assumptions = db.get_assumptions()
    needed = db.setup_needed()
    done = db.setup_complete()
    spouse_checked = " checked" if household["has_spouse"] else ""
    spouse_display = "" if household["has_spouse"] else "display:none;"
    dots = "".join(
        f'<span class="wz-dot" data-dot="{i}">{i + 1}. {html.escape(label)}</span>' for i, label in enumerate(_STEPS)
    )
    if needed:
        intro = (
            f"Welcome to {html.escape(branding.PRODUCT_NAME)}. Five quick steps get your plan started -- "
            "you can change any answer later on this page or on the pages it points to."
        )
    elif done:
        intro = "Setup is finished. You can walk through the wizard again any time -- your answers are pre-filled."
    else:
        intro = "Walk through the basics step by step."
    open_attr = " open" if (needed or not done) else ""
    return f"""
<details class="card" id="wizard"{open_attr}>
<summary style="font-weight:600; font-size:16px;">Setup wizard</summary>
<p class="muted">{intro}</p>
<div class="wz-dots" style="display:flex; gap:6px; flex-wrap:wrap; margin:8px 0 14px; font-size:12px;">{dots}</div>
<style>
  .wz-dot {{ padding:3px 9px; border-radius:99px; border:1px solid var(--border, #d2d2d7); color:var(--muted, #6e6e73); }}
  .wz-dot.on {{ background:#0071e3; border-color:#0071e3; color:#fff; }}
  .wz-dot.past {{ border-color:#0071e3; color:#0071e3; }}
  .wz-step {{ display:none; }} .wz-step.on {{ display:block; }}
  .wz-nav {{ display:flex; gap:8px; margin-top:14px; align-items:center; }}
  .wz-nav .spacer {{ flex:1; }}
</style>

<div class="wz-step" data-step="0">
  <h3 style="margin-top:0">Who is this plan for?</h3>
  <p class="muted">These names appear on every page and in the Owner dropdowns. Turn the second person off for a one-person plan.</p>
  <div class="inline" style="display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end;">
    <label>First person<input id="wz-self" maxlength="40" value="{html.escape(household['self_name'])}"></label>
    <label style="flex-direction:row; align-items:center; gap:6px;"><input type="checkbox" id="wz-has-spouse" style="width:auto;"{spouse_checked}> Spouse or partner</label>
    <label id="wz-spouse-wrap" style="{spouse_display}">Their name<input id="wz-spouse" maxlength="40" value="{html.escape(household['spouse_name'])}"></label>
  </div>
</div>

<div class="wz-step" data-step="1">
  <h3 style="margin-top:0">Your dates</h3>
  <p class="muted">Birth years set when Required Minimum Distributions begin and how old everyone is in each simulated year. Retirement year is the first year you draw on savings. Leave any blank to fill in later.</p>
  <div class="inline" style="display:flex; gap:12px; flex-wrap:wrap;">
    <label><span class="wz-n1">{html.escape(household['self_name'])}</span>'s birth year<input id="wz-birth" type="number" min="1900" max="2100" step="1" value="{_field_value(assumptions, 'birth_year')}"></label>
    <label class="wz-spouse-field" style="{spouse_display}"><span class="wz-n2">{html.escape(household['spouse_name'])}</span>'s birth year<input id="wz-spouse-birth" type="number" min="1900" max="2100" step="1" value="{_field_value(assumptions, 'spouse_birth_year')}"></label>
    <label>Retirement year<input id="wz-retire" type="number" min="2000" max="2200" step="1" value="{_field_value(assumptions, 'retirement_year')}"></label>
  </div>
</div>

<div class="wz-step" data-step="2">
  <h3 style="margin-top:0">Growth assumptions</h3>
  <p class="muted">Starting points for the projections -- long-run averages, not promises. Adjust them any time on the Monte Carlo page.</p>
  <div class="inline" style="display:flex; gap:12px; flex-wrap:wrap;">
    <label>Expected return %<input id="wz-return" type="number" step="0.01" value="{_pct(assumptions, 'expected_return', 0.06)}"></label>
    <label>Inflation %<input id="wz-inflation" type="number" step="0.01" value="{_pct(assumptions, 'inflation_rate', 0.03)}"></label>
  </div>
</div>

<div class="wz-step" data-step="3">
  <h3 style="margin-top:0">Where does your money data come from?</h3>
  <p class="muted">Pick either or both -- you can do this after the wizard too.</p>
  <p><strong>Connect your accounts.</strong> Link banks and brokerages with Plaid for live balances and spending (needs your own free Plaid developer keys; they are kept only in this Mac's Keychain).</p>
  <p><button type="button" onclick="wizardGoTo('plaid-keys')">Take me to Plaid setup</button></p>
  <p><strong>Type it in yourself.</strong> Add accounts, real estate, income and expenses by hand -- no bank connection needed.</p>
  <p><a href="/asset.html"><button type="button">Open the Assets page</button></a> <a href="/expense.html"><button type="button">Open Income/Expense</button></a></p>
</div>

<div class="wz-step" data-step="4">
  <h3 style="margin-top:0">All set</h3>
  <p>Your plan is ready to look at. The Summary page shows net worth and the Monte Carlo result; everything else is a tab away.</p>
  <p class="muted">Tip: the Setup tab keeps backups, the optional login password and all of these settings -- reopen this wizard from the top of this page whenever you like.</p>
</div>

<div class="wz-nav">
  <button type="button" id="wz-back" onclick="wizardMove(-1)">Back</button>
  <span class="spacer"></span>
  <button type="button" onclick="wizardFinish(false)">Skip wizard</button>
  <button type="button" class="primary" id="wz-next" onclick="wizardMove(1)">Next</button>
</div>

<script>
(function() {{
  var last = {len(_STEPS) - 1};
  var cur = 0;
  function $(id) {{ return document.getElementById(id); }}
  function show(i) {{
    cur = i;
    document.querySelectorAll('#wizard .wz-step').forEach(function(el) {{ el.classList.toggle('on', +el.dataset.step === i); }});
    document.querySelectorAll('#wizard .wz-dot').forEach(function(el) {{
      var n = +el.dataset.dot; el.classList.toggle('on', n === i); el.classList.toggle('past', n < i);
    }});
    $('wz-back').style.visibility = i === 0 ? 'hidden' : 'visible';
    $('wz-next').textContent = i === last ? 'Finish' : 'Next';
  }}
  function syncSpouse() {{
    var on = $('wz-has-spouse').checked;
    $('wz-spouse-wrap').style.display = on ? '' : 'none';
    document.querySelectorAll('#wizard .wz-spouse-field').forEach(function(el) {{ el.style.display = on ? '' : 'none'; }});
    document.querySelectorAll('#wizard .wz-n1').forEach(function(el) {{ el.textContent = $('wz-self').value || 'Person 1'; }});
    document.querySelectorAll('#wizard .wz-n2').forEach(function(el) {{ el.textContent = $('wz-spouse').value || 'Person 2'; }});
  }}
  ['wz-has-spouse', 'wz-self', 'wz-spouse'].forEach(function(id) {{ $(id).addEventListener('input', syncSpouse); $(id).addEventListener('change', syncSpouse); }});
  function saveStep(i) {{
    if (i === 0) {{
      return postJSON('/api/household', {{self_name: $('wz-self').value, spouse_name: $('wz-spouse').value, has_spouse: $('wz-has-spouse').checked}});
    }}
    if (i === 1) {{
      var d = {{birth_year: $('wz-birth').value, retirement_year: $('wz-retire').value}};
      if ($('wz-has-spouse').checked) {{ d.spouse_birth_year = $('wz-spouse-birth').value; }}
      return postJSON('/api/assumptions', d);
    }}
    if (i === 2) {{
      return postJSON('/api/assumptions', {{expected_return_pct: $('wz-return').value, inflation_rate_pct: $('wz-inflation').value}});
    }}
    return Promise.resolve();
  }}
  window.wizardMove = function(dir) {{
    if (dir > 0 && cur === last) {{ window.wizardFinish(true); return; }}
    if (dir < 0) {{ show(cur - 1); return; }}
    saveStep(cur).then(function() {{ show(cur + 1); }}).catch(function(e) {{ alert(e.message); }});
  }};
  window.wizardFinish = function(goSummary) {{
    postJSON('/api/setup-complete', {{}}).then(function() {{
      if (goSummary) {{ location.href = '/summary.html'; }} else {{ location.reload(); }}
    }}).catch(function(e) {{ alert(e.message); }});
  }};
  window.wizardGoTo = function(id) {{
    var el = document.getElementById(id);
    if (el) {{ el.scrollIntoView({{behavior: 'smooth', block: 'start'}}); }}
  }};
  show(0);
}})();
</script>
</details>
"""
