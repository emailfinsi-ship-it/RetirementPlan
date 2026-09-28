"""Estimated income tax on a retirement withdrawal -- both the
single-balance model's "treat the whole withdrawal as ordinary income"
shortcut (estimate_annual_drawdown_tax, used by simulation.py's and
stress_test.py's `pools is None` branch) and the three-pool engine's
more detailed ordinary-income/capital-gains split (_pool_year_tax, used
by pools.py's _apply_year_withdrawal). Both use the same actual 2026
federal (IRS) and California (FTB) Married-Filing-Jointly tax brackets
below, grown forward by the plan's Inflation % assumption for any later
simulated year -- see estimate_annual_drawdown_tax's own docstring for
the fixed-point gross-up this needs (paying the tax bill itself
requires withdrawing more, which is itself taxable).
"""

from __future__ import annotations


_TAX_BRACKET_BASE_YEAR = 2026


FEDERAL_TAX_BRACKETS_MFJ_2026: tuple[tuple[float | None, float], ...] = (
    (24_800.0, 0.10),
    (100_800.0, 0.12),
    (211_400.0, 0.22),
    (403_550.0, 0.24),
    (512_450.0, 0.32),
    (768_700.0, 0.35),
    (None, 0.37),
)

FEDERAL_STANDARD_DEDUCTION_MFJ_2026 = 32_200.0


CA_TAX_BRACKETS_MFJ_2026: tuple[tuple[float | None, float], ...] = (
    (22_158.0, 0.01),
    (52_528.0, 0.02),
    (82_904.0, 0.04),
    (115_084.0, 0.06),
    (145_448.0, 0.08),
    (742_958.0, 0.093),
    (891_542.0, 0.103),
    (1_000_000.0, 0.113),
    (1_485_906.0, 0.123),
    (None, 0.133),
)

CA_STANDARD_DEDUCTION_MFJ_2026 = 11_412.0


FEDERAL_LTCG_BRACKETS_MFJ_2026: tuple[tuple[float | None, float], ...] = (
    (98_900.0, 0.0),
    (613_700.0, 0.15),
    (None, 0.20),
)



def _bracket_tax(taxable_income: float, brackets: tuple) -> float:
    """Textbook progressive/marginal tax: each bracket's rate applies
    only to the slice of `taxable_income` between the previous bracket's
    upper bound and this one's, never to the whole amount at the top
    rate. `taxable_income` is assumed already >= 0 (net of any standard
    deduction) -- callers floor it themselves."""
    if taxable_income <= 0:
        return 0.0
    tax = 0.0
    lower = 0.0
    for upper, rate in brackets:
        if upper is None or taxable_income <= upper:
            tax += (taxable_income - lower) * rate
            break
        tax += (upper - lower) * rate
        lower = upper
    return tax



def _marginal_rate(taxable_income: float, brackets: tuple) -> float:
    """The rate that applies to the NEXT dollar of `taxable_income` in
    `brackets` -- i.e. which bucket taxable_income itself falls into,
    not the average/effective rate _bracket_tax's total implies.
    Negative or zero income is pinned to the bottom bracket's own rate
    (every bracket table here starts at 0, so there's no rate below the
    first one to return instead) -- used by source.reporting.
    monte_carlo.legacy_planning to show 'what bracket is this income
    level in' as a single readable number."""
    for upper, rate in brackets:
        if upper is None or taxable_income <= upper:
            return rate
    return brackets[-1][1]



def _stacked_bracket_tax(base_taxable: float, additional: float, brackets: tuple) -> float:
    """Tax on just the `additional` slice of income, given that
    `base_taxable` of some OTHER kind of income already fills the
    brackets below it -- the standard IRS "stacking" rule for how
    long-term capital gains are taxed on top of ordinary income (the
    IRS's own Qualified Dividends and Capital Gain Tax Worksheet works
    the same way): ordinary income occupies the bottom of the LTCG
    brackets without itself being taxed at LTCG rates, so a taxpayer
    already in the 15% LTCG bracket from ordinary income alone pays 15%
    on their first dollar of gains, not 0%. Equivalent to
    _bracket_tax(base_taxable + additional) - _bracket_tax(base_taxable)
    against the SAME bracket table -- both `base_taxable` and
    `additional` are assumed already >= 0."""
    if additional <= 0:
        return 0.0
    return _bracket_tax(base_taxable + additional, brackets) - _bracket_tax(base_taxable, brackets)



