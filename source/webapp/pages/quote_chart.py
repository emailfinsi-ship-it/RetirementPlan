"""The Trading tab's quote panel: a symbol's quote, day and 52-week range,
trend, technical buy / sell rating, and a three-panel chart (price with
moving averages, volume, RSI).

``build_quote`` does the work for the /api/alpaca/quote route: it reads prices
from Alpaca (read-only, either account's keys), runs source.reporting.
technicals over them and returns plain JSON, including the chart as an SVG
string. Prices come from Alpaca's free IEX feed, so volume is IEX's share of
the market, not the whole market's.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from source.collector import alpaca
from concurrent.futures import ThreadPoolExecutor

from source.common import db, secrets_store
from source.reporting import technicals as ta

RANGES = {"1D": None, "1M": 22, "3M": 64, "6M": 127, "1Y": 253}
HISTORY_DAYS = 420          # calendar days of daily bars: enough for the 200-day average and a year of chart
_INTRADAY_DAYS = 6          # look back this far to find the latest trading session
_OPEN_MIN, _CLOSE_MIN = 9 * 60 + 30, 16 * 60   # regular US session, in New York time

W, LEFT, RIGHT = 980, 6, 60
PRICE_TOP, PRICE_H = 14, 290
VOL_TOP, VOL_H = 316, 64
RSI_TOP, RSI_H = 392, 84
AXIS_Y, H = 490, 500


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def _new_york(dt: datetime) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001 -- no tz database: fall back to a fixed offset (close enough for grouping)
        return dt.astimezone(timezone(timedelta(hours=-5)))


def market_data_source(mode: str | None = None) -> tuple[tuple[str, str], str]:
    """(keys, mode) used to READ prices and names. Prices are the same for either account,
    so unless a mode is named this prefers the practice (play-money) keys and falls back
    to the live ones; it raises a plain-language error when neither is saved."""
    order = [mode] if mode in alpaca.MODES else ["paper", "live"]
    for m in order:
        try:
            return secrets_store.get_alpaca_keys(mode=m), m
        except secrets_store.SecretNotFoundError:
            continue
    raise ValueError("Stock Analysis reads prices from Alpaca. Save your practice (free) or live keys on the Trading tab first.")


def market_data_keys(mode: str | None = None) -> tuple[str, str]:
    return market_data_source(mode)[0]


_NO_NAME: set[str] = set()   # tickers Alpaca had no name for, so a refresh doesn't ask again every minute


def company_names(symbols: list[str], keys: tuple[str, str], mode: str, **kw) -> dict[str, str]:
    """{symbol: company name} for what could be found. Names are remembered in the database,
    so each ticker is looked up from Alpaca once."""
    syms = list(dict.fromkeys(symbols))
    known = db.watchlist.cached_names(syms)
    missing = [s for s in syms if s not in known and s not in _NO_NAME]
    if missing:
        with ThreadPoolExecutor(max_workers=6) as pool:
            found = list(pool.map(lambda s: alpaca.get_asset_name(s, keys, mode=mode, **kw), missing))
        for sym, name in zip(missing, found):
            if name:
                db.watchlist.remember_name(sym, name)
                known[sym] = name
            else:
                _NO_NAME.add(sym)
    return known


def _round(value, places: int = 4):
    return None if value is None else round(float(value), places)


# ------------------------------------------------------------------ data

def _daily_rows(daily: list[dict], ind: dict, count: int) -> list[dict]:
    start = max(0, len(daily) - count)
    rows = []
    for i in range(start, len(daily)):
        b = daily[i]
        dt = _parse(b["t"])
        rows.append({
            "t": dt.strftime("%b %-d, %Y") if dt else b["t"], "tick": dt.strftime("%b %-d") if dt else "",
            "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"],
            "rsi": ind["rsi"][i], "a": ind["sma20"][i], "b": ind["sma50"][i], "c2": ind["sma200"][i],
            "vavg": ind["vol_avg20"][i],
        })
    return rows


def _intraday_rows(bars: list[dict]) -> list[dict]:
    """The latest regular-hours session's 5-minute bars, with RSI and VWAP."""
    stamped = []
    for b in bars:
        dt = _parse(b["t"])
        if dt is None:
            continue
        ny = _new_york(dt)
        minutes = ny.hour * 60 + ny.minute
        if _OPEN_MIN <= minutes < _CLOSE_MIN:
            stamped.append((ny, b))
    if not stamped:
        return []
    day = stamped[-1][0].date()
    session = [(ny, b) for ny, b in stamped if ny.date() == day]
    only = [b for _ny, b in session]
    closes = [b["c"] for b in only]
    rsi_vals, vw = ta.rsi(closes), ta.vwap(only)
    rows = []
    for i, (ny, b) in enumerate(session):
        label = ny.strftime("%-I:%M %p")
        rows.append({
            "t": f"{ny.strftime('%b %-d')}, {label}", "tick": ny.strftime("%-I:%M"),
            "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"],
            "rsi": rsi_vals[i], "a": vw[i], "b": None, "c2": None, "vavg": None,
        })
    return rows


