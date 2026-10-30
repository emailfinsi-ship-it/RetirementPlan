"""Turns a plain-English request into screener filters, with no outside service: patterns for the things the screener can
filter on (MACD crossovers, RSI levels, sectors, swings of dollars or percent over a window, price, moving averages,
52-week highs and lows, volume, put/call volume, stocks vs ETFs, your holdings / watchlist / typed tickers).

``parse`` returns {"filters": <filters.normalize output>, "understood": [phrases], "ignored": [words it could not use]}.
The result is shown in the form so the person can correct it before running; nothing is run from a guess."""

from __future__ import annotations

import re

from source.screener import filters as flt
from source.screener import universe

_NUM = r"(\d+(?:\.\d+)?)"
_MONEY = r"\$\s?" + _NUM
_PCT = _NUM + r"\s?(?:%|percent|pct)"

SECTOR_WORDS = {
    "Information Technology": ("information technology", "technology", "tech", "software", "semiconductor", "semiconductors", "chip", "chips"),
    "Health Care": ("health care", "healthcare", "health", "pharma", "pharmaceutical", "pharmaceuticals", "biotech"),
    "Financials": ("financials", "financial", "finance", "banks", "bank", "insurance"),
    "Consumer Discretionary": ("consumer discretionary", "discretionary", "retail", "autos", "auto makers"),
    "Consumer Staples": ("consumer staples", "staples", "food", "beverage", "grocery"),
    "Energy": ("energy", "oil", "gas", "oil and gas"),
    "Industrials": ("industrials", "industrial", "aerospace", "defense", "airlines", "transportation"),
    "Materials": ("materials", "mining", "chemicals", "metals"),
    "Utilities": ("utilities", "utility"),
    "Real Estate": ("real estate", "reits", "reit"),
    "Communication Services": ("communication services", "communications", "communication", "telecom", "media"),
}
# words that name an industry rather than a whole sector: they become industry keywords, not sector filters
INDUSTRY_WORDS = {"semiconductor": "Semiconductor", "semiconductors": "Semiconductor", "chip": "Semiconductor", "chips": "Semiconductor",
                  "software": "Software", "biotech": "Biotechnology", "pharma": "Pharmaceuticals", "pharmaceutical": "Pharmaceuticals",
                  "pharmaceuticals": "Pharmaceuticals", "banks": "Bank", "bank": "Bank", "insurance": "Insurance", "airlines": "Airlines",
                  "oil and gas": "Oil", "reits": "REIT", "reit": "REIT", "defense": "Aerospace", "aerospace": "Aerospace"}
THEME_WORDS = {"ai": ("ai", "artificial intelligence", "a.i."), "cybersecurity": ("cybersecurity", "cyber security", "cyber"),
               "crypto": ("crypto", "bitcoin", "cryptocurrency"), "energy transition": ("clean energy", "solar", "renewable", "renewables")}
_STOP_CAPS = {"AI", "ETF", "ETFS", "RSI", "MACD", "SMA", "USD", "SP", "S&P", "PE", "EPS", "IPO", "OR", "AND", "THE", "A", "I", "US", "ALL", "TOP",
              "UP", "DOWN", "BUY", "SELL", "PUT", "CALL", "CALLS", "PUTS", "VOL", "MA", "EMA", "ATH", "YTD", "ITM", "OTM", "IT", "ON", "IN", "AT",
              "OVER", "UNDER", "BELOW", "ABOVE", "NOT", "NEW", "LOW", "HIGH"}

_UP = r"(?:up|gain(?:ed|ing|s)?|rose|rise|risen|rising|jump(?:ed|ing|s)?|surg(?:e|ed|es|ing)|rall(?:y|ied|ies|ying)|climb(?:ed|ing|s)?|higher|increase[ds]?|increasing)"
_DOWN = r"(?:down|drop(?:ped|ping|s)?|fell|fall(?:en|ing|s)?|declin(?:e|ed|es|ing)|plung(?:e|ed|es|ing)|slump(?:ed|ing|s)?|lost|lose|losing|lower|decrease[ds]?|decreasing|sank|sink)"
_SWINGISH = r"(?:swing(?:s|ing)?|mov(?:e|ed|es|ing)|chang(?:e|ed|es|ing)|volatil\w*|range|jump\w*|surg\w*|plung\w*|" + _UP + "|" + _DOWN + ")"

