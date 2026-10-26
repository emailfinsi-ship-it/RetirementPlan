"""The IBKR and E*TRADE tabs: connect, balances, positions, open orders and a preview-then-confirm order ticket for a
real-money brokerage account. Everything is loaded by the page from /api/broker/data (see source.webapp.broker_api for
the safety rules: live trading must be switched on, limits apply, the symbol is typed again to send, every order is
logged). These balances are not counted in net worth or the retirement plan here."""

from __future__ import annotations

import html

from source.webapp.pages import position_ratings
from source.webapp.render_helpers import _shell

PAGES = {"ibkr": ("ibkr.html", "Interactive Brokers (IBKR)"), "etrade": ("etrade.html", "E*TRADE")}

_CSS = """
[hidden] { display:none !important; }
.bk-tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:10px; margin:10px 0; }
.bk-tile { border:1px solid var(--border); border-radius:12px; padding:10px 12px; background:var(--surface-alt); }
.bk-tile span { display:block; font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--ink-muted); }
.bk-tile b { font-size:20px; }
.bk-danger { color:var(--danger); font-weight:700; }
.bk-ticket { display:flex; flex-wrap:wrap; gap:10px 14px; align-items:flex-end; }
.bk-ticket label { display:flex; flex-direction:column; gap:3px; font-size:12px; color:var(--ink-muted); }
.bk-ticket input, .bk-ticket select { min-width:90px; }
.bk-preview { border:1px solid var(--border); border-radius:12px; padding:10px 12px; margin:10px 0; background:var(--surface-alt); }
.bk-step { margin:6px 0; }
.bk-warn { border:1px solid var(--warn); border-radius:10px; padding:8px 10px; margin:8px 0; }
.bk-pos td, .bk-pos th { white-space:nowrap; }
"""

