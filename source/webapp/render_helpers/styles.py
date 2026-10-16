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

THEME_TOGGLE_HTML = (
    '<button type="button" id="theme-toggle" onclick="rpCycleTheme()" '
    'title="Switch between Auto (follow your Mac), Light and Dark">Theme: Auto</button>'
    "<script>rpThemeSync();</script>"
)


PAGE_CSS = """
  :root {
    --brand: #0071e3; --brand-dark: #0059b2; --brand-soft: #e8f1fc;
    --ink: #1d1d1f; --ink-muted: #6e6e73; --ink-soft: #424245;
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
      --ink: #f5f5f7; --ink-muted: #98989d; --ink-soft: #c7c7cc;
      --surface: #2c2c2e; --surface-alt: #1c1c1e; --border: #38383a;
      --success: #32d74b; --warn: #ff9f0a; --danger: #ff453a;
      --shadow-sm: 0 1px 2px rgba(0,0,0,0.3);
      --shadow-md: 0 16px 32px rgba(0,0,0,0.45), 0 2px 8px rgba(0,0,0,0.3);
    }
  }
  :root[data-theme="dark"] {
    --brand: #0a84ff; --brand-dark: #409cff; --brand-soft: rgba(10,132,255,0.18);
    --ink: #f5f5f7; --ink-muted: #98989d; --ink-soft: #c7c7cc;
    --surface: #2c2c2e; --surface-alt: #1c1c1e; --border: #38383a;
    --success: #32d74b; --warn: #ff9f0a; --danger: #ff453a;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.3);
    --shadow-md: 0 16px 32px rgba(0,0,0,0.45), 0 2px 8px rgba(0,0,0,0.3);
  }
  #theme-toggle { align-self: flex-start; font-size: 12px; padding: 6px 12px; white-space: nowrap; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Helvetica, Arial, sans-serif;
    max-width: 1080px; margin: 0 auto; padding: 28px 20px 96px; color: var(--ink); background: var(--surface-alt);
    -webkit-font-smoothing: antialiased; }
  h1 { font-size: 22px; margin: 0 0 4px 0; font-weight: 700; letter-spacing: -0.015em; }
  h2 { font-size: 15px; margin: 28px 0 10px 0; font-weight: 600; color: var(--ink); letter-spacing: -0.005em; }
  h3 { color: var(--ink); font-weight: 600; }
  .muted { color: var(--ink-muted); font-size: 12px; }
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
  nav a { padding: 7px 6px; border-radius: 8px; text-decoration: none; color: var(--ink-soft); font-size: 12px;
    font-weight: 500; transition: background 0.15s var(--ease), color 0.15s var(--ease); white-space: normal;
    flex: 1 1 0; text-align: center; }
  nav a.active { background: var(--brand); color: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.15); }
  nav a:not(.active):hover { background: var(--surface-alt); color: var(--ink); }
  .subnav { display: flex; gap: 6px; margin: -14px 0 18px 0; }
  .subnav a { padding: 5px 14px; border-radius: 999px; text-decoration: none; font-size: 12px; font-weight: 500;
    color: var(--ink-soft); border: 1px solid var(--border); background: var(--surface); }
  .subnav a.active { border-color: var(--brand); color: var(--brand); font-weight: 600; }
  .subnav a:not(.active):hover { background: var(--surface-alt); color: var(--ink); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; background: var(--surface); }
  th, td { text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--border); }
  th { background: var(--surface-alt); font-weight: 600; color: var(--ink-soft); font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.04em; }
  td.num, th.num { text-align: right; }
  tfoot td { font-weight: 600; border-top: 2px solid var(--border); background: var(--surface-alt); }
  .tiles { display: flex; gap: 14px; flex-wrap: wrap; margin: 14px 0 22px 0; }
  .tile { flex: 1 1 170px; border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px;
    background: var(--surface); box-shadow: var(--shadow-sm); }
  .tile .label { font-size: 11px; color: var(--ink-muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }
  .tile .value { font-size: 21px; font-weight: 700; margin-top: 6px; color: var(--ink); letter-spacing: -0.01em; }
  .card { border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 18px 20px; margin: 14px 0;
    background: var(--surface); box-shadow: var(--shadow-sm); }
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
  form.inline label { display: flex; flex-direction: column; font-size: 11px; color: var(--ink-muted); gap: 3px; font-weight: 500; }
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
  /* Real Expenditure's "Show: All / Income only / Expense only" quick
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
  details.how-it-works > summary { cursor: pointer; color: var(--brand); font-size: 12px; font-weight: 500; list-style: none; }
  details.how-it-works > summary::-webkit-details-marker { display: none; }
  details.how-it-works > summary::before { content: "\\25B8  "; }
  details.how-it-works[open] > summary::before { content: "\\25BE  "; }
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
  .field-grid label { display: flex; flex-direction: column; font-size: 11px; color: var(--ink-muted); gap: 4px; font-weight: 500; }
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
    nav a { flex: 0 0 auto; white-space: nowrap; }
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
