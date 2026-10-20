"""Social Security claiming-age and Medicare-premium planning.

Pure calculators (full retirement age, the early/late claiming adjustment,
a claiming-age comparison table, the Medicare Part B/D premium for an
income, IRMAA included) plus `apply_benefits_plan`, which turns the saved
planner inputs into ordinary rows on the Income / Expense tabs -- so the
rest of the program (Monte Carlo, Drawdown, Legacy, taxes) needs no new
concepts: Social Security is just an Income row that starts in the right
year at the right amount, and Medicare is just an Expense row.

Simplifications, deliberate and stated on the page: benefits are in today's
dollars and then grow with the Inflation assumption (SSA's COLA); the
claiming comparison ignores taxes, spousal/survivor benefits and
discounting; IRMAA is applied as a flat premium from age 65 using one
income estimate you enter (the real rule looks at your income two years
back, tier by tier, every year).
"""

from __future__ import annotations

from datetime import date

from source.common import db

MEDICARE_AGE = 65
CLAIM_AGES = tuple(range(62, 71))
BENEFITS_SOURCE = "benefits-planner"   # marks the rows this module owns

# 2026 Medicare Part B/D (CMS). IRMAA looks at MAGI from two years earlier.
MEDICARE_TABLE_YEAR = 2026
PART_B_STANDARD_MONTHLY = 202.90
# (upper MAGI limit single, upper MAGI limit married filing jointly,
#  total monthly Part B premium, monthly Part D surcharge)
IRMAA_TIERS: tuple[tuple[float, float, float, float], ...] = (
    (109_000.0, 218_000.0, 202.90, 0.0),
    (137_000.0, 274_000.0, 284.10, 14.50),
    (171_000.0, 342_000.0, 405.80, 37.50),
    (205_000.0, 410_000.0, 527.50, 60.40),
    (500_000.0, 750_000.0, 649.20, 83.30),
    (float("inf"), float("inf"), 689.90, 91.00),
)


def full_retirement_age_months(birth_year: int) -> int:
    """Full retirement age, in months, for a birth year (SSA's table)."""
    if birth_year <= 1937:
        return 65 * 12
    if birth_year <= 1942:
        return 65 * 12 + 2 * (birth_year - 1937)
    if birth_year <= 1954:
        return 66 * 12
    if birth_year <= 1959:
        return 66 * 12 + 2 * (birth_year - 1954)
    return 67 * 12


def fra_text(birth_year: int) -> str:
    months = full_retirement_age_months(birth_year)
    years, extra = divmod(months, 12)
    return f"{years}" + (f" and {extra} months" if extra else "")


def benefit_factor(birth_year: int, claim_age: int) -> float:
    """Share of the full-retirement-age benefit paid when claiming at
    `claim_age` (whole years, 62-70): reduced 5/9 of 1% per month for the
    first 36 months early and 5/12 of 1% beyond that; increased 2/3 of 1%
    per month (8%/yr) of delay up to age 70."""
    claim_age = min(70, max(62, int(claim_age)))
    diff = claim_age * 12 - full_retirement_age_months(birth_year)
    if diff < 0:
        early = -diff
        return 1.0 - (min(early, 36) * 5 / 900 + max(early - 36, 0) * 5 / 1200)
    delay = min(diff, 70 * 12 - full_retirement_age_months(birth_year))
    return 1.0 + delay * 2 / 300


def claiming_table(full_benefit: float, birth_year: int) -> list[dict]:
    """One row per claiming age 62-70: {"age", "start_year", "factor",
    "annual", "total_to_85", "break_even_vs_62"} (today's dollars, no COLA
    or discounting)."""
    rows = []
    base = None
    for age in CLAIM_AGES:
        factor = benefit_factor(birth_year, age)
        annual = full_benefit * factor
        row = {
            "age": age, "start_year": birth_year + age, "factor": factor, "annual": annual,
            "total_to_85": annual * max(0, 85 - age), "break_even_vs_62": None,
        }
        if age == CLAIM_AGES[0]:
            base = row
        elif base and annual > base["annual"]:
            row["break_even_vs_62"] = (annual * age - base["annual"] * base["age"]) / (annual - base["annual"])
        rows.append(row)
    return rows


