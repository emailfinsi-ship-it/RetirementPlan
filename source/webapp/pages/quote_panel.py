"""The Trading tab's "Quote and chart" card (practice and live pages alike):
type a symbol and see its price, day range, 52-week range, trend, a technical
buy / sell rating and a price / volume / RSI chart. Data comes from the
/api/alpaca/quote route (source.webapp.pages.quote_chart). Read-only: it never
places or changes an order."""

from __future__ import annotations

from source.webapp.pages.quote_chart import CHART_CSS

_PANEL_CSS = """
.qp-head { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 16px; margin:8px 0 2px; }
.qp-sym { font-size:22px; font-weight:700; }
.qp-price { font-size:26px; font-weight:700; }
.qp-up { color:var(--success); font-weight:600; } .qp-down { color:var(--danger); font-weight:600; }
.qp-stats { display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:8px 14px; margin:10px 0; font-size:13px; }
.qp-stats div span { display:block; color:var(--ink-muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
.qp-ranges { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:10px 24px; margin:6px 0 12px; }
.qp-track { position:relative; height:8px; border-radius:4px; background:color-mix(in srgb, var(--ink-muted) 30%, transparent); margin:6px 0 2px; }
.qp-track i { position:absolute; top:-4px; width:4px; height:16px; border-radius:2px; background:var(--brand); }
.qp-trackl { display:flex; justify-content:space-between; font-size:12px; color:var(--ink-muted); }
.qp-pills { display:flex; gap:6px; flex-wrap:wrap; margin:8px 0; }
.qp-rate { display:flex; flex-wrap:wrap; align-items:center; gap:8px 14px; margin:10px 0 4px; }
.qp-badge { display:inline-block; padding:5px 14px; border-radius:999px; font-weight:700; font-size:15px; border:2px solid; }
.qp-b-buy { color:var(--success); border-color:var(--success); } .qp-b-hold { color:var(--warn); border-color:var(--warn); }
.qp-b-sell { color:var(--danger); border-color:var(--danger); }
.qp-sig { list-style:none; margin:6px 0; padding:0; font-size:13px; }
.qp-sig li { display:flex; gap:8px; padding:3px 0; border-top:1px solid var(--border); }
.qp-sig li:first-child { border-top:0; }
.qp-sig b { flex:0 0 16px; text-align:center; }
.qp-read { min-height:20px; font-size:12px; color:var(--ink-muted); margin:4px 0; font-variant-numeric:tabular-nums; }
.qp-cols { display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:4px 28px; }
"""

