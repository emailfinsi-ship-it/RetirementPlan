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


def effective_tax_treatment(row: dict, live_by_account_id: dict | None = None) -> str:
    """A retirement/liquid asset row's tax treatment for pool-splitting
    purposes: whatever's explicitly stored; failing that, whatever a
    linked Plaid account's own subtype implies (source.common.
    linked_data.detected_tax_treatment -- Roth/IRA/401k are reported by
    Plaid itself, so a row linked to one of those never has to fall back
    to a blind category guess); failing that, a category-based default
    for a row that's never been tagged and isn't linked to a recognized
    subtype. Always one of _VALID_TAX_TREATMENTS -- never blank -- so
    every caller can switch on the result without a None/"" case to
    handle.

    `live_by_account_id` is optional (and keyed by account_id, e.g.
    source.common.linked_data.linkable_accounts() reduced to a dict) --
    omitted entirely, this behaves exactly as it always has (explicit
    stored value, else the category default), which is what every
    existing caller/test that doesn't pass it still gets."""
    explicit = (row.get("tax_treatment") or "").strip().lower()
    if explicit in _VALID_TAX_TREATMENTS:
        return explicit
    if live_by_account_id:
        linked_account_id = row.get("linked_account_id")
        live = live_by_account_id.get(linked_account_id) if linked_account_id else None
        detected = (live or {}).get("detected_tax_treatment")
        if detected in _VALID_TAX_TREATMENTS:
            return detected
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


def real_estate_value(row: dict) -> float:
    """Your share of a property's market value (current_value x ownership
    %), before any loan -- the "Real estate value" the Asset tab charts over
    time, as opposed to real_estate_equity above (value less loan)."""
    share = (row.get("ownership_pct") or 100.0) / 100.0
    return (row.get("current_value") or 0.0) * share


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


def row_bucket_amounts(row: dict, live_by_account_id: dict, splits_by_account: dict) -> list[tuple[str, float]]:
    """One retirement/liquid Asset row's own (tax bucket, amount) pairs --
    normally just the single pair effective_tax_treatment/effective_balance
    above already give (one row, one bucket, its whole balance), but when
    this row is linked to a Plaid account with 1+ manual splits recorded
    (source.common.db "account_tax_splits" -- see the Drawdown Planning
    tab's own "Split a linked account across tax buckets" card), that
    single lumped pair is replaced by each split's own (bucket, amount)
    pair instead. Per the user's own request ("for fidelity can i
    segregate the sources manually" / "give me option to break up one sum
    to parts") -- a real 401k can hold pre-tax, Roth, and after-tax money
    all in the same account, and this is what lets that show up correctly
    in retirement_pools (and therefore the Monte Carlo simulation itself,
    not just the Drawdown Planning tab's own snapshot) once the row is
    linked to that account, exactly the same as an unlinked account's own
    splits already did for drawdown_pools alone."""
    linked_account_id = row.get("linked_account_id")
    if linked_account_id and linked_account_id in splits_by_account:
        return [
            (s["tax_treatment"] if s["tax_treatment"] in _VALID_TAX_TREATMENTS else "taxable", s["amount"] or 0.0)
            for s in splits_by_account[linked_account_id]
        ]
    return [(effective_tax_treatment(row, live_by_account_id), effective_balance(row, live_by_account_id))]


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


def _owner_key(owner) -> str:
    """The bucket an account's Owner value falls into for the per-owner
    Tax-deferred totals below: 'self', 'spouse', or 'unassigned' (blank,
    or anything unrecognized)."""
    return owner if owner in ("self", "spouse") else "unassigned"


def _spouse_share(by_owner: dict) -> float:
    """The fraction (0..1) of a by-owner Tax-deferred breakdown that
    belongs to the spouse -- what the engine's derived
    `spouse_tax_deferred_share` assumption carries (see
    monte_carlo.assumptions._resolve_spouse_tax_deferred_share). Computed
    against the GROSS Tax-deferred total (before _pools_net_of_liabilities
    nets any liability out of it), which only differs from the netted pool
    in the rare case a liability exceeds the whole Taxable pool; the engine
    applies this fraction to whatever the actual starting pool is. 0.0
    whenever the spouse owns none of it (including a zero total), which
    keeps every engine on its original single-owner path."""
    total = sum(by_owner.values())
    if total <= 0:
        return 0.0
    return min(1.0, max(0.0, by_owner.get("spouse", 0.0) / total))


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
        real_estate_value_total=s.get("real_estate_value_total"),
    )
    capture_asset_balance_snapshots(s)


