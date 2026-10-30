"""Portfolio risk across everything held: one stock too big, one sector too big, a lot of cash, and how much sits at each firm.
Looks at the accounts linked through Plaid plus what the Alpaca, IBKR and E*TRADE tabs last showed (the Risk card on Stock Analysis).

Pure arithmetic over holdings rows -- no prices are fetched here and nothing is bought or sold. Not advice: the limits are
common rules of thumb (the same ones as the portfolio check-up on the Linked Positions tab)."""

from __future__ import annotations

from source.reporting.portfolio_checkup import CASH_LIMIT, SECTOR_LIMIT, SINGLE_HOLDING_LIMIT

TOP_N = 10
EARNINGS_MIN_PCT = 5.0          # a holding this big (percent of the total) reporting soon is worth a heads-up
_BROKER_LABEL = {"alpaca": "Alpaca", "ibkr": "IBKR", "etrade": "E*TRADE"}
_BROKER_WORDS = {"alpaca": ("alpaca",), "ibkr": ("interactive brokers", "ibkr"), "etrade": ("e*trade", "etrade", "e-trade")}


def _kind(security_type: str) -> str:
    t = (security_type or "").lower()
    return "stock" if t == "equity" else "etf" if t == "etf" else "fund" if t == "mutual fund" else "cash" if t == "cash" else "other"


def _entry(symbol: str) -> dict | None:
    from source.screener import universe
    sym = universe.clean_symbol(symbol)
    if not sym:
        return None
    return next((e for e in universe.market_entries() if e["symbol"] == sym), None)


def collect() -> dict:
    """{"rows": [{symbol, name, value, kind, sector, firm}], "sources": [{name, value, seen}]}. A broker that is also linked
    through Plaid is counted once, from the broker's own (fresher) numbers."""
    from source.common import linked_data
    from source.screener import universe

    try:
        plaid = linked_data.read_linked_portfolio_positions()
    except Exception:       # noqa: BLE001 -- a missing table must not break the page
        plaid = []
    direct = universe.broker_positions()
    skip_firms = {b for b in direct for p in plaid if any(w in (p.get("institution") or "").lower() for w in _BROKER_WORDS[b])
                  if direct[b]["rows"]}
    rows: list[dict] = []
    for p in plaid:
        firm = p.get("institution") or "Linked account"
        if any(w in firm.lower() for b in skip_firms for w in _BROKER_WORDS[b]):
            continue
        value = float(p.get("market_value") or 0)
        if value <= 0:
            continue
        kind = _kind(p.get("security_type"))
        ent = _entry(p.get("ticker")) if p.get("ticker") else None
        sector = (ent or {}).get("sector") or p.get("manual_sector") or p.get("industry") or ("Cash" if kind == "cash" else "Unclassified")
        rows.append({"symbol": p.get("ticker") or p.get("security_name") or "Unknown", "name": p.get("security_name") or "", "value": value,
                     "kind": kind, "sector": sector, "firm": firm})
    for broker, info in sorted(direct.items()):
        for r in info["rows"]:
            if (r.get("value") or 0) <= 0:
                continue
            ent = _entry(r["symbol"])
            rows.append({"symbol": r["symbol"], "name": r.get("name") or (ent or {}).get("name") or "", "value": float(r["value"]),
                         "kind": "etf" if (ent or {}).get("type") == "etf" else "stock", "sector": (ent or {}).get("sector") or "Unclassified",
                         "firm": _BROKER_LABEL.get(broker, broker)})
    sources = []
    for firm in dict.fromkeys(r["firm"] for r in rows):
        sources.append({"name": firm, "value": sum(r["value"] for r in rows if r["firm"] == firm),
                        "seen": next((v.get("at") for b, v in direct.items() if _BROKER_LABEL.get(b) == firm), "")})
    return {"rows": rows, "sources": sources}


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _money(v: float) -> str:
    return f"${v:,.0f}"


