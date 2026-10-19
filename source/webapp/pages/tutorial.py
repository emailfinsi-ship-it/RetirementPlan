"""The Tutorial page: the narrated video tour and the written user guide, all
bundled with the app (source/webapp/static/tutorial/) so it works offline."""

from __future__ import annotations

from pathlib import Path

from source.webapp.render_helpers import _shell

TUTORIAL_DIR = Path(__file__).resolve().parent.parent / "static" / "tutorial"

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
<div class="card">
<h3 class="sub" style="margin-top:0">Watch the tour</h3>
<video class="tut-video" id="tut-video" controls preload="metadata" src="/tutorial/tour-dark.mp4"></video>
<p class="small muted" style="margin:8px 0 0">
  <button type="button" class="chip" onclick="var v=document.getElementById('tut-video'); v.src='/tutorial/tour-dark.mp4'; v.play();">Narrated tour (dark, with voice-over)</button>
  <button type="button" class="chip" onclick="var v=document.getElementById('tut-video'); v.src='/tutorial/tour-light.mp4'; v.play();">Quick silent tour (light, captions only)</button>
</p>
</div>
<div class="card tut-guide" id="guide">
<h3 class="sub" style="margin-top:0">User guide</h3>
{_guide_html()}
</div>
"""
    return _shell(title="Tutorial", active="tutorial.html", body=body)
