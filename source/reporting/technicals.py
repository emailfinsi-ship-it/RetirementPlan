"""Price-chart indicators and a simple technical buy / sell rating for the
Trading tab's quote panel.

Pure functions over a list of bars (dicts with ``o h l c v``, oldest first), so
they are easy to test and never touch the network. Nothing here is advice: the
rating counts a handful of widely used signals and says which way each one
points. The app never places an order from it.

Indicators (all on daily closes unless the caller passes other bars):
  SMA(n)   simple moving average
  EMA(n)   exponential moving average (smoothing 2 / (n + 1))
  RSI(14)  Wilder's relative strength index, 0-100
  MACD     EMA(12) - EMA(26), with a 9-period EMA signal line and the histogram
"""

from __future__ import annotations

RSI_PERIOD = 14
OVERSOLD, OVERBOUGHT = 30.0, 70.0
VOLUME_SPIKE = 1.5

# The ratio (sum of votes / number of signals) at which each label starts.
_LABELS = ((0.6, "Strong Buy"), (0.25, "Buy"), (-0.25, "Hold"), (-0.6, "Sell"))
_LAST_LABEL = "Strong Sell"


def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if n <= 0 or len(values) < n:
        return out
    window = sum(values[:n])
    out[n - 1] = window / n
    for i in range(n, len(values)):
        window += values[i] - values[i - n]
        out[i] = window / n
    return out


def ema(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if n <= 0 or len(values) < n:
        return out
    k = 2.0 / (n + 1)
    prev = sum(values[:n]) / n  # seeded with the first n-value average
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: list[float], n: int = RSI_PERIOD) -> list[float | None]:
    """Wilder's RSI: average gain / average loss, smoothed as (prev*(n-1) + new) / n."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / n, losses / n

    def value() -> float:
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    out[n] = value()
    for i in range(n + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (n - 1) + max(change, 0.0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-change, 0.0)) / n
        out[i] = value()
    return out


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """(macd line, signal line, histogram), each aligned with closes."""
    fast_e, slow_e = ema(closes, fast), ema(closes, slow)
    line: list[float | None] = [
        (f - s) if f is not None and s is not None else None for f, s in zip(fast_e, slow_e)
    ]
    first = next((i for i, v in enumerate(line) if v is not None), None)
    sig: list[float | None] = [None] * len(closes)
    if first is not None:
        tail = ema([v for v in line[first:]], signal)
        for offset, v in enumerate(tail):
            sig[first + offset] = v
    hist = [(m - s) if m is not None and s is not None else None for m, s in zip(line, sig)]
    return line, sig, hist


def macd_status(bars: list[dict]) -> dict:
    """Where MACD sits against its signal line now, and the most recent crossover:
    {"state": "above" | "below" | None, "cross": "bullish" | "bearish" | None, "bars_ago": int | None}.
    A bullish cross is the MACD line moving up through the signal line, a bearish one down through it."""
    m, sig, _ = macd([b["c"] for b in bars])
    last_cross, last_i = None, None
    for i in range(1, len(m)):
        if None in (m[i], sig[i], m[i - 1], sig[i - 1]):
            continue
        before, now = m[i - 1] - sig[i - 1], m[i] - sig[i]
        if before <= 0 < now:
            last_cross, last_i = "bullish", i
        elif before >= 0 > now:
            last_cross, last_i = "bearish", i
    state = None
    if m and m[-1] is not None and sig[-1] is not None:
        state = "above" if m[-1] > sig[-1] else "below"
    return {"state": state, "cross": last_cross, "bars_ago": (len(m) - 1 - last_i) if last_i is not None else None}


def vwap(bars: list[dict]) -> list[float | None]:
    """Running volume-weighted average price from the first bar (used for one-day charts)."""
    out: list[float | None] = []
    pv = vol = 0.0
    for b in bars:
        typical = (b["h"] + b["l"] + b["c"]) / 3.0
        pv += typical * b["v"]
        vol += b["v"]
        out.append(pv / vol if vol > 0 else None)
    return out


def _last(series: list[float | None], back: int = 0) -> float | None:
    i = len(series) - 1 - back
    return series[i] if 0 <= i < len(series) else None


def series(bars: list[dict]) -> dict:
    """Every indicator the chart and the rating use, aligned with ``bars``."""
    closes = [b["c"] for b in bars]
    volumes = [b["v"] for b in bars]
    m, s, h = macd(closes)
    return {
        "sma20": sma(closes, 20), "sma50": sma(closes, 50), "sma200": sma(closes, 200),
        "rsi": rsi(closes), "macd": m, "macd_signal": s, "macd_hist": h,
        "vol_avg20": sma(volumes, 20),
    }


def trends(bars: list[dict]) -> list[dict]:
    """Short / medium / long trend from price versus its moving average and the
    average's own direction over the last five bars."""
    closes = [b["c"] for b in bars]
    out = []
    for label, n in (("Short term (about 1 month)", 20), ("Medium term (about 3 months)", 50), ("Long term (about 1 year)", 200)):
        avg = sma(closes, n)
        now, before = _last(avg), _last(avg, 5)
        if now is None or before is None or len(closes) <= n:
            out.append({"label": label, "window": n, "direction": "Not enough history", "change_pct": None})
            continue
        price = closes[-1]
        if price > now and now > before:
            direction = "Up"
        elif price < now and now < before:
            direction = "Down"
        else:
            direction = "Sideways"
        base = closes[-1 - n]
        out.append({"label": label, "window": n, "direction": direction,
                    "change_pct": (price / base - 1.0) * 100.0 if base else None})
    return out


