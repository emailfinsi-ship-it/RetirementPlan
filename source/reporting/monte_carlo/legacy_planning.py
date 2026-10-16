"""Roth-conversion / legacy-tax planning: compares a handful of named
Traditional-to-Roth conversion strategies against today's default (no
conversions at all) on two numbers most retirees actually care about --
how much tax YOU pay over your own lifetime, and how much your heir
keeps after THEIR tax, once the plan's tax-deferred, Roth, Taxable, and
opted-in Real estate balances eventually pass to them.

Why this is a genuinely different question from "minimize my own
lifetime tax" (the order pools.py's three-pool engine already runs,
Taxable -> Tax-deferred -> Roth -> Real estate): a Roth balance is
100% tax-free to any heir; a Taxable balance gets a full step-up in
cost basis at death (this program doesn't track per-lot cost basis --
see aggregate/drawdown_schedule's own comments -- so every dollar of
it is treated as passing tax-free too, the standard simplification);
but a Tax-deferred balance is Income in Respect of a Decedent -- the
heir owes ordinary income tax on every dollar they withdraw, and (for
a non-spouse heir) the SECURE Act forces the whole account out within
10 years of your death, often stacking on top of the heir's own
higher-earning-years income. Spending down Tax-deferred first (via
these Roth conversions) while you're alive, even at a real tax cost
now, can leave more after-tax money in the family's hands than
minimizing your own tax bill would -- but not always, since conversion
tax paid now is real money that stops compounding. This module runs
the numbers rather than assuming either answer.

Every strategy below reuses the exact same deterministic, single-path
engine (_apply_year_withdrawal from pools.py, at the plan's own
Expected return assumption, no randomness -- same reasoning as
drawdown_schedule.py's own docstring) that the Drawdown Planning tab's
year-by-year table already runs on, plus one new step each year: an
optional Roth conversion, applied AFTER that year's RMD and spending
withdrawal (a conversion can never satisfy an RMD -- the RMD has to
come out as an ordinary taxable distribution first) and capped so its
own tax bill can be paid out of the Taxable pool without an extra
tax-deferred withdrawal (converting using IRA money to pay the
conversion's own tax defeats much of the point).
"""

from __future__ import annotations

from datetime import date

from source.reporting import rmd
from source.reporting.monte_carlo.assumptions import (
    _resolve_birth_year,
    _resolve_early_tax_deferred_age,
    _resolve_gains_fraction,
    _resolve_retirement_year,
    _truthy_assumption,
)
from source.reporting.monte_carlo.pools import _TAX_DEFERRED_FIRST_ORDER, _apply_year_withdrawal, new_owner_state
from source.reporting.monte_carlo.tax import (
    CA_TAX_BRACKETS_MFJ_2026,
    FEDERAL_STANDARD_DEDUCTION_MFJ_2026,
    FEDERAL_TAX_BRACKETS_MFJ_2026,
    _TAX_BRACKET_BASE_YEAR,
    _marginal_rate,
    _pool_year_tax,
)
from source.reporting.monte_carlo.withdrawal import annual_net_withdrawal_need, annual_taxable_income


# (key, label, target federal bracket rate to fill up to each year --
# None means the baseline "don't convert at all" strategy, "aggressive"
# means "convert as much of the balance as the Taxable pool can afford
# the tax on, every year, uncapped by any target bracket"). Order here
# is also the order strategies render in on the Legacy Planning page.
ROTH_CONVERSION_STRATEGIES: tuple[tuple[str, str, float | str | None], ...] = (
    ("no_conversions", "No Roth conversions (today's default order)", None),
    ("fill_12", "Convert up to the 12% federal bracket each year", 0.12),
    ("fill_22", "Convert up to the 22% federal bracket each year", 0.22),
    ("fill_24", "Convert up to the 24% federal bracket each year", 0.24),
    ("fill_32", "Convert up to the 32% federal bracket each year", 0.32),
    ("aggressive", "Convert as much as the Taxable pool can afford the tax on", "aggressive"),
)

