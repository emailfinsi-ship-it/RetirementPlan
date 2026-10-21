"""The Summary tab: net worth tiles, asset/liability breakdown, and the
"what does this actually mean" insight cards underneath them."""

from __future__ import annotations

import html

import random

from source.common import backup, db, linked_data
from source.reporting.aggregate import build_summary
from source.reporting.plan_health import plan_health_items
from source.reporting import advice, alerts, data_check
from source.reporting import presentation as pres, progress
from source.reporting.monte_carlo import _resolve_retirement_year, run_simulation, stable_simulation_seed
from source.reporting.monte_carlo.drawdown_schedule import deterministic_drawdown_schedule
from source.webapp.pages import summary_blocks as blocks
from source.webapp.pages.asset import _liquid_and_total_points
from source.webapp.render_helpers import (
    _bar_chart_html,
    _donut_chart_html,
    _grouped_slices,
    _line_chart_html,
    _money,
    _pct,
    _shell,
)


def build_plan_views() -> dict:
    """Everything the Summary page and the printable plan report both show,
    computed once so the two can never disagree."""
    s = build_summary()
    assumptions = s["assumptions"]
    mode = db.dollars_mode()
    starting_balance = s["net_liquid_asset"]
    # Seeded deterministically (see stable_simulation_seed's own
    # docstring) so the chance-your-money-lasts figures here always match
    # the Will my money last? tab's own top simulation -- both call run_simulation
    # with identical starting_balance/pools/assumptions/expenses/income.
    mc_seed = stable_simulation_seed(
        starting_balance=starting_balance, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=assumptions,
        pools=s["retirement_pools"],
    )
    mc_result = run_simulation(
        starting_balance=starting_balance, expenses=s["expenses"], income=s["income_for_simulation"], assumptions=assumptions,
        pools=s["retirement_pools"], rng=random.Random(mc_seed),
    )
    display_result = pres.convert_result(mc_result, assumptions, s["this_year"], mode)
    retirement_year = _resolve_retirement_year(assumptions)
    if retirement_year is None:
        retirement_text = "Retirement year not set"
    else:
        years_away = retirement_year - s["this_year"]
        retirement_text = f"Retirement year {retirement_year} (" + (
            f"{years_away} year{'s' if years_away != 1 else ''} away" if years_away > 0
            else "this year" if years_away == 0 else f"{-years_away} year{'s' if years_away != -1 else ''} into retirement"
        ) + ")"
    empty_plan = not s["assets"] and not s["real_estate"] and not s["expenses"]
    schedule = None
    if not empty_plan:
        schedule_assumptions = {**assumptions, "spouse_tax_deferred_share": s["drawdown_spouse_tax_deferred_share"]}
        schedule = deterministic_drawdown_schedule(
            pools=s["drawdown_pools"], expenses=s["expenses"], income=s["income_for_simulation"],
            assumptions=schedule_assumptions,
        )
    return {
        "s": s, "mode": mode, "display_result": display_result, "retirement_year": retirement_year,
        "retirement_text": retirement_text, "empty_plan": empty_plan, "schedule": schedule,
    }