def range_stats(bars: list[dict], last_price: float | None = None) -> dict:
    """52-week (or however much history there is) high and low, and where the price sits in it."""
    if not bars:
        return {"low": None, "high": None, "position": None}
    low, high = min(b["l"] for b in bars), max(b["h"] for b in bars)
    price = last_price if last_price is not None else bars[-1]["c"]
    position = None if high <= low else max(0.0, min(1.0, (price - low) / (high - low)))
    return {"low": low, "high": high, "position": position}


def label_for(ratio: float) -> str:
    for floor, label in _LABELS:
        if ratio >= floor:
            return label
    return _LAST_LABEL


def rating(bars: list[dict]) -> dict:
    """A technical buy / sell rating from daily bars.

    Each signal votes +1 (bullish), 0 (neutral) or -1 (bearish); the rating is
    the sum divided by the number of signals that could be measured. Needs at
    least 30 bars; the 200-day signal is skipped with less than 201."""
    if len(bars) < 30:
        return {"label": "Not enough history", "score": 0, "of": 0, "ratio": 0.0, "signals": [],
                "buy_votes": 0, "sell_votes": 0}
    closes = [b["c"] for b in bars]
    ind = series(bars)
    price = closes[-1]
    signals: list[dict] = []

    def add(name: str, vote: int, text: str) -> None:
        signals.append({"name": name, "vote": vote, "text": text})

    for key, n, name in (("sma20", 20, "Price vs 20-day average"), ("sma50", 50, "Price vs 50-day average"),
                         ("sma200", 200, "Price vs 200-day average")):
        avg = _last(ind[key])
        if avg is None:
            continue
        if price >= avg:
            add(name, 1, f"The price (${price:,.2f}) is above its {n}-day average (${avg:,.2f}).")
        else:
            add(name, -1, f"The price (${price:,.2f}) is below its {n}-day average (${avg:,.2f}).")
    a20, a50 = _last(ind["sma20"]), _last(ind["sma50"])
    if a20 is not None and a50 is not None:
        if a20 >= a50:
            add("20-day vs 50-day average", 1, "The short-term average is above the medium-term one, which fits a rising trend.")
        else:
            add("20-day vs 50-day average", -1, "The short-term average is below the medium-term one, which fits a falling trend.")
    r = _last(ind["rsi"])
    if r is not None:
        if r <= OVERSOLD:
            add("RSI (14)", 1, f"RSI is {r:.0f}: oversold, so sellers may be exhausted and a bounce is common.")
        elif r >= OVERBOUGHT:
            add("RSI (14)", -1, f"RSI is {r:.0f}: overbought, so buyers may be stretched and a pullback is common.")
        else:
            add("RSI (14)", 0, f"RSI is {r:.0f}: neither oversold (30 or less) nor overbought (70 or more).")
    h, h_prev = _last(ind["macd_hist"]), _last(ind["macd_hist"], 1)
    if h is not None:
        rising = h_prev is not None and h > h_prev
        if h > 0:
            add("MACD", 1, "MACD is above its signal line" + (" and gaining." if rising else " but fading."))
        elif h < 0:
            add("MACD", -1, "MACD is below its signal line" + (" but improving." if rising else " and falling."))
        else:
            add("MACD", 0, "MACD is on its signal line.")
    avg_vol = _last(ind["vol_avg20"])
    if avg_vol and len(bars) >= 2:
        ratio = bars[-1]["v"] / avg_vol if avg_vol else 0.0
        move = closes[-1] - closes[-2]
        if ratio >= VOLUME_SPIKE and move > 0:
            add("Volume", 1, f"Volume is {ratio:.1f}x its 20-day average on an up day: buyers are active.")
        elif ratio >= VOLUME_SPIKE and move < 0:
            add("Volume", -1, f"Volume is {ratio:.1f}x its 20-day average on a down day: sellers are active.")
        else:
            add("Volume", 0, f"Volume is {ratio:.1f}x its 20-day average: no unusual activity.")

    score = sum(s["vote"] for s in signals)
    count = len(signals)
    ratio = score / count if count else 0.0
    return {
        "label": label_for(ratio), "score": score, "of": count, "ratio": ratio, "signals": signals,
        "buy_votes": sum(1 for s in signals if s["vote"] > 0), "sell_votes": sum(1 for s in signals if s["vote"] < 0),
    }
