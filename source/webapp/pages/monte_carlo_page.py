"""The Monte Carlo Simulation tab: assumption inputs, the forward
simulation fan chart, and the historical-stress-test table.

Named monte_carlo_page (not monte_carlo) so it doesn't collide with
source.reporting.monte_carlo, which does the actual number-crunching
this page renders.
"""

from __future__ import annotations

import html
import random

from source.common import db
from source.reporting import presentation as pres
from source.reporting.aggregate import build_summary
from source.reporting.monte_carlo import (
    _resolve_retirement_year,
    render_fan_svg,
    run_historical_bootstrap_simulation,
    run_historical_stress_test,
    run_sensitivity_analysis,
    run_simulation,
    stable_simulation_seed,
)
from source.reporting.monte_carlo.real_estate_sale_compare import monte_carlo_sale_comparison
from source.webapp.pages import summary_blocks as blocks
from source.webapp.pages.scenarios_card import saved_scenarios_card_html
from source.webapp.render_helpers import _money, _pct, _shell
from source.webapp.render_helpers.sale_cards import sale_comparison_card_html


def _render_monte_carlo_page() -> str:
    s = build_summary()
    assumptions = s["assumptions"]
    starting_balance = s["net_liquid_asset"]
    pools = s["retirement_pools"]
    # Seeded deterministically (see stable_simulation_seed's own
    # docstring) so this top simulation's Success rate/Median ending
    # balance always match the Summary tab's "What if" card -- both call
    # run_simulation with identical starting_balance/pools/assumptions/
    # expenses/income, so leaving this unseeded would make the two tabs
    # independently draw a different set of 1000 random paths and land
    # on two different (if similarly plausible) numbers for what's
    # supposed to be the same simulation of the same plan.
    seed = stable_simulation_seed(
        starting_balance=starting_balance, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=assumptions, pools=pools,
    )
    result = run_simulation(
        starting_balance=starting_balance, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=assumptions,
        pools=pools, rng=random.Random(seed),
    )
    mode = db.dollars_mode()
    display = pres.convert_result(result, assumptions, s["this_year"], mode)
    try:
        birth = int(float(assumptions.get("birth_year")))
    except (TypeError, ValueError):
        birth = None
    chart = render_fan_svg(
        display, width=980, height=340, plain=True, responsive=True,
        retirement_year=_resolve_retirement_year(assumptions), birth_year=birth,
    )
    # A different-but-still-deterministic seed than the Gaussian run above
    # -- reproducible across reloads (same reasoning as that one), but not
    # reusing the exact same random.Random stream for a differently
    # shaped draw (bootstrap resampling vs. a Gaussian draw).
    sp500_result = run_historical_bootstrap_simulation(
        starting_balance=starting_balance, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=assumptions,
        pools=pools, rng=random.Random(seed ^ 0x5DEECE66D),
    )
    sp_display = pres.convert_result(sp500_result, assumptions, s["this_year"], mode)
    stress_result = run_historical_stress_test(
        starting_balance=starting_balance, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=assumptions, pools=pools,
    )
    stress_html = _historical_stress_test_html(stress_result)
    sensitivity = run_sensitivity_analysis(
        starting_balance=starting_balance, expenses=s["expenses"], income=s["income_for_simulation"],
        assumptions=assumptions, pools=pools,
    )
    sensitivity_html = _sensitivity_html(sensitivity)

    tax_on = result.get("apply_drawdown_tax", True)
    tax_tiles = f"""
  <div class="tile"><div class="label">First-year tax (median path)</div><div class="value">{_money(result.get('first_year_tax', 0.0))}</div></div>
  <div class="tile"><div class="label">Total tax over horizon (median path)</div><div class="value">{_money(result.get('yearly_tax_total', 0.0))}</div></div>
""" if tax_on else ""
    has_birth_year = (assumptions.get("birth_year") or "").strip() != ""
    # Real estate equity opted in on the Real Estate Analysis tab
    # (real_estate.include_in_monte_carlo) is a 4th pool the simulation
    # actually draws from -- run_simulation/run_historical_bootstrap_
    # simulation/run_historical_stress_test all ignore `starting_balance`
    # entirely once `pools` is passed (see _run_random_simulation's own
    # comment) and instead walk down sum(pools.values()), so the true
    # money simulated is starting_balance + re_pool, not just
    # starting_balance -- the intro paragraph and tiles below need to
    # say so, or they understate what's actually being drawn down once
    # a property is opted in.
    re_pool = pools.get("real_estate", 0.0)
    total_simulated_balance = starting_balance + re_pool
    re_pool_tile = (
        f'\n  <div class="tile"><div class="label">Real estate (opted in)</div><div class="value">{_money(re_pool)}</div></div>'
    ) if re_pool else ""
    # A single "Starting balance" tile up top showing the true total
    # (Net Liquid Asset + any opted-in real estate) -- so the actual
    # money the simulation draws down is visible at a glance instead of
    # only inferable from the paragraph below or from adding up the
    # per-pool tiles yourself.
    pool_tiles = f"""
  <div class="tile"><div class="label">Starting balance</div><div class="value">{_money(total_simulated_balance)}</div></div>
  <div class="tile"><div class="label">Tax-deferred (401k/Traditional)</div><div class="value">{_money(pools['tax_deferred'])}</div></div>
  <div class="tile"><div class="label">Roth (tax-free)</div><div class="value">{_money(pools['roth'])}</div></div>
  <div class="tile"><div class="label">Taxable (brokerage)</div><div class="value">{_money(pools['taxable'])}</div></div>{re_pool_tile}
"""
    # Built outside the f-string below -- an f-string expression can't
    # contain a backslash (needed here to escape the quotes around
    # "Apply drawdown tax"), which is a hard SyntaxError on the Python
    # versions this program targets (pre-3.12).
    tax_intro_clause = (
        'grossed up for an estimated tax bill on the withdrawal -- current 2026 federal + California '
        'Married-Filing-Jointly brackets, with each pool taxed according to its own tax treatment (below) '
        'rather than assuming the whole thing is pre-tax/401k income, and Required Minimum Distributions '
        'forced from the Tax-deferred pool once you reach RMD age, if you\'ve set a Birth year in '
        'Assumptions -- see the Year-by-year detail table\'s Tax column below, and uncheck "Apply drawdown '
        'tax" in Assumptions to turn this off), '
    ) if tax_on else (
        '(drawdown tax is currently OFF -- check "Apply drawdown tax" in Assumptions below to model '
        'the estimated tax on each year\'s withdrawal, including any Required Minimum Distributions), '
    )
    rmd_note = (
        "" if has_birth_year else
        ' <span class="muted">Set a Birth year in Assumptions below to also model Required Minimum '
        "Distributions (RMDs) from the Tax-deferred pool once you reach RMD age.</span>"
    )
    retirement_year = _resolve_retirement_year(assumptions)
    retirement_year_note = (
        f' <span class="muted">No withdrawal happens in any simulated year before {retirement_year} (your set '
        "Retirement year) -- income is assumed to cover expenses until then.</span>"
        if retirement_year is not None else
        ' <span class="muted">Set a Retirement year in Assumptions below (or on the Summary tab) to skip '
        "withdrawals entirely for the years before you retire.</span>"
    )

    real_estate_pool_clause = (
        f' Plus {_money(re_pool)} of real estate equity opted in on the Real Estate Analysis tab, added as a '
        f'4th, untaxed pool drawn only once those three are exhausted -- {_money(total_simulated_balance)} '
        f'simulated in total (the Starting balance tile above).'
    ) if re_pool else ""
    excluded_from_net_liquid = (
        "insurance cash value and any other unchecked Asset-tab row" if re_pool
        else "real estate equity, insurance cash value, and any unchecked Asset-tab row"
    )
    withdrawal_order_suffix = ", then the opted-in real estate pool last of all" if re_pool else ""

    sale = s["real_estate_sale"]
    sale_card = sale_comparison_card_html(
        sale=sale,
        intro=(
            "The same simulation re-run with every property sold, on the same random market paths so the only "
            "difference is the sale."
        ),
        rows=monte_carlo_sale_comparison(
            keep=result, starting_balance=starting_balance, expenses=s["expenses"],
            income=s["income_for_simulation"], assumptions=assumptions, pools=pools, sale=sale,
            real_estate=s["real_estate"], loan_balances=s["real_estate_loan_balances"], seed=seed,
        ),
    ) if sale["has_properties"] else ""

    spouse_birth_field = (
        f'<label>{html.escape(db.spouse_name())}\'s birth year (for their RMDs)<input name="spouse_birth_year" type="number" '
        f'step="1" placeholder="e.g. 1962" value="{html.escape(str(assumptions.get("spouse_birth_year") or ""))}"></label>'
    ) if db.has_spouse() else ""
    body = f"""
<div class="card-head"><h2 style="margin:0">Monte Carlo simulation</h2>{blocks.dollars_toggle_html(mode)}</div>
<p class="muted small">Thousands of possible market futures for your plan. Ending balances are in {pres.dollars_caption(mode).replace("ending balances in ", "")}.</p>
<details class="how-it-works"><summary>How this works</summary><p class="muted">Starting balance is your Net Liquid Asset ({_money(starting_balance)}) -- the total of every Asset-tab row checked "In Monte Carlo?", net of liabilities (same figure as the Summary tab's Net Liquid Asset tile) -- not full net worth, since {excluded_from_net_liquid} aren't money you'd draw down in retirement unless you opt them in. It's split into three pools by each checked row's Tax treatment (set on the Asset tab): Tax-deferred, Roth, and Taxable, shown below.{real_estate_pool_clause} Each simulated year withdraws that year's net need -- the Income/Expense tab's Expenses total minus the total of Income rows checked "In simulation?", with any row flagged "Inflates" grown from its own Base Year by the Inflation % assumption below -- plus the flat Annual income offset if you've set one, drawn Taxable first, then Tax-deferred, then Roth last{withdrawal_order_suffix} (the conventional tax-efficient order), {tax_intro_clause}and applies a random annual return drawn from the assumptions below to every pool shown above alike.{rmd_note}{retirement_year_note}</p></details>
<div class="tiles">{pool_tiles}</div>
<div class="tiles">
  <div class="tile"><div class="label">{pres.LABEL_CHANCE}</div><div class="value">{pres.percent_display(result['success_rate'])}</div></div>
  <div class="tile"><div class="label">{pres.LABEL_CAUTIOUS}</div><div class="value">{_money(display['p10_ending_balance'])}</div></div>
  <div class="tile"><div class="label">{pres.LABEL_TYPICAL}</div><div class="value">{_money(display['median_ending_balance'])}</div></div>
  <div class="tile"><div class="label">{pres.LABEL_STRONG}</div><div class="value">{_money(display['p90_ending_balance'])}</div></div>
  <div class="tile"><div class="label">Iterations</div><div class="value">{result['iterations']:,}</div></div>
{tax_tiles}</div>
{chart}
<h2>S&amp;P 500 historical-returns simulation</h2>
<details class="how-it-works"><summary>How this works</summary><p class="muted">Same starting balances and the same per-year withdrawal need as the simulation above, but instead of drawing each simulated year's return from the Expected return/Return volatility assumptions, each of the {sp500_result['iterations']:,} paths draws (with replacement) from the {sp500_result['sample_size']} actual recorded S&amp;P 500 annual total returns -- real boom years and real crashes (1931, 2008, 2022, ...) mixed in, not a bell curve. These figures are this method's own 10th-90th percentile ending balance range, grounded in market history rather than this plan's own return assumptions.</p></details>
<p class="note-box"><strong>Read this as a cross-check, not a forecast.</strong> It replays the real S&amp;P 500&#x27;s past years, which were one unusually strong stretch for one country&#x27;s stocks and never include a future shock. A very high result here is a best-case reference; the simulation above (and the stress test below) are the better guide to planning.</p>
<div class="tiles">
  <div class="tile"><div class="label">S&amp;P 500 chance your money lasts</div><div class="value">{pres.percent_display(sp500_result['success_rate'])}</div></div>
  <div class="tile"><div class="label">S&amp;P 500 cautious case</div><div class="value">{_money(sp_display['p10_ending_balance'])}</div></div>
  <div class="tile"><div class="label">S&amp;P 500 typical case</div><div class="value">{_money(sp_display['median_ending_balance'])}</div></div>
  <div class="tile"><div class="label">S&amp;P 500 strong case</div><div class="value">{_money(sp_display['p90_ending_balance'])}</div></div>
</div>
{sale_card}
{stress_html}
{sensitivity_html}
{saved_scenarios_card_html(db.list_scenarios(), assumptions)}
<h2 id="assumptions">Assumptions</h2>
<form class="inline" onsubmit="event.preventDefault();
  var fields = {{}};
  new FormData(this).forEach(function(value, key) {{ fields[key] = value; }});
  fields.apply_drawdown_tax = this.apply_drawdown_tax.checked ? 1 : 0;
  postJSON('/api/assumptions', fields).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Expected return %<input name="expected_return_pct" type="number" step="0.01" value="{_pct(assumptions, 'expected_return', 0.06)}"></label>
  <label>Return volatility %<input name="return_volatility_pct" type="number" step="0.01" value="{_pct(assumptions, 'return_volatility', 0.12)}"></label>
  <label>Inflation %<input name="inflation_rate_pct" type="number" step="0.01" value="{_pct(assumptions, 'inflation_rate', 0.03)}"></label>
  <label>Plan horizon (years)<input name="plan_horizon_years" type="number" value="{html.escape(str(assumptions.get('plan_horizon_years', 40)))}"></label>
  <label>Iterations<input name="iterations" type="number" value="{html.escape(str(assumptions.get('iterations', 1000)))}"></label>
  <label>Annual income offset<input name="annual_income_offset" type="number" step="0.01" value="{html.escape(str(assumptions.get('annual_income_offset', 0)))}"></label>
  <label>{html.escape(db.self_name())}'s birth year (for RMDs)<input name="birth_year" type="number" step="1" placeholder="e.g. 1960" value="{html.escape(str(assumptions.get('birth_year') or ''))}"></label>
  {spouse_birth_field}
  <label>Retirement year<input name="retirement_year" type="number" step="1" placeholder="e.g. 2035" value="{html.escape(str(assumptions.get('retirement_year') or ''))}"></label>
  <label>Taxable gains %<input name="taxable_gains_fraction_pct" type="number" step="1" value="{_pct(assumptions, 'taxable_gains_fraction', 0.4)}"></label>
  <label style="flex-direction: row; align-items: center; gap: 6px;"><input type="checkbox" name="apply_drawdown_tax" value="1" style="width:auto;"{' checked' if _assumption_checked(assumptions, 'apply_drawdown_tax') else ''}> Apply drawdown tax (Fed + CA, current brackets)</label>
  <button type="submit" class="primary">Save &amp; re-run</button>
</form>
<p class="muted">Birth year is used only to time Required Minimum Distributions (RMDs) from the Tax-deferred pool -- leave it blank to skip RMD modeling entirely. Retirement year zeroes out every simulated year's withdrawal before it -- income is assumed to cover expenses until then -- across this simulation, the historical stress test below, and the Drawdown Planning tab; leave it blank to withdraw starting this year, same as before this field existed. Taxable gains % is the assumed fraction of any Taxable-brokerage withdrawal that's a capital gain rather than a return of already-taxed cost basis (this program doesn't track per-lot cost basis, so this is a deliberate, adjustable simplification) -- only the gains portion is taxed, at federal long-term capital-gains rates plus California's ordinary rates (California has no capital-gains preference).</p>
"""
    return _shell(title="Monte Carlo Simulation", active="monte-carlo.html", body=body)