_WINDOWS = (
    (r"(?:today|intraday|in a day|one day|1[- ]?day|a day|daily|24 hours|overnight)", "1d"),
    (r"(?:2|two)[- ]?weeks?|fortnight|10[- ]?days?", "2w"),
    (r"(?:this|last|past|in a|one|1)[- ]?(?:trading )?week|weekly|5[- ]?days?|7[- ]?days?", "1w"),
    (r"(?:3|three)[- ]?months?|quarter|90[- ]?days?", "3m"),
    (r"(?:6|six)[- ]?months?|half[- ]?year", "6m"),
    (r"(?:this|last|past|in a|one|1)[- ]?month|monthly|30[- ]?days?|21[- ]?days?", "1m"),
    (r"(?:this|last|past|in a|one|1)[- ]?year|yearly|annual|12[- ]?months?|52[- ]?weeks?", "1y"),
)


def _window_in(text: str) -> str | None:
    best, pos = None, None
    for pattern, key in _WINDOWS:
        m = re.search(pattern, text)
        if m and (pos is None or m.start() < pos):
            best, pos = key, m.start()
    return best


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in re.split(r"[;,]|\band\b(?!\s+(?:gas|\d))|\bwith\b|\bplus\b", text) if c.strip()]


def _parse_swings(text: str, understood: list[str]) -> list[dict]:
    out = []
    for clause in _clauses(text):
        if re.search(r"\b(?:rsi|macd|put/?call|price (?:under|below|above|over)|under \$|below \$)", clause) and not re.search(_SWINGISH, clause):
            continue
        if not re.search(_SWINGISH, clause):
            continue
        pct = re.search(_PCT, clause)
        usd = re.search(_MONEY, clause) or re.search(_NUM + r"\s?(?:dollars?|bucks)", clause)
        if not pct and not usd:
            continue
        if re.search(r"\brsi\b", clause) and not re.search(r"(?:swing|move|range|up|down)", clause.replace("rsi", "")):
            continue
        is_range = bool(re.search(r"\b(?:range|intraday swing|high[- ]to[- ]low|day swing|daily swing|swings? (?:of|by|over|more))", clause)) and not re.search(_UP + "|" + _DOWN, clause)
        direction = "up" if re.search(r"\b" + _UP + r"\b", clause) else "down" if re.search(r"\b" + _DOWN + r"\b", clause) else "either"
        if re.search(r"\b(?:up or down|either way|up and down|both ways|in either direction)\b", clause):
            direction = "either"
        window = _window_in(clause) or ("1d" if is_range else "1w")
        if window == "1d" and not is_range and re.search(r"(?:swing|range)", clause) and not re.search(_UP + "|" + _DOWN, clause):
            is_range = True
        out.append({"kind": "range" if is_range else "move", "window": window, "direction": direction,
                    "pct": float(pct.group(1)) if pct else None, "usd": float(usd.group(1)) if usd else None})
    if out:
        understood.append("swing threshold")
    return out


