"""Link a planned Income & Expenses line to a real (synced) category.

A line item can optionally name one Real Expenditure category (for an
expense) or one real-income category (for income). This module works out
what actually came in or went out for that category over the last 12
months, so the page can show "planned vs actual" and offer to copy the
actual into the plan. Nothing is changed automatically."""

from __future__ import annotations

from datetime import date, timedelta


def real_categories(transactions: list[dict]) -> dict[str, list[str]]:
    """{"expenses": [...], "income": [...]} -- categories that actually appear
    in counted (not excluded) transactions, sorted."""
    exp, inc = set(), set()
    for t in transactions:
        if t.get("excluded_from_expense"):
            continue
        cat = (t.get("category") or "").strip()
        if not cat:
            continue
        (inc if t.get("is_real_income") else exp).add(cat)
    return {"expenses": sorted(exp), "income": sorted(inc)}


def actual_last_12_months(transactions: list[dict], section: str, category: str, *, today: date | None = None) -> dict | None:
    """{"annual", "months"} for the category, or None if it has no
    transactions in the window. Fewer than 12 months of history is scaled up
    to a full year (months >= 1 is required so a few days is never scaled)."""
    if not category:
        return None
    today = today or date.today()
    start = (today - timedelta(days=365)).isoformat()
    want_income = section == "income"
    total, dates = 0.0, []
    for t in transactions:
        if t.get("excluded_from_expense") or (t.get("category") or "").strip() != category:
            continue
        if bool(t.get("is_real_income")) != want_income or not (start <= (t.get("date") or "") <= today.isoformat()):
            continue
        total += -t["amount"] if want_income else t["amount"]
        dates.append(t["date"])
    if not dates:
        return None
    # How much history the app actually has (any counted transaction), not just this category.
    all_dates = [t["date"] for t in transactions if not t.get("excluded_from_expense") and (t.get("date") or "") >= start]
    first = date.fromisoformat(min(all_dates)) if all_dates else today
    months = max(1, min(12, round((today - first).days / 30.4)))
    return {"annual": max(0.0, total) * 12.0 / months, "months": months}


def suggest_plan_lines(transactions: list[dict], expenses: list[dict], *, today: date | None = None,
                       min_annual: float = 600.0) -> list[dict]:
    """Real spending categories (last 12 months) that no planned expense line
    is linked to yet: [{"category", "annual", "monthly", "months"}], biggest
    first. Small categories (under `min_annual` a year) are left out so the
    list stays worth reading. Nothing is added automatically."""
    linked = {(e.get("linked_category") or "").strip().lower() for e in expenses if (e.get("linked_category") or "").strip()}
    planned_names = {(e.get("name") or "").strip().lower() for e in expenses}
    out = []
    for cat in real_categories(transactions)["expenses"]:
        if cat.lower() in linked or cat.lower() in planned_names:
            continue
        actual = actual_last_12_months(transactions, "expenses", cat, today=today)
        if not actual or actual["annual"] < min_annual:
            continue
        out.append({"category": cat, "annual": actual["annual"], "monthly": actual["annual"] / 12.0, "months": actual["months"]})
    out.sort(key=lambda r: -r["annual"])
    return out
