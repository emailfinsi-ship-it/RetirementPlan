"""The Screener tab (/screener.html), next to Alpaca / IBKR / E*TRADE / Stock Analysis.

Type what you are looking for in plain English ("ETFs where MACD crossed up in the last 3 days and RSI is under 40"), or set
the filters by hand: MACD crossover, RSI, sectors, swing size in dollars or percent over a window (and today's range), price,
moving average, 52-week high / low, volume, put/call volume, rating. The typed request is read by a built-in parser (no outside
service), shown filled into the form so it can be corrected, and then run. Prices come from Alpaca or Yahoo Finance, put/call
volume from E*TRADE or Yahoo Finance. Read-only: it never places an order, and it is not advice."""

from __future__ import annotations

import html

from source.screener import universe
from source.webapp.pages import glossary
from source.webapp.render_helpers import _shell

_CATEGORIES = ("Broad market", "Dividend", "Thematic", "Commodities", "Bonds", "International", "Crypto", "Leveraged")

_CSS = glossary.CSS + """
.sc-q { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
.sc-q input[type=text] { flex:1 1 360px; min-width:240px; font-size:15px; padding:9px 12px; }
.sc-ex { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0 0; }
.sc-ex button { font-size:12px; padding:3px 10px; border-radius:999px; }
.sc-understood { margin:10px 0 0; }
.sc-chip { display:inline-block; background:var(--brand-soft); color:var(--brand-dark); border-radius:999px; padding:2px 10px; margin:2px 4px 2px 0; font-size:12px; }
.sc-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(310px, 1fr)); gap:14px 22px; margin-top:8px; }
.sc-grid fieldset { border:1px solid var(--border); border-radius:12px; padding:8px 12px 10px; margin:0; }
.sc-grid legend { font-size:12px; font-weight:700; color:var(--ink-muted); text-transform:uppercase; letter-spacing:.04em; padding:0 6px; }
.sc-grid label { display:flex; align-items:center; gap:6px; font-size:13px; margin:3px 0; }
.sc-grid .sc-row { display:flex; flex-wrap:wrap; gap:6px 10px; align-items:center; margin:4px 0; font-size:13px; }
.sc-grid input[type=number], .sc-grid input[type=text] { width:74px; }
.sc-grid input.wide { width:100%; }
.sc-sectors { display:grid; grid-template-columns:repeat(auto-fit, minmax(190px, 1fr)); gap:0 14px; }
.sc-bar { height:8px; border-radius:6px; background:var(--surface-alt); overflow:hidden; margin:8px 0 4px; }
.sc-bar > i { display:block; height:100%; width:0; background:var(--brand); transition:width .3s; }
#sc-table { width:100%; font-size:13px; }
#sc-table th.sortable { cursor:pointer; user-select:none; white-space:nowrap; }
#sc-table td.num, #sc-table th.num { text-align:right; white-space:nowrap; }
#sc-table td.why { font-size:11px; color:var(--ink-muted); min-width:220px; max-width:340px; }
.sc-out { overflow-x:auto; }
"""


def _check(name: str, value: str, label: str, checked: bool = False) -> str:
    return f'<label><input type="checkbox" name="{name}" value="{html.escape(value, quote=True)}"{" checked" if checked else ""}> {html.escape(label)}</label>'


