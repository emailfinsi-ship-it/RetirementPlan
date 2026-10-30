"""The Linked Positions tab's "Review my holdings" card: screens every stock, ETF and fund you own (linked accounts plus what the
Alpaca, IBKR and E*TRADE tabs last showed) with the screener's technical readings and lists a plain-language note for each, the ones
worth a look first. Read-only and not advice: it never places an order."""

from __future__ import annotations

from source.webapp.pages import position_ratings

_CSS = position_ratings.CSS + """
.hr-lvl { display:inline-block; border-radius:999px; padding:1px 9px; font-size:12px; font-weight:700; border:1px solid var(--border); white-space:nowrap; }
.hr-lvl.trim, .hr-lvl.review { border-color:var(--danger); color:var(--danger); }
.hr-lvl.watch { border-color:var(--warn); color:var(--warn); }
.hr-lvl.strong { border-color:var(--success); color:var(--success); }
#hr-table td { vertical-align:top; } #hr-table td.why { font-size:12px; color:var(--ink-muted); min-width:260px; max-width:440px; }
#hr-table td.why div { margin:0 0 3px; }
.hr-sum { display:flex; flex-wrap:wrap; gap:8px; margin:8px 0; }
"""

_BODY = r"""
<div class="card" id="holdings-review">
  <h3 class="sub" style="margin-top:0">Review my holdings</h3>
  <p class="muted small" style="margin:0 0 8px;">Screens every stock, ETF and fund you own (linked accounts, plus what the Alpaca, IBKR and E*TRADE tabs last showed) on trend, momentum, rating and position size, and lists the ones worth a second look first.
  It reads price history, so it takes a few seconds to a minute. These are prompts, not recommendations to buy or sell: chart signals know nothing about your goals, taxes or time horizon.</p>
  <p><button type="button" class="primary" id="hr-go" onclick="hrRun()">Review my holdings</button> <span class="muted small" id="hr-note"></span></p>
  <div id="hr-progress" hidden><div style="height:8px; border-radius:6px; background:var(--surface-alt); overflow:hidden; margin:8px 0 4px;"><i id="hr-bar" style="display:block; height:100%; width:0; background:var(--brand); transition:width .3s;"></i></div><div class="muted small" id="hr-stage"></div></div>
  <div class="hr-sum" id="hr-sum"></div>
  <div style="overflow-x:auto;"><table id="hr-table"></table></div>
  <p class="muted small" id="hr-foot" hidden>Rules of thumb, not advice: a single stock over 15% (a fund over 40%) of everything you hold, RSI over 70 or under 30, a Sell or Strong Sell technical rating, a recent bearish MACD cross, a big one-month move, or a deep drop from the 52-week high. In a taxable account, selling a gain is taxed.</p>
</div>
<script>
(function () {
  var $ = function (id) { return document.getElementById(id); }, timer = null;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function usd(n) { return '$' + Number(n || 0).toLocaleString('en-US', {maximumFractionDigits: 0}); }
  function pct(n, plus) { return n == null ? '<span class="muted">--</span>' : '<span class="' + (n >= 0 ? 'qp-up' : 'qp-down') + '" style="color:var(--' + (n >= 0 ? 'success' : 'danger') + ')">' + (plus && n >= 0 ? '+' : '') + Number(n).toFixed(0) + '%</span>'; }
  function pill(r) { return r ? '<span class="pr-badge ' + (/Buy/.test(r) ? 'pr-buy' : /Sell/.test(r) ? 'pr-sell' : 'pr-hold') + '">' + esc(r) + '</span>' : '<span class="muted">--</span>'; }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  var JOB = null;
  window.hrRun = function () {
    stop(); $('hr-go').disabled = true; $('hr-note').textContent = 'Starting…'; $('hr-table').innerHTML = ''; $('hr-sum').innerHTML = ''; $('hr-foot').hidden = true;
    postJSON('/api/holdings/review/start', {}).then(function (r) {
      JOB = r.job; $('hr-note').textContent = 'Reading prices for ' + r.count + ' holdings…'; $('hr-progress').hidden = false; timer = setInterval(poll, 1000); poll();
    }).catch(function (e) { $('hr-go').disabled = false; $('hr-note').textContent = e.message; });
  };
  function poll() {
    postJSON('/api/holdings/review/result', {job: JOB}).then(function (s) {
      $('hr-bar').style.width = Math.max(3, s.total ? Math.round(s.done / s.total * 100) : 3) + '%'; $('hr-stage').textContent = s.stage + (s.total ? ' (' + s.done + ' of ' + s.total + ')' : '');
      if (s.state === 'running') { return; }
      stop(); $('hr-progress').hidden = true; $('hr-go').disabled = false; $('hr-note').textContent = '';
      if (s.state === 'error') { $('hr-note').textContent = s.error; return; }
      draw(s.review);
    }).catch(function (e) { stop(); $('hr-progress').hidden = true; $('hr-go').disabled = false; $('hr-note').textContent = e.message; });
  }
  var NAMES = {trim: 'worth a look: large and stretched', review: 'worth a look: weakening', watch: 'to watch', strong: 'holding up well', ok: 'with no flags', nodata: 'without enough history'};
  function draw(rv) {
    $('hr-sum').innerHTML = Object.keys(NAMES).filter(function (k) { return rv.counts[k]; }).map(function (k) { return '<span class="hr-lvl ' + k + '">' + rv.counts[k] + ' ' + NAMES[k] + '</span>'; }).join('');
    $('hr-table').innerHTML = '<thead><tr><th>Holding</th><th class="num">Share of all</th><th class="num">Value</th><th class="num">Gain</th><th>Rating</th><th class="num">RSI</th><th>Note</th><th>Why</th></tr></thead><tbody>' +
      rv.items.map(function (n) {
        return '<tr><td><a href="/stock-analysis.html?symbol=' + encodeURIComponent(n.symbol) + '"><strong>' + esc(n.symbol) + '</strong></a><div class="muted small">' + esc(n.name) + '</div></td>' +
          '<td class="num">' + Number(n.weight).toFixed(1) + '%</td><td class="num">' + usd(n.value) + '</td><td class="num">' + pct(n.gain_pct, true) + '</td><td>' + pill(n.rating) + '</td>' +
          '<td class="num">' + (n.rsi == null ? '--' : Math.round(n.rsi)) + '</td><td><span class="hr-lvl ' + esc(n.level) + '">' + esc(n.headline) + '</span></td>' +
          '<td class="why">' + (n.reasons || []).map(function (t) { return '<div>' + esc(t) + '</div>'; }).join('') + '</td></tr>';
      }).join('') + '</tbody>';
    $('hr-foot').hidden = false;
  }
})();
</script>
"""


def holdings_review_card_html() -> str:
    return f"<style>{_CSS}</style>{_BODY}"
