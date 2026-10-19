"""Rebalancing suggestions: compare the linked investments' mix of stocks,
bonds, cash and other with a target mix and say, in plain dollars, what to
buy and sell to get back -- selling where it costs the least tax first.
It only SUGGESTS; nothing here (or anywhere in the app) places an order.

Pure functions over read_linked_portfolio_positions() rows, plus the target
mix and any hand-set asset classes kept in `meta` as small JSON blobs."""

from __future__ import annotations

import json
import re

from source.common import db

CLASSES = ("Stocks", "Bonds", "Cash", "Other")
DRIFT_THRESHOLD_PTS = 5.0
_TARGET_KEY = "target_allocation"
_OVERRIDES_KEY = "asset_class_overrides"
_BOND_WORDS = re.compile(r"\b(bond|bonds|treasury|treasuries|tips|fixed income|t-bill|municipal|muni|aggregate|income fund)\b", re.I)
_STOCK_TYPES = {"equity", "stock", "etf", "mutual fund", "common stock"}
# Least tax first: retirement accounts can be rebalanced for free.
_TAX_ORDER = {"roth": 0, "tax_deferred": 0, "taxable": 2}


def _load(key: str) -> dict:
    raw = db.get_meta(key)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def get_target() -> dict | None:
    data = _load(_TARGET_KEY)
    try:
        target = {c: float(data[c]) for c in CLASSES}
    except (KeyError, TypeError, ValueError):
        return None
    return target if abs(sum(target.values()) - 100.0) < 0.5 else None


def set_target(values: dict) -> dict:
    target = {}
    for c in CLASSES:
        try:
            v = float(values.get(c) if values.get(c) not in (None, "") else 0)
        except (TypeError, ValueError):
            raise ValueError(f"{c} must be a number.") from None
        if not 0 <= v <= 100:
            raise ValueError(f"{c} must be between 0 and 100.")
        target[c] = v
    if abs(sum(target.values()) - 100.0) > 0.5:
        raise ValueError(f"The four targets must add up to 100% (they add up to {sum(target.values()):g}%).")
    db.set_meta(_TARGET_KEY, json.dumps(target))
    return target


def get_overrides() -> dict:
    return {k: v for k, v in _load(_OVERRIDES_KEY).items() if v in CLASSES}


def set_override(security_id: str, asset_class: str | None) -> None:
    if not security_id:
        raise ValueError("Missing security.")
    overrides = get_overrides()
    if not asset_class or asset_class == "auto":
        overrides.pop(security_id, None)
    elif asset_class in CLASSES:
        overrides[security_id] = asset_class
    else:
        raise ValueError("Unknown asset class.")
    db.set_meta(_OVERRIDES_KEY, json.dumps(overrides))


def suggested_target(age: int | None) -> dict:
    """A simple age-based starting point (110 minus age in stocks, 5% cash,
    the rest bonds) -- a rule of thumb to edit, not a recommendation."""
    stocks = 60.0 if age is None else max(30.0, min(90.0, 110.0 - age))
    cash = 5.0
    return {"Stocks": stocks, "Bonds": 100.0 - stocks - cash, "Cash": cash, "Other": 0.0}


def classify(position: dict, overrides: dict | None = None) -> str:
    if overrides and position.get("security_id") in overrides:
        return overrides[position["security_id"]]
    kind = (position.get("security_type") or "").strip().lower()
    name = f"{position.get('security_name') or ''} {position.get('ticker') or ''}"
    if kind == "cash":
        return "Cash"
    if kind in ("fixed income", "bond"):
        return "Bonds"
    if kind in _STOCK_TYPES:
        return "Bonds" if kind in ("etf", "mutual fund") and _BOND_WORDS.search(name) else "Stocks"
    return "Other"


def build_plan(positions: list[dict], target: dict, overrides: dict | None = None) -> dict:
    """{"total", "rows", "needs_action", "trades"}. Each row: class, value,
    pct, target_pct, drift_pts, delta (dollars to add; negative = to sell)."""
    overrides = overrides or {}
    rows_in = [p for p in positions if (p.get("market_value") or 0) > 0]
    total = sum(p["market_value"] for p in rows_in)
    if total <= 0:
        return {"total": 0.0, "rows": [], "needs_action": False, "trades": []}
    by_class = {c: [] for c in CLASSES}
    for p in rows_in:
        by_class[classify(p, overrides)].append(p)
    rows = []
    for c in CLASSES:
        value = sum(p["market_value"] for p in by_class[c])
        tgt = float(target.get(c, 0.0))
        rows.append({
            "cls": c, "value": value, "pct": value / total * 100.0, "target_pct": tgt,
            "drift_pts": value / total * 100.0 - tgt, "delta": total * tgt / 100.0 - value,
        })
    needs_action = any(abs(r["drift_pts"]) >= DRIFT_THRESHOLD_PTS for r in rows)
    trades = []
    if needs_action:
        for r in rows:
            if abs(r["drift_pts"]) < DRIFT_THRESHOLD_PTS or abs(r["delta"]) < 250.0:
                continue  # small gaps are left alone; any leftover simply sits in the group you sold into
            if r["delta"] < 0:
                trades.append({"action": "sell", "cls": r["cls"], "amount": -r["delta"],
                               "picks": _sell_picks(by_class[r["cls"]], -r["delta"])})
            else:
                trades.append({"action": "buy", "cls": r["cls"], "amount": r["delta"],
                               "picks": _buy_picks(by_class[r["cls"]])})
        trades.sort(key=lambda t: (t["action"] != "sell", -t["amount"]))
    return {"total": total, "rows": rows, "needs_action": needs_action, "trades": trades}


def _label(p: dict) -> str:
    return p.get("ticker") or p.get("security_name") or "holding"


def _sell_picks(holdings: list[dict], amount: float) -> list[dict]:
    """Where to sell: retirement accounts first (no tax), then taxable,
    taking the lowest-gain holdings first; largest first inside a tier."""
    def gain_ratio(p):
        basis, value = p.get("cost_basis"), p["market_value"]
        if basis in (None, 0) or not value:
            return 0.0 if p.get("tax_treatment", "taxable") != "taxable" else 0.3  # unknown basis: assume some gain
        return max(0.0, (value - basis) / value)

    ordered = sorted(holdings, key=lambda p: (_TAX_ORDER.get(p.get("tax_treatment") or "taxable", 2),
                                             gain_ratio(p) if (p.get("tax_treatment") or "taxable") == "taxable" else 0.0,
                                             -p["market_value"]))
    picks, left = [], amount
    for p in ordered:
        if left <= 1:
            break
        take = min(left, p["market_value"])
        taxable = (p.get("tax_treatment") or "taxable") == "taxable"
        picks.append({
            "label": _label(p), "account": p.get("account") or "", "amount": take,
            "tax_treatment": p.get("tax_treatment") or "taxable",
            "est_gain": take * gain_ratio(p) if taxable else 0.0,
            "basis_known": p.get("cost_basis") not in (None, 0),
        })
        left -= take
    return picks


def _buy_picks(holdings: list[dict]) -> list[dict]:
    """Where to buy: add to what you already own in that class (largest
    first); an empty list means no holding exists yet."""
    ordered = sorted(holdings, key=lambda p: -p["market_value"])[:2]
    return [{"label": _label(p), "account": p.get("account") or ""} for p in ordered]
