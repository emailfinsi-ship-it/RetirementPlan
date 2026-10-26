"""The Stock Analysis tab's "Earnings this week and next" card: which of your tickers (the watchlist and the
stocks held in your linked accounts) report earnings this week or next (Monday to the Sunday after).
Dates come from source.collector.earnings (Yahoo Finance via yfinance, cached in the database).
Read-only: it never places an order."""

from __future__ import annotations

from datetime import date

from source.collector import earnings
from source.common import db

_EXAMPLE_MAX = earnings.MAX_SYMBOLS
WEEKS = 2          # this week and next


def _equity_values() -> dict[str, float]:
    """{symbol: dollars held} for the stocks (not funds, bonds or cash) in your linked accounts, summed over accounts."""
    try:
        holdings = db.list_plaid_holdings()
    except Exception:       # a missing table must never break the page
        holdings = []
    values: dict[str, float] = {}
    for h in holdings:
        if str(h.get("security_type") or "").lower() != "equity":
            continue
        try:
            sym = db.watchlist.clean_symbol(h.get("ticker_symbol"))
        except ValueError:
            continue
        try:
            values[sym] = values.get(sym, 0.0) + float(h.get("institution_value") or 0.0)
        except (TypeError, ValueError):
            values.setdefault(sym, 0.0)
    return values


def week_universe() -> dict[str, list[str]]:
    """{symbol: ["watchlist", "holding"]}: the tickers worth checking for earnings. The watchlist comes first (it is
    checked whole), then held stocks from the biggest position down, so if there are more tickers than can be
    checked the smallest holdings are the ones left out. Funds, bonds and cash do not report earnings."""
    universe: dict[str, list[str]] = {}
    for sym in db.watchlist.list_symbols():
        universe.setdefault(sym, []).append("watchlist")
    values = _equity_values()
    for sym in sorted(values, key=lambda k: (-values[k], k)):
        if "holding" not in universe.setdefault(sym, []):
            universe[sym].append("holding")
    return dict(list(universe.items())[:_EXAMPLE_MAX])


def build_week(*, today: date | None = None, weeks: int = WEEKS, **kw) -> dict:
    """The /api/earnings/week answer: reporters this week and next, biggest holding first within a day, with
    company names where known and each holding's share of your stock holdings."""
    universe = week_universe()
    if universe:
        out = earnings.this_week(universe, today=today, weeks=weeks, **kw)
    else:
        start, end = earnings.week_bounds(today, weeks)
        out = {"start": start.isoformat(), "end": end.isoformat(), "items": [], "pending": 0, "unknown": 0,
               "checked": 0, "error": ""}
    values = _equity_values()
    total = sum(values.values())
    names = db.watchlist.cached_names([i["symbol"] for i in out["items"]]) if out["items"] else {}
    for item in out["items"]:
        item["name"] = names.get(item["symbol"], "")
        value = values.get(item["symbol"])
        item["value"] = round(value, 2) if value else 0.0
        item["pct"] = round(100.0 * value / total, 1) if value and total > 0 else None
    out["items"].sort(key=lambda i: (i["date"], -i["value"], i["symbol"]))
    out["weeks"] = weeks
    out["left_out"] = max(0, len(set(db.watchlist.list_symbols()) | set(values)) - len(universe))
    return out


_CSS = """
details.fold > summary { cursor:pointer; list-style:none; display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
details.fold > summary::-webkit-details-marker { display:none; }
details.fold > summary h3 { margin:0; display:inline; }
details.fold > summary::before { content:'\\25B8'; color:var(--ink-muted); font-size:14px; }
details.fold[open] > summary::before { content:'\\25BE'; }
details.fold > summary .fold-hint { color:var(--ink-muted); font-size:12px; }
details.fold[open] > summary { margin-bottom:8px; }
details.fold[open] > summary .fold-closed { display:none; }

.ew-days { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin:10px 0 4px; }
.ew-day { border:1px solid var(--border); border-radius:12px; padding:8px 10px; background:var(--surface-alt); min-height:64px; }
.ew-day.today { border-color:var(--brand); }
.ew-day h4 { margin:0 0 6px; font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--ink-muted); }
.ew-day.today h4 { color:var(--brand); }
.ew-chip { display:flex; align-items:baseline; gap:6px; flex-wrap:wrap; padding:3px 0; font-size:13px; }
.ew-chip a { font-weight:700; }
.ew-chip .nm { font-size:11px; color:var(--ink-muted); }
.ew-tag { font-size:10px; padding:1px 7px; border-radius:999px; border:1px solid var(--border); color:var(--ink-muted); }
.ew-week { margin:14px 0 0; font-size:13px; color:var(--ink); }
.ew-pct { font-size:11px; font-weight:700; padding:1px 6px; border-radius:999px; background:var(--surface); border:1px solid var(--border); cursor:default; }
.ew-none { color:var(--ink-muted); font-size:12px; }
"""

