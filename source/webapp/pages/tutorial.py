"""The Tutorial page: the narrated video tour and the written user guide, all
bundled with the app (source/webapp/static/tutorial/) so it works offline."""

from __future__ import annotations

from pathlib import Path

from source.webapp.render_helpers import _shell

TUTORIAL_DIR = Path(__file__).resolve().parent.parent / "static" / "tutorial"

# Where each screen starts in the "A tour of every screen" video (seconds). The "About this page" bar on
# each tab links straight to that moment, so there is no extra video file (and no extra app size).
SCREEN_CHAPTERS: dict[str, int] = {
    "summary.html": 35, "asset.html": 83, "real-estate.html": 98, "linked-accounts.html": 110,
    "linked-positions.html": 122, "rebalance.html": 140, "expense.html": 164, "monte-carlo.html": 210,
    "drawdown-planning.html": 233, "legacy-planning.html": 255, "setup.html": 265,
}


def chapter_link_html(page: str) -> str:
    """A small "Watch this screen" link for the page's "About this page" bar, or "" when the page has
    no chapter in the tour video."""
    start = SCREEN_CHAPTERS.get(page)
    if start is None:
        return ""
    return (f' <a class="ex-btn ex-page-btn ex-watch" href="/tutorial.html?v=screens&amp;t={int(start)}#videos" '
            f'title="Opens the screens video at this tab">&#9654;&nbsp; Watch this screen</a>')


_CSS = """<style>
.tut-video { width: 100%; max-height: 70vh; border-radius: 12px; background: #000; }
.tut-guide h2 { margin-top: 28px; }
.tut-guide h3 { margin-top: 20px; }
.tut-guide img { max-width: 100%; height: auto; border: 1px solid var(--border, #d2d2d7); border-radius: 10px; margin: 8px 0; }
.tut-guide blockquote { margin: 10px 0; padding: 4px 12px; border-left: 3px solid var(--brand, #0071e3); }
.tut-guide table { border-collapse: collapse; } .tut-guide th, .tut-guide td { border: 1px solid var(--border, #d2d2d7); padding: 4px 8px; }
</style>"""


def _guide_html() -> str:
    try:
        return (TUTORIAL_DIR / "guide.html").read_text(encoding="utf-8")
    except OSError:
        return "<p class='muted'>The written guide is not available in this copy of the app.</p>"


def _render_tutorial_page() -> str:
    body = f"""{_CSS}
<h2 style="margin-top:0">Tutorial</h2>
<details class="card tut-guide" id="guide">
<summary style="font-weight:650; font-size:15px; cursor:pointer;">User guide <span class="muted">(click to open)</span></summary>
{_guide_html()}
</details>
<div class="card" id="videos">
<h3 class="sub" style="margin-top:0">Watch the videos</h3>
<video class="tut-video" id="tut-video" controls preload="metadata" src="/tutorial/tour-setup-dark.mp4"></video>
<p id="tut-note" class="status-warn" style="margin:8px 0 0; font-size:14px;" hidden>Press the play button &#9654; to start. The video is already set to the screen you chose.</p>
<p style="margin:10px 0 2px"><strong>1. Setting up</strong> <span class="muted">(password, the setup wizard, linking accounts)</span></p>
<p class="small muted" style="margin:4px 0 8px">
  <button type="button" class="chip" onclick="var v=document.getElementById('tut-video'); v.src='/tutorial/tour-setup-dark.mp4'; v.play();">Narrated by Fin (dark, voice-over)</button>
  <button type="button" class="chip" onclick="var v=document.getElementById('tut-video'); v.src='/tutorial/tour-setup-light.mp4'; v.play();">Silent with captions (light)</button>
</p>
<p style="margin:10px 0 2px"><strong>2. A tour of every screen</strong> <span class="muted">(what each tab shows and how it works)</span></p>
<p class="small muted" style="margin:4px 0 0">
  <button type="button" class="chip" onclick="var v=document.getElementById('tut-video'); v.src='/tutorial/tour-screens-dark.mp4'; v.play();">Narrated by Fin (dark, voice-over)</button>
  <button type="button" class="chip" onclick="var v=document.getElementById('tut-video'); v.src='/tutorial/tour-screens-light.mp4'; v.play();">Silent with captions (light)</button>
</p>
</div>
<script>
if (location.hash === '#guide') document.getElementById('guide').open = true;
(function () {{
  var q = new URLSearchParams(location.search), v = document.getElementById('tut-video'), note = document.getElementById('tut-note');
  if (q.get('v') !== 'screens') {{ return; }}
  var t = parseInt(q.get('t') || '0', 10) || 0;
  v.preload = 'auto';
  v.src = '/tutorial/tour-screens-dark.mp4';
  function start() {{
    try {{ v.currentTime = t; }} catch (e) {{}}
    var pr = v.play();
    // Some browsers (Safari) refuse to start a video without a click: say so instead of sitting silent.
    if (pr && pr.catch) {{ pr.catch(function () {{ if (note) {{ note.hidden = false; }} }}); }}
  }}
  if (v.readyState >= 1) {{ start(); }} else {{ v.addEventListener('loadedmetadata', start, {{once: true}}); }}
  v.load();
  v.addEventListener('error', function () {{ if (note) {{ note.hidden = false; note.textContent = 'This video could not be played here. Try the Silent with captions versions below.'; }} }});
}})();
</script>
"""
    return _shell(title="Tutorial", active="tutorial.html", body=body)
