"""The one shared stylesheet every page's shell embeds (see shell.py's
PAGE_SHELL). Split out on its own purely because it's a long, purely
declarative CSS blob with nothing else in common with the Python helpers
around it -- nothing here depends on, or is depended on by, any other
render_helpers submodule.

Visual language is deliberately modeled on Apple's own first-party apps
(Settings/System Preferences, Music, App Store) and apple.com's own
marketing-site CSS: the canonical light-gray page background (#f5f5f7),
near-black ink (#1d1d1f) rather than pure black, the "Buy button" blue
(#0071e3), pill-shaped buttons (border-radius: 980px -- Apple's own
trick for "however tall this button ends up, round it all the way"),
large-radius cards, very soft/low-opacity shadows, and a translucent,
sticky, blurred top toolbar (the macOS/iOS "vibrancy" effect, via
backdrop-filter) standing in for a native title bar. Dark mode is a true
second palette (not just an automatic filter) that follows the OS
appearance automatically via prefers-color-scheme -- exactly how every
native Apple app behaves, and meaningful here specifically because this
program is meant to be run as a Mac app. `-apple-system` as the first
font-family already resolves to actual San Francisco on the Mac this
almost always runs on; nothing here loads a web font.
"""

from __future__ import annotations


# Runs in <head> (before first paint, so there's no light-to-dark flash)
# on every page, login included: applies a saved Light/Dark choice as
# <html data-theme>. No saved choice = "Auto" = follow the OS appearance
# through the prefers-color-scheme block in PAGE_CSS. Also defines the
# toggle's own cycle/label helpers (Auto -> Light -> Dark -> Auto). Kept
# as a plain string substituted into the page (never .format()-ed), so
# its literal braces need no doubling.
THEME_INIT_SCRIPT = """<script>
(function () {
  function stored() { try { return localStorage.getItem('rp-theme') || ''; } catch (e) { return ''; } }
  function apply(t) {
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
    else document.documentElement.removeAttribute('data-theme');
  }
  apply(stored());
  // "Hide balances": blurs every dollar figure (for demos and screenshots).
  // The choice lives in localStorage; dollar amounts in the page text are
  // tagged with class "mny" once the DOM is ready (see tagMoney).
  function hidden() { try { return localStorage.getItem('rp-hide') === '1'; } catch (e) { return false; } }
  if (hidden()) document.documentElement.classList.add('hide-money');
  var MONEY = /-?\\$\\s?\\d[\\d,]*(?:\\.\\d+)?\\s?[KMB]?/g;
  function tagMoney(root) {
    root = root || document.body;
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var nodes = [], n;
    while ((n = walker.nextNode())) { nodes.push(n); }
    nodes.forEach(function (node) {
      var parent = node.parentNode;
      if (!parent || /^(SCRIPT|STYLE|TEXTAREA|OPTION|TITLE)$/i.test(parent.nodeName) || (parent.classList && parent.classList.contains('mny'))) return;
      if (!MONEY.test(node.nodeValue)) { MONEY.lastIndex = 0; return; }
      MONEY.lastIndex = 0;
      if (parent.namespaceURI === 'http://www.w3.org/2000/svg') { parent.classList.add('mny'); return; }
      var frag = document.createDocumentFragment(), text = node.nodeValue, last = 0, m;
      while ((m = MONEY.exec(text))) {
        if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
        var span = document.createElement('span'); span.className = 'mny'; span.textContent = m[0];
        frag.appendChild(span); last = m.index + m[0].length;
      }
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      parent.replaceChild(frag, node);
    });
  }
  // Dollar-amount inputs (what-if, assumptions, balances...) are blurred too:
  // any text/number box whose name, id or label looks like money.
  var MONEY_FIELD = /amount|balance|spend|income|saving|value|cost|price|salary|wage|withdraw|payment|contribution|expense|dollar|worth|equity|\\$/i;
  var NOT_MONEY_FIELD = /pct|percent|year|age\\b|rate|iteration|seed|ticker|name|password|email|note|%/i;
  function tagMoneyInputs(root) {
    (root.querySelectorAll ? root.querySelectorAll('input') : []).forEach(function (el) {
      if (el.hasAttribute('data-money') || !/^(text|number|)$/i.test(el.type || '')) return;
      var lab = el.closest('label'), label = lab ? lab.textContent : '';
      var key = (el.name || '') + ' ' + (el.id || '') + ' ' + (el.getAttribute('data-field') || '');
      if ((MONEY_FIELD.test(key) || /\\$/.test(label)) && !NOT_MONEY_FIELD.test(key) && !/%/.test(label)) el.setAttribute('data-money', '1');
    });
  }
  // Hover tooltips (SVG <title> and title="" attributes) would still spell out
  // the dollars, so they are masked while balances are hidden and restored after.
  function maskTitles(root, hide) {
    root = root || document.body;
    var scan = root.querySelectorAll ? Array.prototype.slice.call(root.querySelectorAll('title, [title], [data-orig-title]')) : [];
    if (root.nodeType === 1) scan.push(root);
    scan.forEach(function (el) {
      if (el.nodeName.toLowerCase() === 'title') {
        if (!el.closest('svg')) return;
        var orig = el.getAttribute('data-orig');
        if (hide && orig === null && /\\$\\s?\\d/.test(el.textContent)) {
          el.setAttribute('data-orig', el.textContent);
          el.textContent = el.textContent.replace(/\\$\\s?\\d[\\d,]*(?:\\.\\d+)?\\s?[KMB]?/g, '$***');
        } else if (!hide && orig !== null) { el.textContent = orig; el.removeAttribute('data-orig'); }
      } else {
        var t = el.getAttribute('title'), o = el.getAttribute('data-orig-title');
        if (hide && o === null && t && /\\$\\s?\\d/.test(t)) {
          el.setAttribute('data-orig-title', t);
          el.setAttribute('title', t.replace(/\\$\\s?\\d[\\d,]*(?:\\.\\d+)?\\s?[KMB]?/g, '$***'));
        } else if (!hide && o !== null) { el.setAttribute('title', o); el.removeAttribute('data-orig-title'); }
      }
    });
  }
  function tagAll(root) { tagMoney(root); tagMoneyInputs(root); maskTitles(root, hidden()); }
  document.addEventListener('DOMContentLoaded', function () {
    tagAll(document.body); window.rpHideSync();
    // Figures filled in later by scripts (safe spending, what-if, analyses...) get tagged as they appear.
    var pending = false, queue = [];
    new MutationObserver(function (muts) {
      muts.forEach(function (m) { m.addedNodes.forEach(function (nd) { if (nd.nodeType === 1 || nd.nodeType === 3) queue.push(nd); }); });
      if (pending || !queue.length) return;
      pending = true;
      setTimeout(function () {
        var items = queue; queue = []; pending = false;
        items.forEach(function (nd) {
          if (nd.nodeType === 3) { if (nd.parentNode && nd.parentNode.nodeType === 1) tagMoney(nd.parentNode); }
          else if (nd.isConnected) tagAll(nd);
        });
      }, 30);
    }).observe(document.body, {childList: true, subtree: true});
  });
  window.rpHideSync = function () {
    var b = document.getElementById('hide-toggle');
    if (!b) return;
    var label = hidden() ? 'Show balances' : 'Hide balances';
    b.title = label + (hidden() ? '' : ' -- blur every dollar amount, handy for demos and screenshots');
    b.setAttribute('aria-label', label);
  };
  window.rpToggleHide = function () {
    var next = !hidden();
    try { if (next) localStorage.setItem('rp-hide', '1'); else localStorage.removeItem('rp-hide'); } catch (e) {}
    document.documentElement.classList.toggle('hide-money', next);
    maskTitles(document.body, next);
    window.rpHideSync();
  };
  window.rpThemeSync = function () {
    var b = document.getElementById('theme-toggle');
    if (!b) return;
    var t = stored();
    b.textContent = 'Theme: ' + (t === 'light' ? 'Light' : t === 'dark' ? 'Dark' : 'Auto');
  };
  window.rpCycleTheme = function () {
    var order = ['', 'light', 'dark'];
    var next = order[(order.indexOf(stored()) + 1) % order.length];
    try { if (next) localStorage.setItem('rp-theme', next); else localStorage.removeItem('rp-theme'); } catch (e) {}
    apply(next);
    window.rpThemeSync();
  };
})();
</script>"""

