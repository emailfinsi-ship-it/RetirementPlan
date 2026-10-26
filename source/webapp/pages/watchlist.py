"""The Stock Analysis tab's watchlist: a table of the tickers the owner follows,
with price, day change, day and 52-week range, RSI, short / medium / long trend
and the same technical buy / sell rating the quote panel shows.

``build_rows`` does the work for the /api/watchlist/data route: one call for
today's quotes and one (paged) call for about 14 months of daily bars for the
whole list, then source.reporting.technicals over each symbol's bars. Read-only:
nothing here can place or change an order. The ticker list itself lives in
source.common.db.watchlist; prices are never stored."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from source.collector import alpaca
from source.common import db
from source.reporting import technicals as ta
from source.webapp.pages.quote_chart import HISTORY_DAYS, _iso, _quote_block, company_names

_EXAMPLES = ("SPY", "VTI", "QQQ", "AAPL", "MSFT")


def stored_rows(items: list[dict], message: str = "") -> list[dict]:
    """The saved tickers with no prices (company names only if looked up before).
    Shown as soon as the page opens, and used when prices cannot be read, so a
    price-feed problem never makes the saved list look lost."""
    names = db.watchlist.cached_names([i["symbol"] for i in items]) if items else {}
    return [
        {"symbol": i["symbol"], "note": i.get("note") or "", "name": names.get(i["symbol"], ""),
         "pending": True, "error": message}
        for i in items
    ]


def _row(item: dict, snap: dict | None, daily: list[dict]) -> dict:
    sym = item["symbol"]
    base = {"symbol": sym, "note": item.get("note") or ""}
    if not daily:
        return {**base, "error": "No price history found. Check the ticker."}
    quote = _quote_block(sym, snap, daily)
    rsi_now = next((v for v in reversed(ta.rsi([b["c"] for b in daily])) if v is not None), None)
    trend = {t["window"]: t for t in ta.trends(daily)}
    rating = ta.rating(daily)
    macd = ta.macd_status(daily)
    week = ta.range_stats(daily[-253:], quote["price"])
    return {
        **base,
        "price": quote["price"], "change": quote["change"], "change_pct": quote["change_pct"],
        "day_low": quote["low"], "day_high": quote["high"], "day_position": quote["day_position"],
        "volume": quote["volume"],
        "week_low": week["low"], "week_high": week["high"], "week_position": week["position"],
        "rsi": rsi_now,
        "macd_state": macd["state"], "macd_cross": macd["cross"], "macd_ago": macd["bars_ago"],
        "macd_sort": None if macd["state"] is None else (1 if macd["state"] == "above" else -1),
        "trend_short": trend[20]["direction"], "trend_medium": trend[50]["direction"], "trend_long": trend[200]["direction"],
        "rating": rating["label"], "rating_score": rating["ratio"] if rating["of"] else None,
        "buy_votes": rating["buy_votes"], "sell_votes": rating["sell_votes"], "signal_count": rating["of"],
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
details.fold > summary { cursor:pointer; list-style:none; display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
details.fold > summary::-webkit-details-marker { display:none; }
details.fold > summary h3 { margin:0; display:inline; }
details.fold > summary::before { content:'\\25B8'; color:var(--ink-muted); font-size:14px; }
details.fold[open] > summary::before { content:'\\25BE'; }
details.fold > summary .fold-hint { color:var(--ink-muted); font-size:12px; }
details.fold[open] > summary { margin-bottom:8px; }
details.fold[open] > summary .fold-closed { display:none; }

.wl-bar { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; margin:8px 0; }
.wl-bar .grow { flex:1 1 auto; }
.wl-wrap { overflow-x:auto; }
#wl-table { width:100%; font-size:12px; }
#wl-table th, #wl-table td { padding:6px 5px; }
#wl-table th { font-size:10px; }
#wl-table th.sortable { cursor:pointer; white-space:nowrap; user-select:none; }
#wl-table th.sortable:hover { color:var(--brand); }
#wl-table td { vertical-align:middle; }
#wl-table td.num { white-space:nowrap; }
.wl-sym { font-weight:700; font-size:13px; }
.wl-sub { display:block; font-size:11px; font-weight:400; color:var(--ink-muted); }
.wl-sub.qp-up, .wl-sub.qp-down { font-weight:500; }
.wl-mini { width:70px; margin-left:auto; }
.wl-mini .qp-track { margin:3px 0 1px; }
.wl-mini .qp-trackl { font-size:10px; }
.wl-earn-soon { font-weight:700; color:var(--warn); }
.wl-trend { white-space:nowrap; letter-spacing:1px; font-size:12px; }
.wl-note { width:100%; min-width:84px; font-size:12px; padding:3px 6px; }
.wl-rsi-lo { color:var(--success); font-weight:600; } .wl-rsi-hi { color:var(--danger); font-weight:600; }
#wl-table .wl-badge { font-size:11px; padding:2px 8px; border-width:1.5px; white-space:nowrap; }
.wl-empty { padding:10px 0; }
.wl-chips button { margin:2px 4px 2px 0; }
.wl-trade { padding:3px 10px; font-size:12px; }
.wl-x { border:0; background:transparent; color:var(--ink-muted); font-size:16px; cursor:pointer; padding:2px 4px; }
.wl-x:hover { color:var(--danger); }
"""

