""""Fin", the friendly robot guide: an original character drawn as inline SVG,
with a mouth that moves while it talks. Used by the setup wizard (speech
bubble plus spoken voice) and drawn into the tutorial video.

Everything here is plain strings (no str.format placeholders), so the pieces can be
dropped into a page that is itself built with an f-string: a value that is
substituted is never re-scanned for braces."""

from __future__ import annotations

ROBOT_NAME = "Fin"

_SVG = """<svg class="rb" viewBox="0 0 100 112" width="{size}" height="{size}" role="img" aria-label="Fin, your friendly robot guide" xmlns="http://www.w3.org/2000/svg">
<defs>
<linearGradient id="rbHead" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#d6e3f6"/></linearGradient>
<linearGradient id="rbBody" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b8cf0"/><stop offset="1" stop-color="#0059b2"/></linearGradient>
</defs>
<line x1="50" y1="9" x2="50" y2="22" stroke="#8aa4c8" stroke-width="3" stroke-linecap="round"/>
<circle class="rb-tip" cx="50" cy="7" r="5.5" fill="#ffb703"/>
<rect x="4" y="44" width="10" height="20" rx="5" fill="#0071e3"/>
<rect x="86" y="44" width="10" height="20" rx="5" fill="#0071e3"/>
<rect x="29" y="86" width="42" height="22" rx="11" fill="url(#rbBody)"/>
<circle cx="50" cy="97" r="3.6" fill="#ffd166"/>
<rect x="12" y="20" width="76" height="66" rx="24" fill="url(#rbHead)" stroke="#b4c6e2" stroke-width="2"/>
<rect x="22" y="31" width="56" height="42" rx="15" fill="#0b2545"/>
<rect class="rb-eye" x="33" y="42" width="10" height="12" rx="5" fill="#7fd1ff"/>
<rect class="rb-eye" x="57" y="42" width="10" height="12" rx="5" fill="#7fd1ff"/>
<rect class="rb-mouth" x="41" y="60" width="18" height="3.6" rx="1.8" fill="#7fd1ff"/>
<circle cx="30" cy="62" r="3" fill="#ff8fab" opacity=".55"/>
<circle cx="70" cy="62" r="3" fill="#ff8fab" opacity=".55"/>
</svg>"""


def robot_svg(size: int = 84) -> str:
    return _SVG.replace("{size}", str(int(size)))


ROBOT_CSS = """
.rb { display: block; overflow: visible; flex: none; }
.rb-eye, .rb-mouth { transform-box: fill-box; transform-origin: center; }
.rb-eye { animation: rb-blink 4.4s infinite; }
.rb-tip { animation: rb-glow 2.2s ease-in-out infinite; }
.rb.talking { animation: rb-bob .55s ease-in-out infinite; }
.rb.talking .rb-mouth { animation: rb-talk .36s ease-in-out infinite; }
@keyframes rb-blink { 0%, 93%, 100% { transform: scaleY(1); } 96% { transform: scaleY(.1); } }
@keyframes rb-glow { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }
@keyframes rb-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-2px); } }
@keyframes rb-talk { 0%, 100% { transform: scale(1, 1); } 30% { transform: scale(.82, 3.6); } 60% { transform: scale(1.06, 1.8); } 80% { transform: scale(.78, 4.2); } }
@media (prefers-reduced-motion: reduce) { .rb, .rb * { animation: none !important; } }
.rb-guide { display: flex; gap: 14px; align-items: center; margin: 4px 0 14px; padding: 12px 14px; border-radius: 16px;
  background: var(--brand-soft, #e8f1fc); border: 1px solid var(--border, #d2d2d7); }
.rb-bubble { position: relative; flex: 1; min-width: 0; background: var(--surface, #fff); color: var(--ink, #1d1d1f);
  border: 1px solid var(--border, #d2d2d7); border-radius: 14px; padding: 10px 14px; font-size: 15px; line-height: 1.45; }
.rb-bubble::before { content: ""; position: absolute; left: -7px; top: 50%; width: 12px; height: 12px; margin-top: -6px;
  background: var(--surface, #fff); border-left: 1px solid var(--border, #d2d2d7); border-bottom: 1px solid var(--border, #d2d2d7);
  transform: rotate(45deg); }
.rb-name { font-size: 12px; font-weight: 700; color: var(--brand, #0071e3); letter-spacing: .03em; text-transform: uppercase; margin-bottom: 2px; }
.rb-ctl { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.rb-ctl button { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; padding: 5px 10px; border-radius: 99px; }
.rb-ctl svg { width: 14px; height: 14px; flex: none; }
@media (max-width: 560px) { .rb-guide { flex-direction: column; align-items: flex-start; } .rb-bubble::before { display: none; } }
"""