def capture_asset_balance_snapshots(summary: dict | None = None) -> None:
    """Records today's effective balance for every Asset-tab asset row (not
    liabilities) into source.common.db.asset_balance_snapshots -- called
    from capture_net_worth_snapshot, so every place that already captures
    a net-worth point (startup, after a Plaid sync, the once-a-day
    background check) also captures each asset's own point, keeping the
    two series on the same days. Idempotent per row per day."""
    s = summary if summary is not None else build_summary()
    live_by_account_id = {a["account_id"]: a for a in linked_data.linkable_accounts()}
    for a in s["assets"]:
        if a.get("kind") == "liability":
            continue
        db.record_asset_balance_snapshot(
            asset_id=a["id"], balance=effective_balance(a, live_by_account_id),
            name=a.get("name") or "", category=a.get("category") or "",
        )


def asset_balance_history(assets: list[dict]) -> list[dict]:
    """Each current Asset-tab asset row's balance-over-time, for the net-
    worth chart's "plot individual assets" picker: [{"id", "name",
    "category", "points": [(date, balance), ...]}], largest current
    balance first. A row's own daily snapshots are authoritative; days
    before those began are backfilled from the linked Plaid account's own
    history (account_balance_snapshots, recorded for linked investment
    accounts) when the row is linked to one -- so a long-linked 401(k)
    already has a trend the first day this feature exists."""
    own: dict[int, dict[str, float]] = {}
    for row in db.list_asset_balance_snapshots():
        own.setdefault(row["asset_id"], {})[row["snapshot_date"]] = row["balance"]
    by_account: dict[str, dict[str, float]] = {}
    for row in db.list_account_balance_snapshots():
        by_account.setdefault(row["account_id"], {})[row["snapshot_date"]] = row["balance"]
    result = []
    for a in assets:
        if a.get("kind") == "liability":
            continue
        merged: dict[str, float] = dict(by_account.get(a.get("linked_account_id") or "", {}))
        merged.update(own.get(a["id"], {}))
        if not merged:
            continue
        points = sorted(merged.items())
        result.append({
            "id": a["id"], "name": a.get("name") or "", "category": a.get("category") or "", "points": points,
        })
    result.sort(key=lambda r: r["points"][-1][1], reverse=True)
    return result


def capture_investment_account_balances(accounts: list[dict] | None = None) -> None:
    """Records today's balance for every linked investment account into
    source.common.db.account_balance_snapshots, one row per account --
    accounts defaults to linked_data.linkable_accounts() (pass an
    explicit list only from tests). Filters to type == "investment" (the
    raw Plaid account type; linkable_accounts() exposes it precisely so
    this function doesn't have to re-derive it from subtype/category
    guessing) since a checking or 401k balance isn't what "investment
    account balance" means here.

    Called from the same two places as capture_net_worth_snapshot above,
    right alongside it: source.webapp.dashboard.run() on every startup,
    and again after every successful Plaid sync -- both idempotent for
    the same day per account (see db.record_account_balance_snapshot's
    own docstring), so the Linked Accounts tab's balance-over-time chart
    accumulates one point per account per day the app is opened or
    synced, from here on, with no setup required."""
    accts = accounts if accounts is not None else linked_data.linkable_accounts()
    for a in accts:
        if a.get("type") != "investment":
            continue
        db.record_account_balance_snapshot(account_id=a["account_id"], balance=a["balance"])


