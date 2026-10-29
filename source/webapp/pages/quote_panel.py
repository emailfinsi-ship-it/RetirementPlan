"""The Stock Analysis tab's "Quote and chart" card: type a symbol and see its
price, day range, 52-week range, trend, a technical buy / sell rating and a
price / volume / RSI chart. Data comes from the /api/alpaca/quote route
(source.webapp.pages.quote_chart). Read-only: it never places or changes an order."""

from __future__ import annotations

import json

from source.webapp.pages.quote_chart import CHART_CSS

_PANEL_CSS = """
.qp-head { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 16px; margin:8px 0 2px; }
.qp-sym { font-size:22px; font-weight:700; }
.qp-name { font-size:16px; color:var(--ink-muted); }
.qp-news { list-style:none; margin:6px 0 10px; padding:0; }
.qp-news li { padding:8px 0; border-top:1px solid var(--border); }
.qp-news li:first-child { border-top:0; }
.qp-news a { font-weight:600; }
.qp-news .qp-newsmeta { font-size:12px; color:var(--ink-muted); }
.qp-news p { margin:3px 0 0; font-size:13px; }
.qp-price { font-size:26px; font-weight:700; }
.qp-up { color:var(--success); font-weight:600; } .qp-down { color:var(--danger); font-weight:600; }
.qp-stats { display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:8px 14px; margin:10px 0; font-size:13px; }
.qp-stats div span { display:block; color:var(--ink-muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
.qp-ranges { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:10px 24px; margin:6px 0 12px; }
.qp-track { position:relative; height:8px; border-radius:4px; background:color-mix(in srgb, var(--ink-muted) 30%, transparent); margin:6px 0 2px; }
.qp-track i { position:absolute; top:-4px; width:4px; height:16px; border-radius:2px; background:var(--brand); }
.qp-trackl { display:flex; justify-content:space-between; font-size:12px; color:var(--ink-muted); }
.qp-trade { position:relative; display:inline-block; }
.qp-trade > summary { list-style:none; cursor:pointer; display:inline-block; padding:7px 16px; border-radius:999px; background:var(--brand); color:#fff; font-weight:600; font-size:14px; }
.qp-trade > summary::-webkit-details-marker { display:none; }
.qp-trade-menu { position:absolute; right:0; z-index:20; min-width:170px; margin-top:6px; padding:8px; border:1px solid var(--border); border-radius:12px; background:var(--surface); box-shadow:0 12px 28px rgba(0,0,0,.18); display:flex; flex-direction:column; gap:4px; }
.qp-trade-menu a { padding:6px 10px; border-radius:8px; font-weight:600; }
.qp-trade-menu a:hover { background:var(--brand-soft); }
.qp-watch.on { border-color:var(--success); color:var(--success); }
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
.qp-macd { margin:2px 0 8px; font-size:13px; }
.qp-actions { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
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
  function ago(iso) {
    var t = Date.parse(iso); if (isNaN(t)) { return ''; }
    var m = Math.max(0, Math.round((Date.now() - t) / 60000));
    if (m < 60) { return m + ' min ago'; } if (m < 1440) { return Math.round(m / 60) + ' h ago'; }
    var d = Math.round(m / 1440); return d + (d === 1 ? ' day ago' : ' days ago');
  }
  function newsHtml(d) {
    var h = '<h4 style="margin:14px 0 2px;">Latest news about ' + esc(d.symbol) + '</h4>';
    if (!d.news || !d.news.length) {
      return h + '<p class="muted small">' + (d.news_error ? 'News is not available right now.' : 'No recent news found.') + '</p>';
    }
    return h + '<ul class="qp-news">' + d.news.map(function (n) {
      return '<li><a href="' + esc(n.url) + '" target="_blank" rel="noopener noreferrer">' + esc(n.headline) + '</a>' +
        '<div class="qp-newsmeta">' + esc(n.source) + (n.time ? ' \u00B7 ' + esc(ago(n.time)) : '') + '</div>' +
        (n.summary ? '<p>' + esc(n.summary) + '</p>' : '') + '</li>';
    }).join('') + '</ul><p class="muted small">Headlines come from Alpaca\u2019s news feed and open the publisher\u2019s page. They are not recommendations.</p>';
  }
  // "Add to watchlist" and "Trade" sit side by side in the header and again under the chart; the watchlist
  // button reads the saved list, so it turns into "On watchlist" (click again to remove) as soon as it is saved.
  function watchButton() {
    return window.watchHas ? '<button type="button" class="qp-watch" onclick="quoteWatch()"></button> ' : '';
  }
  window.quoteWatchSync = function () {
    var on = !!(cur.symbol && window.watchHas && window.watchHas(cur.symbol));
    Array.prototype.forEach.call(document.querySelectorAll('.qp-watch'), function (b) {
      b.disabled = false; b.className = 'qp-watch' + (on ? ' on' : '');
      b.textContent = on ? '\\u2605 On your watchlist (click to remove)' : '\\u2606 Add ' + cur.symbol + ' to watchlist';
    });
  };
  // Trade opens the order form of the account you pick. With one account it is a plain button; with several
  // it is a small menu (Alpaca, IBKR, E*TRADE) so a real order always goes to the account you chose.
  var TRADE_TARGETS = __TRADE_TARGETS__;
  function tradeButton(sym) {
    var q = '?symbol=' + encodeURIComponent(sym), tip = 'Opens that account\\u2019s order form with ' + esc(sym) + ' filled in. Nothing is sent until you preview and confirm there.';
    if (TRADE_TARGETS.length === 1) {
      return '<a href="' + TRADE_TARGETS[0][1] + q + '" class="pill-link" title="' + tip + '"><button type="button" class="primary">Trade ' + esc(sym) + '</button></a> ';
    }
    return '<details class="qp-trade"><summary class="primary" title="' + tip + '">Trade ' + esc(sym) + ' \\u25BE</summary><div class="qp-trade-menu">' +
      '<span class="muted small">Trade with\\u2026</span>' +
      TRADE_TARGETS.map(function (t) { return '<a href="' + t[1] + q + '">' + esc(t[0]) + '</a>'; }).join('') + '</div></details> ';
  }
  function loadEarn(sym, tries) {
    postJSON('/api/earnings', {symbols: [sym]}).then(function (r) {
      var el = document.getElementById('qp-earn'), it = r.items && r.items[0];
      if (!el || cur.symbol !== sym) { return; }
      if (it && it.date) {
        var dd = new Date(it.date + 'T12:00:00');
        el.className = it.days >= 0 && it.days <= 7 ? 'qp-down' : '';
        el.textContent = dd.toLocaleDateString('en-US', {weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'}) +
          ' (' + (it.days < 0 ? 'already reported this week' : it.days === 0 ? 'today' : it.days === 1 ? 'tomorrow' : 'in ' + it.days + ' days') + ')';
      } else if (it && it.known) {
        el.className = 'muted'; el.textContent = 'None scheduled (funds and ETFs do not report earnings)';
      } else if (r.pending > 0 && tries < 3) {
        setTimeout(function () { loadEarn(sym, tries + 1); }, 6000);
      } else {
        el.className = 'muted'; el.textContent = 'Not available right now';
      }
    }).catch(function () { var el = document.getElementById('qp-earn'); if (el) { el.textContent = 'Not available right now'; } });
  }
  function macdText(m) {
    if (!m || !m.state) { return '<span class="muted">Not enough history</span>'; }
    var ago = m.bars_ago == null ? '' : (m.bars_ago === 0 ? 'today' : m.bars_ago === 1 ? 'yesterday' : m.bars_ago + ' trading days ago');
    var cross = !m.cross ? 'No crossover yet' : (m.cross === 'bullish' ? '<span class="qp-up">\\u25B2 Bullish crossover</span>' : '<span class="qp-down">\\u25BC Bearish crossover</span>') + ' ' + ago;
    return cross + ' <span class="muted">\u00B7 MACD is ' + m.state + ' its signal line</span>';
  }
  function badgeClass(label) { return /Buy/.test(label) ? 'qp-b-buy' : /Sell/.test(label) ? 'qp-b-sell' : 'qp-b-hold'; }
  function render(d) {
    var q = d.quote, up = (q.change || 0) >= 0, r = d.rating;
    cur.symbol = d.symbol; cur.range = d.range; cur.rows = d.rows;
    var arrow = up ? '\\u25B2' : '\\u25BC';
    var h = '<div class="qp-head"><span class="qp-sym">' + esc(d.symbol) + '</span>' + (d.name ? '<span class="qp-name">' + esc(d.name) + '</span>' : '') + '<span class="qp-price">' + usd(q.price) + '</span>' +
      '<span class="' + (up ? 'qp-up' : 'qp-down') + '">' + arrow + ' ' + signed(q.change) + ' (' + signed(q.change_pct, '%') + ') today</span>' +
      '<span style="margin-left:auto;">' + watchButton() + tradeButton(d.symbol) + '</span></div>';
    if (d.extended) {
      var xe = d.extended, xu = (xe.change || 0) >= 0;
      h += '<div class="qp-ext" style="margin:-4px 0 8px;"><strong>' + esc(xe.label) + '</strong> ' + usd(xe.price) +
        (xe.change == null ? '' : ' <span class="' + (xu ? 'qp-up' : 'qp-down') + '">' + (xu ? '\\u25B2 ' : '\\u25BC ') + signed(xe.change) + (xe.change_pct == null ? '' : ' (' + signed(xe.change_pct, '%') + ')') + '</span>') +
        ' <span class="muted small">Yahoo Finance; thinly traded, so it can move a lot.</span></div>';
    }
    h += '<div class="qp-stats">' +
      '<div><span>Open</span>' + usd(q.open) + '</div><div><span>Day high</span>' + usd(q.high) + '</div><div><span>Day low</span>' + usd(q.low) + '</div>' +
      '<div><span>Previous close</span>' + usd(q.prev_close) + '</div><div><span>Volume today</span>' + vol(q.volume) + '</div>' +
      '<div><span>Bid</span>' + usd(q.bid) + (q.bid_size ? ' x ' + q.bid_size : '') + '</div><div><span>Ask</span>' + usd(q.ask) + (q.ask_size ? ' x ' + q.ask_size : '') + '</div></div>';
    h += '<div class="qp-ranges">' + track(q.low, q.high, q.day_position, 'Low', 'High', 'Day range') +
      track(d.week52.low, d.week52.high, d.week52.position, 'Low', 'High', '52-week range') + '</div>';
    h += '<div class="qp-rate"><strong>Technical rating</strong><span class="qp-badge ' + badgeClass(r.label) + '">' + esc(r.label) + '</span>' +
      (r.of ? '<span class="muted">' + r.buy_votes + ' of ' + r.of + ' signals bullish, ' + r.sell_votes + ' bearish</span>' : '') + '</div>';
    h += '<p class="qp-macd"><strong>MACD crossover:</strong> ' + macdText(d.macd) + '</p>';
    h += '<p class="qp-macd"><strong>Next earnings:</strong> <span id="qp-earn" class="muted">checking\\u2026</span></p>';
    h += '<div class="qp-cols"><div><ul class="qp-sig">' + r.signals.map(function (s) {
      return '<li><b class="' + (s.vote > 0 ? 'qp-up' : s.vote < 0 ? 'qp-down' : 'muted') + '">' + (s.vote > 0 ? '\\u25B2' : s.vote < 0 ? '\\u25BC' : '\\u25AC') + '</b><span><strong>' +
        esc(s.name) + '.</strong> ' + esc(s.text) + '</span></li>'; }).join('') + '</ul></div>' +
      '<div><table><thead><tr><th>Trend</th><th>Direction</th><th class="num">Change</th></tr></thead><tbody>' + d.trends.map(function (t) {
        var cls = t.direction === 'Up' ? 'qp-up' : t.direction === 'Down' ? 'qp-down' : '';
        var mark = t.direction === 'Up' ? '\\u25B2 ' : t.direction === 'Down' ? '\\u25BC ' : '';
        return '<tr><td>' + esc(t.label) + '</td><td class="' + cls + '">' + mark + esc(t.direction) + '</td><td class="num">' + (t.change_pct == null ? '--' : signed(t.change_pct, '%')) + '</td></tr>';
      }).join('') + '</tbody></table></div></div>';
    h += '<div class="qp-pills">' + pills() + '</div><div id="qp-read" class="qp-read">Move over the chart for the numbers on any bar. Hollow candle = closed up, filled = closed down. Triangles on the MACD panel mark crossovers (green up = bullish, red down = bearish).</div>' + d.chart;
    h += '<p class="muted small">Technical signals only: moving averages, RSI, MACD and volume, counted on daily prices. It is not advice and this app never places an order from it. ' +
      (d.data_source === 'yahoo' ? 'Prices come from Yahoo Finance because Alpaca prices were not available (Yahoo\\u2019s free data can lag by a few minutes).</p>' : 'Prices come from Alpaca\\u2019s free IEX feed, so volume is IEX\\u2019s share of the market, not the whole market\\u2019s.</p>') +
      newsHtml(d) +
      '<p class="qp-actions">' + watchButton() + tradeButton(d.symbol) +
      '</p>';
    document.getElementById('qp-out').innerHTML = h;
    window.quoteWatchSync();
    loadEarn(d.symbol, 0);
    var hit = document.getElementById('qc-hit'); if (hit) { hit.addEventListener('mousemove', hover); hit.addEventListener('mouseleave', leave); }
  }
  function hover(e) {
    var svg = document.querySelector('svg.qc'); if (!svg) { return; }
    var box = svg.getBoundingClientRect(), n = +svg.dataset.n, left = +svg.dataset.left, pw = +svg.dataset.pw, w = +svg.dataset.w;
    var x = (e.clientX - box.left) * (w / box.width);
    var i = Math.max(0, Math.min(n - 1, Math.floor((x - left) / (pw / n)))), r = cur.rows[i]; if (!r) { return; }
    var k = box.width / w, cx = left + (i + 0.5) * (pw / n);
    var line = document.getElementById('qc-cross'); line.setAttribute('x1', cx); line.setAttribute('x2', cx); line.style.display = '';
    var lo = +svg.dataset.lo, hi = +svg.dataset.hi, top = +svg.dataset.ptop, ph = +svg.dataset.ph;
    var dot = document.getElementById('qc-dot');
    dot.setAttribute('cx', cx); dot.setAttribute('cy', top + (hi - r.c) / (hi - lo) * ph); dot.style.display = '';
    var up = r.c >= r.o;
    function row(name, val, cls) { return '<div class="nw-tip-row"><span class="nw-tip-name">' + name + '</span><span class="nw-tip-val ' + (cls || '') + '">' + val + '</span></div>'; }
    var h = '<div class="nw-tip-date">' + esc(r.t) + '</div>' +
      row('Open', usd(r.o)) + row('High', usd(r.h)) + row('Low', usd(r.l)) + row('Close', usd(r.c), up ? 'qp-up' : 'qp-down') + row('Volume', vol(r.v));
    if (r.a != null || r.b != null || r.c2 != null) {
      h += '<hr>' + (r.a != null ? row(cur.range === '1D' ? 'VWAP' : '20-day avg', usd(r.a)) : '') + (r.b != null ? row('50-day avg', usd(r.b)) : '') + (r.c2 != null ? row('200-day avg', usd(r.c2)) : '');
    }
    if (r.rsi != null || r.m != null) {
      h += '<hr>' + (r.rsi != null ? row('RSI (14)', r.rsi.toFixed(0), r.rsi <= 30 ? 'qp-up' : r.rsi >= 70 ? 'qp-down' : '') : '') +
        (r.m != null && r.ms != null ? row('MACD', r.m.toFixed(2)) + row('Signal', r.ms.toFixed(2)) + row('Histogram', r.mh.toFixed(2), r.mh >= 0 ? 'qp-up' : 'qp-down') : '');
    }
    var tip = document.querySelector('.qc-tip'); tip.innerHTML = h; tip.hidden = false;
    var wrap = tip.parentNode.getBoundingClientRect(), px = cx * k, tw = tip.offsetWidth;
    var tx = px + 16; if (tx + tw > wrap.width) { tx = px - tw - 16; }
    tip.style.left = Math.max(0, tx) + 'px';
    tip.style.top = Math.max(0, Math.min((e.clientY - wrap.top) - tip.offsetHeight / 2, wrap.height - tip.offsetHeight)) + 'px';
  }
  function leave() {
    ['qc-cross', 'qc-dot'].forEach(function (id) { var l = document.getElementById(id); if (l) { l.style.display = 'none'; } });
    var tip = document.querySelector('.qc-tip'); if (tip) { tip.hidden = true; }
  }
  window.lookupQuote = function (sym, range) {
    sym = String(sym || '').trim().toUpperCase(); if (!sym) { return; }
    var out = document.getElementById('qp-out'), box = document.getElementById('quote');
    document.getElementById('qp-symbol').value = sym;
    out.innerHTML = '<p class="muted">Loading ' + esc(sym) + '&hellip;</p>';
    postJSON('/api/alpaca/quote', {mode: MODE, symbol: sym, range: range || cur.range}).then(render)
      .catch(function (e) { out.innerHTML = '<p class="status-line status-warn">' + esc(e.message) + '</p>'; });
    if (box && !range) { box.scrollIntoView({behavior: 'smooth', block: 'start'}); }
  };
  window.quoteWatch = function () {
    if (!window.watchAdd || !cur.symbol) { return; }
    var sym = cur.symbol, on = window.watchHas(sym);
    Array.prototype.forEach.call(document.querySelectorAll('.qp-watch'), function (b) { b.disabled = true; });
    (on ? window.watchRemove(sym) : window.watchAdd(sym)).then(window.quoteWatchSync, window.quoteWatchSync);
  };
  var params = new URLSearchParams(location.search);
  if (params.get('symbol')) {   // postJSON is defined further down the page, so wait until the page has loaded
    var go = function () { window.lookupQuote(params.get('symbol')); };
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', go); } else { go(); }
  }
})();
</script>
"""


