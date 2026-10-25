"""Donut and horizontal-bar chart renderers shared by every page that
breaks a total down by category (Summary, Asset, Expense/Income, Linked
Positions, Linked Accounts, Actual Spending) -- see the dataviz skill
for the chart-form and color-assignment rules these follow (fixed
categorical hue order, <=6 real slices + a folded "Other", click-to-
filter wired through the shared handlePieSegClick() JS in shell.py's
PAGE_SHELL). Every chart's segments carry the data-dim/data-slice-id/
data-values click-to-filter contract, but only Linked Positions
(applyPositionFilters), Actual Spending (applyExpenditureFilters), and
Linked Accounts (applyAccountsFilters) currently have a table wired up
to actually filter on click -- a click on Summary/Asset/Expense's own
charts still highlights the clicked segment but has no table below it
to filter.
"""

from __future__ import annotations

import html
import json
import math
from datetime import date, timedelta

from source.webapp.render_helpers.formatting import _money, _money_short


_DONUT_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300")


_DONUT_OTHER_COLOR = "#898781"  # muted ink -- deliberately outside the categorical sequence


def _grouped_slices(
    rows: list[dict], *, key: str, value_key: str, max_slices: int | None = 6
) -> list[tuple[str, float, list[str]]]:
    """Sums value_key per distinct key, largest first, folding anything
    past max_slices into one "Other" bucket -- a pie/donut stops being
    readable past ~6-7 wedges (dataviz skill: "more than ~7 color classes
    carrying meaning" is an anti-pattern), and this also caps the
    categorical palette at its validated 6-slot run. max_slices=None
    disables folding entirely and returns every distinct value as its
    own slice -- meant for a bar chart (each row is already directly
    labeled, so it stays legible past the donut's slice limit), not a
    donut, where an uncapped slice count would defeat the whole point of
    this function.

    Each returned tuple is (label, value, member_labels) -- member_labels
    is the list of raw row-level values folded into that slice (just
    [label] for a real slice, the whole folded tail for "Other") so a
    click on a slice can filter the underlying rows even when it's the
    "Other" bucket standing in for several distinct values."""
    totals: dict[str, float] = {}
    for row in rows:
        label = (row.get(key) or "").strip() or "Unknown"
        totals[label] = totals.get(label, 0.0) + (row.get(value_key) or 0.0)
    ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    if max_slices is None or len(ordered) <= max_slices:
        return [(label, value, [label]) for label, value in ordered]
    head, tail = ordered[:max_slices], ordered[max_slices:]
    result = [(label, value, [label]) for label, value in head]
    other_total = sum(v for _, v in tail)
    if other_total > 0:
        result.append(("Other", other_total, [label for label, _ in tail]))
    return result


_TIP_NOTE = "Click to filter the list below"


def _tip_attrs(label: str, value: str, color: str, note: str = _TIP_NOTE) -> str:
    """data-* attributes for the shared hover tooltip (the delegated
    handler in the page shell draws the same ".nw-tip" box the Net Worth
    chart uses) -- label line, value line with a color swatch, and an
    optional muted note."""
    return (
        f'data-ctip="{html.escape(label)}" data-ctip-val="{html.escape(value)}" '
        f'data-ctip-color="{html.escape(color)}" data-ctip-note="{html.escape(note)}"'
    )


def _donut_chart_html(title: str, slices: list[tuple[str, float, list[str]]], *, dim: str, size: int = 180) -> str:
    """Part-to-whole donut for <=6 real segments (+ a folded "Other") --
    categorical hues in fixed slot order, a legend with swatch + label +
    value + percent (identity is never color-alone), a small gap between
    wedges standing in for the mark spec's 2px surface gap (a dash gap
    rather than a border), and the shared styled hover tooltip (data-ctip,
    the same look as the Net Worth chart's) per wedge.

    Every slice (both the SVG wedge and its legend row) is also a
    clickable/keyboard-focusable ".pie-seg" carrying data-dim/data-slice-id/
    data-values -- the shared handlePieSegClick() JS (in PAGE_SHELL) uses
    those to filter the positions table below by the row(s) that make up
    the clicked slice. `dim` is the filter dimension this chart encodes
    ("type" or "institution") and must match the data-{dim} attribute the
    caller put on each filterable table row."""
    total = sum(v for _, v, _ in slices)
    if total <= 0:
        return (
            f'<div class="card" style="flex:1 1 320px;">'
            f'<h3 style="margin-top:0; font-size:13px;">{html.escape(title)}</h3>'
            '<p class="muted">No data yet.</p></div>'
        )
    r = 62
    stroke = 26
    cx = cy = size / 2
    circumference = 2 * math.pi * r
    gap = 2.5  # px of arc left as a surface-color gap between wedges

    segments = []
    legend_rows = []
    offset = 0.0
    for i, (label, value, member_labels) in enumerate(slices):
        color = _DONUT_OTHER_COLOR if label == "Other" else _DONUT_COLORS[i % len(_DONUT_COLORS)]
        fraction = value / total
        dash = max(fraction * circumference - gap, 0.0)
        remainder = circumference - dash
        pct = fraction * 100
        slice_id = f"{dim}-{i}"
        values_attr = html.escape(json.dumps(member_labels))
        # Shared by both the SVG wedge and its legend row -- deliberately
        # excludes `class` since each element needs its own class list.
        click_attrs = (
            f'tabindex="0" role="button" aria-pressed="false" '
            f'data-dim="{html.escape(dim)}" data-slice-id="{html.escape(slice_id)}" data-values="{values_attr}" '
            f'onclick="handlePieSegClick(this)" onkeydown="handlePieSegKeydown(event, this)"'
        )
        segments.append(
            f'<circle class="pie-seg" {click_attrs} {_tip_attrs(label, f"{_money(value)} ({pct:.0f}%)", color)} '
            f'aria-label="{html.escape(label)}: {html.escape(_money(value))} ({pct:.0f}%)" '
            f'cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}" '
            f'stroke-dasharray="{dash:.2f} {remainder:.2f}" stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})">'
            '</circle>'
        )
        legend_rows.append(
            f'<div class="legend-row pie-seg" {click_attrs} '
            'style="display:flex; align-items:center; gap:6px; font-size:12px; margin:3px 0;">'
            f'<span class="swatch" style="background:{color};"></span>'
            f'<span class="legend-label" style="flex:1;">{html.escape(label)}</span>'
            f'<span class="muted">{html.escape(_money_short(value))} ({pct:.0f}%)</span></div>'
        )
        offset += dash + gap

    svg = (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" font-family="-apple-system, sans-serif">'
        + "".join(segments)
        + f'<text x="{cx}" y="{cy - 3}" text-anchor="middle" font-size="14" font-weight="600" style="fill:var(--ink,#0b0b0b);">'
        f'{html.escape(_money_short(total))}</text>'
        + f'<text x="{cx}" y="{cy + 12}" text-anchor="middle" font-size="10" style="fill:var(--ink-muted,#777);">Total</text>'
        + "</svg>"
    )
    return f"""
<div class="card" style="flex:1 1 320px;">
<h3 style="margin-top:0; font-size:13px;">{html.escape(title)}</h3>
<div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
<div>{svg}</div>
<div style="flex:1; min-width:150px;">{"".join(legend_rows)}</div>
</div>
</div>
"""


_LINE_CHART_COLOR = _DONUT_COLORS[0]


_DEFAULT_LINE_CHART_EMPTY_MESSAGE = (
    "Come back after this program has been opened (or synced) on a couple of different days "
    "to see a trend here -- one data point isn't a line yet."
)


def _parse_iso_date(label: str):
    """A "YYYY-MM-DD" label as a date, or None for anything else (e.g. a
    "YYYY-MM" month label) -- _line_chart_html uses this to decide between
    date-proportional x positions and plain even spacing."""
    try:
        return date.fromisoformat(label)
    except (TypeError, ValueError):
        return None


def _nice_axis_range(lo: float, hi: float) -> tuple[float, float]:
    """A y-axis range hugging the data (NOT forced down to zero) with a
    little headroom, so a net worth that moves a fraction of a percent
    still reads as a visible line instead of a flat one pinned to the top
    of a chart that starts at $0. A flat series gets a symmetric band
    around its value so it still draws mid-chart."""
    if hi - lo <= 1e-9:
        pad = max(abs(hi) * 0.01, 1.0)
        return lo - pad, hi + pad
    pad = (hi - lo) * 0.12
    return lo - pad, hi + pad


def _axis_money_label(value: float, step: float) -> str:
    """A y-axis tick label precise enough that neighboring ticks never
    read the same or out of step: _money_short's fixed one-decimal
    millions would label a $14.65M gridline "$14.7M" right next to a
    $14.7M one. Shows as many decimals as the tick spacing `step` needs
    (two for millions once ticks are closer than $0.5M, three under
    $50K..., whole thousands/dollars below a million)."""
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        decimals = 1 if step >= 500_000 else 2 if step >= 50_000 else 3
        return f"{sign}${magnitude / 1_000_000:.{decimals}f}M"
    if magnitude >= 1_000:
        decimals = 0 if step >= 500 else 1 if step >= 50 else 2
        return f"{sign}${magnitude / 1_000:.{decimals}f}K"
    return f"{sign}${magnitude:.0f}" if step >= 1 else f"{sign}${magnitude:.2f}"


