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
        return (
            f'<div class="card" style="flex:1 1 480px;">'
            f'<h3 style="margin-top:0; font-size:13px;">{html.escape(title)}</h3>'
            f'<p class="muted">{html.escape(empty_message)}</p></div>'
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
<h3 style="margin-top:0; font-size:13px;">{html.escape(title)} <span class="muted" style="font-weight:400;">-- {html.escape(_money_short(total))} total</span></h3>
<div class="bar-chart">{"".join(rows)}</div>
</div>
"""
