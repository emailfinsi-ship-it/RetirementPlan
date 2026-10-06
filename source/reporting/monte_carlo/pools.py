"""Three-pool withdrawal/RMD/tax engine -- an optional, more detailed
alternative to the single-balance model above, engaged whenever a
caller passes `pools` (a {"tax_deferred", "roth", "taxable"} dict)
into run_simulation / run_historical_bootstrap_simulation /
run_historical_stress_test instead of relying on `starting_balance`
alone. The single-balance model those functions already used is left
completely untouched (see each function's own `if pools is None`
branch) -- every existing caller keeps getting byte-identical
results; this is a strictly additive second mode, not a replacement.

Model: each simulated year, once that year's investment return has
been applied to all three pools alike (this program doesn't track a
separate asset allocation per account, so one blended portfolio
return is the level of fidelity that matches the rest of it), the
year's withdrawal happens in three steps:
  1. RMD -- once the account owner reaches RMD age (73 or 75
     depending on birth year -- source.reporting.rmd), the
     tax-deferred pool owes a mandatory withdrawal (balance / that
     age's IRS Uniform Lifetime Table divisor), whether or not it's
     needed for spending. Whatever of it isn't needed for that year's
     expenses is swept into the taxable pool -- an RMD you don't
     spend still leaves the tax-deferred account; from then on it
     sits in an ordinary taxable brokerage.
  2. Any of that year's net withdrawal need still uncovered by the
     RMD is drawn Taxable first, then any additional Tax-deferred,
     then Roth last -- the conventional tax-efficient order (spend
     already-taxed money first, let tax-deferred and especially Roth
     keep compounding as long as possible).
  3. The tax bill on all of that (ordinary income tax on the
     Tax-deferred withdrawal including the RMD; capital-gains tax on
     an assumed fraction of the Taxable withdrawal; nothing on Roth)
     itself has to be withdrawn too -- funded the same way step 2's
     shortfall was, solved by the same fixed-point-iteration idea
     estimate_annual_drawdown_tax uses above (withdrawing more to
     cover taxes is itself taxable, so the true amount has to
     converge rather than be computed in one pass).
"""

from __future__ import annotations

from source.reporting import rmd
from source.reporting.monte_carlo.assumptions import _resolve_spouse_birth_year, _resolve_spouse_tax_deferred_share
from source.reporting.monte_carlo.tax import _pool_year_tax


# Withdrawal order for any dollar beyond the mandatory RMD -- spend
# already-taxed Taxable-brokerage money first, then dip further into
# Tax-deferred, and only draw down Roth last (it's the one pool that
# never owes income tax on withdrawal and never forces an RMD, so
# leaving it invested longest is the standard tax-efficient default).
# "real_estate" -- an opted-in property's equity (see real_estate.
# include_in_monte_carlo and aggregate.build_summary) -- is drawn dead
# last, after all three of those are exhausted: it's the least liquid
# money in the plan (turning it into spendable cash means selling or
# borrowing against a house), so it's the last resort here too. Every
# pools dict this engine has ever accepted lacks a "real_estate" key,
# and _simulate_fill/available.get(name, 0.0) below treat a missing key
# as $0 available -- so appending it here changes nothing for a
# 3-pool-only caller.
_WITHDRAWAL_ORDER = ("taxable", "tax_deferred", "roth", "real_estate")

# An alternate order -- spend Tax-deferred FIRST -- for a strategy that
# deliberately draws the tax-deferred pool down earlier than the default
# (e.g. starting at age 60, once 401k/IRA withdrawals are penalty-free)
# rather than only once RMDs force it at 73/75. See
# legacy_planning._run_conversion_schedule's early_spend_from_age -- the
# idea is to realize that income in the plan owner's own lower
# pre-RMD-age brackets, and to shrink the balance RMDs will later be
# calculated on, at the cost of spending down Taxable (and its step-up
# basis) more slowly.
_TAX_DEFERRED_FIRST_ORDER = ("tax_deferred", "taxable", "roth", "real_estate")



def _simulate_fill(available: dict, order: tuple, amount: float) -> dict:
    """A read-only "what would withdrawing `amount` dollars look like,
    taken from `available` pool balances in `order`, each capped at
    what it actually has" -- used both to try a candidate total draw
    during _apply_year_withdrawal's tax gross-up iteration below and,
    once converged, to compute the real withdrawal. Never returns more
    than `amount` total, and never more than any one pool has (the sum
    of the result can fall short of `amount` if every pool combined
    can't cover it -- that shortfall is _apply_year_withdrawal's signal
    that this simulated path is depleted)."""
    remaining = max(0.0, amount)
    withdrawn = {}
    for name in order:
        take = min(max(0.0, available.get(name, 0.0)), remaining)
        withdrawn[name] = take
        remaining -= take
    return withdrawn