def _line_chart_html(
    title: str, points: list[tuple[str, float]], *, note: str = "",
    empty_message: str = _DEFAULT_LINE_CHART_EMPTY_MESSAGE,
) -> str:
    """A single-series trend line -- change-over-time, unlike the part-
    to-whole donut/bar charts above (dataviz skill: a trend belongs on
    one axis, read left-to-right, not ranked by magnitude). Currently
    only the Assets tab's net-worth-over-time card uses this (source.
    common.db.net_worth_snapshots, one point per captured day -- see
    source.webapp.pages.asset._liquid_and_total_points).

    Adapts to whatever data it's given rather than assuming a fixed
    shape: the y-axis is fitted to the data's own range (with headroom)
    and labeled with gridlines, rather than always starting at $0 -- a
    plan worth millions that moved by tens of thousands would otherwise
    draw as an unreadably flat line; and when every label is a
    "YYYY-MM-DD" date the x positions are proportional to real elapsed
    time (a gap of a few days with the app closed shows as a gap, not as
    two adjacent points), with date ticks along the bottom. Any other
    label shape (e.g. "YYYY-MM") falls back to even spacing. Draws
    scale to the card's width (viewBox + width:100%) rather than a fixed
    pixel size, and with many points (daily data adds up) only the
    latest point is drawn as a visible dot -- the rest keep an invisible
    hover target, so every day still has its own tooltip without the
    line turning into a string of beads (dataviz skill: selective
    direct labels, never one on every mark)."""
    if len(points) < 2:
        # A <details> disclosure, not the plain always-open card the real
        # chart below renders as -- nothing to actually look at yet (just
        # the "come back later" note), so it starts collapsed and stays
        # out of the way rather than claiming a big empty-looking card's
        # worth of space at the top of the page. Once there's real data,
        # the branch below takes over and this collapsed state no longer
        # applies -- nothing to remember to "re-expand".
        return (
            f'<details class="card">'
            f'<summary style="font-size:13px; font-weight:650;">{html.escape(title)} <span class="muted" style="font-weight:500;">(no data yet)</span></summary>'
            f'<p class="muted" style="margin-bottom:0;">{html.escape(empty_message)}</p></details>'
        )
    width, height = 960, 270
    pad_left, pad_right, pad_top, pad_bottom = 84, 18, 14, 54
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    plot_bottom = pad_top + plot_h
    plot_right = width - pad_right

    values = [v for _, v in points]
    lo, hi = _nice_axis_range(min(values), max(values))

    dates = [_parse_iso_date(label) for label, _ in points]
    by_date = all(d is not None for d in dates) and dates[-1] > dates[0]
    span_days = (dates[-1] - dates[0]).days if by_date else 0

    def x_at(i: int) -> float:
        if by_date:
            return pad_left + ((dates[i] - dates[0]).days / span_days) * plot_w
        return pad_left + (i / (len(points) - 1)) * plot_w

    def y_at(v: float) -> float:
        return pad_top + (1 - (v - lo) / (hi - lo)) * plot_h

    coords = [(x_at(i), y_at(v)) for i, (_, v) in enumerate(points)]
    path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in coords)

    axis_style = 'style="stroke:var(--ink-muted);" stroke-width="1"'
    text_style = 'style="fill:var(--ink-muted);"'

    # Y axis: a real axis line with a tick mark, a faint gridline and a
    # value label at each of five evenly spaced levels across the fitted
    # range, plus a rotated axis title.
    grid = ""
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        v = lo + (hi - lo) * frac
        y = y_at(v)
        grid += (
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{plot_right}" y2="{y:.1f}" '
            f'style="stroke:var(--border);" stroke-width="1" stroke-dasharray="3 3"/>'
            f'<line x1="{pad_left - 5}" y1="{y:.1f}" x2="{pad_left}" y2="{y:.1f}" {axis_style}/>'
            f'<text x="{pad_left - 9}" y="{y + 3:.1f}" font-size="10" text-anchor="end" '
            f'{text_style}>{html.escape(_axis_money_label(v, (hi - lo) / 4))}</text>'
        )
    axes = (
        f'<line x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{plot_bottom}" {axis_style}/>'
        f'<line x1="{pad_left}" y1="{plot_bottom}" x2="{plot_right}" y2="{plot_bottom}" {axis_style}/>'
        f'<text transform="translate(14 {pad_top + plot_h / 2:.1f}) rotate(-90)" font-size="10" '
        f'text-anchor="middle" {text_style}>Net worth</text>'
        f'<text x="{pad_left + plot_w / 2:.1f}" y="{height - 6}" font-size="10" text-anchor="middle" '
        f'{text_style}>Date</text>'
    )
    zero_line = ""
    if lo < 0 < hi:
        zero_y = y_at(0.0)
        zero_line = (
            f'<line x1="{pad_left}" y1="{zero_y:.1f}" x2="{plot_right}" y2="{zero_y:.1f}" '
            f'style="stroke:var(--ink-muted);" stroke-width="1"/>'
        )

    show_all_dots = len(points) <= 45
    last_index = len(points) - 1
    dots = ""
    for i, ((label, value), (x, y)) in enumerate(zip(points, coords)):
        visible = show_all_dots or i == last_index
        dots += (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{3 if visible else 5}" '
            + (f'fill="{_LINE_CHART_COLOR}"' if visible else 'fill="transparent"')
            + f'><title>{html.escape(label)}: {html.escape(_money(value))}</title></circle>'
        )

    first_date, first_value = points[0]
    last_date, last_value = points[-1]
    # X axis: a tick mark and a date label at each tick. Date-proportional
    # charts get the full first/last ISO dates at the ends and up to five
    # evenly spaced short dates between (only when the span is long enough
    # for them not to collide); any other label shape just labels its
    # first and last point.
    x_ticks = [(pad_left, first_date, "start"), (plot_right, last_date, "end")]
    if by_date and span_days >= 8:
        for frac in (1 / 6, 2 / 6, 3 / 6, 4 / 6, 5 / 6):
            tick = dates[0] + timedelta(days=round(span_days * frac))
            tx = pad_left + ((tick - dates[0]).days / span_days) * plot_w
            x_ticks.append((tx, f"{tick.strftime('%b')} {tick.day}", "middle"))
    labels = "".join(
        f'<line x1="{tx:.1f}" y1="{plot_bottom}" x2="{tx:.1f}" y2="{plot_bottom + 5}" {axis_style}/>'
        f'<text x="{tx:.1f}" y="{plot_bottom + 18}" font-size="10" text-anchor="{anchor}" '
        f'{text_style}>{html.escape(text)}</text>'
        for tx, text, anchor in x_ticks
    )

    change = last_value - first_value
    change_pct = (change / abs(first_value) * 100) if first_value else None
    change_color = "#1baf7a" if change >= 0 else "#c94a4a"
    change_label = (
        f"{'+' if change >= 0 else ''}{_money(change)}"
        + (f" ({'+' if change_pct >= 0 else ''}{change_pct:.1f}%)" if change_pct is not None else "")
        + f" since {html.escape(first_date)}"
    )

    svg = (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}" '
        f'style="width:100%; height:auto; display:block;" font-family="-apple-system, sans-serif">'
        f'{grid}{zero_line}{axes}'
        f'<path d="{path}" fill="none" stroke="{_LINE_CHART_COLOR}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        f'{dots}{labels}'
        f'<line class="lc-cross" x1="0" y1="{pad_top}" x2="0" y2="{plot_bottom}" style="stroke:var(--ink-muted); display:none;" stroke-width="1" stroke-dasharray="4 3"/>'
        f'<ellipse class="lc-ring" rx="5" ry="5" cx="0" cy="0" fill="{_LINE_CHART_COLOR}" style="stroke:var(--surface); display:none;" stroke-width="2"/>'
        '</svg>'
    )
    note_html = f'<p class="muted" style="margin:4px 0 0;">{html.escape(note)}</p>' if note else ""
    hover_data = json.dumps([
        [round(x, 1), round(y, 1), label, _money(value),
         (_money(value - points[i - 1][1]) if i else "")]
        for i, ((label, value), (x, y)) in enumerate(zip(points, coords))
    ]).replace("</", "<\\/")
    return f"""
<div class="card" style="flex:2 1 480px;">
<h3 style="margin-top:0; font-size:13px;">{html.escape(title)} <span style="color:{change_color}; font-weight:600;">{html.escape(change_label)}</span></h3>
<div class="lc-wrap" style="position:relative;">
{svg}
<div class="lc-tip nw-tip" role="status" style="display:none; min-width:0; white-space:nowrap;"></div>
</div>
{note_html}
<script>
(function() {{
  var s = document.currentScript, wrap = s.parentNode.querySelector('.lc-wrap');
  if (!wrap) return;
  var svg = wrap.querySelector('svg'), tip = wrap.querySelector('.lc-tip');
  var cross = svg.querySelector('.lc-cross'), ring = svg.querySelector('.lc-ring');
  var pts = {hover_data}, vbw = {width};
  function hide() {{ tip.style.display = 'none'; cross.style.display = 'none'; ring.style.display = 'none'; }}
  function show(evt) {{
    var r = svg.getBoundingClientRect();
    var t = evt.touches && evt.touches[0] ? evt.touches[0] : evt;
    var vx = (t.clientX - r.left) / r.width * vbw, best = 0, bd = 1e9;
    for (var i = 0; i < pts.length; i++) {{ var d = Math.abs(pts[i][0] - vx); if (d < bd) {{ bd = d; best = i; }} }}
    var p = pts[best], k = r.width / vbw;
    cross.setAttribute('x1', p[0]); cross.setAttribute('x2', p[0]); cross.style.display = '';
    ring.setAttribute('cx', p[0]); ring.setAttribute('cy', p[1]); ring.style.display = '';
    var delta = p[4] ? '<div class="nw-tip-pct">' + (p[4].charAt(0) === '-' ? '' : '+') + p[4] + ' vs. previous day</div>' : '';
    tip.innerHTML = '<div class="nw-tip-date">' + p[2] + '</div><div class="nw-tip-row"><span class="nw-swatch" style="background:{_LINE_CHART_COLOR};"></span><span class="nw-tip-val">' + p[3] + '</span></div>' + delta;
    tip.style.display = 'block';
    var w = tip.offsetWidth, x = p[0] * k + 12;
    if (x + w > r.width) x = p[0] * k - w - 12;
    tip.style.left = Math.max(0, x) + 'px';
    tip.style.top = Math.max(0, p[1] * k - tip.offsetHeight - 10) + 'px';
  }}
  svg.addEventListener('mousemove', show); svg.addEventListener('mouseleave', hide);
  svg.addEventListener('touchstart', show, {{passive: true}}); svg.addEventListener('touchmove', show, {{passive: true}});
  svg.addEventListener('touchend', hide);
}})();
</script>
</div>
"""


