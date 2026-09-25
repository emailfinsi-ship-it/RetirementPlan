"""The Linked Positions tab: individual brokerage/retirement holdings
pulled in via Plaid, grouped and charted by sector and by industry."""

from __future__ import annotations

import html

from source.common import linked_data
from source.webapp.render_helpers import (
    _bar_chart_html,
    _donut_chart_html,
    _grouped_slices,
    _money,
    _shell,
    _sync_now_button_html,
)


def _render_linked_positions_page() -> str:
    linked_positions = linked_data.read_linked_portfolio_positions()

    # Plaid's own "security_type" already folds a lot of distinct real-world
    # holdings (REITs, private funds, employee stock plans, etc.) into one
    # generic "Other" value -- every such row shares that identical string,
    # so simply raising _grouped_slices' max_slices can't split them apart
    # (it groups by exact key equality). Instead, for an "Other"-typed
    # holding that already has an Industry tag (from the classification
    # feature above), derive a more specific "Other: <industry>" label and
    # group/filter by that instead, reusing the existing Industry tags
    # rather than inventing a new sub-categorization mechanism. A
    # non-"Other" type, or an "Other" with no industry tag yet, is
    # unaffected.
    def _type_chart_label(p):
        security_type = p["security_type"] or ""
        if security_type.strip().lower() == "other":
            industry = (p["industry"] or "").strip()
            if industry:
                return f"Other: {industry}"
        return security_type

    for p in linked_positions:
        p["type_chart_label"] = _type_chart_label(p)
        # A manual sector override (set via the "Set sector" bulk-classify
        # bar below) wins over the derived one -- the usual case for a
        # mutual fund/ETF/target-date fund, which never gets an `industry`
        # to derive a sector from in the first place.
        p["sector"] = p["manual_sector"] or _sector_for_industry(p["industry"])

    type_chart_html = _donut_chart_html(
        "Positions by type (market value)",
        _grouped_slices(linked_positions, key="type_chart_label", value_key="market_value", max_slices=10),
        dim="type",
    )
    institution_chart_html = _donut_chart_html(
        "Positions by institution (market value)",
        _grouped_slices(linked_positions, key="institution", value_key="market_value"),
        dim="institution",
    )
    # Broad roll-up of the fine-grained industry chart below (via
    # _sector_for_industry/_SECTOR_BY_INDUSTRY above) -- a bar chart
    # rather than a donut since even at the sector level there are more
    # than the ~6-7 slices a donut stays legible past, but bounded to
    # Yahoo Finance's ~11 sectors (plus "Other"/"Unknown"), so unlike the
    # industry chart it needs no uncapped/folding decision at all.
    sector_chart_html = _bar_chart_html(
        "Positions by sector (market value)",
        _grouped_slices(linked_positions, key="sector", value_key="market_value", max_slices=None),
        dim="sector",
    )
    # A bar, not a donut -- industry tends to accumulate far more distinct
    # values than type/institution (especially once positions are
    # manually tagged), and a pie/donut stops being legible well before
    # that (dataviz skill: ~6-7 slices). Each bar is already directly
    # labeled, so it stays legible well past that count -- max_slices=None
    # shows every distinct industry as its own bar rather than folding a
    # long tail into one "Other" bucket, which used to hide real,
    # specific industries (e.g. a single Tesla holding's "Auto
    # Manufacturers") behind a vague grouped label just because that
    # industry's total market value wasn't in the top dozen. The sector
    # chart above is the coarser alternative for anyone who'd rather
    # scan ~11 broad buckets than a long, fine-grained industry list.
    industry_chart_html = _bar_chart_html(
        "Positions by industry (market value)",
        _grouped_slices(linked_positions, key="industry", value_key="market_value", max_slices=None),
        dim="industry",
    )

    # data-type/data-institution/data-industry/data-sector/data-market-value
    # on each row let the shared applyPositionFilters() JS (see
    # PAGE_SHELL) show/hide rows and recompute the visible total when a
    # chart slice above is clicked -- the values here are the exact same
    # strings _grouped_slices grouped by (including its "Unknown"
    # fallback for a blank industry), so a slice's data-values always
    # matches these attributes.
    def _industry_attr(p):
        return (p["industry"] or "").strip() or "Unknown"

    # Every industry already in use (auto-classified or manually set),
    # offered as a <datalist> on the bulk-classify input below so a
    # second Cash/REIT/fund position gets tagged with the exact same
    # label as the first instead of a near-duplicate ("Cash" vs "cash").
    known_industries = sorted({p["industry"].strip() for p in linked_positions if p["industry"]})
    industry_datalist_html = "".join(f"<option>{html.escape(i)}</option>" for i in known_industries)

    # Yahoo Finance's own ~11 sectors, plus any custom sector already
    # manually set (e.g. "Diversified") -- offered on the "Set sector"
    # bulk-classify input below the same way known_industries is, so a
    # second fund gets tagged with the exact same label as the first
    # rather than a near-duplicate ("Diversified" vs "diversified").
    known_sectors = sorted(set(_SECTOR_INDUSTRIES) | {p["manual_sector"].strip() for p in linked_positions if p["manual_sector"]})
    sector_datalist_html = "".join(f"<option>{html.escape(s)}</option>" for s in known_sectors)

    linked_positions_html = "".join(
        f'<tr data-type="{html.escape(p["type_chart_label"])}" data-institution="{html.escape(p["institution"])}" '
        f'data-industry="{html.escape(_industry_attr(p))}" data-sector="{html.escape(p["sector"])}" '
        f'data-market-value="{p["market_value"] or 0}">'
        f'<td class="check-col"><input type="checkbox" class="position-check" '
        f'data-security-id="{html.escape(p["security_id"] or "")}" data-ticker="{html.escape(p["ticker"])}"></td>'
        f'<td>{html.escape(p["institution"])}</td><td>{html.escape(p["account"])}</td>'
        f'<td>{html.escape(p["security_name"])}</td><td>{html.escape(p["ticker"])}</td>'
        f'<td>{html.escape(p["type_chart_label"])}</td><td>{html.escape(p["industry"] or "Unclassified")}</td>'
        f'<td class="num">{_money(p["market_value"])}</td>'
        f'<td>{html.escape(p["position_as_of"])}</td></tr>'
        for p in linked_positions
    ) or '<tr><td colspan="9" class="muted">No linked portfolio positions yet -- connect a Plaid investments account on Setup.</td></tr>'
    market_value_total = sum(p["market_value"] or 0 for p in linked_positions)

    body = f"""
<h2 style="margin-top:0">Linked portfolio positions (live, read-only)</h2>
<p class="muted">Investment holdings pulled directly from Plaid for accounts that requested the "investments" product, each time this page loads. Industry is auto-classified for equities from Yahoo Finance during sync ("Sync now" below) -- Plaid has no industry data, so a cash position, ETF, mutual fund, or anything not yet classified shows as "Unclassified"/"Unknown"; check the box next to one or more rows below and use the bar that appears to tag them yourself. Sector normally rolls each industry up to one of Yahoo Finance's ~11 broad sectors, for a coarser view than the full industry list -- but a mutual fund, ETF, or target-date fund never gets an industry in the first place (it holds many at once), so it stays in "Unknown" forever unless you tag its sector directly with the "Set sector" bar. Click a slice, bar, or legend entry in any chart below to filter the list to just that type, institution, sector, or industry; click it again (or "Clear all") to reset. See <a href="/portfolio-positions.html">portfolio-positions.html</a> for the standalone export.</p>
{_sync_now_button_html()}
<div class="group-section">
{type_chart_html}
{institution_chart_html}
</div>
<div class="group-section">
{sector_chart_html}
</div>
<div class="group-section">
{industry_chart_html}
</div>
<div id="positions-filter-bar" class="filter-bar"></div>
<div id="industry-bulk-bar" class="industry-bulk-bar">
  <span class="bulk-count">0 selected</span>
  <input type="text" id="industry-bulk-input" list="industry-options" placeholder="e.g. Cash, REIT, International Equity" disabled>
  <datalist id="industry-options">{industry_datalist_html}</datalist>
  <button type="button" onclick="classifySelectedIndustry()" disabled>Set industry</button>
  <button type="button" onclick="clearSelectedIndustry()" disabled>Clear industry</button>
  <button type="button" onclick="clearPositionSelection()" disabled>Clear selection</button>
</div>
<div id="sector-bulk-bar" class="industry-bulk-bar">
  <span class="bulk-count">0 selected</span>
  <input type="text" id="sector-bulk-input" list="sector-options" placeholder="e.g. Diversified, Fixed Income" disabled>
  <datalist id="sector-options">{sector_datalist_html}</datalist>
  <button type="button" onclick="classifySelectedSector()" disabled>Set sector</button>
  <button type="button" onclick="clearSelectedSector()" disabled>Clear sector</button>
  <button type="button" onclick="clearPositionSelection()" disabled>Clear selection</button>
</div>
<table class="sortable" id="linked-positions-table">
<thead><tr><th class="check-col"><input type="checkbox" class="position-select-all"></th><th>Institution</th><th>Account</th><th>Security</th><th>Ticker</th><th>Type</th><th>Industry</th><th class="num">Market Value</th><th>As Of</th></tr></thead>
<tbody>{linked_positions_html}</tbody>
<tfoot><tr><td colspan="7">Total</td><td class="num" id="linked-positions-total">{_money(market_value_total)}</td><td></td></tr></tfoot>
</table>
<p class="muted">Account balances (and their own "by institution"/"by account type" charts) are on the <a href="/linked-accounts.html">Linked Accounts</a> tab.</p>
"""
    return _shell(title="Linked Positions", active="linked-positions.html", body=body)