_BODY = """
<h2 style="margin-top:0">Screener</h2>
<p class="muted">Find stocks and ETFs that match what you describe. Type it in plain English or set the filters yourself. Prices come from
Alpaca or Yahoo Finance, put/call volume from E*TRADE or Yahoo Finance. It only looks; it never places an order, and none of it is advice.</p>

<div class="card">
  <div class="sc-q">
    <input type="text" id="sc-text" placeholder="e.g. ETFs where MACD crossed up in the last 3 days, RSI under 40, moved 5% this week" autocomplete="off">
    <button type="button" class="primary" id="sc-find">Find</button>
  </div>
  <div class="sc-ex" id="sc-examples"></div>
  <p class="sc-understood" id="sc-understood" hidden></p>
  <p class="muted small" id="sc-sources"></p>
</div>

<details class="card fold" id="sc-filters" open>
<summary><h3 style="margin:0;display:inline">Filters</h3> <span class="muted small">(your request fills these in; change anything, then press Run screen)</span></summary>
<form id="sc-form" onsubmit="event.preventDefault(); scRun();">
<div class="sc-grid">
  <fieldset><legend>Scan</legend>
    <label><input type="checkbox" name="universe" value="market" checked> S&amp;P 500, big stocks and popular ETFs</label>
    <label><input type="checkbox" name="universe" value="holdings"> My holdings (linked accounts)</label>
    <label><input type="checkbox" name="universe" value="watchlist"> My watchlist</label>
    <div class="sc-row"><span>Only these tickers</span><input type="text" class="wide" name="tickers" placeholder="AAPL, MSFT, QQQ"></div>
    <div class="sc-row"><label><input type="checkbox" name="assets" value="stock" checked> Stocks</label><label><input type="checkbox" name="assets" value="etf" checked> ETFs</label></div>
  </fieldset>
  <fieldset><legend>Theme and industry</legend>
    <div class="sc-row"><select name="theme"><option value="">Any theme</option>__THEMES__</select></div>
    <div class="sc-row"><input type="text" class="wide" name="industries" placeholder="industry words, e.g. Semiconductor, Bank"></div>
  </fieldset>
  <fieldset><legend><span class="has-tip" data-term="macd">MACD</span></legend>
    <div class="sc-row"><select name="macd"><option value="">Any</option><option value="bullish">Bullish crossover</option><option value="bearish">Bearish crossover</option><option value="any">Crossover either way</option><option value="above">Above signal line</option><option value="below">Below signal line</option></select></div>
    <div class="sc-row"><span>crossed within the last</span><input type="number" name="macd_days" min="1" max="60" value="5"><span>days</span></div>
  </fieldset>
  <fieldset><legend><span class="has-tip" data-term="rsi">RSI</span></legend>
    <div class="sc-row"><span>from</span><input type="number" name="rsi_min" min="0" max="100" step="1" placeholder="0"><span>to</span><input type="number" name="rsi_max" min="0" max="100" step="1" placeholder="100"></div>
    <div class="sc-row"><button type="button" class="small" onclick="scRsi(0,30)">Oversold (&le;30)</button><button type="button" class="small" onclick="scRsi(70,100)">Overbought (&ge;70)</button></div>
  </fieldset>
  <fieldset><legend><span class="has-tip" data-term="swing">Swing</span> (price moved by at least)</legend>
    __SWING1__
    __SWING2__
    <div class="sc-row"><span>Today&rsquo;s high-to-low range at least</span><input type="number" name="r_pct" min="0" step="0.1" placeholder="%"><span>%</span><input type="number" name="r_usd" min="0" step="0.5" placeholder="$"><span>$</span></div>
  </fieldset>
  <fieldset><legend>Price and trend</legend>
    <div class="sc-row"><span>Price from</span><input type="number" name="price_min" min="0" step="0.01" placeholder="$"><span>to</span><input type="number" name="price_max" min="0" step="0.01" placeholder="$"></div>
    <div class="sc-row"><select name="sma"><option value="">Any average</option><option value="above:20">Above 20-day average</option><option value="below:20">Below 20-day average</option><option value="above:50">Above 50-day average</option><option value="below:50">Below 50-day average</option><option value="above:200">Above 200-day average</option><option value="below:200">Below 200-day average</option></select></div>
    <div class="sc-row"><select name="near"><option value="">Any 52-week position</option><option value="high">Near 52-week high</option><option value="low">Near 52-week low</option></select><span>within</span><input type="number" name="near_pct" min="0" max="100" step="0.5" value="5"><span>%</span></div>
  </fieldset>
  <fieldset><legend><span class="has-tip" data-term="volume">Volume</span> and <span class="has-tip" data-term="putcall">put/call</span></legend>
    <div class="sc-row"><span>Volume at least</span><input type="number" name="vol" min="0" step="0.1" placeholder="x"><span>&times; its 20-day average</span></div>
    <div class="sc-row"><span>Put/call volume from</span><input type="number" name="pc_min" min="0" step="0.05"><span>to</span><input type="number" name="pc_max" min="0" step="0.05"></div>
    <div class="muted small">Put/call is read for the best 60 matches only, so keep the other filters tight.</div>
  </fieldset>
  <fieldset><legend><span class="has-tip" data-term="rating">Rating</span> and results</legend>
    <div class="sc-row"><select name="rating"><option value="">Any rating</option><option value="buy">Buy or Strong Buy</option><option value="sell">Sell or Strong Sell</option></select></div>
    <div class="sc-row"><span>Show up to</span><input type="number" name="limit" min="1" max="300" value="50"><span>sorted by</span>
      <select name="sort"><option value="change">Biggest move today</option><option value="move">Biggest move this week</option><option value="rsi">Lowest RSI</option><option value="volume">Highest volume</option><option value="macd">Newest MACD cross</option><option value="putcall">Highest put/call</option><option value="symbol">Symbol</option></select></div>
  </fieldset>
</div>
<fieldset style="margin-top:14px; border:1px solid var(--border); border-radius:12px; padding:8px 12px;"><legend style="font-size:12px; font-weight:700; color:var(--ink-muted); text-transform:uppercase; letter-spacing:.04em; padding:0 6px;">Sectors (none ticked = all)</legend>
  <div class="sc-sectors">__SECTORS__</div>
  <div class="muted small" style="margin-top:6px;">ETFs: sector funds follow the sector above; other ETFs are grouped as</div>
  <div class="sc-sectors">__CATEGORIES__</div>
</fieldset>
<p style="margin-top:12px;"><button type="submit" class="primary" id="sc-run">Run screen</button> <button type="button" onclick="scClear()">Clear filters</button></p>
</form>
</details>

<div class="card" id="sc-result-card" hidden>
  <div id="sc-progress" hidden><div class="sc-bar"><i id="sc-bar"></i></div><div class="muted small"><span id="sc-stage"></span> <button type="button" class="small" onclick="scCancel()">Cancel</button></div></div>
  <div id="sc-summary" class="status-line"></div>
  <p id="sc-actions" class="small" hidden><button type="button" onclick="scLoadOptions()" id="sc-opt-btn">Load put/call volume for these rows</button> <span class="muted" id="sc-opt-note"></span></p>
  <div class="sc-out"><table id="sc-table"></table></div>
</div>
"""