# Deliberately outside the _DONUT_COLORS categorical rotation (same
# reasoning as _DONUT_OTHER_COLOR above) -- an "emphasize"d series in
# _multi_line_chart_html (the combined Total line, normally) always gets
# this dark, un-rotated ink color instead of a rotation slot, so it
# reads as "the headline total," never "series #5."
_MULTI_LINE_EMPHASIS_COLOR = "var(--ink, #3a3833)"


def _log_ticks(lo: float, hi: float, *, max_ticks: int = 6) -> list[float]:
    """Nice round gridline values (the standard 1/2/5 x 10^n pattern) for
    a logarithmic axis spanning [lo, hi] -- e.g. 1, 2, 5, 10, 20, 50,
    100, ... Tries the full 1-2-5 pattern first and falls back to
    coarser patterns (1-5, then decades only) if that would put more
    than max_ticks gridlines on a wide-range chart, so a balance history
    spanning several decades of magnitude doesn't end up with a dozen
    cluttered gridlines. Returns [] for a non-positive or empty range
    (log is undefined there -- the caller just skips gridlines)."""
    if lo <= 0 or hi <= lo:
        return []
    decades = range(math.floor(math.log10(lo)), math.ceil(math.log10(hi)) + 1)
    ticks: list[float] = []
    for pattern in ((1, 2, 5), (1, 5), (1,)):
        ticks = sorted({
            mult * (10 ** decade)
            for decade in decades
            for mult in pattern
            if lo * 0.999 <= mult * (10 ** decade) <= hi * 1.001
        })
        if len(ticks) <= max_ticks:
            break
    return ticks


def _multi_line_chart_html(
    title: str, series: list[dict], *, note: str = "", log_scale: bool = False,
    empty_message: str = _DEFAULT_LINE_CHART_EMPTY_MESSAGE,
) -> str:
    """Several trend lines sharing ONE y-axis -- e.g. the Linked Accounts
    tab's "Investment balance over time" chart (source.webapp.pages.
    linked_accounts._investment_balance_history_series): one line per
    linked investment account, plus an emphasized combined Total.
    Multiple series of the same unit/scale sharing a single axis is NOT
    the dual-axis anti-pattern the dataviz skill warns against (that's
    two DIFFERENT scales on one chart); this is one scale, several
    entities on it, same as _line_chart_html above just with more than
    one line.

    Each `series` entry is {"name": str, "points": [(date, value), ...],
    "emphasize": bool}. Series don't have to share the same set of dates
    (an account linked partway through this history simply starts
    later) -- the x-axis is the sorted union of every date across every
    series, and a series' own line breaks into a separate subpath
    wherever IT skips one or more shared x-positions, rather than
    drawing a straight (and misleading) interpolation across a real data
    gap.

    A non-emphasized series is colored from _DONUT_COLORS in the order
    given -- fixed categorical order, never re-cycled (dataviz skill:
    color follows the entity, not rank), so re-sorting/filtering the
    account list upstream would need its own stable sort to keep colors
    stable across a page reload (source.webapp.pages.linked_accounts
    sorts by name for exactly this reason). An emphasized series (there
    should be at most one in practice) gets _MULTI_LINE_EMPHASIS_COLOR
    and a thicker stroke instead of a rotation slot. A legend is always
    shown for >=2 series (dataviz skill: identity is never color-alone
    at 2+ series); an end-of-line direct label is added too when there
    are <=4 series total, since beyond that the line ends get crowded
    and the legend below already carries identity on its own.

    log_scale=True plots the y-axis logarithmically instead of linearly
    (e.g. the investment-balance chart, where a small account and a much
    larger one otherwise squash the small one's own month-to-month
    movement flat near the bottom) -- gridlines + $ labels are added in
    this mode specifically so the axis change is visible rather than a
    silently reshaped line (dataviz skill: an axis that changes what
    visual distance means has to be disclosed, not left implicit), and a
    short note is appended explaining what equal vertical spacing means
    now. A log axis is mathematically undefined at/below zero, so a
    non-positive point is clamped to the lowest positive value on the
    chart for PLOTTING purposes only -- its dot still sits at the
    correct real value in its tooltip/label, it just can't be placed at
    its true (unplottable) height."""
    non_empty = [s for s in series if s.get("points")]
    all_dates = sorted({d for s in non_empty for d, _ in s["points"]})
    if len(all_dates) < 2:
        return (
            f'<details class="card">'
            f'<summary style="font-size:13px; font-weight:650;">{html.escape(title)} <span class="muted" style="font-weight:500;">(no data yet)</span></summary>'
            f'<p class="muted" style="margin-bottom:0;">{html.escape(empty_message)}</p></details>'
        )
    width, height = 640, 200
    pad_left, pad_right, pad_top, pad_bottom = 8, 8, 12, 22
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    index_of = {d: i for i, d in enumerate(all_dates)}
    all_values = [v for s in non_empty for _, v in s["points"]]

    def x_at(i: int) -> float:
        return pad_left + (i / (len(all_dates) - 1)) * plot_w

    grid_svg = ""
    zero_line = ""
    if log_scale:
        positive_values = [v for v in all_values if v > 0]
        lo = min(positive_values) if positive_values else 1.0
        hi = max(all_values) if all_values else lo
        if hi <= lo:
            hi = lo * 10  # a flat/all-equal series still gets a visible range
        log_lo, log_hi = math.log10(lo), math.log10(hi)

        def y_at(v: float) -> float:
            vv = v if v > 0 else lo  # clamp: a non-positive point still plots, at the chart's floor
            return pad_top + (1 - (math.log10(vv) - log_lo) / (log_hi - log_lo)) * plot_h

        grid_lines = []
        for tick in _log_ticks(lo, hi):
            ty = y_at(tick)
            grid_lines.append(
                f'<line x1="{pad_left}" y1="{ty:.1f}" x2="{width - pad_right}" y2="{ty:.1f}" '
                f'style="stroke:var(--border,#e5e2db);" stroke-width="1"/>'
                f'<text x="{pad_left + 2}" y="{ty - 2:.1f}" font-size="9" style="fill:var(--ink-muted,#777);">{html.escape(_money_short(tick))}</text>'
            )
        grid_svg = "".join(grid_lines)
    else:
        lo, hi = min(0.0, min(all_values)), max(all_values)
        if hi - lo <= 0:
            hi = lo + max(abs(lo) * 0.1, 1.0)  # a flat/all-zero series still gets a visible range

        def y_at(v: float) -> float:
            return pad_top + (1 - (v - lo) / (hi - lo)) * plot_h

        if lo < 0 < hi:
            zero_y = y_at(0.0)
            zero_line = (
                f'<line x1="{pad_left}" y1="{zero_y:.1f}" x2="{width - pad_right}" y2="{zero_y:.1f}" '
                f'style="stroke:var(--border,#e5e2db);" stroke-width="1" stroke-dasharray="3 3"/>'
            )

    direct_label_ok = len(non_empty) <= 4
    color_i = 0
    lines_svg, dots_svg, end_labels_svg, legend_items = [], [], [], []
    chart_series = []   # the same lines as data, so the page can redraw them for whichever are selected
    for s in non_empty:
        emphasize = bool(s.get("emphasize"))
        if emphasize:
            color, stroke_width, dot_r = _MULTI_LINE_EMPHASIS_COLOR, 3, 3.5
        else:
            color, stroke_width, dot_r = _DONUT_COLORS[color_i % len(_DONUT_COLORS)], 2, 3
            color_i += 1
        pts = sorted(s["points"])
        indices = [index_of[d] for d, _ in pts]
        coords = [(x_at(i), y_at(v)) for i, (_, v) in zip(indices, pts)]
        # One subpath per contiguous run of shared x-positions -- a new
        # "M" starts whenever this series' own next point isn't at the
        # very next shared index (i.e. it has no data for one or more
        # dates in between), instead of one continuous path that would
        # draw a straight line across that gap.
        path_parts: list[str] = []
        current = ""
        prev_i = None
        for (x, y), i in zip(coords, indices):
            if prev_i is None or i != prev_i + 1:
                if current:
                    path_parts.append(current)
                current = f"M {x:.1f} {y:.1f}"
            else:
                current += f" L {x:.1f} {y:.1f}"
            prev_i = i
        if current:
            path_parts.append(current)
        lines_svg.append(
            f'<path d="{" ".join(path_parts)}" fill="none" style="stroke:{color};" stroke-width="{stroke_width}" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        dots_svg.append("".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{dot_r}" style="fill:{color};">'
            f'<title>{html.escape(s["name"])} -- {html.escape(d)}: {html.escape(_money(v))}</title></circle>'
            for (x, y), (d, v) in zip(coords, pts)
        ))
        if direct_label_ok and coords:
            lx, ly = coords[-1]
            end_labels_svg.append(
                f'<text x="{lx + 4:.1f}" y="{ly + 3:.1f}" font-size="9" style="fill:{color};">{html.escape(s["name"])}</text>'
            )
        chart_series.append({
            "name": s["name"], "color": color, "emph": emphasize, "sw": stroke_width, "r": dot_r,
            "pts": [[index_of[d], v, d] for d, v in pts],
        })
        legend_items.append(
            f'<button type="button" class="nw-chip mlc-chip" aria-pressed="true" data-i="{len(chart_series) - 1}" '
            f'title="Click to show or hide this line">'
            f'<span class="nw-swatch" style="background:{color};"></span>{html.escape(s["name"])}</button>'
        )

    first_date, last_date = all_dates[0], all_dates[-1]
    x_labels = (
        f'<text x="{pad_left}" y="{height - 6}" font-size="10" style="fill:var(--ink-muted,#777);">{html.escape(first_date)}</text>'
        f'<text x="{width - pad_right}" y="{height - 6}" font-size="10" style="fill:var(--ink-muted,#777);" text-anchor="end">'
        f'{html.escape(last_date)}</text>'
    )

    # The headline change figure (top-right of the title) reads off the
    # emphasized series when there is one (the combined Total, normally
    # -- the one number worth calling out at a glance) or the single
    # series itself when there's only one line at all.
    headline = next((s for s in non_empty if s.get("emphasize")), non_empty[0])
    headline_points = sorted(headline["points"])
    first_value, last_value = headline_points[0][1], headline_points[-1][1]
    change = last_value - first_value
    change_pct = (change / abs(first_value) * 100) if first_value else None
    change_color = "#1baf7a" if change >= 0 else "#c94a4a"
    change_label = (
        f"{'+' if change >= 0 else ''}{_money(change)}"
        + (f" ({'+' if change_pct >= 0 else ''}{change_pct:.1f}%)" if change_pct is not None else "")
        + f" since {html.escape(headline_points[0][0])}"
    )

    svg = (
        f'<svg class="mlc-svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="-apple-system, sans-serif">'
        f'{grid_svg}{zero_line}{"".join(lines_svg)}{"".join(dots_svg)}{"".join(end_labels_svg)}{x_labels}'
        '</svg>'
    )
    interactive = len(non_empty) >= 2
    has_total = any(c["emph"] for c in chart_series)
    legend_html = (
        '<div class="nw-controls mlc-controls">'
        '<button type="button" class="nw-chip" data-mlc="all">All</button>'
        '<button type="button" class="nw-chip" data-mlc="none">None</button>'
        + ('<button type="button" class="nw-chip" data-mlc="total">Total only</button>' if has_total else "")
        + "".join(legend_items) + "</div>"
        '<p class="muted small" style="margin:2px 0 0;">Click a name to show or hide that line; the scale re-fits to the lines showing.</p>'
        if interactive else ""
    )
    full_note = note
    if log_scale:
        log_note = "Logarithmic scale -- equal vertical spacing represents equal percentage change, not equal dollar change."
        full_note = f"{log_note} {note}" if note else log_note
    note_html = f'<p class="muted" style="margin:4px 0 0;">{html.escape(full_note)}</p>' if full_note else ""
    spec = html.escape(json.dumps({
        "w": width, "h": height, "pl": pad_left, "pr": pad_right, "pt": pad_top, "pb": pad_bottom,
        "log": log_scale, "dates": all_dates, "series": chart_series,
    }, separators=(",", ":")), quote=True)
    script = _MULTI_LINE_JS if interactive else ""
    return f"""
<div class="card mlc" style="flex:2 1 480px;" data-mlc-spec="{spec}">
<h3 style="margin-top:0; font-size:13px;">{html.escape(title)} <span class="mlc-change" style="color:{change_color}; font-weight:600;">{html.escape(change_label)}</span></h3>
<div class="mlc-plot">{svg}</div>
{legend_html}
{note_html}
</div>
{script}
"""


