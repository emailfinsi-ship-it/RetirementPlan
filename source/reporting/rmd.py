"""Required Minimum Distributions (RMDs) -- the IRS-mandated minimum
withdrawal from a tax-deferred retirement account (401k/Traditional IRA)
once the owner reaches a certain age, used by source.reporting.
monte_carlo's three-pool withdrawal engine to force part of each
simulated year's tax-deferred withdrawal once that age is reached,
rather than letting the simulation withdraw from whichever pool the
ordering rule would otherwise prefer.

Two pieces of real IRS guidance, both verified against current sources
(IRS.gov, Fidelity's published Uniform Lifetime Table, and cross-checked
against a second independent source) rather than approximated:

RMD_AGE_BY_BIRTH_YEAR -- SECURE 2.0 Act pushed the RMD starting age from
73 to 75, but only for people born in 1960 or later (born 1951-1959:
still 73, through 2032; born 1960+: 75, starting 2033). Anyone born
before 1951 has an even older starting age (72, pre-SECURE-2.0) --
irrelevant here, since by this program's earliest simulated year (2026
or later) that cohort is already well past any of these thresholds, so
treating them the same as the 1951-1959 cohort (73) is exact for every
year this program will ever actually simulate.

UNIFORM_LIFETIME_TABLE -- the IRS's own age -> life-expectancy-factor
divisor table (Uniform Lifetime Table, effective for distributions
after 2021), used for the ordinary "you and your spouse aren't more
than 10 years apart" case, which covers the vast majority of retirees
and is what every other online RMD calculator defaults to as well. This
program doesn't model the (rarer) sole-spousal-beneficiary-more-than-10-
years-younger case, which uses a different table (Joint Life and Last
Survivor Expectancy) -- a documented simplification, not an oversight.
"""

from __future__ import annotations

# age -> distribution period divisor. RMD = tax-deferred balance (as of
# the prior year-end -- this program uses "balance entering the
# simulated year, i.e. before that year's return is applied" as its
# stand-in, since it doesn't track a separate December 31 snapshot) /
# divisor. Ages 72-119 are the table's actual published entries; 120 and
# above are all pinned to the table's final divisor (2.0), same
# convention the IRS table itself uses ("120 and over").
UNIFORM_LIFETIME_TABLE: dict[int, float] = {
    72: 27.4, 73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9, 78: 22.0, 79: 21.1,
    80: 20.2, 81: 19.4, 82: 18.5, 83: 17.7, 84: 16.8, 85: 16.0, 86: 15.2, 87: 14.4,
    88: 13.7, 89: 12.9, 90: 12.2, 91: 11.5, 92: 10.8, 93: 10.1, 94: 9.5, 95: 8.9,
    96: 8.4, 97: 7.8, 98: 7.3, 99: 6.8, 100: 6.4, 101: 6.0, 102: 5.6, 103: 5.2,
    104: 4.9, 105: 4.6, 106: 4.3, 107: 4.1, 108: 3.9, 109: 3.7, 110: 3.5, 111: 3.4,
    112: 3.3, 113: 3.1, 114: 3.0, 115: 2.9, 116: 2.8, 117: 2.7, 118: 2.5, 119: 2.3,
}
_MAX_TABLE_AGE = max(UNIFORM_LIFETIME_TABLE)
_MIN_TABLE_AGE = min(UNIFORM_LIFETIME_TABLE)
_LAST_DIVISOR = 2.0  # "120 and over" per the IRS table


def rmd_age_for_birth_year(birth_year: int) -> int:
    """73 for anyone born 1959 or earlier (this simulation only ever
    covers years where that cohort's RMD age is already 73, whether
    their real original threshold was 72 or 73 -- see module docstring),
    75 for anyone born 1960 or later (SECURE 2.0, effective 2033)."""
    return 75 if birth_year >= 1960 else 73


def _divisor_for_age(age: int) -> float | None:
    """None below the table's first age (nothing required yet); the
    table's own value within range; pinned to the final divisor at or
    above the table's last age (matches the IRS table's "120 and over"
    row -- ages that high essentially never come up in a real plan
    horizon, but the fallback keeps a long horizon from erroring)."""
    if age < _MIN_TABLE_AGE:
        return None
    if age > _MAX_TABLE_AGE:
        return _LAST_DIVISOR
    return UNIFORM_LIFETIME_TABLE[age]


def required_minimum_distribution(balance: float, age: int, birth_year: int) -> float:
    """The RMD dollar amount for a tax-deferred balance at a given age,
    given the account owner's birth year (only used to pick the 73-vs-75
    starting threshold -- see rmd_age_for_birth_year). 0.0 before that
    age, for a balance <= 0, or for an age below the table's own range
    entirely (shouldn't happen once past the 73/75 threshold, but
    guards against a nonsensical age rather than raising)."""
    if balance <= 0:
        return 0.0
    if age < rmd_age_for_birth_year(birth_year):
        return 0.0
    divisor = _divisor_for_age(age)
    if not divisor:
        return 0.0
    return balance / divisor
