"""Records one narrated tour video (screen recording + Fin's voice) of the app running on the sample household.

Run from the Code folder (needs playwright, kokoro-onnx, soundfile, ffmpeg; the voice model sits in /tmp/kokoro):

    TOUR_PART=trading PYTHONPATH=. python3 tools/video/make_tour.py        # today | myplan | explore | trading | setup
    python3 tools/video/post.py trading /tmp/tour11_trading_dark help-trading.mp4

Nothing here is part of the app: it drives a throwaway copy of the app (temporary data folder, made-up Alpaca / IBKR / E*TRADE
answers from fakes.py) and writes the recording, the voice track and the start time of every scene to the output folder."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import os
import pickle
import shutil
import sys
import time
import unittest
from datetime import date, timedelta

import numpy as np
import soundfile as sf
from playwright.async_api import async_playwright

from source.common import auth_store, branding, db, demo_data, first_run
from source.webapp.render_helpers import robot as _robot
from tests.test_dashboard import DashboardTestCase
from tools.video import fakes
from tools.video.narration import PARTS, SETUP_TEXT

PART = os.environ.get("TOUR_PART", "today")
DRY = os.environ.get("TOUR_DRY") == "1"          # no voice, short holds: only to check the scenes and take pictures
SCHEME = "dark"
VIEW = {"width": 1480, "height": 832} if PART == "trading" else {"width": 1280, "height": 720}
CAP_SIZE = 28 if PART == "trading" else 24
OUT = f"/tmp/tour11_{PART}_{SCHEME}"
ORDER = ["setup", "today", "myplan", "explore", "trading"]
SR = 24000

CAP_JS = """
(text) => {
  let el = document.getElementById('tour-cap');
  if (!el) {
    el = document.createElement('div'); el.id = 'tour-cap';
    el.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:980px;width:88%;background:rgba(15,23,42,.92);color:#fff;font:600 @@CAP@@px/1.35 Inter,Helvetica,Arial,sans-serif;padding:16px 24px;border-radius:14px;z-index:99999;box-shadow:0 10px 30px rgba(0,0,0,.35);text-align:center;transition:opacity .25s;pointer-events:none';
    document.body.appendChild(el);
  }
  el.style.opacity = text ? 1 : 0; el.textContent = text || '';
}
""".replace("@@CAP@@", str(CAP_SIZE))
CLEAR_HL = "() => document.querySelectorAll('[data-tourhl]').forEach(e => { e.style.outline = ''; e.style.outlineOffset = ''; e.removeAttribute('data-tourhl'); })"
HL = "(e) => { e.setAttribute('data-tourhl', '1'); e.style.outline = '3px solid #ffb703'; e.style.outlineOffset = '4px'; e.style.borderRadius = '10px'; }"
SCROLL = "(e) => window.scrollTo({top: Math.max(0, e.getBoundingClientRect().top + window.scrollY - 150), behavior: 'smooth'})"
CARD = """<html><body style="margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
background:linear-gradient(135deg,#0b2545,#13315c 60%,#0071e3);color:#fff;font-family:Inter,Helvetica,Arial,sans-serif;text-align:center">
<img src="@@LOGO@@" width="150" height="150" style="border-radius:32px;box-shadow:0 12px 40px rgba(0,0,0,.4)">
<div style="font-size:72px;font-weight:800;letter-spacing:-1px;margin-top:18px">FinSi</div>
<div style="font-size:30px;margin-top:4px;font-weight:600;color:#9cc9ff">@@TAG@@</div>
<div style="font-size:34px;margin-top:26px;font-weight:700">@@HEAD@@</div>
<div style="font-size:21px;margin-top:10px;opacity:.9;max-width:980px">@@SUB@@</div>
<div style="font-size:19px;margin-top:26px;opacity:.75;font-style:italic">@@MOTTO@@</div>
<div style="font-size:17px;margin-top:30px;opacity:.7">@@NOTE@@</div></body></html>"""

FIN_INIT = """
(function () {
  function make() {
    if (document.getElementById('tour-fin') || document.getElementById('wz-guide')) { return; }
    var st = document.createElement('style'); st.textContent = %s;
    document.head.appendChild(st);
    var d = document.createElement('div'); d.id = 'tour-fin';
    d.style.cssText = 'position:fixed;right:18px;bottom:22px;z-index:100000;pointer-events:none;';
    d.innerHTML = %s; document.body.appendChild(d);
  }
  function beacon() {
    var b = document.getElementById('tour-beacon');
    if (!b && document.body) {
      b = document.createElement('div'); b.id = 'tour-beacon';
      b.style.cssText = 'position:fixed;left:0;top:0;width:6px;height:6px;z-index:2147483647;background:#000;pointer-events:none;';
      document.body.appendChild(b);
    }
    return b;
  }
  window.__finTalk = function (ms) {
    make();
    var els = document.querySelectorAll('.rb'), b = beacon();
    els.forEach(function (e) { e.classList.add('talking'); });
    if (b) { b.style.background = '#ff00ff'; }
    setTimeout(function () { els.forEach(function (e) { e.classList.remove('talking'); }); if (b) { b.style.background = '#000'; } }, ms);
  };
  function swapGuide() {
    var g = document.querySelector('#wz-guide svg.rb');
    if (g && !g.classList.contains('rb-person')) { g.outerHTML = %s; }
  }
  function boot() { if (document.body) { make(); beacon(); swapGuide(); } }
  document.addEventListener('DOMContentLoaded', boot);
  if (document.readyState !== 'loading') { boot(); }
})();
""" % (json.dumps(_robot.ROBOT_CSS), json.dumps(_robot.person_svg(104)), json.dumps(_robot.person_svg(84)))

LOGO = "data:image/png;base64," + base64.b64encode(open("source/webapp/static/icons/icon-512.png", "rb").read()).decode()
_K = None
_CACHE: dict[str, tuple] = {}


def spoken(text: str) -> str:
    return (text.replace("IBKR", "I B K R").replace("E*TRADE", "E-Trade").replace("FinSi", "Fin-See").replace("Fin-Sigh", "Fin-See")
            .replace("CSV", "C S V").replace("RSI", "R S I").replace("MACD", "mack-dee"))


def speak(text: str):
    global _K
    text = spoken(text)
    if DRY:
        return np.zeros(int(min(6.0, 1.0 + len(text) / 18) * SR), dtype=np.float32), SR
    if text in _CACHE:
        return _CACHE[text]
    fn = "/tmp/ttscache/" + hashlib.md5(text.encode()).hexdigest() + ".npy"
    os.makedirs("/tmp/ttscache", exist_ok=True)
    if os.path.exists(fn):
        _CACHE[text] = (np.load(fn), SR)
    else:
        if _K is None:
            from kokoro_onnx import Kokoro
            _K = Kokoro("/tmp/kokoro/kokoro.onnx", "/tmp/kokoro/voices.bin")
        s, sr = _K.create(text, voice="af_heart", speed=0.97, lang="en-us")
        _CACHE[text] = (np.asarray(s, dtype=np.float32), sr)
        np.save(fn, _CACHE[text][0])
    return _CACHE[text]


_N = [0]


async def dry_snaps(pg, label):
    """Dry runs only: a picture every 2 seconds so the scenes can be checked without watching the video."""
    os.makedirs(OUT + "/dry", exist_ok=True)
    try:
        while True:
            _N[0] += 1
            await pg.screenshot(path=f"{OUT}/dry/{_N[0]:03d}_{label}.png")
            await pg.wait_for_timeout(1800)
    except Exception:
        pass


class R:
    """What the scene actions can use."""
    pg = None
    port = 0
    ctx = None


# ---- actions that happen while a step is being narrated ----------------------------------------------------------------------
async def tour_tabs(r):
    n = await r.pg.locator("nav a, .tabs a, .nav a").count()
    links = r.pg.locator("nav a")
    for i in range(min(5, await links.count())):
        await links.nth(i).evaluate(HL)
        await r.pg.wait_for_timeout(2300)
        await links.nth(i).evaluate("e => { e.style.outline = ''; }")


async def hide_balances(r):
    await r.pg.wait_for_timeout(1200)
    await r.pg.evaluate(CLEAR_HL)
    await r.pg.click("#hide-toggle")
    await r.pg.wait_for_timeout(3200)
    await r.pg.click("#hide-toggle")


async def show_help(r):
    await r.pg.evaluate(CLEAR_HL)
    for sel in (".ex-pagebar", "#tutorial-btn"):
        if await r.pg.locator(sel).count():
            await r.pg.locator(sel).first.evaluate(HL)
            await r.pg.wait_for_timeout(3500)
            await r.pg.evaluate(CLEAR_HL)


async def review_holdings(r):
    await r.pg.wait_for_timeout(1500)
    await r.pg.click("#hr-go")
    await r.pg.wait_for_selector("#hr-table tbody tr", timeout=90000)


async def alpaca_arm(r):
    await r.pg.wait_for_timeout(1500)
    await r.pg.type("input[name=phrase]", db.live_trading.CONFIRM_PHRASE, delay=70)
    await r.pg.wait_for_timeout(900)
    await r.pg.click("button:has-text('Turn live trading on')")
    await r.pg.wait_for_load_state("load")
    await r.pg.wait_for_timeout(1500)


async def open_menu(r, sel):
    """Brings the first matching Trade button to the middle of the screen and opens its menu."""
    await r.pg.locator(sel).first.evaluate("e => e.scrollIntoView({behavior: 'smooth', block: 'center', inline: 'nearest'})")
    await r.pg.wait_for_timeout(1100)
    await r.pg.locator(sel).first.evaluate("e => e.click()")
    await r.pg.wait_for_timeout(500)


async def flat(r):
    """Scroll every sideways-scrolling table back to its left edge (a click on a far-right button can push it)."""
    await r.pg.evaluate("document.querySelectorAll('*').forEach(e => { if (e.scrollLeft) { e.scrollLeft = 0; } })")


async def alpaca_menu(r):
    await open_menu(r, ".trade-btn")
    await r.pg.wait_for_timeout(3500)
    await r.pg.keyboard.press("Escape")


async def alpaca_preview(r):
    await open_menu(r, ".trade-btn")
    await r.pg.locator("#trade-menu .tm-buy").click()
    await r.pg.wait_for_timeout(1500)
    await r.pg.fill("#ticket input[name=qty]", "5")
    await r.pg.wait_for_timeout(600)
    await r.pg.click("#ticket button[type=submit]")
    await r.pg.wait_for_selector("#ticket-preview .status-line", timeout=20000)
    await r.pg.evaluate("document.getElementById('ticket-preview').scrollIntoView({behavior: 'smooth', block: 'center'})")


async def broker_menu(r):
    await r.pg.wait_for_selector(".bk-trade-btn", timeout=30000)
    await open_menu(r, ".bk-trade-btn")
    await r.pg.wait_for_timeout(3200)
    await r.pg.keyboard.press("Escape")
    await r.pg.mouse.click(5, 300)
    await flat(r)


async def broker_lots(r):
    await r.pg.locator(".lot-toggle").first.click()
    await r.pg.wait_for_selector("tr.bk-lot", timeout=15000)
    await r.pg.wait_for_timeout(2500)


async def broker_preview(r):
    await open_menu(r, ".bk-trade-btn")
    await r.pg.locator("#bk-tmenu button[data-act=sell]").click()
    await r.pg.wait_for_timeout(1200)
    await r.pg.click("#bk-form button[type=submit]")
    await r.pg.wait_for_selector(".bk-checks", timeout=20000)
    await r.pg.evaluate("document.querySelector('#bk-preview').scrollIntoView({behavior: 'smooth', block: 'center'})")


async def analysis_quote(r):
    await r.pg.fill("#quote input", "NVDA")
    await r.pg.locator("#quote button:has-text('Look up')").first.click()
    await r.pg.wait_for_timeout(3500)


async def analysis_watch(r):
    btn = r.pg.locator("button:has-text('to watchlist')")
    if await btn.count():
        await btn.first.click()
        await r.pg.wait_for_timeout(800)
    await r.pg.locator("summary:has-text('Watchlist')").first.click()
    await r.pg.wait_for_selector("#wl-table tbody tr", timeout=30000)
    await r.pg.evaluate("document.getElementById('wl-out').scrollIntoView({behavior: 'smooth', block: 'center'})")
    await r.pg.wait_for_timeout(3000)


async def screener_type(r):
    await r.pg.fill("#sc-text", "")
    await r.pg.type("#sc-text", "technology stocks that moved at least 5% this month", delay=45)
    await r.pg.wait_for_timeout(600)
    await r.pg.click("#sc-find")
    await r.pg.wait_for_timeout(2500)
    await r.pg.select_option("select[name=sort]", "rating")
    await r.pg.click("#sc-run")


async def screener_results(r):
    await r.pg.wait_for_selector("#sc-result-card table tbody tr", timeout=90000)
    await r.pg.evaluate("document.getElementById('sc-result-card').scrollIntoView({behavior: 'smooth', block: 'start'})")
    await r.pg.wait_for_timeout(2500)
    await r.pg.click("summary:has-text('Columns')")
    await r.pg.wait_for_timeout(1200)
    for col in ("type", "sector", "volume_ratio", "pc"):
        box = r.pg.locator(f"input[data-col={col}]")
        if await box.count() and await box.first.is_checked():
            await box.first.evaluate("e => e.click()")
            await r.pg.wait_for_timeout(500)
    await r.pg.click("summary:has-text('Columns')")
    boxes = r.pg.locator("#sc-result-card tbody input[type=checkbox]")
    for i in range(min(2, await boxes.count())):
        await boxes.nth(i).evaluate("e => e.click()")
        await r.pg.wait_for_timeout(500)
    await flat(r)


async def screener_menu(r):
    await open_menu(r, ".sc-trade-btn")
    await r.pg.wait_for_timeout(4200)
    await r.pg.keyboard.press("Escape")
    await r.pg.mouse.click(5, 300)


async def screener_save(r):
    await r.pg.fill("#sc-save-name", "Oversold stocks")
    await r.pg.wait_for_timeout(500)
    await r.pg.click("button:has-text('Save screen')")
    await r.pg.wait_for_timeout(1500)
    box = r.pg.locator("input[data-watch-saved]").first
    if await box.count():
        await box.check()
    await r.pg.evaluate("document.getElementById('sc-saved-card').scrollIntoView({behavior: 'smooth', block: 'center'})")
    await r.pg.wait_for_timeout(2500)


ACTS = {k: v for k, v in globals().items() if callable(v) and k in (
    "alpaca_arm", "analysis_watch", "tour_tabs", "hide_balances", "show_help", "review_holdings", "alpaca_menu", "alpaca_preview", "broker_menu", "broker_lots",
    "broker_preview", "analysis_quote", "screener_type", "screener_results", "screener_menu", "screener_save")}


class T(DashboardTestCase):
    def test_tour(self):
        for weeks_ago in range(52, -1, -4):
            growth = 1.0 - 0.11 * (weeks_ago / 52) + (0.012 if weeks_ago % 8 == 0 else -0.006) * (weeks_ago / 52)
            nw = 4_170_000 * growth
            db.record_snapshot(net_worth=nw, manual_asset_total=nw - 940_000 * growth, linked_asset_total=0.0, liability_total=0.0,
                               real_estate_equity_total=940_000 * growth, retirement_liquid_total=3_230_000 * growth,
                               snapshot_date=(date.today() - timedelta(weeks=weeks_ago)).isoformat())
        db.set_tour_seen(True)
        db.set_wording_mode("plain")            # what people see unless they switch it
        shutil.rmtree(OUT, ignore_errors=True)
        os.makedirs(OUT + "/shots", exist_ok=True)
        auth_store.clear_auth_cache()
        self.fake_keyring._store.clear()
        if PART == "setup":
            first_run.enforce(True)
        else:
            demo_data.seed_sample_household(with_linked=True)
            from source.common import backup as _bk
            _bk.create_backup("startup")
            time.sleep(1.2)
            _bk.create_backup("manual")
            db.set_view_mode("full")
        fakes.seed_orders()
        db.live_trading.disarm()
        if PART != "setup":
            db.watchlist.add(["MSFT", "KO", "JPM", "VTI"])
        events: list = []
        scenes_at: list = []
        defn = PARTS.get(PART)
        texts = [defn["intro"], defn["outro"]] if defn else [SETUP_TEXT["intro"], SETUP_TEXT["outro"]]
        for sc in (defn["scenes"] if defn else []):
            texts += [s["say"] for s in sc["steps"]]
        if PART == "setup":
            texts += [v for v in SETUP_TEXT.values() if isinstance(v, str)] + [s["say"] for s in SETUP_TEXT["tabs"]]
        for t in texts:
            speak(t)

        async def run():
            with contextlib.ExitStack() as stack:
                fakes.install(stack)
                async with async_playwright() as p:
                    b = await p.chromium.launch()
                    ctx = await b.new_context(color_scheme=SCHEME, viewport=VIEW, record_video_dir=OUT + "/video",
                                              record_video_size={"width": 1280, "height": 720})
                    await ctx.add_init_script(FIN_INIT)
                    await fakes.broker_routes(ctx)
                    pg = await ctx.new_page()
                    pg.set_default_timeout(40000)
                    pg.set_default_navigation_timeout(120000)
                    pg.on("pageerror", lambda e: print("PAGE ERROR:", e))
                    R.pg, R.port, R.ctx = pg, self.port, ctx
                    BASE = f"http://127.0.0.1:{self.port}"
                    t0 = time.monotonic()

                    async def say(text, min_hold=0.0):
                        audio, sr = speak(text)
                        events.append((time.monotonic() - t0, audio))
                        try:
                            await pg.evaluate("(ms) => window.__finTalk && window.__finTalk(ms)", int(len(audio) / sr * 1000))
                        except Exception:
                            pass
                        await pg.wait_for_timeout(int(max(min_hold, len(audio) / sr + (0.3 if DRY else 0.7)) * 1000))

                    async def card(text, note, head=None, sub=None):
                        html_ = (CARD.replace("@@LOGO@@", LOGO).replace("@@TAG@@", branding.PRODUCT_TAGLINE)
                                 .replace("@@HEAD@@", head or branding.PRODUCT_HEADLINE).replace("@@SUB@@", sub or branding.PRODUCT_SUBLINE)
                                 .replace("@@MOTTO@@", branding.PRODUCT_MOTTO).replace("@@NOTE@@", note))
                        try:
                            await pg.wait_for_load_state("load")
                            await pg.wait_for_timeout(1500)
                        except Exception:
                            pass
                        await pg.set_content(html_)
                        await pg.wait_for_timeout(600)
                        await say(text, 4)

                    async def step(st, label):
                        sel = st["sel"]
                        await pg.evaluate(CLEAR_HL)
                        if sel in ("top", "nav"):
                            await pg.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
                        else:
                            loc = pg.locator(sel).first
                            if await pg.locator(sel).count() == 0:
                                print("MISSING SELECTOR:", label, sel)
                            else:
                                await loc.evaluate(SCROLL)
                                if st.get("act") is None:
                                    await loc.evaluate(HL)
                        await pg.wait_for_timeout(500 if DRY else 1500)
                        await pg.evaluate(CAP_JS, st["cap"])
                        task = asyncio.create_task(say(st["say"], 3))
                        snaps = asyncio.create_task(dry_snaps(pg, label)) if (DRY and os.environ.get("TOUR_SNAPS") == "1") else None
                        act = ACTS.get(st.get("act") or "")
                        if act:
                            try:
                                await act(R)
                            except Exception as exc:        # noqa: BLE001
                                print("ACTION FAILED:", st.get("act"), repr(exc)[:300])
                        await task
                        if snaps:
                            snaps.cancel()

                    async def shot(name):
                        await pg.evaluate(CAP_JS, "")
                        await pg.evaluate(CLEAR_HL)
                        await pg.evaluate("window.scrollTo(0, 0)")
                        await pg.wait_for_timeout(500)
                        await pg.screenshot(path=f"{OUT}/shots/{name}.png", full_page=True)

                    n = ORDER.index(PART) + 1
                    title = defn["title"] if defn else "Setup"
                    await card((defn or SETUP_TEXT)["intro"], f"Video {n} of 5: {title}")
                    if PART == "setup":
                        await setup_part(self, pg, BASE, say, step, shot, scenes_at, events)
                    else:
                        for sc in defn["scenes"]:
                            await pg.goto(BASE + sc["path"], wait_until="load")
                            await pg.wait_for_timeout(1500 if not DRY else 800)
                            scenes_at.append((sc["name"], sc["chapter"], sc["path"], len(events)))
                            for st in sc["steps"]:
                                await step(st, sc["name"])
                            await shot(sc["name"])
                    await pg.evaluate(CAP_JS, "")
                    await card((defn or SETUP_TEXT)["outro"], "Not financial, investment, tax or legal advice.")
                    total = time.monotonic() - t0
                    await ctx.close()
                    await b.close()
                    return total

        total = asyncio.run(run())
        track = np.zeros(int((total + 3) * SR), dtype=np.float32)
        for start, audio in events:
            i = int(start * SR)
            track[i:i + len(audio)] += audio[:len(track) - i]
        pickle.dump(events, open(OUT + "/events.pkl", "wb"))
        json.dump(scenes_at, open(OUT + "/scenes.json", "w"))
        sf.write(OUT + "/narration.wav", track, SR)
        import glob
        print("VIDEO", glob.glob(OUT + "/video/*.webm"), "TOTAL", round(total, 1), "events", len(events), "scenes", len(scenes_at))


async def setup_part(self, pg, BASE, say, step, shot, scenes_at, events):
    """First launch, the setup wizard, connecting accounts, then a walk through the Setup tab."""
    N = SETUP_TEXT
    FAKE = "/Users/you/Library/Application Support/RetirementPlan/data"
    HLsel = "(sel) => { const e = document.querySelector(sel); if (!e) return; e.style.outline = '3px solid #ffb703'; e.style.outlineOffset = '4px'; e.style.borderRadius = '10px'; }"

    async def narrate(key, caption, secs=3):
        await pg.evaluate(CAP_JS, caption)
        await pg.evaluate("(t) => { const b = document.getElementById('wz-bubble'); if (b) b.textContent = t; }", N[key])
        await say(N[key], secs)

    async def typed(sel, text):
        await pg.click(sel, click_count=3)
        await pg.keyboard.press("Backspace")
        await pg.type(sel, text, delay=60 if not DRY else 5)

    scenes_at.append(("welcome", "First launch", "/", len(events)))
    await pg.goto(BASE + "/", wait_until="load")
    await pg.wait_for_timeout(1200)
    await pg.add_style_tag(content="body{padding-bottom:170px !important}")
    real = await pg.evaluate("document.getElementById('fr-folder').value")
    await pg.evaluate("(f) => { document.querySelectorAll('#first-run code').forEach(c => c.textContent = f); document.getElementById('fr-folder').value = f; }", FAKE)
    await pg.evaluate(CAP_JS, "First launch: create your admin password and database")
    await say(N["WELCOME1"], 3)
    await pg.evaluate("window.scrollTo({top: 140, behavior: 'smooth'})")
    await pg.wait_for_timeout(700)
    await pg.evaluate(HLsel, "input[name=password]")
    await typed("input[name=password]", "Sunshine-Maple-42")
    await typed("input[name=confirm]", "Sunshine-Maple-42")
    await say(N["WELCOME2"], 2)
    await pg.evaluate("document.querySelector('#first-run details').open = true")
    await pg.evaluate("document.getElementById('fr-folder').scrollIntoView({behavior: 'smooth', block: 'center'})")
    await pg.wait_for_timeout(900)
    await pg.evaluate(HLsel, "#first-run details")
    await say(N["WELCOME3"], 3)
    await pg.evaluate("(r) => { document.getElementById('fr-folder').value = r; }", real)
    await pg.click("button[type=submit]")
    await pg.wait_for_selector("#fr-done", state="visible")
    await pg.wait_for_timeout(800)
    await pg.evaluate("document.getElementById('fr-go').scrollIntoView({behavior: 'smooth', block: 'center'})")
    await pg.wait_for_timeout(900)
    await pg.evaluate(CAP_JS, "Save your recovery key. It is shown only once.")
    await say(N["WELCOME4"], 3)
    await pg.click("#fr-saved")
    await pg.wait_for_timeout(700)
    await pg.click("#fr-go")
    await pg.wait_for_load_state("load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate(CAP_JS, "")
    scenes_at.append(("wizard", "The setup wizard", "/setup-wizard.html", len(events)))
    await pg.goto(BASE + "/setup-wizard.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate(HLsel, "#wz-self")
    await narrate("SETUP1", "Step 1: who is the plan for?")
    await typed("#wz-self", "Alex")
    await typed("#wz-spouse", "Sam")
    await pg.click("#wz-next")
    await pg.wait_for_timeout(900)
    await typed("#wz-birth", "1968")
    await typed("#wz-spouse-birth", "1970")
    await typed("#wz-retire", "2031")
    await narrate("SETUP2", "Step 2: birth years and retirement year", 2)
    await pg.click("#wz-next")
    await pg.wait_for_timeout(900)
    await narrate("SETUP3", "Step 3: expected growth and inflation", 2)
    await pg.click("#wz-next")
    await pg.wait_for_timeout(900)
    await narrate("SETUP4", "Step 4: bring in your accounts", 2)
    scenes_at.append(("plaid", "Connecting accounts", "/setup.html", len(events)))
    await pg.goto(BASE + "/setup.html#plaid-keys", wait_until="load")
    await pg.wait_for_timeout(1000)
    await pg.locator("#plaid-keys").first.evaluate(SCROLL)
    await pg.wait_for_timeout(1500)
    await pg.evaluate(HLsel, "#plaid-keys ~ .card form")
    await narrate("SETUP5", "Connect with Plaid: paste your free Client ID and Secret")
    await pg.locator("#connect-account").first.evaluate(SCROLL)
    await pg.wait_for_timeout(1500)
    await pg.evaluate(HLsel, "#connect-account ~ form")
    await typed("input[name=item_key]", "wells_fargo_checking")
    await narrate("SETUP6", "Then press Connect and log in to your bank in Plaid's secure window")
    await pg.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    await pg.wait_for_timeout(1200)
    await pg.click(".fab-add")
    await pg.wait_for_timeout(900)
    await narrate("SETUP7", "Or type everything in by hand with + Add", 2)
    await pg.evaluate("closeAddModal()")
    await pg.wait_for_timeout(500)
    await narrate("SETUP8", "On Assets, mark what is in the plan. In Setup, set a password.", 2)
    await pg.evaluate(CAP_JS, "")
    await pg.goto(BASE + "/setup-wizard.html", wait_until="load")
    await pg.wait_for_timeout(800)
    for _ in range(3):
        await pg.click("#wz-next")
        await pg.wait_for_timeout(900)
    await pg.evaluate(HLsel, "#wz-sample")
    await narrate("SETUP9", "Just exploring? Load the sample household (made-up numbers)", 2)
    await pg.click("#wz-sample")
    await pg.wait_for_load_state("load")
    await pg.wait_for_timeout(2500)
    from source.common import backup as _bk
    _bk.create_backup("startup")
    time.sleep(1.2)
    _bk.create_backup("manual")
    db.set_view_mode("full")
    scenes_at.append(("setup", "The Setup tab", "/setup.html", len(events)))
    await pg.goto(BASE + "/setup.html", wait_until="load")
    await pg.wait_for_timeout(1500)
    await pg.evaluate("document.querySelectorAll('#alerts-card, #backups-card, #advanced-settings').forEach(d => d.open = true)")
    await pg.evaluate("""() => { const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let n;
      while ((n = w.nextNode())) { n.nodeValue = n.nodeValue.replace(/\\/tmp\\/tmp\\w+/g, '/Users/you/Library/Application Support/RetirementPlan'); }
      document.querySelectorAll('input').forEach(i => { i.value = i.value.replace(/\\/tmp\\/tmp\\w+/g, '/Users/you/Library/Application Support/RetirementPlan'); }); }""")
    for st in N["tabs"]:
        await step(st, "setup")
    await shot("setup")
    for _try in range(4):
        try:
            await pg.wait_for_timeout(1500)
            await pg.goto(BASE + "/summary.html", wait_until="load")
            break
        except Exception:
            pass


unittest.main(argv=["x", "T"])
