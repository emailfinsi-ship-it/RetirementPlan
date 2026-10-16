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
    "benefit" (annual, full retirement age), "claim_age"}], Sri then Anu."""
    out = []
    for key, name, birth_key in (("self", "Sri", "birth_year"), ("spouse", "Anu", "spouse_birth_year")):
        out.append({
            "key": key, "name": name, "birth_year": _year(assumptions.get(birth_key)),
            "benefit": _number(assumptions.get(f"ss_benefit_{key}")),
            "claim_age": _year(assumptions.get(f"ss_claim_age_{key}")),
        })
    return out


def planned_rows(assumptions: dict, this_year: int | None = None) -> dict:
    """{"income": [...], "expenses": [...]} -- the Income / Expense rows the
    saved planner inputs describe (field dicts for db.add_line_item)."""
    this_year = this_year or date.today().year
    people = planner_people(assumptions)
    income, expenses = [], []
    for p in people:
        if p["birth_year"] and p["benefit"] and p["claim_age"]:
            claim = min(70, max(62, p["claim_age"]))
            income.append({
                "name": f"Social Security ({p['name']})", "category": "Social Security",
                "annual_amount": round(p["benefit"] * benefit_factor(p["birth_year"], claim), 2),
                "start_year": p["birth_year"] + claim, "end_year": None,
                "base_year": this_year, "inflates": 1, "source": BENEFITS_SOURCE, "include_in_monte_carlo": 1,
                "notes": f"Claiming at {claim}; full-retirement-age benefit {p['benefit']:,.0f}/yr in today's dollars.",
            })
    magi = _number(assumptions.get("medicare_magi"))
    if magi is not None:
        married = bool(people[1]["birth_year"])
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
    return {"created": created, "updated": updated}
