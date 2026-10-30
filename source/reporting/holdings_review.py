"""Review of everything you hold: the screener's technical readings for each stock / ETF / fund (rating, RSI, MACD, recent move,
distance from the 52-week high) combined with how big the position is and how much it has gained, turned into a short note per
holding -- "worth a look", "watch", "holding up well" or "no flags".

Pure arithmetic over numbers the caller already has (``collect_held`` reads the holdings; the screener supplies the readings). These
are prompts to think, not instructions: technical signals know nothing about your goals, taxes or time horizon, and none of this is
investment advice."""

from __future__ import annotations

SINGLE_STOCK_LIMIT = 15.0       # percent of everything held (same rule of thumb as the portfolio check-up)
FUND_LIMIT = 40.0
RISING = ("Strong Buy", "Buy")
FALLING = ("Sell", "Strong Sell")
_BROKER_LABEL = {"alpaca": "Alpaca", "ibkr": "IBKR", "etrade": "E*TRADE"}
_BROKER_WORDS = {"alpaca": ("alpaca",), "ibkr": ("interactive brokers", "ibkr"), "etrade": ("e*trade", "etrade", "e-trade")}
_ORDER = {"trim": 0, "review": 1, "watch": 2, "strong": 3, "ok": 4, "nodata": 5}
LABELS = {"trim": "Worth a look: large and stretched", "review": "Worth a look: weakening", "watch": "Watch", "strong": "Holding up well",
          "ok": "No flags", "nodata": "Not enough price history"}


def _kind(security_type: str) -> str:
    t = (security_type or "").lower()
    return "stock" if t == "equity" else "etf" if t == "etf" else "fund" if t == "mutual fund" else "cash" if t == "cash" else "other"


def collect_held() -> dict[str, dict]:
    """{symbol: {symbol, name, value, cost, kind, taxable_value, firms}} for everything with a ticker: accounts linked through Plaid plus
    what the Alpaca, IBKR and E*TRADE tabs last showed (a broker that is also linked through Plaid is counted once, from the broker)."""
    from source.common import linked_data
    from source.screener import universe

    try:
        plaid = linked_data.read_linked_portfolio_positions()
    except Exception:       # noqa: BLE001
        plaid = []
    direct = {b: v for b, v in universe.broker_positions().items() if v.get("rows")}
    covered = {b for b in direct for p in plaid if any(w in (p.get("institution") or "").lower() for w in _BROKER_WORDS[b])}
    held: dict[str, dict] = {}

    def add(sym, name, value, cost, kind, taxable, firm):
        sym = universe.clean_symbol(sym)
        if not sym or value <= 0 or kind in ("cash", "other"):
            return
        cur = held.setdefault(sym, {"symbol": sym, "name": name, "value": 0.0, "cost": 0.0, "value_known": 0.0, "kind": kind,
                                    "taxable_value": 0.0, "firms": []})
        cur["value"] += value
        if cost:
            cur["cost"] += cost
            cur["value_known"] += value
        if taxable:
            cur["taxable_value"] += value
        if firm and firm not in cur["firms"]:
            cur["firms"].append(firm)

    for p in plaid:
        firm = p.get("institution") or "Linked account"
        if any(w in firm.lower() for b in covered for w in _BROKER_WORDS[b]):
            continue
        add(p.get("ticker"), p.get("security_name") or "", float(p.get("market_value") or 0), float(p.get("cost_basis") or 0),
            _kind(p.get("security_type")), p.get("tax_treatment") == "taxable", firm)
    for broker, info in sorted(direct.items()):
        for r in info["rows"]:
            ent = next((e for e in universe.market_entries() if e["symbol"] == r["symbol"]), None)
            add(r["symbol"], r.get("name") or (ent or {}).get("name") or "", float(r.get("value") or 0), float(r.get("cost") or 0),
                "etf" if (ent or {}).get("type") == "etf" else "stock", True, _BROKER_LABEL.get(broker, broker))
    return held