# Lets a multi-line chart's reader pick which lines to show (the All / None / Total only buttons and a click on
# any name): the chart is redrawn from the data in its data-mlc-spec for the lines showing, with the y-axis
# re-fitted to them, so one small account can be looked at on its own. One copy of this runs per page.
_MULTI_LINE_JS = """<script>
(function () {
  if (window.__mlcReady) { return; } window.__mlcReady = true;
  var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var W = 960, H = 300, PL = 76, PR = 16, PT = 12, PB = 44, PW = W - PL - PR, PH = H - PT - PB, PBOT = PT + PH;
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function day(iso) { var p = iso.split('-'); return Date.UTC(+p[0], +p[1] - 1, +p[2]) / 86400000; }
  function money(v) { var r = Math.round(v), t = Math.abs(r).toLocaleString('en-US'); return (r < 0 ? '-' : '') + '$' + t; }
  function axisMoney(v, step) {
    var s = v < 0 ? '-' : '', m = Math.abs(v);
    if (m >= 1e6) { return s + '$' + (m / 1e6).toFixed(step >= 5e5 ? 1 : 2) + 'M'; }
    if (m >= 1e3) { return s + '$' + (m / 1e3).toFixed(step >= 500 ? 0 : 1) + 'K'; }
    return s + '$' + m.toFixed(0);
  }
  function shortDate(iso, withYear) { var p = iso.split('-'); return MONTHS[+p[1] - 1] + ' ' + (+p[2]) + (withYear ? ', ' + p[0] : ''); }
  function niceStep(raw) { var e = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / e; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * e; }
  function logTicks(lo, hi) {
    if (lo <= 0 || hi <= lo) { return []; }
    // The first step pattern giving 3-6 labelled values wins (finest
    // first, so a narrow range still gets a few); otherwise whichever
    // pattern gives the most values without passing six.
    var pats = [[1, 2, 3, 4, 5, 6, 8], [1, 2, 5], [1, 5], [1]], best = [];
    for (var p = 0; p < pats.length; p++) {
      var out = [];
      for (var d = Math.floor(Math.log10(lo)); d <= Math.ceil(Math.log10(hi)); d++) {
        pats[p].forEach(function (m) { var t = m * Math.pow(10, d); if (t >= lo * 0.999 && t <= hi * 1.001) { out.push(t); } });
      }
      if (out.length >= 3 && out.length <= 6) { return out; }
      if (out.length <= 6 && out.length > best.length) { best = out; }
    }
    return best;
  }
  function setup(root) {
    if (root._spec) { return; }
    root._spec = JSON.parse(root.dataset.mlcSpec);
    root._on = root._spec.series.map(function () { return true; });
    var plot = root.querySelector('.mlc-plot');
    plot.classList.add('nw-chart');
    var tip = document.createElement('div'); tip.className = 'nw-tip'; tip.hidden = true; plot.appendChild(tip);
    root._tip = tip;
    plot.addEventListener('pointermove', function (ev) { hover(root, ev); });
    plot.addEventListener('pointerleave', function () { unhover(root); });
  }
  function unhover(root) {
    root._tip.hidden = true;
    var g = root.querySelector('.mlc-guide'); if (g) { g.setAttribute('visibility', 'hidden'); }
    var h = root.querySelector('.mlc-hl'); if (h) { h.innerHTML = ''; }
  }
  function hover(root, ev) {
    var st = root._state, svg = root.querySelector('.mlc-svg'); if (!st || !svg) { return; }
    var r = svg.getBoundingClientRect(), sx = (ev.clientX - r.left) / r.width * W;
    if (sx < PL - 8 || sx > W - PR + 8) { unhover(root); return; }
    var best = null, dist = Infinity;
    st.days.forEach(function (d) { var k = Math.abs(st.xAt(d) - sx); if (k < dist) { dist = k; best = d; } });
    if (best === null) { return; }
    var rows = [];
    st.vis.forEach(function (s) { s.pts.forEach(function (p) { if (day(p[2]) === best) { rows.push({s: s, p: p}); } }); });
    rows.sort(function (a, b) { return b.p[1] - a.p[1]; });
    var x = st.xAt(best), g = root.querySelector('.mlc-guide');
    g.setAttribute('x1', x.toFixed(1)); g.setAttribute('x2', x.toFixed(1)); g.setAttribute('visibility', 'visible');
    root.querySelector('.mlc-hl').innerHTML = rows.map(function (row) {
      return '<circle cx="' + x.toFixed(1) + '" cy="' + st.yAt(row.p[1]).toFixed(1) + '" r="4.5" stroke-width="2" style="fill:' + row.s.color + '; stroke:var(--surface);"/>';
    }).join('');
    var tip = root._tip;
    tip.innerHTML = '<div class="nw-tip-date">' + esc(rows.length ? shortDate(rows[0].p[2], true) : '') + '</div>' + rows.map(function (row) {
      return '<div class="nw-tip-row"><span class="nw-swatch" style="background:' + row.s.color + ';"></span><span class="nw-tip-name">' + esc(row.s.name) +
        '</span><span class="nw-tip-val">' + money(row.p[1]) + '</span></div>';
    }).join('');
    tip.hidden = false;
    var px = x / W * r.width, w = tip.offsetWidth, left = px + 14;
    if (left + w > r.width) { left = Math.max(0, px - w - 14); }
    tip.style.left = left + 'px'; tip.style.top = '8px';
  }
  function draw(root) {
    setup(root);
    var spec = root._spec, on = root._on, vis = spec.series.filter(function (_s, i) { return on[i]; });
    var holder = root.querySelector('.mlc-svg-holder') || (function () {
      var old = root.querySelector('.mlc-svg'), h = document.createElement('div'); h.className = 'mlc-svg-holder';
      old.parentNode.insertBefore(h, old); old.parentNode.removeChild(old); return h; })();
    root.querySelectorAll('.mlc-chip').forEach(function (c) { c.setAttribute('aria-pressed', on[+c.dataset.i] ? 'true' : 'false'); });
    var ch = root.querySelector('.mlc-change'), label = 'Balance history chart';
    if (!vis.length) {
      holder.innerHTML = '<svg class="mlc-svg" viewBox="0 0 ' + W + ' ' + H + '" style="width:100%; height:auto; display:block;"><text x="' + W / 2 + '" y="' + H / 2 +
        '" text-anchor="middle" font-size="14" style="fill:var(--ink-muted,#777);">No lines selected. Click a name below, or All.</text></svg>';
      root._state = null; ch.textContent = ''; return;
    }
    var vals = []; vis.forEach(function (s) { s.pts.forEach(function (p) { vals.push(p[1]); }); });
    var lo, hi, yAt, ticks = [], stepHint = 1;
    if (spec.log) {
      var pos = vals.filter(function (v) { return v > 0; }); lo = pos.length ? Math.min.apply(null, pos) : 1; hi = Math.max.apply(null, vals);
      if (hi <= lo) { hi = lo * 10; }
      var l0 = Math.log10(lo), l1 = Math.log10(hi);
      yAt = function (v) { return PT + (1 - (Math.log10(v > 0 ? v : lo) - l0) / (l1 - l0)) * PH; };
      ticks = logTicks(lo, hi); stepHint = 1e9;
      if (ticks.length < 3) {
        // A narrow span (a single account, say) holds no 1-2-5 gridlines, so
        // fall back to evenly spaced round values inside the span.
        [4, 6, 9].some(function (div) {
          var st = niceStep((hi - lo) / div), tk = [];
          for (var v = Math.ceil(lo / st) * st; v <= hi * 1.0001; v += st) { tk.push(v); }
          if (tk.length >= 3) { ticks = tk; stepHint = st; return true; }
          if (tk.length > ticks.length) { ticks = tk; stepHint = st; }
          return false;
        });
      }
    } else {
      lo = Math.min(0, Math.min.apply(null, vals)); hi = Math.max.apply(null, vals);
      if (hi - lo <= 0) { hi = lo + Math.max(Math.abs(lo) * 0.1, 1); }
      var step = niceStep((hi - lo) / 4); stepHint = step;
      for (var t = Math.ceil(lo / step) * step; t <= hi + step * 0.001; t += step) { ticks.push(t); }
      yAt = function (v) { return PT + (1 - (v - lo) / (hi - lo)) * PH; };
    }
    var dayset = {}; vis.forEach(function (s) { s.pts.forEach(function (p) { dayset[day(p[2])] = true; }); });
    var days = Object.keys(dayset).map(Number).sort(function (a, b) { return a - b; }), d0 = days[0], d1 = days[days.length - 1];
    var xAt = function (d) { return d1 === d0 ? PL + PW / 2 : PL + (d - d0) / (d1 - d0) * PW; };
    var years = new Date(d1 * 86400000).getUTCFullYear() !== new Date(d0 * 86400000).getUTCFullYear();
    var svg = '';
    ticks.forEach(function (t) { var y = yAt(t).toFixed(1);
      svg += '<line x1="' + PL + '" y1="' + y + '" x2="' + (W - PR) + '" y2="' + y + '" style="stroke:var(--border,#e5e2db);" stroke-width="1"/>' +
        '<text x="' + (PL - 8) + '" y="' + (+y + 4) + '" font-size="11" text-anchor="end" style="fill:var(--ink-muted,#777);">' + axisMoney(t, stepHint) + '</text>'; });
    if (!spec.log && lo < 0 && hi > 0) { var zy = yAt(0).toFixed(1); svg += '<line x1="' + PL + '" y1="' + zy + '" x2="' + (W - PR) + '" y2="' + zy + '" style="stroke:var(--ink-muted);" stroke-width="1" stroke-dasharray="3 3"/>'; }
    svg += '<text transform="translate(12 ' + (PT + PH / 2).toFixed(1) + ') rotate(-90)" font-size="10" text-anchor="middle" style="fill:var(--ink-muted,#777);">Balance' + (spec.log ? ' (log scale)' : '') + '</text>' +
      '<text x="' + (PL + PW / 2).toFixed(1) + '" y="' + (H - 6) + '" font-size="10" text-anchor="middle" style="fill:var(--ink-muted,#777);">Date</text>' +
      '<line x1="' + PL + '" y1="' + PBOT + '" x2="' + (W - PR) + '" y2="' + PBOT + '" style="stroke:var(--ink-muted,#777);" stroke-width="1"/>' +
      '<line x1="' + PL + '" y1="' + PT + '" x2="' + PL + '" y2="' + PBOT + '" style="stroke:var(--ink-muted,#777);" stroke-width="1"/>';
    var nt = Math.min(6, days.length), seen = {};
    for (var k = 0; k < nt; k++) {
      var dd = days[Math.round(k * (days.length - 1) / Math.max(1, nt - 1))]; if (seen[dd]) { continue; } seen[dd] = true;
      var iso = new Date(dd * 86400000).toISOString().slice(0, 10), xx = xAt(dd).toFixed(1);
      svg += '<line x1="' + xx + '" y1="' + PBOT + '" x2="' + xx + '" y2="' + (PBOT + 4) + '" style="stroke:var(--ink-muted,#777);" stroke-width="1"/>' +
        '<text x="' + xx + '" y="' + (PBOT + 18) + '" font-size="11" text-anchor="' + (k === 0 ? 'start' : k === nt - 1 ? 'end' : 'middle') + '" style="fill:var(--ink-muted,#777);">' + esc(shortDate(iso, years)) + '</text>';
    }
    vis.forEach(function (s) {
      var d = '', prev = null;
      s.pts.forEach(function (p) { var x = xAt(day(p[2])).toFixed(1), y = yAt(p[1]).toFixed(1); d += (prev === null || p[0] !== prev + 1 ? ' M ' : ' L ') + x + ' ' + y; prev = p[0]; });
      svg += '<path d="' + d.trim() + '" fill="none" style="stroke:' + s.color + ';" stroke-width="' + s.sw + '" stroke-linejoin="round" stroke-linecap="round"/>';
      if (s.pts.length <= 45) { s.pts.forEach(function (p) { svg += '<circle cx="' + xAt(day(p[2])).toFixed(1) + '" cy="' + yAt(p[1]).toFixed(1) + '" r="2.5" style="fill:' + s.color + ';"/>'; }); }
    });
    svg += '<line class="mlc-guide" x1="0" y1="' + PT + '" x2="0" y2="' + PBOT + '" visibility="hidden" style="stroke:var(--ink-muted);" stroke-width="1" stroke-dasharray="2 3"/><g class="mlc-hl"></g>';
    holder.innerHTML = '<svg class="mlc-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + label + '" style="width:100%; height:auto; display:block;" font-family="-apple-system, sans-serif">' + svg + '</svg>';
    root._state = {vis: vis, days: days, xAt: xAt, yAt: yAt};
    var head = vis.filter(function (s) { return s.emph; })[0] || vis[0], a = head.pts[0], b = head.pts[head.pts.length - 1], chg = b[1] - a[1];
    ch.style.color = chg >= 0 ? '#1baf7a' : '#c94a4a';
    ch.textContent = (chg >= 0 ? '+' : '') + money(chg) + (a[1] ? ' (' + (chg >= 0 ? '+' : '') + (chg / Math.abs(a[1]) * 100).toFixed(1) + '%)' : '') + ' since ' + a[2];
  }
  document.addEventListener('click', function (ev) {
    var root = ev.target.closest && ev.target.closest('.mlc'); if (!root) { return; }
    var btn = ev.target.closest('[data-mlc], .mlc-chip'); if (!btn) { return; }
    setup(root);
    var on = root._on, act = btn.dataset.mlc;
    if (act === 'all') { root._on = on = on.map(function () { return true; }); }
    else if (act === 'none') { root._on = on = on.map(function () { return false; }); }
    else if (act === 'total') { root._on = on = root._spec.series.map(function (s) { return !!s.emph; }); }
    else { on[+btn.dataset.i] = !on[+btn.dataset.i]; }
    draw(root);
  });
  function start() { document.querySelectorAll('.mlc').forEach(draw); }   // draw with axes straight away
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', start); } else { start(); }
})();
</script>"""


