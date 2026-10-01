"""Donut and horizontal-bar chart renderers shared by every page that
breaks a total down by category (Summary, Asset, Expense/Income, Linked
Positions, Linked Accounts, Real Expenditure) -- see the dataviz skill
for the chart-form and color-assignment rules these follow (fixed
categorical hue order, <=6 real slices + a folded "Other", click-to-
filter wired through the shared handlePieSegClick() JS in shell.py's
PAGE_SHELL). Every chart's segments carry the data-dim/data-slice-id/
data-values click-to-filter contract, but only Linked Positions
(applyPositionFilters), Real Expenditure (applyExpenditureFilters), and
Linked Accounts (applyAccountsFilters) currently have a table wired up
to actually filter on click -- a click on Summary/Asset/Expense's own
charts still highlights the clicked segment but has no table below it
to filter.
"""

from __future__ import annotations

import html
import json
import math

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


def _donut_chart_html(title: str, slices: list[tuple[str, float, list[str]]], *, dim: str, size: int = 180) -> str:
    """Part-to-whole donut for <=6 real segments (+ a folded "Other") --
    categorical hues in fixed slot order, a legend with swatch + label +
    value + percent (identity is never color-alone), a small gap between
    wedges standing in for the mark spec's 2px surface gap (a dash gap
    rather than a border), and a native <title> hover tooltip per wedge
    since this is a plain static SVG page, not a JS charting library.

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
            f'<circle class="pie-seg" {click_attrs} cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}" '
            f'stroke-dasharray="{dash:.2f} {remainder:.2f}" stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})">'
            f'<title>{html.escape(label)}: {html.escape(_money(value))} ({pct:.0f}%) -- click to filter the list below</title></circle>'
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
        + f'<text x="{cx}" y="{cy - 3}" text-anchor="middle" font-size="14" font-weight="600" fill="#0b0b0b">'
        f'{html.escape(_money_short(total))}</text>'
        + f'<text x="{cx}" y="{cy + 12}" text-anchor="middle" font-size="10" fill="#777">Total</text>'
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


def _line_chart_html(
    title: str, points: list[tuple[str, float]], *, note: str = "",
    empty_message: str = _DEFAULT_LINE_CHART_EMPTY_MESSAGE,
) -> str:
    """A single-series trend line -- change-over-time, unlike the part-
    to-whole donut/bar charts above (dataviz skill: a trend belongs on
    one axis, read left-to-right, not ranked by magnitude). Currently
    only the Asset tab's net-worth-over-time card uses this (source.
    common.db.net_worth_snapshots, reduced to one point per calendar
    month -- see source.webapp.pages.asset._monthly_net_worth_points),
    so it's deliberately minimal: no click-to-filter (there's no table
    of individual snapshots to filter down to), evenly-spaced x
    positions (real date-proportional spacing would mostly just
    reproduce even spacing anyway for points that are roughly evenly
    spread over time), and direct labels only at the first/last point
    plus one hover tooltip per point rather than a label on every point
    (dataviz skill: selective direct labels,
    never one on every mark)."""
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
    width, height = 640, 180
    pad_left, pad_right, pad_top, pad_bottom = 8, 8, 12, 22
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    values = [v for _, v in points]
    lo, hi = min(0.0, min(values)), max(values)
    if hi - lo <= 0:
        hi = lo + max(abs(lo) * 0.1, 1.0)  # a flat/all-zero series still gets a visible range

    def x_at(i: int) -> float:
        return pad_left + (i / (len(points) - 1)) * plot_w

    def y_at(v: float) -> float:
        return pad_top + (1 - (v - lo) / (hi - lo)) * plot_h

    coords = [(x_at(i), y_at(v)) for i, (_, v) in enumerate(points)]
    path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in coords)

    zero_line = ""
    if lo < 0 < hi:
        zero_y = y_at(0.0)
        zero_line = (
            f'<line x1="{pad_left}" y1="{zero_y:.1f}" x2="{width - pad_right}" y2="{zero_y:.1f}" '
            f'stroke="#d8d5cf" stroke-width="1" stroke-dasharray="3 3"/>'
        )

    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{_LINE_CHART_COLOR}">'
        f'<title>{html.escape(date)}: {html.escape(_money(value))}</title></circle>'
        for (date, value), (x, y) in zip(points, coords)
    )
    first_date, first_value = points[0]
    last_date, last_value = points[-1]
    labels = (
        f'<text x="{pad_left}" y="{height - 6}" font-size="10" fill="#777">{html.escape(first_date)}</text>'
        f'<text x="{width - pad_right}" y="{height - 6}" font-size="10" fill="#777" text-anchor="end">'
        f'{html.escape(last_date)}</text>'
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
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="-apple-system, sans-serif">'
        f'{zero_line}'
        f'<path d="{path}" fill="none" stroke="{_LINE_CHART_COLOR}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        f'{dots}{labels}'
        '</svg>'
    )
    note_html = f'<p class="muted" style="margin:4px 0 0;">{html.escape(note)}</p>' if note else ""
    return f"""
