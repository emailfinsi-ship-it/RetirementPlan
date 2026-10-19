"""Monte Carlo retirement-drawdown simulation, run fresh from this
program's own data every time the Monte Carlo tab is opened -- unlike the
retired FamilyFinanceTracker feature, which only ever displayed whatever
percentile band happened to already be pasted into the old workbook (and,
for this user's real workbook, that band was empty -- a bug this rebuild
fixes by computing it instead of reading it).

Model: starting from the Monte Carlo starting balance (Net Liquid Asset
-- every Asset-tab row checked "In the plan?", net of liabilities --
see source.reporting.aggregate.build_summary's net_liquid_asset), each of
`iterations` simulated paths draws a
random annual return ~ Normal(expected_return, return_volatility) for
`plan_horizon_years` years starting at `current_year`. Each year, that
year's expense need (source.common.db's expenses line items, summed for
whichever rows cover that year -- see annual_expense_need) is withdrawn,
net of the Income tab's own line items checked "In simulation?"
(annual_income_need -- rental, Social Security, a pension, ...) and the
older flat `annual_income_offset` assumption, which still stacks on top
for anyone who'd rather type one manual number. A line item on either tab with
`inflates` set grows from its own `base_year` by the `inflation_rate`
assumption every simulated year (matches the original workbook's
"(2026 basis)" budget table, whose Fixed/Variable cost rows and rental
income all grew with inflation while Social Security, once started, held
flat). A path that hits zero is clamped there (no borrowing) and counted
as depleted.

Alongside that random simulation, run_historical_stress_test() below
runs a second, deterministic model: the same starting balance and
withdrawal schedule, but replaying actual historical S&P 500 annual
total returns (dividends reinvested) for a handful of real past
downturns -- same feature as the old workbook's "Historical Stress
Test" tab, carried over so a specific "what if 2008 happened again
starting now" question has an answer, not just a percentile band.

Every method above also subtracts an estimated income-tax bill on top
of that year's withdrawal need, via estimate_annual_drawdown_tax()
below -- retirement-account withdrawals are ordinary taxable income,
and modeling the balance as if that tax didn't exist overstates how
long the money lasts. It assumes the entire withdrawal comes from a
pre-tax account (401k/IRA) -- the simplest of the ways to model this,
and the one this program uses, rather than splitting withdrawals across
pre-tax/Roth/already-taxed brokerage accounts -- and uses actual 2026
federal (IRS) and California (FTB) Married-Filing-Jointly tax brackets,
grown forward by the Inflation % assumption for any later simulated
year. It can be turned off entirely with the "Apply drawdown tax"
checkbox on the Monte Carlo tab's Assumptions form (assumptions key
apply_drawdown_tax) to compare the plan with and without it.

This used to be a single ~1075-line monte_carlo.py file; it's now a
package split along the model's own seams -- line-item withdrawal math
(withdrawal.py), tax brackets (tax.py), the three-pool RMD/withdrawal-
order engine (pools.py), small shared assumption/percentile helpers
(assumptions.py), the random Gaussian/historical-bootstrap engine
(simulation.py), the deterministic historical stress test
(stress_test.py), the fan-chart SVG renderer (chart.py), and the
one-lever-at-a-time tornado sensitivity sweep (sensitivity.py). Nothing
outside this package should need to change: every name any page module,
report, or test previously imported with
`from source.reporting.monte_carlo import X` is re-exported here
unchanged, from the same place.
"""

from __future__ import annotations