_JS = r"""
<script>
__GLOSSARY__
(function () {
  var $ = function (id) { return document.getElementById(id); }, F = $('sc-form'), job = null, timer = null, rows = [], sortKey = null, sortDir = 1, CFG = null;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function num(v) { return v === '' || v == null ? null : Number(v); }
  function checked(name) { return Array.prototype.slice.call(F.querySelectorAll('input[name=' + name + ']:checked')).map(function (e) { return e.value; }); }
  function setChecked(name, values) { Array.prototype.forEach.call(F.querySelectorAll('input[name=' + name + ']'), function (e) { e.checked = values.indexOf(e.value) >= 0; }); }
  Array.prototype.forEach.call(document.querySelectorAll('[data-term]'), function (el) {
    var attrs = window.termAttrs(el.getAttribute('data-term')); var tmp = document.createElement('div'); tmp.innerHTML = '<i' + attrs + '></i>';
    Array.prototype.forEach.call(tmp.firstChild.attributes, function (a) { el.setAttribute(a.name, a.value); });
  });

  function swingFrom(prefix) {
    var pct = num(F['s' + prefix + '_pct'].value), usd = num(F['s' + prefix + '_usd'].value);
    return (pct || usd) ? {kind: 'move', window: F['s' + prefix + '_win'].value, direction: F['s' + prefix + '_dir'].value, pct: pct, usd: usd} : null;
  }
  function readFilters() {
    var f = {assets: checked('assets'), universe: checked('universe'), tickers: F.tickers.value, sectors: checked('sector'), theme: F.theme.value,
      industries: F.industries.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean), limit: num(F.limit.value) || 50, sort: F.sort.value,
      rating: F.rating.value, volume_ratio_min: num(F.vol.value), swing: [], macd: null, rsi: null, price: null, sma: null, near_52w: null, put_call: null};
    var m = F.macd.value, days = num(F.macd_days.value) || 5;
    if (m === 'above' || m === 'below') { f.macd = {state: m}; } else if (m) { f.macd = {cross: m, within_days: days}; }
    if (F.rsi_min.value !== '' || F.rsi_max.value !== '') { f.rsi = {min: num(F.rsi_min.value), max: num(F.rsi_max.value)}; }
    [swingFrom('1'), swingFrom('2')].forEach(function (s) { if (s) { f.swing.push(s); } });
    var rp = num(F.r_pct.value), ru = num(F.r_usd.value); if (rp || ru) { f.swing.push({kind: 'range', window: '1d', direction: 'either', pct: rp, usd: ru}); }
    if (F.price_min.value !== '' || F.price_max.value !== '') { f.price = {min: num(F.price_min.value), max: num(F.price_max.value)}; }
    if (F.sma.value) { var p = F.sma.value.split(':'); f.sma = {relation: p[0], window: Number(p[1])}; }
    if (F.near.value) { f.near_52w = {side: F.near.value, within_pct: num(F.near_pct.value) || 5}; }
    if (F.pc_min.value !== '' || F.pc_max.value !== '') { f.put_call = {min: num(F.pc_min.value), max: num(F.pc_max.value)}; }
    return f;
  }
  function fillForm(f) {
    setChecked('assets', f.assets); setChecked('universe', f.universe); setChecked('sector', f.sectors);
    F.tickers.value = (f.tickers || []).join(', '); F.theme.value = f.theme || ''; F.industries.value = (f.industries || []).join(', ');
    F.limit.value = f.limit || 50; F.sort.value = f.sort || 'change'; F.rating.value = f.rating || ''; F.vol.value = f.volume_ratio_min || '';
    var m = f.macd; F.macd.value = !m ? '' : m.state ? m.state : m.cross; F.macd_days.value = m && m.within_days ? m.within_days : 5;
    F.rsi_min.value = f.rsi && f.rsi.min != null ? f.rsi.min : ''; F.rsi_max.value = f.rsi && f.rsi.max != null ? f.rsi.max : '';
    ['1', '2'].forEach(function (k) { F['s' + k + '_pct'].value = ''; F['s' + k + '_usd'].value = ''; });
    F.r_pct.value = ''; F.r_usd.value = '';
    var i = 0;
    (f.swing || []).forEach(function (s) {
      if (s.kind === 'range') { F.r_pct.value = s.pct || ''; F.r_usd.value = s.usd || ''; return; }
      i += 1; if (i > 2) { return; }
      F['s' + i + '_win'].value = s.window; F['s' + i + '_dir'].value = s.direction; F['s' + i + '_pct'].value = s.pct || ''; F['s' + i + '_usd'].value = s.usd || '';
    });
    F.price_min.value = f.price && f.price.min != null ? f.price.min : ''; F.price_max.value = f.price && f.price.max != null ? f.price.max : '';
    F.sma.value = f.sma ? f.sma.relation + ':' + f.sma.window : '';
    F.near.value = f.near_52w ? f.near_52w.side : ''; F.near_pct.value = f.near_52w ? f.near_52w.within_pct : 5;
    F.pc_min.value = f.put_call && f.put_call.min != null ? f.put_call.min : ''; F.pc_max.value = f.put_call && f.put_call.max != null ? f.put_call.max : '';
  }
  function showUnderstood(list, msg) {
    var el = $('sc-understood'); el.hidden = false;
    el.innerHTML = list && list.length ? '<strong>I looked for:</strong> ' + list.map(function (x) { return '<span class="sc-chip">' + esc(x) + '</span>'; }).join('') +
      ' <span class="muted small">Check the filters below, change what is off, and press Run screen.</span>' : '<span class="status-warn">' + esc(msg || 'No filters set.') + '</span>';
  }
  window.scRsi = function (lo, hi) { F.rsi_min.value = lo; F.rsi_max.value = hi; };
  window.scClear = function () { fillForm({assets: ['stock', 'etf'], universe: ['market'], sectors: [], tickers: [], limit: 50, sort: 'change', swing: []}); $('sc-understood').hidden = true; };

  function find() {
    var text = $('sc-text').value.trim(); if (!text) { $('sc-text').focus(); return; }
    postJSON('/api/screener/parse', {text: text}).then(function (r) {
      fillForm(r.filters); showUnderstood(r.understood, r.message);
      if (r.understood && r.understood.length) { run(r.filters); }
    }).catch(function (e) { showUnderstood([], e.message); });
  }
  $('sc-find').onclick = find;
  $('sc-text').addEventListener('keydown', function (ev) { if (ev.key === 'Enter') { ev.preventDefault(); find(); } });

  function run(f) {
    f = f || readFilters(); stopTimer(); rows = [];
    $('sc-result-card').hidden = false; $('sc-table').innerHTML = ''; $('sc-actions').hidden = true; $('sc-summary').textContent = 'Starting…';
    $('sc-progress').hidden = false; $('sc-bar').style.width = '2%'; $('sc-run').disabled = true;
    postJSON('/api/screener/run', {filters: f}).then(function (r) {
      job = r.job; if (!$('sc-understood').innerHTML) { showUnderstood(r.understood); }
      timer = setInterval(poll, 1000); poll();
    }).catch(function (e) { $('sc-progress').hidden = true; $('sc-summary').innerHTML = '<span class="status-warn">' + esc(e.message) + '</span>'; $('sc-run').disabled = false; });
  }
  window.scRun = function () { run(); };
  function stopTimer() { if (timer) { clearInterval(timer); timer = null; } }
  window.scCancel = function () { if (job) { postJSON('/api/screener/cancel', {job: job}); } };
  function poll() {
    postJSON('/api/screener/status', {job: job}).then(function (s) {
      var pct = s.total ? Math.round(s.done / s.total * 100) : 3;
      $('sc-bar').style.width = Math.max(3, pct) + '%'; $('sc-stage').textContent = s.stage + (s.total ? ' (' + s.done + ' of ' + s.total + ')' : '') + ' · ' + s.seconds + 's';
      if (s.state === 'running') { return; }
      stopTimer(); $('sc-progress').hidden = true; $('sc-run').disabled = false;
      if (s.state === 'error') { $('sc-summary').innerHTML = '<span class="status-warn">' + esc(s.error) + '</span>'; return; }
      done(s.result, s.state === 'cancelled');
    }).catch(function (e) { stopTimer(); $('sc-progress').hidden = true; $('sc-run').disabled = false; $('sc-summary').innerHTML = '<span class="status-warn">' + esc(e.message) + '</span>'; });
  }
  function fmt(n, d) { return n == null ? '--' : Number(n).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d}); }
  function pct(n) { return n == null ? '<span class="muted">--</span>' : '<span class="' + (n >= 0 ? 'qp-up' : 'qp-down') + '">' + (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%</span>'; }
  function done(res, cancelled) {
    rows = res.rows; sortKey = null;
    var src = res.sources || {}, from = Object.keys(src).map(function (k) { return src[k] + ' from ' + (k === 'alpaca' ? 'Alpaca' : 'Yahoo Finance'); }).join(', ');
    $('sc-summary').innerHTML = (cancelled ? 'Stopped. ' : '') + '<strong>' + res.matched + '</strong> match' + (res.matched === 1 ? '' : 'es') + ' out of ' + res.scanned + ' scanned' +
      (res.no_data ? ' (' + res.no_data + ' had too little price history)' : '') + (res.truncated ? '; showing the first ' + rows.length : '') + (from ? '. Prices: ' + from : '') +
      (res.options_capped ? '. Put/call was read for the best ' + res.options_checked + ' matches only.' : '') + '.';
    $('sc-actions').hidden = !rows.length || rows.some(function (r) { return r.put_call; });
    $('sc-opt-note').textContent = '';
    draw();
  }
  var COLS = [['symbol', 'Symbol', true], ['type', 'Type'], ['sector', 'Sector'], ['price', 'Price'], ['change_pct', 'Today'], ['move_1w', 'Week'], ['move_1m', 'Month'],
    ['rsi', 'RSI', false, 'rsi'], ['macd_ago', 'MACD', false, 'macd'], ['volume_ratio', 'Volume vs avg', false, 'volume'], ['pc', 'Put/call', false, 'putcall'], ['rating', 'Rating', false, 'rating'], ['why', 'Why it matched']];
  function val(r, k) { return k === 'pc' ? (r.put_call ? r.put_call.ratio : null) : k === 'macd_ago' ? (r.macd_ago == null ? null : (r.macd_cross === 'bullish' ? 1 : -1) / (1 + r.macd_ago)) : r[k]; }
  function draw() {
    var list = rows.slice();
    if (sortKey) { list.sort(function (a, b) { var x = val(a, sortKey), y = val(b, sortKey); if (x == null && y == null) { return 0; } if (x == null) { return 1; } if (y == null) { return -1; } return (x < y ? -1 : x > y ? 1 : 0) * sortDir; }); }
    var head = COLS.map(function (c) {
      var t = c[3] ? '<span class="has-tip"' + window.termAttrs(c[3]) + '>' + c[1] + '</span>' : c[1];
      var sortable = c[0] !== 'why';
      return '<th class="' + (c[0] === 'symbol' || c[0] === 'type' || c[0] === 'sector' || c[0] === 'why' || c[0] === 'rating' ? '' : 'num') + (sortable ? ' sortable' : '') + '"' + (sortable ? ' onclick="scSort(\'' + c[0] + '\')"' : '') + '>' + t + (sortKey === c[0] ? (sortDir > 0 ? ' ▲' : ' ▼') : '') + '</th>';
    }).join('') + '<th></th>';
    var body = list.map(function (r) {
      var macd = r.macd_state == null ? '<span class="muted">--</span>' : r.macd_cross && r.macd_ago != null && r.macd_ago <= 10
        ? '<span class="' + (r.macd_cross === 'bullish' ? 'qp-up' : 'qp-down') + '">' + (r.macd_cross === 'bullish' ? '▲ Bullish' : '▼ Bearish') + ' ' + (r.macd_ago === 0 ? 'today' : r.macd_ago + 'd ago') + '</span>'
        : '<span class="' + (r.macd_state === 'above' ? 'qp-up' : 'qp-down') + '">' + (r.macd_state === 'above' ? '▲ Above' : '▼ Below') + '</span>';
      var pc = r.put_call ? '<span title="' + fmt(r.put_call.put_volume, 0) + ' puts / ' + fmt(r.put_call.call_volume, 0) + ' calls (' + esc(r.put_call.source || '') + ')">' + (r.put_call.ratio == null ? '--' : Number(r.put_call.ratio).toFixed(2)) + '</span>' : '<span class="muted">--</span>';
      return '<tr><td><a href="/stock-analysis.html?symbol=' + encodeURIComponent(r.symbol) + '" title="' + esc(r.name) + '"><strong>' + esc(r.symbol) + '</strong></a><div class="muted small">' + esc(r.name) + '</div></td>' +
        '<td>' + (r.type === 'etf' ? 'ETF' : 'Stock') + '</td><td>' + esc(r.sector || '') + '</td><td class="num">$' + fmt(r.price, 2) + '</td><td class="num">' + pct(r.change_pct) + '</td><td class="num">' + pct(r.move_1w) +
        '</td><td class="num">' + pct(r.move_1m) + '</td><td class="num">' + (r.rsi == null ? '--' : r.rsi.toFixed(0)) + '</td><td class="num">' + macd + '</td><td class="num">' + (r.volume_ratio == null ? '--' : r.volume_ratio.toFixed(1) + 'x') +
        '</td><td class="num">' + pc + '</td><td>' + esc(r.rating) + '</td><td class="why">' + esc((r.why || []).join('; ')) + '</td>' +
        '<td><button type="button" class="small" data-watch="' + esc(r.symbol) + '" title="Add to your watchlist">☆</button></td></tr>';
    }).join('');
    $('sc-table').innerHTML = rows.length ? '<thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody>' : '';
    if (!rows.length) { $('sc-summary').innerHTML += ' <span class="muted">Nothing matched: loosen a filter (a wider RSI range or a longer MACD window usually helps).</span>'; }
  }
  window.scSort = function (k) { if (sortKey === k) { sortDir = -sortDir; } else { sortKey = k; sortDir = (k === 'symbol' || k === 'type' || k === 'sector' || k === 'rating') ? 1 : -1; } draw(); };
  document.addEventListener('click', function (ev) {
    var b = ev.target.closest ? ev.target.closest('button[data-watch]') : null; if (!b) { return; }
    b.disabled = true; postJSON('/api/watchlist/add', {symbol: b.getAttribute('data-watch')}).then(function () { b.textContent = '★'; }).catch(function (e) { b.disabled = false; alert(e.message); });
  });
  window.scLoadOptions = function () {
    var btn = $('sc-opt-btn'); btn.disabled = true; $('sc-opt-note').textContent = 'Reading option volume…';
    postJSON('/api/screener/options', {symbols: rows.slice(0, 40).map(function (r) { return r.symbol; })}).then(function (r) {
      var n = 0; rows.forEach(function (x) { if (r.items[x.symbol]) { x.put_call = r.items[x.symbol]; n += 1; } });
      $('sc-opt-note').textContent = n + ' of ' + Math.min(rows.length, 40) + ' have option volume today (the first 40 rows were checked).'; btn.disabled = false; draw();
    }).catch(function (e) { $('sc-opt-note').textContent = e.message; btn.disabled = false; });
  };

  postJSON('/api/screener/config', {}).then(function (c) {
    CFG = c; $('sc-sources').textContent = c.sources + ' Scans ' + c.universe_size + ' stocks and ETFs.';
    $('sc-examples').innerHTML = c.examples.map(function (e) { return '<button type="button" data-ex="' + esc(e) + '">' + esc(e) + '</button>'; }).join('');
  }).catch(function () {});
  $('sc-examples').addEventListener('click', function (ev) { var b = ev.target.closest('button[data-ex]'); if (b) { $('sc-text').value = b.getAttribute('data-ex'); find(); } });
})();
</script>
"""