def new_owner_state(tax_deferred_balance: float, assumptions: dict) -> dict | None:
    """A fresh per-path/per-scenario "who owns the Tax-deferred pool"
    tracker for _apply_year_withdrawal's `owners` parameter, or None when
    no tax-deferred money is assigned to the spouse (the original
    single-owner behavior -- every caller can pass this straight through
    without checking). Splits `tax_deferred_balance` (a path's starting
    Tax-deferred pool) by the derived spouse share (see
    assumptions._resolve_spouse_tax_deferred_share); the plan owner's
    side gets everything not assigned to the spouse, including accounts
    still marked Unassigned, which are modeled under the plan owner's
    own birth year until someone assigns them. Every simulation site
    calls this once per path/scenario, since each path's own balances
    (and therefore each person's own RMD) evolve independently."""
    share = _resolve_spouse_tax_deferred_share(assumptions)
    if share <= 0:
        return None
    balance = max(0.0, tax_deferred_balance)
    return {
        "self": balance * (1.0 - share),
        "spouse": balance * share,
        "spouse_birth_year": _resolve_spouse_birth_year(assumptions),
    }


def _sync_owner_balances(owners: dict, tax_deferred_total: float) -> None:
    """Rescales each owner's balance so they sum to the pool's actual
    current Tax-deferred total, keeping their relative proportions.
    Growth is applied to the shared pools dict by every caller (one
    blended return, same as always) and Roth conversions pull from it
    too -- neither touches `owners` itself, so this is what keeps the two
    views from drifting apart before each year's RMD is computed."""
    total = owners["self"] + owners["spouse"]
    target = max(0.0, tax_deferred_total)
    if total > 0:
        scale = target / total
        owners["self"] *= scale
        owners["spouse"] *= scale
    else:
        owners["self"], owners["spouse"] = target, 0.0


def _split_extra_tax_deferred(
    amount: float, remaining_self: float, remaining_spouse: float, self_birth_year: int | None, spouse_birth_year: int | None,
) -> tuple[float, float]:
    """Divides an `amount` of ordinary (beyond-the-RMD) Tax-deferred
    spending between the two owners' remaining balances: the OLDER
    spouse's accounts first (the person who reaches RMD age sooner --
    drawing theirs down shrinks the balance their own future RMDs are
    calculated on), the other's only once that one's remaining balance
    is exhausted. Falls back to splitting proportionally to remaining
    balances when either birth year is unknown or both are equal, so
    there's never an arbitrary winner. Returns (from_self, from_spouse),
    never more than either person's own remaining balance."""
    amount = max(0.0, amount)
    if amount == 0.0:
        return 0.0, 0.0
    total_remaining = remaining_self + remaining_spouse
    if total_remaining <= 0:
        return 0.0, 0.0
    amount = min(amount, total_remaining)
    if self_birth_year is not None and spouse_birth_year is not None and self_birth_year != spouse_birth_year:
        first_is_self = self_birth_year < spouse_birth_year
        first_remaining = remaining_self if first_is_self else remaining_spouse
        from_first = min(amount, first_remaining)
        from_second = amount - from_first
        return (from_first, from_second) if first_is_self else (from_second, from_first)
    from_self = amount * (remaining_self / total_remaining)
    return from_self, amount - from_self