# Rows a bar chart shows before it scrolls (see .bar-chart's max-height in styles.py).
_BAR_CHART_VISIBLE_ROWS = 10


def _bar_chart_html(title: str, slices: list[tuple[str, float, list[str]]], *, dim: str) -> str:
    """Horizontal bar ranking, for a magnitude breakdown with too many
    categories to read as a donut (dataviz skill: a pie/donut stops
    being legible past ~6-7 slices, and every category here is already
    directly labeled on its own row, so a bar doesn't need a separate
    legend the way the donut charts above do). Same click-to-filter
    contract as _donut_chart_html -- each row is a ".pie-seg" carrying
    data-dim/data-slice-id/data-values, wired to the same shared
    handlePieSegClick() JS; the class name is kept for that shared JS
    even though this mark is a bar, not a wedge."""
    total = sum(v for _, v, _ in slices)
    if total <= 0:
        return (
            f'<div class="card" style="flex:1 1 320px;">'
            f'<h3 style="margin-top:0; font-size:13px;">{html.escape(title)}</h3>'
            '<p class="muted">No data yet.</p></div>'
        )
    max_value = max(v for _, v, _ in slices)

    rows = []
    for i, (label, value, member_labels) in enumerate(slices):
        color = _DONUT_OTHER_COLOR if label == "Other" else _DONUT_COLORS[i % len(_DONUT_COLORS)]
        pct = value / total * 100
        width_pct = max(value / max_value * 100, 1.5) if max_value > 0 else 0
        slice_id = f"{dim}-{i}"
        values_attr = html.escape(json.dumps(member_labels))
        click_attrs = (
            f'tabindex="0" role="button" aria-pressed="false" '
            f'data-dim="{html.escape(dim)}" data-slice-id="{html.escape(slice_id)}" data-values="{values_attr}" '
            f'onclick="handlePieSegClick(this)" onkeydown="handlePieSegKeydown(event, this)"'
        )
        rows.append(
            f'<div class="bar-row pie-seg" {click_attrs}>'
            f'<span class="bar-label" title="{html.escape(label)}">{html.escape(label)}</span>'
            f'<span class="bar-track" {_tip_attrs(label, f"{_money(value)} ({pct:.0f}%)", color)}>'
            f'<span class="bar-fill" style="width:{width_pct:.1f}%; background:{color};"></span></span>'
            f'<span class="bar-value">{html.escape(_money_short(value))} ({pct:.0f}%)</span>'
            f'</div>'
        )

    scrolls = len(slices) > _BAR_CHART_VISIBLE_ROWS
    hint_html = (
        f'<p class="muted bar-chart-hint">{len(slices)} rows -- scroll the list to see them all.</p>' if scrolls else ""
    )
    # A scrollable region has to be keyboard-reachable too.
    scroll_attrs = f' tabindex="0" role="region" aria-label="Bar chart rows (scrollable list)"' if scrolls else ""
    return f"""
<div class="card" style="flex:2 1 480px;">
<h3 style="margin-top:0; font-size:13px;">{html.escape(title)} <span class="muted bar-chart-total-label" style="font-weight:400;">&mdash; {html.escape(_money_short(total))} total</span></h3>
<div class="bar-chart"{scroll_attrs}>{"".join(rows)}</div>
{hint_html}
</div>
"""


