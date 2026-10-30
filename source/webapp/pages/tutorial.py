"""The Tutorial page: five short narrated videos (one for each tab, plus getting started) and the written user guide, all bundled with the
app (source/webapp/static/tutorial/) so it works offline. Every tab's "About this page" bar links to the video for that tab, at the
moment it starts talking about that page."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from source.webapp.render_helpers import _shell

TUTORIAL_DIR = Path(__file__).resolve().parent.parent / "static" / "tutorial"

# key, name on the buttons, what the video covers. "setup" comes first: it is where a new person starts.
SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("setup", "Setup", "your password, the setup wizard, connecting accounts, and the Setup tab"),
    ("today", "Today", "your whole picture on one page, alerts, the data check and what to do next"),
    ("myplan", "My Plan", "accounts, positions, what you own and owe, income, spending and budget"),
    ("explore", "Explore", "will my money last, risk and suggestions, drawdown and legacy planning"),
    ("trading", "Trading", "Alpaca, IBKR and E*TRADE, stock analysis, the screener and your order history"),
)
_KEYS = {k for k, _, _ in SECTIONS}


def video_file(key: str) -> str:
    return f"help-{key}.mp4"


_PAGE_SECTIONS = {
    "summary.html": "today",
    "setup.html": "setup", "setup-wizard.html": "setup",
    "linked-accounts.html": "myplan", "linked-positions.html": "myplan", "asset.html": "myplan", "real-estate.html": "myplan",
    "expense.html": "myplan", "real-expenditure.html": "myplan", "budget-vs-actual.html": "myplan",
    "monte-carlo.html": "explore", "rebalance.html": "explore", "drawdown-planning.html": "explore", "legacy-planning.html": "explore",
    "trading.html": "trading", "trading-live.html": "trading", "ibkr.html": "trading", "etrade.html": "trading",
    "stock-analysis.html": "trading", "screener.html": "trading", "orders.html": "trading",
}


def section_for(page: str) -> str | None:
    """Which video covers this page (its file name, e.g. "monte-carlo.html"). Named pages rather than nav groups, so it holds
    whichever way a version arranges its tab rows."""
    return _PAGE_SECTIONS.get(page)


def _chapters() -> dict:
    try:
        data = json.loads((TUTORIAL_DIR / "chapters.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def chapter_link_html(page: str) -> str:
    """A small "Watch this video" link for the page's "About this page" bar: the video for the page's tab, starting at the page's own
    chapter. "" when the page has no video or the video is not in this copy of the app."""
    key = section_for(page)
    if key is None or not (TUTORIAL_DIR / video_file(key)).is_file():
        return ""
    start = 0
    for ch in (_chapters().get(key) or {}).get("chapters") or []:
        if str(ch.get("page") or "").lstrip("/") == page:
            start = int(ch.get("start") or 0)          # the last chapter on this page: the Setup video visits setup.html twice
    return (f' <a class="ex-watch" href="/tutorial.html?s={key}&amp;t={start}#videos" '
            f'title="Opens the video for this tab at this page">&#9654;&nbsp; Watch this video</a>')


_CSS = """<style>
#videos { scroll-margin-top: 140px; }
.tut-video { width: 100%; max-height: 70vh; border-radius: 12px; background: #000; }
.tut-chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 12px; }
.tut-chips button { padding: 6px 14px; border-radius: 999px; border: 1px solid var(--brand, #0071e3); background: transparent; color: var(--brand, #0071e3); font-weight: 650; cursor: pointer; }
.tut-chips button.on { background: var(--brand, #0071e3); color: #fff; }
.tut-chap { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 0; }
.tut-chap button { padding: 3px 10px; border-radius: 999px; border: 1px solid var(--border, #d2d2d7); background: transparent; color: inherit; font-size: 12.5px; cursor: pointer; }
.tut-chap button:hover { border-color: var(--brand, #0071e3); }
.tut-guide h2 { margin-top: 28px; }
.tut-guide h3 { margin-top: 20px; }
.tut-guide img { max-width: 100%; height: auto; border: 1px solid var(--border, #d2d2d7); border-radius: 10px; margin: 8px 0; }
.tut-guide blockquote { margin: 10px 0; padding: 4px 12px; border-left: 3px solid var(--brand, #0071e3); }
.tut-guide table { border-collapse: collapse; } .tut-guide th, .tut-guide td { border: 1px solid var(--border, #d2d2d7); padding: 4px 8px; }
</style>"""

_SEC = re.compile(r'<div class="tut-sec" data-sec="([a-z]+)">(.*?)</div><!--/tut-sec-->', re.S)


def _guide_html() -> str:
    try:
        return (TUTORIAL_DIR / "guide.html").read_text(encoding="utf-8")
    except OSError:
        return "<p class='muted'>The written guide is not available in this copy of the app.</p>"


def _render_tutorial_page() -> str:
    guide = _guide_html()
    docs = {k: v for k, v in _SEC.findall(guide)}
    chapters = _chapters()
    info = {k: {"name": name, "about": about, "video": "/tutorial/" + video_file(k), "have": (TUTORIAL_DIR / video_file(k)).is_file(),
                "chapters": (chapters.get(k) or {}).get("chapters") or []} for k, name, about in SECTIONS}
    chips = "".join(f'<button type="button" data-sec="{k}">{i}. {html.escape(name)}</button>' for i, (k, name, _) in enumerate(SECTIONS, 1))
    doc_blocks = "".join(f'<div class="tut-guide" data-doc="{k}" hidden>{docs.get(k, "")}</div>' for k in info)
    body = f"""{_CSS}
<h2 style="margin-top:0">Tutorial</h2>
<div class="card" id="videos">
<h3 class="sub" style="margin-top:0">Watch the videos</h3>
<p class="muted small" style="margin:0 0 10px;">One short video for each tab. New here? Start with Setup. Each tab also has a <strong>Watch this video</strong> button that opens the right one.</p>
<div class="tut-chips" id="tut-chips">{chips}</div>
<video class="tut-video" id="tut-video" controls preload="metadata"></video>
<p id="tut-note" class="status-warn" style="margin:8px 0 0; font-size:14px;" hidden></p>
<p class="small muted" id="tut-about" style="margin:8px 0 0;"></p>
<div class="tut-chap" id="tut-chap"></div>
</div>
<div class="card" id="tut-doc-card">
<h3 class="sub" style="margin-top:0">About this tab</h3>
<div id="tut-docs">{doc_blocks}</div>
</div>
<details class="card tut-guide" id="guide">
<summary style="font-weight:650; font-size:15px; cursor:pointer;">Full user guide <span class="muted">(click to open)</span></summary>
{guide}
</details>
<script>
if (location.hash === '#guide') document.getElementById('guide').open = true;
(function () {{
  var INFO = __INFO__, KEYS = __KEYS__;
  var v = document.getElementById('tut-video'), note = document.getElementById('tut-note'), q = new URLSearchParams(location.search);
  function mmss(s) {{ s = Math.round(s); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }}
  function seek(t, play) {{
    function go() {{
      try {{ v.currentTime = t; }} catch (e) {{}}
      if (!play) {{ return; }}
      var pr = v.play();
      // Some browsers (Safari) refuse to start a video without a click: say so instead of sitting silent.
      if (pr && pr.catch) {{ pr.catch(function () {{ note.hidden = false; note.textContent = 'Press the play button to start. The video is already set to the part you chose.'; }}); }}
    }}
    if (v.readyState >= 1) {{ go(); }} else {{ v.addEventListener('loadedmetadata', go, {{once: true}}); }}
  }}
  function show(key, t, play) {{
    var s = INFO[key]; if (!s) {{ return; }}
    note.hidden = true;
    Array.prototype.forEach.call(document.querySelectorAll('#tut-chips button'), function (b) {{ b.classList.toggle('on', b.getAttribute('data-sec') === key); }});
    document.getElementById('tut-about').textContent = 'This video covers ' + s.about + '.';
    var ch = document.getElementById('tut-chap');
    ch.innerHTML = s.chapters.map(function (c, i) {{ return '<button type="button" data-i="' + i + '">' + mmss(c.start) + ' ' + c.title.replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</button>'; }}).join('');
    Array.prototype.forEach.call(ch.querySelectorAll('button'), function (b) {{ b.addEventListener('click', function () {{ seek(s.chapters[+b.getAttribute('data-i')].start, true); }}); }});
    if (!s.have) {{ v.removeAttribute('src'); v.load(); note.hidden = false; note.textContent = 'This video is not included in this copy of the app.'; }}
    else if (v.getAttribute('src') !== s.video) {{ v.src = s.video; v.load(); }}
    Array.prototype.forEach.call(document.querySelectorAll('#tut-docs [data-doc]'), function (d) {{ d.hidden = d.getAttribute('data-doc') !== key; }});
    if (s.have && t) {{ seek(t, play !== false); }}
    try {{ history.replaceState(null, '', '/tutorial.html?s=' + key + (location.hash || '#videos')); }} catch (e) {{}}
  }}
  document.getElementById('tut-chips').addEventListener('click', function (ev) {{ var b = ev.target.closest('button[data-sec]'); if (b) {{ show(b.getAttribute('data-sec'), 0, false); v.play && v.play().catch(function () {{}}); }} }});
  v.addEventListener('error', function () {{ if (v.getAttribute('src')) {{ note.hidden = false; note.textContent = 'This video could not be played here. The written guide below covers the same ground.'; }} }});
  var start = q.get('s'); if (KEYS.indexOf(start) < 0) {{ start = KEYS[0]; }}
  show(start, parseInt(q.get('t') || '0', 10) || 0, true);
}})();
</script>
""".replace("__INFO__", json.dumps(info)).replace("__KEYS__", json.dumps([k for k, _, _ in SECTIONS]))
    return _shell(title="Tutorial", active="tutorial.html", body=body)