def _swing_row(n: int) -> str:
    wins = "".join(f'<option value="{k}">{label}</option>' for k, label in (("1d", "1 day"), ("1w", "1 week"), ("2w", "2 weeks"), ("1m", "1 month"), ("3m", "3 months"), ("6m", "6 months"), ("1y", "1 year")))
    default_win = "1w" if n == 1 else "1m"
    wins = wins.replace(f'value="{default_win}"', f'value="{default_win}" selected', 1)
    return (f'<div class="sc-row"><select name="s{n}_dir"><option value="either">Up or down</option><option value="up">Up</option><option value="down">Down</option></select>'
            f'<input type="number" name="s{n}_pct" min="0" step="0.1" placeholder="%"><span>%</span><input type="number" name="s{n}_usd" min="0" step="0.5" placeholder="$"><span>$</span>'
            f'<span>over</span><select name="s{n}_win">{wins}</select></div>')


def _render_screener_page() -> str:
    themes = "".join(f'<option value="{html.escape(k)}">{html.escape(v["label"])}</option>' for k, v in universe.THEMES.items())
    sectors = "".join(_check("sector", s, s) for s in universe.SECTORS)
    cats = "".join(_check("sector", c, c) for c in _CATEGORIES)
    body = (_BODY.replace("__THEMES__", themes).replace("__SWING1__", _swing_row(1)).replace("__SWING2__", _swing_row(2))
            .replace("__SECTORS__", sectors).replace("__CATEGORIES__", cats))
    return _shell(title="Screener", active="screener.html",
                  body=f"<style>{_CSS}</style>{body}" + _JS.replace("__GLOSSARY__", glossary.JS))
