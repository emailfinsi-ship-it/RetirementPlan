"""The Orders tab (/orders.html): every real-money order sent from this app, across Alpaca, IBKR and E*TRADE, in one list, with
today's total against the daily limit and a CSV download. Alpaca statuses are refreshed from Alpaca's own order list; for IBKR and
E*TRADE the status shown is the last one the broker reported (open the broker's tab for its live list). Read-only."""

from __future__ import annotations

from source.webapp.render_helpers import _shell

_BODY = r"""
<style>
.od-sum { display:flex; flex-wrap:wrap; gap:10px 14px; margin:10px 0; }
.od-tile { border:1px solid var(--border); border-radius:12px; padding:8px 12px; background:var(--surface-alt); min-width:140px; }
.od-tile > span:first-child { display:block; font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--ink-muted); }
.od-tile b { font-size:18px; }
.od-filters { display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; margin:6px 0 10px; font-size:13px; }
#od-table td, #od-table th { white-space:nowrap; }
.od-buy { color:var(--success); font-weight:700; } .od-sell { color:var(--danger); font-weight:700; }
.od-st { display:inline-block; border-radius:999px; padding:0 8px; font-size:12px; font-weight:600; border:1px solid var(--border); }
.od-st.ok { border-color:var(--success); color:var(--success); } .od-st.bad { border-color:var(--danger); color:var(--danger); } .od-st.open { border-color:var(--warn); color:var(--warn); }
</style>
<h2 style="margin-top:0">Orders</h2>
<p class="muted">Every real-money order sent from this app, from Alpaca, IBKR and E*TRADE together. Practice (paper) orders are not listed. Alpaca&rsquo;s status is kept up to date;
for IBKR and E*TRADE the status is the last one the broker reported when it was sent, so open that tab for its live order list.</p>
<div class="card">
  <div class="od-sum" id="od-sum"></div>
  <div class="od-filters">
    <label>Show <select id="od-days"><option value="1">today</option><option value="7">last 7 days</option><option value="30" selected>last 30 days</option><option value="365">last year</option><option value="0">everything</option></select></label>
    <label>Broker <select id="od-broker"><option value="">all</option><option value="alpaca">Alpaca</option><option value="ibkr">IBKR</option><option value="etrade">E*TRADE</option></select></label>
    <label>Side <select id="od-side"><option value="">buy and sell</option><option value="buy">buy</option><option value="sell">sell</option></select></label>
    <button type="button" onclick="odLoad()">Refresh</button> <button type="button" onclick="odCsv()">Download CSV</button>
    <span class="muted small" id="od-note"></span>
  </div>
  <div style="overflow-x:auto;"><table id="od-table"></table></div>
</div>
<script>
(function () {
  var $ = function (id) { return document.getElementById(id); }, ITEMS = [], BR = {alpaca: 'Alpaca', ibkr: 'IBKR', etrade: 'E*TRADE'};
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function usd(n) { return '$' + Number(n || 0).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
  function kind(st) { st = String(st || '').toLowerCase(); return /fill/.test(st) && !/partial/.test(st) ? 'ok' : /cancel|reject|expire|fail/.test(st) ? 'bad' : 'open'; }
  function view() {
    var side = $('od-side').value, br = $('od-broker').value;
    return ITEMS.filter(function (o) { return (!side || o.side === side) && (!br || o.broker === br); });
  }
  function draw() {
    var list = view();
    $('od-table').innerHTML = list.length ? '<thead><tr><th>Sent</th><th>Broker</th><th>Side</th><th>Symbol</th><th class="num">Shares</th><th>Type</th><th class="num">Worth about</th><th>Status</th><th>Order id</th></tr></thead><tbody>' +
      list.map(function (o) {
        return '<tr><td>' + esc(String(o.placed_at).replace('T', ' ').slice(0, 16)) + '</td><td>' + esc(BR[o.broker] || o.broker) + '</td><td class="od-' + esc(o.side) + '">' + esc(o.side) + '</td>' +
          '<td><a href="/stock-analysis.html?symbol=' + encodeURIComponent(o.symbol) + '"><strong>' + esc(o.symbol) + '</strong></a></td><td class="num">' + o.qty + '</td><td>' + esc(o.order_type) +
          '</td><td class="num">' + usd(o.estimate) + '</td><td><span class="od-st ' + kind(o.status) + '">' + esc(String(o.status || '').replace(/_/g, ' ') || 'sent') + '</span></td><td class="muted small">' + esc(o.order_id) + '</td></tr>';
      }).join('') + '</tbody>' : '<tr><td class="muted">No orders in this view.</td></tr>';
    var total = list.reduce(function (a, o) { return a + (o.estimate || 0); }, 0), buys = list.filter(function (o) { return o.side === 'buy'; }).length;
    $('od-sum').innerHTML = '<div class="od-tile"><span>Orders shown</span><b>' + list.length + '</b></div><div class="od-tile"><span>Buys / sells</span><b>' + buys + ' / ' + (list.length - buys) + '</b></div>' +
      '<div class="od-tile"><span>Worth about (all shown)</span><b>' + usd(total) + '</b></div>' + (TODAY ? '<div class="od-tile"><span>Sent today</span><b>' + usd(TODAY.spent) + '</b>' +
      (TODAY.limit == null ? '' : '<div class="muted small">' + usd(TODAY.remaining) + ' left of ' + usd(TODAY.limit) + '</div>') + '</div>' : '');
  }
  var TODAY = null;
  window.odLoad = function () {
    $('od-note').textContent = 'Loading…';
    postJSON('/api/orders/history', {days: Number($('od-days').value)}).then(function (r) {
      ITEMS = r.items || []; TODAY = r.today; $('od-note').textContent = r.note || ''; draw();
    }).catch(function (e) { $('od-note').textContent = e.message; });
  };
  window.odCsv = function () {
    var cols = [['placed_at', 'Sent'], ['broker', 'Broker'], ['side', 'Side'], ['symbol', 'Symbol'], ['qty', 'Shares'], ['order_type', 'Type'], ['estimate', 'Worth about'], ['status', 'Status'], ['order_id', 'Order id']];
    function q(v) { v = v == null ? '' : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
    var text = cols.map(function (c) { return q(c[1]); }).join(',') + '\n' + view().map(function (o) { return cols.map(function (c) { return q(o[c[0]]); }).join(','); }).join('\n') + '\n';
    var a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], {type: 'text/csv'})); a.download = 'orders-' + new Date().toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(a); a.click(); a.remove();
  };
  ['od-days'].forEach(function (id) { $(id).addEventListener('change', window.odLoad); });
  ['od-broker', 'od-side'].forEach(function (id) { $(id).addEventListener('change', draw); });
  window.odLoad();
})();
</script>
"""


def _render_orders_page() -> str:
    return _shell(title="Orders", active="orders.html", body=_BODY)