def _stress_test_label_short(label: str) -> str:
    """"Great Depression (1929)" -> "Great Depression" -- the parenthetical
    is spelled out in the Scenario Summary table and the section intro,
    so the wide Year-by-Year Detail table's column headers don't need to
    repeat it twice per scenario (once for Return, once for Balance)."""
    return label.split(" (")[0]

def _historical_stress_test_html(result: dict) -> str:
    """Renders both halves of the historical stress test: a short
    Scenario Summary table (depleted? when? ending balance?) and the
    full Year-by-Year Detail table -- same two-part layout as the
    original workbook's own "Historical Stress Test" tab.

    In legacy (single-balance) mode, the withdrawal schedule -- and so
    Tax and Total Withdrawal -- is the same for every scenario in a
    given year (it doesn't depend on any scenario's own returns), so
    those two columns are shared and each scenario only needs a
    Return/Balance pair. In three-pool/RMD mode
    (result["per_scenario_tax"]), the Required Minimum Distribution --
    and so the tax and total withdrawal -- depends on each scenario's
    own path (its own Tax-deferred balance, driven by its own
    returns), so Tax and Total Withdrawal move out of the shared
    columns and into each scenario's own four-column group alongside
    Return and Balance."""
    summary_rows = "".join(
        f'<tr><td>{html.escape(sc["label"])}</td>'
        f'<td>{"Yes" if sc["depleted"] else "No"}</td>'
        f'<td>{sc["depleted_year"] if sc["depleted_year"] else "--"}</td>'
        f'<td class="num">{_money(sc["ending_balance"])}</td></tr>'
        for sc in result["scenarios"]
    )

    # Total Expense and Total Income are the two raw, un-netted tab
    # totals for that year (both inflation-adjusted per each row's own
    # Base Year/Inflates setting) -- shown right next to each other so
    # they're easy to compare directly (e.g. an Income row with
    # "Inflates" checked, like a COLA'd Social Security benefit, grows
    # year over year same as an inflating Expense row would -- seeing
    # both columns side by side makes that visible instead of surprising).
    # Yearly Drawdown is what every scenario needs after Income: Total
    # Expense minus Total Income minus the flat Annual income offset
    # assumption, if set -- so Total Expense - Total Income (- the
    # offset, if any) should equal Yearly Drawdown on every row, a quick
    # way to check the numbers. These three are scenario/return-
    # independent in both modes, so they're always one shared column
    # group, never repeated per scenario.
    yearly_total_expense = result.get("yearly_total_expense") or []
    yearly_income = result.get("yearly_income") or []
    yearly_needs = result.get("yearly_needs") or []
    per_scenario_tax = bool(result.get("per_scenario_tax"))

    # Which of result["years"]' indices actually get a row in the
    # Year-by-year detail table below. Every year is still computed above
    # and each scenario's own path/balance above still walks through every
    # pre-retirement year internally (so a scenario's 2028 balance still
    # reflects 2026/2027's returns even though those rows aren't shown) --
    # this only trims which rows *render*, per the user's own request to
    # stop showing years that withdraw nothing because they're before the
    # Retirement year. Falls back to every year if that would hide the
    # whole table (e.g. a Retirement year past this plan's horizon), so
    # the table is never left empty.
    retirement_year_for_table = result.get("retirement_year")
    all_indices = list(range(len(result["years"])))
    if retirement_year_for_table is not None:
        visible_indices = [i for i in all_indices if result["years"][i] >= retirement_year_for_table]
        if not visible_indices:
            visible_indices = all_indices
    else:
        visible_indices = all_indices
    hidden_year_count = len(all_indices) - len(visible_indices)
    visible_years = [(i, result["years"][i]) for i in visible_indices]

    if per_scenario_tax:
        # Tax (Fed+CA) is the estimated tax on that scenario's own
        # withdrawal (each pool taxed per its own tax treatment, with
        # any Required Minimum Distribution forced from the
        # Tax-deferred pool once RMD age is reached) -- 0 for every row
        # when "Apply drawdown tax" is unchecked below. Total Withdrawal
        # (Yearly Drawdown + that scenario's Tax) is what actually comes
        # out of that scenario's balance -- the figure its own Balance
        # column reflects. Both depend on this scenario's own returns
        # (via its own running Tax-deferred balance), so they live in
        # this scenario's own column group rather than the shared one.
        detail_header_cells = "".join(
            f'<th class="num">{html.escape(_stress_test_label_short(sc["label"]))} Return</th>'
            f'<th class="num">{html.escape(_stress_test_label_short(sc["label"]))} Tax</th>'
            f'<th class="num">{html.escape(_stress_test_label_short(sc["label"]))} Withdrawal</th>'
            f'<th class="num">{html.escape(_stress_test_label_short(sc["label"]))} Balance</th>'
            for sc in result["scenarios"]
        )
        detail_rows = "".join(
            f'<tr><td>{year}</td>'
            f'<td class="num">{_money(yearly_total_expense[i]) if i < len(yearly_total_expense) else ""}</td>'
            f'<td class="num">{_money(yearly_income[i]) if i < len(yearly_income) else ""}</td>'
            f'<td class="num">{_money(yearly_needs[i]) if i < len(yearly_needs) else ""}</td>'
            + "".join(
                f'<td class="num">{sc["path"][i]["return"] * 100:.2f}%</td>'
                f'<td class="num">{_money(sc["yearly_tax"][i]) if i < len(sc.get("yearly_tax") or []) else ""}</td>'
                f'<td class="num">{_money(sc["yearly_total_withdrawal"][i]) if i < len(sc.get("yearly_total_withdrawal") or []) else ""}</td>'
                f'<td class="num">{_money(sc["path"][i]["balance"])}</td>'
                for sc in result["scenarios"]
            )
            + '</tr>'
            for i, year in visible_years
        )
        detail_thead_row = (
            '<th>Year</th><th class="num">Total Expense</th><th class="num">Total Income</th>'
            f'<th class="num">Yearly Drawdown</th>{detail_header_cells}'
        )
        tax_note = (
            "Tax (Fed+CA) and Total Withdrawal are shown per scenario here rather than shared, because each "
            "scenario's own returns drive its own Tax-deferred balance -- and so its own Required Minimum "
            "Distribution and tax bill -- once RMDs kick in; each pool is taxed according to its own tax treatment "
            "(Tax-deferred: ordinary income, Taxable: the estimated gains fraction at capital-gains rates, Roth: "
            "untaxed), using current (2026) federal and California Married-Filing-Jointly brackets -- uncheck "
            "\"Apply drawdown tax\" below to model without it."
            if result.get("apply_drawdown_tax", True) else
            "Tax is $0 on every row -- \"Apply drawdown tax\" is unchecked below, so each scenario's Total Withdrawal equals Yearly Drawdown."
        )
    else:
        detail_header_cells = "".join(
            f'<th class="num">{html.escape(_stress_test_label_short(sc["label"]))} Return</th>'
            f'<th class="num">{html.escape(_stress_test_label_short(sc["label"]))} Balance</th>'
            for sc in result["scenarios"]
        )
        # Tax (Fed+CA) is the estimated federal + California income tax
        # on that withdrawal (source.reporting.monte_carlo.
        # estimate_annual_drawdown_tax -- 0 for every row when "Apply
        # drawdown tax" is unchecked below), and Total Withdrawal
        # (Yearly Drawdown + Tax) is what actually comes out of the
        # balance each scenario -- the figure the Balance columns below
        # reflect. Both are scenario/return-independent in legacy mode
        # (see yearly_withdrawal_schedule), so they're one column group
        # shared by every scenario's row, not repeated per scenario the
        # way Return/Balance are.
        yearly_tax = result.get("yearly_tax") or []
        yearly_total_withdrawal = result.get("yearly_total_withdrawal") or []
        detail_rows = "".join(
            f'<tr><td>{year}</td>'
            f'<td class="num">{_money(yearly_total_expense[i]) if i < len(yearly_total_expense) else ""}</td>'
            f'<td class="num">{_money(yearly_income[i]) if i < len(yearly_income) else ""}</td>'
            f'<td class="num">{_money(yearly_needs[i]) if i < len(yearly_needs) else ""}</td>'
            f'<td class="num">{_money(yearly_tax[i]) if i < len(yearly_tax) else ""}</td>'
            f'<td class="num">{_money(yearly_total_withdrawal[i]) if i < len(yearly_total_withdrawal) else ""}</td>'
            + "".join(
                f'<td class="num">{sc["path"][i]["return"] * 100:.2f}%</td>'
                f'<td class="num">{_money(sc["path"][i]["balance"])}</td>'
                for sc in result["scenarios"]
            )
            + '</tr>'
            for i, year in visible_years
        )
        detail_thead_row = (
            '<th>Year</th><th class="num">Total Expense</th><th class="num">Total Income</th>'
            f'<th class="num">Yearly Drawdown</th><th class="num">Tax (Fed+CA)</th><th class="num">Total Withdrawal</th>{detail_header_cells}'
        )
        tax_note = (
            "Tax (Fed+CA) assumes the entire withdrawal is ordinary taxable income from a pre-tax account (401k/IRA), "
            "using current (2026) federal and California Married-Filing-Jointly tax brackets, grown by the Inflation % "
            "assumption for later years -- uncheck \"Apply drawdown tax\" below to model without it."
            if result.get("apply_drawdown_tax", True) else
            "Tax (Fed+CA) is $0 on every row -- \"Apply drawdown tax\" is unchecked below, so Total Withdrawal equals Yearly Drawdown."
        )

    hidden_years_note_html = (
        f'<p class="muted">Years before {retirement_year_for_table} (your set Retirement year) are omitted below -- '
        "nothing withdraws in them, so there's nothing to see, though the scenarios' balances from "
        f"{retirement_year_for_table} on still reflect those years' own returns.</p>"
        if hidden_year_count else ""
    )
    return f"""
<h2>What if markets fall? Historical recession stress test</h2>
<p class="muted">A second, deterministic view alongside the random simulation above: each scenario replays actual S&amp;P 500 annual total returns (dividends reinvested) for a real historical downturn, starting at your plan's first year ({result['years'][0] if result['years'] else ''}), against the same starting balance and the same per-year withdrawal need (Income/Expense tab) -- withdrawals aren't re-solved per scenario, so the shared columns below are directly comparable across scenarios. Total Expense and Total Income are that year's Expense- and Income-tab totals on their own (inflation-adjusted per each row's own Base Year/Inflates setting -- an income row like Social Security can grow year over year too, if you've checked Inflates on it); Yearly Drawdown nets the two against each other (plus the flat Annual income offset assumption, if set). {tax_note} Years after {result['last_recorded_year']} (not yet on record) use a flat 10%/year placeholder. The last two scenarios are flat reference lines rather than crashes: your plan's own Expected return assumption, and the S&amp;P 500's compound average over every year on record.</p>
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th>Scenario</th><th>Depleted?</th><th>Year depleted</th><th class="num">Ending balance</th></tr></thead>
<tbody>{summary_rows}</tbody>
</table>
</div>
<h3 style="font-size:13px; margin:20px 0 4px 0;">Year-by-year detail</h3>
{hidden_years_note_html}
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr>{detail_thead_row}</tr></thead>
<tbody>{detail_rows}</tbody>
</table>
</div>
"""