# (key, label, age spending switches to drawing Tax-deferred FIRST
# instead of last) -- a different lever from ROTH_CONVERSION_STRATEGIES
# above: no conversion to Roth at all, just spending straight from
# Tax-deferred once the owner reaches this age (401k/IRA withdrawals are
# already penalty-free from 59 1/2, well before RMDs would force it at
# 73/75), instead of today's default of spending Taxable first and only
# reaching Tax-deferred once Taxable runs out. Per the user's own
# question ("if it makes sense we can start withdraw of 401k from 60").
# Compared alongside the conversion strategies on the same Legacy
# Planning page/table -- see compare_roth_conversion_strategies.
EARLY_TAX_DEFERRED_SPENDING_STRATEGIES: tuple[tuple[str, str, int], ...] = (
    ("tax_deferred_from_60", "Spend Tax-deferred first starting at age 60", 60),
)

_HEIR_TYPES = ("non_spouse", "spouse")


def _current_year(assumptions: dict) -> int:
    raw = assumptions.get("current_year")
    return int(raw) if raw not in (None, "") else date.today().year


def _combined_marginal_rate(taxable_income: float, year: int, inflation_rate: float) -> float:
    """Federal + California marginal rate at `taxable_income` (both
    grown from _TAX_BRACKET_BASE_YEAR to `year` by inflation_rate, same
    convention as every other bracket lookup in this package) -- a
    single readable "what bracket is this" number for the Legacy
    Planning page, e.g. "22% federal + 9.3% CA = 31.3%"."""
    growth = (1.0 + inflation_rate) ** (year - _TAX_BRACKET_BASE_YEAR)
    fed_brackets = tuple((None if upper is None else upper * growth, rate) for upper, rate in FEDERAL_TAX_BRACKETS_MFJ_2026)
    ca_brackets = tuple((None if upper is None else upper * growth, rate) for upper, rate in CA_TAX_BRACKETS_MFJ_2026)
    taxable = max(0.0, taxable_income)
    return _marginal_rate(taxable, fed_brackets) + _marginal_rate(taxable, ca_brackets)


def _stacked_tax_on_amount(base_income: float, additional: float, year: int, inflation_rate: float) -> float:
    """Fed+CA tax owed on just the `additional` ordinary-income slice
    given `base_income` of other ordinary income already fills the
    brackets below it -- both treated as pure ordinary income (no
    capital-gains portion), via _pool_year_tax's own base_ordinary_income
    stacking."""
    if additional <= 0:
        return 0.0
    return _pool_year_tax(
        ordinary_income=additional, gains_income=0.0, year=year, inflation_rate=inflation_rate,
        base_ordinary_income=max(0.0, base_income),
    )


def estimate_default_heir_base_income(assumptions: dict, expenses: list, income: list) -> float:
    """"Use my own current bracket as a stand-in" for the heir's own tax
    situation -- this program has no separate income field for anyone
    but the plan owner, so it reuses this plan's OWN Yearly Drawdown
    need for `current_year` (Expense-tab total minus Income-tab total
    minus the flat income offset -- the very same "ordinary income"
    figure estimate_annual_drawdown_tax already taxes elsewhere in this
    program) as the base income the heir's own inherited distributions
    stack on top of. Floored at 0 (a plan not yet retired, or fully
    covered by Income-tab rows, has no net need yet -- this just means
    the default starts at the bottom bracket; it's an editable
    assumption -- see the Legacy Planning page's own field -- precisely
    so a real difference between your bracket and your heir's can be
    typed in instead)."""
    current_year = _current_year(assumptions)
    inflation_rate = float(assumptions.get("inflation_rate") or 0.0)
    income_offset = float(assumptions.get("annual_income_offset") or 0)
    retirement_year = _resolve_retirement_year(assumptions)
    need = annual_net_withdrawal_need(expenses, income, current_year, inflation_rate, income_offset, retirement_year)
    return max(0.0, round(need, 2))


def _resolve_heir_base_income(assumptions: dict, expenses: list, income: list) -> float:
    raw = assumptions.get("heir_base_income")
    if raw not in (None, ""):
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
    return estimate_default_heir_base_income(assumptions, expenses, income)


def _resolve_heir_type(assumptions: dict) -> str:
    raw = (assumptions.get("heir_type") or "").strip().lower()
    return raw if raw in _HEIR_TYPES else "non_spouse"