def _quote_block(sym: str, snap: dict | None, daily: list[dict]) -> dict:
    last_bar = daily[-1]
    day = (snap or {}).get("day") or last_bar
    prev = (snap or {}).get("prev_day") or (daily[-2] if len(daily) >= 2 else None)
    price = (snap or {}).get("price") or day.get("c") or last_bar["c"]
    prev_close = prev["c"] if prev else None
    change = None if prev_close is None else price - prev_close
    pct = None if not prev_close else change / prev_close * 100.0
    low, high = day.get("l"), day.get("h")
    if low is not None and high is not None:
        low, high = min(low, price), max(high, price)
    position = None if low is None or high is None or high <= low else (price - low) / (high - low)
    return {
        "symbol": sym, "price": price, "prev_close": prev_close, "change": change, "change_pct": pct,
        "open": day.get("o"), "high": high, "low": low, "day_position": position, "volume": day.get("v"),
        "bid": (snap or {}).get("bid"), "ask": (snap or {}).get("ask"),
        "bid_size": (snap or {}).get("bid_size"), "ask_size": (snap or {}).get("ask_size"),
        "as_of": (snap or {}).get("trade_time") or last_bar["t"],
    }


def build_price(symbol: str, keys: tuple[str, str], **kw) -> dict:
    """The current price and bid / ask for the order form (one light call; JSON-ready)."""
    sym = alpaca._symbol(symbol)
    snap = alpaca.get_snapshot(sym, keys, **kw)
    day, prev = snap.get("day") or {}, snap.get("prev_day")
    price = snap.get("price") or day.get("c")
    if not price:
        raise alpaca.AlpacaError(f"No current price is available for {sym}. Check the ticker.")
    prev_close = prev["c"] if prev else None
    change = None if prev_close is None else price - prev_close
    return {
        "symbol": sym, "price": price, "prev_close": prev_close, "change": change,
        "change_pct": None if not prev_close else change / prev_close * 100.0,
        "bid": snap.get("bid"), "ask": snap.get("ask"), "bid_size": snap.get("bid_size"), "ask_size": snap.get("ask_size"),
        "as_of": snap.get("trade_time") or "",
    }


