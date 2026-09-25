"""The one shared stylesheet every page's shell embeds (see shell.py's
PAGE_SHELL). Split out on its own purely because it's a long, purely
declarative CSS blob with nothing else in common with the Python helpers
around it -- nothing here depends on, or is depended on by, any other
render_helpers submodule.
"""

from __future__ import annotations


PAGE_CSS = """
  :root {
    --brand: #2563eb; --brand-dark: #1d4ed8; --brand-soft: #eef4ff;
    --ink: #0f172a; --ink-muted: #64748b; --ink-soft: #475569;
    --surface: #ffffff; --surface-alt: #f8fafc; --border: #e2e8f0;
    --success: #16a34a; --warn: #ca8a04; --danger: #dc2626;
    --radius: 10px; --radius-lg: 14px;
    --shadow-sm: 0 1px 2px rgba(15,23,42,0.06), 0 1px 1px rgba(15,23,42,0.04);
    --shadow-md: 0 8px 24px rgba(15,23,42,0.12);
  }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 1080px; margin: 0 auto;
    padding: 32px 20px 96px; color: var(--ink); background: var(--surface-alt); }
  h1 { font-size: 22px; margin: 0 0 4px 0; font-weight: 700; letter-spacing: -0.01em; }
  h2 { font-size: 15px; margin: 28px 0 10px 0; font-weight: 650; color: var(--ink); }
  h3 { color: var(--ink); }
  .muted { color: var(--ink-muted); font-size: 12px; }
  nav { display: flex; gap: 2px; flex-wrap: wrap; margin: 18px 0 28px 0; background: var(--surface);
    border: 1px solid var(--border); border-radius: 12px; padding: 6px; box-shadow: var(--shadow-sm); }
  nav a { padding: 8px 14px; border-radius: 8px; text-decoration: none; color: var(--ink-soft); font-size: 13px;
    font-weight: 500; transition: background 0.15s ease, color 0.15s ease; }
  nav a.active { background: var(--brand); color: #fff; }
  nav a:not(.active):hover { background: var(--surface-alt); color: var(--ink); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; background: var(--surface); }
  th, td { text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--border); }
  th { background: var(--surface-alt); font-weight: 650; color: var(--ink-soft); font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.04em; }
  td.num, th.num { text-align: right; }
  tfoot td { font-weight: 650; border-top: 2px solid #cbd5e1; background: var(--surface-alt); }
  .tiles { display: flex; gap: 14px; flex-wrap: wrap; margin: 14px 0 22px 0; }
  .tile { flex: 1 1 170px; border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px;
    background: var(--surface); box-shadow: var(--shadow-sm); }
  .tile .label { font-size: 11px; color: var(--ink-muted); font-weight: 650; text-transform: uppercase; letter-spacing: 0.03em; }
  .tile .value { font-size: 21px; font-weight: 700; margin-top: 6px; color: var(--ink); }
  .card { border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 20px; margin: 14px 0;
    background: var(--surface); box-shadow: var(--shadow-sm); }
  form.inline { display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-end; margin-top: 10px; }
  form.inline label { display: flex; flex-direction: column; font-size: 11px; color: #555; gap: 3px; font-weight: 500; }
  form.inline input, form.inline select { font: inherit; font-size: 13px; padding: 6px 8px; border: 1px solid #cbd5e1; border-radius: 6px; }
  button { font: inherit; font-size: 13px; padding: 7px 13px; border: 1px solid #cbd5e1; border-radius: 8px;
    background: #fff; cursor: pointer; font-weight: 500; color: var(--ink-soft); transition: background 0.15s, border-color 0.15s; }
  button.primary { background: var(--brand); border-color: var(--brand); color: #fff; font-weight: 600; }
  button.primary:hover { background: var(--brand-dark); }
  button.danger { background: #fff; border-color: #dc2626; color: #dc2626; padding: 3px 8px; font-size: 12px; }
  button:hover { filter: brightness(0.97); }
  .status-line { margin: 6px 0; font-size: 13px; }
  .status-ok { color: var(--success); }
  .status-warn { color: var(--warn); }
  .status-err { color: var(--danger); }
  .group-section { display: flex; gap: 32px; align-items: flex-start; flex-wrap: wrap; }
  .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; }
  .link-col { width: 130px; max-width: 130px; white-space: normal; word-break: break-word; }
  .link-col select { width: 100%; white-space: normal; }
  th.sortable-col { cursor: pointer; user-select: none; }
  th.sortable-col:hover { background: #eef2f7; }
  th.sort-asc::after { content: " \\25B2"; font-size: 10px; }
  th.sort-desc::after { content: " \\25BC"; font-size: 10px; }
  td input[type=text], td input[type=number] { border: 1px solid transparent; background: transparent; border-radius: 4px; }
  td input[type=text]:hover, td input[type=number]:hover { border-color: #ccc; }
  td input[type=text]:focus, td input[type=number]:focus { border-color: var(--brand); background: #fff; outline: none; }
  .check-col { width: 28px; }
  .bulk-bar { display: none; align-items: center; gap: 10px; background: #fff7ed; border: 1px solid #fdba74;
    border-radius: 8px; padding: 8px 12px; margin: 0 0 16px 0; position: sticky; top: 8px; z-index: 5; }
  .bulk-bar .bulk-count { font-weight: 600; color: #9a3412; font-size: 13px; }
  .pie-seg { cursor: pointer; }
  .pie-seg:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
  circle.pie-seg.seg-selected { stroke-width: 30; filter: drop-shadow(0 1px 2px rgba(0,0,0,0.35)); }
  circle.pie-seg.seg-dimmed { opacity: 0.35; }
  .legend-row.seg-selected { background: var(--brand-soft); }
  .legend-row.seg-selected .legend-label { font-weight: 600; }
  .legend-row.seg-dimmed { opacity: 0.55; }
  .legend-row:hover:not(.seg-selected) { background: #f5f5f5; }
  .filter-bar { display: none; align-items: center; gap: 8px; flex-wrap: wrap; background: var(--brand-soft);
    border: 1px solid #bfdbfe; border-radius: 8px; padding: 6px 10px; margin: 10px 0; font-size: 12px; }
  .filter-chip { background: var(--brand); color: #fff; border-radius: 999px; padding: 2px 6px 2px 10px;
    display: inline-flex; align-items: center; gap: 4px; }
  .filter-chip button { background: transparent; border: none; color: #fff; padding: 0 4px; font-size: 12px;
    cursor: pointer; line-height: 1.4; }
  .filter-bar > button { background: transparent; border: none; color: var(--brand-dark); text-decoration: underline;
    padding: 0; font-size: 12px; cursor: pointer; }
  .bar-chart { display: flex; flex-direction: column; gap: 2px; max-height: 480px; overflow-y: auto; }
  .bar-row { display: flex; align-items: center; gap: 8px; padding: 3px 4px; border-radius: 6px; }
  .bar-row .bar-label { flex: 0 0 150px; max-width: 150px; font-size: 12px; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; }
  .bar-row .bar-track { flex: 1; background: #eef1f5; border-radius: 4px; height: 14px; overflow: hidden; }
  .bar-row .bar-fill { display: block; height: 100%; border-radius: 4px; min-width: 2px; }
  .bar-row .bar-value { flex: 0 0 110px; text-align: right; font-size: 12px; color: var(--ink-muted); }
  .bar-row:hover:not(.seg-selected) { background: #f5f5f5; }
  .bar-row.seg-selected { background: var(--brand-soft); }
  .bar-row.seg-selected .bar-label { font-weight: 600; }
  .bar-row.seg-dimmed { opacity: 0.5; }
  .industry-bulk-bar { display: none; align-items: center; gap: 8px; flex-wrap: wrap; background: #f0fdf4;
    border: 1px solid #86efac; border-radius: 8px; padding: 8px 12px; margin: 10px 0; font-size: 12px; }
  .industry-bulk-bar .bulk-count { font-weight: 600; color: #166534; }
  .industry-bulk-bar input[type=text] { font: inherit; font-size: 13px; padding: 5px 7px; border: 1px solid #ccc;
    border-radius: 5px; width: 220px; }
  .add-shortcut-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
  .fab-add { position: fixed; right: 24px; bottom: 24px; z-index: 50; padding: 13px 22px; font-size: 14px;
    font-weight: 650; border-radius: 999px; background: var(--brand); border-color: var(--brand); color: #fff;
    box-shadow: var(--shadow-md); }
  .fab-add:hover { background: var(--brand-dark); }
  .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(15,23,42,0.45); align-items: center;
    justify-content: center; z-index: 100; padding: 20px; }
  .modal-overlay:not([hidden]) { display: flex; }
  .modal-card { background: #fff; border-radius: var(--radius-lg); padding: 22px 24px; width: 100%; max-width: 540px;
    max-height: 88vh; overflow-y: auto; box-shadow: var(--shadow-md); }
  .modal-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
  .modal-close { border: none; background: transparent; font-size: 22px; line-height: 1; padding: 2px 6px;
    cursor: pointer; color: var(--ink-muted); }
  .modal-close:hover { color: var(--ink); }
  .add-kind-field { display: flex; flex-direction: column; font-size: 12px; color: #555; gap: 4px; font-weight: 600;
    margin-bottom: 16px; }
  .add-kind-field select { font-size: 14px; padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 8px; }
  .field-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 14px; border: none; padding: 0; margin: 0; }
  .field-grid[hidden] { display: none; }
  .field-grid label { display: flex; flex-direction: column; font-size: 11px; color: #555; gap: 4px; font-weight: 500; }
  .field-grid input, .field-grid select { font: inherit; font-size: 13px; padding: 7px 9px; border: 1px solid #cbd5e1;
    border-radius: 6px; }
  .modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
  .insight-row { display: flex; gap: 16px; flex-wrap: wrap; align-items: stretch; margin: 12px 0; }

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
    nav { flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; }
    nav::-webkit-scrollbar { display: none; }
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
