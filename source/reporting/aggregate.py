"""Pulls together everything the Summary tab (and the Excel export) needs:
this program's own line items (source.common.db) plus the live linked
account/portfolio data (source.common.linked_data), rolled up into net
worth, total liabilities, real estate equity, and this year's expense
need. Kept as one shared module so the dashboard's Summary page and
source.reporting.excel_export compute the exact same numbers rather than
two slightly-different implementations drifting apart.
"""

from __future__ import annotations

from datetime import date

from source.common import db, linked_data

# A retirement/liquid asset row's tax treatment drives which of the
# Monte Carlo simulation's three pools it belongs to (tax_deferred /
# roth / taxable -- see source.reporting.monte_carlo's module
# docstring). Stored explicitly per row (assets.tax_treatment) once the
# user sets it on the Asset tab; a row that hasn't been touched yet
# ('' in storage) falls back to this category-based guess instead of
# silently being treated as $0/uncategorized, so every dollar included
# in the simulation (row.include_in_monte_carlo) always lands in
# exactly one pool. "401k" defaults to tax_deferred (the common case --
# most 401k/Traditional IRA balances), "liquid" defaults to taxable (a
# brokerage/savings balance)
# -- either default is a single click away from being corrected to Roth
# (or the other treatment) once tagged.
_VALID_TAX_TREATMENTS = {"tax_deferred", "roth", "taxable"}
_DEFAULT_TAX_TREATMENT_BY_CATEGORY = {"401k": "tax_deferred", "liquid": "taxable"}


def effective_tax_treatment(row: dict) -> str:
    """A retirement/liquid asset row's tax treatment for pool-splitting
    purposes: whatever's explicitly stored, or a category-based default
    for a row that's never been tagged. Always one of
    _VALID_TAX_TREATMENTS -- never blank -- so every caller can switch
    on the result without a None/"" case to handle."""
    explicit = (row.get("tax_treatment") or "").strip().lower()
    if explicit in _VALID_TAX_TREATMENTS:
        return explicit
    return _DEFAULT_TAX_TREATMENT_BY_CATEGORY.get((row.get("category") or "").strip().lower(), "taxable")


def real_estate_equity(row: dict, *, loan_balance: float | None = None) -> float:
    """Pass loan_balance explicitly to override the row's own stored
    figure -- effective_loan_balance below is what the Asset/Real Estate
    tabs and build_summary pass in for a row linked to a live mortgage/
    HELOC account, so equity reflects the current balance rather than
    whatever was last typed in.

    Ownership % applies to the loan as well as the value -- a
    partial-ownership property's equity is your share of (value minus
    loan), not your share of value minus the whole loan. current_value
    and loan_balance stay stored/displayed as the property's full
    figures (useful on their own, and what a linked Plaid mortgage
    account reports); ownership_pct is applied once, here, to turn that
    into your share."""
    share = (row.get("ownership_pct") or 100.0) / 100.0
    balance = row.get("loan_balance") or 0.0 if loan_balance is None else loan_balance
    return ((row.get("current_value") or 0.0) - balance) * share


def effective_loan_balance(row: dict, live_by_account_id: dict) -> float:
    """A real_estate row's loan balance for totals: the live Plaid balance
    when it's linked to a still-connected loan/HELOC account, otherwise
    the typed-in loan_balance. Always a positive amount owed, regardless
    of how Plaid signs the underlying account -- mirrors
    effective_balance's liability handling above."""
    account_id = row.get("linked_account_id")
    if not account_id or account_id not in live_by_account_id:
        return row.get("loan_balance") or 0.0
    return abs(live_by_account_id[account_id]["balance"] or 0.0)


def effective_balance(row: dict, live_by_account_id: dict) -> float:
    """A line item's balance for totals: its live Plaid balance when it's
    linked to a still-connected account (kept in sync automatically --
    see the Asset tab's "Linked account" column), otherwise whatever was
    typed in by hand. A linked liability row always comes back as a
    positive amount owed regardless of how Plaid signs the underlying
    account (credit/loan balances come back negative from
    linked_data.linkable_accounts, since that's the convention for the
    single already-netted "linked account balances" total below) --
    liability totals here are subtracted separately, so this one needs
    the plain magnitude."""
    account_id = row.get("linked_account_id")
    if not account_id or account_id not in live_by_account_id:
        return row["balance"] or 0.0
    value = live_by_account_id[account_id]["balance"] or 0.0
    return abs(value) if row["kind"] == "liability" else value


