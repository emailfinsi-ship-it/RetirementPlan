"""Data check: spots data problems that quietly skew the numbers -- a
negative cash balance, a fund tagged with the wrong sector, accounts that
have not synced in days, holdings with no cost basis, a stale or unhealthy
backup -- and says in plain words what is wrong and what to do.

Pure functions over data the pages already load. Each issue:
{"id", "level": "warn"|"info", "title", "detail", "href", "fix": None | {"label", "url", "payload"}}.
A "fix" is a one-click action the page can post; an issue with no fix just
links to where it can be sorted out."""

from __future__ import annotations

import re
from datetime import datetime

from source.reporting import rebalance

_US_INDEX = re.compile(r"\b(s&p|s and p|500|total stock|total market|russell|nasdaq|large cap)\b", re.I)
STALE_SYNC_DAYS = 7
STALE_BACKUP_DAYS = 3


def _money(v: float) -> str:
    return f"${abs(v):,.0f}"


def _tag(p: dict) -> str:
    return (p.get("manual_sector") or p.get("industry") or "").strip()


def _holding_label(p: dict) -> str:
    return p.get("ticker") or p.get("security_name") or "a holding"


def check_positions(positions: list[dict]) -> list[dict]:
    issues: list[dict] = []
    negatives = [p for p in positions if (p.get("market_value") or 0) < 0]
    if negatives:
        total = sum(p["market_value"] for p in negatives)
        where = ", ".join(sorted({f"{p.get('institution') or ''} {p.get('account') or ''}".strip() for p in negatives}))
        issues.append({
            "id": "negative-holdings", "level": "info",
            "title": f"{len(negatives)} holding{'s' if len(negatives) != 1 else ''} with a negative value ({_money(total)} below zero)",
            "detail": f"Usually a margin loan or an overdrawn cash line in {where}. It is left out of your stock/bond/cash mix, "
                      "so your real mix may differ. If it is a loan, you could also list it under Liabilities.",
            "href": "/linked-positions.html", "fix": None,
        })
    mismatched = []
    for p in positions:
        tag = _tag(p).lower()
        name = f"{p.get('security_name') or ''} {p.get('ticker') or ''}"
        if not tag or (p.get("market_value") or 0) <= 0:
            continue
        says_bond = bool(rebalance._BOND_WORDS.search(name)) and not rebalance._MIXED_WORDS.search(name)
        bond_tag = "bond" in tag or "fixed income" in tag
        wrong = (says_bond and not bond_tag) or (not says_bond and bond_tag and p.get("security_type") not in ("fixed income", "bond")) \
            or (bool(_US_INDEX.search(name)) and tag in ("international", "bond"))
        if wrong and p.get("security_type") != "cash":
            mismatched.append(p)
    if mismatched:
        ids = sorted({p["security_id"] for p in mismatched if p.get("security_id")})
        names = ", ".join(sorted({_holding_label(p) for p in mismatched})[:4])
        issues.append({
            "id": "tag-mismatch", "level": "warn",
            "title": f"{len(ids)} fund{'s' if len(ids) != 1 else ''} may have the wrong sector tag ({names})",
            "detail": "The name and the tag disagree (for example a US stock index fund tagged \"International\"). "
                      "A wrong tag distorts your sector chart and your stock/bond mix.",
            "href": "/linked-positions.html",
            "fix": {"label": "Clear these tags", "url": "/api/clear-sector-tags", "payload": {"security_ids": ids}},
        })
    no_basis = [p for p in positions if p.get("tax_treatment") == "taxable" and (p.get("market_value") or 0) >= 1000
                and p.get("cost_basis") in (None, 0) and p.get("security_type") != "cash"]
    if no_basis:
        issues.append({
            "id": "no-cost-basis", "level": "info",
            "title": f"{len(no_basis)} taxable holding{'s' if len(no_basis) != 1 else ''} with no cost basis",
            "detail": "Without what you paid, the app cannot estimate the tax on selling, so rebalancing and withdrawal advice may "
                      "understate taxes. Your broker's website has the cost basis.",
            "href": "/linked-positions.html", "fix": None,
        })
    return issues