def _sector_for_industry(industry: str | None) -> str:
    """Broad sector for a fine-grained industry string, via
    _SECTOR_BY_INDUSTRY above -- "Unknown" for a blank/unclassified
    industry (matches the industry chart's own fallback), "Other" for a
    non-blank industry this table doesn't recognize (most often a
    manually typed-in tag), case-insensitive so a manually retyped
    "software - application" still lands in Technology."""
    key = (industry or "").strip()
    if not key:
        return "Unknown"
    return _SECTOR_BY_INDUSTRY.get(key.lower(), "Other")

_SECTOR_INDUSTRIES: dict[str, tuple[str, ...]] = {
    "Technology": (
        "Information Technology Services", "Software - Application", "Software - Infrastructure",
        "Communication Equipment", "Computer Hardware", "Consumer Electronics", "Electronic Components",
        "Electronics & Computer Distribution", "Scientific & Technical Instruments",
        "Semiconductor Equipment & Materials", "Semiconductors", "Solar",
    ),
    "Communication Services": (
        "Advertising Agencies", "Broadcasting", "Electronic Gaming & Multimedia", "Entertainment",
        "Internet Content & Information", "Publishing", "Telecom Services",
    ),
    "Healthcare": (
        "Biotechnology", "Drug Manufacturers - General", "Drug Manufacturers - Specialty & Generic",
        "Health Information Services", "Healthcare Plans", "Medical Care Facilities", "Medical Devices",
        "Medical Distribution", "Medical Instruments & Supplies", "Diagnostics & Research",
        "Pharmaceutical Retailers",
    ),
    "Financial Services": (
        "Asset Management", "Banks - Diversified", "Banks - Regional", "Capital Markets", "Credit Services",
        "Financial Conglomerates", "Financial Data & Stock Exchanges", "Insurance - Diversified",
        "Insurance - Life", "Insurance - Property & Casualty", "Insurance - Reinsurance",
        "Insurance - Specialty", "Insurance Brokers", "Mortgage Finance", "Shell Companies",
    ),
    "Consumer Cyclical": (
        "Apparel Manufacturing", "Apparel Retail", "Auto & Truck Dealerships", "Auto Manufacturers",
        "Auto Parts", "Department Stores", "Footwear & Accessories", "Furnishings, Fixtures & Appliances",
        "Gambling", "Home Improvement Retail", "Internet Retail", "Leisure", "Lodging", "Luxury Goods",
        "Packaging & Containers", "Personal Services", "Recreational Vehicles", "Residential Construction",
        "Resorts & Casinos", "Restaurants", "Specialty Retail", "Travel Services",
    ),
    "Consumer Defensive": (
        "Beverages - Brewers", "Beverages - Non-Alcoholic", "Beverages - Wineries & Distilleries",
        "Confectioners", "Discount Stores", "Education & Training Services", "Farm Products",
        "Food Distribution", "Grocery Stores", "Household & Personal Products", "Packaged Foods", "Tobacco",
    ),
    "Industrials": (
        "Aerospace & Defense", "Airlines", "Airports & Air Services", "Building Products & Equipment",
        "Business Equipment & Supplies", "Conglomerates", "Consulting Services",
        "Electrical Equipment & Parts", "Engineering & Construction", "Farm & Heavy Construction Machinery",
        "Industrial Distribution", "Infrastructure Operations", "Integrated Freight & Logistics",
        "Marine Shipping", "Metal Fabrication", "Pollution & Treatment Controls", "Railroads",
        "Rental & Leasing Services", "Security & Protection Services", "Specialty Business Services",
        "Specialty Industrial Machinery", "Staffing & Employment Services", "Tools & Accessories",
        "Trucking", "Waste Management",
    ),
    "Energy": (
        "Oil & Gas Drilling", "Oil & Gas E&P", "Oil & Gas Equipment & Services", "Oil & Gas Integrated",
        "Oil & Gas Midstream", "Oil & Gas Refining & Marketing", "Thermal Coal", "Uranium",
    ),
    "Utilities": (
        "Utilities - Diversified", "Utilities - Independent Power Producers", "Utilities - Regulated Electric",
        "Utilities - Regulated Gas", "Utilities - Regulated Water", "Utilities - Renewable",
    ),
    "Real Estate": (
        "REIT - Diversified", "REIT - Healthcare Facilities", "REIT - Hotel & Motel", "REIT - Industrial",
        "REIT - Mortgage", "REIT - Office", "REIT - Residential", "REIT - Retail", "REIT - Specialty",
        "Real Estate - Development", "Real Estate - Diversified", "Real Estate Services",
    ),
    "Basic Materials": (
        "Agricultural Inputs", "Aluminum", "Building Materials", "Chemicals", "Coking Coal", "Copper",
        "Gold", "Industrial Materials", "Lumber & Wood Production", "Other Industrial Metals & Mining",
        "Other Precious Metals & Mining", "Paper & Paper Products", "Silver", "Specialty Chemicals", "Steel",
    ),
}

_SECTOR_BY_INDUSTRY: dict[str, str] = {
    industry.lower(): sector for sector, industries in _SECTOR_INDUSTRIES.items() for industry in industries
}