# Fallback "spread heir's withdrawals over N years" per heir type, used
# by _resolve_heir_spread_years whenever the user hasn't typed over it.
# 10 for a non-spouse heir matches the SECURE Act's own default forced
# window; 20 for a spouse is this program's own placeholder guess at "a
# long remaining lifetime" (a spouse has no forced window at all -- see
# estimate_heir_tax_on_tax_deferred's own docstring). Neither is a legal
# requirement for every real situation, which is exactly why this is a
# user-editable assumption rather than hardcoded math.
_DEFAULT_HEIR_SPREAD_YEARS = {"non_spouse": 10, "spouse": 20}


def _resolve_heir_spread_years(assumptions: dict, heir_type: str) -> int:
    """How many years the heir's own inherited Tax-deferred balance is
    assumed to be spread across as even annual distributions -- "" (or
    garbage, or anything below 1) falls back to
    _DEFAULT_HEIR_SPREAD_YEARS[heir_type]. Always user-editable (see the
    Heir assumptions card on the Legacy Planning page) because the
    "right" number varies by real situation: a surviving spouse can
    roll the account and draw it down on whatever schedule they choose;
    a non-spouse heir is forced to empty it within 10 years by the
    SECURE Act UNLESS they qualify as an "eligible designated
    beneficiary" (a minor child of the decedent, until they reach
    majority; a disabled or chronically ill beneficiary; someone not
    more than 10 years younger than the decedent) exempting them from
    that flat 10-year rule and letting them stretch distributions over
    their own life expectancy instead."""
    raw = assumptions.get("heir_spread_years")
    if raw not in (None, ""):
        try:
            parsed = int(float(raw))
            if parsed >= 1:
                return parsed
        except (TypeError, ValueError):
            pass
    return _DEFAULT_HEIR_SPREAD_YEARS.get(heir_type, 10)


def estimate_heir_tax_on_tax_deferred(
    *, remaining_balance: float, heir_type: str, heir_base_income: float, year: int, inflation_rate: float,
    spread_years: int,
) -> float:
    """The estimated tax the heir owes on inheriting `remaining_balance`
    of Tax-deferred (401k/Traditional) money, given their own assumed
    base ordinary income (heir_base_income) and `spread_years` (see
    _resolve_heir_spread_years) -- both heir types are modeled the same
    way: `remaining_balance` spread across `spread_years` even annual
    distributions, each its own tax year, every one stacked on the SAME
    assumed heir_base_income (held flat across the window -- a
    documented simplification: brackets and the heir's own income would
    really keep moving over that many real years, but holding both flat
    keeps this a single, explainable number rather than a multi-year
    simulation of the heir's own life). Because tax years reset every
    year, splitting the balance evenly across `spread_years` separate
    tax years is dramatically cheaper than dumping it all into one --
    this rewards spreading out distributions instead of ignoring it.

    `heir_type` no longer changes the math directly (an earlier version
    of this function gave a spouse a flat rate on the whole balance
    instead) -- it's kept as a parameter because callers still use it
    to pick spread_years' own default and to drive the page's
    explanatory text; the two heir types can converge on identical math
    once spread_years is set to the same number for both."""
    if remaining_balance <= 0 or spread_years <= 0:
        return 0.0
    annual_distribution = remaining_balance / spread_years
    per_year_tax = _stacked_tax_on_amount(heir_base_income, annual_distribution, year, inflation_rate)
    return per_year_tax * spread_years


def _federal_bracket_ceiling(target_rate: float, year: int, inflation_rate: float) -> float:
    """The taxable-income upper bound of the federal bracket taxed at
    `target_rate` (grown to `year` same as every other bracket lookup
    here) -- e.g. 0.12 -> the top of the 12% bracket. Unbounded
    (float("inf")) if target_rate doesn't match any bracket in the
    table (shouldn't happen given ROTH_CONVERSION_STRATEGIES only uses
    rates that are actually in FEDERAL_TAX_BRACKETS_MFJ_2026, but this
    keeps a typo'd rate from raising)."""
    growth = (1.0 + inflation_rate) ** (year - _TAX_BRACKET_BASE_YEAR)
    for upper, rate in FEDERAL_TAX_BRACKETS_MFJ_2026:
        if abs(rate - target_rate) < 1e-9:
            return float("inf") if upper is None else upper * growth
    return float("inf")