def trade_targets() -> list[list[str]]:
    """[[label, page], ...]: the real-money accounts the Trade button can open (Alpaca when its live keys are saved,
    IBKR always since its gateway needs no saved secret, E*TRADE once its keys are saved)."""
    from source.common import secrets_store
    out = []
    try:
        if secrets_store.has_alpaca_keys(mode="live"):
            out.append(["Alpaca", "/trading-live.html"])
        out.append(["IBKR", "/ibkr.html"])
        if secrets_store.has_broker_secret("etrade"):
            out.append(["E*TRADE", "/etrade.html"])
    except Exception:       # a locked Keychain must not break the page
        out = [["Alpaca", "/trading-live.html"], ["IBKR", "/ibkr.html"]]
    return out


def quote_panel_html(mode: str = "auto") -> str:
    """``mode`` picks which saved Alpaca keys read the prices; \"auto\" prefers the practice keys."""
    return f"""
<style>{CHART_CSS}{_PANEL_CSS}</style>
<div class="card" id="quote">
<h3 style="margin-top:0;">Quote and chart</h3>
<p class="muted">Look up any stock or ETF: price, day range, trend, a buy / sell rating from the chart, and a price, volume and RSI chart.
Looking things up never places an order and works even while live trading is off.</p>
<form class="inline" onsubmit="event.preventDefault(); lookupQuote(this.symbol.value);">
  <label>Symbol<input id="qp-symbol" name="symbol" autocomplete="off" style="width:110px; text-transform:uppercase;" placeholder="AAPL" required></label>
  <button type="submit" class="primary">Look up</button>
</form>
<div id="qp-out"></div>
</div>
{_PANEL_JS.replace("__MODE__", mode).replace("__TRADE_TARGETS__", json.dumps(trade_targets()))}
"""