# ---------------------------------------------------------------------------
# Net worth explorer: the Assets tab's net-worth line plus a picker for
# plotting individual assets next to it.
# ---------------------------------------------------------------------------

_NW_EXPLORER_COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#898781")
_NW_EXPLORER_DEFAULT_SELECTED = 3  # the largest assets are shown until the person picks their own

# Plain string (never .format()-ed / f-string-ed), so its braces need no
# doubling. Draws the same chart _line_chart_html does -- fitted y-range,
# five gridlines, labeled axes, date-proportional x -- for however many
# series are currently picked, in either dollar or %-change terms.
_NW_EXPLORER_JS = """
(function () {
  var root = document.getElementById(__ROOT_ID__);
  if (!root) return;
  var data = JSON.parse(root.querySelector('script[type="application/json"]').textContent);
  var chart = root.querySelector('.nw-chart');
  var COLORS = data.colors;
  var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  var W = 960, H = 270, PL = 84, PR = 18, PT = 14, PB = 54;
  var PW = W - PL - PR, PH = H - PT - PB, PBOT = PT + PH, PRIGHT = W - PR;
  var mode = 'value';
  var showNw = true;
  var selected = {};
  var reSel = {};
  var state = null;
  var holder = document.createElement('div');
  chart.appendChild(holder);
  var tip = document.createElement('div');
  tip.className = 'nw-tip';
  tip.hidden = true;
  chart.appendChild(tip);

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function day(iso) { var p = iso.split('-'); return Date.UTC(+p[0], +p[1] - 1, +p[2]) / 86400000; }
  function money(v) {
    var sign = v < 0 ? '-' : '';
    return sign + '$' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }
  function axisMoney(v, step) {
    var sign = v < 0 ? '-' : '', m = Math.abs(v);
    if (m >= 1e6) { var d = step >= 5e5 ? 1 : step >= 5e4 ? 2 : 3; return sign + '$' + (m / 1e6).toFixed(d) + 'M'; }
    if (m >= 1e3) { var k = step >= 500 ? 0 : step >= 50 ? 1 : 2; return sign + '$' + (m / 1e3).toFixed(k) + 'K'; }
    return sign + '$' + (step >= 1 ? m.toFixed(0) : m.toFixed(2));
  }
  function axisPct(v, step) {
    var d = step >= 5 ? 0 : step >= 0.5 ? 1 : 2;
    return (v > 0 ? '+' : '') + v.toFixed(d) + '%';
  }

  var topIds = data.assets.slice(0, data.defaultSelected).map(function (a) { return a.id; });
  var valid = {};
  data.assets.forEach(function (a) { valid[a.id] = true; });
  var saved = null;
  try { saved = JSON.parse(localStorage.getItem(__K_ASSETS__) || 'null'); } catch (e) {}
  (Array.isArray(saved) ? saved.filter(function (id) { return valid[id]; }) : topIds).forEach(function (id) { selected[id] = true; });
  try { var m = localStorage.getItem(__K_MODE__); if (m === 'value' || m === 'pct') mode = m; } catch (e) {}
  try { if (localStorage.getItem(__K_SHOW__) === '0') showNw = false; } catch (e) {}
  var reKeys = {};
  data.re.forEach(function (r) { reKeys[r.key] = true; });
  try {
    var savedRe = JSON.parse(localStorage.getItem(__K_RE__) || 'null');
    if (Array.isArray(savedRe)) savedRe.forEach(function (k) { if (reKeys[k]) reSel[k] = true; });
  } catch (e) {}

  // Picking either real-estate line switches the headline total from Net
  // Liquid Asset to Total Asset (Investable savings + real estate equity).
  function anyRe() { return !!(data.total && (data.headlineTotal || Object.keys(reSel).some(function (k) { return reSel[k]; }))); }
  function totalDef() { return anyRe() ? data.total : data.liquid; }

  function series() {
    var td = totalDef();
    var out = showNw ? [{ name: td.name, color: 'var(--ink)', width: 3, dash: '', pts: td.points }] : [];
    data.re.forEach(function (r) {
      if (reSel[r.key]) out.push({ name: r.name, color: data.reColor, width: 2.5, dash: r.dash, pts: r.points });
    });
    data.assets.forEach(function (a, i) {
      if (selected[a.id]) out.push({
        name: a.name, color: COLORS[i % COLORS.length], width: 2, dash: i >= COLORS.length ? '5 3' : '', pts: a.points,
      });
    });
    return out;
  }

  function draw() {
    var list = series().map(function (s) {
      var base = s.pts.length ? s.pts[0][1] : 0;
      var pts = [];
      s.pts.forEach(function (p) {
        var y = p[1];
        if (mode === 'pct') { if (!base) return; y = (p[1] - base) / Math.abs(base) * 100; }
        pts.push({ d: day(p[0]), label: p[0], raw: p[1], y: y });
      });
      return { name: s.name, color: s.color, width: s.width, dash: s.dash, pts: pts };
    }).filter(function (s) { return s.pts.length >= 1; });

    if (!list.length) {
      state = null; hideTip();
      holder.innerHTML = '<p class="muted" style="margin:28px 0; text-align:center;">' + esc(__EMPTY__) + '</p>';
      return;
    }
    var d0 = Infinity, d1 = -Infinity, lo = Infinity, hi = -Infinity;
    list.forEach(function (s) { s.pts.forEach(function (p) {
      d0 = Math.min(d0, p.d); d1 = Math.max(d1, p.d); lo = Math.min(lo, p.y); hi = Math.max(hi, p.y);
    }); });
    if (mode === 'pct') { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (hi - lo <= 1e-9) { var padFlat = Math.max(Math.abs(hi) * 0.01, 1); lo -= padFlat; hi += padFlat; }
    else { var padY = (hi - lo) * 0.12; lo -= padY; hi += padY; }
    var span = d1 - d0;
    function xAt(d) { return PL + (span > 0 ? (d - d0) / span : 0.5) * PW; }
    function yAt(v) { return PT + (1 - (v - lo) / (hi - lo)) * PH; }

    var axis = 'style="stroke:var(--ink-muted);" stroke-width="1"';
    var text = 'style="fill:var(--ink-muted);"';
    var svg = '';
    var step = (hi - lo) / 4;
    for (var g = 0; g <= 4; g++) {
      var v = lo + (hi - lo) * g / 4, y = yAt(v);
      svg += '<line x1="' + PL + '" y1="' + y.toFixed(1) + '" x2="' + PRIGHT + '" y2="' + y.toFixed(1) + '" style="stroke:var(--border);" stroke-width="1" stroke-dasharray="3 3"/>' +
        '<line x1="' + (PL - 5) + '" y1="' + y.toFixed(1) + '" x2="' + PL + '" y2="' + y.toFixed(1) + '" ' + axis + '/>' +
        '<text x="' + (PL - 9) + '" y="' + (y + 3).toFixed(1) + '" font-size="10" text-anchor="end" ' + text + '>' +
        (mode === 'pct' ? axisPct(v, step) : axisMoney(v, step)) + '</text>';
    }
    if (lo < 0 && hi > 0) {
      var zy = yAt(0).toFixed(1);
      svg += '<line x1="' + PL + '" y1="' + zy + '" x2="' + PRIGHT + '" y2="' + zy + '" style="stroke:var(--ink-muted);" stroke-width="1"/>';
    }
    svg += '<line x1="' + PL + '" y1="' + PT + '" x2="' + PL + '" y2="' + PBOT + '" ' + axis + '/>' +
      '<line x1="' + PL + '" y1="' + PBOT + '" x2="' + PRIGHT + '" y2="' + PBOT + '" ' + axis + '/>' +
      '<text transform="translate(14 ' + (PT + PH / 2).toFixed(1) + ') rotate(-90)" font-size="10" text-anchor="middle" ' + text + '>' +
      (mode === 'pct' ? 'Change since first reading' : 'Balance') + '</text>' +
      '<text x="' + (PL + PW / 2).toFixed(1) + '" y="' + (H - 6) + '" font-size="10" text-anchor="middle" ' + text + '>Date</text>';

    function iso(d) { var t = new Date(d * 86400000); return t.toISOString().slice(0, 10); }
    var ticks = [[PL, iso(d0), 'start'], [PRIGHT, iso(d1), 'end']];
    if (span >= 8) {
      [1, 2, 3, 4, 5].forEach(function (k) {
        var td = d0 + Math.round(span * k / 6), t = new Date(td * 86400000);
        ticks.push([xAt(td), MONTHS[t.getUTCMonth()] + ' ' + t.getUTCDate(), 'middle']);
      });
    }
    ticks.forEach(function (t) {
      svg += '<line x1="' + t[0].toFixed(1) + '" y1="' + PBOT + '" x2="' + t[0].toFixed(1) + '" y2="' + (PBOT + 5) + '" ' + axis + '/>' +
        '<text x="' + t[0].toFixed(1) + '" y="' + (PBOT + 18) + '" font-size="10" text-anchor="' + t[2] + '" ' + text + '>' + t[1] + '</text>';
    });

    // Assets first, net worth last, so the headline line is never hidden under one.
    list.slice().reverse().forEach(function (s) {
      var path = s.pts.map(function (p, i) { return (i ? 'L ' : 'M ') + xAt(p.d).toFixed(1) + ' ' + yAt(p.y).toFixed(1); }).join(' ');
      svg += '<path d="' + path + '" fill="none" style="stroke:' + s.color + ';" stroke-width="' + s.width + '"' +
        (s.dash ? ' stroke-dasharray="' + s.dash + '"' : '') + ' stroke-linejoin="round" stroke-linecap="round"/>';
      var all = s.pts.length <= 45;
      s.pts.forEach(function (p, i) {
        // Hover is driven by the pointer's x (state.days), so points that
        // aren't drawn need no element at all.
        if (!(all || i === s.pts.length - 1)) return;
        svg += '<circle cx="' + xAt(p.d).toFixed(1) + '" cy="' + yAt(p.y).toFixed(1) + '" r="3" ' +
          'style="fill:' + s.color + ';"/>';
      });
    });
    svg += '<line class="nw-guide" x1="0" y1="' + PT + '" x2="0" y2="' + PBOT + '" visibility="hidden" ' +
      'style="stroke:var(--ink-muted);" stroke-width="1" stroke-dasharray="2 3"/><g class="nw-hl"></g>';
    holder.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(__ARIA__) + '" ' +
      'style="width:100%; height:auto; display:block;" font-family="-apple-system, sans-serif">' + svg + '</svg>';
    var dayset = {};
    list.forEach(function (s) { s.pts.forEach(function (p) { dayset[p.d] = true; }); });
    state = { list: list, xAt: xAt, yAt: yAt, days: Object.keys(dayset).map(Number).sort(function (a, b) { return a - b; }) };
  }

  function hideTip() {
    tip.hidden = true;
    var g = holder.querySelector('.nw-guide');
    if (g) g.setAttribute('visibility', 'hidden');
    var h = holder.querySelector('.nw-hl');
    if (h) h.innerHTML = '';
  }

  function showTip(ev) {
    var svgEl = holder.querySelector('svg');
    if (!state || !svgEl) return;
    var r = svgEl.getBoundingClientRect();
    var sx = (ev.clientX - r.left) / r.width * W;
    if (sx < PL - 8 || sx > PRIGHT + 8) { hideTip(); return; }
    var best = null, bestDist = Infinity;
    state.days.forEach(function (d) {
      var dist = Math.abs(state.xAt(d) - sx);
      if (dist < bestDist) { bestDist = dist; best = d; }
    });
    if (best === null) return;
    var rows = [];
    state.list.forEach(function (s) {
      s.pts.forEach(function (p) { if (p.d === best) rows.push({ s: s, p: p }); });
    });
    var x = state.xAt(best);
    var guide = holder.querySelector('.nw-guide');
    guide.setAttribute('x1', x.toFixed(1)); guide.setAttribute('x2', x.toFixed(1));
    guide.setAttribute('visibility', 'visible');
    holder.querySelector('.nw-hl').innerHTML = rows.map(function (row) {
      return '<circle cx="' + x.toFixed(1) + '" cy="' + state.yAt(row.p.y).toFixed(1) + '" r="5" stroke-width="2" ' +
        'style="fill:' + row.s.color + '; stroke:var(--surface);"/>';
    }).join('');
    var label = rows.length ? rows[0].p.label : '';
    tip.innerHTML = '<div class="nw-tip-date">' + esc(label) + '</div>' + rows.map(function (row) {
      return '<div class="nw-tip-row"><span class="nw-swatch" style="background:' + row.s.color + ';"></span>' +
        '<span class="nw-tip-name">' + esc(row.s.name) + '</span><span class="nw-tip-val">' + money(row.p.raw) +
        (mode === 'pct' ? ' <span class="nw-tip-pct">(' + (row.p.y >= 0 ? '+' : '') + row.p.y.toFixed(2) + '%)</span>' : '') +
        '</span></div>';
    }).join('');
    tip.hidden = false;
    var px = x / W * r.width, w = tip.offsetWidth;
    var left = px + 14;
    if (left + w > r.width) left = Math.max(0, px - w - 14);
    tip.style.left = left + 'px';
    tip.style.top = '8px';
  }
  chart.addEventListener('pointermove', showTip);
  chart.addEventListener('pointerleave', hideTip);

  function sync() {
    var nwChip = root.querySelector('.nw-chip[data-nw]');
    if (nwChip) {
      nwChip.setAttribute('aria-pressed', showNw ? 'true' : 'false');
      nwChip.querySelector('.nw-chip-label').textContent = totalDef().name;
    }
    var title = root.querySelector('.nw-title');
    if (title) title.textContent = totalDef().name;
    var change = root.querySelector('.nw-change');
    if (change) { change.textContent = totalDef().change; change.style.color = totalDef().up ? '#1baf7a' : '#c94a4a'; }
    root.querySelectorAll('.nw-chip[data-re]').forEach(function (b) {
      b.setAttribute('aria-pressed', reSel[b.getAttribute('data-re')] ? 'true' : 'false');
    });
    root.querySelectorAll('.nw-chip[data-id]').forEach(function (b) {
      var on = !!selected[b.getAttribute('data-id') * 1];
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    root.querySelectorAll('.nw-mode').forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-mode') === mode ? 'true' : 'false');
    });
  }
  function save() {
    try {
      localStorage.setItem(__K_ASSETS__, JSON.stringify(Object.keys(selected).filter(function (k) { return selected[k]; }).map(Number)));
      localStorage.setItem(__K_MODE__, mode);
      localStorage.setItem(__K_SHOW__, showNw ? '1' : '0');
      localStorage.setItem(__K_RE__, JSON.stringify(Object.keys(reSel).filter(function (k) { return reSel[k]; })));
    } catch (e) {}
  }
  root.addEventListener('click', function (ev) {
    var chip = ev.target.closest('.nw-chip[data-id]');
    if (chip) { var id = chip.getAttribute('data-id') * 1; selected[id] = !selected[id]; }
    var nwc = ev.target.closest('.nw-chip[data-nw]');
    if (nwc) showNw = !showNw;
    var rec = ev.target.closest('.nw-chip[data-re]');
    if (rec) { var rk = rec.getAttribute('data-re'); reSel[rk] = !reSel[rk]; }
    var m = ev.target.closest('.nw-mode');
    if (m) mode = m.getAttribute('data-mode');
    var act = ev.target.closest('[data-action]');
    if (act) {
      selected = {};
      if (act.getAttribute('data-action') !== 'all') reSel = {};
      if (act.getAttribute('data-action') === 'all') data.assets.forEach(function (a) { selected[a.id] = true; });
    }
    if (chip || nwc || rec || m || act) { save(); sync(); draw(); }
  });
  sync();
  draw();
})();
"""