def estimate_annual_drawdown_tax(net_need: float, year: int, inflation_rate: float = 0.0) -> float:
    """Estimated federal + California income tax owed on a year's
    retirement withdrawal, assuming the ENTIRE Yearly Drawdown is
    ordinary taxable income from a pre-tax account (401k/IRA) -- see the
    module docstring. Uses the actual 2026 IRS and California FTB
    Married-Filing-Jointly brackets/standard deductions above, both
    grown from _TAX_BRACKET_BASE_YEAR to `year` by `inflation_rate` --
    the same "grows every simulated year" treatment this module already
    gives an inflating expense/income row, and a reasonable stand-in for
    the way the IRS and FTB themselves CPI-adjust brackets and
    deductions annually.

    This grosses the withdrawal up rather than taxing net_need directly:
    paying the tax bill itself requires withdrawing MORE, which is
    itself taxable, so the true amount withdrawn (call it G) satisfies
    G - tax(G) == net_need, not tax(net_need) == the answer. Solved by
    fixed-point iteration (G := net_need + tax(G), repeated) -- tax(G)'s
    marginal rate is always well under 1, so this is a contraction that
    converges to float precision in well under the 12 iterations used
    here. Returns just the tax portion (G - net_need); never negative,
    0.0 for a net_need that's already <= 0 (a year Income/the offset
    alone covers, with nothing left to withdraw)."""
    if net_need <= 0:
        return 0.0
    growth = (1.0 + inflation_rate) ** (year - _TAX_BRACKET_BASE_YEAR)
    fed_deduction = FEDERAL_STANDARD_DEDUCTION_MFJ_2026 * growth
    ca_deduction = CA_STANDARD_DEDUCTION_MFJ_2026 * growth
    fed_brackets = tuple(
        (None if upper is None else upper * growth, rate) for upper, rate in FEDERAL_TAX_BRACKETS_MFJ_2026
    )
    ca_brackets = tuple(
        (None if upper is None else upper * growth, rate) for upper, rate in CA_TAX_BRACKETS_MFJ_2026
    )

    def _tax_on(gross: float) -> float:
        return (
            _bracket_tax(max(0.0, gross - fed_deduction), fed_brackets)
            + _bracket_tax(max(0.0, gross - ca_deduction), ca_brackets)
        )

    gross = net_need
    for _ in range(12):
        gross = net_need + _tax_on(gross)
    return gross - net_need



# Tax on one simulated year's withdrawal under the three-pool engine
# (pools.py) -- see pools.py's own module docstring for how RMD/
# withdrawal-order/tax fit together; this is just the tax-calculation
# piece of that engine, kept here next to estimate_annual_drawdown_tax
# since both share the same bracket tables and fixed-point gross-up idea.
def _pool_year_tax(*, ordinary_income: float, gains_income: float, year: int, inflation_rate: float) -> float:
    """Federal + California tax on one simulated year's withdrawal,
    split by kind rather than estimate_annual_drawdown_tax's "treat the
    whole thing as ordinary income" shortcut: `ordinary_income` (a
    Tax-deferred withdrawal, including any RMD) is taxed as ordinary
    income both federally and by California; `gains_income` (the
    assumed-gains portion of a Taxable withdrawal) is taxed at
    California's ordinary rates too (the FTB has no capital-gains
    preference -- it taxes gains as ordinary income) but at the FEDERAL
    LTCG brackets, stacked on top of `ordinary_income` per the standard
    IRS stacking rule (see _stacked_bracket_tax -- ordinary income fills
    the LTCG brackets from the bottom without itself being taxed at
    LTCG rates). Both brackets/deductions are grown from
    _TAX_BRACKET_BASE_YEAR to `year` by `inflation_rate`, same
    convention as estimate_annual_drawdown_tax above."""
    growth = (1.0 + inflation_rate) ** (year - _TAX_BRACKET_BASE_YEAR)
    fed_deduction = FEDERAL_STANDARD_DEDUCTION_MFJ_2026 * growth
    ca_deduction = CA_STANDARD_DEDUCTION_MFJ_2026 * growth
    fed_ordinary_brackets = tuple(
        (None if upper is None else upper * growth, rate) for upper, rate in FEDERAL_TAX_BRACKETS_MFJ_2026
    )
    fed_ltcg_brackets = tuple(
        (None if upper is None else upper * growth, rate) for upper, rate in FEDERAL_LTCG_BRACKETS_MFJ_2026
    )
    ca_brackets = tuple(
        (None if upper is None else upper * growth, rate) for upper, rate in CA_TAX_BRACKETS_MFJ_2026
    )
    fed_ordinary_taxable = max(0.0, ordinary_income - fed_deduction)
    fed_tax = _bracket_tax(fed_ordinary_taxable, fed_ordinary_brackets)
    fed_tax += _stacked_bracket_tax(fed_ordinary_taxable, gains_income, fed_ltcg_brackets)
    ca_taxable = max(0.0, ordinary_income + gains_income - ca_deduction)
    ca_tax = _bracket_tax(ca_taxable, ca_brackets)
    return fed_tax + ca_tax
