"""Small, plain-language "where you stand" facts for the Summary: how far
along the savings are toward a rule-of-thumb independence number, and what
changed since a month ago (net worth plus the chance your money lasts).
Pure functions over data build_summary() / the snapshot table already hold,
plus a tiny JSON history of the plan-check percentage kept in `meta`."""

from __future__ import annotations

import json
import math
from datetime import date, datetime

from source.common import db

_HISTORY_KEY = "plan_check_history"
_HISTORY_LIMIT = 200
FI_MULTIPLE = 25.0  # the "4% rule": savings of about 25x yearly spending


def plan_check_history() -> dict:
    raw = db.get_meta(_HISTORY_KEY)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def record_plan_check(rate: float, today: date | None = None) -> None:
    """Remember today's chance-your-money-lasts, one value per day (the
    latest of the day wins), so the Summary can show how it moved."""
    history = plan_check_history()
    history[(today or date.today()).isoformat()] = round(float(rate), 4)
    for old in sorted(history)[:-_HISTORY_LIMIT]:
        history.pop(old, None)
    db.set_meta(_HISTORY_KEY, json.dumps(history))


def independence_progress(s: dict) -> dict | None:
    """Savings versus ~25x the yearly spending your income does NOT cover.

    Income that has already started (rent, a pension...) pays part of the
    bills, so only the rest has to come out of savings -- the same netting the
    "will my money last" simulation does, so the two never disagree. Future
    income (Social Security that starts later) is left out on purpose, which
    keeps this a little cautious. Home equity you did NOT tick "In the plan?" is
    reported separately as a cushion, never added to savings. None when there is no spending."""
    from source.reporting.monte_carlo import annual_income_need

    spending = float(s.get("next_year_expense_need") or 0.0)
    # Home equity you ticked "In the plan?" on the Real Estate tab is part of
    # what the simulation can draw on, so it counts as savings here too.
    in_plan = max(float((s.get("retirement_pools") or {}).get("real_estate") or 0.0), 0.0)
    savings = max(float(s.get("net_liquid_asset") or 0.0), 0.0) + in_plan
    if spending <= 0:
        return None
    assumptions = s.get("assumptions") or {}
    inflation = float(assumptions.get("inflation_rate") or 0.03)
    next_year = int(s.get("this_year") or date.today().year) + 1
    income = min(spending, max(0.0, float(annual_income_need(s.get("income_for_simulation") or [], next_year, inflation))))
    need = spending - income
    target = need * FI_MULTIPLE
    pct = 100.0 if target <= 0 else savings / target * 100.0
    growth = float(assumptions.get("expected_return") or 0.06)
    real = (1.0 + growth) / (1.0 + inflation) - 1.0
    year = None
    if 0 < savings < target and real > 0.0005:
        years = math.log(target / savings) / math.log(1.0 + real)
        if years < 80:
            year = int(s.get("this_year") or date.today().year) + math.ceil(years)
    equity = max(float(s.get("real_estate_equity_total") or 0.0) - in_plan, 0.0)   # not ticked: a cushion only
    return {
        "target": target, "savings": savings, "pct": pct, "reached": savings >= target, "year": year,
        "spending": spending, "income": income, "need": need, "equity": equity, "in_plan_equity": in_plan,
    }