def capture_daily_snapshots_if_new_day(last_captured_date: str | None, today: str | None = None) -> str:
    """The once-a-day capture the dashboard's background timer drives
    (source.webapp.dashboard._daily_snapshot_loop): if `today` (default:
    the local date) differs from `last_captured_date`, records today's
    net-worth snapshot and today's per-account investment balances (the
    same two captures the dashboard already does at startup and after a
    sync), and returns today's date string; if it's still the same day,
    does nothing and returns `last_captured_date` unchanged. Lets net
    worth history accumulate one point per day for as long as the
    dashboard process is running, even on days nobody opens it -- the
    startup/sync captures alone only ever fired on days the app was
    actually opened or synced. Any exception from a capture propagates,
    so the caller doesn't mark the day as captured and tries again on its
    next tick."""
    today = today or date.today().isoformat()
    if today == last_captured_date:
        return today
    capture_net_worth_snapshot()
    capture_investment_account_balances()
    return today


def _rental_taxable_schedule(real_estate: list[dict]) -> str:
    """JSON [[loan_end_year | null, weight], ...] for the Real Estate rows
    that bring in rent (weight = the row's annual income). When no row has
    a loan end year -- or no row has any income and none has a loan end
    year -- returns "" (no shelter modeled). If properties have loan end
    years but none of them has an Annual Income typed in, each row with a
    loan end year counts equally."""
    import json

    if not any(r.get("loan_end_year") for r in real_estate):
        return ""
    entries = [
        [r.get("loan_end_year"), float(r.get("annual_income") or 0.0)]
        for r in real_estate if (r.get("annual_income") or 0) > 0
    ]
    if not entries:
        entries = [[r["loan_end_year"], 1.0] for r in real_estate if r.get("loan_end_year")]
    return json.dumps(entries)