def medicare_tier(magi: float, married: bool = True) -> dict:
    """{"tier" (0 = no surcharge), "part_b_monthly", "part_d_surcharge",
    "monthly" (both), "annual"} for an income."""
    for index, (single_limit, joint_limit, part_b, part_d) in enumerate(IRMAA_TIERS):
        if magi <= (joint_limit if married else single_limit):
            break
    return {
        "tier": index, "part_b_monthly": part_b, "part_d_surcharge": part_d,
        "monthly": part_b + part_d, "annual": 12 * (part_b + part_d),
    }


def _number(value, default=None):
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _year(value):
    number = _number(value)
    return int(number) if number is not None else None


def planner_people(assumptions: dict) -> list[dict]:
    """The people the planner covers: [{"key", "name", "birth_year",
    "benefit" (annual, full retirement age), "claim_age"}] -- the household's
    first person, then the second one when the household has one."""
    household = db.household()
    out = []
    candidates = [("self", household["self_name"], "birth_year")]
    if household["has_spouse"]:
        candidates.append(("spouse", household["spouse_name"], "spouse_birth_year"))
    for key, name, birth_key in candidates:
        out.append({
            "key": key, "name": name, "birth_year": _year(assumptions.get(birth_key)),
            "benefit": _number(assumptions.get(f"ss_benefit_{key}")),
            "claim_age": _year(assumptions.get(f"ss_claim_age_{key}")),
        })
    return out


def social_security_row(person: dict, claim_age: int, this_year: int) -> dict:
    """The Income-row fields for one person claiming at `claim_age`."""
    claim = min(70, max(62, int(claim_age)))
    return {
        "name": f"Social Security ({person['name']})", "category": "Social Security",
        "annual_amount": round(person["benefit"] * benefit_factor(person["birth_year"], claim), 2),
        "start_year": person["birth_year"] + claim, "end_year": None,
        "base_year": this_year, "inflates": 1, "source": BENEFITS_SOURCE, "include_in_monte_carlo": 1,
        "notes": f"Claiming at {claim}; full-retirement-age benefit {person['benefit']:,.0f}/yr in today's dollars.",
    }


def older_social_security_rows(income_rows: list[dict], assumptions: dict) -> list[dict]:
    """Social Security rows typed in by hand that would be counted ON TOP of the
    planner's own rows -- empty unless the planner has (or would write) Social
    Security rows. The planner's rows come from the SSA statement figures, so
    older hand-made ones double the benefit."""
    from source.reporting.monte_carlo.withdrawal import _income_kind

    def is_ss(r):
        return _income_kind(r) == "social_security"

    planner_has = any(is_ss(r) and r.get("source") == BENEFITS_SOURCE for r in income_rows) or any(
        True for r in planned_rows(assumptions)["income"]
    )
    if not planner_has:
        return []
    return [r for r in income_rows if is_ss(r) and r.get("source") != BENEFITS_SOURCE]


def planned_rows(assumptions: dict, this_year: int | None = None) -> dict:
    """{"income": [...], "expenses": [...]} -- the Income / Expense rows the
    saved planner inputs describe (field dicts for db.add_line_item)."""
    this_year = this_year or date.today().year
    people = planner_people(assumptions)
    income, expenses = [], []
    for p in people:
        if p["birth_year"] and p["benefit"] and p["claim_age"]:
            income.append(social_security_row(p, p["claim_age"], this_year))
    magi = _number(assumptions.get("medicare_magi"))
    if magi is not None:
        married = len(people) > 1 and bool(people[1]["birth_year"])
        tier = medicare_tier(magi, married)
        other_monthly = _number(assumptions.get("medicare_other_monthly"), 0.0) or 0.0
        for p in people:
            if p["birth_year"]:
                expenses.append({
                    "name": f"Medicare premiums ({p['name']})", "category": "Healthcare",
                    "annual_amount": round(12 * other_monthly + tier["annual"], 2),
                    "start_year": p["birth_year"] + MEDICARE_AGE, "end_year": None,
                    "base_year": this_year, "inflates": 1, "source": BENEFITS_SOURCE,
                    "notes": f"Part B + Part D surcharge at {tier['part_b_monthly']:.2f} + {tier['part_d_surcharge']:.2f}"
                             f"/mo ({MEDICARE_TABLE_YEAR} IRMAA tier {tier['tier'] + 1}), plus {other_monthly:,.0f}/mo other.",
                })
    return {"income": income, "expenses": expenses}


