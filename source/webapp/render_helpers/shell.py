"""Page chrome shared across every dashboard page: the nav bar, the
overall <html> shell (including the "+ Add" modal and every bit of
inline JS the pages' onclick/onchange handlers call into), and the
"Sync now" button used by the two pages that show Plaid-synced data.
"""

from __future__ import annotations

import html
import threading
from datetime import datetime

from source.common import auth_store, branding, config, db
from source.webapp.render_helpers.styles import PAGE_CSS, THEME_INIT_SCRIPT, THEME_TOGGLE_HTML
from source.webapp import explain, wording


# Eight top-level tabs. Four of them hold two related pages each (the
# NAV_GROUPS below): every page keeps its own URL -- old bookmarks and links
# still work -- and shows a small "section" row under the tab bar to hop
# between the pair. Each group's tab links to its first page.
NAV_ITEMS = (
    ("summary.html", "Summary"),
    ("asset.html", "Assets"),
    ("linked-accounts.html", "Linked Accounts"),
    ("expense.html", "Income & Expenses"),
    ("real-expenditure.html", "Spending"),
    ("monte-carlo.html", "Will my money last?"),
    ("drawdown-planning.html", "Drawdown & Legacy"),
    ("trading.html", "Trading"),
    ("setup.html", "Setup"),
)

NAV_GROUPS = (
    (("asset.html", "Assets & Debts"), ("real-estate.html", "Real Estate")),
    (("linked-accounts.html", "Accounts"), ("linked-positions.html", "Positions"), ("rebalance.html", "Risk & Suggestions")),
    (("real-expenditure.html", "Actual Spending"), ("budget-vs-actual.html", "Budget vs Actual")),
    (("drawdown-planning.html", "Drawdown Planning"), ("legacy-planning.html", "Legacy Planning")),
)


def _group_for(active: str):
    for group in NAV_GROUPS:
        if any(href == active for href, _ in group):
            return group
    return None

PAGE_SHELL = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{product_name} -- {title}</title>
<link rel="manifest" href="/manifest.json">
<link rel="icon" type="image/svg+xml" href="/icons/logo.svg">
<link rel="apple-touch-icon" href="/icons/icon-180.png">
<meta name="theme-color" content="#0071e3">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="{product_name}">
<style>{css}</style>
{theme_head_script}
</head>
<body data-current-year="{current_year}" data-view="{view_mode}" data-tour="{tour}">
<div class="hdr" style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap;">
  <div class="hdr-brand" style="display:flex; align-items:center; gap:12px;">
    <img src="/icons/logo.svg" alt="" width="84" height="84" style="border-radius:18px; flex:none;">
    <div>
      <h1 style="margin:0;">{product_name}</h1>
      <p class="brand-tagline" style="margin:2px 0 0; font-size:13px;">{product_tagline}</p>
      <p style="margin:3px 0 0; font-size:12px;"><strong>{product_headline}</strong></p>
    </div>
  </div>
  <div class="hdr-actions" style="display:flex; gap:8px; align-items:flex-start; flex-wrap:wrap; max-width:100%;">{theme_toggle_html}{logout_html}</div>
</div>
<nav>{nav}</nav>
<div id="bulk-bar" class="bulk-bar">
  <span class="bulk-count">0 selected</span>
  <button type="button" class="danger" onclick="deleteSelectedRows()">Delete selected</button>
  <button type="button" onclick="clearSelection()">Clear</button>
</div>
{body}

<button type="button" class="fab-add" onclick="openAddModal()" title="Add an asset, liability, expense, income, or property">+ Add</button>

<div id="add-modal-overlay" class="modal-overlay" hidden onclick="if (event.target === this) closeAddModal();">
  <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="add-modal-title">
    <div class="modal-header">
      <h2 id="add-modal-title" style="margin:0; font-size:16px;">Add item</h2>
      <button type="button" class="modal-close" onclick="closeAddModal()" aria-label="Close">&times;</button>
    </div>
    <p class="muted" style="margin-top:-8px;">One place to add anything to your plan -- pick a type below and its fields will appear.</p>
    <form id="add-modal-form" onsubmit="event.preventDefault(); submitAddModal(this);">
      <label class="add-kind-field">Type
        <select id="add-kind-select" onchange="updateAddModalFields()">
          <option value="asset">Asset</option>
          <option value="liability">Liability</option>
          <option value="expenses">Expense</option>
          <option value="income">Income</option>
          <option value="real_estate">Real estate property</option>
        </select>
      </label>
      <input type="hidden" name="kind" id="add-field-kind" value="asset">

      <fieldset id="add-fields-assets" class="add-fieldset field-grid">
        <label>Category<input name="category" placeholder="e.g. 401k, Liquid, Insurance"></label>
        <label>Name<input name="name" required></label>
        <label>Institution<input name="institution"></label>
        <label>Account #<input name="last4" maxlength="20"></label>
        <label>Balance<input name="balance" type="number" step="0.01" required></label>
        <label>Owner<select name="owner">{owner_options_html}</select></label>
        <label style="grid-column:1/-1;">Notes<input name="notes"></label>
      </fieldset>

      <fieldset id="add-fields-line" class="add-fieldset field-grid" hidden>
        <label>Name<input name="name" id="add-line-name" required></label>
        <label>Category<input name="category" id="add-line-category"
          oninput="autoInflateIfVariableCategory(this, document.body.dataset.currentYear)"></label>
        <label>Annual amount<input name="annual_amount" type="number" step="0.01" required></label>
        <label>Start year<input name="start_year" type="number" placeholder="optional"></label>
        <label>End year<input name="end_year" type="number" placeholder="optional"></label>
        <label>Base year<input name="base_year" type="number" placeholder="e.g. 2026"></label>
        <label style="flex-direction:row; align-items:center; gap:6px;">
          <input type="checkbox" name="inflates" value="1" style="width:auto;"> Inflates</label>
        <label style="grid-column:1/-1;">Notes<input name="notes"></label>
      </fieldset>

      <fieldset id="add-fields-realestate" class="add-fieldset field-grid" hidden>
        <label>Property<input name="name" required></label>
        <label>Purchase price<input name="purchase_price" type="number" step="0.01"></label>
        <label>Current value<input name="current_value" type="number" step="0.01" required></label>
        <label>Ownership %<input name="ownership_pct" type="number" step="0.01" value="100"></label>
        <label>Loan balance<input name="loan_balance" type="number" step="0.01"></label>
        <label>Loan ends (year)<input name="loan_end_year" type="number" step="1" placeholder="e.g. 2051"></label>
        <label>Annual income<input name="annual_income" type="number" step="0.01" placeholder="e.g. rental income"></label>
        <label style="grid-column:1/-1;">Notes<input name="notes"></label>
      </fieldset>

      <div class="modal-actions">
        <button type="button" onclick="closeAddModal()">Cancel</button>
        <button type="submit" class="primary">Add</button>
      </div>
    </form>
  </div>
</div>