_JS = r"""
<script>
(function () {
  var BROKER = '__BROKER__', ACCOUNT = '', DATA = null, LAST = null;
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function usd(v, cents) { return v == null ? '--' : '$' + Number(v).toLocaleString('en-US', {minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: cents ? 2 : 0}); }
  function num(v) { return v == null ? '--' : Number(v).toLocaleString('en-US', {maximumFractionDigits: 4}); }
  function say(id, text, bad) { var el = $(id); if (el) { el.textContent = text; el.className = bad ? 'status-line status-warn' : 'muted small'; } }
  function err(e) { alert(e.message || e); }

  function overviewHtml(o) {
    var h = '<div class="card"><h3 style="margin-top:0;">All accounts</h3><div style="overflow-x:auto"><table class="bk-pos"><thead><tr><th>Account</th><th class="num">Value</th><th class="num">Cash</th><th class="num">Buying power</th><th class="num">Stocks held</th></tr></thead><tbody>' +
      o.accounts.map(function (a) {
        var s = a.summary || {};
        return '<tr><td>' + esc(a.name) + (a.error ? '<br><span class="status-warn small">' + esc(a.error) + '</span>' : '') + '</td><td class="num">' + usd(s.value) + '</td><td class="num">' + usd(s.cash) + '</td><td class="num">' + usd(s.buying_power) + '</td><td class="num">' + a.positions.length + '</td></tr>';
      }).join('') +
      '<tr><td><strong>Total</strong></td><td class="num"><strong>' + usd(o.total.value) + '</strong></td><td class="num"><strong>' + usd(o.total.cash) + '</strong></td><td class="num"><strong>' + usd(o.total.buying_power) + '</strong></td><td></td></tr></tbody></table></div>';
    var withStocks = o.accounts.filter(function (a) { return a.positions.length; }).length;
    if (o.holdings.length && withStocks > 1) {   // with stocks in only one account the table would repeat that account's own list
      h += '<details class="fold"><summary><strong>Everything held, added up across accounts</strong> <span class="muted small">(' + o.holdings.length + ' stocks)</span></summary><div style="overflow-x:auto"><table class="bk-pos"><thead><tr><th>Symbol</th><th class="num">Shares</th><th class="num">Value</th><th class="num">Gain / loss</th><th class="num">In accounts</th></tr></thead><tbody>' +
        o.holdings.map(function (p) {
          var g = p.gain, cls = g == null ? '' : g >= 0 ? 'qp-up' : 'qp-down';
          return '<tr><td><a href="/stock-analysis.html?symbol=' + encodeURIComponent(p.symbol) + '"><strong>' + esc(p.symbol) + '</strong></a></td><td class="num">' + num(p.qty) + '</td><td class="num">' + usd(p.market_value, true) + '</td><td class="num ' + cls + '">' + (g == null ? '--' : (g >= 0 ? '+' : '-') + usd(Math.abs(g), true)) + '</td><td class="num">' + p.accounts + '</td></tr>';
        }).join('') + '</tbody></table></div></details>';
    }
    return h + '</div>';
  }

  function render(d) {
    DATA = d; ACCOUNT = d.account || '';
    var live = d.armed
      ? '<p class="status-line status-ok">Live trading is ON ' + (d.persistent ? 'until you turn it off' : 'until ' + new Date(d.armed_until * 1000).toLocaleTimeString()) + '. Limit per order ' + usd(d.per_order) + ', ' + usd(d.daily_remaining) + ' left today (shared with every broker).</p>' +
        '<p><button type="button" data-act="disarm">Turn live trading OFF now</button></p>'
      : '<p class="status-line status-warn">Live trading is OFF, so you can look but not preview or send orders.</p>' +
        '<form data-act="arm" class="inline"><label>To turn it on, type TRADE REAL MONEY<input name="phrase" autocomplete="off" style="width:200px"></label> <label><input name="stay" type="checkbox" checked> Keep it on until I turn it off</label> <button type="submit" class="primary">Turn on</button></form>';
    $('bk-live').innerHTML = live + (d.found_note ? '<p class="status-line status-ok">' + esc(d.found_note) + '</p>' : '');
    var gu = document.querySelector('input[name=url]'); if (gu && d.gateway_url) { gu.value = d.gateway_url; }
    var ga = $('gw-auto'); if (ga && d.gateway_autostart != null) { ga.checked = !!d.gateway_autostart; }
    if (!d.connected) {
      $('bk-data').innerHTML = '<p class="status-line status-warn">' + esc(d.message || 'Not connected.') + '</p>';
      $('bk-ticket-card').hidden = true;
      return;
    }
    var h = '';
    if (!d.accounts.length) { h += '<p class="status-line status-warn">' + esc(d.message || 'Connected, but no brokerage account came back.') + ' Press "Run a check" below and send me what it shows.</p>'; }
    if (d.accounts.length > 1) {
      h += '<p><label>Account <select id="bk-acct">' + d.accounts.map(function (a) { return '<option value="' + esc(a.id) + '"' + (a.id === d.account ? ' selected' : '') + '>' + esc(a.name) + '</option>'; }).join('') + '</select></label></p>';
    } else if (d.accounts.length) { h += '<p class="muted small">Account: ' + esc(d.accounts[0].name) + '</p>'; }
    if (d.summary) {
      h += '<div class="bk-tiles"><div class="bk-tile"><span>Account value</span><b>' + usd(d.summary.value) + '</b></div>' +
        '<div class="bk-tile"><span>Cash</span><b>' + usd(d.summary.cash) + '</b></div>' +
        '<div class="bk-tile"><span>Buying power</span><b>' + usd(d.summary.buying_power) + '</b></div></div>';
    }
    d.errors.forEach(function (m) { h += '<p class="status-line status-warn">' + esc(m) + '</p>'; });
    if (d.overview) { h += overviewHtml(d.overview); }
    h += '<h3>Positions' + (d.overview ? ' in this account' : '') + '</h3>';
    if (!d.positions.length) { h += '<p class="muted">No stock positions.</p>'; }
    else {
      h += '<div style="overflow-x:auto"><table class="bk-pos"><thead><tr><th>Symbol</th><th class="num">Shares</th><th class="num">Avg cost</th><th class="num">Price</th><th class="num">Value</th><th class="num">Gain / loss</th><th>Rating</th><th></th></tr></thead><tbody>' +
        d.positions.map(function (p) {
          var g = p.gain, cls = g == null ? '' : g >= 0 ? 'qp-up' : 'qp-down';
          var sell = '<button type="button" data-act="buy" data-sym="' + esc(p.symbol) + '">Buy</button> ' +
            (p.qty >= 1 ? '<button type="button" data-act="sell" data-sym="' + esc(p.symbol) + '" data-qty="' + Math.floor(p.qty) + '">Sell</button>' : '');
          return '<tr><td><a href="/stock-analysis.html?symbol=' + encodeURIComponent(p.symbol) + '" title="Open in Stock Analysis"><strong>' + esc(p.symbol) + '</strong></a></td><td class="num">' + num(p.qty) + '</td><td class="num">' + usd(p.avg_cost, true) +
            '</td><td class="num">' + usd(p.price, true) + '</td><td class="num">' + usd(p.market_value, true) + '</td><td class="num ' + cls + '">' + (g == null ? '--' : (g >= 0 ? '+' : '-') + usd(Math.abs(g), true)) + '</td><td data-rate-sym="' + esc(p.symbol) + '"><span class="muted">&hellip;</span></td><td>' + sell + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    }
    if (BROKER === 'etrade' && d.positions.length) {
      h += '<p><button type="button" data-act="lots">Show tax lots and cost basis</button> <span id="bk-lots-note" class="muted small"></span></p><div id="bk-lots"></div>';
    }
    h += '<h3>Orders</h3>';
    if (!d.orders.length) { h += '<p class="muted">No recent orders.</p>'; }
    else {
      h += '<div style="overflow-x:auto"><table class="bk-pos"><thead><tr><th>Symbol</th><th>Side</th><th class="num">Shares</th><th>Type</th><th>Status</th><th></th></tr></thead><tbody>' +
        d.orders.map(function (o) {
          return '<tr><td><strong>' + esc(o.symbol) + '</strong></td><td>' + esc(o.side) + '</td><td class="num">' + num(o.qty) + (o.filled ? ' (' + num(o.filled) + ' filled)' : '') + '</td><td>' + esc(o.type) + (o.limit_price ? ' ' + usd(o.limit_price, true) : '') +
            '</td><td>' + esc(o.status) + '</td><td>' + (o.open ? '<button type="button" data-act="cancel" data-id="' + esc(o.id) + '">Cancel</button>' : '') + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    }
    $('bk-data').innerHTML = h;
    if (window.applyRatings) { window.applyRatings(); }
    $('bk-ticket-card').hidden = false;
    var sel = $('bk-acct'); if (sel) { sel.onchange = function () { load(sel.value); }; }
  }

  function load(account) {
    say('bk-status', 'Loading…');
    return postJSON('/api/broker/data', {broker: BROKER, account: account || ACCOUNT}).then(function (d) { render(d); say('bk-status', d.connected ? 'Updated ' + new Date().toLocaleTimeString() + '.' : ''); })
      .catch(function (e) { say('bk-status', e.message, true); });
  }

  function order() {
    var f = $('bk-form');
    return {symbol: f.symbol.value, side: f.side.value, qty: f.qty.value, type: f.type.value, limit_price: f.limit_price.value, time_in_force: f.tif.value};
  }
  function showPreview(p) {
    LAST = p; var o = p.order;
    var h = '<div class="bk-preview"><strong>' + esc(o.side.toUpperCase()) + ' ' + o.qty + ' ' + esc(o.symbol) + '</strong> (' + (o.type === 'limit' ? 'limit ' + usd(o.limit_price, true) : 'market') + ', ' + (o.time_in_force === 'gtc' ? 'good till cancelled' : 'today only') + ')' +
      '<br>Worth about <strong>' + usd(p.estimate, true) + '</strong>' + (p.price ? ' at ' + usd(p.price, true) + ' a share' : '') + (p.commission != null ? '; estimated commission ' + usd(p.commission, true) : '') + '.' +
      (p.notes && p.notes.length ? '<div class="bk-warn">' + p.notes.map(esc).join('<br>') + '</div>' : '') +
      '<form data-act="send" class="inline bk-step"><label>To send this REAL-MONEY order, type its symbol (' + esc(o.symbol) + ')<input name="confirm" autocomplete="off" style="width:110px; text-transform:uppercase"></label> ' +
      '<button type="submit" class="primary" style="background:#c94a4a;">Send order</button> <button type="button" data-act="discard">Discard</button></form>' +
      '<p class="muted small">This preview stays valid for about ' + Math.round(p.expires_in / 60) + ' minutes.</p></div>';
    $('bk-preview').innerHTML = h;
  }
  function showAck(r) {
    LAST = {token: r.token, order: LAST ? LAST.order : null};
    $('bk-preview').innerHTML = '<div class="bk-preview"><p class="bk-danger">Interactive Brokers asked a question before accepting this order. Nothing has been sent yet.</p>' +
      '<div class="bk-warn">' + r.messages.map(esc).join('<br>') + '</div>' +
      '<p><button type="button" class="primary" style="background:#c94a4a;" data-act="ack">Send anyway</button> <button type="button" data-act="discard">Cancel this order</button></p></div>';
  }
  var LOTS = null;
  function showLots() {
    say('bk-lots-note', 'Loading every lot in every account (one request per stock)\u2026');
    postJSON('/api/broker/lots', {broker: BROKER, account: ACCOUNT}).then(function (r) {
      LOTS = r; say('bk-lots-note', '');
      var gl = function (g) { return g == null ? '--' : (g >= 0 ? '+' : '-') + usd(Math.abs(g), true); };
      var h = (r.problems || []).map(function (m) { return '<p class="status-line status-warn">' + esc(m) + '</p>'; }).join('') + '<h3>Tax lots, all accounts</h3><p class="muted small">Each row is one purchase. Cost basis is what you paid for those shares; gain is value now minus cost basis.</p>' +
        '<div style="overflow-x:auto"><table class="bk-pos"><thead><tr><th>Account</th><th>Symbol</th><th>Bought</th><th class="num">Shares</th><th class="num">Cost / share</th><th class="num">Cost basis</th><th class="num">Value now</th><th class="num">Gain / loss</th><th>Term</th></tr></thead><tbody>' +
        r.lots.map(function (l) {
          return '<tr><td>' + esc(l.account) + '</td><td><strong>' + esc(l.symbol) + '</strong></td><td>' + esc(l.acquired || '--') + '</td><td class="num">' + num(l.qty) + '</td><td class="num">' + usd(l.cost_per_share, true) + '</td><td class="num">' + usd(l.cost_basis, true) +
            '</td><td class="num">' + usd(l.market_value, true) + '</td><td class="num ' + (l.gain == null ? '' : l.gain >= 0 ? 'qp-up' : 'qp-down') + '">' + gl(l.gain) + '</td><td>' + esc(l.term || '--') + '</td></tr>';
        }).join('') +
        r.by_account.map(function (a) {
          return '<tr><td colspan="5">' + esc(a.account) + ' (' + a.lots + ' lots)</td><td class="num">' + usd(a.cost_basis, true) + '</td><td class="num">' + usd(a.market_value, true) + '</td><td class="num">' + gl(a.gain) + '</td><td></td></tr>';
        }).join('') +
        '<tr><td colspan="5"><strong>Total, all accounts</strong></td><td class="num"><strong>' + usd(r.total.cost_basis, true) + '</strong></td><td class="num"><strong>' + usd(r.total.market_value, true) + '</strong></td><td class="num"><strong>' + gl(r.total.gain) + '</strong></td><td></td></tr></tbody></table></div>' +
        '<p><button type="button" data-act="lotscsv">Download as a spreadsheet (CSV)</button></p>';
      $('bk-lots').innerHTML = h;
    }).catch(function (e) { say('bk-lots-note', e.message, true); });
  }
  function downloadLots() {
    if (!LOTS) { return; }
    var nl = String.fromCharCode(10);
    var rows = [['Account', 'Symbol', 'Bought', 'Shares', 'Cost per share', 'Cost basis', 'Value now', 'Gain', 'Term']].concat(LOTS.lots.map(function (l) {
      return [l.account, l.symbol, l.acquired, l.qty, l.cost_per_share, l.cost_basis, l.market_value, l.gain, l.term];
    }));
    var csv = rows.map(function (r) { return r.map(function (c) { return '"' + String(c == null ? '' : c).replace(/"/g, '""') + '"'; }).join(','); }).join(nl);
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], {type: 'text/csv'}));
    a.download = 'tax-lots-' + BROKER + '.csv'; document.body.appendChild(a); a.click(); a.remove();
  }
  function sent(r) {
    $('bk-preview').innerHTML = '<p class="status-line status-ok">Order sent: ' + esc(r.side) + ' ' + r.qty + ' ' + esc(r.symbol) + ' (' + esc(r.status) + '). Order id ' + esc(r.id) + '.</p>';
    LAST = null; load();
  }

  document.addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-act]'); if (!b || b.tagName === 'FORM') { return; }
    var act = b.dataset.act;
    if (act === 'disarm') { postJSON('/api/alpaca/live/disarm', {}).then(function () { load(); }).catch(err); }
    else if (act === 'sell') {
      var f = $('bk-form'); f.symbol.value = b.dataset.sym; f.side.value = 'sell'; f.qty.value = b.dataset.qty;
      $('bk-ticket-card').scrollIntoView({behavior: 'smooth', block: 'start'});
      say('bk-ticket-note', 'Selling ' + b.dataset.qty + ' ' + b.dataset.sym + '. Change the number to sell fewer; pick Limit and a price to sell only at that price or better. Nothing is sent until you preview and confirm.');
    }
    else if (act === 'buy') {
      var fb = $('bk-form'); fb.symbol.value = b.dataset.sym; fb.side.value = 'buy'; fb.qty.value = '1';
      $('bk-ticket-card').scrollIntoView({behavior: 'smooth', block: 'start'});
      say('bk-ticket-note', 'Buying ' + b.dataset.sym + ' in this account. Set the number of shares; pick Limit and a price to buy only at that price or lower. Nothing is sent until you preview and confirm.');
    }
    else if (act === 'cancel') {
      if (!confirm('Cancel this order?')) { return; }
      postJSON('/api/broker/cancel', {broker: BROKER, account: ACCOUNT, order_id: b.dataset.id}).then(function () { load(); }).catch(err);
    }
    else if (act === 'discard') { LAST = null; $('bk-preview').innerHTML = ''; }
    else if (act === 'ack') {
      postJSON('/api/broker/order', {broker: BROKER, account: ACCOUNT, token: LAST.token, confirm_symbol: LAST.order.symbol}).then(function (r) { r.ack_required ? showAck(r) : sent(r); }).catch(err);
    }
    else if (act === 'refresh') { load(); }
    else if (act === 'lots') { showLots(); }
    else if (act === 'lotscsv') { downloadLots(); }
    else if (act === 'diagnose') {
      var box = $('bk-diag'); box.hidden = false; box.textContent = 'Checking\u2026';
      postJSON('/api/broker/diagnose', {broker: BROKER}).then(function (r) {
        box.textContent = 'What each call returned (structure only; no balances, numbers or tokens are shown):\n\n' + r.steps.map(function (s) {
          return (s.ok ? 'OK    ' : 'FAIL  ') + s.step + '\n      ' + (s.ok ? JSON.stringify(s.shape) : s.error);
        }).join('\n');
      }).catch(function (e) { box.textContent = 'The check itself failed: ' + e.message; });
    }
  });
  document.addEventListener('submit', function (ev) {
    var f = ev.target, act = f.dataset.act; if (!act) { return; }
    ev.preventDefault();
    if (act === 'arm') { postJSON('/api/alpaca/live/arm', {phrase: f.phrase.value, stay_on: f.stay.checked, broker: BROKER}).then(function () { load(); }).catch(err); }
    else if (act === 'send') {
      postJSON('/api/broker/order', {broker: BROKER, account: ACCOUNT, token: LAST.token, confirm_symbol: f.confirm.value}).then(function (r) { r.ack_required ? showAck(r) : sent(r); }).catch(err);
    }
  });
  document.addEventListener('DOMContentLoaded', function () {
    var f = $('bk-form');
    f.addEventListener('submit', function (ev) {
      ev.preventDefault(); say('bk-ticket-note', '');
      postJSON('/api/broker/preview', {broker: BROKER, account: ACCOUNT, order: order()}).then(showPreview).catch(function (e) { $('bk-preview').innerHTML = ''; say('bk-ticket-note', e.message, true); });
    });
    var sym = new URLSearchParams(location.search).get('symbol'); if (sym) { f.symbol.value = sym.toUpperCase(); }
    f.type.addEventListener('change', function () { f.limit_price.disabled = f.type.value !== 'limit'; });
    f.limit_price.disabled = true;
    load();
  });
  window.brokerReload = function () { load(); };
})();
</script>
"""

