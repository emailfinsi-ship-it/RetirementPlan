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



def _apply_year_withdrawal(
    pools: dict, *, need: float, age: int | None, birth_year: int | None, gains_fraction: float,
    year: int, inflation_rate: float, apply_drawdown_tax: bool,
) -> dict:
    """Withdraws one simulated year's need (+ its own tax, if
    apply_drawdown_tax) from `pools` IN PLACE (mutates
    pools["tax_deferred"]/["roth"]/["taxable"], never below 0) -- see
    the "Three-pool withdrawal/RMD/tax engine" comment above for the
    ordering rule this follows. `age`/`birth_year` are both None when
    the Setup/Assumptions birth year hasn't been filled in, which simply
    skips RMDs (rmd_amount stays 0) rather than blocking the rest of the
    simulation on it.

    Returns {"rmd": ..., "tax": ..., "shortfall": ..., "withdrawn": ...}
    -- shortfall > 0 means every pool combined couldn't cover this
    year's need + tax, the three-pool equivalent of the single-balance
    model's "balance went negative, clamp to 0, mark depleted".
    `withdrawn` is the {"taxable", "tax_deferred", "roth", "real_estate"}
    breakdown of the "beyond the RMD" draw (extra_withdrawn) -- a
    caller that wants "how much actually came out of each pool this
    year" adds `rmd` to withdrawn["tax_deferred"] itself, since the RMD
    is a separate, mandatory draw from that same pool."""
    rmd_amount = 0.0
    if birth_year is not None and age is not None:
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
    extra_withdrawn = _simulate_fill(available, _WITHDRAWAL_ORDER, extra_total)
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
            extra_withdrawn = _simulate_fill(available, _WITHDRAWAL_ORDER, extra_total)

    shortfall = max(0.0, extra_total - sum(extra_withdrawn.values()))

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

    return {"rmd": rmd_amount, "tax": tax, "shortfall": shortfall, "withdrawn": extra_withdrawn}
