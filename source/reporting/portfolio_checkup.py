"""A plain-language "portfolio check-up" over the linked holdings: too much
in one holding or sector, idle cash, or everything at one firm. Pure
function over read_linked_portfolio_positions() rows -- no new data."""

from __future__ import annotations

SINGLE_HOLDING_LIMIT = 0.15
SECTOR_LIMIT = 0.40
CASH_LIMIT = 0.20
INSTITUTION_LIMIT = 0.75


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def portfolio_checkup(positions: list[dict]) -> dict:
    """{"total", "findings": [{"level": "warn"|"ok", "text"}]} -- empty
    findings list when there are no holdings to look at."""
    rows = [p for p in positions if (p.get("market_value") or 0) > 0]
    total = sum(p["market_value"] for p in rows)
    if total <= 0:
        return {"total": 0.0, "findings": []}
    findings: list[dict] = []

    # One holding (a fund counts as one holding -- it is already spread out).
    by_name: dict[str, float] = {}
    for p in rows:
        if (p.get("security_type") or "").lower() in ("cash", "mutual fund", "etf"):
            continue
        label = p.get("ticker") or p.get("security_name") or "Unknown holding"
        by_name[label] = by_name.get(label, 0.0) + p["market_value"]
    for label, value in sorted(by_name.items(), key=lambda kv: -kv[1]):
        if value / total > SINGLE_HOLDING_LIMIT:
            findings.append({"level": "warn", "text": (
                f"{label} is {_pct(value / total)} of your linked investments. One company can fall a lot on its own; "
                f"many people cap a single stock at around {_pct(SINGLE_HOLDING_LIMIT)}.")})
            break

    # One sector / industry (only holdings that have one).
    by_sector: dict[str, float] = {}
    for p in rows:
        sector = (p.get("sector") or p.get("manual_sector") or p.get("industry") or "").strip()
        if sector and sector.lower() not in ("unknown", "unclassified"):
            by_sector[sector] = by_sector.get(sector, 0.0) + p["market_value"]
    classified = sum(by_sector.values())
    if by_sector and classified > 0:
        top, value = max(by_sector.items(), key=lambda kv: kv[1])
        # Only judge once a fair share of the portfolio has a sector at all.
        if value / classified > SECTOR_LIMIT and classified / total >= 0.3:
            findings.append({"level": "warn", "text": (
                f"{top} makes up {_pct(value / classified)} of the holdings that have a sector. "
                "A downturn in one industry would hit you harder than the market as a whole.")})

    # Idle cash.
    cash = sum(p["market_value"] for p in rows if (p.get("security_type") or "").lower() == "cash")
    if cash / total > CASH_LIMIT:
        findings.append({"level": "warn", "text": (
            f"{_pct(cash / total)} of your linked investments ({_fmt(cash)}) is sitting in cash. "
            "Some cash is sensible; a lot of it may lose ground to inflation.")})

    # Everything at one firm.
    by_firm: dict[str, float] = {}
    for p in rows:
        firm = p.get("institution") or "Unknown"
        by_firm[firm] = by_firm.get(firm, 0.0) + p["market_value"]
    if len(by_firm) > 1:
        firm, value = max(by_firm.items(), key=lambda kv: kv[1])
        if value / total > INSTITUTION_LIMIT:
            findings.append({"level": "warn", "text": (
                f"{_pct(value / total)} of your linked investments are with {firm}. "
                "Spreading across firms limits the damage if one has a problem or an outage.")})

    if not findings:
        findings.append({"level": "ok", "text": "No red flags: no single holding, sector, firm or pile of cash dominates your linked investments."})
    return {"total": total, "findings": findings}


def _fmt(v: float) -> str:
    return f"${v:,.0f}"