from source.reporting.monte_carlo.withdrawal import (
    annual_expense_need,
    annual_income_need,
    annual_line_item_total,
    annual_net_withdrawal_need,
    annual_income_breakdown,
    annual_taxable_income,
    effective_line_item_amount,
    yearly_withdrawal_schedule,
)
from source.reporting.monte_carlo.tax import (
    CA_STANDARD_DEDUCTION_MFJ_2026,
    CA_TAX_BRACKETS_MFJ_2026,
    FEDERAL_LTCG_BRACKETS_MFJ_2026,
    FEDERAL_STANDARD_DEDUCTION_MFJ_2026,
    FEDERAL_TAX_BRACKETS_MFJ_2026,
    _bracket_tax,
    _pool_year_tax,
    _stacked_bracket_tax,
    estimate_annual_drawdown_tax,
)
from source.reporting.monte_carlo.pools import (
    _WITHDRAWAL_ORDER,
    _apply_year_withdrawal,
    _simulate_fill,
)
from source.reporting.monte_carlo.assumptions import (
    _percentile,
    _resolve_birth_year,
    _resolve_early_tax_deferred_age,
    _resolve_gains_fraction,
    _resolve_retirement_year,
    _truthy_assumption,
)
from source.reporting.monte_carlo.simulation import (
    _run_random_simulation,
    run_historical_bootstrap_simulation,
    run_simulation,
    stable_simulation_seed,
)
from source.reporting.monte_carlo.sensitivity import (
    LEVERS,
    run_sensitivity_analysis,
)
from source.reporting.monte_carlo.stress_test import (
    HISTORICAL_STRESS_SCENARIOS,
    _LAST_RECORDED_YEAR,
    _LONG_RUN_AVERAGE_RETURN,
    _SP500_ANNUAL_RETURNS,
    _historical_return,
    run_historical_stress_test,
    sp500_average_return,
    sp500_lookback,
    stress_scenarios,
)
from source.reporting.monte_carlo.chart import (
    _BAND_COLOR,
    _HISTORICAL_BAND_COLOR,
    _money_short,
    render_fan_svg,
)
from source.reporting.monte_carlo.drawdown_schedule import (
    deterministic_drawdown_schedule,
)
from source.reporting.monte_carlo.legacy_planning import (
    CUSTOM_BRACKET_CHOICES,
    EARLY_TAX_DEFERRED_SPENDING_STRATEGIES,
    ROTH_CONVERSION_STRATEGIES,
    compare_roth_conversion_strategies,
    normalize_custom_strategy,
    estimate_default_heir_base_income,
    estimate_heir_tax_on_tax_deferred,
)

__all__ = [
    "annual_expense_need",
    "annual_income_need",
    "annual_income_breakdown",
    "annual_taxable_income",
    "annual_line_item_total",
    "annual_net_withdrawal_need",
    "effective_line_item_amount",
    "yearly_withdrawal_schedule",
    "CA_STANDARD_DEDUCTION_MFJ_2026",
    "CA_TAX_BRACKETS_MFJ_2026",
    "FEDERAL_LTCG_BRACKETS_MFJ_2026",
    "FEDERAL_STANDARD_DEDUCTION_MFJ_2026",
    "FEDERAL_TAX_BRACKETS_MFJ_2026",
    "_bracket_tax",
    "_pool_year_tax",
    "_stacked_bracket_tax",
    "estimate_annual_drawdown_tax",
    "_WITHDRAWAL_ORDER",
    "_apply_year_withdrawal",
    "_simulate_fill",
    "_percentile",
    "_resolve_birth_year",
    "_resolve_early_tax_deferred_age",
    "_resolve_gains_fraction",
    "_resolve_retirement_year",
    "_truthy_assumption",
    "_run_random_simulation",
    "run_historical_bootstrap_simulation",
    "run_simulation",
    "stable_simulation_seed",
    "LEVERS",
    "run_sensitivity_analysis",
    "HISTORICAL_STRESS_SCENARIOS",
    "_LAST_RECORDED_YEAR",
    "_LONG_RUN_AVERAGE_RETURN",
    "_SP500_ANNUAL_RETURNS",
    "_historical_return",
    "sp500_average_return",
    "sp500_lookback",
    "stress_scenarios",
    "run_historical_stress_test",
    "_BAND_COLOR",
    "_HISTORICAL_BAND_COLOR",
    "_money_short",
    "render_fan_svg",
    "deterministic_drawdown_schedule",
    "ROTH_CONVERSION_STRATEGIES",
    "EARLY_TAX_DEFERRED_SPENDING_STRATEGIES",
    "compare_roth_conversion_strategies",
    "normalize_custom_strategy",
    "CUSTOM_BRACKET_CHOICES",
    "estimate_default_heir_base_income",
    "estimate_heir_tax_on_tax_deferred",
]