def apply_benefits_plan(assumptions: dict, this_year: int | None = None) -> dict:
    """Creates or updates (matched by name) the planner's Income and
    Expense rows. Returns {"created": [names], "updated": [names]}."""
    rows = planned_rows(assumptions, this_year)
    created, updated = [], []
    for section in ("income", "expenses"):
        existing = {r["name"]: r for r in db.list_line_items(section)}
        for fields in rows[section]:
            current = existing.get(fields["name"])
            if current:
                db.update_line_item(section, current["id"], fields)
                updated.append(fields["name"])
            else:
                db.add_line_item(section, fields)
                created.append(fields["name"])
    # The planner owns every row it writes (source == BENEFITS_SOURCE). A
    # row for someone no longer in the plan -- a renamed person, a household
    # that dropped its second person -- would otherwise stay behind and
    # double-count, so rows it did not just write are removed.
    kept = {fields["name"] for section in rows.values() for fields in section}
    removed = []
    for section in ("income", "expenses"):
        for row in db.list_line_items(section):
            if row.get("source") == BENEFITS_SOURCE and row["name"] not in kept:
                db.delete_line_item(section, row["id"])
                removed.append(row["name"])
    return {"created": created, "updated": updated, "removed": removed}


def analyze_claiming(summary: dict, person_key: str, iterations: int = 300) -> dict:
    """Runs the plan's own Monte Carlo once per claiming age 62-70 for one
    person (everyone else held at their chosen claiming age, or 67), with
    the same random market paths each time so only the claiming age differs.
    Returns {"person", "rows": [{"age", "start_year", "annual", "success_rate",
    "median", "p10"}], "best_odds_age", "recommended_age", "chosen_age"} with
    balances in today's dollars."""
    import random

    from source.reporting import presentation as pres
    from source.reporting.monte_carlo import run_simulation, stable_simulation_seed

    assumptions = dict(summary["assumptions"])
    assumptions["iterations"] = min(int(float(assumptions.get("iterations") or iterations)), iterations)
    people = planner_people(assumptions)
    target = next((p for p in people if p["key"] == person_key), None)
    if not target or not (target["birth_year"] and target["benefit"]):
        raise ValueError("Enter this person's birth year and Social Security benefit first.")
    this_year = int(summary.get("this_year") or date.today().year)
    base_income = [
        r for r in summary["income_for_simulation"]
        if not (r.get("source") == BENEFITS_SOURCE and str(r.get("name") or "").startswith("Social Security"))
    ]
    expenses, pools, balance = summary["expenses"], summary["retirement_pools"], summary["net_liquid_asset"]

    def income_for(age: int) -> list:
        rows = list(base_income)
        for p in people:
            if not (p["birth_year"] and p["benefit"]):
                continue
            rows.append(social_security_row(p, age if p["key"] == person_key else (p["claim_age"] or 67), this_year))
        return rows

    seed = stable_simulation_seed(
        starting_balance=balance, expenses=expenses, income=income_for(67), assumptions=assumptions, pools=pools,
    )
    out = []
    for age in CLAIM_AGES:
        raw = run_simulation(
            starting_balance=balance, expenses=expenses, income=income_for(age), assumptions=assumptions,
            pools=pools, rng=random.Random(seed),
        )
        shown = pres.convert_result(raw, assumptions, this_year, "today")
        out.append({
            "age": age, "start_year": target["birth_year"] + age,
            "annual": round(target["benefit"] * benefit_factor(target["birth_year"], age), 2),
            "success_rate": raw["success_rate"], "median": shown["median_ending_balance"], "p10": shown["p10_ending_balance"],
        })
    best_rate = max(r["success_rate"] for r in out)
    best_odds = max((r for r in out if r["success_rate"] >= best_rate - 1e-9), key=lambda r: (r["median"], r["age"]))
    # Recommended: highest typical balance among ages whose odds are within a
    # point of the best -- do not give up reliability for a bigger typical case.
    near = [r for r in out if r["success_rate"] >= best_rate - 0.01]
    recommended = max(near, key=lambda r: (r["median"], r["age"]))
    return {
        "person": target["name"], "key": person_key, "rows": out,
        "best_odds_age": best_odds["age"], "recommended_age": recommended["age"],
        "chosen_age": target["claim_age"], "married": len([p for p in people if p["birth_year"]]) > 1,
    }
