"""The Stock Analysis tab's watchlist: a table of the tickers the owner follows,
with price, day change, day and 52-week range, RSI, short / medium / long trend
and the same technical buy / sell rating the quote panel shows.

``build_rows`` does the work for the /api/watchlist/data route: one call for
today's quotes and one (paged) call for about 14 months of daily bars for the
whole list, then source.reporting.technicals over each symbol's bars. Read-only:
nothing here can place or change an order. The ticker list itself lives in
source.common.db.watchlist; prices are never stored."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from source.collector import alpaca
from source.reporting import technicals as ta
from source.webapp.pages.quote_chart import HISTORY_DAYS, _iso, _quote_block, company_names

_EXAMPLES = ("SPY", "VTI", "QQQ", "AAPL", "MSFT")


def _row(item: dict, snap: dict | None, daily: list[dict]) -> dict:
    sym = item["symbol"]
    base = {"symbol": sym, "note": item.get("note") or ""}
    if not daily:
        return {**base, "error": "No price history found. Check the ticker."}
    quote = _quote_block(sym, snap, daily)
    rsi_now = next((v for v in reversed(ta.rsi([b["c"] for b in daily])) if v is not None), None)
    trend = {t["window"]: t for t in ta.trends(daily)}
    rating = ta.rating(daily)
    week = ta.range_stats(daily[-253:], quote["price"])
    return {
        **base,
        "price": quote["price"], "change": quote["change"], "change_pct": quote["change_pct"],
        "day_low": quote["low"], "day_high": quote["high"], "day_position": quote["day_position"],
        "volume": quote["volume"],
        "week_low": week["low"], "week_high": week["high"], "week_position": week["position"],
        "rsi": rsi_now,
        "trend_short": trend[20]["direction"], "trend_medium": trend[50]["direction"], "trend_long": trend[200]["direction"],
        "rating": rating["label"], "rating_score": rating["ratio"] if rating["of"] else None,
        "as_of": quote["as_of"],
    }


def build_rows(items: list[dict], keys: tuple[str, str], *, mode: str | None = None, now: datetime | None = None, **kw) -> list[dict]:
    """One JSON-ready row per watchlist item, in the list's own order."""
    if not items:
        return []
    now = now or datetime.now(timezone.utc)
    symbols = [i["symbol"] for i in items]
    bars = alpaca.get_bars_multi(symbols, keys, start=_iso(now - timedelta(days=HISTORY_DAYS)), **kw)
    try:
        snaps = alpaca.get_snapshots(symbols, keys, **kw)
    except alpaca.AlpacaError:
        snaps = {}   # the daily bars still give a last price
    names = company_names(symbols, keys, mode, **kw) if mode else {}
    rows = [_row(i, snaps.get(i["symbol"]), bars.get(i["symbol"]) or []) for i in items]
    for row in rows:
        row["name"] = names.get(row["symbol"], "")
    return rows


_CSS = """
.wl-bar { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; margin:8px 0; }
.wl-bar .grow { flex:1 1 auto; }
.wl-wrap { overflow-x:auto; }
#wl-table th.sortable { cursor:pointer; white-space:nowrap; user-select:none; }
#wl-table th.sortable:hover { color:var(--brand); }
#wl-table td { vertical-align:middle; }
.wl-sym { font-weight:700; }
.wl-name { font-size:11px; color:var(--ink-muted); max-width:170px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.wl-mini { width:96px; }
.wl-mini .qp-track { margin:3px 0 1px; }
.wl-mini .qp-trackl { font-size:10px; }
.wl-trend { white-space:nowrap; letter-spacing:2px; font-size:12px; }
.wl-note { width:150px; font-size:12px; padding:3px 6px; }
.wl-rsi-lo { color:var(--success); font-weight:600; } .wl-rsi-hi { color:var(--danger); font-weight:600; }
.wl-empty { padding:10px 0; }
.wl-chips button { margin:2px 4px 2px 0; }
.wl-trade { padding:3px 12px; font-size:12px; }
.wl-x { border:0; background:transparent; color:var(--ink-muted); font-size:16px; cursor:pointer; padding:2px 6px; }
.wl-x:hover { color:var(--danger); }
"""

