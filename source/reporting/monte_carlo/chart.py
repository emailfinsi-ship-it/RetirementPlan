"""Rendering -- a single-hue fan chart (p10-p90 band, dashed 90th/10th
percentile lines and a solid median line), per the
dataviz skill: one hue for a magnitude band, thin 2px median line,
recessive gridlines, per-point <title> hover tooltips (this is a plain
static SVG page, not a JS charting library).
"""

from __future__ import annotations

import html


_BAND_COLOR = "#0071e3"  # matches the dashboard shell's own --brand (styles.py)

_HISTORICAL_BAND_COLOR = "#eb6834"  # same 2nd-slot orange dashboard.py's own _DONUT_COLORS use



def _money_short(value: float) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:.0f}K"
    return f"{sign}${value:.0f}"



def render_fan_svg(result: dict, *, width: int = 720, height: int = 320, color: str = _BAND_COLOR) -> str:
    band = result.get("band") or []
    if not band:
        return (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<text x="{width / 2}" y="{height / 2}" text-anchor="middle" style="fill:var(--ink-muted,#999);" font-size="13">'
            "No simulation data yet.</text></svg>"
        )

    margin_left, margin_right, margin_top, margin_bottom = 64, 62, 16, 28
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    max_val = max(row["p90"] for row in band)
    max_val = max(max_val, 1.0)
    n = len(band)

    def x_for(i):
        return margin_left + (plot_w * i / (n - 1) if n > 1 else 0)

    def y_for(value):
        return margin_top + plot_h - (value / max_val * plot_h)

    # Gridlines + y-axis labels (4 bands).
    gridlines = []
    for step in range(5):
        val = max_val * step / 4
        y = y_for(val)
        gridlines.append(
            f'<line x1="{margin_left}" y1="{y:.1f}" x2="{width - margin_right}" y2="{y:.1f}" '
            f'style="stroke:var(--border,#e5e5e5);" stroke-width="1" />'
        )
        gridlines.append(
            f'<text x="{margin_left - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" style="fill:var(--ink-muted,#777);">'
            f"{html.escape(_money_short(val))}</text>"
        )

    # Band area (p10-p90).
    top_points = " ".join(f"{x_for(i):.1f},{y_for(row['p90']):.1f}" for i, row in enumerate(band))
    bottom_points = " ".join(
        f"{x_for(i):.1f},{y_for(row['p10']):.1f}" for i, row in reversed(list(enumerate(band)))
    )
    band_path = f"M {top_points} L {bottom_points} Z"

    # Explicit 90th / 10th percentile lines along the band's edges (thin,
    # dashed, same hue as the band -- the median stays the one solid,
    # heavier line), plus direct end-of-line labels so nothing relies on
    # color alone to say which line is which.
    p90_points = " ".join(f"{x_for(i):.1f},{y_for(row['p90']):.1f}" for i, row in enumerate(band))
    p10_points = " ".join(f"{x_for(i):.1f},{y_for(row['p10']):.1f}" for i, row in enumerate(band))
    last = band[-1]
    end_labels = [
        ["90th pct", y_for(last["p90"]), 400],
        ["Median", y_for(last["median"]), 600],
        ["10th pct", y_for(last["p10"]), 400],
    ]
    # Lines can end close together -- push labels apart (top to bottom)
    # so they never overprint one another.
    end_labels.sort(key=lambda item: item[1])
    min_gap = 12.0
    for k in range(1, len(end_labels)):
        if end_labels[k][1] - end_labels[k - 1][1] < min_gap:
            end_labels[k][1] = end_labels[k - 1][1] + min_gap
    end_label_svg = "".join(
        f'<text x="{width - margin_right + 6}" y="{y + 3.5:.1f}" font-size="10" font-weight="{weight}" '
        f'style="fill:var(--ink-muted,#777);">{html.escape(label)}</text>'
        for label, y, weight in end_labels
    )

    # Median line + hover points.
    median_points = " ".join(f"{x_for(i):.1f},{y_for(row['median']):.1f}" for i, row in enumerate(band))
    dots = []
    for i, row in enumerate(band):
        if i % max(1, n // 12) != 0 and i != n - 1:
            continue
        cx, cy = x_for(i), y_for(row["median"])
        tip = (
            f"{row['year']}: median {_money_short(row['median'])} "
            f"(p10 {_money_short(row['p10'])} - p90 {_money_short(row['p90'])})"
        )
        dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="{color}"><title>{tip}</title></circle>')
        for key in ("p90", "p10"):
            dots.append(
                f'<circle cx="{cx:.1f}" cy="{y_for(row[key]):.1f}" r="2.5" fill="{color}" fill-opacity="0.8">'
                f"<title>{tip}</title></circle>"
            )

    # X-axis year labels, thinned to avoid overlap.
    x_labels = []
    label_stride = max(1, n // 8)
    for i, row in enumerate(band):
        if i % label_stride != 0 and i != n - 1:
            continue
        x_labels.append(
            f'<text x="{x_for(i):.1f}" y="{height - 8}" text-anchor="middle" font-size="11" style="fill:var(--ink-muted,#777);">'
            f"{row['year']}</text>"
        )

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="-apple-system, sans-serif">'
        + "".join(gridlines)
        + f'<path d="{band_path}" fill="{color}" fill-opacity="0.15" stroke="none" />'
        + f'<polyline points="{p90_points}" fill="none" stroke="{color}" stroke-width="1.5" stroke-dasharray="5 3" />'
        + f'<polyline points="{p10_points}" fill="none" stroke="{color}" stroke-width="1.5" stroke-dasharray="5 3" />'
        + f'<polyline points="{median_points}" fill="none" stroke="{color}" stroke-width="2" />'
        + "".join(dots)
        + end_label_svg
        + "".join(x_labels)
        + "</svg>"
    )