_EYE_SVG = (
    '<svg class="eye" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/>'
    '<circle cx="12" cy="12" r="3"/></svg>'
    '<svg class="eye-off" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.9 17.9A10.9 10.9 0 0 1 12 19C5.6 19 2 12 2 12a18.5 18.5 0 0 1 5.1-5.9"/>'
    '<path d="M9.9 4.2A10.4 10.4 0 0 1 12 4c6.4 0 10 7 10 7a18.6 18.6 0 0 1-2.2 3.2"/><path d="M14.1 14.1a3 3 0 1 1-4.2-4.2"/>'
    '<line x1="2" y1="2" x2="22" y2="22"/></svg>'
)

THEME_TOGGLE_HTML = (
    '<a href="/report.html" target="_blank" rel="noopener" id="report-link" '
    'title="Open a clean, printable report of this plan -- save it as a PDF"><button type="button" class="primary" '
    'id="report-btn">Report Download</button></a>'
    '<a href="/tutorial.html" id="tutorial-link" title="Watch the video tour and read the user guide">'
    '<button type="button" class="primary" id="tutorial-btn">Tutorial</button></a>'
    '<button type="button" id="hide-toggle" onclick="rpToggleHide()" aria-label="Hide balances" '
    f'title="Hide balances -- blur every dollar amount, handy for demos and screenshots">{_EYE_SVG}</button>'
    '<!--wording-toggle-->'
    '<button type="button" id="theme-toggle" onclick="rpCycleTheme()" '
    'title="Switch between Auto (follow your Mac), Light and Dark">Theme: Auto</button>'
    "<script>rpThemeSync();</script>"
)