<script>
function postJSON(url, body) {{
  return fetch(url, {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)}})
    .then(function(resp) {{
      return resp.json().then(function(data) {{
        if (!resp.ok || data.ok === false) {{ throw new Error(data.error || 'Request failed'); }}
        return data;
      }});
    }});
}}
var RP_TOUR = [
  {{sel: 'nav a[href="/summary.html"]', title: 'Summary', text: 'Start here. It tells you in plain words whether your money is on track.'}},
  {{sel: 'nav a[href="/asset.html"]', title: 'Assets', text: 'What you own and what you owe.'}},
  {{sel: 'nav a[href="/expense.html"]', title: 'Income & Expenses', text: 'What comes in and what goes out each year.'}},
  {{sel: 'nav a[href="/monte-carlo.html"]', title: 'Will my money last?', text: 'Your chance of the money lasting. This is also where you enter Social Security.'}},
  {{sel: '.ex-btn', title: 'The little i', text: 'Tap an i next to any title to read the full explanation.'}},
  {{sel: '#whatif-quick', title: 'What if...?', text: 'Try a change and see its effect. Nothing is saved.'}}
];
function startTour() {{
  var steps = RP_TOUR.filter(function(s) {{ var el = document.querySelector(s.sel); return el && el.offsetParent !== null; }});
  if (!steps.length) {{ return; }}
  var i = 0, box = document.createElement('div'), mark = null;
  box.id = 'rp-tour';
  box.style.cssText = 'position:absolute; z-index:100001; max-width:290px; background:var(--surface,#fff); color:var(--ink,#1d1d1f); border:1px solid var(--border,#d2d2d7); border-radius:14px; padding:14px 16px; box-shadow:0 14px 36px rgba(0,0,0,.28); font-size:14px; line-height:1.4;';
  document.body.appendChild(box);
  function done() {{
    if (mark) {{ mark.style.outline = ''; mark.style.outlineOffset = ''; }}
    box.remove();
    postJSON('/api/tour-seen', {{}}).catch(function() {{}});
  }}
  function show() {{
    if (mark) {{ mark.style.outline = ''; mark.style.outlineOffset = ''; }}
    var s = steps[i]; mark = document.querySelector(s.sel);
    mark.style.outline = '3px solid #0071e3'; mark.style.outlineOffset = '3px';
    mark.scrollIntoView({{block: 'center', behavior: 'smooth'}});
    box.innerHTML = '<div style="font-weight:700; margin-bottom:4px;">' + s.title + '</div><div>' + s.text + '</div>' +
      '<div style="display:flex; gap:8px; align-items:center; margin-top:12px;"><span class="muted small">' + (i + 1) + ' of ' + steps.length + '</span><span style="flex:1"></span>' +
      '<button type="button" id="tour-skip">Skip</button>' +
      (i > 0 ? '<button type="button" id="tour-back">Back</button>' : '') +
      '<button type="button" class="primary" id="tour-next">' + (i === steps.length - 1 ? 'Done' : 'Next') + '</button></div>';
    document.getElementById('tour-skip').onclick = done;
    if (i > 0) {{ document.getElementById('tour-back').onclick = function() {{ i--; show(); }}; }}
    document.getElementById('tour-next').onclick = function() {{ if (i === steps.length - 1) {{ done(); }} else {{ i++; show(); }} }};
    setTimeout(function() {{
      var r = mark.getBoundingClientRect(), top = r.bottom + window.scrollY + 12, left = Math.max(10, Math.min(r.left + window.scrollX, window.innerWidth - 310));
      box.style.top = top + 'px'; box.style.left = left + 'px';
    }}, 350);
  }}
  show();
}}
document.addEventListener('DOMContentLoaded', function() {{
  if (document.body.getAttribute('data-tour') === 'auto') {{ setTimeout(startTour, 900); }}
}});
function setDollarsMode(mode) {{
  postJSON('/api/dollars-mode', {{mode: mode}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});
}}
function wiPct(rate) {{ return rate >= 0.995 ? '>99%' : Math.round(rate * 100) + '%'; }}
function wiMoney(v) {{ return '$' + Math.round(v).toLocaleString('en-US'); }}
function wiDelta(a, b) {{
  var d = b - a;
  if (Math.abs(d) < 0.5) {{ return '<span class="muted">no change</span>'; }}
  return '<span class="' + (d > 0 ? 'up' : 'down') + '">' + (d > 0 ? '+' : '-') + '$' + Math.abs(Math.round(d)).toLocaleString('en-US') + '</span>';
}}
function wiPreset(spend, retire) {{
  document.getElementById('wi-spend').value = spend;
  var r = document.getElementById('wi-retire');
  if (r && !r.disabled) {{ r.value = retire; }}
  else if (retire) {{ return; }}
  runWhatIf(document.getElementById('whatif-btn'));
}}
function runWhatIf(btn) {{
  var out = document.getElementById('whatif-result');
  var r = document.getElementById('wi-retire');
  var payload = {{
    custom: true,
    spend_change_pct: document.getElementById('wi-spend').value,
    retire_shift_years: r && !r.disabled ? r.value : 0,
    expected_return_pct: document.getElementById('wi-growth').value
  }};
  btn.disabled = true; btn.textContent = 'Running...';
  postJSON('/api/what-if', payload).then(function(d) {{
    var b = d.base, w = d.whatif;
    var pts = Math.round((w.success_rate - b.success_rate) * 1000) / 10;
    var ptsHtml = Math.abs(pts) < 0.05 ? '<span class="muted">no change</span>'
      : '<span class="' + (pts > 0 ? 'up' : 'down') + '">' + (pts > 0 ? '+' : '') + pts.toFixed(1) + ' pts</span>';
    out.innerHTML = '<p class="small" style="margin:10px 0 4px"><strong>' + d.label + '</strong></p>' +
      '<table class="whatif-table"><thead><tr><th></th><th class="num">Plan as it is today</th><th class="num">Your what-if</th><th class="num">Change</th></tr></thead><tbody>' +
      '<tr><td>Chance your money lasts</td><td class="num">' + wiPct(b.success_rate) + '</td><td class="num"><strong>' + wiPct(w.success_rate) + '</strong></td><td class="num">' + ptsHtml + '</td></tr>' +
      '<tr><td>Cautious case (1 in 10 do worse)</td><td class="num">' + wiMoney(b.p10) + '</td><td class="num"><strong>' + wiMoney(w.p10) + '</strong></td><td class="num">' + wiDelta(b.p10, w.p10) + '</td></tr>' +
      '<tr><td>Typical case</td><td class="num">' + wiMoney(b.median) + '</td><td class="num"><strong>' + wiMoney(w.median) + '</strong></td><td class="num">' + wiDelta(b.median, w.median) + '</td></tr>' +
      '<tr><td>Strong case (1 in 10 do better)</td><td class="num">' + wiMoney(b.p90) + '</td><td class="num"><strong>' + wiMoney(w.p90) + '</strong></td><td class="num">' + wiDelta(b.p90, w.p90) + '</td></tr>' +
      '</tbody></table><p class="muted small" style="margin-top:0">Ending balances at the end of your plan horizon. Nothing is saved; this only compares.</p>';
    btn.disabled = false; btn.textContent = 'Compare';
  }}).catch(function(e) {{ out.innerHTML = '<p class="status-line status-warn">' + e.message + '</p>'; btn.disabled = false; btn.textContent = 'Compare'; }});
}}
function wiSay(where, html) {{ document.getElementById(where).innerHTML = html; }}
function wiQuick(btn, spend, retire) {{
  var card = document.getElementById('whatif-quick'), out = 'whatif-quick-result';
  var label = btn.textContent;
  btn.disabled = true; wiSay(out, '<span class="muted">Working it out...</span>');
  postJSON('/api/what-if', {{custom: true, spend_change_pct: spend, retire_shift_years: retire, expected_return_pct: card.getAttribute('data-growth')}}).then(function(d) {{
    var b = d.base, w = d.whatif, pts = Math.round((w.success_rate - b.success_rate) * 1000) / 10;
    var change = Math.abs(pts) < 0.05 ? 'no real change' : (pts > 0 ? 'up ' : 'down ') + Math.abs(pts).toFixed(1) + ' points';
    wiSay(out, '<strong>' + label + ':</strong> your chance of lasting goes from <strong>' + wiPct(b.success_rate) + '</strong> to <strong>' + wiPct(w.success_rate) +
      '</strong> (' + change + '). The typical ending balance goes from ' + wiMoney(b.median) + ' to ' + wiMoney(w.median) + '.');
    btn.disabled = false;
  }}).catch(function(e) {{ wiSay(out, '<span class="status-warn">' + e.message + '</span>'); btn.disabled = false; }});
}}
function wiClaim(btn, age) {{
  var out = 'whatif-quick-result';
  btn.disabled = true; wiSay(out, '<span class="muted">Running your plan for each claiming age...</span>');
  postJSON('/api/benefits/claiming-analysis', {{person: 'self'}}).then(function(d) {{
    var byAge = {{}}; d.rows.forEach(function(r) {{ byAge[r.age] = r; }});
    var now = byAge[d.chosen_age || d.recommended_age], then = byAge[age];
    wiSay(out, '<strong>Claim Social Security at ' + age + ':</strong> your chance of lasting goes from <strong>' + wiPct(now.success_rate) + '</strong> (claiming at ' + now.age +
      ') to <strong>' + wiPct(then.success_rate) + '</strong>. It pays ' + wiMoney(then.annual) + ' a year in today&#39;s dollars from ' + then.start_year + '. Change your age on the Will my money last? tab.');
    btn.disabled = false;
  }}).catch(function(e) {{ wiSay(out, '<span class="status-warn">' + e.message + '</span>'); btn.disabled = false; }});
}}
function loadSafeSpending(target, save) {{
  var el = document.getElementById('ss-text'); if (!el) {{ return; }}
  el.textContent = 'Calculating...';
  postJSON('/api/safe-spending', {{target: target, save: !!save}}).then(function(d) {{
    var pct = Math.round(d.target * 100);
    if (d.limit === 'max') {{ el.innerHTML = 'Even spending <strong>3 times</strong> your plan keeps a ' + pct + '% chance your money lasts.'; return; }}
    if (d.limit === 'min') {{ el.innerHTML = 'Even a much leaner budget does not reach a ' + pct + '% chance. See <a href="/monte-carlo.html#levers">what moves your plan most</a>.'; return; }}
    var safe = Math.round(d.safe_spending / 100) * 100, diff = safe - Math.round(d.current_spending);
    var rel = Math.abs(diff) < d.current_spending * 0.02 ? 'right about what you plan to spend'
      : wiMoney(Math.abs(diff)) + ' ' + (diff > 0 ? 'more' : 'less') + ' than the ' + wiMoney(d.current_spending) + ' you plan to spend';
    el.innerHTML = 'You could spend up to about <strong>' + wiMoney(safe) + ' a year</strong> and still have a ' + pct + '% chance your money lasts. That is ' + rel + '.';
  }}).catch(function(e) {{ el.textContent = e.message; }});
}}
document.addEventListener('DOMContentLoaded', function() {{
  var sel = document.getElementById('ss-target');
  var box = document.getElementById('ss-text');
  loadSafeSpending(sel ? parseFloat(sel.value) : parseFloat((box && box.getAttribute('data-target')) || '0.9'));
}});
var RP_GLOSSARY = {{
  'required minimum distributions': 'Money the IRS forces you to start taking out of tax-deferred accounts (401k, traditional IRA) once you reach about age 73, whether you need it or not. It is taxed as income.',
  'required minimum distribution': 'Money the IRS forces you to start taking out of tax-deferred accounts (401k, traditional IRA) once you reach about age 73, whether you need it or not. It is taxed as income.',
  'rmds': 'Money the IRS forces you to start taking out of tax-deferred accounts (401k, traditional IRA) once you reach about age 73, whether you need it or not. It is taxed as income.',
  'rmd': 'Money the IRS forces you to start taking out of tax-deferred accounts (401k, traditional IRA) once you reach about age 73, whether you need it or not. It is taxed as income.',
  'roth conversion': 'Moving money from a tax-deferred account (traditional IRA/401k) into a Roth. You pay income tax on it now, and it then grows and can be withdrawn tax-free later.',
  'roth conversions': 'Moving money from a tax-deferred account (traditional IRA/401k) into a Roth. You pay income tax on it now, and it then grows and can be withdrawn tax-free later.',
  'tax-deferred': 'Accounts like a 401k or traditional IRA: you skipped tax when you put money in, and you pay ordinary income tax when you take it out.',
  'monte carlo': 'A method that runs your plan through thousands of randomly generated market futures to see how often the money lasts. The name comes from the casino.',
  'plan horizon': 'How many years the plan looks ahead, usually to an age you are unlikely to outlive.',
  'expected return': 'The average yearly growth you assume for your investments. Real years vary a lot around it.',
  'return volatility': 'How bumpy yearly returns are. Higher means wider swings between good and bad years.',
  'drawdown': 'Taking money out of savings to live on, instead of adding to it.',
  'irmaa': 'Extra Medicare premiums charged to higher earners. A large Roth conversion can push you into a higher bracket.',
  'cost basis': 'What you originally paid for an investment. Only the gain above it is taxed when you sell.',
  'net liquid asset': 'Savings you could actually spend in retirement: investments and cash, minus debts. It leaves out your home and other things you would not sell.',
  'taxable gains': 'The share of a brokerage withdrawal that is profit rather than your original money. Only the profit is taxed.',
  'iterations': 'How many random market futures are simulated. More is smoother but slower.'
}};
function rpApplyGlossary() {{
  var terms = Object.keys(RP_GLOSSARY).sort(function(a, b) {{ return b.length - a.length; }});
  var re = new RegExp('(^|[^A-Za-z0-9-])(' + terms.join('|') + ')(?![A-Za-z0-9-])', 'i');
  var used = {{}};
  var skip = 'nav,.subnav,h1,h2,h3,button,a,input,select,textarea,option,script,style,label,summary,th,.help,svg,.bulk-bar,.tile,.label,.value';
  var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
  var hits = [], n;
  while ((n = walker.nextNode())) {{
    var el = n.parentElement;
    if (!el || el.closest(skip)) {{ continue; }}
    hits.push(n);
  }}
  hits.forEach(function(node) {{
    var m = re.exec(node.nodeValue);
    while (m) {{
      var key = m[2].toLowerCase(), base = RP_GLOSSARY[key];
      if (!used[base]) {{
        used[base] = true;
        var start = m.index + m[1].length, word = m[2];
        var after = node.splitText(start);
        var rest = after.splitText(word.length);
        var span = document.createElement('span');
        span.className = 'help'; span.tabIndex = 0; span.setAttribute('data-tip', RP_GLOSSARY[key]);
        span.textContent = word;
        after.parentNode.replaceChild(span, after);
        node = rest;
        m = re.exec(node.nodeValue);
      }} else {{
        var tail = node.nodeValue.slice(m.index + m[0].length);
        if (!tail) {{ break; }}
        node = node.splitText(m.index + m[0].length);
        m = re.exec(node.nodeValue);
      }}
    }}
  }});
}}
document.addEventListener('DOMContentLoaded', rpApplyGlossary);
function deleteCategoryRule(id) {{
  if (!confirm('Delete this category rule?')) return;
  postJSON('/api/category-rule/delete', {{id: id}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function updateCategoryRule(id, rowEl) {{
  // Setup page's per-row "Save" button on an existing Category rule --
  // that row's own <select>/<input> fields (rule_type, match_key,
  // match_mode, category) ARE the edit form (see setup.py's
  // _category_rules_card_html), so this just reads them straight off
  // the row and posts to /api/category-rule/update, which changes that
  // SAME rule in place (unlike /api/category-rule/save, which would add
  // a second rule if match_key changed) -- see source.common.db.
  // category_rules.update_category_rule for exactly why the two differ.
  postJSON('/api/category-rule/update', {{
    id: id,
    rule_type: rowEl.querySelector('[name="rule_type"]').value,
    match_key: rowEl.querySelector('[name="match_key"]').value,
    match_mode: rowEl.querySelector('[name="match_mode"]').value,
    category: rowEl.querySelector('[name="category"]').value,
    kind: rowEl.querySelector('[name="kind"]').value,
  }}).then(function(d) {{
    alert(d.recategorized + ' existing transaction' + (d.recategorized === 1 ? '' : 's') +
      ' auto-recategorized (hand-edited ones were left alone -- use the Apply all rules button for those).');
    location.reload();
  }}).catch(function(err) {{ alert(err.message); }});
}}
function applyAllCategoryRules() {{
  // Setup page's single "Apply all rules" button -- force-applies every
  // SAVED category rule (category AND Kind) to every transaction it
  // matches, hand-edited ones included; see source.common.db.
  // transactions.apply_all_category_rules. Edits typed into a row but not
  // yet saved are not applied (Save first).
  if (!confirm('Apply every saved rule to all matching transactions now, including ones you already categorized by hand?')) return;
  postJSON('/api/category-rule/apply-all', {{}})
    .then(function(d) {{
      alert(
        d.rules + ' rule' + (d.rules === 1 ? '' : 's') + ' applied -- ' +
        d.recategorized + ' category update' + (d.recategorized === 1 ? '' : 's') + ', ' +
        d.kind_applied + ' income/expense update' + (d.kind_applied === 1 ? '' : 's') + '.'
      );
      location.reload();
    }})
    .catch(function(err) {{ alert(err.message); }});
}}
function toggleCategoryRuleMatchMode(selectEl) {{
  // A Match mode only means anything for a "keyword" rule (a
  // "primary"/"detailed" rule is always an exact match on Plaid's own
  // value) -- greys out that row's own Match mode <select> the moment
  // "Match on" is switched away from "keyword", on both the add-rule
  // form and an existing rule's own edit row. Disabling it doesn't stop
  // updateCategoryRule()/the add form's own postJSON above from reading
  // its .value -- the server ignores it for a non-keyword rule anyway
  // (source.common.db.category_rules._normalize_rule always stores
  // "exact" for those), this is purely so the UI doesn't imply a choice
  // that wouldn't do anything.
  var row = selectEl.closest('tr') || selectEl.closest('form');
  var modeSelect = row ? row.querySelector('[name="match_mode"]') : null;
  if (modeSelect) modeSelect.disabled = selectEl.value !== 'keyword';
}}
function addLineItem(section, formEl) {{
  var fields = {{}};
  new FormData(formEl).forEach(function(value, key) {{ if (value !== '') fields[key] = value; }});
  postJSON('/api/line-item/add', {{section: section, fields: fields}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function refreshBulkBar() {{
  refreshCardDeleteButtons();
  var boxes = document.querySelectorAll('.row-check:checked');
  var bar = document.getElementById('bulk-bar');
  if (!bar) return;
  var n = boxes.length;
  bar.querySelector('.bulk-count').textContent = n + (n === 1 ? ' item selected' : ' items selected');
  bar.querySelector('button.danger').disabled = n === 0;
  bar.style.display = n > 0 ? 'flex' : 'none';
}}
// Per-table "Delete selected" buttons (Income & Expenses cards): shown next to the
// card's Add button as soon as one of its own rows is ticked.
function refreshCardDeleteButtons() {{
  document.querySelectorAll('.li-del').forEach(function(btn) {{
    var n = document.querySelectorAll('.row-check[data-section="' + btn.dataset.section + '"]:checked').length;
    btn.classList.toggle('on', n > 0);
    btn.textContent = 'Delete selected (' + n + ')';
  }});
}}
function toggleAllRowChecks(masterCheckbox, tableEl) {{
  var boxes = tableEl.querySelectorAll('tbody .row-check');
  boxes.forEach(function(cb) {{ cb.checked = masterCheckbox.checked; }});
  refreshBulkBar();
}}
function clearSelection() {{
  document.querySelectorAll('.row-check, .select-all-check').forEach(function(cb) {{ cb.checked = false; }});
  refreshBulkBar();
}}
function deleteSelectedRows(section) {{
  var boxes = Array.prototype.slice.call(document.querySelectorAll('.row-check:checked'));
  if (section) boxes = boxes.filter(function(cb) {{ return cb.dataset.section === section; }});
  if (!boxes.length) return;
  if (!confirm('Delete ' + boxes.length + (boxes.length === 1 ? ' selected item? ' : ' selected items? ') + "This can't be undone.")) return;
  var items = boxes.map(function(cb) {{ return {{section: cb.dataset.section, id: parseInt(cb.dataset.id, 10)}}; }});
  postJSON('/api/line-item/delete-bulk', {{items: items}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
document.addEventListener('change', function(e) {{
  if (e.target.classList.contains('row-check')) refreshBulkBar();
  if (e.target.classList.contains('select-all-check')) {{
    var table = e.target.closest('table');
    if (table) toggleAllRowChecks(e.target, table);
  }}
}});
document.addEventListener('DOMContentLoaded', refreshBulkBar);
document.addEventListener('DOMContentLoaded', function() {{
  // On a phone, nav is a horizontally-scrollable single row (see
  // styles.py's phone media query) -- with 10 tabs, most don't fit on
  // screen at once, so whichever one is active needs to be scrolled
  // into view itself, or it can land flush against the edge, half cut
  // off (looks like broken/truncated text, not "swipe for more"). A
  // no-op on desktop, where nav never scrolls in the first place.
  var activeTab = document.querySelector('nav a.active');
  if (activeTab) activeTab.scrollIntoView({{inline: 'center', block: 'nearest'}});
}});
function removePlaidItem(itemKey) {{
  if (!confirm('Unlink ' + itemKey + '? This revokes access at Plaid and removes its stored balances/holdings.')) return;
  postJSON('/api/plaid-remove', {{item_key: itemKey}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function chooseWorkbookFile(formEl) {{
  postJSON('/api/choose-file', {{}})
    .then(function(d) {{ formEl.path.value = d.path; }})
    .catch(function(err) {{ if (err.message !== 'Canceled') alert(err.message); }});
}}
function linkAccount(section, id, accountId) {{
  postJSON('/api/line-item/link-account', {{section: section, id: id, account_id: accountId}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function classifyLinkedAccount(accountId, rowEl) {{
  // The Linked Accounts page's "Classify" action -- creates the Asset
  // tab line item and links it to this Plaid account in one call (see
  // /api/line-item/classify-linked-account), instead of the user having
  // to go add a row by hand on the Assets tab first. rowEl is the small
  // classify form's own container, so its fields are read by class name
  // rather than by id (there's one of these per unlinked row).
  var kind = rowEl.querySelector('.classify-kind').value;
  var category = rowEl.querySelector('.classify-category').value.trim();
  var name = rowEl.querySelector('.classify-name').value.trim();
  if (!category) {{ alert('Pick a category for this account.'); return; }}
  if (!name) {{ alert('This account needs a name.'); return; }}
  postJSON('/api/line-item/classify-linked-account', {{account_id: accountId, kind: kind, category: category, name: name}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function updateField(section, id, field, value) {{
  var fields = {{}};
  fields[field] = value;
  postJSON('/api/line-item/update', {{section: section, id: id, fields: fields}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function updateMoneyField(section, id, field, inputEl) {{
  // Money cells show thousands commas ("1,290,000"); strip them (and a $)
  // before saving, and refuse anything that is not a number.
  var cleaned = String(inputEl.value).replace(/[$,\\s]/g, '');
  if (cleaned === '' || isNaN(Number(cleaned))) {{
    alert('Please enter a number, for example 1,290,000');
    location.reload();
    return;
  }}
  updateField(section, id, field, cleaned);
}}
function formatMoneyInputs() {{
  document.querySelectorAll('input[data-money]').forEach(function(el) {{
    el.addEventListener('focus', function() {{ el.value = el.value.replace(/,/g, ''); el.select(); }});
    el.addEventListener('blur', function() {{
      var n = Number(String(el.value).replace(/[$,\\s]/g, ''));
      if (el.value !== '' && !isNaN(n)) el.value = n.toLocaleString('en-US', {{maximumFractionDigits: 2}});
    }});
  }});
}}
document.addEventListener('DOMContentLoaded', formatMoneyInputs);
function setAccountOwner(accountId, owner) {{
  // Drawdown Planning's "Resources by source" Owner column, for a live
  // linked account that ISN'T tied to an Assets-tab row (an Asset row's
  // own Owner select goes through updateField instead) -- see
  // source.common.db.owners.
  postJSON('/api/account-owner/set', {{account_id: accountId, owner: owner}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function updateCategoryField(section, id, inputEl, currentYear) {{
  // Like updateField(), but for the Expense/Income tabs' Category column
  // specifically: switching an existing row to "Variable" (case-
  // insensitive) also turns its Inflates checkbox on and, if Base Year
  // is still blank, fills it with the plan's current year -- otherwise
  // a row you just marked Variable would silently stay flat until you
  // separately checked Inflates and typed a base year yourself.
  var value = inputEl.value;
  var fields = {{category: value}};
  var row = inputEl.closest('tr');
  if (row && (value || '').trim().toLowerCase() === 'variable') {{
    var inflatesBox = row.querySelector('input[data-field="inflates"]');
    if (inflatesBox) inflatesBox.checked = true;
    fields.inflates = 1;
    var baseYearInput = row.querySelector('input[data-field="base_year"]');
    if (baseYearInput && !baseYearInput.value) {{
      baseYearInput.value = currentYear;
      fields.base_year = currentYear;
    }}
  }}
  postJSON('/api/line-item/update', {{section: section, id: id, fields: fields}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function autoInflateIfVariableCategory(categoryInput, currentYear) {{
  // The add-form counterpart to updateCategoryField() above -- as soon
  // as you type/pick "Variable" for a new row, check Inflates and
  // prefill Base Year (if still blank) right in the form, before you
  // even submit it, so a Variable-cost row starts inflating from the
  // moment it's added.
  if ((categoryInput.value || '').trim().toLowerCase() !== 'variable') return;
  var form = categoryInput.form;
  if (!form) return;
  var inflatesBox = form.querySelector('input[name="inflates"]');
  if (inflatesBox) inflatesBox.checked = true;
  var baseYearInput = form.querySelector('input[name="base_year"]');
  if (baseYearInput && !baseYearInput.value) {{ baseYearInput.value = currentYear; }}
}}
function sortCellValue(cell) {{
  var input = cell.querySelector('input');
  if (input) {{
    var n = parseFloat(input.value);
    return isNaN(n) ? input.value.toLowerCase() : n;
  }}
  var select = cell.querySelector('select');
  if (select) {{
    var opt = select.options[select.selectedIndex];
    return opt ? opt.text.toLowerCase() : '';
  }}
  var clone = cell.cloneNode(true);
  var br = clone.querySelector('br');
  if (br) {{
    while (br.nextSibling) {{ clone.removeChild(br.nextSibling); }}
    clone.removeChild(br);
  }}
  var text = clone.textContent.replace(/\\s+/g, ' ').trim();
  var stripped = text.replace(/[^0-9.\\-]/g, '');
  if (stripped !== '' && stripped !== '-' && stripped !== '.' && /^-?[0-9]*\\.?[0-9]*$/.test(stripped)) {{
    var num = parseFloat(stripped);
    if (!isNaN(num)) return num;
  }}
  return text.toLowerCase();
}}
function _sortStorageKey(table, index) {{
  // location.pathname (not the full href) so a filter chip's hash/query
  // state never splits what's otherwise the same table's saved sort
  // into two separate keys. Most sortable tables don't carry an `id`
  // (only a couple of pages' do), so this falls back to the table's
  // position among every table.sortable on the page -- stable across
  // reloads since it's the same server-rendered template each time.
  return 'sortState::' + location.pathname + '::' + (table.id || ('t' + index));
}}
function sortTableBy(table, colIndex) {{
  var tbody = table.tBodies[0];
  if (!tbody) return;
  var rows = Array.prototype.slice.call(tbody.rows);
  var th = table.tHead.rows[0].cells[colIndex];
  var asc = th.getAttribute('data-sort-dir') !== 'asc';
  rows.sort(function(rowA, rowB) {{
    var a = sortCellValue(rowA.cells[colIndex]);
    var b = sortCellValue(rowB.cells[colIndex]);
    if (typeof a === 'number' && typeof b === 'number') {{ return asc ? a - b : b - a; }}
    a = String(a); b = String(b);
    if (a < b) return asc ? -1 : 1;
    if (a > b) return asc ? 1 : -1;
    return 0;
  }});
  rows.forEach(function(row) {{ tbody.appendChild(row); }});
  var headerCells = table.tHead.rows[0].cells;
  for (var i = 0; i < headerCells.length; i++) {{
    headerCells[i].removeAttribute('data-sort-dir');
    headerCells[i].classList.remove('sort-asc', 'sort-desc');
  }}
  th.setAttribute('data-sort-dir', asc ? 'asc' : 'desc');
  th.classList.add(asc ? 'sort-asc' : 'sort-desc');
  // Persisted so a later location.reload() (every bulk-edit action on
  // this page ends with one) can restore this exact sort instead of
  // silently reverting to the server's default row order -- a real
  // person-reported annoyance ("my sort will reset every time I select
  // and update"). Keyed per-table/per-page (see _sortStorageKey) so
  // sorting one table never affects another's remembered sort.
  try {{
    localStorage.setItem(table.dataset.sortKey, JSON.stringify({{col: colIndex, asc: asc}}));
  }} catch (e) {{ /* private-browsing / storage disabled -- sort still works, just isn't remembered */ }}
}}
function initSortableTables() {{
  var tables = document.querySelectorAll('table.sortable');
  for (var t = 0; t < tables.length; t++) {{
    (function(table, index) {{
      if (!table.tHead || !table.tHead.rows.length) return;
      table.dataset.sortKey = _sortStorageKey(table, index);
      var ths = table.tHead.rows[0].cells;
      for (var i = 0; i < ths.length; i++) {{
        (function(idx, th) {{
          if (th.textContent.trim() === '') return;
          th.classList.add('sortable-col');
          th.addEventListener('click', function() {{ sortTableBy(table, idx); }});
        }})(i, ths[i]);
      }}
      try {{
        var saved = JSON.parse(localStorage.getItem(table.dataset.sortKey) || 'null');
        if (saved && table.tHead.rows[0].cells[saved.col]) {{
          // sortTableBy toggles off whatever data-sort-dir is already on
          // the header, so pre-set it to the OPPOSITE of the saved
          // direction to land on the saved direction once it toggles.
          table.tHead.rows[0].cells[saved.col].setAttribute('data-sort-dir', saved.asc ? 'desc' : 'asc');
          sortTableBy(table, saved.col);
        }}
      }} catch (e) {{ /* no saved sort, or storage unavailable -- default row order */ }}
    }})(tables[t], t);
  }}
}}
document.addEventListener('DOMContentLoaded', initSortableTables);
var __positionsFilters = {{}};
function handlePieSegClick(el) {{
  var dim = el.dataset.dim;
  var sliceId = el.dataset.sliceId;
  var wasSelected = __positionsFilters[dim] && __positionsFilters[dim].sliceId === sliceId;
  if (wasSelected) {{
    delete __positionsFilters[dim];
  }} else {{
    __positionsFilters[dim] = {{sliceId: sliceId, values: JSON.parse(el.dataset.values)}};
  }}
  updatePieSelectionUI(dim);
  applyPositionFilters();
  applyExpenditureFilters();
  applyAccountsFilters();
}}
function handlePieSegKeydown(e, el) {{
  if (e.key === 'Enter' || e.key === ' ') {{
    e.preventDefault();
    handlePieSegClick(el);
  }}
}}
function updatePieSelectionUI(dim) {{
  var active = __positionsFilters[dim];
  var segs = document.querySelectorAll('.pie-seg[data-dim="' + dim + '"]');
  segs.forEach(function(seg) {{
    var isSelected = !!active && seg.dataset.sliceId === active.sliceId;
    seg.classList.toggle('seg-selected', isSelected);
    seg.classList.toggle('seg-dimmed', !!active && !isSelected);
    seg.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
  }});
}}
function renderFilterChips(barId, filters, onClearOne, onClearAll) {{
  // Shared by every page's own applyXFilters() (below) -- builds the
  // "Filtered by: <chip> <chip> Clear all" bar from whatever dims are
  // currently set in that page's filters object. Pulled out on its own
  // so a new filterable table only has to write the row-visibility
  // half of applyPositionFilters(), not re-implement this chip UI too.
  var bar = document.getElementById(barId);
  if (!bar) return;
  bar.innerHTML = '';
  var dims = Object.keys(filters);
  if (!dims.length) {{
    bar.style.display = 'none';
    return;
  }}
  var lead = document.createElement('span');
  lead.textContent = 'Filtered by:';
  bar.appendChild(lead);
  dims.forEach(function(dim) {{
    var f = filters[dim];
    var chip = document.createElement('span');
    chip.className = 'filter-chip';
    var text = document.createElement('span');
    var dimLabel = dim.replace(/-/g, ' ').replace(/\\b\\w/g, function(c) {{ return c.toUpperCase(); }});
    text.textContent = dimLabel + ': ' + (f.values.length > 1 ? (f.values.length + ' grouped') : f.values[0]);
    chip.appendChild(text);
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.textContent = '\\u2715';
    closeBtn.setAttribute('aria-label', 'Clear ' + dim + ' filter');
    closeBtn.onclick = function() {{ onClearOne(dim); }};
    chip.appendChild(closeBtn);
    bar.appendChild(chip);
  }});
  var clearAllBtn = document.createElement('button');
  clearAllBtn.type = 'button';
  clearAllBtn.textContent = 'Clear all';
  clearAllBtn.onclick = onClearAll;
  bar.appendChild(clearAllBtn);
  bar.style.display = 'flex';
}}
function __filtersSubset(dimNames) {{
  // Every page's applyXFilters() only owns a handful of dims (Linked
  // Positions: type/institution/industry/sector; Actual Spending:
  // expense-category/expense-month) out of the one shared
  // __positionsFilters object, since a single page load only ever sets
  // the dims its own charts declare -- this just keeps each page's own
  // filter-chip bar from listing a dim it doesn't render charts for.
  var subset = {{}};
  dimNames.forEach(function(d) {{ if (d in __positionsFilters) subset[d] = __positionsFilters[d]; }});
  return subset;
}}
function applyPositionFilters() {{
  var table = document.getElementById('linked-positions-table');
  if (!table) return;
  var dims = Object.keys(__filtersSubset(['type', 'institution', 'industry', 'sector']));
  var rows = table.tBodies[0] ? Array.prototype.slice.call(table.tBodies[0].rows) : [];
  var total = 0;
  var anyDataRow = false;
  rows.forEach(function(row) {{
    if (!('type' in row.dataset) && !('institution' in row.dataset) && !('industry' in row.dataset) && !('sector' in row.dataset)) return;  // the "no data" placeholder row
    anyDataRow = true;
    var visible = dims.every(function(dim) {{
      var f = __positionsFilters[dim];
      return f.values.indexOf(row.dataset[dim]) !== -1;
    }});
    row.style.display = visible ? '' : 'none';
    if (visible) total += parseFloat(row.dataset.marketValue) || 0;
  }});
  var totalCell = document.getElementById('linked-positions-total');
  if (totalCell && anyDataRow) {{
    totalCell.textContent = '$' + total.toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
  }}
  renderFilterChips('positions-filter-bar', __filtersSubset(['type', 'institution', 'industry', 'sector']), clearPositionFilter, clearPositionFilters);
  refreshLinkedPositionsBarCharts();
}}
function moneyShort(value) {{
  // JS mirror of source.webapp.render_helpers.formatting._money_short --
  // used by refreshLinkedPositionsBarCharts() below since that recompute
  // has to match the same "$1.2M"/"$340K" style the server-rendered bar
  // labels started with.
  var sign = value < 0 ? '-' : '';
  value = Math.abs(value || 0);
  if (value >= 1000000) return sign + '$' + (value / 1000000).toFixed(1) + 'M';
  if (value >= 1000) return sign + '$' + Math.round(value / 1000) + 'K';
  return sign + '$' + Math.round(value);
}}
function refreshLinkedPositionsBarCharts() {{
  // The Linked Positions tab's "Positions by sector"/"Positions by
  // industry" bar charts are rendered server-side from the FULL,
  // unfiltered holdings list -- picking an Institution (or Type) slice
  // above only ever filtered the table rows below it, leaving these two
  // charts showing every sector/industry across every account, not just
  // the one just selected. This recomputes each bar's value/width/label
  // (and the chart's own total) from whichever rows are currently
  // visible under every OTHER active filter (so selecting Institution
  // narrows Sector/Industry down to that institution's own holdings,
  // and vice versa), hides a bar that drops to $0 under the current
  // filter, and re-sorts the remaining bars largest-first -- with no
  // filter active this reproduces the exact server-rendered chart, so
  // there's nothing special-cased for the "no filter" state.
  var table = document.getElementById('linked-positions-table');
  if (!table) return;
  var rows = table.tBodies[0] ? Array.prototype.slice.call(table.tBodies[0].rows) : [];
  ['sector', 'industry'].forEach(function(chartDim) {{
    var bars = Array.prototype.slice.call(document.querySelectorAll('.bar-row.pie-seg[data-dim="' + chartDim + '"]'));
    if (!bars.length) return;
    var otherDims = Object.keys(__positionsFilters).filter(function(d) {{ return d !== chartDim; }});
    var values = {{}};
    bars.forEach(function(bar) {{ values[bar.dataset.sliceId] = 0; }});
    rows.forEach(function(row) {{
      if (!(chartDim in row.dataset)) return;  // the "no data" placeholder row
      var visible = otherDims.every(function(d) {{
        return __positionsFilters[d].values.indexOf(row.dataset[d]) !== -1;
      }});
      if (!visible) return;
      bars.forEach(function(bar) {{
        if (JSON.parse(bar.dataset.values).indexOf(row.dataset[chartDim]) !== -1) {{
          values[bar.dataset.sliceId] += parseFloat(row.dataset.marketValue) || 0;
        }}
      }});
    }});
    var total = 0, maxVal = 0;
    bars.forEach(function(bar) {{
      var v = values[bar.dataset.sliceId];
      total += v;
      if (v > maxVal) maxVal = v;
    }});
    bars.forEach(function(bar) {{
      var v = values[bar.dataset.sliceId];
      var pct = total > 0 ? (v / total * 100) : 0;
      var widthPct = maxVal > 0 ? Math.max(v / maxVal * 100, 1.5) : 0;
      var label = bar.querySelector('.bar-label');
      var fill = bar.querySelector('.bar-fill');
      var valueLabel = bar.querySelector('.bar-value');
      if (fill) {{
        fill.style.width = widthPct.toFixed(1) + '%';
        fill.title = (label ? label.textContent : '') + ': ' + formatSignedMoney(v) +
          ' (' + pct.toFixed(0) + '%) -- click to filter the list below';
      }}
      if (valueLabel) {{ valueLabel.textContent = moneyShort(v) + ' (' + pct.toFixed(0) + '%)'; }}
      bar.style.display = v > 0 ? '' : 'none';
    }});
    var container = bars[0].parentElement;
    bars.slice().sort(function(a, b) {{ return values[b.dataset.sliceId] - values[a.dataset.sliceId]; }})
      .forEach(function(bar) {{ container.appendChild(bar); }});
    var totalLabel = bars[0].closest('.card').querySelector('.bar-chart-total-label');
    if (totalLabel) {{ totalLabel.textContent = '\u2014 ' + moneyShort(total) + ' total'; }}
  }});
}}
var EXPENDITURE_FILTER_DIMS = ['expense-category', 'expense-month', 'income-category', 'income-month', 'kind'];
function __expenditureFilterField(dim) {{
  // 'expense-category' -> 'expenseCategory', 'income-month' ->
  // 'incomeMonth' -- the dataset property name for the row attribute
  // that dim's bar chart is actually built from (data-expense-category/
  // data-income-category/data-expense-month/data-income-month -- see
  // real_expenditure.py's _row_html). Deliberately distinct per dim,
  // NOT the shared data-category/data-month every row also carries --
  // see this function's caller for why.
  return dim.replace(/-([a-z])/g, function(_, c) {{ return c.toUpperCase(); }});
}}
function applyExpenditureFilters() {{
  // Actual Spending tab's own click-to-filter: clicking a "by
  // category" or "by month" bar segment (expense OR income) filters the
  // transaction list below to the row(s) that actually make up that
  // bar's own dollar total -- same contract as applyPositionFilters()
  // above (shares __positionsFilters/handlePieSegClick -- dims are
  // namespaced by string, "expense-"/"income-" here vs.
  // "type"/"institution"/"industry"/"sector" on Linked Positions, so
  // none of these ever collide even though they all live in the same
  // global filter state), but targets the transactions table's own
  // data-expense-category/data-income-category/data-expense-month/
  // data-income-month attributes -- one dim, one attribute -- rather
  // than the plain data-category/data-month every row carries. Those
  // two are deliberately NOT what this filters on: a row only carries
  // the split attribute for the ONE chart its own dollars were actually
  // counted toward (is_real_income, and not excluded_from_expense) --
  // clicking, say, the income-by-category chart's "mortgage" bar (built
  // from one specific unclassified inbound transaction) must not also
  // surface every OTHER "mortgage"-category row that's really an
  // excluded loan-account transfer or a counted expense -- those rows
  // simply have no data-income-category attribute at all, so they never
  // match. Has no running total to recompute.
  var table = document.getElementById('real-expenditure-table');
  if (!table) return;
  var dims = Object.keys(__filtersSubset(EXPENDITURE_FILTER_DIMS));
  var rows = table.tBodies[0] ? Array.prototype.slice.call(table.tBodies[0].rows) : [];
  var visibleCount = 0;
  rows.forEach(function(row) {{
    if (!('category' in row.dataset) && !('month' in row.dataset)) return;  // the "no transactions yet" placeholder row
    var visible = dims.every(function(dim) {{
      var f = __positionsFilters[dim];
      var field = __expenditureFilterField(dim);
      return (field in row.dataset) && f.values.indexOf(row.dataset[field]) !== -1;
    }});
    row.style.display = visible ? '' : 'none';
    if (visible) visibleCount++;
  }});
  var countEl = document.getElementById('real-expenditure-shown-count');
  if (countEl) {{
    countEl.textContent = dims.length ? ('Showing ' + visibleCount + ' of ' + rows.length + ' transactions.') : '';
  }}
  renderFilterChips('expenditure-filter-bar', __filtersSubset(EXPENDITURE_FILTER_DIMS), clearPositionFilter, clearPositionFilters);
  // Keeps the "Show: All / Income only / Expense only" buttons' active
  // state correct no matter how the 'kind' filter actually changed --
  // a direct click on one of these buttons, the filter chip's own \\u2715,
  // or "Clear all" all funnel through here.
  var activeKind = __positionsFilters['kind'] ? __positionsFilters['kind'].values[0] : '';
  ['all', 'income', 'expense'].forEach(function(k) {{
    var btn = document.getElementById('expenditure-kind-filter-' + k);
    if (btn) btn.classList.toggle('active', k === (activeKind || 'all'));
  }});
}}
function setExpenditureKindFilter(kind) {{
  // The Actual Spending page's "Show: All / Income only / Expense
  // only" buttons -- unlike every other dim on this page, 'kind' isn't
  // built from a chart click (there's no "by kind" chart), so this sets
  // __positionsFilters directly instead of going through
  // handlePieSegClick. Backed by each counted row's own data-kind
  // attribute (real_expenditure.py's _row_html -- "income" or "expense",
  // absent on an excluded row).
  if (kind) {{
    __positionsFilters['kind'] = {{sliceId: kind, values: [kind]}};
  }} else {{
    delete __positionsFilters['kind'];
  }}
  applyExpenditureFilters();
}}
function formatSignedMoney(value) {{
  // Matches source.webapp.render_helpers.formatting._money's own
  // "-$1,234.56" (sign before the dollar sign) rather than
  // toLocaleString's default "$-1,234.56" if the '$' were just
  // prepended to a negative number's own string -- matters here because
  // a credit card's balance is negative, unlike Linked Positions' market
  // values (always >= 0, so applyPositionFilters' own total recompute
  // never had to worry about this).
  var abs = Math.abs(value).toLocaleString('en-US', {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
  return (value < 0 ? '-$' : '$') + abs;
}}
function applyAccountsFilters() {{
  // Linked Accounts tab's own click-to-filter: clicking a slice of
  // either "by institution" or "by account type" donut filters the
  // accounts table below to the row(s) that make up that slice -- same
  // contract as applyPositionFilters()/applyExpenditureFilters() above
  // (dims namespaced "account-institution"/"account-type", so they
  // never collide with either of those). Also recomputes the Total row
  // from just the visible accounts, same idea as applyPositionFilters'
  // own market-value total.
  var table = document.getElementById('linked-accounts-table');
  if (!table) return;
  var dims = Object.keys(__filtersSubset(['account-institution', 'account-type']));
  var rows = table.tBodies[0] ? Array.prototype.slice.call(table.tBodies[0].rows) : [];
  var total = 0;
  var visibleCount = 0;
  var anyDataRow = false;
  rows.forEach(function(row) {{
    if (!('institution' in row.dataset) && !('accountType' in row.dataset)) return;  // the "no linked accounts" placeholder row
    anyDataRow = true;
    var visible = dims.every(function(dim) {{
      var f = __positionsFilters[dim];
      var field = dim === 'account-institution' ? 'institution' : 'accountType';
      return f.values.indexOf(row.dataset[field]) !== -1;
    }});
    row.style.display = visible ? '' : 'none';
    if (visible) {{
      total += parseFloat(row.dataset.balance) || 0;
      visibleCount++;
    }}
  }});
  var totalCell = document.getElementById('linked-accounts-balance-total');
  if (totalCell && anyDataRow) {{
    totalCell.textContent = formatSignedMoney(total);
  }}
  var countEl = document.getElementById('linked-accounts-shown-count');
  if (countEl) {{
    countEl.textContent = dims.length ? ('Showing ' + visibleCount + ' of ' + rows.length + ' accounts.') : '';
  }}
  renderFilterChips('accounts-filter-bar', __filtersSubset(['account-institution', 'account-type']), clearPositionFilter, clearPositionFilters);
}}
function clearPositionFilter(dim) {{
  delete __positionsFilters[dim];
  updatePieSelectionUI(dim);
  applyPositionFilters();
  applyExpenditureFilters();
  applyAccountsFilters();
}}
function clearPositionFilters() {{
  Object.keys(__positionsFilters).forEach(function(dim) {{
    delete __positionsFilters[dim];
    updatePieSelectionUI(dim);
  }});
  applyPositionFilters();
  applyExpenditureFilters();
  applyAccountsFilters();
}}
function refreshPositionBulkBarFor(barId, inputId) {{
  // Renamed from refreshBulkBar(barId, inputId) -- that name collided
  // with the generic, no-argument refreshBulkBar() above (both live in
  // this same shared <script>, included on every page), and a later
  // `function` declaration silently replaces an earlier one in the same
  // scope in JS. The result: this one always won, so on every page the
  // row-checkbox "Delete selected" bar (#bulk-bar, driven by the generic
  // refreshBulkBar()) never actually appeared or enabled its button --
  // checking a row's checkbox looked like it worked, but the bar stayed
  // hidden (its default CSS is display:none) because
  // document.getElementById(undefined) here returned null and bailed out
  // immediately. Deleting was never actually reachable from the UI on
  // any page, regardless of a row's source. Distinct names fix both.
  var boxes = document.querySelectorAll('.position-check:checked');
  var bar = document.getElementById(barId);
  if (!bar) return;
  var n = boxes.length;
  bar.querySelector('.bulk-count').textContent = n + (n === 1 ? ' selected' : ' selected');
  var input = document.getElementById(inputId);
  if (input) input.disabled = n === 0;
  bar.querySelectorAll('button').forEach(function(btn) {{ btn.disabled = n === 0; }});
  bar.style.display = n > 0 ? 'flex' : 'none';
}}
function refreshIndustryBulkBar() {{
  refreshPositionBulkBarFor('industry-bulk-bar', 'industry-bulk-input');
  refreshPositionBulkBarFor('sector-bulk-bar', 'sector-bulk-input');
}}
function toggleAllPositionChecks(masterCheckbox, tableEl) {{
  var boxes = tableEl.querySelectorAll('tbody .position-check');
  boxes.forEach(function(cb) {{ cb.checked = masterCheckbox.checked; }});
  refreshIndustryBulkBar();
}}
function clearPositionSelection() {{
  document.querySelectorAll('.position-check, .position-select-all').forEach(function(cb) {{ cb.checked = false; }});
  refreshIndustryBulkBar();
}}
function classifySelectedIndustry() {{
  var boxes = Array.prototype.slice.call(document.querySelectorAll('.position-check:checked'));
  if (!boxes.length) return;
  var input = document.getElementById('industry-bulk-input');
  var industry = (input.value || '').trim();
  if (!industry) {{ alert('Enter an industry to set, or use "Clear industry" to remove it.'); return; }}
  var items = boxes.map(function(cb) {{ return {{security_id: cb.dataset.securityId, ticker: cb.dataset.ticker}}; }});
  postJSON('/api/classify-industry', {{items: items, industry: industry}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function clearSelectedIndustry() {{
  var boxes = Array.prototype.slice.call(document.querySelectorAll('.position-check:checked'));
  if (!boxes.length) return;
  if (!confirm('Clear the industry classification for ' + boxes.length + (boxes.length === 1 ? ' selected position?' : ' selected positions?'))) return;
  var items = boxes.map(function(cb) {{ return {{security_id: cb.dataset.securityId, ticker: cb.dataset.ticker}}; }});
  postJSON('/api/classify-industry', {{items: items, industry: null}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function classifySelectedSector() {{
  var boxes = Array.prototype.slice.call(document.querySelectorAll('.position-check:checked'));
  if (!boxes.length) return;
  var input = document.getElementById('sector-bulk-input');
  var sector = (input.value || '').trim();
  if (!sector) {{ alert('Enter a sector to set, or use "Clear sector" to remove it.'); return; }}
  var items = boxes.map(function(cb) {{ return {{security_id: cb.dataset.securityId, ticker: cb.dataset.ticker}}; }});
  postJSON('/api/classify-sector', {{items: items, sector: sector}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function clearSelectedSector() {{
  var boxes = Array.prototype.slice.call(document.querySelectorAll('.position-check:checked'));
  if (!boxes.length) return;
  if (!confirm('Clear the manual sector override for ' + boxes.length + (boxes.length === 1 ? ' selected position?' : ' selected positions?'))) return;
  var items = boxes.map(function(cb) {{ return {{security_id: cb.dataset.securityId, ticker: cb.dataset.ticker}}; }});
  postJSON('/api/classify-sector', {{items: items, sector: null}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
document.addEventListener('change', function(e) {{
  if (e.target.classList.contains('position-check')) refreshIndustryBulkBar();
  if (e.target.classList.contains('position-select-all')) {{
    var table = e.target.closest('table');
    if (table) toggleAllPositionChecks(e.target, table);
  }}
}});
document.addEventListener('DOMContentLoaded', refreshIndustryBulkBar);
// Actual Spending tab's own checkbox + bulk-classify bars (category,
// and the excluded-from-total flag) -- same shape as the industry/
// sector bars just above, deliberately kept as its own, distinctly-
// named set of functions/listener rather than reusing
// refreshIndustryBulkBar/toggleAllPositionChecks (which hardcode the
// .position-check/.position-select-all classes): giving every bulk-bar
// family its own name is what actually prevents the kind of silent
// same-name collision the row-checkbox "Delete selected" bar once hit
// here (two different `function refreshBulkBar(...)` in this same
// shared script, the later one quietly winning) -- see
// tests.test_dashboard.test_shared_page_script_has_no_duplicate_top_level_function_names.
function refreshTransactionBulkBar() {{
  var boxes = document.querySelectorAll('.transaction-check:checked');
  var bar = document.getElementById('transaction-bulk-bar');
  if (!bar) return;
  var n = boxes.length;
  bar.querySelector('.bulk-count').textContent = n + (n === 1 ? ' selected' : ' selected');
  var input = document.getElementById('transaction-category-input');
  if (input) input.disabled = n === 0;
  bar.querySelectorAll('button').forEach(function(btn) {{ btn.disabled = n === 0; }});
  bar.style.display = n > 0 ? 'flex' : 'none';
}}
function toggleAllTransactionChecks(masterCheckbox, tableEl) {{
  var boxes = tableEl.querySelectorAll('tbody .transaction-check');
  boxes.forEach(function(cb) {{ cb.checked = masterCheckbox.checked; }});
  refreshTransactionBulkBar();
}}
function clearTransactionSelection() {{
  document.querySelectorAll('.transaction-check, .transaction-select-all').forEach(function(cb) {{ cb.checked = false; }});
  refreshTransactionBulkBar();
}}
function _selectedTransactionItems() {{
  var boxes = Array.prototype.slice.call(document.querySelectorAll('.transaction-check:checked'));
  return boxes.map(function(cb) {{ return {{transaction_id: cb.dataset.transactionId}}; }});
}}
function classifySelectedTransactions() {{
  var items = _selectedTransactionItems();
  if (!items.length) return;
  var input = document.getElementById('transaction-category-input');
  var category = (input.value || '').trim();
  if (!category) {{ alert('Enter a category to set, or use "Reset category" to go back to the automatic one.'); return; }}
  postJSON('/api/classify-transaction-category', {{items: items, category: category}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function resetSelectedTransactionCategories() {{
  var items = _selectedTransactionItems();
  if (!items.length) return;
  postJSON('/api/classify-transaction-category', {{items: items, category: ''}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function setSelectedTransactionsExcluded(excluded) {{
  var items = _selectedTransactionItems();
  if (!items.length) return;
  postJSON('/api/classify-transaction-expense-flag', {{items: items, action: excluded ? 'exclude' : 'include'}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function resetSelectedTransactionsExpenseFlag() {{
  var items = _selectedTransactionItems();
  if (!items.length) return;
  postJSON('/api/classify-transaction-expense-flag', {{items: items, action: 'reset'}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function setSelectedTransactionsIncomeKind(kind) {{
  // "Mark as income"/"Mark as expense"/"Auto-detect income/expense" --
  // sets an explicit override (plaid_categorize.is_real_income's
  // income_kind_override) that wins over the automatic category-text
  // heuristic outright, for the case that heuristic can't win: a
  // manually-retyped category that IS income but doesn't literally
  // contain the word "income" ("salary", "Rental-mp", "tax-refund" were
  // real examples). kind is 'income', 'expense', or '' (auto-detect).
  var items = _selectedTransactionItems();
  if (!items.length) return;
  postJSON('/api/classify-transaction-income-kind', {{items: items, kind: kind}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function excludeOneTransaction(transactionId) {{
  // The "Exclude this one" quick-action on a "Possible duplicate" badge
  // (see _duplicate_badge_html in real_expenditure.py) -- a one-click
  // shortcut for the exact same /api/classify-transaction-expense-flag
  // call the bulk bar's "Exclude from total" button makes, just for a
  // single transaction_id without needing to check its row first.
  postJSON('/api/classify-transaction-expense-flag', {{items: [{{transaction_id: transactionId}}], action: 'exclude'}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function categorizeSimilarTransactions(transactionId) {{
  // Actual Spending's per-row "Categorize similar" link -- turns this
  // ONE transaction's own already-set Category into a reusable keyword
  // rule (source.common.db.transactions.apply_category_rule_from_
  // transaction derives the keyword server-side from this row's own
  // merchant_name/name, the same way Setup's "Category rules" card
  // would if a person typed one by hand) and applies it immediately to
  // every other matching transaction already synced, not just future
  // ones. If this row's own category isn't what you want yet, retype
  // it first with the bulk-classify bar above, then use this.
  postJSON('/api/category-rule/apply-from-transaction', {{transaction_id: transactionId}})
    .then(function(data) {{
      alert(
        'Saved a rule: any transaction whose name/merchant contains "' + data.keyword + '" is now categorized "' +
        data.category + '" -- ' + data.recategorized + ' existing transaction' + (data.recategorized === 1 ? '' : 's') +
        ' updated, and future syncs will match it too. (Manage or remove this rule on Setup\\'s "Category rules" card.)'
      );
      location.reload();
    }})
    .catch(function(err) {{ alert(err.message); }});
}}
document.addEventListener('change', function(e) {{
  if (e.target.classList.contains('transaction-check')) refreshTransactionBulkBar();
  if (e.target.classList.contains('transaction-select-all')) {{
    var table = e.target.closest('table');
    if (table) toggleAllTransactionChecks(e.target, table);
  }}
}});
document.addEventListener('DOMContentLoaded', refreshTransactionBulkBar);
function enableTransactionsForItem(itemKey) {{
  if (!confirm('This opens Plaid Link in a new browser tab so you can re-authorize ' + itemKey + ' for transaction history. Continue?')) return;
  var btn = event.target;
  btn.disabled = true;
  btn.textContent = 'Waiting for Plaid Link in the new tab...';
  postJSON('/api/plaid-connect-transactions', {{item_key: itemKey}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); btn.disabled = false; btn.textContent = 'Enable Transactions'; }});
}}
// One consolidated "+ Add" entry point (see the fab button + modal above)
// for every kind of line item -- Asset/Liability/Expense/Income/Real
// estate -- instead of a separate add-form duplicated on each tab. All
// five kinds still go through the same generic addLineItem()/
// /api/line-item/add path each tab's own form already used; this just
// picks the right section (and, for Asset/Liability, the right `kind`)
// before calling it, and shows only the field group that kind needs.
var ADD_KIND_INFO = {{
  asset: {{section: 'assets', kind: 'asset', group: 'add-fields-assets', title: 'Add asset'}},
  liability: {{section: 'assets', kind: 'liability', group: 'add-fields-assets', title: 'Add liability'}},
  expenses: {{section: 'expenses', kind: null, group: 'add-fields-line', title: 'Add expense'}},
  income: {{section: 'income', kind: null, group: 'add-fields-line', title: 'Add income'}},
  real_estate: {{section: 'real_estate', kind: null, group: 'add-fields-realestate', title: 'Add real estate property'}},
}};
var ADD_LINE_TEXT = {{
  expenses: {{name: 'e.g. House, Utility', category: 'e.g. Fixed, Variable'}},
  income: {{name: 'e.g. Rental income, Social Security', category: 'e.g. Rental, Social Security'}},
}};
function openAddModal(presetKind) {{
  var overlay = document.getElementById('add-modal-overlay');
  var select = document.getElementById('add-kind-select');
  var form = document.getElementById('add-modal-form');
  if (!overlay || !select || !form) return;
  form.reset();
  if (presetKind && ADD_KIND_INFO[presetKind]) select.value = presetKind;
  updateAddModalFields();
  overlay.hidden = false;
}}
function closeAddModal() {{
  var overlay = document.getElementById('add-modal-overlay');
  if (overlay) overlay.hidden = true;
}}
function updateAddModalFields() {{
  var select = document.getElementById('add-kind-select');
  var info = ADD_KIND_INFO[select.value];
  if (!info) return;
  document.getElementById('add-modal-title').textContent = info.title;
  var kindInput = document.getElementById('add-field-kind');
  kindInput.value = info.kind || '';
  kindInput.disabled = !info.kind;
  document.querySelectorAll('.add-fieldset').forEach(function(fs) {{
    var active = fs.id === info.group;
    fs.hidden = !active;
    fs.querySelectorAll('input, select').forEach(function(el) {{ el.disabled = !active; }});
  }});
  if (info.group === 'add-fields-line') {{
    var text = ADD_LINE_TEXT[select.value] || {{}};
    var nameInput = document.getElementById('add-line-name');
    var catInput = document.getElementById('add-line-category');
    if (nameInput) nameInput.placeholder = text.name || '';
    if (catInput) catInput.placeholder = text.category || '';
  }}
}}
function submitAddModal(formEl) {{
  var select = document.getElementById('add-kind-select');
  var info = ADD_KIND_INFO[select.value];
  if (!info) return;
  addLineItem(info.section, formEl);
}}
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') closeAddModal();
}});
if ('serviceWorker' in navigator) {{
  // See source/webapp/static/service-worker.js's own comment for what
  // this does and (deliberately) doesn't cache -- registered here
  // rather than blocking page render on it.
  window.addEventListener('load', function() {{
    navigator.serviceWorker.register('/service-worker.js').catch(function() {{}});
  }});
}}
</script>
</body>
</html>
"""

# (gradient top, gradient bottom, SVG glyph body) for each top-level tab's
# iOS-style 3D icon tile. Glyphs are white outlines drawn on a 24x24 grid.
_NAV_ICONS = {
    "summary.html": ("#5ac8fa", "#0a63e6",
        '<rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/>'
        '<rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="13" width="7" height="7" rx="2"/>'),
    "asset.html": ("#72e38c", "#1b9a45",
        '<path d="M3 10l9-6 9 6"/><path d="M5.5 10.5v7M9.8 10.5v7M14.2 10.5v7M18.5 10.5v7"/><path d="M3 20h18"/>'),
    "linked-accounts.html": ("#60e3e8", "#0e8c9c",
        '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/>'
        '<path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
    "expense.html": ("#ffb84d", "#ee5f00",
        '<path d="M7 4v15M7 19l-3-3M7 19l3-3"/><path d="M17 20V5M17 5l-3 3M17 5l3 3"/>'),
    "real-expenditure.html": ("#ff8296", "#d71c47",
        '<rect x="3" y="5.5" width="18" height="13" rx="3"/><path d="M3 10h18M7 15h4"/>'),
    "monte-carlo.html": ("#c993ff", "#7132d6",
        '<path d="M5 12c5 0 9-6 15-7"/><path d="M5 12h15"/><path d="M5 12c5 0 9 6 15 7"/>'
        '<circle cx="5" cy="12" r="1.6" fill="#fff"/>'),
    "drawdown-planning.html": ("#8a96ff", "#3338c0",
        '<path d="M3 7l6 6 4-4 8 8"/><path d="M21 17v-5M21 17h-5"/>'),
    "trading.html": ("#ffd75e", "#d98a00",
        '<rect x="5" y="8" width="4" height="7" rx="1"/><path d="M7 5v3M7 15v4"/>'
        '<rect x="15" y="6" width="4" height="9" rx="1"/><path d="M17 3v3M17 15v3"/>'),
    "setup.html": ("#bcc1ca", "#646a76",
        '<path d="M5 7h14M5 12h14M5 17h14"/><circle cx="9" cy="7" r="2" fill="#fff"/>'
        '<circle cx="15" cy="12" r="2" fill="#fff"/><circle cx="8" cy="17" r="2" fill="#fff"/>'),
}


def _nav_icon_html(href: str) -> str:
    top, bottom, glyph = _NAV_ICONS.get(href, ("#bcc1ca", "#646a76", ""))
    return (
        f'<span class="ni" style="--c1:{top}; --c2:{bottom}">'
        f'<svg viewBox="0 0 24 24" aria-hidden="true">{glyph}</svg></span>'
    )


def _nav_html(active: str) -> str:
    group = _group_for(active)
    highlighted = group[0][0] if group else active
    return "".join(
        '<a href="/{href}"{cls}>{icon}<span class="nl">{label}</span></a>'.format(
            href=href,
            cls=' class="active"' if href == highlighted else "",
            icon=_nav_icon_html(href),
            label=html.escape(label),
        )
        for href, label in NAV_ITEMS
    )


def _subnav_html(active: str) -> str:
    """The "section" row for a tab that holds two pages; empty otherwise."""
    group = _group_for(active)
    if not group:
        return ""
    links = "".join(
        '<a href="/{href}"{cls}>{label}</a>'.format(
            href=href, cls=' class="active"' if href == active else "", label=html.escape(label),
        )
        for href, label in group
    )
    return f'<div class="subnav">{links}</div>'


def _logout_html() -> str:
    """A small "Log out" button in the page header -- clears the session
    cookie (source.webapp.dashboard's /api/logout) and sends the browser
    to the login page. Rendered only once a password actually exists
    (source.common.auth_store.is_password_set()) -- before that there's
    no session to log out of and the login gate isn't active at all, so
    showing the button would just be confusing. Built as its own string
    (not inline in PAGE_SHELL) so its literal {} in the JS below doesn't
    need doubling for PAGE_SHELL's own .format() call -- a value passed
    into .format() is substituted as-is, never re-scanned for further
    placeholders."""
    if not auth_store.is_password_set():
        return ""
    return (
        '<button type="button" style="align-self:flex-start; font-size:12px; padding:6px 12px; white-space:nowrap;" '
        "onclick=\"postJSON('/api/logout', {}).then(function() { location.href = '/login.html'; })"
        ".catch(function(e) { alert(e.message); });\">Log out</button>"
    )


_request = threading.local()


def set_request_role(role: str) -> None:
    """Called by the dashboard at the start of each request so pages can
    tell whether the person is the owner or a view-only viewer."""
    _request.role = role


def is_viewer() -> bool:
    return getattr(_request, "role", "owner") == "viewer"


_VIEWER_CSS = """<style>
html.viewer .fab-add, html.viewer #bulk-bar, html.viewer .li-del, html.viewer .modal-overlay,
html.viewer nav a[href="/setup.html"], html.viewer .subnav a[href="/setup.html"] { display: none !important; }
html.viewer td input, html.viewer td select, html.viewer td textarea, html.viewer .tile input { pointer-events: none; border-color: transparent; background: transparent; }
.viewer-banner { background: #fff4d6; color: #5c4400; border: 1px solid #f0d78a; border-radius: 10px; padding: 8px 12px; margin: 10px 0; font-size: 13px; }
</style><script>document.documentElement.classList.add('viewer');</script>"""


def _viewer_banner_html() -> str:
    if not is_viewer():
        return ""
    return (_VIEWER_CSS + '<div class="viewer-banner"><strong>View-only.</strong> You are signed in as a viewer: '
            "you can look at everything and try what-ifs, but nothing you do here is saved.</div>")


def _alert_bell_html() -> str:
    """A bell with the number of open alerts (see source.reporting.alerts);
    clicking it jumps to the Alerts card on the Summary. Hidden when there
    is nothing to look at."""
    try:
        from source.reporting import alerts

        n = alerts.count()
    except Exception:
        return ""
    if not n:
        return ""
    return (f'<a href="/summary.html#alerts" id="alert-bell" title="{n} thing(s) need a look -- open the Alerts" '
            'style="text-decoration:none"><button type="button" aria-label="Alerts" style="position:relative">'
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>'
            '<path d="M13.7 21a2 2 0 0 1-3.4 0"/></svg>'
            f'<span style="position:absolute;top:-6px;right:-6px;background:#d70015;color:#fff;border-radius:10px;'
            f'font-size:10px;font-weight:700;padding:1px 5px;line-height:1.3">{n}</span></button></a>')


def _owner_options_html() -> str:
    """<option> list for the shared "+ Add" modal's Owner dropdown -- the
    household's own names, and no second person when there isn't one."""
    return "".join(
        f'<option value="{html.escape(value)}">{html.escape(label)}</option>' for value, label in db.owner_options()
    )


# The motto ("See your future. Shape your retirement and Legacy.") lives on the
# forward-looking planning pages rather than in the global header.
_MOTTO_PAGES = frozenset({"monte-carlo.html", "legacy-planning.html", "drawdown-planning.html"})


def _motto_html(active: str) -> str:
    if active not in _MOTTO_PAGES:
        return ""
    return (
        f'<p class="motto brand-tagline" style="margin:0 0 12px; font-size:16px; font-style:italic; text-align:center;">'
        f'{html.escape(branding.PRODUCT_MOTTO)}</p>'
    )


def _demo_banner_html() -> str:
    if not config.DEMO:
        return ""
    return (
        '<div class="demo-banner"><strong>Demo mode</strong> &mdash; example household only. Nothing here is real, '
        'nothing is saved to your own plan, and no login is needed.</div>'
    )


def _header_sync_html() -> str:
    """A compact "Sync now" button in the page header (left of "Download
    plan report"), shown only once at least one Plaid item is linked.
    Same /api/plaid-sync request as the form-style button on the linked
    pages. Built as a plain string (not inside PAGE_SHELL) so its literal
    braces need no doubling for PAGE_SHELL's .format()."""
    try:
        if not db.list_plaid_items():
            return ""
    except Exception:
        return ""
    js = (
        "var b=this; b.disabled=true; b.textContent='Syncing...';"
        "postJSON('/api/plaid-sync', {}).then(function(d){"
        "alert('Synced '+d.summary.items_synced.length+' item(s): '+d.summary.accounts+' account(s), '"
        "+d.summary.holdings+' holding(s), '+d.summary.account_numbers+' full account number(s), '+d.summary.industries_classified+' industry classification(s).'+(d.summary.errors.length?' Errors: '+JSON.stringify(d.summary.errors):''));"
        "location.reload();}).catch(function(e){alert(e.message); b.disabled=false; b.textContent='Sync now';});"
    )
    return (
        '<button type="button" class="primary" id="sync-btn" '
        'title="Pull the latest balances and holdings from your linked accounts (Plaid)" '
        f'onclick="{html.escape(js, quote=True)}">Sync now</button>'
    )


def _header_wording_html() -> str:
    """The Plain / Technical wording switch, just before the Theme button. Plain
    (the default) uses everyday words; Technical keeps the full financial terms.
    It only changes the words on the page, never a calculated number."""
    plain = db.wording_mode() == "plain"
    nxt = "technical" if plain else "plain"
    label = "Wording: Plain" if plain else "Wording: Technical"
    js = (
        f"var b=this; b.disabled=true; postJSON('/api/wording-mode', {{mode: '{nxt}'}})"
        ".then(function(){location.reload();}).catch(function(e){alert(e.message); b.disabled=false;});"
    )
    title = ("Everyday words are shown. Press to switch to the full technical wording."
             if plain else "Full technical wording is shown. Press to switch to everyday words.")
    return (
        f'<button type="button" id="wording-toggle" data-mode="{"plain" if plain else "technical"}" '
        f'title="{html.escape(title)}" onclick="{html.escape(js, quote=True)}">{label}</button>'
    )


def _header_quit_html() -> str:
    """A Quit button in the page header, right after the Theme button: the Mac app has no
    window of its own to close, so this stops the program (same request as
    the Setup tab's Quit card). Always shown; asks before it quits."""
    name = html.escape(branding.PRODUCT_NAME)
    js = (
        f"if(confirm('Quit {name}? Open the app again any time; your data is kept.')){{"
        "postJSON('/api/quit',{}).then(function(){"
        f"document.body.innerHTML='<p style=\\'font-family:sans-serif;padding:40px\\'>{name} has quit. You can close this tab.</p>';"
        "}).catch(function(e){alert(e.message);});}"
    )
    return (
        '<button type="button" id="quit-btn" title="Stop the program running on this computer (your data is kept)" '
        f'onclick="{html.escape(js, quote=True)}">Quit {name}</button>'
    )


DISCLAIMER_TEXT = (
    "For planning and education only. Not financial, investment, tax or legal advice. "
    "Projections are estimates, not guarantees; talk to a qualified professional before making decisions."
)


def _disclaimer_html() -> str:
    """The one-line footer shown at the bottom of every page."""
    return (f'<p class="muted small site-disclaimer" style="margin:28px 0 70px; padding-top:10px; '
            f'border-top:1px solid var(--border, #e5e5ea); text-align:center;">{html.escape(DISCLAIMER_TEXT)} '
            f'<a href="/legal.html" style="color:inherit; text-decoration:underline;">Privacy &amp; terms</a></p>')


def _tour_state(active: str) -> str:
    """"auto" on the Summary of a set-up plan that has never seen the tour, else "off"."""
    if active != "summary.html" or db.tour_seen() or db.setup_needed():
        return "off"
    return "auto"


def _plain_targets(body: str, targets: list[list[str]]) -> list[list[str]]:
    """The "i" button list with each heading's text turned into its plain-mode
    form, so the buttons still find their headings after the words change."""
    wanted = {text for text, _key in targets}
    plain: dict[str, str] = {}
    for rx, group, kind in ((explain._TEXT_HEAD, 3, "h"), (explain._TEXT_LABEL, 2, "l")):
        for m in rx.finditer(body):
            old = explain._norm(m.group(group))
            if old in wanted:
                plain.setdefault(old, wording.plain_node_text(m.group(group), kind))
    return [[plain.get(text, text), key] for text, key in targets]


_PLAIN_SHELL: str | None = None


def _page_shell() -> str:
    """The page template. In plain mode its own words (the "+ Add" window, the
    what-if table the page script builds) are rewritten once and kept."""
    global _PLAIN_SHELL
    if not wording.is_plain():
        return PAGE_SHELL
    if _PLAIN_SHELL is None:
        _PLAIN_SHELL = wording.plain_html(PAGE_SHELL)
    return _PLAIN_SHELL


def _shell(*, title: str, active: str, body: str) -> str:
    # Threaded through as <body data-current-year="..."> so the shared "+
    # Add" modal's Category field (see PAGE_SHELL) can drive the same
    # Variable-category auto-inflate JS the Expense/Income tables' own
    # cells use, without every page having to know about that modal.
    current_year = int(db.get_assumptions().get("current_year") or datetime.now().year)
    annotated_body, explain_targets = explain.annotate(body, active)
    annotated_body, explain_extra = explain.condense(annotated_body)
    if wording.is_plain():
        # Plain wording: the "i" buttons are matched on heading text, so the
        # matching list is rebuilt from the plain headings before the page
        # text itself is rewritten.
        explain_targets = _plain_targets(annotated_body, explain_targets)
        annotated_body = wording.plain_html(annotated_body)
    return _page_shell().format(
        title=html.escape(title), css=PAGE_CSS, nav=_nav_html(active), body=_viewer_banner_html() + _demo_banner_html() + _subnav_html(active) + wording.plain_html(_motto_html(active) + explain.page_button_html(active)) + annotated_body + _disclaimer_html() + explain.assets_html(active, explain_targets, explain_extra), current_year=current_year, view_mode=db.view_mode(), tour=_tour_state(active),
        product_name=html.escape(branding.PRODUCT_NAME), product_tagline=html.escape(branding.PRODUCT_TAGLINE), product_headline=html.escape(branding.PRODUCT_HEADLINE), logout_html=_logout_html(), owner_options_html=_owner_options_html(), theme_head_script=THEME_INIT_SCRIPT, theme_toggle_html=_alert_bell_html() + _header_sync_html() + THEME_TOGGLE_HTML.replace("<!--wording-toggle-->", _header_wording_html()) + _header_quit_html(),
    )


def _sync_now_button_html(*, note: str | None = None) -> str:
    """The "Sync now" button -- pulls current balances/holdings from Plaid
    and regenerates account-balances.html/portfolio-positions.html, same
    /api/plaid-sync endpoint this used to be the Setup page's alone.
    Shared by the Summary and Linked Positions pages (the two places that
    actually show synced data) so both stay wired to the exact same
    request/response handling instead of drifting into two copies."""
    note_html = f'<p class="muted">{html.escape(note)}</p>' if note else ""
    return f"""
<form class="inline" onsubmit="event.preventDefault();
  var btn = this.querySelector('button');
  btn.disabled = true; btn.textContent = 'Syncing...';
  postJSON('/api/plaid-sync', {{}})
    .then(function(d) {{ alert('Synced ' + d.summary.items_synced.length + ' item(s): ' + d.summary.accounts + ' account(s), ' + d.summary.holdings + ' holding(s), ' + d.summary.account_numbers + ' full account number(s), ' + d.summary.industries_classified + ' industry classification(s).' + (d.summary.errors.length ? ' Errors: ' + JSON.stringify(d.summary.errors) : '')); location.reload(); }})
    .catch(function(e) {{ alert(e.message); btn.disabled = false; btn.textContent = 'Sync now'; }});">
  <button type="submit" class="primary">Sync now</button>
</form>
{note_html}
"""