def _cap_conversion_by_affordability(
    candidate: float, other_ordinary_income: float, taxable_available: float, year: int, inflation_rate: float,
) -> float:
    """Shrinks `candidate` (a conversion amount) down, if needed, so the
    tax it triggers (stacked on other_ordinary_income) can be paid from
    taxable_available without touching the IRA itself -- converting
    using IRA money to pay the conversion's own tax gives away most of
    the point of converting. _stacked_tax_on_amount is monotonically
    non-decreasing in its `additional` argument, so a plain bisection
    over [0, candidate] converges to the largest affordable amount."""
    if candidate <= 0:
        return 0.0
    full_tax = _stacked_tax_on_amount(other_ordinary_income, candidate, year, inflation_rate)
    if full_tax <= taxable_available:
        return candidate
    if taxable_available <= 0:
        return 0.0
    lo, hi = 0.0, candidate
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if _stacked_tax_on_amount(other_ordinary_income, mid, year, inflation_rate) > taxable_available:
            hi = mid
        else:
            lo = mid
    return lo


def _run_conversion_schedule(
    *, pools: dict, expenses: list, income: list, assumptions: dict, target_rate: float | str | None,
    early_spend_from_age: int | None = None,
) -> dict:
    """Walks one Roth-conversion strategy forward year by year, exactly
    like drawdown_schedule.deterministic_drawdown_schedule, with one
    extra step per year: after that year's RMD + spending withdrawal
    (via the shared _apply_year_withdrawal engine, untouched), convert
    up to `target_rate`'s federal bracket ceiling (or, for
    target_rate="aggressive", as much of the remaining Tax-deferred
    balance as the Taxable pool can afford the tax on) from Tax-deferred
    into Roth. target_rate=None (the "no_conversions" baseline) skips
    the conversion step entirely, byte-for-byte reproducing
    deterministic_drawdown_schedule's own numbers.

    `early_spend_from_age`, when set (see
    EARLY_TAX_DEFERRED_SPENDING_STRATEGIES), is a completely separate
    lever from `target_rate`/conversions: once the owner's age reaches
    it, that year's SPENDING withdrawal itself draws Tax-deferred first
    (via _apply_year_withdrawal's own `order` override) instead of
    Taxable first -- no money moves to Roth, it just gets spent straight
    from Tax-deferred earlier than the default order would. Both levers
    can in principle combine (an early-spend row can still receive a
    conversion), though EARLY_TAX_DEFERRED_SPENDING_STRATEGIES's own
    entries currently only ever set one or the other.

    Returns {"years", "rows", "total_lifetime_tax", "total_converted",
    "ending_taxable", "ending_tax_deferred", "ending_roth",
    "ending_real_estate", "ending_total", "depletes"} -- `rows` mirrors
    deterministic_drawdown_schedule's own row shape plus "conversion"
    and "conversion_tax" per year."""
    expected_return = float(assumptions.get("expected_return") or 0.06)
    inflation_rate = float(assumptions.get("inflation_rate") or 0.0)
    income_offset = float(assumptions.get("annual_income_offset") or 0)
    apply_drawdown_tax = _truthy_assumption(assumptions, "apply_drawdown_tax")
    horizon = max(1, int(float(assumptions.get("plan_horizon_years") or 40)))
    current_year = _current_year(assumptions)
    birth_year = _resolve_birth_year(assumptions)
    gains_fraction = _resolve_gains_fraction(assumptions)
    retirement_year = _resolve_retirement_year(assumptions)

    years = [current_year + i for i in range(horizon)]
    path_pools = {
        "tax_deferred": pools.get("tax_deferred", 0.0),
        "roth": pools.get("roth", 0.0),
        "taxable": pools.get("taxable", 0.0),
        "real_estate": pools.get("real_estate", 0.0),
    }
    owners = new_owner_state(path_pools["tax_deferred"], assumptions)
    total_lifetime_tax = 0.0
    total_converted = 0.0
    depletes = False
    rows = []
    for year in years:
        for name in path_pools:
            path_pools[name] *= (1 + expected_return)

        age = (year - birth_year) if birth_year is not None else None
        need = annual_net_withdrawal_need(expenses, income, year, inflation_rate, income_offset, retirement_year)
        spend_order = (
            _TAX_DEFERRED_FIRST_ORDER
            if early_spend_from_age is not None and age is not None and age >= early_spend_from_age
            else None
        )
        taxable_income = annual_taxable_income(income, year, inflation_rate)
        result = _apply_year_withdrawal(
            path_pools, need=need, age=age, birth_year=birth_year, gains_fraction=gains_fraction,
            year=year, inflation_rate=inflation_rate, apply_drawdown_tax=apply_drawdown_tax, order=spend_order,
            owners=owners, base_ordinary_income=taxable_income,
        )
        if result["shortfall"] > 1e-6:
            depletes = True
        total_lifetime_tax += result["tax"]
        # Ordinary income already recognized this year before any
        # conversion -- the taxable part of the Income-tab total, the RMD,
        # and whatever additional Tax-deferred dollars the spending
        # withdrawal itself pulled out.
        other_ordinary_income = taxable_income + result["rmd"] + result["withdrawn"].get("tax_deferred", 0.0)

        conversion = 0.0
        conversion_tax = 0.0
        if target_rate is not None and path_pools["tax_deferred"] > 0:
            if target_rate == "aggressive":
                candidate = path_pools["tax_deferred"]
            else:
                ceiling = _federal_bracket_ceiling(target_rate, year, inflation_rate)
                fed_deduction = FEDERAL_STANDARD_DEDUCTION_MFJ_2026 * ((1.0 + inflation_rate) ** (year - _TAX_BRACKET_BASE_YEAR))
                room = ceiling - fed_deduction - other_ordinary_income
                candidate = max(0.0, min(room, path_pools["tax_deferred"]))
            conversion = _cap_conversion_by_affordability(
                candidate, other_ordinary_income, max(0.0, path_pools["taxable"]), year, inflation_rate,
            )
            if conversion > 0:
                conversion_tax = _stacked_tax_on_amount(other_ordinary_income, conversion, year, inflation_rate)
                path_pools["tax_deferred"] -= conversion
                path_pools["roth"] += conversion
                path_pools["taxable"] = max(0.0, path_pools["taxable"] - conversion_tax)
                total_lifetime_tax += conversion_tax
                total_converted += conversion

        withdrawn = result["withdrawn"]
        rows.append({
            "year": year,
            "age": age,
            "need": need,
            "rmd": result["rmd"],
            "tax": result["tax"],
            "conversion": conversion,
            "conversion_tax": conversion_tax,
            "shortfall": result["shortfall"],
            # Same "what actually came out of each pool this year" shape
            # as deterministic_drawdown_schedule's own rows -- see that
            # module's row-building comment for why the RMD folds into
            # drawn_tax_deferred rather than standing apart from it.
            "drawn_taxable": withdrawn.get("taxable", 0.0),
            "drawn_tax_deferred": result["rmd"] + withdrawn.get("tax_deferred", 0.0),
            "drawn_roth": withdrawn.get("roth", 0.0),
            "drawn_real_estate": withdrawn.get("real_estate", 0.0),
            "taxable": path_pools["taxable"],
            "tax_deferred": path_pools["tax_deferred"],
            "roth": path_pools["roth"],
            "real_estate": path_pools["real_estate"],
            "total": sum(path_pools.values()),
        })

    return {
        "years": years,
        "rows": rows,
        "total_lifetime_tax": total_lifetime_tax,
        "total_converted": total_converted,
        "ending_taxable": path_pools["taxable"],
        "ending_tax_deferred": path_pools["tax_deferred"],
        "ending_roth": path_pools["roth"],
        "ending_real_estate": path_pools["real_estate"],
        "ending_total": sum(path_pools.values()),
        "depletes": depletes,
    }


