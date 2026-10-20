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
    loans = [p for p in positions if rebalance.is_margin_loan(p)]
    if loans:
        s = rebalance.margin_loan_summary(positions)
        issues.append({
            "id": "margin-loan", "level": "info",
            "title": f"Margin loan tagged: {_money(s['loan'])} borrowed ({s['pct_of_holdings']:.0f}% of your holdings)",
            "detail": f"Your holdings add up to {_money(s['holdings'])}; after the loan you own {_money(s['net'])}. "
                      "Your stock/bond/cash mix is worked out on the holdings before the loan, so it shows what you are really exposed to. "
                      "A loan makes losses bigger in a downturn.",
            "href": "/rebalance.html", "fix": None,
        })
    negatives = [p for p in positions if (p.get("market_value") or 0) < 0 and not rebalance.is_margin_loan(p)]
    if negatives:
        total = sum(p["market_value"] for p in negatives)
        where = ", ".join(sorted({f"{p.get('institution') or ''} {p.get('account') or ''}".strip() for p in negatives}))
        issues.append({
            "id": "negative-holdings", "level": "info",
            "title": f"{len(negatives)} holding{'s' if len(negatives) != 1 else ''} with a negative value ({_money(total)} below zero)",
            "detail": f"Usually a margin loan or an overdrawn cash line in {where}. It is left out of your stock/bond/cash mix, "
                      "so your real mix may differ. If it is a margin loan, open Linked Positions and press \"Mark as margin loan\" on that row. "
                      "Do not also add it under Liabilities if the account balance on Linked Accounts is already after the loan.",
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
    from source.reporting import benefits

    older = benefits.older_social_security_rows(summary.get("income") or [], summary.get("assumptions") or {})
    if older:
        names = ", ".join(r["name"] for r in older)
        issues.append({
            "id": "double-social-security", "level": "warn",
            "title": f"Social Security may be counted twice ({names})",
            "detail": "The Social Security planner already adds a row for each of you from your SSA statement figures. "
                      "These older rows are added on top, so your income looks too high. If the planner's numbers are right, remove the older rows.",
            "href": "/expense.html",
            "fix": {"label": "Remove the older rows", "url": "/api/line-item/delete-bulk",
                    "payload": {"items": [{"section": "income", "id": r["id"]} for r in older]}},
        })
    # A lopsided 401(k)/IRA split decides whose age starts the required withdrawals.
    share = summary.get("drawdown_spouse_tax_deferred_share")
    deferred = float((summary.get("drawdown_pools") or {}).get("tax_deferred") or 0.0)
    has_spouse = bool((summary.get("assumptions") or {}).get("spouse_birth_year"))
    if has_spouse and share is not None and deferred >= 100_000 and (share >= 0.8 or share <= 0.2):
        whose = "your partner's" if share >= 0.8 else "your"
        issues.append({
            "id": "lopsided-401k-split", "level": "info",
            "title": f"About {round(max(share, 1 - share) * 100)}% of your 401(k)/IRA money is in {whose} name",
            "detail": "That decides whose age starts the required withdrawals, and so when they raise your taxes. "
                      "If the owner tags on the Assets tab are right, nothing to do; if not, fix them.",
            "href": "/asset.html", "fix": None,
        })
    # Rent that never grows, next to spending that does, makes the later years look worse than they are.
    flat_rent = [r for r in summary.get("income") or []
                 if "rent" in f"{r.get('name', '')} {r.get('category', '')}".lower() and not r.get("inflates") and (r.get("annual_amount") or 0)]
    if flat_rent and any(r.get("inflates") for r in summary.get("expenses") or []):
        issues.append({
            "id": "rent-not-inflating", "level": "info",
            "title": f"Rental income stays flat for {len(flat_rent)} propert{'ies' if len(flat_rent) != 1 else 'y'}",
            "detail": "Your spending grows with inflation but this rent does not. If rents usually go up, tick \"Inflates\" on those Income rows.",
            "href": "/expense.html", "fix": None,
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
