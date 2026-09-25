"""Page chrome shared across every dashboard page: the nav bar, the
overall <html> shell (including the "+ Add" modal and every bit of
inline JS the pages' onclick/onchange handlers call into), and the
"Sync now" button used by the two pages that show Plaid-synced data.
"""

from __future__ import annotations

import html
from datetime import datetime

from source.common import db
from source.webapp.render_helpers.styles import PAGE_CSS


NAV_ITEMS = (
    ("summary.html", "Summary"),
    ("asset.html", "Asset"),
    ("linked-accounts.html", "Linked Accounts"),
    ("linked-positions.html", "Linked Positions"),
    ("expense.html", "Income/Expense"),
    ("real-estate.html", "Real Estate Analysis"),
    ("monte-carlo.html", "Monte Carlo Simulation"),
    ("setup.html", "Setup"),
)

PAGE_SHELL = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Retirement Plan -- {title}</title>
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icons/icon-180.png">
<meta name="theme-color" content="#2563eb">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Retirement Plan">
<style>{css}</style>
</head>
<body data-current-year="{current_year}">
<h1>Retirement Plan</h1>
<p class="muted">Your own retirement/asset plan -- standalone program, your own data.</p>
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
function addLineItem(section, formEl) {{
  var fields = {{}};
  new FormData(formEl).forEach(function(value, key) {{ if (value !== '') fields[key] = value; }});
  postJSON('/api/line-item/add', {{section: section, fields: fields}})
    .then(function() {{ location.reload(); }})
    .catch(function(err) {{ alert(err.message); }});
}}
function refreshBulkBar() {{
  var boxes = document.querySelectorAll('.row-check:checked');
  var bar = document.getElementById('bulk-bar');
  if (!bar) return;
  var n = boxes.length;
  bar.querySelector('.bulk-count').textContent = n + (n === 1 ? ' item selected' : ' items selected');
  bar.querySelector('button.danger').disabled = n === 0;
  bar.style.display = n > 0 ? 'flex' : 'none';
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
function deleteSelectedRows() {{
  var boxes = Array.prototype.slice.call(document.querySelectorAll('.row-check:checked'));
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
  // to go add a row by hand on the Asset tab first. rowEl is the small
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
}}
function initSortableTables() {{
  var tables = document.querySelectorAll('table.sortable');
  for (var t = 0; t < tables.length; t++) {{
    (function(table) {{
      if (!table.tHead || !table.tHead.rows.length) return;
      var ths = table.tHead.rows[0].cells;
      for (var i = 0; i < ths.length; i++) {{
        (function(idx, th) {{
          if (th.textContent.trim() === '') return;
          th.classList.add('sortable-col');
          th.addEventListener('click', function() {{ sortTableBy(table, idx); }});
        }})(i, ths[i]);
      }}
    }})(tables[t]);
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
function applyPositionFilters() {{
  var table = document.getElementById('linked-positions-table');
  var bar = document.getElementById('positions-filter-bar');
  if (!table) return;
  var dims = Object.keys(__positionsFilters);
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
  if (bar) {{
    bar.innerHTML = '';
    if (!dims.length) {{
      bar.style.display = 'none';
    }} else {{
      var lead = document.createElement('span');
      lead.textContent = 'Filtered by:';
      bar.appendChild(lead);
      dims.forEach(function(dim) {{
        var f = __positionsFilters[dim];
        var chip = document.createElement('span');
        chip.className = 'filter-chip';
        var text = document.createElement('span');
        var dimLabel = dim.charAt(0).toUpperCase() + dim.slice(1);
        text.textContent = dimLabel + ': ' + (f.values.length > 1 ? (f.values.length + ' grouped') : f.values[0]);
        chip.appendChild(text);
        var closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.textContent = '\\u2715';
        closeBtn.setAttribute('aria-label', 'Clear ' + dim + ' filter');
        closeBtn.onclick = function() {{ clearPositionFilter(dim); }};
        chip.appendChild(closeBtn);
        bar.appendChild(chip);
      }});
      var clearAllBtn = document.createElement('button');
      clearAllBtn.type = 'button';
      clearAllBtn.textContent = 'Clear all';
      clearAllBtn.onclick = clearPositionFilters;
      bar.appendChild(clearAllBtn);
      bar.style.display = 'flex';
    }}
  }}
}}
function clearPositionFilter(dim) {{
  delete __positionsFilters[dim];
  updatePieSelectionUI(dim);
  applyPositionFilters();
}}
function clearPositionFilters() {{
  Object.keys(__positionsFilters).forEach(function(dim) {{
    delete __positionsFilters[dim];
    updatePieSelectionUI(dim);
  }});
  applyPositionFilters();
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

def _nav_html(active: str) -> str:
    return "".join(
        '<a href="/{href}"{cls}>{label}</a>'.format(
            href=href,
            cls=' class="active"' if href == active else "",
            label=html.escape(label),
        )
        for href, label in NAV_ITEMS
    )

def _shell(*, title: str, active: str, body: str) -> str:
    # Threaded through as <body data-current-year="..."> so the shared "+
    # Add" modal's Category field (see PAGE_SHELL) can drive the same
    # Variable-category auto-inflate JS the Expense/Income tables' own
    # cells use, without every page having to know about that modal.
    current_year = int(db.get_assumptions().get("current_year") or datetime.now().year)
    return PAGE_SHELL.format(
        title=html.escape(title), css=PAGE_CSS, nav=_nav_html(active), body=body, current_year=current_year,
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