def build_summary() -> dict:
    assets = db.list_line_items("assets")
    real_estate = db.list_line_items("real_estate")
    expenses = db.list_line_items("expenses")
    income = db.list_line_items("income")
    assumptions = db.get_assumptions()
    linked = linked_data.linked_totals()
    linked_status = linked_data.linked_data_status()
    live_by_account_id = {a["account_id"]: a for a in linked_data.linkable_accounts()}

    # Manual per-account splits (source.common.db "account_tax_splits" --
    # see the Drawdown Planning tab's own "Split a linked account across
    # tax buckets" card): a single Plaid investment account's subtype is
    # one bucket for the WHOLE balance (see detected_tax_treatment
    # above), but a real 401k can hold pre-tax, Roth, and after-tax money
    # all at once (an institution's own "Sources" breakdown, e.g.
    # Fidelity's Base Pay Traditional/Roth In-Plan Conversion/After-tax/
    # ...) -- per the user's own request ("for fidelity can i segregate
    # the sources manually" / "give me option to break up one sum to
    # parts"), an account with 1+ splits recorded has its lump balance
    # replaced below by those named, individually-bucketed pieces
    # instead, whether that account is still unlinked or is now linked to
    # a manual Asset-tab row (row_bucket_amounts above handles the
    # latter -- see retirement_liquid_total/tax_deferred_total/etc.
    # below). Computed once, up front, since both retirement_rows'
    # own totals and the Drawdown-only unlinked-account totals further
    # down both need it. Grouped by account_id so every split for one
    # account is handled together.
    splits_by_account: dict[str, list[dict]] = {}
    for split in db.list_line_items("account_tax_splits"):
        splits_by_account.setdefault(split["account_id"], []).append(split)

    manual_asset_total = sum(effective_balance(a, live_by_account_id) for a in assets if a["kind"] == "asset")
    liability_total = sum(effective_balance(a, live_by_account_id) for a in assets if a["kind"] == "liability")
    re_equity_total = sum(
        real_estate_equity(r, loan_balance=effective_loan_balance(r, live_by_account_id)) for r in real_estate
    )
    re_value_total = sum(real_estate_value(r) for r in real_estate)

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
    retirement_row_buckets = {
        a["id"]: row_bucket_amounts(a, live_by_account_id, splits_by_account) for a in retirement_rows
    }
    retirement_liquid_total = sum(
        amount for buckets in retirement_row_buckets.values() for _, amount in buckets
    )

    # The same retirement/liquid total, split by tax treatment (normally
    # effective_tax_treatment, unless this row's own linked account has
    # been split -- see row_bucket_amounts) into the three pools the
    # Monte Carlo simulation's withdrawal/RMD/tax engine tracks
    # separately -- tax_deferred_total + roth_total + taxable_total
    # always equals retirement_liquid_total.
    tax_deferred_total = sum(
        amount for buckets in retirement_row_buckets.values() for bucket, amount in buckets if bucket == "tax_deferred"
    )
    roth_total = sum(
        amount for buckets in retirement_row_buckets.values() for bucket, amount in buckets if bucket == "roth"
    )
    taxable_total = sum(
        amount for buckets in retirement_row_buckets.values() for bucket, amount in buckets if bucket == "taxable"
    )

    # The Tax-deferred total split by account OWNER (assets.owner) -- the
    # input to the per-person RMD modeling. A row's whole balance (or
    # each of its manual splits' pieces) belongs to that row's owner;
    # Unassigned money is reported separately here so the UI can flag it,
    # even though the engine models it under the plan owner (see
    # source.common.db.owners).
    tax_deferred_by_owner = {"self": 0.0, "spouse": 0.0, "unassigned": 0.0}
    for a in retirement_rows:
        key = _owner_key(a.get("owner"))
        for bucket, amount in retirement_row_buckets[a["id"]]:
            if bucket == "tax_deferred":
                tax_deferred_by_owner[key] += amount

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

    # Drawdown Planning tab support: "resources by tax criteria" for
    # every dollar this program knows about, not just the manual
    # Asset-tab rows checked "In Monte Carlo?" that retirement_pools
    # above is built from. A live Plaid investment account (Fidelity's
    # BrokerageLink, a 401(k), a Roth IRA, ...) that's never been added
    # as its own Asset-tab row -- and so was never part of
    # retirement_rows/retirement_pools at all, only ever counted once
    # inside the single lumped linked_asset_total figure above -- is
    # surfaced here on its own, bucketed by its own Plaid subtype
    # (source.common.linked_data.detected_tax_treatment), so Roth/IRA/
    # 401k money at an institution like Fidelity shows up correctly
    # without requiring the extra manual step of linking it to an
    # Asset-tab row first. Excludes anything in linked_account_ids (an
    # account already linked to a manual asset/real-estate row) -- that
    # money is already in retirement_pools/re_equity_total via its own
    # row, so including it again here would double-count it, the exact
    # same reasoning linked_asset_total above already follows.
    unlinked_investment_accounts = [
        v for account_id, v in live_by_account_id.items()
        if account_id not in linked_account_ids and (v.get("type") or "").strip().lower() == "investment"
    ]
    # Every live investment account, linked to an Asset-tab row or not --
    # what the Drawdown Planning tab's own "Split a linked account across
    # tax buckets" card offers in its account picker, so a 401k that's
    # already on the Asset tab (row_bucket_amounts above handles applying
    # its splits) can still be split, not just one that isn't yet.
    splittable_investment_accounts = [
        v for v in live_by_account_id.values() if (v.get("type") or "").strip().lower() == "investment"
    ]
    split_unlinked_account_ids = {acc["account_id"] for acc in unlinked_investment_accounts} & splits_by_account.keys()

    # A quick reconciliation note per split account (whether it's linked
    # to an Asset-tab row or not) -- the splits are manually typed, so
    # they can drift from the account's own live balance (new
    # contributions since the split was last set, a typo, ...) --
    # surfaced so the Drawdown Planning tab can flag it rather than
    # silently using a total that no longer matches Plaid's own figure.
    account_split_mismatches = []
    for account_id in splits_by_account.keys() & live_by_account_id.keys():
        acc = live_by_account_id[account_id]
        split_total = sum(s["amount"] or 0.0 for s in splits_by_account[account_id])
        if abs(split_total - acc["balance"]) > 0.01:
            account_split_mismatches.append({
                "account_id": account_id,
                "label": acc["label"],
                "institution": acc["institution"],
                "live_balance": acc["balance"],
                "split_total": split_total,
            })

    # Owner of each live account that ISN'T tied to an Asset-tab row
    # (source.common.db.owners) -- the Asset row's own owner column
    # covers the linked case.
    account_owners = db.get_account_owners()
    drawdown_tax_deferred_by_owner = dict(tax_deferred_by_owner)

    drawdown_unlinked_totals = {"tax_deferred": 0.0, "roth": 0.0, "taxable": 0.0}
    for acc in unlinked_investment_accounts:
        owner_key = _owner_key(account_owners.get(acc["account_id"]))
        if acc["account_id"] in split_unlinked_account_ids:
            for split in splits_by_account[acc["account_id"]]:
                bucket = split["tax_treatment"] if split["tax_treatment"] in _VALID_TAX_TREATMENTS else "taxable"
                drawdown_unlinked_totals[bucket] = drawdown_unlinked_totals.get(bucket, 0.0) + (split["amount"] or 0.0)
                if bucket == "tax_deferred":
                    drawdown_tax_deferred_by_owner[owner_key] += split["amount"] or 0.0
        else:
            bucket = acc.get("detected_tax_treatment") or "taxable"
            drawdown_unlinked_totals[bucket] = drawdown_unlinked_totals.get(bucket, 0.0) + acc["balance"]
            if bucket == "tax_deferred":
                drawdown_tax_deferred_by_owner[owner_key] += acc["balance"]

    # The starting pools for the Drawdown Planning tab's year-by-year
    # projection, and the numbers behind its snapshot tiles/chart: the
    # same tax_deferred/roth/taxable/real_estate shape as
    # retirement_pools (already net of liabilities -- see
    # _pools_net_of_liabilities), plus the unlinked live investment
    # accounts just bucketed above layered on top of each of the first
    # three pools. real_estate is carried over unchanged (an unlinked
    # investment account is never real estate).
    drawdown_pools = dict(retirement_pools)
    drawdown_pools["tax_deferred"] += drawdown_unlinked_totals["tax_deferred"]
    drawdown_pools["roth"] += drawdown_unlinked_totals["roth"]
    drawdown_pools["taxable"] += drawdown_unlinked_totals["taxable"]

    # Per-source breakdown for the Drawdown Planning tab's own table --
    # every manual retirement row (linked or not), every unlinked live
    # investment account, and every opted-in real-estate row, each
    # tagged with its own tax bucket and where that classification came
    # from, so the user can see exactly what's feeding each pool above
    # rather than only the totals.
    drawdown_sources = []
    for a in retirement_rows:
        linked_account_id = a.get("linked_account_id")
        live = live_by_account_id.get(linked_account_id) if linked_account_id else None
        row_name = a.get("name") or "(unnamed asset)"
        if linked_account_id and linked_account_id in splits_by_account:
            # This row's own linked account has been split -- see
            # row_bucket_amounts, which already folded these into
            # tax_deferred_total/roth_total/taxable_total above -- so its
            # single lumped source row is replaced by each split's own
            # named piece here too, same as an unlinked account's splits
            # already did below.
            for split in splits_by_account[linked_account_id]:
                drawdown_sources.append({
                    "name": f'{row_name} -- {split["name"]}',
                    "institution": (live or {}).get("institution", ""),
                    "origin": "Linked account (Asset tab, manually split)",
                    "tax_bucket": split["tax_treatment"] if split["tax_treatment"] in _VALID_TAX_TREATMENTS else "taxable",
                    "balance": split["amount"] or 0.0,
                    "owner": db.normalize_owner(a.get("owner")),
                    "owner_target": {"kind": "asset", "id": a["id"]},
                })
        else:
            drawdown_sources.append({
                "name": row_name,
                "institution": (live or {}).get("institution", ""),
                "origin": "Linked account (Asset tab)" if live else "Manual entry (Asset tab)",
                "tax_bucket": effective_tax_treatment(a, live_by_account_id),
                "balance": effective_balance(a, live_by_account_id),
                "owner": db.normalize_owner(a.get("owner")),
                "owner_target": {"kind": "asset", "id": a["id"]},
            })
    for acc in unlinked_investment_accounts:
        if acc["account_id"] in split_unlinked_account_ids:
            for split in splits_by_account[acc["account_id"]]:
                drawdown_sources.append({
                    "name": f'{acc["label"]} -- {split["name"]}',
                    "institution": acc["institution"],
                    "origin": "Linked account (not on Asset tab, manually split)",
                    "tax_bucket": split["tax_treatment"] if split["tax_treatment"] in _VALID_TAX_TREATMENTS else "taxable",
                    "balance": split["amount"] or 0.0,
                    "owner": db.normalize_owner(account_owners.get(acc["account_id"])),
                    "owner_target": {"kind": "account", "id": acc["account_id"]},
                })
        else:
            drawdown_sources.append({
                "name": acc["label"],
                "institution": acc["institution"],
                "origin": "Linked account (not on Asset tab)",
                "tax_bucket": acc.get("detected_tax_treatment") or "taxable",
                "balance": acc["balance"],
                "owner": db.normalize_owner(account_owners.get(acc["account_id"])),
                "owner_target": {"kind": "account", "id": acc["account_id"]},
            })
    for r in real_estate:
        if r.get("include_in_monte_carlo"):
            drawdown_sources.append({
                "name": r.get("name") or "(unnamed property)",
                "institution": "",
                "origin": "Real estate (opted in)",
                "tax_bucket": "real_estate",
                "balance": real_estate_equity(r, loan_balance=effective_loan_balance(r, live_by_account_id)),
            })

    # The derived spouse share of the Tax-deferred pool -- see
    # monte_carlo.assumptions._resolve_spouse_tax_deferred_share. Injected
    # into this fresh (never-persisted) assumptions dict so every
    # simulation entry point, which already takes `assumptions`, sees it
    # without a new parameter. It describes retirement_pools; the Drawdown
    # and Legacy pages, whose pools ALSO include unlinked Plaid accounts,
    # layer drawdown_spouse_tax_deferred_share over it instead.
    assumptions["spouse_tax_deferred_share"] = _spouse_share(tax_deferred_by_owner)
    # Likewise derived (not a user setting): when each property's loan ends,
    # weighted by its rental income, so the tax engine only counts rent as
    # taxable once the loan is paid off -- see monte_carlo.assumptions.
    # _resolve_rental_taxable_fraction. Absent when no property has a loan
    # end year (rent is then taxable every year, the original behavior).
    assumptions["rental_taxable_schedule"] = _rental_taxable_schedule(real_estate)

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

    # A second, forward-looking figure for the Summary page's "expense
    # need" tile -- next_year is always this_year + 1, deliberately NOT a
    # second read of assumptions.current_year, so nothing here can drift
    # out of step with "this year" as computed above. Every other page
    # (Monte Carlo, Income/Expense) keeps using this_year/current_year as
    # "now" -- this is purely an additional number, not a redefinition.
    next_year = this_year + 1
    next_year_need = annual_expense_need(expenses, next_year, inflation_rate)

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
        "real_estate_value_total": re_value_total,
        "net_worth": net_worth,
        "retirement_liquid_total": retirement_liquid_total,
        "tax_deferred_total": tax_deferred_total,
        "tax_deferred_by_owner": tax_deferred_by_owner,
        "drawdown_tax_deferred_by_owner": drawdown_tax_deferred_by_owner,
        "drawdown_spouse_tax_deferred_share": _spouse_share(drawdown_tax_deferred_by_owner),
        "roth_total": roth_total,
        "taxable_total": taxable_total,
        "asset_category_subtotals": asset_category_subtotals,
        "net_liquid_asset": net_liquid_asset,
        "retirement_pools": retirement_pools,
        "drawdown_pools": drawdown_pools,
        "drawdown_sources": drawdown_sources,
        "drawdown_unlinked_total": sum(drawdown_unlinked_totals.values()),
        # The Drawdown Planning tab's own "Split a linked account across
        # tax buckets" card: every live investment account -- linked to
        # an Asset-tab row or not -- so the user can pick one to split,
        # every split recorded so far (regardless of whether its account
        # is still live -- see the comment above splits_by_account), and
        # any account whose splits no longer add up to its own live
        # balance.
        "unlinked_investment_accounts": unlinked_investment_accounts,
        "splittable_investment_accounts": splittable_investment_accounts,
        "account_tax_splits": [s for splits in splits_by_account.values() for s in splits],
        "account_split_mismatches": account_split_mismatches,
        "total_asset": total_asset,
        "this_year": this_year,
        "this_year_expense_need": this_year_need,
        "this_year_income": this_year_income,
        "this_year_net_need": this_year_net_need,
        "next_year": next_year,
        "next_year_expense_need": next_year_need,
        "import_status": {
            "last_import_at": db.get_meta("last_import_at"),
            "last_import_source": db.get_meta("last_import_source"),
        },
    }
