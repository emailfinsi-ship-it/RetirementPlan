"""A technical rating beside each stock you hold (Alpaca Live Account, IBKR and E*TRADE tabs), and a hover box over the
symbol with the analysis behind it. Both come from /api/ratings, which reads daily prices from Alpaca's free market data
(the same data and the same rating as Stock Analysis). Read-only: it never places an order and is not advice."""

from __future__ import annotations

import html

CSS = """
.pr-badge { display:inline-block; padding:2px 10px; border-radius:999px; font-weight:700; font-size:12px; border:2px solid var(--border); white-space:nowrap; cursor:default; }
.nw-tip .nw-tip-pct { white-space:pre-line; max-width:270px; line-height:1.45; }
.pr-buy { color:var(--success); border-color:var(--success); } .pr-hold { color:var(--warn); border-color:var(--warn); } .pr-sell { color:var(--danger); border-color:var(--danger); }
"""

JS = r"""
<script>
(function () {
  var cache = {}, TTL = 5 * 60 * 1000;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function cls(label) { return /Buy/.test(label) ? 'pr-buy' : /Sell/.test(label) ? 'pr-sell' : 'pr-hold'; }
  function color(label) { return /Buy/.test(label) ? '#1f8a3f' : /Sell/.test(label) ? '#d70015' : '#b36200'; }
  function trend(t) { return t === 'Up' ? 'up' : t === 'Down' ? 'down' : 'sideways'; }
  function arrow(t) { return t === 'Up' ? '▲' : t === 'Down' ? '▼' : '▬'; }
  function note(it, skipVotes) {
    // one short fact per line (the hover box keeps the line breaks), instead of one long run-on sentence
    var p = [];
    if (it.signal_count && !skipVotes) { p.push('Signals: ' + it.buy_votes + ' of ' + it.signal_count + ' bullish, ' + it.sell_votes + ' bearish'); }
    if (it.rsi != null) { p.push('RSI: ' + Math.round(it.rsi) + (it.rsi <= 30 ? ' (oversold)' : it.rsi >= 70 ? ' (overbought)' : '')); }
    if (it.macd_state) {
      var when = it.macd_ago === 0 ? 'today' : it.macd_ago === 1 ? 'yesterday' : it.macd_ago + ' days ago';
      p.push('MACD: ' + it.macd_state + ' signal line (' + (it.macd_state === 'above' ? 'momentum rising' : 'momentum fading') + ')' + (it.macd_cross ? '\n' + it.macd_cross + ' crossover ' + when : ''));
    }
    p.push('Trend: ' + arrow(it.trend_short) + ' 1 month \u00B7 ' + arrow(it.trend_medium) + ' 3 months \u00B7 ' + arrow(it.trend_long) + ' 1 year');
    p.push('Click the symbol for the chart. Not advice.');
    return p.join('\n');
  }
  function paint() {
    Array.prototype.forEach.call(document.querySelectorAll('td[data-rate-sym]'), function (td) {
      var sym = td.getAttribute('data-rate-sym'), it = cache[sym] && cache[sym].item, link = td.parentNode.querySelector('a');
      if (!it) { return; }
      if (it.error || !it.rating) { td.innerHTML = '<span class="muted" title="' + esc(it.error || 'No rating yet') + '">--</span>'; return; }
      td.innerHTML = '<span class="pr-badge ' + cls(it.rating) + '" data-ctip="' + esc(sym + ' · ' + it.rating) + '" data-ctip-note="' + esc(note(it)) + '">' + esc(it.rating) + '</span>';
      if (link) {
        link.setAttribute('data-ctip', sym + (it.name ? ' · ' + it.name : ''));
        link.setAttribute('data-ctip-val', it.rating + (it.signal_count ? ' · ' + it.buy_votes + ' of ' + it.signal_count + ' signals bullish' : ''));
        link.setAttribute('data-ctip-color', color(it.rating));
        link.setAttribute('data-ctip-note', note(it, true));
        link.removeAttribute('title');
      }
    });
  }
  window.applyRatings = function () {
    var now = Date.now(), syms = [];
    Array.prototype.forEach.call(document.querySelectorAll('td[data-rate-sym]'), function (td) {
      var s = td.getAttribute('data-rate-sym');
      if (syms.indexOf(s) < 0 && !(cache[s] && now - cache[s].at < TTL)) { syms.push(s); }
    });
    paint();
    if (!syms.length) { return; }
    postJSON('/api/ratings', {symbols: syms}).then(function (d) {
      (d.items || []).forEach(function (it) { cache[it.symbol] = {item: it, at: Date.now()}; });
      paint();
    }).catch(function () {
      Array.prototype.forEach.call(document.querySelectorAll('td[data-rate-sym]'), function (td) { if (!td.querySelector('.pr-badge')) { td.innerHTML = '<span class="muted" title="Ratings could not be loaded">--</span>'; } });
    });
  };
  // postJSON is defined further down the page, so wait until the page has loaded
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', window.applyRatings); } else { window.applyRatings(); }
})();
</script>
"""


def rating_cell(symbol: str) -> str:
    """The table cell the script fills in for this symbol."""
    return f'<td data-rate-sym="{html.escape(symbol, quote=True)}"><span class="muted">&hellip;</span></td>'


def block() -> str:
    return f"<style>{CSS}</style>{JS}"