def category_subtotals(rows: list[dict], live_by_account_id: dict) -> list[tuple[str, float]]:
    """Per-category subtotals (effective balance -- live Plaid balance
    when linked, otherwise the typed-in figure) for a list of asset or
    liability line items, in first-seen order. Shared by the Asset tab's
    own per-category tables and build_summary()'s asset_category_subtotals
    below, so the Asset tab and the Summary tab can never show two
    different numbers for the same category."""
    order: list[str] = []
    totals: dict[str, float] = {}
    for row in rows:
        cat = (row["category"] or "").strip() or "Uncategorized"
        if cat not in totals:
            order.append(cat)
            totals[cat] = 0.0
        totals[cat] += effective_balance(row, live_by_account_id)
    return [(cat, totals[cat]) for cat in order]


def _pools_net_of_liabilities(
    tax_deferred_total: float, roth_total: float, taxable_total: float, liability_total: float,
) -> dict:
    """Nets liability_total out of the three retirement/liquid pools so
    their sum always equals net_liquid_asset (retirement_liquid_total -
    liability_total) -- what source.reporting.monte_carlo's three-pool
    engine actually starts each simulated path from. Liabilities come
    out of the taxable pool first (a margin loan or credit balance is
    conventionally against a taxable account, and taxable is already
    the "spend this first" pool in the withdrawal ordering -- see that
    module's docstring), then tax_deferred, then roth, same order
    withdrawals themselves follow -- so a liability larger than the
    taxable pool alone "spills over" the same way an oversized
    withdrawal would, rather than ever pushing a pool negative."""
    remaining = max(0.0, liability_total)
    taxable = taxable_total - remaining
    remaining = max(0.0, -taxable)
    taxable = max(0.0, taxable)
    tax_deferred = tax_deferred_total - remaining
    remaining = max(0.0, -tax_deferred)
    tax_deferred = max(0.0, tax_deferred)
    roth = max(0.0, roth_total - remaining)
    return {"tax_deferred": tax_deferred, "roth": roth, "taxable": taxable}


def capture_net_worth_snapshot(summary: dict | None = None) -> None:
    """Records today's net worth (and its component totals) into
    source.common.db.net_worth_snapshots, from a build_summary() dict --
    builds one itself if not given one. Called from source.webapp.
    dashboard.run() on every startup, and again after every successful
    Plaid sync (source.webapp.dashboard's /api/plaid-sync handler) --
    both idempotent for the same day (see db.record_snapshot's own
    docstring), so a person never has to do anything to start building a
    net-worth-over-time history; it just accumulates one point per day
    the app is opened or synced, from here on. Cheap: one extra INSERT
    after work build_summary() (or its caller) already did."""
    s = summary if summary is not None else build_summary()
    db.record_snapshot(
        net_worth=s["net_worth"],
        manual_asset_total=s["manual_asset_total"],
        linked_asset_total=s["linked_asset_total"],
        liability_total=s["liability_total"],
        real_estate_equity_total=s["real_estate_equity_total"],
        retirement_liquid_total=s["retirement_liquid_total"],
    )