def build_quote(symbol: str, keys: tuple[str, str], range_key: str = "3M", *, now: datetime | None = None, mode: str | None = None, **kw) -> dict:
    """Everything the quote panel shows for ``symbol`` (JSON-ready)."""
    sym = alpaca._symbol(symbol)
    if range_key not in RANGES:
        range_key = "3M"
    now = now or datetime.now(timezone.utc)
    daily = alpaca.get_bars(sym, keys, timeframe="1Day", start=_iso(now - timedelta(days=HISTORY_DAYS)), limit=1000, **kw)
    if not daily:
        raise alpaca.AlpacaError(f"No price history was found for {sym}. Check the ticker.")
    try:
        snap = alpaca.get_snapshot(sym, keys, **kw)
    except alpaca.AlpacaError:
        snap = None  # the daily bars still give a last price
    quote = _quote_block(sym, snap, daily)
    ind = ta.series(daily)
    if range_key == "1D":
        intraday = alpaca.get_bars(sym, keys, timeframe="5Min", start=_iso(now - timedelta(days=_INTRADAY_DAYS)), limit=2000, **kw)
        rows, kind = _intraday_rows(intraday), "intraday"
        if not rows:  # market data for today not available: show the daily chart instead
            rows, kind, range_key = _daily_rows(daily, ind, RANGES["1M"]), "daily", "1M"
    else:
        rows, kind = _daily_rows(daily, ind, RANGES[range_key]), "daily"
    rating = ta.rating(daily)
    news, news_error = [], False
    if mode:    # headlines are only fetched for the real route (mode is how it asks for them)
        try:
            news = alpaca.get_news(sym, keys, **kw)
        except alpaca.AlpacaError:
            news_error = True     # news is a nicety: the quote still shows
    return {
        "symbol": sym, "name": company_names([sym], keys, mode, **kw).get(sym, "") if mode else "", "range": range_key, "quote": quote,
        "week52": ta.range_stats(daily[-253:], quote["price"]),
        "rating": rating, "trends": ta.trends(daily), "news": news, "news_error": news_error,
        "chart": chart_html(rows, kind, quote["prev_close"] if kind == "intraday" else None),
        "rows": [{k: _round(v) if k not in ("t", "tick") else v for k, v in r.items()} for r in rows],
        "bars": len(daily),
    }


# ------------------------------------------------------------------ chart

def _nice_ticks(low: float, high: float, count: int = 4) -> list[float]:
    span = high - low
    if span <= 0:
        return [low]
    return [low + span * i / count for i in range(count + 1)]


def _fmt_price(value: float) -> str:
    return f"{value:,.2f}" if abs(value) < 1000 else f"{value:,.0f}"


def _fmt_volume(value: float) -> str:
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= size:
            return f"{value / size:.1f}{suffix}"
    return f"{value:.0f}"


def _path(points: list[tuple[float, float | None]], y_of) -> str:
    """One SVG path through the points, lifting the pen where a value is missing."""
    parts: list[str] = []
    pen_down = False
    for x, v in points:
        if v is None:
            pen_down = False
            continue
        parts.append(f"{'L' if pen_down else 'M'}{x:.1f},{y_of(v):.1f}")
        pen_down = True
    return " ".join(parts)


