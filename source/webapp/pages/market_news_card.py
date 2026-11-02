"""The Trading tab's "Market news" card: headlines about the broader market (indexes, the Fed and rates, the economy,
oil, trade and world events), with a topic filter. It loads when the page opens and asks again every hour while the page
stays open (source.collector.market_news keeps the list so that is cheap). Read-only; headlines are not advice."""

from __future__ import annotations

_CSS = """
.mn-top { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:6px 0 4px; }
.mn-chips button { padding:3px 10px; font-size:12px; }
.mn-list { list-style:none; margin:6px 0 4px; padding:0; }
.mn-list li { padding:8px 0; border-top:1px solid var(--border); }
.mn-list li:first-child { border-top:0; }
.mn-list a { font-weight:600; }
.mn-meta { font-size:12px; color:var(--ink-muted); }
.mn-tag { display:inline-block; font-size:11px; font-weight:600; padding:1px 7px; border-radius:10px; background:var(--surface-2, #f2f2f7); color:var(--ink-soft, #555); margin-right:6px; }
.mn-list p { margin:3px 0 0; font-size:13px; }
"""

_JS = r"""
<script>
(function () {
  var all = [], topic = 'All', timer = null, every = 3600000;
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function ago(iso) {
    var t = Date.parse(iso); if (isNaN(t)) { return ''; }
    var m = Math.max(0, Math.round((Date.now() - t) / 60000));
    if (m < 60) { return m + ' min ago'; } if (m < 1440) { return Math.round(m / 60) + ' h ago'; }
    var d = Math.round(m / 1440); return d + (d === 1 ? ' day ago' : ' days ago');
  }
  function status(text, bad) { var el = document.getElementById('mn-status'); el.textContent = text; el.style.color = bad ? 'var(--danger, #c94a4a)' : ''; }
  function chips() {
    var names = ['All']; all.forEach(function (n) { if (names.indexOf(n.topic) < 0) { names.push(n.topic); } });
    document.getElementById('mn-chips').innerHTML = names.length > 2 ? names.map(function (t) {
      return '<button type="button" class="' + (t === topic ? 'primary' : '') + '" onclick="marketNewsTopic(\'' + esc(t) + '\')">' + esc(t) + '</button>';
    }).join(' ') : '';
  }
  function draw() {
    var rows = all.filter(function (n) { return topic === 'All' || n.topic === topic; });
    document.getElementById('mn-out').innerHTML = rows.length ? '<ul class="mn-list">' + rows.map(function (n) {
      return '<li><a href="' + esc(n.url) + '" target="_blank" rel="noopener noreferrer">' + esc(n.headline) + '</a>' +
        '<div class="mn-meta"><span class="mn-tag">' + esc(n.topic) + '</span>' + esc(n.source) + (n.time ? ' · ' + esc(ago(n.time)) : '') + '</div>' +
        (n.summary ? '<p>' + esc(n.summary) + '</p>' : '') + '</li>';
    }).join('') + '</ul>' : '<p class="muted small">No headlines under this topic right now.</p>';
  }
  function clock(iso) { var d = new Date(iso); return isNaN(d) ? '' : d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}); }
  function load(force) {
    status('Loading market news…');
    return postJSON('/api/market-news', {force: !!force}).then(function (d) {
      all = d.items || [];
      if (d.refresh_seconds) { every = d.refresh_seconds * 1000; }
      chips(); draw();
      document.getElementById('mn-count').textContent = all.length ? all.length + ' headlines' : '';
      if (!all.length) { status(d.error ? 'Market news could not be loaded right now (' + d.error + ').' : 'No market headlines found right now.', !!d.error); return; }
      status((d.stale ? 'Could not refresh, showing the list from ' : 'Updated ') + clock(d.fetched) + ' · from ' + d.source + ' · refreshes every hour while this page is open.', !!d.stale);
    }).catch(function (e) { status(e.message, true); });
  }
  function schedule() { clearTimeout(timer); timer = setTimeout(function () { load(false).then(schedule, schedule); }, every); }
  window.marketNewsTopic = function (t) { topic = t; chips(); draw(); };
  window.marketNewsRefresh = function () { load(true).then(schedule, schedule); };
  function start() { load(false).then(schedule, schedule); }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', start); } else { start(); }
})();
</script>
"""


def market_news_card_html() -> str:
    return f"""
<style>{_CSS}</style>
<details class="card fold" id="market-news" open>
<summary><h3>Market news</h3><span class="fold-hint" id="mn-count"></span><span class="fold-hint fold-closed">click to expand</span></summary>
<p class="muted">What is moving the broader market: stocks and bonds overall, the Fed and interest rates, inflation and jobs, oil, trade and world events. It is about the market as a whole, not one company
(a stock's own headlines are on <a href="/stock-analysis.html">Stock Analysis</a>).</p>
<div class="mn-top"><button type="button" onclick="marketNewsRefresh()">Refresh</button><span id="mn-chips" class="mn-chips"></span></div>
<p id="mn-status" class="muted small"></p>
<div id="mn-out"></div>
<p class="muted small">Headlines open the publisher's page. They are not recommendations, and a headline can be old news by the time you read it.</p>
</details>
{_JS}
"""
