"""Shared building blocks for the Drawdown Planning and Legacy Planning
tabs' year-by-year rows -- both walk the exact same
Taxable/Tax-deferred/Roth/Real-estate row shape (see
deterministic_drawdown_schedule and legacy_planning._run_conversion_schedule,
which build identically-keyed row dicts on purpose), so the bits that were
previously copy-pasted between source.webapp.pages.drawdown_planning and
source.webapp.pages.legacy_planning -- picking which rows are "visible" once
a Retirement year is set, describing a row's own withdrawal breakdown in
plain language, and the Withdrawn:/Ending: table columns -- live in exactly
one place instead of two (per the user's own request, "remove duplicates
from Legacy and Drawdown"). Each page still writes its own surrounding
copy and its own extra columns (Need vs. Conversion, etc.) -- only the parts
that were byte-for-byte identical moved here.
"""

from __future__ import annotations

from source.webapp.render_helpers.formatting import _money


def _visible_rows_by_year(rows: list[dict], retirement_year: int | None) -> list[dict]:
    """Filters `rows` down to year >= retirement_year, once a Retirement
    year assumption is set -- both tabs hide pre-retirement rows (nothing
    to spend before then) the same way, per the user's own request
    ("legacy planning should match retirement year"). Falls back to every
    row if that would hide the whole list (e.g. a Retirement year past the
    plan's own horizon), so a table or callout is never left with nothing
    to show."""
    if not rows:
        return []
    visible = rows if retirement_year is None else [r for r in rows if r["year"] >= retirement_year]
    return visible or rows


def _withdrawal_parts(r: dict) -> list[str]:
    """The list of "$X from <bucket>" fragments describing one row's own
    withdrawal, in the conventional Taxable/Tax-deferred/Roth/Real-estate
    order, with the Tax-deferred fragment calling out a mandatory RMD when
    there is one. Each caller still assembles its own sentence around this
    list (empty-state wording and any trailing clause differ intentionally
    between the two tabs)."""
    parts = []
    if r["drawn_taxable"] > 0.01:
        parts.append(f"{_money(r['drawn_taxable'])} from Taxable")
    if r["drawn_tax_deferred"] > 0.01:
        rmd_clause = f" (of which {_money(r['rmd'])} is a mandatory RMD)" if r["rmd"] > 0.01 else ""
        parts.append(f"{_money(r['drawn_tax_deferred'])} from Tax-deferred{rmd_clause}")
    elif r["rmd"] > 0.01:
        parts.append(f"{_money(r['rmd'])} from Tax-deferred (a mandatory RMD, even though nothing else is needed this year)")
    if r["drawn_roth"] > 0.01:
        parts.append(f"{_money(r['drawn_roth'])} from Roth")
    if r["drawn_real_estate"] > 0.01:
        parts.append(f"{_money(r['drawn_real_estate'])} from Real estate")
    return parts


def _withdrawn_ending_header_html() -> str:
    """The <th> cells shared by both tabs' year-by-year tables: what came
    out of each of the four pools this year, and what each pool ends the
    year holding. (Legacy Planning's table used to leave out "Ending: Real
    estate" -- an oversight fixed here now that both tables share one
    header, since real estate can matter to a legacy just like any other
    pool.)"""
    return (
        '<th class="num">Withdrawn: Taxable</th><th class="num">Withdrawn: Tax-deferred</th>'
        '<th class="num">Withdrawn: Roth</th><th class="num">Withdrawn: Real estate</th>'
        '<th class="num">Ending: Taxable</th><th class="num">Ending: Tax-deferred</th>'
        '<th class="num">Ending: Roth</th><th class="num">Ending: Real estate</th>'
    )


def _withdrawn_ending_cells_html(r: dict) -> str:
    """The <td> cells matching _withdrawn_ending_header_html, in the same
    order."""
    return (
        f'<td class="num">{_money(r["drawn_taxable"])}</td>'
        f'<td class="num">{_money(r["drawn_tax_deferred"])}</td>'
        f'<td class="num">{_money(r["drawn_roth"])}</td>'
        f'<td class="num">{_money(r["drawn_real_estate"])}</td>'
        f'<td class="num">{_money(r["taxable"])}</td>'
        f'<td class="num">{_money(r["tax_deferred"])}</td>'
        f'<td class="num">{_money(r["roth"])}</td>'
        f'<td class="num">{_money(r["real_estate"])}</td>'
    )