PAGE_CSS = """
  :root {
    --brand: #0071e3; --brand-dark: #0059b2; --brand-soft: #e8f1fc;
    --ink: #1d1d1f; --ink-muted: #6e6e73; --ink-soft: #424245; --navy: #14283f; --raise-top: #ffffff; --raise-bottom: #eef1f7; --hi: rgba(255,255,255,0.95); --lo: rgba(20,40,80,0.07); --drop: 20,40,80;
    --surface: #ffffff; --surface-alt: #f5f5f7; --border: #d2d2d7;
    --success: #1f8a3f; --warn: #b36200; --danger: #d70015;
    --radius: 12px; --radius-lg: 18px;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.04), 0 1px 1px rgba(0,0,0,0.03);
    --shadow-md: 0 16px 32px rgba(0,0,0,0.10), 0 2px 8px rgba(0,0,0,0.05);
    --ease: cubic-bezier(0.28, 0.11, 0.32, 1);
  }
  /* Dark mode follows the Mac's own System Settings > Appearance by
     default (same as every native Apple app), and the header's theme
     toggle can force Light or Dark instead (stored in localStorage and
     applied as <html data-theme="light|dark"> before first paint -- see
     THEME_INIT_SCRIPT). Re-points every token above to its dark-surface
     equivalent; nothing below this block needs to know which mode is
     active, since everything is already built on var(--...). Shadows
     soften in favor of the hairline --border for card separation, same
     as macOS dark mode's own preference for borders over cast shadows
     on a dark background. */
  :root { color-scheme: light dark; }
  :root[data-theme="light"] { color-scheme: light; }
  :root[data-theme="dark"] { color-scheme: dark; }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --brand: #0a84ff; --brand-dark: #409cff; --brand-soft: rgba(10,132,255,0.18);
      --ink: #f5f5f7; --ink-muted: #98989d; --ink-soft: #c7c7cc; --navy: #8db4e8; --raise-top: #3b3b3f; --raise-bottom: #242426; --hi: rgba(255,255,255,0.12); --lo: rgba(0,0,0,0.45); --drop: 0,0,0;
      --surface: #2c2c2e; --surface-alt: #1c1c1e; --border: #38383a;
      --success: #32d74b; --warn: #ff9f0a; --danger: #ff453a;
      --shadow-sm: 0 1px 2px rgba(0,0,0,0.3);
      --shadow-md: 0 16px 32px rgba(0,0,0,0.45), 0 2px 8px rgba(0,0,0,0.3);
    }
  }
  :root[data-theme="dark"] {
    --brand: #0a84ff; --brand-dark: #409cff; --brand-soft: rgba(10,132,255,0.18);
    --ink: #f5f5f7; --ink-muted: #98989d; --ink-soft: #c7c7cc; --navy: #8db4e8; --raise-top: #3b3b3f; --raise-bottom: #242426; --hi: rgba(255,255,255,0.12); --lo: rgba(0,0,0,0.45); --drop: 0,0,0;
    --surface: #2c2c2e; --surface-alt: #1c1c1e; --border: #38383a;
    --success: #32d74b; --warn: #ff9f0a; --danger: #ff453a;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.3);
    --shadow-md: 0 16px 32px rgba(0,0,0,0.45), 0 2px 8px rgba(0,0,0,0.3);
  }
  /* Summary: hero verdict, status badge, own/owe bar, segmented control */
  .small { font-size: 12.5px; }
  .card-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
  .hero { padding: 22px 24px; }
  .hero-top { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
  .hero-title { font-size: 26px; letter-spacing: -0.02em; margin: 10px 0 4px; }
  .hero-verdict { font-size: 17px; line-height: 1.45; color: var(--ink-soft); margin: 0 0 14px; max-width: none; text-wrap: balance; }
  .hero-note { font-size: 15px; line-height: 1.55; color: var(--ink); margin: 14px 0 0; padding: 12px 16px; border-radius: 12px;
    background: color-mix(in srgb, var(--brand) 11%, var(--surface)); border: 1px solid color-mix(in srgb, var(--brand) 28%, var(--border));
    border-left: 4px solid var(--brand); }
  .hero-note a { font-weight: 650; white-space: nowrap; }
  .hero-change { font-size: 14.5px !important; color: var(--ink) !important; margin-top: 8px !important; }
  .hero-watch { font-size: 14px !important; line-height: 1.5; padding: 9px 12px; border-radius: 10px; margin-top: 10px !important;
    background: color-mix(in srgb, var(--warn) 12%, var(--surface)); border-left: 4px solid var(--warn); }
  .hero-watch strong { font-weight: 600; color: var(--ink); }
  .hero.tone-ok { border-top: 4px solid var(--success); }
  .hero.tone-warn { border-top: 4px solid var(--warn); }
  .hero.tone-bad { border-top: 4px solid var(--danger); }
  .badge { display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 12.5px; font-weight: 700; letter-spacing: .01em; }
  .badge-ok { color: var(--success); background: color-mix(in srgb, var(--success) 14%, transparent); }
  .badge-warn { color: var(--warn); background: color-mix(in srgb, var(--warn) 16%, transparent); }
  .badge-bad { color: var(--danger); background: color-mix(in srgb, var(--danger) 14%, transparent); }
  .hero-tile .value { font-size: 26px; }
  .segbar { display: flex; height: 18px; border-radius: 9px; overflow: hidden; background: var(--surface-alt); margin: 8px 0 12px;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.12); gap: 2px; }
  .segbar-part { display: block; height: 100%; }
  .legend-list { list-style: none; margin: 0 0 12px; padding: 0; font-size: 13px; }
  .legend-list li { display: flex; align-items: center; gap: 8px; padding: 3px 0; }
  .legend-list .grow { flex: 1; }
  .legend-inline { list-style: none; display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 0; margin: 8px 0 0; font-size: 12.5px; color: var(--ink-soft); }
  .legend-inline li { display: flex; align-items: center; gap: 6px; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .dash { display: inline-block; width: 18px; border-top: 2px dashed var(--ink); }
  .sub { font-size: 13.5px; margin: 14px 0 4px; color: var(--ink-soft); text-transform: uppercase; letter-spacing: .03em; }
  /* Simple / Full view (a display preference only -- see db.view_mode): .adv-only
     parts and long grey explanations are tucked away in Simple view. */
  body[data-view="simple"] .adv-only { display: none !important; }
  body[data-view="simple"] nav a[href="/drawdown-planning.html"] { display: none !important; }
  .simple-only { display: none !important; }
  body[data-view="simple"] .simple-only { display: flex !important; }
  .tx-short { display: none; }
  body[data-view="simple"] .tx-short { display: block; }
  body[data-view="simple"] .tx-short + p { display: none; }
  .seg-group { display: inline-flex; border: 1px solid var(--border); border-radius: 999px; overflow: hidden; }
  .seg-group .seg { border: 0; border-radius: 0; background: transparent; color: var(--ink-soft); font-size: 12px; padding: 5px 12px; box-shadow: none; }
  .seg-group .seg.on { background: var(--brand); color: #fff; }
  .note-box { background: color-mix(in srgb, var(--warn) 10%, var(--surface)); border: 1px solid color-mix(in srgb, var(--warn) 35%, var(--border));
    border-radius: 12px; padding: 10px 14px; font-size: 13px; margin: 6px 0 12px; }
  .trust-footer { margin: 18px 2px 30px; line-height: 1.55; }
  .whatif-table { width: 100%; border-collapse: collapse; font-size: 13.5px; margin: 6px 0 12px; }
  .whatif-table td { padding: 7px 4px; border-bottom: 1px solid var(--border); }
  .whatif-table th { padding: 4px; text-align: left; font-size: 11px; font-weight: 600; color: var(--ink-muted); text-transform: uppercase; letter-spacing: .04em; border-bottom: 1px solid var(--border); }
  .whatif-table th.num { text-align: right; }
  .ledger { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 28px; margin-top: 6px; }
  @media (max-width: 640px) { .ledger { grid-template-columns: 1fr; } }
  .ledger-list { list-style: none; margin: 4px 0 0; padding: 0; font-size: 14px; }
  .ledger-list li { padding: 7px 0; border-bottom: 1px solid var(--border); }
  .ledger-row { display: flex; align-items: center; gap: 8px; }
  .ledger-row .grow, .ledger-net .grow { flex: 1; }
  .ledger-note { margin: 2px 0 0 18px; }
  .ledger-total { font-weight: 600; border-bottom: 0 !important; }
  .ledger-net { display: flex; align-items: center; gap: 10px; margin: 10px 0 8px; padding: 10px 14px; border-radius: 10px; background: var(--surface-alt); border: 1px solid var(--border); font-size: 15px; }
  .ledger-net strong { font-size: 18px; }
  .legend-inline li.legend-btn { cursor: pointer; user-select: none; padding: 2px 8px; border-radius: 99px; border: 1px solid transparent; }
  .legend-inline li.legend-btn:hover { border-color: var(--border); }
  .legend-inline li.legend-btn.on { border-color: var(--ink-muted); font-weight: 600; }
  svg.focusing rect.seg { opacity: .18; } svg.focusing rect.seg.on { opacity: 1; }
  .yr-hit { cursor: pointer; }
  .src-detail { min-height: 38px; margin-top: 8px; padding: 8px 12px; border-radius: 10px; background: var(--surface-alt); border: 1px solid var(--border); line-height: 1.7; }
  .src-chip .dot { margin-right: 5px; }
  .src-chip { display: inline-block; margin-right: 10px; white-space: nowrap; } .src-chip.on { text-decoration: underline; }
  .whatif-form { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: flex-end; margin: 8px 0 0; }
  .whatif-form label { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--ink-muted); }
  .whatif-form input { width: 130px; }
  .whatif-form input:disabled { opacity: .5; }
  button.chip { font-size: 12px; padding: 3px 10px; border-radius: 99px; margin: 0 2px; }
  .whatif-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
  .up { color: var(--success); } .down { color: var(--danger); }
  .brand-tagline { color: var(--navy); font-weight: 600; letter-spacing: .02em; }
  .tiles.tiles-five { grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); }
  .badge-whatif { display: inline-block; font-size: 11px; font-weight: 600; color: #7a5af8; background: rgba(122,90,248,.12); border-radius: 99px; padding: 1px 8px; }
  .acct-num { filter: blur(5px); transition: filter .15s; }
  .acct-num:hover, html.show-acct .acct-num { filter: none; }
  .demo-banner { background: #fff4d6; color: #5c4400; border: 1px solid #f0d58a; border-radius: 10px; padding: 8px 14px; margin: 10px 0; font-size: 13px; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .demo-banner { background: #3a2f10; color: #f3dfa2; border-color: #6b5518; } }
  :root[data-theme="dark"] .demo-banner { background: #3a2f10; color: #f3dfa2; border-color: #6b5518; }
  html.hide-money .mny, html.hide-money input[data-money] { filter: blur(7px); user-select: none; }
  /* Header: the buttons always sit at the top right, in one tidy row that stays right-aligned if it has to wrap. */
  .hdr-actions { margin-left: auto; justify-content: flex-end; }
  .hdr-actions > * { flex: none; }
  .hdr-actions button, .hdr-actions a.btn { padding: 6px 10px; }
  @media (max-width: 1180px) {
    .hdr-brand img { width: 56px; height: 56px; border-radius: 14px; }
    .hdr-brand .brand-tagline { display: none; }
  }
  @media (max-width: 1000px) {
    .hdr-brand { min-width: 0; }
    .hdr-brand p { display: none; }
  }
  #hide-toggle, #theme-toggle, #wording-toggle, #report-btn, #sync-btn, #quit-btn { align-self: flex-start; font-size: 12px; padding: 6px 12px; white-space: nowrap; }
  #hide-toggle { padding: 6px 8px; line-height: 0; display: inline-flex; align-items: center; }
  #hide-toggle .eye-off { display: none; } html.hide-money #hide-toggle .eye { display: none; } html.hide-money #hide-toggle .eye-off { display: inline; }
  #report-link { text-decoration: none; }
  .standing { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; margin-top: 8px; }
  .standing .box { background: var(--surface-alt); border: 1px solid var(--border); border-radius: 12px; padding: 14px; }
  .standing h3 { margin: 0 0 6px; font-size: 13px; color: var(--ink-muted); text-transform: uppercase; letter-spacing: .04em; font-weight: 600; }
  .standing .big { font-size: 24px; font-weight: 700; letter-spacing: -0.02em; margin: 2px 0 6px; }
  .fi-bar { height: 10px; border-radius: 99px; background: var(--border); overflow: hidden; margin: 8px 0; }
  .fi-bar > i { display: block; height: 100%; background: var(--brand); border-radius: 99px; }
  .standing ul { margin: 6px 0 0 18px; padding: 0; font-size: 13px; }
  .compare-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-top: 12px; }
  .compare-card { background: var(--surface-alt); border: 1px solid var(--border); border-radius: 12px; padding: 14px; }
  .compare-card.best { border-color: var(--success); box-shadow: 0 0 0 1px var(--success) inset; }
  .compare-card .nm { font-weight: 650; font-size: 14px; margin-bottom: 4px; }
  .compare-card .pct { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; }
  .compare-card dl { margin: 8px 0 0; font-size: 12px; display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; }
  .compare-card dt { color: var(--ink-muted); } .compare-card dd { margin: 0; text-align: right; font-weight: 550; }
  .help { border-bottom: 1px dotted var(--ink-muted); cursor: help; position: relative; }
  .help:hover::after, .help:focus::after { content: attr(data-tip); position: absolute; left: 0; top: 1.5em; z-index: 50; width: 240px; background: var(--ink); color: var(--surface);
    font-size: 12px; font-weight: 400; line-height: 1.35; padding: 8px 10px; border-radius: 8px; box-shadow: var(--shadow-md); text-transform: none; letter-spacing: 0; white-space: normal; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Helvetica, Arial, sans-serif;
    max-width: 1080px; margin: 0 auto; padding: 28px 20px 96px; color: var(--ink); background: var(--surface-alt);
    -webkit-font-smoothing: antialiased; }
  h1 { font-size: 22px; margin: 0 0 4px 0; font-weight: 700; letter-spacing: -0.015em; }
  h2 { font-size: 18px; margin: 28px 0 10px 0; font-weight: 650; color: var(--ink); letter-spacing: -0.005em; }
  h3 { color: var(--ink); font-weight: 600; }
  .muted { color: var(--ink-muted); font-size: 12px; }
  /* Readable notes: paragraph-level grey notes get a larger size and a darker grey; the first note under a
     page title is the tab's purpose, so it is larger still. Inline spans, table cells and tile labels keep
     their small grey style. */
  p.muted, div.muted { font-size: 14px; line-height: 1.55; color: var(--ink-soft); }
  p.muted.small, div.muted.small { font-size: 13px; line-height: 1.5; }
  h2 + p.muted { font-size: 15px; line-height: 1.6; }
  /* macOS/iOS-style translucent toolbar -- sticky to the top of the
     viewport, with the "vibrancy" frosted-glass blur Apple uses for
     Safari's tab bar, Mail's toolbar, Settings' sidebar, etc. Falls
     back to a plain opaque bar (no blur, no stick) on a browser engine
     without backdrop-filter support -- @supports guards it rather than
     relying on the property silently no-opping, since an unsupported
     backdrop-filter MUST NOT leave the semi-transparent background on
     its own (that would make nav text illegible against whatever
     scrolls underneath it). */
  nav { display: flex; gap: 2px; flex-wrap: nowrap; margin: 18px 0 28px 0; background: var(--surface);
    border: 1px solid var(--border); border-radius: 12px; padding: 5px; box-shadow: var(--shadow-sm); }
  @supports (backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)) {
    nav { position: sticky; top: 10px; z-index: 20; background: color-mix(in srgb, var(--surface) 72%, transparent);
      -webkit-backdrop-filter: saturate(180%) blur(20px); backdrop-filter: saturate(180%) blur(20px); }
  }
  nav a { display: flex; flex-direction: column; align-items: center; gap: 5px; padding: 7px 4px 6px;
    border-radius: 14px; text-decoration: none; color: var(--ink-soft); font-size: clamp(11.5px, 1.15vw, 13.5px); line-height: 1.15;
    font-weight: 500; transition: background 0.15s var(--ease), color 0.15s var(--ease);
    flex: 1 1 0; text-align: center; }
  /* iOS-style 3D icon tile: vertical gradient, glossy top highlight, inner
     bevel (light top edge, dark bottom edge) and a soft cast shadow. */
  nav a .ni { position: relative; width: clamp(48px, 5.4vw, 64px); aspect-ratio: 1; border-radius: 23%; display: grid; place-items: center;
    background: linear-gradient(180deg, var(--c1), var(--c2));
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.6), inset 0 -2px 3px rgba(0,0,0,0.25),
      0 4px 7px rgba(0,0,0,0.28), 0 1px 1px rgba(0,0,0,0.25);
    transition: transform 0.15s var(--ease), box-shadow 0.15s var(--ease); }
  nav a .ni::before { content: ""; position: absolute; left: 0; right: 0; top: 0; height: 52%;
    border-radius: 23% 23% 60% 60% / 23% 23% 30% 30%;
    background: linear-gradient(180deg, rgba(255,255,255,0.45), rgba(255,255,255,0.02)); pointer-events: none; }
  nav a .ni svg { position: relative; width: 54%; height: 54%; fill: none; stroke: #fff; stroke-width: 2;
    stroke-linecap: round; stroke-linejoin: round; filter: drop-shadow(0 1px 1px rgba(0,0,0,0.4)); }
  nav a:not(.active):hover .ni { transform: translateY(-2px); }
  nav a:not(.active):hover { color: var(--ink); }
  nav a.active { background: var(--brand-soft); color: var(--brand); font-weight: 600; }
  nav a.active .ni { transform: translateY(-1px) scale(1.06);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.65), inset 0 -2px 3px rgba(0,0,0,0.25),
      0 7px 12px rgba(0,0,0,0.32), 0 0 0 2px var(--brand); }
  .subnav { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 22px 0; }
  .subnav a { padding: 9px 15px; border-radius: 999px; text-decoration: none; font-size: 14.5px; font-weight: 600;
    color: var(--ink); border: 1.5px solid var(--border); background: var(--surface); box-shadow: var(--shadow-sm); }
  .subnav a.active { border-color: var(--brand); background: var(--brand); color: #fff; }
  .subnav a:not(.active):hover { border-color: var(--brand); color: var(--brand); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; background: var(--surface); }
  th, td { text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--border); }
  th { background: var(--surface-alt); font-weight: 600; color: var(--ink-soft); font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.04em; }
  td.num, th.num { text-align: right; }
  tfoot td { font-weight: 600; border-top: 2px solid var(--border); background: var(--surface-alt); }
  .tiles { display: flex; gap: 14px; flex-wrap: wrap; margin: 14px 0 22px 0; }
  /* Apple-style raised tiles: a faint top-to-bottom gradient, a bright
     inner top edge and a soft inner bottom edge (the bevel), then a tight
     contact shadow plus a wide soft one underneath for depth. */
  .tile { flex: 1 1 170px; border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px;
    background: linear-gradient(180deg, var(--raise-top), var(--raise-bottom));
    box-shadow: inset 0 1px 0 var(--hi), inset 0 -1px 0 var(--lo),
      0 1px 1px rgba(var(--drop),0.10), 0 6px 14px rgba(var(--drop),0.12), 0 12px 24px -8px rgba(var(--drop),0.10);
    transition: transform 0.18s var(--ease), box-shadow 0.18s var(--ease); }
  .tile:hover { transform: translateY(-2px);
    box-shadow: inset 0 1px 0 var(--hi), inset 0 -1px 0 var(--lo),
      0 2px 2px rgba(var(--drop),0.10), 0 12px 22px rgba(var(--drop),0.18), 0 20px 32px -10px rgba(var(--drop),0.14); }
  .tile .label { font-size: 12px; color: var(--ink-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }
  .tile .value { font-size: 21px; font-weight: 700; margin-top: 6px; color: var(--ink); letter-spacing: -0.01em; }
  .card { border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 18px 20px; margin: 14px 0;
    background: linear-gradient(180deg, var(--raise-top), color-mix(in srgb, var(--raise-bottom) 45%, var(--raise-top)));
    box-shadow: inset 0 1px 0 var(--hi), inset 0 -1px 0 var(--lo),
      0 1px 1px rgba(var(--drop),0.08), 0 8px 18px rgba(var(--drop),0.09), 0 16px 30px -12px rgba(var(--drop),0.08); }
  /* A <details>-based card (currently just _line_chart_html's "no data
     yet" state) -- collapsed by default so a chart with nothing to show
     yet doesn't claim a full card's worth of space; clicking the
     summary line expands it to read the explanatory note underneath. */
  details.card { padding: 12px 20px; }
  details.card[open] { padding: 18px 20px; }
  details.card > summary { cursor: pointer; list-style: none; }
  details.card > summary::-webkit-details-marker { display: none; }
  details.card > summary::before { content: "\\25b8  "; color: var(--ink-muted); font-size: 11px; }
  details.card[open] > summary::before { content: "\\25be  "; }
  details.card > summary + p { margin-top: 8px; }
  form.inline { display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-end; margin-top: 10px; }
  form.inline label { display: flex; flex-direction: column; font-size: 12px; color: var(--ink-muted); gap: 3px; font-weight: 500; }
  form.inline input, form.inline select { font: inherit; font-size: 13px; padding: 6px 8px; border: 1px solid var(--border);
    border-radius: 8px; background: var(--surface); color: var(--ink); }
  /* Pill-shaped buttons (border-radius: 980px is Apple's own CSS trick
     for apple.com's buttons -- round enough that any single-line
     button, however tall its padding makes it, ends up a true pill
     rather than just rounded corners). A light, tactile press (scale
     down very slightly on :active) stands in for the native control
     "squish" Apple's own buttons have. */
  button { font: inherit; font-size: 13px; padding: 7px 16px; border: 1px solid var(--border); border-radius: 980px;
    background: var(--surface); cursor: pointer; font-weight: 500; color: var(--ink-soft);
    transition: background 0.15s var(--ease), border-color 0.15s var(--ease), transform 0.1s var(--ease); }
  button.primary { background: var(--brand); border-color: var(--brand); color: #fff; font-weight: 600; }
  button.primary:hover { background: var(--brand-dark); border-color: var(--brand-dark); }
  button.danger { background: var(--surface); border-color: var(--danger); color: var(--danger); padding: 3px 10px; font-size: 12px; }
  .rule-actions { display: inline-flex; flex-wrap: wrap; gap: 4px; align-items: center; }
  .rule-actions button { padding: 4px 9px; font-size: 11px; white-space: nowrap; }
  button:hover { filter: brightness(0.98); }
  button:active { transform: scale(0.96); }
  button:disabled { opacity: 0.45; cursor: default; transform: none; }
  button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible {
    outline: none; box-shadow: 0 0 0 4px var(--brand-soft); border-radius: 6px; }
  .status-line { margin: 6px 0; font-size: 13px; }
  .status-ok { color: var(--success); }
  .status-warn { color: var(--warn); }
  .status-err { color: var(--danger); }
  .group-section { display: flex; gap: 32px; align-items: flex-start; flex-wrap: wrap; }
  .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; }
  .link-col { min-width: 130px; white-space: normal; word-break: normal; }
  .link-col select { width: 100%; white-space: normal; }
  /* Net worth explorer (charts._net_worth_explorer_html): asset toggle
     chips + a $/% segmented switch above the chart. */
  /* Summary detail layer (summary_blocks.fold_html): a one-line bar that opens the card underneath. */
  .fold { margin: 10px 0; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
  .fold > summary { list-style: none; cursor: pointer; display: flex; align-items: baseline; gap: 10px; padding: 12px 16px;
    font-weight: 600; color: var(--ink); border-radius: var(--radius); }
  .fold > summary::-webkit-details-marker { display: none; }
  .fold > summary::before { content: "\\25B8"; color: var(--brand); font-size: 12px; transition: transform .15s var(--ease); }
  .fold[open] > summary::before { transform: rotate(90deg); }
  .fold-hint { font-weight: 400; font-size: 12px; color: var(--ink-muted); }
  .fold[open] > summary { border-bottom: 1px solid var(--border); border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
  .fold > .card, .fold > div { margin: 0 !important; border: 0 !important; box-shadow: none !important; }
  .nw-controls { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 8px 0 4px; }
  .nw-chip { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; padding: 3px 10px; border-radius: 980px;
    border: 1px solid var(--border); background: var(--surface); color: var(--ink-muted); cursor: pointer; font-weight: 500; }
  .nw-chip[aria-pressed="true"] { color: var(--ink); border-color: var(--ink-muted); background: var(--surface-alt); font-weight: 600; }
  .nw-chip[aria-pressed="false"] .nw-swatch { opacity: 0.35; }
  .nw-swatch { display: inline-block; width: 9px; height: 9px; border-radius: 2px; }
  .nw-chart { position: relative; }
  .nw-tip { position: absolute; z-index: 5; pointer-events: none; min-width: 190px; max-width: 340px; padding: 8px 10px;
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow-md);
    font-size: 11px; color: var(--ink); }
  .nw-tip[hidden] { display: none; }
  .nw-tip-fixed { position: fixed; min-width: 0; max-width: 300px; white-space: nowrap; }
  .bar-track[data-ctip], .pie-seg[data-ctip] { cursor: pointer; }
  .nw-tip-date { font-weight: 600; margin-bottom: 4px; color: var(--ink-muted); }
  .nw-tip-row { display: flex; align-items: center; gap: 6px; padding: 1px 0; }
  .nw-tip-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .nw-tip-val { font-weight: 600; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .nw-tip-pct { font-weight: 500; color: var(--ink-muted); }
  .nw-tools { display: inline-flex; gap: 2px; margin-left: 4px; }
  .nw-link { background: none; border: none; padding: 2px 6px; font-size: 11px; color: var(--brand); cursor: pointer; border-radius: 6px; }
  .nw-seg { display: inline-flex; margin-left: auto; border: 1px solid var(--border); border-radius: 980px; overflow: hidden; }
  .nw-mode { border: none; border-radius: 0; padding: 3px 12px; font-size: 11px; background: var(--surface); color: var(--ink-muted); }
  .nw-mode[aria-pressed="true"] { background: var(--brand); color: #fff; font-weight: 600; }
  th.sortable-col { cursor: pointer; user-select: none; }
  th.sortable-col:hover { background: var(--border); }
  th.sort-asc::after { content: " \\25B2"; font-size: 10px; }
  th.sort-desc::after { content: " \\25BC"; font-size: 10px; }
  td input[type=text], td input[type=number] { border: 1px solid transparent; background: transparent; border-radius: 6px;
    color: var(--ink); }
  td input[type=text]:hover, td input[type=number]:hover { border-color: var(--border); }
  td input[type=text]:focus, td input[type=number]:focus { border-color: var(--brand); background: var(--surface); outline: none; }
  .check-col { width: 28px; }
  /* Deliberately NOT position:sticky (unlike before this file's own
     Apple-style pass) -- nav itself is sticky now (see above), and a
     second sticky element stacked under it at a guessed pixel offset
     would either overlap nav or leave an ugly gap depending on how many
     of nav's own tab labels happen to wrap to a second line at a given
     viewport width, which varies and can't be predicted from CSS alone.
     Sitting in normal flow right after nav avoids that risk entirely --
     it still appears the moment a row is checked, right where a person
     is already looking. */
  .bulk-bar { display: none; align-items: center; gap: 10px; background: color-mix(in srgb, var(--warn) 12%, var(--surface));
    border: 1px solid color-mix(in srgb, var(--warn) 45%, var(--border)); border-radius: var(--radius); padding: 8px 12px;
    margin: 0 0 16px 0; box-shadow: var(--shadow-sm); }
  .bulk-bar .bulk-count { font-weight: 600; color: var(--warn); font-size: 13px; }
  /* Always in view: floats at the bottom of the window instead of sitting up by the tabs. */
  .bulk-bar { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); z-index: 60; margin: 0;
    box-shadow: var(--shadow-md); background: var(--surface); }
  /* Income & Expenses put the Delete button in each table's own header instead. */
  body:has(.li-card) .bulk-bar { display: none !important; }
  .li-del { display: none; }
  .li-del.on { display: inline-flex; }
  .pie-seg { cursor: pointer; }
  .pie-seg:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
  circle.pie-seg.seg-selected { stroke-width: 30; filter: drop-shadow(0 1px 2px rgba(0,0,0,0.35)); }
  circle.pie-seg.seg-dimmed { opacity: 0.35; }
  .legend-row.seg-selected { background: var(--brand-soft); }
  .legend-row.seg-selected .legend-label { font-weight: 600; }
  .legend-row.seg-dimmed { opacity: 0.55; }
  .legend-row:hover:not(.seg-selected) { background: var(--surface-alt); }
  .filter-bar { display: none; align-items: center; gap: 8px; flex-wrap: wrap; background: var(--brand-soft);
    border: 1px solid color-mix(in srgb, var(--brand) 35%, var(--border)); border-radius: var(--radius); padding: 6px 10px;
    margin: 10px 0; font-size: 12px; }
  .filter-chip { background: var(--brand); color: #fff; border-radius: 999px; padding: 2px 6px 2px 10px;
    display: inline-flex; align-items: center; gap: 4px; }
  .filter-chip button { background: transparent; border: none; color: #fff; padding: 0 4px; font-size: 12px;
    cursor: pointer; line-height: 1.4; }
  .filter-bar > button { background: transparent; border: none; color: var(--brand-dark); text-decoration: underline;
    padding: 0; font-size: 12px; cursor: pointer; }
  /* Actual Spending's "Show: All / Income only / Expense only" quick
     filter -- a plain toggle-button row (not chart-driven, so it isn't
     a .filter-chip), the active one filled in brand color same as a
     selected chart segment reads. */
  .kind-filter-btn { font-size: 12px; padding: 3px 12px; border: 1px solid var(--border); border-radius: 999px;
    background: var(--surface); color: var(--ink-soft); cursor: pointer; }
  .kind-filter-btn.active { background: var(--brand); border-color: var(--brand); color: #fff; font-weight: 600; }
  /* Every bar chart scrolls inside its card past ~10 rows (the partly
     visible 11th row is the cue that there's more); the track is kept
     visible by the scrollbar gutter, and _bar_chart_html adds a "scroll
     for more" caption with the real count. */
  .bar-chart { display: flex; flex-direction: column; gap: 2px; max-height: 272px; overflow-y: auto; scrollbar-gutter: stable;
    overscroll-behavior: contain; }
  .bar-chart-hint { margin: 6px 0 0; font-size: 11px; }
  details.how-it-works { margin: 4px 0 12px; }
  /* "Show more" toggles: one look everywhere -- a little chevron badge, a slightly larger bold label. */
  details.how-it-works > summary, details.ns-more > summary, details:not([class]) > summary {
    cursor: pointer; list-style: none; display: inline-flex; align-items: center; gap: 8px; padding: 4px 6px 4px 0;
    color: var(--brand) !important; font-size: 14px !important; font-weight: 600 !important;
  }
  details.how-it-works > summary::-webkit-details-marker, details.ns-more > summary::-webkit-details-marker,
  details:not([class]) > summary::-webkit-details-marker { display: none; }
  details.how-it-works > summary::before, details.ns-more > summary::before, details:not([class]) > summary::before {
    content: "\\203A"; flex: none; display: inline-flex; align-items: center; justify-content: center;
    width: 20px; height: 20px; border-radius: 6px; background: rgba(0,113,227,.12); color: var(--brand);
    font-size: 17px; font-weight: 700; line-height: 1; padding-bottom: 2px; transition: transform .15s var(--ease, ease), background .15s;
  }
  details.how-it-works > summary:hover::before, details.ns-more > summary:hover::before, details:not([class]) > summary:hover::before { background: rgba(0,113,227,.22); }
  details.how-it-works[open] > summary::before, details.ns-more[open] > summary::before, details:not([class])[open] > summary::before { transform: rotate(90deg); }
  details.how-it-works[open] > summary, details.ns-more[open] > summary, details:not([class])[open] > summary { margin-bottom: 4px; }
  details.how-it-works > summary:focus-visible, details.ns-more > summary:focus-visible, details:not([class]) > summary:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; border-radius: 6px; }
  .bar-row { display: flex; align-items: center; gap: 8px; padding: 3px 4px; border-radius: 8px; }
  .bar-row .bar-label { flex: 0 0 150px; max-width: 150px; font-size: 12px; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; }
  .bar-row .bar-track { flex: 1; background: var(--surface-alt); border-radius: 4px; height: 14px; overflow: hidden; }
  .bar-row .bar-fill { display: block; height: 100%; border-radius: 4px; min-width: 2px; }
  .bar-row .bar-value { flex: 0 0 110px; text-align: right; font-size: 12px; color: var(--ink-muted); }
  .bar-row:hover:not(.seg-selected) { background: var(--surface-alt); }
  .bar-row.seg-selected { background: var(--brand-soft); }
  .bar-row.seg-selected .bar-label { font-weight: 600; }
  .bar-row.seg-dimmed { opacity: 0.5; }
  .industry-bulk-bar { display: none; align-items: center; gap: 8px; flex-wrap: wrap;
    background: color-mix(in srgb, var(--success) 12%, var(--surface));
    border: 1px solid color-mix(in srgb, var(--success) 45%, var(--border)); border-radius: var(--radius);
    padding: 8px 12px; margin: 10px 0; font-size: 12px; }
  .industry-bulk-bar .bulk-count { font-weight: 600; color: var(--success); }
  .industry-bulk-bar input[type=text] { font: inherit; font-size: 13px; padding: 5px 7px; border: 1px solid var(--border);
    border-radius: 8px; background: var(--surface); color: var(--ink); width: 220px; }
  .add-shortcut-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
  .fab-add { position: fixed; right: 24px; bottom: 24px; z-index: 50; padding: 13px 22px; font-size: 14px;
    font-weight: 600; border-radius: 999px; background: var(--brand); border-color: var(--brand); color: #fff;
    box-shadow: var(--shadow-md); }
  .fab-add:hover { background: var(--brand-dark); }
  .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.4); align-items: center;
    justify-content: center; z-index: 100; padding: 20px; }
  @supports (backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)) {
    .modal-overlay { -webkit-backdrop-filter: blur(6px); backdrop-filter: blur(6px); }
  }
  .modal-overlay:not([hidden]) { display: flex; }
  .modal-card { background: var(--surface); border-radius: var(--radius-lg); padding: 22px 24px; width: 100%;
    max-width: 540px; max-height: 88vh; overflow-y: auto; box-shadow: var(--shadow-md); }
  .modal-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
  .modal-close { border: none; background: transparent; font-size: 22px; line-height: 1; padding: 2px 6px;
    cursor: pointer; color: var(--ink-muted); border-radius: 999px; }
  .modal-close:hover { color: var(--ink); }
  .add-kind-field { display: flex; flex-direction: column; font-size: 12px; color: var(--ink-muted); gap: 4px; font-weight: 600;
    margin-bottom: 16px; }
  .add-kind-field select { font-size: 14px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 10px;
    background: var(--surface); color: var(--ink); }
  .field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 14px; border: none; padding: 0; margin: 0; }
  .field-grid[hidden] { display: none; }
  .field-grid label { display: flex; flex-direction: column; font-size: 12px; color: var(--ink-muted); gap: 4px; font-weight: 500; }
  .field-grid input, .field-grid select { font: inherit; font-size: 13px; padding: 7px 9px; border: 1px solid var(--border);
    border-radius: 8px; background: var(--surface); color: var(--ink); }
  .modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
  .insight-row { display: flex; gap: 16px; flex-wrap: wrap; align-items: stretch; margin: 12px 0; }

  /* A thin, self-hiding scrollbar on any element that scrolls its own
     content (a horizontally-scrolled table on a phone, a tall
     .bar-chart list) -- the inset, barely-there scrollbar every native
     macOS app uses, instead of the chunky default one a plain web page
     gets. Webkit-only (Safari/Chrome, which covers this program's own
     target), and purely cosmetic -- scrolling itself needs nothing
     here, so a browser that ignores these rules just keeps its own
     default scrollbar with no loss of function. */
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: color-mix(in srgb, var(--ink-muted) 45%, transparent); border-radius: 999px;
    border: 2px solid transparent; background-clip: content-box; }
  ::-webkit-scrollbar-thumb:hover { background: color-mix(in srgb, var(--ink-muted) 65%, transparent); background-clip: content-box; }

  /* -------------------------------------------------------------
     Phone layout (iPhone-width viewports and similar). Desktop/
     tablet layout above is untouched -- everything here only takes
     effect under the breakpoint, as an addition on top of it, never
     a replacement. */
  @media (max-width: 640px) {
    body { padding: calc(16px + env(safe-area-inset-top)) 16px calc(96px + env(safe-area-inset-bottom)); }
    h1 { font-size: 19px; }
    /* A wrapped multi-row nav ate a lot of vertical space on a phone
       (every tab's own label, up to 3-4 rows deep) -- a single
       horizontally-scrollable row reads as familiar "tab bar" UI
       instead, and keeps the page's own content starting higher up. */
    nav { flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none;
      scroll-padding-inline: 14px; top: 0; }
    nav::-webkit-scrollbar { display: none; }
    /* flex: 0 0 auto (not 1 1 0, the desktop rule) -- each tab sizes to
       its own label instead of splitting the row evenly, since with 10
       tabs an even split would squeeze every label unreadably thin. The
       shared <script>'s DOMContentLoaded handler scrolls nav a.active
       into view on load (with scroll-padding-inline above giving it a
       little breathing room) -- otherwise whichever tab you're actually
       on can land flush against the edge, half cut off, which reads as
       broken rather than "swipe for more". */
    nav a { flex: 0 0 auto; min-width: 84px; }
    /* A table wider than the phone screen (Asset/Expense/Linked
       Positions all have several columns) scrolls horizontally
       within its own card instead of forcing the whole page to
       scroll sideways or squeezing every column unreadably thin. */
    .card { overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .tile { flex-basis: 45%; }
    .field-grid { grid-template-columns: 1fr; }
    form.inline { flex-direction: column; align-items: stretch; }
    form.inline label { width: 100%; }
    /* 16px, not the desktop 13px -- an input under 16px makes Safari
       on iOS zoom the whole page in on focus, which then has to be
       manually zoomed back out; these are the form fields someone
       would actually tap into on a phone (not the narrow per-cell
       table inputs below, which stay their existing compact size so
       a data table doesn't blow out sideways). */
    form.inline input, form.inline select,
    .add-kind-field select, .field-grid input, .field-grid select { font-size: 16px; }
    .modal-card { padding: 18px 16px; max-height: 82vh; }
    .bar-row .bar-label { flex-basis: 90px; max-width: 90px; }
    /* Lifted clear of the iPhone's home-indicator gesture bar. */
    .fab-add { right: 16px; bottom: calc(16px + env(safe-area-inset-bottom)); padding: 14px 20px; }
    table { font-size: 12px; }
    th, td { padding: 8px 6px; }
  }
"""