def _apply_year_withdrawal(
    pools: dict, *, need: float, age: int | None, birth_year: int | None, gains_fraction: float,
    year: int, inflation_rate: float, apply_drawdown_tax: bool, order: tuple | None = None,
    owners: dict | None = None,
) -> dict:
    """Withdraws one simulated year's need (+ its own tax, if
    apply_drawdown_tax) from `pools` IN PLACE (mutates
    pools["tax_deferred"]/["roth"]/["taxable"], never below 0) -- see
    the "Three-pool withdrawal/RMD/tax engine" comment above for the
    ordering rule this follows. `age`/`birth_year` are both None when
    the Setup/Assumptions birth year hasn't been filled in, which simply
    skips RMDs (rmd_amount stays 0) rather than blocking the rest of the
    simulation on it.

    `order` overrides _WITHDRAWAL_ORDER for this year's spending draw
    only -- the RMD itself is unaffected either way (it's always forced
    from tax_deferred first, before any ordering choice even applies).
    Every existing caller leaves this at the default None (the standard
    Taxable-then-Tax-deferred-then-Roth-then-Real-estate order); it
    exists so a strategy like "spend Tax-deferred first starting at a
    chosen age" (see legacy_planning.py) can reuse this exact engine
    rather than re-implementing it.

    Returns {"rmd": ..., "tax": ..., "shortfall": ..., "withdrawn": ...}
    -- shortfall > 0 means every pool combined couldn't cover this
    year's need + tax, the three-pool equivalent of the single-balance
    model's "balance went negative, clamp to 0, mark depleted".
    `withdrawn` is the {"taxable", "tax_deferred", "roth", "real_estate"}
    breakdown of the "beyond the RMD" draw (extra_withdrawn) -- a
    caller that wants "how much actually came out of each pool this
    year" adds `rmd` to withdrawn["tax_deferred"] itself, since the RMD
    is a separate, mandatory draw from that same pool.

    `owners` (see new_owner_state) is None by default -- the original
    behavior, where one RMD is computed on the WHOLE Tax-deferred pool
    from the plan owner's own age, untouched byte for byte. Passed a
    tracker instead (one is only ever created when some Tax-deferred
    money is assigned to the spouse), each person's RMD is computed on
    THEIR OWN share of the pool using THEIR OWN age/birth year (so
    someone born 1962 isn't forced out at 73 just because their spouse
    was born 1955), the two are summed, and any ordinary Tax-deferred
    spending beyond the RMDs comes from the older spouse's remaining
    balance first (_split_extra_tax_deferred). `owners` is mutated in
    place to each person's new balance; the returned dict also gains
    "rmd_by_owner": {"self": ..., "spouse": ...}. Everything else --
    the pools dict, the withdrawal order, tax -- is unchanged, since
    the pools dict itself never splits Tax-deferred by owner."""
    withdrawal_order = order or _WITHDRAWAL_ORDER
    rmd_amount = 0.0
    rmd_self = rmd_spouse = 0.0
    if owners is not None:
        _sync_owner_balances(owners, pools["tax_deferred"])
        if birth_year is not None and age is not None:
            rmd_self = rmd.required_minimum_distribution(owners["self"], age, birth_year)
        spouse_birth_year = owners.get("spouse_birth_year")
        if spouse_birth_year is not None:
            rmd_spouse = rmd.required_minimum_distribution(owners["spouse"], year - spouse_birth_year, spouse_birth_year)
        rmd_amount = rmd_self + rmd_spouse
    elif birth_year is not None and age is not None:
        rmd_amount = rmd.required_minimum_distribution(pools["tax_deferred"], age, birth_year)
    rmd_amount = min(rmd_amount, max(0.0, pools["tax_deferred"]))
    need_after_rmd = max(0.0, need - rmd_amount)
    # Reserve the RMD out of tax_deferred's own availability before any
    # further ("extra") withdrawal is allowed to touch it -- the RMD
    # itself already claims that slice of the pool.
    available = {
        "taxable": pools["taxable"],
        "tax_deferred": max(0.0, pools["tax_deferred"] - rmd_amount),
        "roth": pools["roth"],
        "real_estate": pools.get("real_estate", 0.0),
    }

    extra_total = need_after_rmd
    extra_withdrawn = _simulate_fill(available, withdrawal_order, extra_total)
    tax = 0.0
    if apply_drawdown_tax:
        # Fixed-point iteration, same idea (and same iteration count) as
        # estimate_annual_drawdown_tax's gross-up above: withdrawing
        # more to pay this year's tax bill is itself partly taxable (the
        # extra Tax-deferred/Taxable slice it comes from), so the true
        # total converges rather than being solvable in one pass. The
        # marginal rate on any single extra dollar is always well under
        # 1, so this contracts to float precision well within 12 passes.
        for _ in range(12):
            ordinary = rmd_amount + extra_withdrawn["tax_deferred"]
            gains = extra_withdrawn["taxable"] * gains_fraction
            tax = _pool_year_tax(ordinary_income=ordinary, gains_income=gains, year=year, inflation_rate=inflation_rate)
            extra_total = need_after_rmd + tax
            extra_withdrawn = _simulate_fill(available, withdrawal_order, extra_total)

    shortfall = max(0.0, extra_total - sum(extra_withdrawn.values()))

    if owners is not None:
        from_self, from_spouse = _split_extra_tax_deferred(
            extra_withdrawn["tax_deferred"], max(0.0, owners["self"] - rmd_self), max(0.0, owners["spouse"] - rmd_spouse),
            birth_year, owners.get("spouse_birth_year"),
        )
        owners["self"] = max(0.0, owners["self"] - rmd_self - from_self)
        owners["spouse"] = max(0.0, owners["spouse"] - rmd_spouse - from_spouse)

    pools["tax_deferred"] -= rmd_amount + extra_withdrawn["tax_deferred"]
    pools["taxable"] -= extra_withdrawn["taxable"]
    pools["roth"] -= extra_withdrawn["roth"]
    # Only touch pools["real_estate"] when the caller's own pools dict
    # already has that key -- a plan with nothing opted in never gets a
    # "real_estate": 0.0 key silently added, so a 3-pool-only caller's
    # pools dict keeps its exact original shape.
    if "real_estate" in pools:
        pools["real_estate"] -= extra_withdrawn["real_estate"]
    # Whatever the RMD didn't need to cover spending is still money that
    # left the tax-deferred account -- it doesn't vanish, it lands in
    # the taxable pool (an ordinary brokerage/checking balance) from
    # here on.
    rmd_surplus = max(0.0, rmd_amount - min(rmd_amount, need))
    pools["taxable"] += rmd_surplus
    for name in pools:
        if pools[name] < 0:
            pools[name] = 0.0

    result = {"rmd": rmd_amount, "tax": tax, "shortfall": shortfall, "withdrawn": extra_withdrawn}
    if owners is not None:
        result["rmd_by_owner"] = {"self": rmd_self, "spouse": rmd_spouse}
    return result