def _success_rate_cell(rate: float, baseline: float) -> str:
    """Colors a lever's low/high success rate green if it's at least as
    good as the plan's own baseline, amber otherwise -- same status-ok/
    status-warn convention as Budget vs Actual's variance cells, just
    keyed off "did this direction help or hurt" instead of "over/under
    budget"."""
    css_class = "status-ok" if rate >= baseline else "status-warn"
    return f'<span class="{css_class}">{rate * 100:.0f}%</span>'


def _tornado_track_html(row: dict, baseline_pct: float) -> str:
    """A single horizontal range bar spanning this lever's low- and
    high-scenario success rate (whichever end is smaller/larger), on a
    shared 0-100% success-rate axis, with a dark tick marking the plan's
    own baseline success rate for reference -- the classic "tornado
    diagram" shape falls out once every lever's bar is drawn on the same
    axis and the rows are already sorted by swing (widest first, done by
    run_sensitivity_analysis itself)."""
    low_pct = row["low_success_rate"] * 100
    high_pct = row["high_success_rate"] * 100
    left = max(0.0, min(low_pct, high_pct))
    right = min(100.0, max(low_pct, high_pct))
    width = max(right - left, 0.8)
    # #2a78d6 -- the same first categorical color every donut/bar chart
    # on this page's siblings starts with (source.webapp.render_helpers.
    # charts._DONUT_COLORS[0]); not imported directly since this is the
    # only mark on this page that isn't built through that module.
    return f"""<div style="position:relative; height:14px; background:var(--border); border-radius:4px;">
<div style="position:absolute; left:{left:.1f}%; width:{width:.1f}%; height:100%; border-radius:4px; background:#2a78d6;"></div>
<div style="position:absolute; left:{baseline_pct:.1f}%; top:-2px; width:2px; height:18px; background:var(--ink);" title="Baseline success rate: {baseline_pct:.0f}%"></div>
</div>"""