def _note(h: dict, r: dict | None, weight: float) -> dict:
    """One holding's note. ``h`` the holding, ``r`` the screener row (None without price history), ``weight`` percent of everything held."""
    gain = None
    if h["cost"] > 0 and h["value_known"] > 0:                  # gain on the part of the position whose cost is known
        gain = (h["value_known"] / h["cost"] - 1.0) * 100.0
    out = {"symbol": h["symbol"], "name": h["name"] or (r or {}).get("name") or "", "kind": h["kind"], "value": round(h["value"], 2),
           "weight": round(weight, 1), "gain_pct": None if gain is None else round(gain, 1), "firms": h["firms"], "reasons": []}
    if r is None:
        out.update(level="nodata", headline=LABELS["nodata"])
        out["reasons"].append("No price history could be read for this ticker (it may be a fund Yahoo and Alpaca do not cover).")
        return out
    out.update(rating=r.get("rating"), rsi=r.get("rsi"), macd_state=r.get("macd_state"), macd_cross=r.get("macd_cross"), macd_ago=r.get("macd_ago"),
               move_1m=r.get("move_1m"), from_high_pct=r.get("from_high_pct"), price=r.get("price"))
    rating, rsi, m1 = r.get("rating"), r.get("rsi"), r.get("move_1m")
    limit = FUND_LIMIT if h["kind"] in ("etf", "fund") else SINGLE_STOCK_LIMIT
    big = weight > limit
    hot = rsi is not None and rsi >= 70
    cold = rsi is not None and rsi <= 30
    bearish = rating in FALLING
    bearish_cross = r.get("macd_cross") == "bearish" and r.get("macd_ago") is not None and r["macd_ago"] <= 10
    deep = (r.get("from_high_pct") or 0) >= 30
    taxable = h["taxable_value"] / h["value"] > 0.5 if h["value"] else False
    reasons = out["reasons"]

    if big:
        reasons.append(f"It is {weight:.0f}% of everything you hold; many people keep a single {'fund' if h['kind'] != 'stock' else 'stock'} under {limit:.0f}%.")
    if hot:
        reasons.append(f"RSI is {rsi:.0f}: it has run up fast and is often called overbought (it can stay that way).")
    if cold:
        reasons.append(f"RSI is {rsi:.0f}: it has been sold hard and is often called oversold (that alone is not a reason to buy).")
    if bearish:
        reasons.append(f"The technical rating is {rating}: most of the signals (trend, momentum, averages) point down.")
    if rating in RISING:
        reasons.append(f"The technical rating is {rating}: most of the signals point up.")
    if bearish_cross:
        reasons.append(f"MACD crossed below its signal line {'today' if r['macd_ago'] == 0 else str(r['macd_ago']) + ' days ago'}, a sign momentum is fading.")
    if m1 is not None and abs(m1) >= 8:
        reasons.append(f"It has moved {m1:+.0f}% in the last month.")
    if deep:
        reasons.append(f"It is {r['from_high_pct']:.0f}% below its 52-week high.")
    if gain is not None and gain >= 50:
        reasons.append(f"It is up about {gain:.0f}% from what you paid.")

    if big and (hot or bearish or bearish_cross):
        level = "trim"
        out["headline"] = LABELS["trim"]
        reasons.append("Worth deciding whether the position should be this big" + (
            "; in a taxable account, selling a gain is taxed (and which lots are sold matters)." if taxable and (gain or 0) > 0 else "."))
    elif bearish and (bearish_cross or (m1 is not None and m1 <= -8) or deep):
        level = "review"
        out["headline"] = LABELS["review"]
        reasons.append("Worth checking whether your reason for owning it still holds.")
    elif big or hot or bearish or bearish_cross or cold:
        level = "watch"
        out["headline"] = LABELS["watch"]
    elif rating in RISING and weight < limit:
        level = "strong"
        out["headline"] = LABELS["strong"]
    else:
        level = "ok"
        out["headline"] = LABELS["ok"]
        if not reasons:
            reasons.append("Nothing unusual in its trend, momentum or size.")
    out["level"] = level
    return out


def review(held: dict[str, dict], rows: list[dict]) -> dict:
    """{"items": [note per holding, most to least worth a look], "counts": {level: n}, "total": dollars}."""
    by_sym = {r["symbol"]: r for r in rows}
    total = sum(h["value"] for h in held.values())
    items = [_note(h, by_sym.get(h["symbol"]), (h["value"] / total * 100.0) if total else 0.0) for h in held.values()]
    items.sort(key=lambda n: (_ORDER[n["level"]], -n["value"]))
    counts: dict[str, int] = {}
    for n in items:
        counts[n["level"]] = counts.get(n["level"], 0) + 1
    return {"items": items, "counts": counts, "total": round(total, 2)}