SPEAKER_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                'stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>'
                '<path d="M18.5 5.5a9 9 0 0 1 0 13"/></svg>')
MUTED_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
              'stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="m16 9 5 6"/><path d="m21 9-5 6"/></svg>')

# Page script: window.rpFin.say(text, opts) shows nothing by itself; it speaks `text`
# (if the voice is on) and moves the robot's mouth while it does. Voice choice is
# remembered per browser; the mouth also moves for a moment when the voice is off,
# so the character still feels alive. Never throws when speech is unavailable.
ROBOT_JS = """
(function () {
  var KEY = 'rp-robot-voice', fin = {}, activated = false;
  function robot() { return document.querySelector('.rb'); }
  function setTalking(on) { var r = robot(); if (r) { r.classList.toggle('talking', !!on); } }
  function synth() { try { return window.speechSynthesis || null; } catch (e) { return null; } }
  function voiceOn() { try { return localStorage.getItem(KEY) !== 'off'; } catch (e) { return true; } }
  function setVoice(on) { try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch (e) {} }
  function pickVoice() {
    var s = synth(); if (!s) { return null; }
    var all = s.getVoices() || [], en = all.filter(function (v) { return /^en[-_]/i.test(v.lang); });
    var prefer = ['Samantha', 'Ava', 'Allison', 'Karen', 'Moira', 'Serena', 'Google US English', 'Microsoft Aria', 'Zira'];
    for (var i = 0; i < prefer.length; i++) {
      for (var j = 0; j < en.length; j++) { if (en[j].name.indexOf(prefer[i]) >= 0) { return en[j]; } }
    }
    return en[0] || null;
  }
  var timer = null;
  fin.stop = function () {
    var s = synth(); if (s) { try { s.cancel(); } catch (e) {} }
    if (timer) { clearTimeout(timer); timer = null; }
    setTalking(false);
  };
  fin.say = function (text, force) {
    fin.stop();
    var s = synth(), canSpeak = s && (force || voiceOn()) && (force || activated || (navigator.userActivation && navigator.userActivation.hasBeenActive));
    if (canSpeak && typeof SpeechSynthesisUtterance !== 'undefined') {
      try {
        var u = new SpeechSynthesisUtterance(text), v = pickVoice();
        if (v) { u.voice = v; u.lang = v.lang; } else { u.lang = 'en-US'; }
        u.rate = 1.0; u.pitch = 1.08;
        u.onstart = function () { setTalking(true); };
        u.onend = u.onerror = function () { setTalking(false); };
        s.speak(u);
        return;
      } catch (e) {}
    }
    // Voice off or unavailable: a short, silent "talking" moment while the words are read.
    setTalking(true); timer = setTimeout(function () { setTalking(false); }, Math.min(4500, 500 + text.length * 38));
  };
  fin.voiceOn = voiceOn; fin.setVoice = setVoice; fin.activate = function () { activated = true; };
  document.addEventListener('pointerdown', function () { activated = true; }, true);
  document.addEventListener('keydown', function () { activated = true; }, true);
  window.addEventListener('pagehide', fin.stop);
  if (synth() && synth().addEventListener) { synth().addEventListener('voiceschanged', function () {}); }
  window.rpFin = fin;
})();
"""
