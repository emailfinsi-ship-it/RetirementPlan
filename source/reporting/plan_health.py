"""Plan health checklist -- the inputs whose absence silently weakens the
numbers (a blank birth year means no RMDs; a property with no purchase
price means no gain tax on a sale; ...). A pure function over
aggregate.build_summary()'s result, so it can be tested without a page.

Each item is {"level": "warn" | "info", "text": str, "href": str}: "warn"
changes the numbers materially, "info" is worth knowing.
"""

from __future__ import annotations

from source.reporting.monte_carlo.assumptions import _resolve_retirement_year, _truthy_assumption


def _blank(value) -> bool:
    return value in (None, "") or str(value).strip() == ""


def plan_health_items(summary: dict) -> list[dict]:
    a = summary["assumptions"]
    household = summary.get("household") or {"self_name": "Person 1", "spouse_name": "Person 2", "has_spouse": True}
    me, partner = household["self_name"], household["spouse_name"]
    items: list[dict] = []

    def add(level: str, text: str, href: str) -> None:
        items.append({"level": level, "text": text, "href": href})

    by_owner = summary.get("drawdown_tax_deferred_by_owner") or {}
    if _blank(a.get("birth_year")):
        add("warn", f"{me}'s birth year isn't set, so Required Minimum Distributions aren't modeled for {me}.",
            "/monte-carlo.html#assumptions")
    if household.get("has_spouse", True) and by_owner.get("spouse", 0.0) > 0.005 and _blank(a.get("spouse_birth_year")):
        add("warn", f"{partner} owns Tax-deferred money but {partner}'s birth year isn't set, so {partner} has no RMDs in the plan.",
            "/drawdown-planning.html")
    if by_owner.get("unassigned", 0.0) > 0.005:
        add("info", f"Some Tax-deferred money has no Owner, so it is modeled under {me}'s birth year.",
            "/drawdown-planning.html")
    if _resolve_retirement_year(a) is None:
        add("info", "No retirement year is set, so withdrawals are modeled from the first plan year.",
            "/monte-carlo.html#assumptions")
    if not summary.get("expenses"):
        add("warn", "No expenses are entered, so the plan has nothing to fund.", "/expense.html")
    pools = summary.get("retirement_pools") or {}
    if sum(pools.values()) <= 0:
        add("warn", "Nothing is ticked \"In the plan?\" on the Assets tab, so there is no money to simulate.",
            "/asset.html")
    if not any("social security" in f"{r.get('name') or ''} {r.get('category') or ''}".lower() for r in summary.get("income") or []):
        add("info", "No Social Security income is entered. The planner on the Income & Expenses tab can add it.",
            "/expense.html")
    if not _truthy_assumption(a, "apply_drawdown_tax"):
        add("info", "\"Apply drawdown tax\" is off, so withdrawals are modeled with no income tax.",
            "/monte-carlo.html#assumptions")

    for p in summary.get("real_estate") or []:
        name = p.get("name") or "(unnamed property)"
        if not (p.get("current_value") or 0):
            add("warn", f"{name} has no current value.", "/real-estate.html")
        if not (p.get("purchase_price") or 0):
            add("info", f"{name} has no purchase price, so no tax on the gain is estimated if it is sold.",
                "/real-estate.html")
        if (p.get("loan_balance") or 0) > 0 and not p.get("loan_end_year"):
            add("info", f"{name} has a loan but no \"Loan ends\" year, so its rent is taxed every year.",
                "/real-estate.html")
    return items


def plan_health_card_html(items: list[dict]) -> str:
    import html

    if not items:
        body = '<p class="status-line status-ok">Nothing missing -- every input the plan relies on is filled in.</p>'
        heading = "Plan health"
    else:
        rows = "".join(
            f'<li class="{"status-warn" if i["level"] == "warn" else "muted"}">{html.escape(i["text"])} '
            f'<a href="{html.escape(i["href"])}">Fix</a></li>'
            for i in items
        )
        body = f'<ul style="margin:6px 0 0 18px; padding:0; font-size:13px;">{rows}</ul>'
        heading = f"Plan health ({len(items)} to review)"
    return f'<div class="card"><h2 style="margin-top:0">{heading}</h2>{body}</div>'
