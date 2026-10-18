"""Plain-language presentation helpers shared by the Summary, Monte Carlo
and report pages: today's-dollars conversion, the on-track verdict, and
the "lasts to age N" phrase. Pure functions -- no database or HTML here
beyond what the callers pass in.
"""

from __future__ import annotations

ON_TRACK_AT = 0.85
REVIEW_AT = 0.70


def inflation_factor(inflation: float, years: int) -> float:
    """How many future dollars equal one of today's dollars `years` ahead."""
    return (1.0 + inflation) ** max(0, years)


def to_today(value: float, inflation: float, years: int) -> float:
    return value / inflation_factor(inflation, years)


def inflation_rate(assumptions: dict) -> float:
    try:
        return float(assumptions.get("inflation_rate") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def convert_result(result: dict, assumptions: dict, base_year: int, mode: str) -> dict:
    """A copy of a simulation result with every dollar figure expressed in
    today's dollars when mode == "today" (the band by year, and the three
    ending-balance figures, which are the last band row). "future" returns
    the result untouched. Success rate and everything non-dollar carry over."""
    if mode != "today" or not result.get("band"):
        return result
    infl = inflation_rate(assumptions)
    out = dict(result)
    band = []
    for row in result["band"]:
        k = inflation_factor(infl, int(row["year"]) - base_year)
        new_row = dict(row)
        for key in ("median", "p10", "p90", "p25", "p75", "mean"):
            if key in new_row and new_row[key] is not None:
                new_row[key] = new_row[key] / k
        band.append(new_row)
    out["band"] = band
    last = band[-1]
    out["median_ending_balance"] = last["median"]
    out["p10_ending_balance"] = last["p10"]
    out["p90_ending_balance"] = last["p90"]
    return out


def plan_status(success_rate: float) -> dict:
    """{"key", "label", "tone"} for the Summary badge. tone is one of
    ok / warn / bad so the page can colour it from its status tokens."""
    if success_rate >= ON_TRACK_AT:
        return {"key": "on_track", "label": "On track", "tone": "ok"}
    if success_rate >= REVIEW_AT:
        return {"key": "review", "label": "Worth reviewing", "tone": "warn"}
    return {"key": "at_risk", "label": "Needs attention", "tone": "bad"}


def last_year_and_age(result: dict, assumptions: dict) -> tuple[int | None, int | None]:
    """(final simulated year, the first person's age that year or None)."""
    band = result.get("band") or []
    if not band:
        return None, None
    end_year = int(band[-1]["year"])
    try:
        birth = int(float(assumptions.get("birth_year")))
    except (TypeError, ValueError):
        return end_year, None
    return end_year, end_year - birth


def verdict_sentence(result: dict, assumptions: dict, yearly_spending: float, money) -> str:
    """One plain sentence: chance the money lasts, to when, and the
    spending it covers. `money` is the page's currency formatter."""
    rate = result.get("success_rate", 0.0)
    out_of_100 = None if rate >= 0.995 else round(rate * 100)
    end_year, age = last_year_and_age(result, assumptions)
    until = (
        f"to age {age} ({end_year})" if age is not None and 0 < age < 130
        else f"through {end_year}" if end_year else "through the plan"
    )
    spend = f", while covering about {money(yearly_spending)} a year of spending" if yearly_spending > 0 else ""
    lead = "In more than 99 of 100" if out_of_100 is None else f"In {out_of_100} of 100"
    return f"{lead} market simulations your savings last {until}{spend}."


# One set of plain-language labels used on every page that shows simulation
# results, so Summary, Monte Carlo and the report always read the same.
LABEL_CHANCE = "Chance your money lasts"
LABEL_CAUTIOUS = "Cautious case (1 in 10 do worse)"
LABEL_TYPICAL = "Typical case"
LABEL_STRONG = "Strong case (1 in 10 do better)"
LABEL_START = "Savings simulated"


def dollars_caption(mode: str) -> str:
    return "ending balances in today's dollars" if mode == "today" else "ending balances in future (inflated) dollars"


def percent_display(rate: float) -> str:
    """A whole-number percent that never claims a certainty it does not have:
    anything at or above 99.5% reads ">99%" rather than "100%"."""
    return ">99%" if rate >= 0.995 else f"{rate * 100:.0f}%"