def chart_html(rows: list[dict], kind: str, prev_close: float | None = None) -> str:
    """Legend plus one SVG with three panels (price, volume, RSI) sharing an x axis."""
    n = len(rows)
    if n < 2:
        return '<p class="muted">Not enough price data to draw a chart for this range.</p>'
    pw = W - LEFT - RIGHT
    step = pw / n
    cx = lambda i: LEFT + (i + 0.5) * step  # noqa: E731

    # --- price panel
    avgs = ("a", "b", "c2")
    # Scaled to the candles only (plus the previous close); an average far outside
    # them is clipped at the panel edge instead of squashing the candles flat.
    values = [r["l"] for r in rows] + [r["h"] for r in rows]
    if prev_close:
        values.append(prev_close)
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.04 or hi * 0.01
    lo, hi = lo - pad, hi + pad
    y_price = lambda v: PRICE_TOP + (hi - v) / (hi - lo) * PRICE_H  # noqa: E731
    out = [f'<svg class="qc" viewBox="0 0 {W} {H}" role="img" data-n="{n}" data-left="{LEFT}" data-pw="{pw}" data-w="{W}" '
           f'aria-label="Price, volume and RSI chart">'
           f'<defs><clipPath id="qc-clip"><rect x="{LEFT}" y="{PRICE_TOP}" width="{pw}" height="{PRICE_H}"/></clipPath></defs>']
    for tick in _nice_ticks(lo, hi):
        y = y_price(tick)
        out.append(f'<line class="qc-grid" x1="{LEFT}" x2="{LEFT + pw}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text class="qc-axis" x="{LEFT + pw + 6}" y="{y + 4:.1f}">{_fmt_price(tick)}</text>')
    if prev_close:
        y = y_price(prev_close)
        out.append(f'<line class="qc-prev" x1="{LEFT}" x2="{LEFT + pw}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text class="qc-axis" x="{LEFT + 4}" y="{y - 4:.1f}">previous close</text>')
    body_w = max(1.4, min(step * 0.64, 14.0))
    for i, r in enumerate(rows):
        up = r["c"] >= r["o"]
        cls = "qc-up" if up else "qc-down"
        x = cx(i)
        top, bottom = y_price(max(r["o"], r["c"])), y_price(min(r["o"], r["c"]))
        out.append(
            f'<line class="{cls}" x1="{x:.1f}" x2="{x:.1f}" y1="{y_price(r["h"]):.1f}" y2="{y_price(r["l"]):.1f}"/>'
            f'<rect class="{cls} qc-body" x="{x - body_w / 2:.1f}" y="{top:.1f}" width="{body_w:.1f}" height="{max(bottom - top, 1.0):.1f}"/>'
        )
    names = ("qc-s1", "qc-s2", "qc-s3")
    for key, cls in zip(avgs, names):
        d = _path([(cx(i), r[key]) for i, r in enumerate(rows)], y_price)
        if d:
            out.append(f'<path class="qc-line {cls}" d="{d}" clip-path="url(#qc-clip)"/>')

    # --- volume panel
    vmax = max([r["v"] for r in rows] + [r["vavg"] or 0 for r in rows]) or 1.0
    y_vol = lambda v: VOL_TOP + VOL_H - v / vmax * VOL_H  # noqa: E731
    out.append(f'<line class="qc-grid" x1="{LEFT}" x2="{LEFT + pw}" y1="{VOL_TOP + VOL_H}" y2="{VOL_TOP + VOL_H}"/>'
               f'<text class="qc-axis" x="{LEFT + pw + 6}" y="{VOL_TOP + 10}">{_fmt_volume(vmax)}</text>'
               f'<text class="qc-axis" x="{LEFT + 4}" y="{VOL_TOP + 10}">Volume</text>')
    for i, r in enumerate(rows):
        cls = "qc-vup" if r["c"] >= r["o"] else "qc-vdown"
        h = r["v"] / vmax * VOL_H
        out.append(f'<rect class="{cls}" x="{cx(i) - body_w / 2:.1f}" y="{VOL_TOP + VOL_H - h:.1f}" width="{body_w:.1f}" height="{max(h, 0.5):.1f}"/>')
    vavg = _path([(cx(i), r["vavg"]) for i, r in enumerate(rows)], y_vol)
    if vavg:
        out.append(f'<path class="qc-line qc-vavg" d="{vavg}"/>')

    # --- RSI panel
    y_rsi = lambda v: RSI_TOP + (100 - v) / 100 * RSI_H  # noqa: E731
    out.append(f'<rect class="qc-band" x="{LEFT}" y="{y_rsi(70):.1f}" width="{pw}" height="{y_rsi(30) - y_rsi(70):.1f}"/>')
    for level in (70, 50, 30):
        out.append(f'<line class="qc-grid{" qc-mid" if level == 50 else ""}" x1="{LEFT}" x2="{LEFT + pw}" y1="{y_rsi(level):.1f}" y2="{y_rsi(level):.1f}"/>'
                   f'<text class="qc-axis" x="{LEFT + pw + 6}" y="{y_rsi(level) + 4:.1f}">{level}</text>')
    out.append(f'<text class="qc-axis" x="{LEFT + 4}" y="{RSI_TOP + 10}">RSI (14)</text>')
    rsi_path = _path([(cx(i), r["rsi"]) for i, r in enumerate(rows)], y_rsi)
    if rsi_path:
        out.append(f'<path class="qc-line qc-rsi" d="{rsi_path}"/>')

    # --- x axis labels and the hover layer
    marks = sorted({round(i * (n - 1) / 5) for i in range(6)})
    for i in marks:
        anchor = "start" if i == 0 else "end" if i == n - 1 else "middle"
        x_label = LEFT if i == 0 else LEFT + pw if i == n - 1 else cx(i)
        out.append(f'<text class="qc-axis" x="{x_label:.1f}" y="{AXIS_Y}" text-anchor="{anchor}">{html.escape(rows[i]["tick"])}</text>')
    out.append(f'<line id="qc-cross" class="qc-cross" x1="0" x2="0" y1="{PRICE_TOP}" y2="{RSI_TOP + RSI_H}" style="display:none"/>'
               f'<rect id="qc-hit" x="{LEFT}" y="{PRICE_TOP}" width="{pw}" height="{RSI_TOP + RSI_H - PRICE_TOP}" fill="transparent"/>')
    out.append("</svg>")

    if kind == "intraday":
        legend = [("qc-s1", "VWAP (average price paid, weighted by volume)")]
    else:
        legend = [("qc-s1", "20-day average"), ("qc-s2", "50-day average")]
        if any(r["c2"] is not None for r in rows):
            legend.append(("qc-s3", "200-day average"))
    legend_html = "".join(
        f'<span class="qc-key"><i class="qc-swatch {cls}"></i>{html.escape(text)}</span>' for cls, text in legend
    ) + ('<span class="qc-key"><i class="qc-swatch qc-vavg"></i>20-day average volume</span>' if kind == "daily" else "")
    return f'<div class="qc-legend">{legend_html}</div>' + "".join(out)