_TICKET = """
<div class="card" id="bk-ticket-card" hidden>
<h3 style="margin-top:0;">Order ticket</h3>
<p class="muted">Whole shares only. You will see the order priced first, then confirm it by typing the symbol. Nothing is sent until you do.</p>
<form id="bk-form" class="bk-ticket">
  <label>Symbol<input name="symbol" autocomplete="off" style="width:100px; text-transform:uppercase" required></label>
  <label>Action<select name="side"><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
  <label>Shares<input name="qty" type="number" min="1" step="1" style="width:90px" required></label>
  <label>Type<select name="type"><option value="market">Market</option><option value="limit">Limit</option></select></label>
  <label>Limit price<input name="limit_price" type="number" min="0.01" step="0.01" style="width:100px"></label>
  <label>Good for<select name="tif"><option value="day">Today only</option><option value="gtc">Until cancelled</option></select></label>
  <button type="submit" class="primary">Preview order</button>
</form>
<p id="bk-ticket-note" class="muted small"></p>
<div id="bk-preview"></div>
</div>
"""


def _ibkr_connect_html(url: str) -> str:
    return f"""
<div class="card">
<h3 style="margin-top:0;">Connect Interactive Brokers</h3>
<p class="muted">IBKR connects through its own <strong>Client Portal Gateway</strong>, a small Java program that runs on this computer and comes with this app.
It starts by itself when this app starts (you can turn that off below) and listens only on this computer, on a port private to this app. If it is not running, press <strong>Start gateway</strong> and wait about 10 seconds, then press <strong>Sign in to IBKR</strong>: IBKR's own sign-in page opens in your browser
(it may warn about the certificate; that is normal for this local program, so continue past it). Your IBKR password goes only to IBKR's gateway, never to this app.
The gateway signs you out after a while, and when it does this page tells you to sign in again. It needs Java (11 or newer is safest) installed on the Mac.</p>
<p><button type="button" class="primary" id="gw-start">Start gateway</button>
<a id="gw-signin" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" class="pill-link"><button type="button">Sign in to IBKR</button></a>
<button type="button" id="gw-stop">Stop gateway</button> <span id="gw-note" class="muted small"></span></p>
<p><label style="flex-direction:row; align-items:center; gap:6px;"><input type="checkbox" id="gw-auto" style="width:auto"> Start the gateway automatically when this app starts</label></p>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/broker/ibkr/gateway', {{url: this.url.value}}).then(function() {{ brokerReload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Gateway address (this computer only)<input name="url" value="{html.escape(url, quote=True)}" style="width:260px"></label>
  <button type="submit">Save and check</button>
  <button type="button" data-act="refresh">Check connection</button>
</form>
</div>
<script>
(function () {{
  function $(id) {{ return document.getElementById(id); }}
  document.addEventListener('DOMContentLoaded', function () {{
    var tries = 0;
    function poll() {{
      brokerReload();
      if (tries++ < 6) {{ setTimeout(poll, 5000); }}
    }}
    $('gw-start').onclick = function () {{
      $('gw-note').textContent = 'Starting\u2026';
      postJSON('/api/broker/ibkr/start', {{}}).then(function (r) {{
        $('gw-note').textContent = r.message; $('gw-signin').href = r.url; tries = 0; setTimeout(poll, 5000);
      }}).catch(function (e) {{ $('gw-note').textContent = ''; alert(e.message); }});
    }};
    $('gw-auto').onchange = function () {{ postJSON('/api/broker/ibkr/autostart', {{on: this.checked}}).catch(function (e) {{ alert(e.message); }}); }};
    $('gw-stop').onclick = function () {{
      postJSON('/api/broker/ibkr/stop', {{}}).then(function (r) {{ $('gw-note').textContent = r.stopped ? 'Stopped.' : 'This app did not start a gateway, so there is nothing to stop here.'; brokerReload(); }});
    }};
  }});
}})();
</script>
"""