_JS = """
<script>
(function () {
  var rows = __INITIAL__, earnBy = {}, earnTries = 0, earnTimer = null, sortKey = null, sortDir = 1, timer = null;
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
    ['symbol', 'Symbol', false], ['price', 'Price', true], ['change_pct', 'Change', true],
    ['day_position', 'Day range', true], ['week_position', '52-week', true], ['volume', 'Volume', true],
    ['rsi', 'RSI', true], ['macd_sort', 'MACD', true], ['earn_date', 'Next earnings', true], ['trend_long', 'Trend', false], ['rating_score', 'Rating', true]
  ];
  function sorted() {
    if (!sortKey) { return rows.slice(); }
    return rows.slice().sort(function (a, b) {
      var x = a[sortKey], y = b[sortKey];
      if (x == null && y == null) { return 0; } if (x == null) { return 1; } if (y == null) { return -1; }
      return (x < y ? -1 : x > y ? 1 : 0) * sortDir;
    });
  }
  // The company name shows in the shared hover box over the symbol (saves a line of column width).
  function symLink(r) {
    var s = esc(r.symbol);
    return '<a href="#quote" class="wl-sym" ' + (r.name ? 'data-ctip="' + esc(r.name) + '" data-ctip-note="Click to open the chart and rating"' : 'title="Open the chart and rating"') +
      ' onclick="lookupQuote(\\'' + s + '\\'); return false;">' + s + '</a>';
  }
  function count() {
    var el = document.getElementById('wl-count'); if (!el) { return; }
    el.textContent = rows.length ? rows.length + (rows.length === 1 ? ' stock' : ' stocks') : '';
  }
  function render() { draw(); count(); syncQuote(); }
  function draw() {
    var out = document.getElementById('wl-out');
    if (!rows.length) {
      out.innerHTML = '<p class="muted wl-empty">Your watchlist is empty. Look up a stock in Quote and chart below and press Add to watchlist, or start with one of these: ' +
        '<span class="wl-chips">' + __EXAMPLES__.map(function (s) { return '<button type="button" onclick="watchAdd(\\'' + s + '\\')">' + s + '</button>'; }).join('') + '</span></p>';
      return;
    }
    var head = COLS.map(function (c) {
      var mark = sortKey === c[0] ? (sortDir > 0 ? ' \\u25B2' : ' \\u25BC') : '';
      return '<th class="' + (c[0] === 'symbol' ? '' : 'num ') + (c[2] || c[0] === 'symbol' ? 'sortable' : '') + '"' +
        (c[2] || c[0] === 'symbol' ? ' onclick="watchSort(\\'' + c[0] + '\\')"' : '') + '>' + c[1] + mark + '</th>';
    }).join('') + '<th></th><th>Note</th>';
    var body = sorted().map(function (r) {
      var s = esc(r.symbol), note = '<td><input class="wl-note" maxlength="120" placeholder="Add a note" value="' + esc(r.note || '') +
        '" onchange="watchNote(\\'' + s + '\\', this.value)"></td>';
      var act = '<td style="white-space:nowrap;"><a href="/trading-live.html?symbol=' + encodeURIComponent(r.symbol) + '" class="pill-link" title="Open the live order form for ' + s + '">' +
        '<button type="button" class="primary wl-trade">Trade</button></a> <button type="button" class="wl-x" title="Remove ' + s + '" onclick="watchRemove(\\'' + s + '\\')">\\u00D7</button></td>';
      if (r.pending && !r.error) {
        return '<tr><td>' + symLink(r) + '</td><td colspan="10" class="muted">Loading prices\\u2026</td>' + act + note + '</tr>';
      }
      if (r.error) {
        return '<tr><td>' + symLink(r) + '</td><td colspan="10" class="muted">' + esc(r.error) + '</td>' + act + note + '</tr>';
      }
      var up = (r.change || 0) >= 0, cls = r.change == null ? '' : up ? 'qp-up' : 'qp-down';
      var macdCell = '<span class="muted">--</span>';
      if (r.macd_state) {
        var recent = r.macd_cross && r.macd_ago != null && r.macd_ago <= 5, isUp = r.macd_state === 'above';
        var when = r.macd_ago === 0 ? 'today' : r.macd_ago === 1 ? 'yesterday' : r.macd_ago + ' days ago';
        macdCell = recent
          ? '<span class="' + (r.macd_cross === 'bullish' ? 'qp-up' : 'qp-down') + '" title="MACD crossed its signal line ' + when + '">' + (r.macd_cross === 'bullish' ? '\\u25B2 Bullish cross' : '\\u25BC Bearish cross') + '<span class="wl-sub">' + when + '</span></span>'
          : '<span class="' + (isUp ? 'qp-up' : 'qp-down') + '" title="MACD is ' + (isUp ? 'above' : 'below') + ' its signal line. ' + (r.macd_cross ? 'Last crossover: ' + r.macd_cross + ', ' + when : 'No crossover in the history') + '">' + (isUp ? '\\u25B2 Above' : '\\u25BC Below') + '<span class="wl-sub">signal line</span></span>';
      }
      var earnCell = '<span class="muted">--</span>';
      if (r.earn_known) {
        if (!r.earn_date) { earnCell = '<span class="muted" title="Nothing upcoming: funds and ETFs do not report earnings">\\u2014</span>'; }
        else {
          var past = r.earn_days != null && r.earn_days < 0, soon = r.earn_days != null && r.earn_days >= 0 && r.earn_days <= 7, dd = new Date(r.earn_date + 'T12:00:00');
          earnCell = '<span class="' + (soon ? 'wl-earn-soon' : '') + '" title="Companies confirm dates close to the day">' +
            dd.toLocaleDateString('en-US', {month: 'short', day: 'numeric'}) +
            '<span class="wl-sub">' + (past ? 'reported' : r.earn_days === 0 ? 'today' : r.earn_days === 1 ? 'tomorrow' : 'in ' + r.earn_days + ' days') + '</span></span>';
        }
      }
      var rsiCls = r.rsi == null ? '' : r.rsi <= 30 ? 'wl-rsi-lo' : r.rsi >= 70 ? 'wl-rsi-hi' : '';
      return '<tr><td>' + symLink(r) + '</td>' +
        '<td class="num">' + usd(r.price) + '</td><td class="num ' + cls + '">' + signed(r.change_pct, '%') + '<span class="wl-sub ' + cls + '">' + signed(r.change) + '</span></td>' +
        '<td class="num">' + mini(r.day_low, r.day_high, r.day_position) + '</td><td class="num">' + mini(r.week_low, r.week_high, r.week_position) + '</td>' +
        '<td class="num">' + vol(r.volume) + '</td><td class="num ' + rsiCls + '">' + (r.rsi == null ? '--' : r.rsi.toFixed(0)) + '</td><td class="num wl-macd">' + macdCell + '</td><td class="num">' + earnCell + '</td>' +
        '<td class="num wl-trend">' + arrow(r.trend_short, 'Short term (about 1 month)') + arrow(r.trend_medium, 'Medium term (about 3 months)') + arrow(r.trend_long, 'Long term (about 1 year)') + '</td>' +
        '<td class="num"><span class="qp-badge wl-badge ' + badgeClass(r.rating) + '">' + esc(r.rating) + '</span></td>' + act + note + '</tr>';
    }).join('');
    out.innerHTML = '<div class="wl-wrap"><table id="wl-table"><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
  }
  function syncQuote() { if (window.quoteWatchSync) { window.quoteWatchSync(); } }
  function status(text, warn) {
    var el = document.getElementById('wl-status');
    el.textContent = text; el.className = warn ? 'status-line status-warn' : 'muted small';
  }
  function applyEarn() {
    rows.forEach(function (r) { var e = earnBy[r.symbol]; if (e) { r.earn_known = e.known; r.earn_date = e.date; r.earn_days = e.days; } });
  }
  function loadEarn() {
    if (!rows.length) { return; }
    postJSON('/api/earnings', {symbols: rows.map(function (r) { return r.symbol; })}).then(function (d) {
      d.items.forEach(function (it) { earnBy[it.symbol] = it; });
      applyEarn(); render();
      if (d.pending > 0 && earnTries < 4) { earnTries += 1; clearTimeout(earnTimer); earnTimer = setTimeout(loadEarn, 7000); }
    }).catch(function () { /* the dates are a nicety: the table stays as it is */ });
  }
  function load() {
    status('Loading prices\\u2026');
    return postJSON('/api/watchlist/data', {}).then(function (d) {
      rows = d.rows; applyEarn(); render();
      if (!d.warning) { earnTries = 0; loadEarn(); }
      status(d.warning ? 'Your saved list is shown, but prices could not be loaded: ' + d.warning : rows.length ? 'Updated ' + new Date().toLocaleTimeString() + '. Prices refresh by themselves every minute.' : '', !!d.warning);
      if (timer) { clearInterval(timer); }
      if (rows.length) { timer = setInterval(function () { if (!document.hidden) { load(); } }, 60000); }
    }).catch(function (e) { render(); status('Your saved list is shown, but prices could not be loaded: ' + e.message, true); });
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
    return postJSON('/api/watchlist/remove', {symbol: sym}).then(function () { rows = rows.filter(function (r) { return r.symbol !== sym; }); render(); if (!rows.length) { status(''); } })
      .catch(function (e) { status(e.message, true); });
  };
  window.watchHas = function (sym) { sym = String(sym || '').toUpperCase(); return rows.some(function (r) { return r.symbol === sym; }); };
  window.watchNote = function (sym, text) {
    postJSON('/api/watchlist/note', {symbol: sym, note: text}).then(function () {
      rows.forEach(function (r) { if (r.symbol === sym) { r.note = text; } });
    }).catch(function (e) { status(e.message, true); });
  };
  window.watchRefresh = load;
  render();   // the saved list shows at once; prices fill in when they arrive
  // postJSON is defined further down the page, so wait until the page has loaded
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', load); } else { load(); }
})();
</script>
"""


def watchlist_card_html() -> str:
    initial = json.dumps(stored_rows(db.watchlist.list_items())).replace("</", "<\\/")
    js = _JS.replace("__INITIAL__", initial).replace("__EXAMPLES__", "[" + ",".join(f"'{s}'" for s in _EXAMPLES) + "]")
    return f"""
<style>{_CSS}</style>
<details class="card fold" id="watchlist">
<summary><h3>Watchlist</h3><span class="fold-hint" id="wl-count"></span><span class="fold-hint fold-closed">click to expand</span></summary>
<p class="muted">Tickers you want to keep an eye on. To add a ticker, look it up in Quote and chart below and press Add to watchlist. Click a symbol to open its chart and rating; click a column heading to sort.
Reading prices never places an order.</p>
<div class="wl-bar"><button type="button" onclick="watchRefresh()">Refresh prices</button></div>
<p id="wl-status" class="muted small"></p>
<div id="wl-out"></div>
<p class="muted small">Rating counts moving-average, RSI, MACD and volume signals on daily prices. The MACD column shows whether it is above or below its signal line and flags a crossover from the last 5 trading days. Trend arrows are short (about a month), medium (about 3 months) and long (about a year). Technical signals only, not advice.</p>
</details>
{js}
"""