CHART_CSS = """
.qc { width: 100%; height: auto; display: block; }
.qc-grid { stroke: var(--border); stroke-width: 1; }
.qc-mid { stroke-dasharray: 3 4; }
.qc-prev { stroke: var(--ink-muted); stroke-width: 1; stroke-dasharray: 2 4; }
.qc-axis { fill: var(--ink-muted); font-size: 11px; }
line.qc-up, rect.qc-up { stroke: var(--success); fill: var(--success); }
line.qc-down, rect.qc-down { stroke: var(--danger); fill: var(--danger); }
rect.qc-up.qc-body { fill: var(--surface); stroke-width: 1.4; }
rect.qc-down.qc-body { stroke-width: 1.4; }
.qc-vup { fill: var(--success); opacity: .55; }
.qc-vdown { fill: var(--danger); opacity: .55; }
.qc-band { fill: var(--ink-muted); opacity: .08; }
.qc-line { fill: none; stroke-width: 1.8; stroke-linejoin: round; stroke-linecap: round; }
.qc-s1 { stroke: #2a78d6; background: #2a78d6; }
.qc-s2 { stroke: #d98324; background: #d98324; }
.qc-s3 { stroke: #8a5cc2; background: #8a5cc2; }
.qc-vavg { stroke: var(--ink); background: var(--ink); opacity: .75; }
.qc-rsi { stroke: #2a78d6; }
.qc-cross { stroke: var(--ink-muted); stroke-width: 1; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .qc-s1, :root:not([data-theme="light"]) .qc-rsi { stroke: #6aa8f0; background: #6aa8f0; }
  :root:not([data-theme="light"]) .qc-s2 { stroke: #f0a85a; background: #f0a85a; }
  :root:not([data-theme="light"]) .qc-s3 { stroke: #b794e6; background: #b794e6; }
}
:root[data-theme="dark"] .qc-s1, :root[data-theme="dark"] .qc-rsi { stroke: #6aa8f0; background: #6aa8f0; }
:root[data-theme="dark"] .qc-s2 { stroke: #f0a85a; background: #f0a85a; }
:root[data-theme="dark"] .qc-s3 { stroke: #b794e6; background: #b794e6; }
.qc-legend { display: flex; flex-wrap: wrap; gap: 4px 16px; font-size: 12px; color: var(--ink-muted); margin: 6px 0 2px; }
.qc-key { display: inline-flex; align-items: center; gap: 6px; }
.qc-swatch { display: inline-block; width: 16px; height: 0; border-top: 3px solid; border-radius: 2px; }
.qc-swatch.qc-s1 { border-color: #2a78d6; } .qc-swatch.qc-s2 { border-color: #d98324; } .qc-swatch.qc-s3 { border-color: #8a5cc2; }
.qc-swatch.qc-vavg { border-color: var(--ink); }
:root[data-theme="dark"] .qc-swatch.qc-s1 { border-color: #6aa8f0; } :root[data-theme="dark"] .qc-swatch.qc-s2 { border-color: #f0a85a; }
:root[data-theme="dark"] .qc-swatch.qc-s3 { border-color: #b794e6; }
.qc-swatch { background: none !important; }
"""