def build_summary() -> dict:
    assets = db.list_line_items("assets")
    real_estate = db.list_line_items("real_estate")
    expenses = db.list_line_items("expenses")
    income = db.list_line_items("income")
    assumptions = db.get_assumptions()
    linked = linked_data.linked_totals()
    linked_status = linked_data.linked_data_status()
    live_by_account_id = {a["account_id"]: a for a in linked_data.linkable_accounts()}

    manual_asset_total = sum(effective_balance(a, live_by_account_id) for a in assets if a["kind"] == "asset")
    liability_total = sum(effective_balance(a, live_by_account_id) for a in assets if a["kind"] == "liability")
    re_equity_total = sum(
        real_estate_equity(r, loan_balance=effective_loan_balance(r, live_by_account_id)) for r in real_estate
    )

    # Monte Carlo's starting balance -- per-row, via each Asset row's own
    # "In Monte Carlo?" checkbox (assets.include_in_monte_carlo), rather
    # than a category-list match. Uses the same effective_balance() as
    # manual_asset_total (live Plaid balance when linked, otherwise the
    # typed-in figure) so a 401k or brokerage row linked on the Asset tab
    # is never stale here either.
    retirement_rows = [
        a for a in assets
        if a["kind"] == "asset" and a.get("include_in_monte_carlo")
    ]
    retirement_liquid_total = sum(effective_balance(a, live_by_account_id) for a in retirement_rows)

    # The same retirement/liquid total, split by tax treatment
    # (effective_tax_treatment above) into the three pools the Monte
    # Carlo simulation's withdrawal/RMD/tax engine tracks separately --
    # tax_deferred_total + roth_total + taxable_total always equals
    # retirement_liquid_total.
    tax_deferred_total = sum(
        effective_balance(a, live_by_account_id) for a in retirement_rows if effective_tax_treatment(a) == "tax_deferred"
    )
    roth_total = sum(
        effective_balance(a, live_by_account_id) for a in retirement_rows if effective_tax_treatment(a) == "roth"
    )
    taxable_total = sum(
        effective_balance(a, live_by_account_id) for a in retirement_rows if effective_tax_treatment(a) == "taxable"
    )

    # Any Plaid account a manual line item or real-estate row is now
    # linked to is already folded into manual_asset_total/liability_total/
    # re_equity_total above via its live balance -- excluding it here is
    # what keeps it from being counted a second time as a separate
    # "linked account balance".
    linked_account_ids = {a["linked_account_id"] for a in assets if a.get("linked_account_id")}
    linked_account_ids |= {r["linked_account_id"] for r in real_estate if r.get("linked_account_id")}
    linked_asset_total = sum(
        v["balance"] for account_id, v in live_by_account_id.items() if account_id not in linked_account_ids
    )

    net_worth = manual_asset_total + linked_asset_total - liability_total + re_equity_total

    # Same per-category breakdown the Asset tab's own top Summary table
    # shows (401k, Liquid, Insurance, whatever else exists) -- exposed
    # here so the Summary page can show the *actual* Asset-tab balances
    # instead of a single lumped "manual asset total" figure that didn't
    # match what the Asset tab itself displays.
    asset_only_rows = [a for a in assets if a["kind"] == "asset"]
    asset_category_subtotals = category_subtotals(asset_only_rows, live_by_account_id)
    net_liquid_asset = retirement_liquid_total - liability_total
    total_asset = net_liquid_asset + re_equity_total
    # sum(retirement_pools.values()) == net_liquid_asset, always -- see
    # _pools_net_of_liabilities. This is what the Monte Carlo tab passes
    # as run_simulation/run_historical_bootstrap_simulation/
    # run_historical_stress_test's `pools` argument.
    retirement_pools = _pools_net_of_liabilities(tax_deferred_total, roth_total, taxable_total, liability_total)
    # A 4th, optional pool: real estate equity for properties the user has
    # explicitly opted in to the simulation (real_estate.include_in_monte_carlo),
    # deliberately computed OUTSIDE _pools_net_of_liabilities -- a
    # property's own mortgage is already netted into its equity by
    # real_estate_equity()/effective_loan_balance() above, so it has
    # nothing to do with the Asset tab's separate liability_total. Always
    # present (0.0 when nothing is opted in) so every caller can treat
    # retirement_pools as a fixed four-key shape rather than special-
    # casing whether "real_estate" exists.
    retirement_pools["real_estate"] = sum(
        real_estate_equity(r, loan_balance=effective_loan_balance(r, live_by_account_id))
        for r in real_estate if r.get("include_in_monte_carlo")
    )

    this_year = int(assumptions.get("current_year") or date.today().year)
    from source.reporting.monte_carlo import annual_expense_need, annual_income_need

    # Which income rows net against the withdrawal need in the Monte Carlo /
    # historical stress test simulations -- per-row, via each Income row's
    # own "In simulation?" checkbox (income.include_in_monte_carlo). Every
    # income row has always counted; this defaults to on (see db.py's
    # migration) so nothing changes unless a row is explicitly unchecked.
    # `income` itself stays the full, unfiltered list for display purposes
    # (the Income tab shows every row regardless of this setting).
    income_for_simulation = [i for i in income if i.get("include_in_monte_carlo")]

    inflation_rate = float(assumptions.get("inflation_rate") or 0.0)
    # Inflation-aware: a Fixed/Variable expense row (or a Rental/Social
    # Security income row) with inflates set grows from its own
    # base_year first -- see monte_carlo._effective_line_item_amount.
    # Same numbers the Monte Carlo tab's own first simulated year uses,
    # so this figure and that tab can never drift apart.
    this_year_need = annual_expense_need(expenses, this_year, inflation_rate)
    this_year_income = annual_income_need(income_for_simulation, this_year, inflation_rate)
    this_year_net_need = this_year_need - this_year_income

    return {
        "assets": assets,
        "real_estate": real_estate,
        "expenses": expenses,
        "income": income,
        "income_for_simulation": income_for_simulation,
        "assumptions": assumptions,
        "linked_totals": linked,
        "linked_status": linked_status,
        "manual_asset_total": manual_asset_total,
        "linked_asset_total": linked_asset_total,
        "liability_total": liability_total,
        "real_estate_equity_total": re_equity_total,
        "net_worth": net_worth,
        "retirement_liquid_total": retirement_liquid_total,
        "tax_deferred_total": tax_deferred_total,
        "roth_total": roth_total,
        "taxable_total": taxable_total,
        "asset_category_subtotals": asset_category_subtotals,
        "net_liquid_asset": net_liquid_asset,
        "retirement_pools": retirement_pools,
        "total_asset": total_asset,
        "this_year": this_year,
        "this_year_expense_need": this_year_need,
        "this_year_income": this_year_income,
        "this_year_net_need": this_year_net_need,
        "import_status": {
            "last_import_at": db.get_meta("last_import_at"),
            "last_import_source": db.get_meta("last_import_source"),
        },
    }