_PANEL_JS = """
<script>
(function () {
  var MODE = '__MODE__', cur = {symbol: '', range: '3M', rows: []};
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function usd(n) { return n == null ? '--' : '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
  function vol(n) { return n == null ? '--' : (n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(Math.round(n))); }
  function signed(n, suffix) { return n == null ? '--' : (n >= 0 ? '+' : '-') + Math.abs(n).toFixed(2) + (suffix || ''); }
  function track(low, high, pos, lowLabel, highLabel, title) {
    if (low == null || high == null || pos == null) { return '<div><strong>' + title + '</strong><div class="muted small">Not available right now.</div></div>'; }
    return '<div><strong>' + title + '</strong><div class="qp-track"><i style="left:calc(' + (pos * 100).toFixed(1) + '% - 2px)"></i></div>' +
      '<div class="qp-trackl"><span>' + lowLabel + ' ' + usd(low) + '</span><span>' + highLabel + ' ' + usd(high) + '</span></div></div>';
  }
  function pills() {
    return ['1D', '1M', '3M', '6M', '1Y'].map(function (r) {
      return '<button type="button" class="' + (r === cur.range ? 'primary' : '') + '" onclick="lookupQuote(\\'' + cur.symbol + '\\', \\'' + r + '\\')">' + r + '</button>';
    }).join('');
  }
  function badgeClass(label) { return /Buy/.test(label) ? 'qp-b-buy' : /Sell/.test(label) ? 'qp-b-sell' : 'qp-b-hold'; }
  function render(d) {
    var q = d.quote, up = (q.change || 0) >= 0, r = d.rating;
    cur.symbol = d.symbol; cur.range = d.range; cur.rows = d.rows;
    var arrow = up ? '\\u25B2' : '\\u25BC';
    var h = '<div class="qp-head"><span class="qp-sym">' + esc(d.symbol) + '</span><span class="qp-price">' + usd(q.price) + '</span>' +
      '<span class="' + (up ? 'qp-up' : 'qp-down') + '">' + arrow + ' ' + signed(q.change) + ' (' + signed(q.change_pct, '%') + ') today</span></div>';
    h += '<div class="qp-stats">' +
      '<div><span>Open</span>' + usd(q.open) + '</div><div><span>Day high</span>' + usd(q.high) + '</div><div><span>Day low</span>' + usd(q.low) + '</div>' +
      '<div><span>Previous close</span>' + usd(q.prev_close) + '</div><div><span>Volume today</span>' + vol(q.volume) + '</div>' +
      '<div><span>Bid</span>' + usd(q.bid) + (q.bid_size ? ' x ' + q.bid_size : '') + '</div><div><span>Ask</span>' + usd(q.ask) + (q.ask_size ? ' x ' + q.ask_size : '') + '</div></div>';
    h += '<div class="qp-ranges">' + track(q.low, q.high, q.day_position, 'Low', 'High', 'Day range') +
      track(d.week52.low, d.week52.high, d.week52.position, 'Low', 'High', '52-week range') + '</div>';
    h += '<div class="qp-rate"><strong>Technical rating</strong><span class="qp-badge ' + badgeClass(r.label) + '">' + esc(r.label) + '</span>' +
      (r.of ? '<span class="muted">' + r.buy_votes + ' of ' + r.of + ' signals bullish, ' + r.sell_votes + ' bearish</span>' : '') + '</div>';
    h += '<div class="qp-cols"><div><ul class="qp-sig">' + r.signals.map(function (s) {
      return '<li><b class="' + (s.vote > 0 ? 'qp-up' : s.vote < 0 ? 'qp-down' : 'muted') + '">' + (s.vote > 0 ? '\\u25B2' : s.vote < 0 ? '\\u25BC' : '\\u25AC') + '</b><span><strong>' +
        esc(s.name) + '.</strong> ' + esc(s.text) + '</span></li>'; }).join('') + '</ul></div>' +
      '<div><table><thead><tr><th>Trend</th><th>Direction</th><th class="num">Change</th></tr></thead><tbody>' + d.trends.map(function (t) {
        var cls = t.direction === 'Up' ? 'qp-up' : t.direction === 'Down' ? 'qp-down' : '';
        var mark = t.direction === 'Up' ? '\\u25B2 ' : t.direction === 'Down' ? '\\u25BC ' : '';
        return '<tr><td>' + esc(t.label) + '</td><td class="' + cls + '">' + mark + esc(t.direction) + '</td><td class="num">' + (t.change_pct == null ? '--' : signed(t.change_pct, '%')) + '</td></tr>';
      }).join('') + '</tbody></table></div></div>';
    h += '<div class="qp-pills">' + pills() + '</div><div id="qp-read" class="qp-read">Move over the chart for the numbers on any bar. Hollow candle = closed up, filled = closed down.</div>' + d.chart;
    h += '<p class="muted small">Technical signals only: moving averages, RSI, MACD and volume, counted on daily prices. It is not advice and this app never places an order from it. ' +
      'Prices come from Alpaca\\u2019s free IEX feed, so volume is IEX\\u2019s share of the market, not the whole market\\u2019s.</p>' +
      '<p><button type="button" onclick="useInTicket()">Use ' + esc(d.symbol) + ' in the order form</button></p>';
    document.getElementById('qp-out').innerHTML = h;
    var hit = document.getElementById('qc-hit'); if (hit) { hit.addEventListener('mousemove', hover); hit.addEventListener('mouseleave', leave); }
  }
  function hover(e) {
    var svg = document.querySelector('svg.qc'); if (!svg) { return; }
    var box = svg.getBoundingClientRect(), n = +svg.dataset.n, left = +svg.dataset.left, pw = +svg.dataset.pw, w = +svg.dataset.w;
    var x = (e.clientX - box.left) * (w / box.width);
    var i = Math.max(0, Math.min(n - 1, Math.floor((x - left) / (pw / n)))), r = cur.rows[i]; if (!r) { return; }
    var line = document.getElementById('qc-cross'); var cx = left + (i + 0.5) * (pw / n);
    line.setAttribute('x1', cx); line.setAttribute('x2', cx); line.style.display = '';
    document.getElementById('qp-read').textContent = r.t + '   Open ' + usd(r.o) + '  High ' + usd(r.h) + '  Low ' + usd(r.l) + '  Close ' + usd(r.c) +
      '  Volume ' + vol(r.v) + (r.rsi == null ? '' : '  RSI ' + r.rsi.toFixed(0)) + (r.a == null ? '' : '  Avg ' + usd(r.a));
  }
  function leave() { var l = document.getElementById('qc-cross'); if (l) { l.style.display = 'none'; } }
  window.lookupQuote = function (sym, range) {
    sym = String(sym || '').trim().toUpperCase(); if (!sym) { return; }
    var out = document.getElementById('qp-out'), box = document.getElementById('quote');
    document.getElementById('qp-symbol').value = sym;
    out.innerHTML = '<p class="muted">Loading ' + esc(sym) + '&hellip;</p>';
    postJSON('/api/alpaca/quote', {mode: MODE, symbol: sym, range: range || cur.range}).then(render)
      .catch(function (e) { out.innerHTML = '<p class="status-line status-warn">' + esc(e.message) + '</p>'; });
    if (box && !range) { box.scrollIntoView({behavior: 'smooth', block: 'start'}); }
  };
  window.useInTicket = function () {
    var f = document.getElementById('ticket'); if (!f) { alert('The order form is not available on this page right now.'); return; }
    f.symbol.value = cur.symbol; f.scrollIntoView({behavior: 'smooth', block: 'center'}); f.qty.focus();
  };
  var params = new URLSearchParams(location.search); if (params.get('symbol')) { window.lookupQuote(params.get('symbol')); }
})();
</script>
"""


def quote_panel_html(mode: str) -> str:
    live = mode == "live"
    return f"""
<style>{CHART_CSS}{_PANEL_CSS}</style>
<div class="card" id="quote"{' style="border:2px solid #c94a4a;"' if live else ''}>
<h3 style="margin-top:0;">Quote and chart</h3>
<p class="muted">Look up any stock or ETF: price, day range, trend, a buy / sell rating from the chart, and a price, volume and RSI chart.
Looking things up never places an order{" and works even while live trading is off" if live else ""}.</p>
<form class="inline" onsubmit="event.preventDefault(); lookupQuote(this.symbol.value);">
  <label>Symbol<input id="qp-symbol" name="symbol" autocomplete="off" style="width:110px; text-transform:uppercase;" placeholder="AAPL" required></label>
  <button type="submit" class="primary">Look up</button>
</form>
<div id="qp-out"></div>
</div>
{_PANEL_JS.replace("__MODE__", mode)}
"""