def _sensitivity_html(sensitivity: dict) -> str:
    """The "what moves the needle" tornado view: holds every input fixed
    at the plan's own baseline and perturbs one lever at a time (see
    source.reporting.monte_carlo.sensitivity.LEVERS) to see how far
    Success rate swings, sorted widest-swing-first so the tornado shape
    is visible at a glance -- answers "which assumption is this plan
    actually most sensitive to", which a single point estimate (the
    tiles above) can't."""
    baseline = sensitivity["baseline_success_rate"]
    baseline_pct = baseline * 100
    rows_html = "".join(
        f'<tr><td>{html.escape(row["label"])}</td>'
        f'<td class="muted">{html.escape(row["swing_label"])}</td>'
        f'<td style="min-width:160px;">{_tornado_track_html(row, baseline_pct)}</td>'
        f'<td class="num">{_success_rate_cell(row["low_success_rate"], baseline)}</td>'
        f'<td class="num">{_success_rate_cell(row["high_success_rate"], baseline)}</td></tr>'
        for row in sensitivity["rows"]
    )
    return f"""
<h2>Sensitivity: what moves the needle</h2>
<p class="muted">Same simulation as above, run again for each row below with exactly one input nudged up and down (everything else held at this plan's own assumptions) -- sorted by how far Success rate swings, biggest first. This plan's baseline Success rate is <strong>{baseline_pct:.0f}%</strong> (the dark tick on each bar); green means that direction helped, amber means it hurt. "Expense/income level" scales every Expense/Income-tab line item by the same percentage, holding the Assumptions form's own numbers fixed.</p>
<div style="overflow-x:auto">
<table class="sortable">
<thead><tr><th>Lever</th><th>Swing tested</th><th>Low vs. high success rate</th><th class="num">Low</th><th class="num">High</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
</div>
"""


def _assumption_checked(assumptions: dict, key: str, default: bool = True) -> bool:
    """Same '1'/'0'-string convention as source.reporting.monte_carlo's
    _truthy_assumption -- used here just to decide whether a checkbox in
    the Assumptions form (e.g. Apply drawdown tax) renders `checked`."""
    raw = assumptions.get(key)
    if raw in (None, ""):
        return default
    return str(raw).strip().lower() not in ("0", "false", "no")