_JS = """
<script>
(function () {
  var rows = [], sortKey = null, sortDir = 1, timer = null;
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function usd(n) { return n == null ? '--' : '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
  function vol(n) { return n == null ? '--' : (n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(Math.round(n))); }
  function signed(n, suffix) { return n == null ? '--' : (n >= 0 ? '+' : '-') + Math.abs(n).toFixed(2) + (suffix || ''); }
  function badgeClass(label) { return /Buy/.test(label) ? 'qp-b-buy' : /Sell/.test(label) ? 'qp-b-sell' : 'qp-b-hold'; }
  function mini(low, high, pos) {
    if (low == null || high == null || pos == null) { return '<span class="muted">--</span>'; }
    return '<div class="wl-mini"><div class="qp-track"><i style="left:calc(' + (pos * 100).toFixed(1) + '% - 2px)"></i></div>' +
      '<div class="qp-trackl"><span>' + Number(low).toFixed(2) + '</span><span>' + Number(high).toFixed(2) + '</span></div></div>';
  }
  function arrow(dir, label) {
    var up = dir === 'Up', down = dir === 'Down';
    return '<span class="' + (up ? 'qp-up' : down ? 'qp-down' : 'muted') + '" title="' + esc(label + ': ' + dir) + '">' + (up ? '\\u25B2' : down ? '\\u25BC' : '\\u25AC') + '</span>';
  }
  var COLS = [
    ['symbol', 'Symbol', false], ['price', 'Price', true], ['change', 'Change', true], ['change_pct', 'Change %', true],
    ['day_position', 'Day range', true], ['week_position', '52-week range', true], ['volume', 'Volume', true],
    ['rsi', 'RSI', true], ['trend_long', 'Trend', false], ['rating_score', 'Rating', true]
  ];
  function sorted() {
    if (!sortKey) { return rows.slice(); }
    return rows.slice().sort(function (a, b) {
      var x = a[sortKey], y = b[sortKey];
      if (x == null && y == null) { return 0; } if (x == null) { return 1; } if (y == null) { return -1; }
      return (x < y ? -1 : x > y ? 1 : 0) * sortDir;
    });
  }
  function render() {
    var out = document.getElementById('wl-out');
    if (!rows.length) {
      out.innerHTML = '<p class="muted wl-empty">Your watchlist is empty. Type a ticker above, or start with one of these: ' +
        '<span class="wl-chips">' + __EXAMPLES__.map(function (s) { return '<button type="button" onclick="watchAdd(\\'' + s + '\\')">' + s + '</button>'; }).join('') + '</span></p>';
      return;
    }
    var head = COLS.map(function (c) {
      var mark = sortKey === c[0] ? (sortDir > 0 ? ' \\u25B2' : ' \\u25BC') : '';
      return '<th class="' + (c[0] === 'symbol' ? '' : 'num ') + (c[2] || c[0] === 'symbol' ? 'sortable' : '') + '"' +
        (c[2] || c[0] === 'symbol' ? ' onclick="watchSort(\\'' + c[0] + '\\')"' : '') + '>' + c[1] + mark + '</th>';
    }).join('') + '<th>Note</th><th></th>';
    var body = sorted().map(function (r) {
      var s = esc(r.symbol), note = '<td><input class="wl-note" maxlength="120" placeholder="Add a note" value="' + esc(r.note || '') +
        '" onchange="watchNote(\\'' + s + '\\', this.value)"></td>';
      var act = '<td style="white-space:nowrap;"><a href="/trading-live.html?symbol=' + encodeURIComponent(r.symbol) + '" class="pill-link" title="Open the live order form for ' + s + '">' +
        '<button type="button" class="primary wl-trade">Trade</button></a> <button type="button" class="wl-x" title="Remove ' + s + '" onclick="watchRemove(\\'' + s + '\\')">\\u00D7</button></td>';
      if (r.error) {
        return '<tr><td class="wl-sym">' + s + (r.name ? '<div class="wl-name">' + esc(r.name) + '</div>' : '') + '</td><td colspan="9" class="muted">' + esc(r.error) + '</td>' + note + act + '</tr>';
      }
      var up = (r.change || 0) >= 0, cls = r.change == null ? '' : up ? 'qp-up' : 'qp-down';
      var rsiCls = r.rsi == null ? '' : r.rsi <= 30 ? 'wl-rsi-lo' : r.rsi >= 70 ? 'wl-rsi-hi' : '';
      return '<tr><td><a href="#quote" class="wl-sym" title="Open the chart and rating" onclick="lookupQuote(\\'' + s + '\\'); return false;">' + s + '</a>' +
        (r.name ? '<div class="wl-name" title="' + esc(r.name) + '">' + esc(r.name) + '</div>' : '') + '</td>' +
        '<td class="num">' + usd(r.price) + '</td><td class="num ' + cls + '">' + signed(r.change) + '</td><td class="num ' + cls + '">' + signed(r.change_pct, '%') + '</td>' +
        '<td class="num">' + mini(r.day_low, r.day_high, r.day_position) + '</td><td class="num">' + mini(r.week_low, r.week_high, r.week_position) + '</td>' +
        '<td class="num">' + vol(r.volume) + '</td><td class="num ' + rsiCls + '">' + (r.rsi == null ? '--' : r.rsi.toFixed(0)) + '</td>' +
        '<td class="num wl-trend">' + arrow(r.trend_short, 'Short term (about 1 month)') + arrow(r.trend_medium, 'Medium term (about 3 months)') + arrow(r.trend_long, 'Long term (about 1 year)') + '</td>' +
        '<td class="num"><span class="qp-badge ' + badgeClass(r.rating) + '" style="font-size:12px; padding:2px 10px;">' + esc(r.rating) + '</span></td>' + note + act + '</tr>';
    }).join('');
    out.innerHTML = '<div class="wl-wrap"><table id="wl-table"><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
  }
  function status(text, warn) {
    var el = document.getElementById('wl-status');
    el.textContent = text; el.className = warn ? 'status-line status-warn' : 'muted small';
  }
  function load() {
    status('Loading prices\\u2026');
    return postJSON('/api/watchlist/data', {}).then(function (d) {
      rows = d.rows; render();
      status(rows.length ? 'Updated ' + new Date().toLocaleTimeString() + '. Prices refresh by themselves every minute.' : '');
      if (timer) { clearInterval(timer); }
      if (rows.length) { timer = setInterval(function () { if (!document.hidden) { load(); } }, 60000); }
    }).catch(function (e) { status(e.message, true); });
  }
  window.watchSort = function (key) {
    if (sortKey === key) { sortDir = -sortDir; } else { sortKey = key; sortDir = key === 'symbol' ? 1 : -1; }
    render();
  };
  window.watchAdd = function (text) {
    return postJSON('/api/watchlist/add', {symbol: text}).then(function () { return load(); })
      .catch(function (e) { status(e.message, true); });
  };
  window.watchRemove = function (sym) {
    postJSON('/api/watchlist/remove', {symbol: sym}).then(function () { rows = rows.filter(function (r) { return r.symbol !== sym; }); render(); if (!rows.length) { status(''); } })
      .catch(function (e) { status(e.message, true); });
  };
  window.watchNote = function (sym, text) {
    postJSON('/api/watchlist/note', {symbol: sym, note: text}).then(function () {
      rows.forEach(function (r) { if (r.symbol === sym) { r.note = text; } });
    }).catch(function (e) { status(e.message, true); });
  };
  window.watchRefresh = load;
  document.getElementById('wl-form').addEventListener('submit', function (ev) {
    ev.preventDefault(); var box = this.symbol, text = box.value;
    if (!text.trim()) { return; }
    window.watchAdd(text).then(function () { box.value = ''; });
  });
  // postJSON is defined further down the page, so wait until the page has loaded
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', load); } else { load(); }
})();
</script>
"""


def watchlist_card_html() -> str:
    js = _JS.replace("__EXAMPLES__", "[" + ",".join(f"'{s}'" for s in _EXAMPLES) + "]")
    return f"""
<style>{_CSS}</style>
<div class="card" id="watchlist">
<h3 style="margin-top:0;">Watchlist</h3>
<p class="muted">Tickers you want to keep an eye on. Click a symbol to open its chart and rating below; click a column heading to sort.
Reading prices never places an order.</p>
<form id="wl-form" class="inline wl-bar">
  <label>Add tickers<input name="symbol" autocomplete="off" style="width:200px; text-transform:uppercase;" placeholder="AAPL, MSFT, VTI"></label>
  <button type="submit" class="primary">Add to watchlist</button>
  <button type="button" onclick="watchRefresh()">Refresh prices</button>
</form>
<p id="wl-status" class="muted small"></p>
<div id="wl-out"></div>
<p class="muted small">Rating counts moving-average, RSI, MACD and volume signals on daily prices. Trend arrows are short (about a month), medium (about 3 months) and long (about a year). Technical signals only, not advice.</p>
</div>
{js}
"""