def _parse(day: str) -> date | None:
    try:
        return datetime.strptime(day, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def since_then(snapshots: list[dict], current: dict, history: dict, today: date | None = None, days: int = 30,
               asset_rows: list[dict] | None = None) -> dict | None:
    """Compare now against the snapshot nearest to `days` ago (the oldest
    one if the history is shorter, as long as it is at least 2 days old).
    `current` is today's build_summary(). Returns None when there is no
    earlier point to compare with."""
    today = today or date.today()
    earlier = [(d, row) for row in snapshots if (d := _parse(row["snapshot_date"])) and (today - d).days >= 2]
    if not earlier:
        return None
    cutoff = [(d, r) for d, r in earlier if (today - d).days >= days]
    base_date, base = (max(cutoff, key=lambda x: x[0]) if cutoff else min(earlier, key=lambda x: x[0]))
    net_now = float(current["net_worth"])
    d_net = net_now - float(base["net_worth"])
    d_invest = float(current["retirement_liquid_total"]) - float(base["retirement_liquid_total"] or 0)
    d_equity = float(current["real_estate_equity_total"]) - float(base["real_estate_equity_total"] or 0)
    d_debt = -(float(current["liability_total"]) - float(base["liability_total"] or 0))  # paying debt down is positive
    d_other = d_net - d_invest - d_equity - d_debt
    parts = [
        ("Investments & savings", d_invest), ("Home equity", d_equity),
        ("Debts (paid down)" if d_debt >= 0 else "Debts (grew)", d_debt), ("Other assets", d_other),
    ]
    parts = sorted((p for p in parts if abs(p[1]) >= 1.0), key=lambda p: -abs(p[1]))[:3]
    rate_then = None
    prior = [(d, v) for d, v in ((_parse(k), v) for k, v in history.items()) if d and d <= base_date]
    if prior:
        rate_then = max(prior, key=lambda x: x[0])[1]
    elif history:
        first = min((d, v) for d, v in ((_parse(k), v) for k, v in history.items()) if d)
        if (today - first[0]).days >= 2:
            rate_then = first[1]
    return {"since": base_date, "net_change": d_net, "parts": parts, "rate_then": rate_then,
            "movers": biggest_movers(asset_rows or [], base_date)}


_DRIVER_WORDS = {
    "Investments & savings": "investments", "Home equity": "home equity", "Debts (paid down)": "paying down debt",
    "Debts (grew)": "debts growing", "Other assets": "other assets",
}


def change_sentence(change: dict | None, plan_rate: float, money, percent) -> str:
    """One or two plain sentences on what moved since the comparison date (see
    since_then): the net-worth change, what drove it, and the chance your money
    lasts. "" when there is nothing earlier to compare with or nothing moved."""
    if not change:
        return ""
    d = float(change["net_change"])
    rate_then = change.get("rate_then")
    rate_moved = rate_then is not None and abs(plan_rate - rate_then) >= 0.005
    if abs(d) < 1.0 and not rate_moved:
        return ""
    since = change["since"].strftime("%b %d").replace(" 0", " ")
    out = f"Since {since}, your net worth is {'up' if d >= 0 else 'down'} {money(abs(d))}"
    if change.get("parts"):
        name, value = change["parts"][0]
        if abs(d) >= 1.0 and abs(value) >= 0.5 * abs(d) and (value >= 0) == (d >= 0):
            out += f", mostly from {_DRIVER_WORDS.get(name, name.lower())}"
    out += "."
    if rate_then is not None:
        if rate_moved:
            out += f" Your chance of lasting went from {percent(rate_then)} to {percent(plan_rate)}."
        else:
            out += f" Your chance of lasting is steady at {percent(plan_rate)}."
    return out


def biggest_movers(rows: list[dict], base_date: date, limit: int = 3) -> list[dict]:
    """The accounts that moved the most since `base_date`, from the per-row
    daily balance snapshots: [{"name", "change"}], biggest swing first. A row
    is skipped when there is no snapshot within 3 days of the base date
    (it is new, or its history starts later) so a new account is never
    reported as "up" by its whole balance."""
    by_row: dict = {}
    for r in rows:
        d = _parse(r["snapshot_date"])
        if d:
            by_row.setdefault(r["asset_id"], []).append((d, float(r["balance"] or 0), r.get("name") or ""))
    movers = []
    for points in by_row.values():
        points.sort(key=lambda x: x[0])
        latest = points[-1]
        before = [p for p in points if p[0] <= base_date]
        if before:
            base = before[-1]
        else:
            after = [p for p in points if p[0] > base_date]
            base = after[0] if after and (after[0][0] - base_date).days <= 3 else None
        if base is None or base is latest:
            continue
        change = latest[1] - base[1]
        if abs(change) >= 1.0:
            movers.append({"name": latest[2] or "An account", "change": change})
    movers.sort(key=lambda m: -abs(m["change"]))
    return movers[:limit]