def analyze(rows: list[dict]) -> dict:
    """{"total", "positions": [top N by value], "sectors", "firms", "cash_pct", "top5_pct", "findings"} -- empty when nothing is held."""
    total = sum(r["value"] for r in rows)
    if total <= 0:
        return {"total": 0.0, "positions": [], "sectors": [], "firms": [], "cash_pct": 0.0, "top5_pct": 0.0, "findings": []}
    by_symbol: dict[str, dict] = {}
    for r in rows:
        if r["kind"] == "cash":
            continue
        cur = by_symbol.setdefault(r["symbol"], {"symbol": r["symbol"], "name": r["name"], "kind": r["kind"], "sector": r["sector"], "value": 0.0, "firms": set()})
        cur["value"] += r["value"]
        cur["firms"].add(r["firm"])
    positions = sorted(by_symbol.values(), key=lambda x: -x["value"])
    for p in positions:
        p["pct"] = p["value"] / total
        p["firms"] = sorted(p["firms"])
        p["flag"] = ("big" if p["kind"] == "stock" and p["pct"] > SINGLE_HOLDING_LIMIT
                     else "watch" if p["kind"] == "stock" and p["pct"] > SINGLE_HOLDING_LIMIT * 0.66 else "")
    sectors: dict[str, float] = {}
    for r in rows:
        if r["sector"] not in ("Unclassified",) and r["kind"] != "cash":
            sectors[r["sector"]] = sectors.get(r["sector"], 0.0) + r["value"]
    unclassified = sum(r["value"] for r in rows if r["sector"] == "Unclassified" and r["kind"] != "cash")
    sector_rows = [{"sector": k, "value": v, "pct": v / total, "flag": k in _GICS and v / total > SECTOR_LIMIT}
                   for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])]
    if unclassified:
        sector_rows.append({"sector": "Unclassified", "value": unclassified, "pct": unclassified / total, "flag": False})
    firms: dict[str, float] = {}
    for r in rows:
        firms[r["firm"]] = firms.get(r["firm"], 0.0) + r["value"]
    firm_rows = [{"firm": k, "value": v, "pct": v / total} for k, v in sorted(firms.items(), key=lambda kv: -kv[1])]
    cash = sum(r["value"] for r in rows if r["kind"] == "cash")
    top5 = sum(p["value"] for p in positions[:5]) / total

    findings: list[dict] = []
    bigs = [p for p in positions if p["flag"] == "big"]
    for p in bigs[:3]:
        findings.append({"level": "warn", "text": f"{p['symbol']} is {_pct(p['pct'])} of everything you hold ({_money(p['value'])}). "
                         f"One company can fall a lot on its own; many people cap a single stock near {_pct(SINGLE_HOLDING_LIMIT)}."})
    for s in sector_rows:
        if s["flag"]:
            findings.append({"level": "warn", "text": f"{s['sector']} is {_pct(s['pct'])} of everything you hold. A downturn in one sector would hit you harder than the market as a whole."})
            break
    if cash / total > CASH_LIMIT:
        findings.append({"level": "warn", "text": f"{_pct(cash / total)} ({_money(cash)}) is cash. Some is sensible; a lot can lose ground to inflation."})
    if top5 > 0.6 and len(positions) > 5:
        findings.append({"level": "info", "text": f"Your five biggest holdings are {_pct(top5)} of the total, so a few names drive most of your results."})
    if len(firm_rows) > 1 and firm_rows[0]["pct"] > 0.75:
        findings.append({"level": "info", "text": f"{_pct(firm_rows[0]['pct'])} is with {firm_rows[0]['firm']}."})
    if not findings:
        findings.append({"level": "ok", "text": "No red flags: no single stock, sector or pile of cash dominates what you hold."})
    return {"total": total, "positions": positions[:TOP_N], "sectors": sector_rows, "firms": firm_rows, "cash_pct": cash / total,
            "top5_pct": top5, "findings": findings, "count": len(positions)}


_GICS = {"Information Technology", "Health Care", "Financials", "Consumer Discretionary", "Communication Services", "Industrials",
         "Consumer Staples", "Energy", "Utilities", "Real Estate", "Materials"}
