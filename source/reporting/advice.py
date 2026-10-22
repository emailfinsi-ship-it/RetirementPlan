"""Ranked next steps: one short list, most important first, pulled from
everything the app already checks -- the chance your money lasts, the Data
check, missing plan inputs, the portfolio check-up, how far your mix has
drifted from your goal, and a Social Security prompt.

Pure function over data the Summary page already loads. Each action:
{"rank", "title", "why", "href", "level": "warn"|"info"}. Nothing here
changes anything; it only points you at the right tab."""

from __future__ import annotations

from datetime import date

from source.reporting import presentation, rebalance
from source.reporting.portfolio_checkup import portfolio_checkup

MAX_ACTIONS = 6


def _age(assumptions: dict, today: date) -> int | None:
    try:
        return today.year - int(float(assumptions.get("birth_year")))
    except (TypeError, ValueError):
        return None


def build_actions(summary: dict, chance: float | None, positions: list[dict], data_issues: list[dict],
                  health_items: list[dict], *, today: date | None = None) -> list[dict]:
    today = today or date.today()
    scored: list[tuple[int, dict]] = []

    def add(score: int, level: str, title: str, why: str, href: str) -> None:
        scored.append((score, {"title": title, "why": why, "href": href, "level": level}))

    # 1. The big one: will the money last?
    if chance is not None and chance < presentation.ON_TRACK_AT:
        pct = presentation.percent_display(chance)
        if chance < presentation.REVIEW_AT:
            add(100, "warn", "Raise your chance of lasting",
                f"Your money lasts in {pct} of the test runs. Try spending a little less or retiring a little later.",
                "/monte-carlo.html#assumptions")
        else:
            add(90, "warn", "Strengthen your plan",
                f"Your money lasts in {pct} of the test runs. Many planners like {presentation.ON_TRACK_AT * 100:.0f}% or more. Try a what-if.",
                "/monte-carlo.html#assumptions")

    # 2. Problems with the data (they skew every number).
    for issue in data_issues:
        if issue["level"] == "warn":
            add(80, "warn", issue["title"], issue["detail"], issue["href"])
        else:
            add(25, "info", issue["title"], issue["detail"], issue["href"])

    # 3. Missing inputs.
    for item in health_items:
        add(75 if item["level"] == "warn" else 20, item["level"], item["text"], "", item["href"])

    # 4. Concentration and mix.
    check = portfolio_checkup(positions)
    for f in check["findings"]:
        if f["level"] == "warn":
            add(50, "warn", "Spread your investments out", f["text"], "/linked-positions.html#checkup")
    if positions:
        target = rebalance.get_target() or rebalance.risk_target("moderate", _age(summary["assumptions"], today))
        plan = rebalance.build_plan(positions, target, rebalance.get_overrides())
        if plan["needs_action"]:
            worst = max(plan["rows"], key=lambda r: abs(r["drift_pts"]))
            direction = "more" if worst["drift_pts"] > 0 else "less"
            add(55, "info", "Rebalance your mix",
                f"You hold {abs(worst['drift_pts']):.0f} percentage points {direction} in {worst['cls'].lower()} than your goal. "
                "The Risk & Suggestions tab says what to move.", "/rebalance.html")

    # 5. Social Security timing matters most in the years just before claiming.
    age = _age(summary["assumptions"], today)
    if age is not None and 58 <= age <= 70:
        add(40, "info", "Compare Social Security claiming ages",
            "When you start Social Security changes your check for life. See the 62-70 comparison.", "/expense.html")

    scored.sort(key=lambda t: -t[0])
    seen, out = set(), []
    for _, action in scored:
        key = action["title"]
        if key in seen:
            continue
        seen.add(key)
        out.append({"rank": len(out) + 1, **action})
        if len(out) >= MAX_ACTIONS:
            break
    return out