def _etrade_connect_html(state: dict) -> str:
    steps = ""
    saved = ""
    if state.get("has_keys"):
        saved = ('<p class="status-line status-ok">Keys saved in the Keychain: consumer key ending <strong>'
                 + html.escape(state.get("key_hint", "")) + '</strong>, consumer secret stored.</p>')
    elif state.get("key_hint"):
        saved = ('<p class="status-line status-warn">Only the consumer key (ending <strong>' + html.escape(state["key_hint"])
                 + '</strong>) is saved. The consumer secret is missing, so paste both again.</p>')
    if state.get("has_keys"):
        if state.get("has_session"):
            steps = """
<p class="status-line status-ok">Signed in to E*TRADE. This stays signed in while you move around the app; E*TRADE ends it at midnight US Eastern.</p>"""
        steps += """
<div class="bk-step"><p class="muted">Each day you trade, press <strong>Connect</strong>: E*TRADE opens a sign-in page, you approve it, and E*TRADE shows a short code to paste back here. (E*TRADE ends the session every night.)</p>
<p><button type="button" class="primary" id="et-start">Connect</button> <span id="et-note" class="muted small"></span><br>
<button type="button" id="et-off">Sign out</button> <button type="button" id="et-forget">Forget my keys</button></p>
<div id="et-code" hidden><p class="status-line status-ok">A sign-in page was opened. Approve it, then paste the code E*TRADE shows.
<a id="et-link" target="_blank" rel="noopener noreferrer" href="#">Open the sign-in page again</a></p>
<form class="inline" id="et-finish"><label>Verification code<input name="verifier" autocomplete="off" style="width:140px" required></label> <button type="submit" class="primary">Finish</button></form></div></div>"""
    return f"""
<div class="card">
<h3 style="margin-top:0;">Connect E*TRADE</h3>
<p class="muted">Get a <strong>consumer key and secret</strong> from E*TRADE's developer page (developer.etrade.com): use the <strong>production</strong> key
(this app does not use sandbox keys). It is stored in the macOS Keychain, never in the database.
Your E*TRADE password goes only to E*TRADE. <strong>E*TRADE does not cover orders sent through its API under its Customer Protection Guarantee.</strong></p>
{saved}<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/broker/etrade/keys', {{consumer_key: this.ck.value, consumer_secret: this.cs.value}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Consumer key<input name="ck" autocomplete="off" style="width:240px" required></label>
  <label>Consumer secret<input name="cs" type="password" autocomplete="off" style="width:240px" required></label>
  <button type="submit">{'Replace keys' if state.get('has_keys') else 'Save keys'}</button>
</form>
{steps}
</div>
<script>
(function () {{
  function $(id) {{ return document.getElementById(id); }}
  function err(e) {{ alert(e.message || e); }}
  document.addEventListener('DOMContentLoaded', function () {{
    if (!$('et-start')) {{ return; }}
    function note(t, bad) {{ var n = $('et-note'); n.textContent = t; n.className = bad ? 'status-line status-warn' : 'muted small'; }}
    $('et-start').onclick = function () {{
      note('Contacting E*TRADE\\u2026');
      postJSON('/api/broker/etrade/start', {{}}).then(function (r) {{
        $('et-link').href = r.authorize_url; $('et-code').hidden = false;
        note('E*TRADE is ready. If its sign-in page did not open, use the link below. Approve it, then paste the code.');
        window.open(r.authorize_url, '_blank', 'noopener');
      }}).catch(function (e) {{ note(e.message, true); }});
    }};
    $('et-finish').onsubmit = function (ev) {{
      ev.preventDefault();
      note('Checking the code\\u2026');
      postJSON('/api/broker/etrade/finish', {{verifier: this.verifier.value}}).then(function () {{ location.reload(); }}).catch(function (e) {{ note(e.message, true); }});
    }};
    $('et-off').onclick = function () {{ postJSON('/api/broker/etrade/disconnect', {{}}).then(function () {{ location.reload(); }}).catch(err); }};
    $('et-forget').onclick = function () {{
      if (confirm('Remove the saved E*TRADE keys from this computer?')) {{ postJSON('/api/broker/etrade/disconnect', {{forget_keys: true}}).then(function () {{ location.reload(); }}).catch(err); }}
    }};
  }});
}})();
</script>
"""