def _render_summary_page() -> str:
    v = build_plan_views()
    s, mode, display_result = v["s"], v["mode"], v["display_result"]
    assumptions = s["assumptions"]
    retirement_year, retirement_text = v["retirement_year"], v["retirement_text"]
    linked = s["linked_status"]

    linked_summary = (
        "No Plaid accounts linked yet." if not linked["configured"]
        else f"{linked['item_count']} linked Plaid account(s)"
        + (f", last synced {html.escape(linked['last_synced_at'])}." if linked["last_synced_at"] else ", not synced yet.")
    )
    # Today's job is "am I OK, and what should I do?": the answer first, then what to do about it, then the
    # picture behind it.
    if v["empty_plan"]:
        top_html = blocks.welcome_card_html()
        picture_html = ""
    else:
        top_html = (
            blocks.hero_html(s, display_result, retirement_text, mode, v["schedule"])
            + blocks.standing_card_html(s, db.list_net_worth_snapshots(), progress.plan_check_history(), display_result["success_rate"])
        )
        picture_html = (
            blocks.whatif_quick_html(
                assumptions, retirement_year is not None,
                bool(assumptions.get("birth_year") and assumptions.get("ss_benefit_self")),
            )
            + blocks.projection_card_html(s, display_result, mode, retirement_year)
            + blocks.income_sources_card_html(v["schedule"], assumptions, mode, s["this_year"])
            + blocks.own_owe_html(s)
        )
    positions = [] if v["empty_plan"] else linked_data.read_linked_portfolio_positions()
    data_issues = [] if v["empty_plan"] else data_check.run_checks(s, positions, backup.verify_latest())
    data_check_html = "" if v["empty_plan"] else blocks.data_check_card_html(data_issues)
    next_steps = "" if v["empty_plan"] else blocks.next_steps_html(advice.build_actions(
        s, display_result["success_rate"], positions, data_issues, plan_health_items(s)))

    alerts_html = ""
    if not v["empty_plan"]:
        alerts_html = blocks.alerts_card_html(alerts.refresh(alerts.evaluate(
            s, display_result["success_rate"], positions, data_issues, progress.plan_check_history())))
        progress.record_plan_check(display_result["success_rate"])

    _liquid_points, _total_points = _liquid_and_total_points(db.list_net_worth_snapshots())
    history_html = _line_chart_html(
        "Total Asset over time", _total_points,
        note="One point per day, captured automatically. Individual accounts and property lines are on the Assets tab.",
        empty_message="The trend appears here after a couple of days of history -- it's captured automatically each day the program runs.",
    )

    body = f"""
{alerts_html}
{top_html}
<div class="adv-only">{_summary_insight_html(s)}</div>
{picture_html}
{history_html}
{data_check_html}
{next_steps}
{blocks.footer_html(s, linked_summary, mode)}
"""
    return _shell(title="Summary", active="summary.html", body=body)


def _safe_pct(numerator: float, denominator: float) -> str:
    """Formats numerator/denominator as a whole-number percent, "--" when
    the denominator is zero/negative (an empty plan, or a debt-to-asset
    ratio with no assets yet) rather than dividing by zero."""
    if not denominator or denominator <= 0:
        return "--"
    return f"{numerator / denominator * 100:.0f}%"

def _summary_insight_html(s: dict) -> str:
    """"Summary insight" card -- a quick-read financial-health strip (three
    ratio tiles) plus two breakdowns (asset allocation, top expense
    categories) built from the same build_summary()/build_summary()-derived
    figures the tiles above already use, so nothing here can disagree with
    the rest of the page. Skips entirely once every input is empty (a
    fresh, unpopulated plan) rather than showing a wall of "--"/empty
    charts."""
    if not s["assets"] and not s["real_estate"] and not s["expenses"]:
        return ""

    income_coverage = _safe_pct(s["this_year_income"], s["this_year_expense_need"])
    liquid_share = _safe_pct(s["net_liquid_asset"], s["net_worth"])
    gross_liquid_and_re = s["total_asset"] + s["liability_total"]
    debt_ratio = _safe_pct(s["liability_total"], gross_liquid_and_re)

    ratio_tiles = "".join(
        f'<div class="tile"><div class="label">{html.escape(label)}</div><div class="value">{value}</div></div>'
        for label, value in (
            (f"{s['this_year']} income covers expenses", income_coverage),
            ("Liquid share of net worth", liquid_share),
            ("Debt-to-asset ratio", debt_ratio),
        )
    )

    asset_alloc_rows = [{"category": cat, "amount": amt} for cat, amt in s["asset_category_subtotals"] if amt]
    asset_alloc_chart = _donut_chart_html(
        "Asset allocation by category",
        _grouped_slices(asset_alloc_rows, key="category", value_key="amount"),
        dim="summary-asset-category",
    )
    expense_chart = _bar_chart_html(
        "Expenses by category (annual, nominal)",
        _grouped_slices(s["expenses"], key="category", value_key="annual_amount", max_slices=None),
        dim="summary-expense-category",
    )

    return f"""
<div class="card">
<h2 style="margin-top:0">Summary insight</h2>
<p class="muted">A quick read on the plan as a whole -- how much of this year's expenses your income already covers, how liquid your net worth is, how leveraged you are, and where your assets and expenses are concentrated.</p>
<div class="tiles">{ratio_tiles}</div>
<div class="insight-row">
{asset_alloc_chart}
{expense_chart}
</div>
</div>
"""