_JS = """
<script>
(function () {
  var tries = 0, timer = null;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function pretty(iso) { return new Date(iso + 'T12:00:00').toLocaleDateString('en-US', {month: 'short', day: 'numeric'}); }
  function status(text, warn) { var el = document.getElementById('ew-status'); el.textContent = text; el.className = warn ? 'status-line status-warn' : 'muted small'; }
  function draw(d) {
    var weeks = d.weeks || 1, start = new Date(d.start + 'T12:00:00'), todayIso = d.today, html = '';
    for (var w = 0; w < weeks; w++) {
      var days = [];
      for (var i = 0; i < 7; i++) {
        var dt = new Date(start.getTime() + (w * 7 + i) * 86400000), iso = dt.getFullYear() + '-' + ('0' + (dt.getMonth() + 1)).slice(-2) + '-' + ('0' + dt.getDate()).slice(-2);
        days.push({iso: iso, label: dt.toLocaleDateString('en-US', {weekday: 'short'}) + ' ' + pretty(iso), items: []});
      }
      d.items.forEach(function (it) { days.forEach(function (day) { if (day.iso === it.date) { day.items.push(it); } }); });
      // Saturday and Sunday only get a column when something reports then.
      days = days.filter(function (day, i) { return i < 5 || day.items.length; });
      html += (weeks > 1 ? '<h4 class="ew-week">' + (w === 0 ? 'This week' : w === 1 ? 'Next week' : 'In ' + w + ' weeks') + '</h4>' : '') +
        '<div class="ew-days">' + days.map(function (day) {
        return '<div class="ew-day' + (day.iso === todayIso ? ' today' : '') + '"><h4>' + esc(day.label) + (day.iso === todayIso ? ' \\u00B7 today' : '') + '</h4>' +
          (day.items.length ? day.items.map(function (it) {
            return '<div class="ew-chip"><a href="#quote" onclick="lookupQuote(\\'' + esc(it.symbol) + '\\'); return false;" title="Open the chart and rating">' + esc(it.symbol) + '</a>' +
              (it.pct != null ? '<span class="ew-pct" data-ctip="' + esc(it.symbol) + ' is ' + it.pct + '% of the stocks in your linked accounts">' + (it.pct < 0.1 ? '<0.1' : it.pct) + '%</span>' : '') +
              (it.name ? '<span class="nm">' + esc(it.name) + '</span>' : '') +
              (it.days < 0 ? '<span class="ew-tag">reported</span>' : '') +
              it.sources.map(function (s) { return '<span class="ew-tag">' + (s === 'holding' ? 'you own' : 'watchlist') + '</span>'; }).join('') + '</div>';
          }).join('') : '<div class="ew-none">\\u2014</div>') + '</div>';
      }).join('') + '</div>';
    }
    document.getElementById('ew-out').innerHTML = html;
  }
  function span(d) { return d.weeks > 1 ? 'in the next ' + d.weeks + ' weeks' : 'this week'; }
  function load(manual) {
    if (manual) { tries = 0; }
    status('Checking earnings dates\\u2026');
    return postJSON('/api/earnings/week', {}).then(function (d) {
      draw(d);
      document.getElementById('ew-count').textContent = d.items.length ? d.items.length + (d.items.length === 1 ? ' ticker reports' : ' tickers report') + ' in the next 2 weeks' : '';
      var big = d.items.filter(function (it) { return it.pct != null; }).sort(function (a, b) { return b.pct - a.pct; })[0];
      var line = d.items.length ? d.items.length + (d.items.length === 1 ? ' ticker reports ' : ' tickers report ') + span(d) + ' (' + pretty(d.start) + ' to ' + pretty(d.end) + ').' +
          (big ? ' Biggest holding: ' + big.symbol + ' (' + big.pct + '% of your stocks) on ' + pretty(big.date) + '.' : '')
        : d.checked ? 'None of your ' + d.checked + ' tickers report earnings ' + span(d) + ' (' + pretty(d.start) + ' to ' + pretty(d.end) + ').'
        : 'Put stocks on your watchlist (or link an investment account) and the ones reporting soon show here.';
      if (d.left_out) { line += ' ' + d.left_out + ' of your smallest holdings were not checked.'; }
      if (d.pending > 0 && tries < 5) {
        tries += 1; status(line + ' Still checking ' + d.pending + ' more\\u2026');
        clearTimeout(timer); timer = setTimeout(load, 6000);
      } else if (d.error && d.unknown >= d.checked && d.checked) {
        status('Earnings dates could not be loaded right now (' + d.error + '). Try again later.', true);
      } else {
        status(line + (d.unknown ? ' (' + d.unknown + ' could not be checked.)' : ''), d.unknown > 0 && !!d.error);
      }
    }).catch(function (e) { status(e.message, true); });
  }
  window.earningsWeekRefresh = function () { load(true); };
  // postJSON is defined further down the page, so wait until the page has loaded
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', load); } else { load(); }
})();
</script>
"""


def earnings_week_card_html() -> str:
    return f"""
<style>{_CSS}</style>
<details class="card fold" id="earnings-week">
<summary><h3>Earnings this week and next</h3><span class="fold-hint" id="ew-count"></span><span class="fold-hint fold-closed">click to expand</span></summary>
<p class="muted">Stocks on your watchlist, and stocks you hold in your linked accounts, that report earnings this week or next. Your biggest holdings come first in each day, and the % is that stock's share of
the stocks in your linked accounts (so a big one reporting is easy to spot). A report can move a price sharply either way, so it is worth knowing before you place an order. Funds and ETFs do not report earnings.</p>
<p><button type="button" onclick="earningsWeekRefresh()">Refresh</button> <span id="ew-status" class="muted small"></span></p>
<div id="ew-out"></div>
<p class="muted small">Dates come from Yahoo Finance and can change; companies confirm them close to the day. Dates are cached and refreshed about twice a day.</p>
</details>
{_JS}
"""
