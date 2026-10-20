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
    runs = int(result.get("iterations") or 1000)
    end_year, age = last_year_and_age(result, assumptions)
    until = (
        f"to age {age} ({end_year})" if age is not None and 0 < age < 130
        else f"through {end_year}" if end_year else "through the plan"
    )
    spend = f", while covering about {money(yearly_spending)} a year of spending" if yearly_spending > 0 else ""
    # Say it in the real number of runs (e.g. 1,000), so it matches "based on 1,000 simulated paths".
    lead = (f"In more than 99% of {runs:,}" if rate >= 0.995 else f"In {round(rate * runs):,} of {runs:,}")
    return f"{lead} market simulations your savings last {until}{spend}."


def watch_sentence(rows: list[dict], money, convert=None) -> str:
    """One plain sentence about the biggest sudden rise in yearly spending plus
    taxes in the drawdown schedule (e.g. the year required withdrawals begin),
    or "" when nothing jumps. `convert(value, year)` re-expresses a figure in
    today's dollars when the page is in that mode."""
    convert = convert or (lambda value, year: value)
    usable = [r for r in rows if r.get("expenses", 0) > 0]
    best = None
    for prev, cur in zip(usable, usable[1:]):
        before = convert(prev["expenses"] + prev["tax"], prev["year"])
        after = convert(cur["expenses"] + cur["tax"], cur["year"])
        if before > 0 and after > before * 1.25 and after - before > 20000:
            if best is None or after - before > best[0]:
                best = (after - before, prev, cur, before, after)
    if best is None:
        return ""
    _gain, prev, cur, before, after = best
    required = cur.get("rmd", 0) > 2 * max(prev.get("rmd", 0), 1)
    cause = ("the IRS starts requiring withdrawals from your retirement accounts, and they are taxed"
             if required else "your spending and taxes step up")
    return (f"One thing to watch: in {cur['year']} yearly spending plus taxes jumps from "
            f"{money(before)} to {money(after)} because {cause}.")


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