def compare_roth_conversion_strategies(*, pools: dict, expenses: list, assumptions: dict, income: list | None = None) -> dict:
    """Top-level entry point for the Legacy Planning page: runs every
    strategy in ROTH_CONVERSION_STRATEGIES (including the "no_conversions"
    baseline, so every other strategy can be compared against today's
    actual default) plus every strategy in
    EARLY_TAX_DEFERRED_SPENDING_STRATEGIES (a different lever -- spend
    Tax-deferred earlier rather than convert it), and estimates each
    one's after-tax legacy -- Roth + Taxable + Real estate at full value
    (see the module docstring for why), plus whatever Tax-deferred
    survives net of estimate_heir_tax_on_tax_deferred.

    Returns {"heir_type", "heir_base_income", "baseline_key",
    "strategies"} -- `strategies` is sorted best (highest
    net_after_tax_legacy) first, each entry carrying
    "legacy_gain_vs_baseline" (positive means this strategy leaves more
    after-tax money to the heir than doing nothing does) alongside its
    own lifetime-tax and ending-balance figures."""
    income = income or []
    heir_type = _resolve_heir_type(assumptions)
    heir_base_income = _resolve_heir_base_income(assumptions, expenses, income)
    heir_spread_years = _resolve_heir_spread_years(assumptions, heir_type)
    inflation_rate = float(assumptions.get("inflation_rate") or 0.0)

    # The plan's own "Start drawing Tax-deferred at age" setting (the Drawdown
    # Planning tab already follows it) applies to the baseline AND to every
    # conversion row -- otherwise "no conversions" would not be the plan
    # you're actually running, and every comparison would be against a
    # strawman. A fixed-age early-draw alternative is only listed when it
    # differs from that setting (it would just repeat the baseline).
    plan_early_age = _resolve_early_tax_deferred_age(assumptions)
    strategy_configs = [
        {"key": key, "label": label, "target_rate": target_rate, "early_spend_from_age": plan_early_age}
        for key, label, target_rate in ROTH_CONVERSION_STRATEGIES
    ] + [
        {"key": key, "label": label, "target_rate": None, "early_spend_from_age": early_spend_from_age}
        for key, label, early_spend_from_age in EARLY_TAX_DEFERRED_SPENDING_STRATEGIES
        if early_spend_from_age != plan_early_age
    ]
    if plan_early_age is not None:
        for config in strategy_configs:
            if config["key"] == "no_conversions":
                config["label"] = (
                    f"Your current plan: spend Tax-deferred first from age {plan_early_age}, no conversions"
                )

    results = []
    for config in strategy_configs:
        key, label = config["key"], config["label"]
        schedule = _run_conversion_schedule(
            pools=pools, expenses=expenses, income=income, assumptions=assumptions,
            target_rate=config["target_rate"], early_spend_from_age=config["early_spend_from_age"],
        )
        death_year = schedule["years"][-1] if schedule["years"] else _current_year(assumptions)
        heir_tax = estimate_heir_tax_on_tax_deferred(
            remaining_balance=schedule["ending_tax_deferred"], heir_type=heir_type,
            heir_base_income=heir_base_income, year=death_year, inflation_rate=inflation_rate,
            spread_years=heir_spread_years,
        )
        net_legacy = (
            schedule["ending_taxable"] + schedule["ending_roth"] + schedule["ending_real_estate"]
            + max(0.0, schedule["ending_tax_deferred"] - heir_tax)
        )
        results.append({
            "key": key,
            "label": label,
            "total_lifetime_tax": schedule["total_lifetime_tax"],
            "total_converted": schedule["total_converted"],
            "ending_taxable": schedule["ending_taxable"],
            "ending_tax_deferred": schedule["ending_tax_deferred"],
            "ending_roth": schedule["ending_roth"],
            "ending_real_estate": schedule["ending_real_estate"],
            "ending_total": schedule["ending_total"],
            "estimated_heir_tax": heir_tax,
            "net_after_tax_legacy": net_legacy,
            "depletes": schedule["depletes"],
            "rows": schedule["rows"],
        })

    baseline = next(r for r in results if r["key"] == "no_conversions")
    for r in results:
        r["legacy_gain_vs_baseline"] = r["net_after_tax_legacy"] - baseline["net_after_tax_legacy"]

    # Sorted by net_after_tax_legacy descending, with total_lifetime_tax
    # ascending as an explicit tie-break (a real tie is common -- e.g.
    # every strategy fully depletes the same deterministic path and ends
    # at $0 alike -- and among equally-good legacies, the one that cost
    # less in your own lifetime tax to get there is the better plan).
    results.sort(key=lambda r: (r["net_after_tax_legacy"], -r["total_lifetime_tax"]), reverse=True)
    return {
        "heir_type": heir_type,
        "heir_base_income": heir_base_income,
        "heir_marginal_rate": _combined_marginal_rate(heir_base_income, _current_year(assumptions), inflation_rate),
        "heir_spread_years": heir_spread_years,
        "baseline_key": "no_conversions",
        "plan_early_tax_deferred_age": plan_early_age,
        "death_year": results[0]["rows"][-1]["year"] if results and results[0]["rows"] else _current_year(assumptions),
        "strategies": results,
    }