def parse(text: str) -> dict:
    raw = str(text or "")
    t = " " + raw.lower().replace("&", " and ").replace("–", "-").replace("—", "-") + " "
    t = re.sub(r"\s+", " ", t)
    understood: list[str] = []
    f: dict = {}

    # stocks vs ETFs
    has_etf, has_stock = bool(re.search(r"\betfs?\b|\bfunds?\b", t)), bool(re.search(r"\bstocks?\b|\bequities\b|\bshares\b|\bcompanies\b", t))
    if has_etf and not has_stock:
        f["assets"] = ["etf"]
    elif has_stock and not has_etf:
        f["assets"] = ["stock"]
    if has_etf or has_stock:
        understood.append("stocks / ETFs")

    # universe
    universe_list = []
    if re.search(r"\bmy (?:holdings?|portfolio|positions?|stocks|accounts?)\b|\bi (?:own|hold)\b|\bamong what i own\b", t):
        universe_list.append("holdings")
    if re.search(r"\bmy watch ?list\b|\bwatch ?list\b", t):
        universe_list.append("watchlist")
    typed = []
    for tok in re.findall(r"(?<![A-Za-z$])\$?([A-Z]{1,5}(?:[.\-][A-Z])?)(?![A-Za-z])", raw):
        if tok not in _STOP_CAPS and len(tok) >= 2 and tok not in typed:
            typed.append(tok)
    only_typed = bool(typed) and bool(re.search(r"\b(?:only|among|from|in|just|check|screen|scan)\b", t)) and len(typed) >= 1
    if only_typed:
        f["tickers"] = typed
        universe_list.append("custom")
        understood.append("tickers you named")
    if universe_list:
        f["universe"] = universe_list if not (typed and not re.search(r"\bmarket\b|\bs and p\b|s&p", t)) else universe_list
        understood.append("where to scan")

    # theme / sectors / industries
    for key, words in THEME_WORDS.items():
        if any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", t) for w in words):
            f["theme"] = key
            understood.append("theme")
            break
    sectors, industries = [], []
    for sector, words in SECTOR_WORDS.items():
        for w in sorted(words, key=len, reverse=True):
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", t):
                if w in INDUSTRY_WORDS:
                    ind = INDUSTRY_WORDS[w]
                    if ind not in industries:
                        industries.append(ind)
                elif sector not in sectors:
                    sectors.append(sector)
                break
    if re.search(r"\b(?:sectors?|in|within|from)\b", t) or sectors or industries:
        pass
    if sectors:
        f["sectors"] = sectors
        understood.append("sector")
    if industries and not f.get("theme"):
        f["industries"] = industries
        understood.append("industry")

    # MACD
    if "macd" in t:
        window = re.search(r"(?:within|in|over|during|past|last)(?: the)?(?: last| past)? " + _NUM + r" (?:trading )?(?:days?|sessions?|bars?)", t)
        days = int(float(window.group(1))) if window else (1 if re.search(r"\b(?:today|just|this morning)\b", t) else 3 if "yesterday" in t else
                                                              5 if re.search(r"\b(?:this week|recent|recently|past week|last week)\b", t) else 5)
        clause = next((c for c in _clauses(t) if "macd" in c), t)       # judge direction words only within MACD's own clause
        near = clause
        if re.search(r"cross", t):
            if re.search(r"\b(?:bullish|up|upward|positive|above|buy|golden)\b", near) and not re.search(r"\b(?:bearish|down|downward|negative|below|sell|death)\b", near):
                f["macd"] = {"cross": "bullish", "within_days": days}
            elif re.search(r"\b(?:bearish|down|downward|negative|below|sell|death)\b", near) and not re.search(r"\b(?:bullish|up|upward|positive)\b", near):
                f["macd"] = {"cross": "bearish", "within_days": days}
            else:
                f["macd"] = {"cross": "any", "within_days": days}
        elif re.search(r"above (?:its |the )?signal", t):
            f["macd"] = {"state": "above"}
        elif re.search(r"below (?:its |the )?signal", t):
            f["macd"] = {"state": "below"}
        elif re.search(r"\bbullish macd|macd (?:is )?bullish|macd positive\b", t):
            f["macd"] = {"state": "above"}
        elif re.search(r"\bbearish macd|macd (?:is )?bearish|macd negative\b", t):
            f["macd"] = {"state": "below"}
        else:
            f["macd"] = {"cross": "any", "within_days": days}
        understood.append("MACD")

    # RSI
    rsi = None
    m = re.search(r"rsi\s*(?:\(\d+\))?\s*(?:is |was )?(?:between|from)\s*" + _NUM + r"\s*(?:and|to|-)\s*" + _NUM, t) or re.search(r"rsi\s*" + _NUM + r"\s*-\s*" + _NUM, t)
    if m:
        rsi = {"min": float(m.group(1)), "max": float(m.group(2))}
    else:
        m = re.search(r"rsi\s*(?:\(\d+\))?\s*(?:is |was |of )?(?:under|below|less than|lower than|<=?|at most|no more than|beneath)\s*" + _NUM, t)
        if m:
            rsi = {"min": None, "max": float(m.group(1))}
        m2 = re.search(r"rsi\s*(?:\(\d+\))?\s*(?:is |was |of )?(?:over|above|greater than|higher than|more than|>=?|at least|exceeds?)\s*" + _NUM, t)
        if m2:
            rsi = {**(rsi or {"min": None, "max": None}), "min": float(m2.group(1))}
        if rsi is None:
            m3 = re.search(r"rsi\s*(?:\(\d+\))?\s*(?:is |was |of |at |=)\s*" + _NUM, t)
            if m3:
                v = float(m3.group(1))
                rsi = {"min": max(0, v - 5), "max": min(100, v + 5)}
    if rsi is None:
        if re.search(r"\boversold\b", t):
            rsi = {"min": None, "max": 30.0}
        elif re.search(r"\boverbought\b", t):
            rsi = {"min": 70.0, "max": None}
    if rsi:
        f["rsi"] = rsi
        understood.append("RSI")

    # swing threshold
    swings = _parse_swings(t, understood)
    if swings:
        f["swing"] = swings

    # price
    pm = re.search(r"(?:price|priced|trading|costs?|costing|share price)\s*(?:is |of )?(?:under|below|less than|<=?|cheaper than|at most)\s*" + _MONEY, t) \
        or re.search(r"(?:stocks?|etfs?|shares)\s+(?:under|below|less than|cheaper than)\s*" + _MONEY, t)
    pa = re.search(r"(?:price|priced|trading|costs?|costing|share price)\s*(?:is |of )?(?:over|above|more than|>=?|at least)\s*" + _MONEY, t) \
        or re.search(r"(?:stocks?|etfs?|shares)\s+(?:over|above|more than)\s*" + _MONEY, t)
    pr = re.search(r"(?:price|priced)\s*(?:is )?between\s*" + _MONEY + r"\s*(?:and|to|-)\s*" + _MONEY, t)
    if pr:
        f["price"] = {"min": float(pr.group(1)), "max": float(pr.group(2))}
    elif pm or pa:
        f["price"] = {"min": float(pa.group(1)) if pa else None, "max": float(pm.group(1)) if pm else None}
    if f.get("price"):
        understood.append("price")

    # price vs moving average
    sm = re.search(r"(above|over|below|under)\s+(?:its |the |their )?(20|50|200)[- ]?(?:day|d)?\s*(?:moving average|average|ma|sma|ema)", t)
    if sm:
        f["sma"] = {"window": int(sm.group(2)), "relation": "above" if sm.group(1) in ("above", "over") else "below"}
        understood.append("moving average")

    # 52-week
    nw = re.search(r"(?:within " + _NUM + r"\s?%?\s*of|near|close to|at|hitting|new)\s*(?:its |their |a |an )?(?:52|fifty[- ]two)[- ]?(?:week|wk)\s*(high|low)", t) \
        or re.search(r"(?:52|fifty[- ]two)[- ]?(?:week|wk)\s*(high|low)", t)
    if nw:
        within = re.search(r"within " + _NUM + r"\s?%?\s*of", t)
        side = nw.group(nw.lastindex)
        f["near_52w"] = {"side": side, "within_pct": float(within.group(1)) if within else (1.0 if re.search(r"\b(?:at|hitting|new)\b", nw.group(0)) else 5.0)}
        understood.append("52-week")

    # volume
    vm = re.search(r"volume\s*(?:is |of )?(?:at least |over |above |more than |>=?)?\s*" + _NUM + r"\s?(?:x|times)", t) or re.search(_NUM + r"\s?(?:x|times)\s*(?:the |its |average |normal )*volume", t)
    if vm:
        f["volume_ratio_min"] = float(vm.group(1))
    elif re.search(r"volume (?:spike|surge|jump)|unusual volume|high volume|heavy volume|volume (?:is )?(?:above|higher than) average", t):
        f["volume_ratio_min"] = 1.5
    if f.get("volume_ratio_min"):
        understood.append("volume")

    # put / call volume
    if re.search(r"put\s*/?\s*(?:to\s*)?call|call\s*/?\s*(?:to\s*)?put|\bcalls?\b.*\bputs?\b|\bputs?\b.*\bcalls?\b|options? volume|options? flow", t):
        mm = re.search(r"put\s*/?\s*(?:to\s*)?call(?: volume)?(?: ratio)?\s*(?:is |of )?(under|below|less than|<=?|over|above|greater than|more than|>=?|at least|at most)\s*" + _NUM, t)
        if mm:
            val = float(mm.group(2))
            f["put_call"] = {"min": val, "max": None} if mm.group(1) in ("over", "above", "greater than", "more than", ">", ">=", "at least") else {"min": None, "max": val}
        elif re.search(r"more calls than puts|call volume (?:is )?(?:higher|greater|above|bigger|more)|bullish (?:options|call)|call heavy|heavy call|calls? (?:exceed|outnumber|dominate)", t):
            f["put_call"] = {"min": None, "max": 0.7}
        elif re.search(r"more puts than calls|put volume (?:is )?(?:higher|greater|above|bigger|more)|bearish (?:options|put)|put heavy|heavy put|puts? (?:exceed|outnumber|dominate)", t):
            f["put_call"] = {"min": 1.2, "max": None}
        if f.get("put_call"):
            understood.append("put/call volume")

    # rating
    if re.search(r"\b(?:strong )?buy rating|rated buy|technical buy|buy signal|rated (?:a )?strong buy", t):
        f["rating"] = "buy"
        understood.append("rating")
    elif re.search(r"\b(?:strong )?sell rating|rated sell|technical sell|sell signal", t):
        f["rating"] = "sell"
        understood.append("rating")

    # how many / sort
    lm = re.search(r"\b(?:top|first|best|show(?: me)?|give me|list|only)\s+(\d{1,3})\b", t)
    if lm:
        f["limit"] = int(lm.group(1))
    if re.search(r"\b(?:biggest|largest|most) (?:movers?|swing|move)|sort(?:ed)? by (?:move|change)", t):
        f["sort"] = "move"
    elif re.search(r"\blowest rsi|most oversold|sort(?:ed)? by rsi", t):
        f["sort"] = "rsi"
    elif re.search(r"\bvolume (?:leaders?|spikes?)|sort(?:ed)? by volume", t):
        f["sort"] = "volume"

    ignored = []
    try:
        normalized = flt.normalize(f)
    except ValueError as exc:
        normalized = flt.normalize({k: v for k, v in f.items() if k not in ("rsi", "price", "put_call", "near_52w", "swing")})
        ignored.append(str(exc))
    return {"filters": normalized, "understood": flt.describe(normalized), "ignored": ignored, "recognized": sorted(set(understood))}