_NW_EXPLORER_RE_COLOR = "#8e5bd9"


def _nw_change(points: list[tuple[str, float]], *, debt: bool = False) -> tuple[str, bool]:
    """("+$X (+Y%) since DATE", is_good) for a dated series' first-to-last
    move. For a debt series (debt=True) a fall is the good direction and the
    wording says so: "paid down $X (Y%) since DATE" / "up $X (Y%) since DATE"."""
    first_date, first_value = points[0]
    change = points[-1][1] - first_value
    pct = (change / abs(first_value) * 100) if first_value else None
    if debt:
        word = "paid down" if change <= 0 else "up"
        label = (
            f"{word} {_money(abs(change))}"
            + (f" ({abs(pct):.1f}%)" if pct is not None else "")
            + f" since {first_date}"
        )
        return label, change <= 0
    label = (
        f"{'+' if change >= 0 else ''}{_money(change)}"
        + (f" ({'+' if pct >= 0 else ''}{pct:.1f}%)" if pct is not None else "")
        + f" since {first_date}"
    )
    return label, change >= 0


def _net_worth_explorer_html(
    liquid_points: list[tuple[str, float]], total_points: list[tuple[str, float]] | None,
    assets: list[dict], real_estate: list[dict], *, note: str = "",
    element_id: str = "nw-explorer", storage_prefix: str = "rp-nw", debt: bool = False,
    heading: str = "", total_name: str = "Total Asset", liquid_name: str = "Investable savings",
    aria_label: str = "Net worth and selected assets over time",
    empty_message: str = "Nothing selected -- pick the total line, real estate, or one or more assets above to plot them.",
    default_selected: int = _NW_EXPLORER_DEFAULT_SELECTED,
) -> str:
    """The Assets tab's one over-time chart. The headline line is Net Liquid
    Asset by default; picking either real-estate line (value / equity)
    switches it to Total Asset (Investable savings + real estate equity,
    `total_points`) -- the same two figures the rollup table above sums.
    Toggle chips plot individual assets next to it (colored in the same
    fixed palette order as the donut charts), with "All"/"None" shortcuts
    and a "$ value" / "% change" switch -- % change starts every line at 0
    so a $100K account and a $14M total can share one axis. The y-axis
    refits to whatever is shown. `assets` is aggregate.asset_balance_history()'s
    shape (largest first); `real_estate` is [{"key": "value"|"equity",
    "name", "points", "dash"}] (empty when there are no properties). The
    picked set and mode persist in localStorage. Drawn client-side from the
    embedded JSON (same layout rules as _line_chart_html).

    The same chart also draws the Assets & Debts page's debt-paydown chart
    (debt=True): ``liquid_points`` is then the Liabilities total, the optional
    ``total_points`` is All debts (liabilities + mortgages) and is the
    headline whenever it exists, ``real_estate`` carries the extra lines
    (Liabilities, Home mortgages), a falling line is the good (green)
    direction and the headline reads "paid down $X since DATE". The id,
    storage keys, heading and wording are parameters so two charts on one
    page never share state."""
    def total_def(name: str, points: list[tuple[str, float]]) -> dict:
        label, up = _nw_change(points, debt=debt)
        return {"name": name, "points": [[d, v] for d, v in points], "change": label, "up": up}

    liquid = total_def(liquid_name, liquid_points)
    total = total_def(total_name, total_points) if total_points and real_estate else None
    payload = {
        "liquid": liquid,
        "total": total,
        "re": [
            {"key": r["key"], "name": r["name"], "dash": r.get("dash", ""), "points": [[d, v] for d, v in r["points"]]}
            for r in real_estate
        ],
        "reColor": _NW_EXPLORER_RE_COLOR,
        "assets": [
            {"id": a["id"], "name": a["name"], "category": a["category"], "points": [[d, v] for d, v in a["points"]]}
            for a in assets
        ],
        "colors": list(_NW_EXPLORER_COLORS),
        "defaultSelected": default_selected,
        "headlineTotal": bool(debt and total),
    }
    data_json = json.dumps(payload).replace("</", "<\\/")
    chips = "".join(
        f'<button type="button" class="nw-chip" data-id="{a["id"]}" aria-pressed="false" '
        f'title="{html.escape(a["category"])} -- {html.escape(_money(a["points"][-1][1]))} on {html.escape(a["points"][-1][0])}">'
        f'<span class="nw-swatch" style="background:{_NW_EXPLORER_COLORS[i % len(_NW_EXPLORER_COLORS)]};"></span>'
        f'{html.escape(a["name"])}</button>'
        for i, a in enumerate(assets)
    )
    re_chips = "".join(
        f'<button type="button" class="nw-chip" data-re="{html.escape(r["key"])}" aria-pressed="false" '
        f'title="{html.escape(r.get("title", ""))}">'
        f'<span class="nw-swatch" style="'
        + (f'background:transparent; border:2px solid {_NW_EXPLORER_RE_COLOR};' if r.get("dash")
           else f'background:{_NW_EXPLORER_RE_COLOR};')
        + f'"></span>{html.escape(r["name"])}</button>'
        for r in real_estate
    )
    note_html = f'<p class="muted" style="margin:4px 0 0;">{html.escape(note)}</p>' if note else ""
    headline = total if (debt and total) else liquid
    title_html = (
        f'{html.escape(heading)}' if heading
        else f'<span class="nw-title">{html.escape(headline["name"])}</span> over time'
    )
    js = (
        _NW_EXPLORER_JS
        .replace("__ROOT_ID__", json.dumps(element_id))
        .replace("__K_ASSETS__", json.dumps(storage_prefix + "-assets"))
        .replace("__K_MODE__", json.dumps(storage_prefix + "-mode"))
        .replace("__K_SHOW__", json.dumps(storage_prefix + "-show"))
        .replace("__K_RE__", json.dumps(storage_prefix + "-re"))
        .replace("__EMPTY__", json.dumps(empty_message))
        .replace("__ARIA__", json.dumps(aria_label))
    )
    return f"""
<div class="card nw-explorer" id="{html.escape(element_id)}" style="flex:2 1 480px;">
<h3 style="margin-top:0; font-size:13px;">{title_html} <span class="nw-change" style="color:{'#1baf7a' if headline['up'] else '#c94a4a'}; font-weight:600;">{html.escape(headline["change"])}</span></h3>
<div class="nw-controls">
  <button type="button" class="nw-chip" data-nw="1" aria-pressed="true" title="Show or hide the total line"><span class="nw-swatch" style="background:var(--ink);"></span><span class="nw-chip-label">{html.escape(headline["name"])}</span></button>
  {re_chips}
  {chips}
  <span class="nw-tools">
    <button type="button" class="nw-link" data-action="all">All</button>
    <button type="button" class="nw-link" data-action="none">None</button>
  </span>
  <span class="nw-seg" role="group" aria-label="Chart units">
    <button type="button" class="nw-mode" data-mode="value" aria-pressed="true">$ value</button>
    <button type="button" class="nw-mode" data-mode="pct" aria-pressed="false">% change</button>
  </span>
</div>
<div class="nw-chart"></div>
{note_html}
<script type="application/json">{data_json}</script>
<script>{js}</script>
</div>
"""
