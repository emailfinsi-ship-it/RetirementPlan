"""The Stock Analysis tab's "Earnings this week" card: which of your tickers (the watchlist and the
stocks held in your linked accounts) report earnings between Monday and Sunday of the current week.
Dates come from source.collector.earnings (Yahoo Finance via yfinance, cached in the database).
Read-only: it never places an order."""

from __future__ import annotations

from datetime import date

from source.collector import earnings
from source.common import db

_EXAMPLE_MAX = 60


def week_universe() -> dict[str, list[str]]:
    """{symbol: ["watchlist", "holding"]}: the tickers worth checking for earnings. Only stocks are
    checked among holdings (funds, bonds and cash do not report earnings); the watchlist is checked whole."""
    universe: dict[str, list[str]] = {}
    for sym in db.watchlist.list_symbols():
        universe.setdefault(sym, []).append("watchlist")
    try:
        holdings = db.list_plaid_holdings()
    except Exception:       # a missing table must never break the page
        holdings = []
    for h in holdings:
        if str(h.get("security_type") or "").lower() != "equity":
            continue
        try:
            sym = db.watchlist.clean_symbol(h.get("ticker_symbol"))
        except ValueError:
            continue
        if "holding" not in universe.setdefault(sym, []):
            universe[sym].append("holding")
    return dict(list(universe.items())[:_EXAMPLE_MAX])


def build_week(*, today: date | None = None, **kw) -> dict:
    """The /api/earnings/week answer: this week's reporters with company names where known."""
    universe = week_universe()
    out = earnings.this_week(universe, today=today, **kw) if universe else {
        "start": earnings.week_bounds(today)[0].isoformat(), "end": earnings.week_bounds(today)[1].isoformat(),
        "items": [], "pending": 0, "unknown": 0, "checked": 0, "error": "",
    }
    names = db.watchlist.cached_names([i["symbol"] for i in out["items"]]) if out["items"] else {}
    for item in out["items"]:
        item["name"] = names.get(item["symbol"], "")
    return out


_CSS = """
.ew-days { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin:10px 0 4px; }
.ew-day { border:1px solid var(--border); border-radius:12px; padding:8px 10px; background:var(--surface-alt); min-height:64px; }
.ew-day.today { border-color:var(--brand); }
.ew-day h4 { margin:0 0 6px; font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--ink-muted); }
.ew-day.today h4 { color:var(--brand); }
.ew-chip { display:flex; align-items:baseline; gap:6px; flex-wrap:wrap; padding:3px 0; font-size:13px; }
.ew-chip a { font-weight:700; }
.ew-chip .nm { font-size:11px; color:var(--ink-muted); }
.ew-tag { font-size:10px; padding:1px 7px; border-radius:999px; border:1px solid var(--border); color:var(--ink-muted); }
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
    var days = [], start = new Date(d.start + 'T12:00:00'), todayIso = d.today;
    for (var i = 0; i < 7; i++) {
      var dt = new Date(start.getTime() + i * 86400000), iso = dt.getFullYear() + '-' + ('0' + (dt.getMonth() + 1)).slice(-2) + '-' + ('0' + dt.getDate()).slice(-2);
      days.push({iso: iso, label: dt.toLocaleDateString('en-US', {weekday: 'short'}) + ' ' + pretty(iso), items: []});
    }
    d.items.forEach(function (it) { days.forEach(function (day) { if (day.iso === it.date) { day.items.push(it); } }); });
    // Saturday and Sunday only get a column when something reports then.
    days = days.filter(function (day, i) { return i < 5 || day.items.length; });
    document.getElementById('ew-out').innerHTML = '<div class="ew-days">' + days.map(function (day) {
      return '<div class="ew-day' + (day.iso === todayIso ? ' today' : '') + '"><h4>' + esc(day.label) + (day.iso === todayIso ? ' \\u00B7 today' : '') + '</h4>' +
        (day.items.length ? day.items.map(function (it) {
          return '<div class="ew-chip"><a href="#quote" onclick="lookupQuote(\\'' + esc(it.symbol) + '\\'); return false;" title="Open the chart and rating">' + esc(it.symbol) + '</a>' +
            (it.name ? '<span class="nm">' + esc(it.name) + '</span>' : '') +
            (it.days < 0 ? '<span class="ew-tag">reported</span>' : '') +
            it.sources.map(function (s) { return '<span class="ew-tag">' + (s === 'holding' ? 'you own' : 'watchlist') + '</span>'; }).join('') + '</div>';
        }).join('') : '<div class="ew-none">\\u2014</div>') + '</div>';
    }).join('') + '</div>';
  }
  function load(manual) {
    if (manual) { tries = 0; }
    status('Checking earnings dates\\u2026');
    return postJSON('/api/earnings/week', {}).then(function (d) {
      draw(d);
      var line = d.items.length ? d.items.length + (d.items.length === 1 ? ' ticker reports' : ' tickers report') + ' this week (' + pretty(d.start) + ' to ' + pretty(d.end) + ').'
        : d.checked ? 'None of your ' + d.checked + ' tickers report earnings this week (' + pretty(d.start) + ' to ' + pretty(d.end) + ').'
        : 'Add tickers to your watchlist (or link an investment account) and the ones reporting this week show here.';
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
<div class="card" id="earnings-week">
<h3 style="margin-top:0;">Earnings this week</h3>
<p class="muted">Stocks on your watchlist, and stocks you hold in your linked accounts, that report earnings between Monday and Sunday of this week.
A report can move a price sharply either way, so it is worth knowing before you place an order. Funds and ETFs do not report earnings.</p>
<p><button type="button" onclick="earningsWeekRefresh()">Refresh</button> <span id="ew-status" class="muted small"></span></p>
<div id="ew-out"></div>
<p class="muted small">Dates come from Yahoo Finance and can change; companies confirm them close to the day. Dates are cached and refreshed about twice a day.</p>
</div>
{_JS}
"""