def _render_broker_page(broker: str) -> str:
    from source.webapp import broker_api       # imported here: broker_api is loaded by trading_api, which loads pages
    page, name = PAGES[broker]
    warn = (f'<p class="status-line" style="color:#c94a4a; font-weight:700;">REAL MONEY. Orders sent from this page buy and sell real investments in your '
            f'{html.escape(name)} account. This app does not give investment advice and never places an order by itself.</p>'
            '<p class="muted">These balances are not added to your net worth or plan here. (Link the account with Plaid if you want it counted.)</p>')
    connect = _ibkr_connect_html(broker_api.gateway_url()) if broker == "ibkr" else _etrade_connect_html(broker_api.etrade_state())
    body = (f"<style>{_CSS}</style><h2 style=\"margin-top:0\">{html.escape(name)}</h2>{warn}{connect}"
            '<div class="card"><div id="bk-live"></div><p><button type="button" data-act="refresh">Refresh</button> <button type="button" data-act="diagnose">Run a check</button> <span id="bk-status" class="muted small"></span></p>'
            '<div id="bk-data"></div><pre id="bk-diag" class="muted small" style="white-space:pre-wrap; max-height:340px; overflow:auto;" hidden></pre></div>' + _TICKET + _JS.replace("__BROKER__", broker) + position_ratings.block())
    return _shell(title=name, active=page, body=body)
