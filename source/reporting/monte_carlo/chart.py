"""Rendering -- a single-hue fan chart (p10-p90 band, dashed 90th/10th
percentile lines and a solid median line), per the
dataviz skill: one hue for a magnitude band, thin 2px median line,
recessive gridlines, per-point <title> hover tooltips (this is a plain
static SVG page, not a JS charting library).
"""

from __future__ import annotations

import html
import json


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



def render_fan_svg(
    result: dict, *, width: int = 720, height: int = 320, color: str = _BAND_COLOR,
    plain: bool = False, responsive: bool = False, retirement_year: int | None = None, birth_year: int | None = None,
) -> str:
    """plain=True swaps the statistician's labels (90th pct / Median / 10th
    pct) for plain words (Strong case / Typical / Cautious); responsive=True
    lets the SVG scale to its container's width; retirement_year draws a
    dashed "Retire" marker; birth_year adds an age under each year label."""
    band = result.get("band") or []
    if not band:
        return (
            f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<text x="{width / 2}" y="{height / 2}" text-anchor="middle" style="fill:var(--ink-muted,#999);" font-size="13">'
            "No simulation data yet.</text></svg>"
        )

    margin_left, margin_right, margin_top, margin_bottom = 64, 78 if plain else 62, 22, 44 if birth_year else 28
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
        ["Strong case" if plain else "90th pct", y_for(last["p90"]), 400],
        ["Typical" if plain else "Median", y_for(last["median"]), 600],
        ["Cautious" if plain else "10th pct", y_for(last["p10"]), 400],
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
            f"{row['year']}: typical {_money_short(row['median'])} "
            f"(cautious {_money_short(row['p10'])} - strong {_money_short(row['p90'])})"
            if plain else
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
            f'<text x="{x_for(i):.1f}" y="{height - (26 if birth_year else 8)}" text-anchor="middle" font-size="11" '
            f'style="fill:var(--ink-muted,#777);">{row["year"]}</text>'
        )
        if birth_year:
            x_labels.append(
                f'<text x="{x_for(i):.1f}" y="{height - 10}" text-anchor="middle" font-size="10" '
                f'style="fill:var(--ink-muted,#777);">age {int(row["year"]) - int(birth_year)}</text>'
            )

    marker = ""
    if retirement_year is not None:
        for i, row in enumerate(band):
            if int(row["year"]) == int(retirement_year):
                mx = x_for(i)
                marker = (
                    f'<line x1="{mx:.1f}" y1="{margin_top}" x2="{mx:.1f}" y2="{margin_top + plot_h}" '
                    f'style="stroke:var(--ink-muted,#777);" stroke-width="1" stroke-dasharray="3 3" />'
                    f'<text x="{mx + 4:.1f}" y="{margin_top + 10}" font-size="10" style="fill:var(--ink-muted,#777);">'
                    f"Retire {int(retirement_year)}</text>"
                )
                break
    size_attrs = (
        f'width="100%" style="max-width:{width}px; height:auto;"' if responsive else f'width="{width}" height="{height}"'
    )
    svg = (
        f'<svg {size_attrs} viewBox="0 0 {width} {height}" '
        f'font-family="-apple-system, sans-serif">'
        + "".join(gridlines)
        + marker
        + f'<path d="{band_path}" fill="{color}" fill-opacity="0.15" stroke="none" />'
        + f'<polyline points="{p90_points}" fill="none" stroke="{color}" stroke-width="1.5" stroke-dasharray="5 3" />'
        + f'<polyline points="{p10_points}" fill="none" stroke="{color}" stroke-width="1.5" stroke-dasharray="5 3" />'
        + f'<polyline points="{median_points}" fill="none" stroke="{color}" stroke-width="2" />'
        + "".join(dots)
        + end_label_svg
        + "".join(x_labels)
        + (
            f'<line class="fan-cross" x1="0" y1="{margin_top}" x2="0" y2="{margin_top + plot_h}" '
            f'style="stroke:var(--ink-muted,#777); display:none;" stroke-width="1" stroke-dasharray="4 3"/>'
            f'<ellipse class="fan-ring" rx="5" ry="5" cx="0" cy="0" fill="{color}" '
            f'style="stroke:var(--surface,#fff); display:none;" stroke-width="2"/>'
            if responsive else ""
        )
        + "</svg>"
    )
    if not responsive:
        return svg
    # Instant crosshair + tooltip: the nearest year's typical / cautious /
    # strong balances (the native <title> tooltips above stay as a fallback).
    def money(v):
        return ("-" if v < 0 else "") + f"${abs(v):,.0f}"

    data = json.dumps([
        [round(x_for(i), 1), round(y_for(row["median"]), 1), row["year"],
         (int(row["year"]) - int(birth_year)) if birth_year else None,
         money(row["median"]), money(row["p10"]), money(row["p90"])]
        for i, row in enumerate(band)
    ]).replace("</", "<\\/")
    names = ["Typical", "Cautious", "Strong"] if plain else ["Median", "10th pct", "90th pct"]
    return (
        f'<div class="fan-wrap" style="position:relative; max-width:{width}px;">{svg}'
        '<div class="fan-tip" role="status" style="display:none; position:absolute; pointer-events:none; z-index:5; '
        'padding:6px 10px; border-radius:8px; background:var(--surface,#fff); color:var(--ink,#111); '
        'border:1px solid var(--border,#ddd); box-shadow:var(--shadow-md,0 4px 12px rgba(0,0,0,.15)); '
        'font-size:12px; line-height:1.4; white-space:nowrap;"></div>'
        "<script>(function(){"
        "var w=document.currentScript.parentNode,svg=w.querySelector('svg'),tip=w.querySelector('.fan-tip'),"
        "cr=svg.querySelector('.fan-cross'),ring=svg.querySelector('.fan-ring'),"
        f"P={data},N={json.dumps(names)},VW={width};"
        "function hide(){tip.style.display='none';cr.style.display='none';ring.style.display='none';}"
        "function show(e){var r=svg.getBoundingClientRect(),t=e.touches&&e.touches[0]?e.touches[0]:e,"
        "vx=(t.clientX-r.left)/r.width*VW,b=0,bd=1e9,i,d;"
        "for(i=0;i<P.length;i++){d=Math.abs(P[i][0]-vx);if(d<bd){bd=d;b=i;}}"
        "var p=P[b],k=r.width/VW;"
        "cr.setAttribute('x1',p[0]);cr.setAttribute('x2',p[0]);cr.style.display='';"
        "ring.setAttribute('cx',p[0]);ring.setAttribute('cy',p[1]);ring.style.display='';"
        "tip.innerHTML='<div style=\"color:var(--ink-muted,#777)\">'+p[2]+(p[3]!==null?' &middot; age '+p[3]:'')+'</div>'"
        "+'<div><strong>'+N[0]+':</strong> '+p[4]+'</div>'"
        "+'<div style=\"color:var(--ink-muted,#777)\">'+N[1]+': '+p[5]+'</div>'"
        "+'<div style=\"color:var(--ink-muted,#777)\">'+N[2]+': '+p[6]+'</div>';"
        "tip.style.display='block';var tw=tip.offsetWidth,x=p[0]*k+12;"
        "if(x+tw>r.width)x=p[0]*k-tw-12;tip.style.left=Math.max(0,x)+'px';"
        "tip.style.top=Math.max(0,p[1]*k-tip.offsetHeight-10)+'px';}"
        "svg.addEventListener('mousemove',show);svg.addEventListener('mouseleave',hide);"
        "svg.addEventListener('touchstart',show,{passive:true});svg.addEventListener('touchmove',show,{passive:true});"
        "svg.addEventListener('touchend',hide);"
        "})();</script></div>"
    )