def check_plan(summary: dict, *, now: datetime | None = None) -> list[dict]:
    issues: list[dict] = []
    now = now or datetime.now()
    status = summary.get("linked_status") or {}
    last = status.get("last_synced_at")
    if status.get("configured") and last:
        try:
            when = datetime.fromisoformat(str(last).replace("Z", "")[:19])
            days = (now - when).days
            if days >= STALE_SYNC_DAYS:
                issues.append({
                    "id": "stale-sync", "level": "warn",
                    "title": f"Linked accounts last synced {days} days ago",
                    "detail": "Balances and holdings are out of date. Press Sync now (top right) to refresh them.",
                    "href": "/linked-accounts.html", "fix": None,
                })
        except ValueError:
            pass
    untyped = [a for a in summary.get("assets") or [] if a.get("include_in_monte_carlo") and not (a.get("tax_treatment") or "").strip()
               and a.get("kind", "asset") == "asset"]
    if untyped:
        issues.append({
            "id": "no-tax-type", "level": "info",
            "title": f"{len(untyped)} asset{'s' if len(untyped) != 1 else ''} in the plan with no tax type",
            "detail": "Set Taxable, Tax-deferred or Roth on the Assets tab so withdrawals and taxes are modeled correctly.",
            "href": "/asset.html", "fix": None,
        })
    for section, label in (("expenses", "Expense"), ("income", "Income")):
        odd = [r for r in summary.get(section) or [] if (r.get("start_year") and r.get("end_year") and r["start_year"] > r["end_year"])]
        if odd:
            issues.append({
                "id": f"bad-years-{section}", "level": "warn",
                "title": f"{label} row{'s' if len(odd) != 1 else ''} that end before they start: {', '.join(r['name'] for r in odd[:3])}",
                "detail": "The start year is later than the end year, so these rows never apply. Fix the years.",
                "href": "/expense.html", "fix": None,
            })
        zero = [r for r in summary.get(section) or [] if not (r.get("annual_amount") or 0)]
        if zero:
            issues.append({
                "id": f"zero-{section}", "level": "info",
                "title": f"{len(zero)} {label.lower()} row{'s' if len(zero) != 1 else ''} with a $0 amount",
                "detail": "They do nothing right now. Fill in the amount or delete them.",
                "href": "/expense.html", "fix": None,
            })
    return issues


def check_backup(info: dict) -> list[dict]:
    if not info.get("exists"):
        return [{"id": "no-backup", "level": "warn", "title": "No backup of your data yet",
                 "detail": "Press \"Back up now\" on the Setup tab. A backup is also taken automatically each day you open the app.",
                 "href": "/setup.html#backups-card", "fix": None}]
    if not info.get("ok"):
        return [{"id": "bad-backup", "level": "warn", "title": "Your latest backup did not pass its health check",
                 "detail": f"{info.get('error') or 'It could not be opened.'} Take a fresh backup from the Setup tab.",
                 "href": "/setup.html#backups-card", "fix": None}]
    if (info.get("age_days") or 0) >= STALE_BACKUP_DAYS:
        return [{"id": "old-backup", "level": "info", "title": f"Your latest backup is {int(info['age_days'])} days old",
                 "detail": "Press \"Back up now\" on the Setup tab before making big changes.",
                 "href": "/setup.html#backups-card", "fix": None}]
    return []


def run_checks(summary: dict, positions: list[dict], backup_info: dict, *, now: datetime | None = None) -> list[dict]:
    issues = check_positions(positions) + check_plan(summary, now=now) + check_backup(backup_info)
    return sorted(issues, key=lambda i: 0 if i["level"] == "warn" else 1)