<div class="card" style="flex:2 1 480px;">
<h3 style="margin-top:0; font-size:13px;">{html.escape(title)} <span style="color:{change_color}; font-weight:600;">{html.escape(change_label)}</span></h3>
{svg}
{note_html}
</div>
"""


# Deliberately outside the _DONUT_COLORS categorical rotation (same
# reasoning as _DONUT_OTHER_COLOR above) -- an "emphasize"d series in
# _multi_line_chart_html (the combined Total line, normally) always gets
# this dark, un-rotated ink color instead of a rotation slot, so it
# reads as "the headline total," never "series #5."
_MULTI_LINE_EMPHASIS_COLOR = "#3a3833"


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
                f'stroke="#e5e2db" stroke-width="1"/>'
                f'<text x="{pad_left + 2}" y="{ty - 2:.1f}" font-size="9" fill="#777">{html.escape(_money_short(tick))}</text>'
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
                f'stroke="#d8d5cf" stroke-width="1" stroke-dasharray="3 3"/>'
            )

    direct_label_ok = len(non_empty) <= 4
    color_i = 0
    lines_svg, dots_svg, end_labels_svg, legend_items = [], [], [], []
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
            f'<path d="{" ".join(path_parts)}" fill="none" stroke="{color}" stroke-width="{stroke_width}" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        dots_svg.append("".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{dot_r}" fill="{color}">'
            f'<title>{html.escape(s["name"])} -- {html.escape(d)}: {html.escape(_money(v))}</title></circle>'
            for (x, y), (d, v) in zip(coords, pts)
        ))
        if direct_label_ok and coords:
            lx, ly = coords[-1]
            end_labels_svg.append(
                f'<text x="{lx + 4:.1f}" y="{ly + 3:.1f}" font-size="9" fill="{color}">{html.escape(s["name"])}</text>'
            )
        legend_items.append(
            f'<span style="display:inline-flex; align-items:center; gap:4px; margin-right:12px;">'
            f'<span style="display:inline-block; width:10px; height:10px; border-radius:2px; background:{color};"></span>'
            f'<span class="muted" style="font-size:11px;">{html.escape(s["name"])}</span></span>'
        )

    first_date, last_date = all_dates[0], all_dates[-1]
    x_labels = (
        f'<text x="{pad_left}" y="{height - 6}" font-size="10" fill="#777">{html.escape(first_date)}</text>'
        f'<text x="{width - pad_right}" y="{height - 6}" font-size="10" fill="#777" text-anchor="end">'
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
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="-apple-system, sans-serif">'
        f'{grid_svg}{zero_line}{"".join(lines_svg)}{"".join(dots_svg)}{"".join(end_labels_svg)}{x_labels}'
        '</svg>'
    )
    legend_html = f'<div style="margin-top:4px;">{"".join(legend_items)}</div>' if len(non_empty) >= 2 else ""
    full_note = note
    if log_scale:
        log_note = "Logarithmic scale -- equal vertical spacing represents equal percentage change, not equal dollar change."
        full_note = f"{log_note} {note}" if note else log_note
    note_html = f'<p class="muted" style="margin:4px 0 0;">{html.escape(full_note)}</p>' if full_note else ""
    return f"""
<div class="card" style="flex:2 1 480px;">
<h3 style="margin-top:0; font-size:13px;">{html.escape(title)} <span style="color:{change_color}; font-weight:600;">{html.escape(change_label)}</span></h3>
{svg}
{legend_html}
{note_html}
</div>
"""


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
            f'<span class="bar-track"><span class="bar-fill" style="width:{width_pct:.1f}%; background:{color};" '
            f'title="{html.escape(label)}: {html.escape(_money(value))} ({pct:.0f}%) -- click to filter the list below"></span></span>'
            f'<span class="bar-value">{html.escape(_money_short(value))} ({pct:.0f}%)</span>'
            f'</div>'
        )

    return f"""
<div class="card" style="flex:2 1 480px;">
<h3 style="margin-top:0; font-size:13px;">{html.escape(title)} <span class="muted bar-chart-total-label" style="font-weight:400;">-- {html.escape(_money_short(total))} total</span></h3>
<div class="bar-chart">{"".join(rows)}</div>
</div>
"""
