"""What the screener can scan: the S&P 500 (bundled list with sectors), a few big non-S&P names, popular ETFs, your own
holdings (everything linked through Plaid), your watchlist, or tickers you type.

Every entry is {"symbol", "name", "sector", "industry", "type": "stock" | "etf"}. Sectors are the 11 GICS sectors; ETFs that
track one sector carry it, other ETFs carry a plain category ("Broad market", "Bonds", ...). Symbols use the usual dot form
(BRK.B); Yahoo's dash form is made where prices are fetched."""

from __future__ import annotations

import csv
import re
from pathlib import Path

SECTORS = (
    "Communication Services", "Consumer Discretionary", "Consumer Staples", "Energy", "Financials", "Health Care",
    "Industrials", "Information Technology", "Materials", "Real Estate", "Utilities",
)

_SP500 = Path(__file__).with_name("data") / "sp500.csv"

# Big names that are not in the S&P 500 (mostly Nasdaq-100 members listed abroad) plus a few popular growth names.
_EXTRAS = (
    ("ARM", "Arm Holdings", "Information Technology", "Semiconductors"), ("ASML", "ASML Holding", "Information Technology", "Semiconductor Equipment"),
    ("AZN", "AstraZeneca", "Health Care", "Pharmaceuticals"), ("MELI", "MercadoLibre", "Consumer Discretionary", "Broadline Retail"),
    ("PDD", "PDD Holdings", "Consumer Discretionary", "Broadline Retail"), ("MRVL", "Marvell Technology", "Information Technology", "Semiconductors"),
    ("ZS", "Zscaler", "Information Technology", "Systems Software"), ("TEAM", "Atlassian", "Information Technology", "Application Software"),
    ("CCEP", "Coca-Cola Europacific Partners", "Consumer Staples", "Soft Drinks"), ("GFS", "GlobalFoundries", "Information Technology", "Semiconductors"),
    ("TRI", "Thomson Reuters", "Industrials", "Research & Consulting Services"), ("SHOP", "Shopify", "Information Technology", "Application Software"),
    ("SPOT", "Spotify", "Communication Services", "Movies & Entertainment"), ("SNOW", "Snowflake", "Information Technology", "Application Software"),
    ("NET", "Cloudflare", "Information Technology", "Application Software"), ("RBLX", "Roblox", "Communication Services", "Interactive Home Entertainment"),
    ("SOFI", "SoFi Technologies", "Financials", "Consumer Finance"), ("MSTR", "Strategy (MicroStrategy)", "Information Technology", "Application Software"),
    ("TSM", "Taiwan Semiconductor", "Information Technology", "Semiconductors"), ("SMCI", "Super Micro Computer", "Information Technology", "Technology Hardware"),
    ("RDDT", "Reddit", "Communication Services", "Interactive Media & Services"), ("CRWV", "CoreWeave", "Information Technology", "IT Consulting & Other Services"),
    ("IONQ", "IonQ", "Information Technology", "Technology Hardware"), ("AFRM", "Affirm", "Financials", "Consumer Finance"),
    ("SE", "Sea Limited", "Consumer Discretionary", "Broadline Retail"), ("BABA", "Alibaba", "Consumer Discretionary", "Broadline Retail"),
)

# (symbol, name, sector-or-category)
_ETFS = (
    ("SPY", "SPDR S&P 500", "Broad market"), ("VOO", "Vanguard S&P 500", "Broad market"), ("IVV", "iShares Core S&P 500", "Broad market"),
    ("VTI", "Vanguard Total Stock Market", "Broad market"), ("QQQ", "Invesco QQQ (Nasdaq-100)", "Broad market"), ("QQQM", "Invesco Nasdaq 100", "Broad market"),
    ("DIA", "SPDR Dow Jones Industrial", "Broad market"), ("IWM", "iShares Russell 2000", "Broad market"), ("IJH", "iShares S&P Mid-Cap 400", "Broad market"),
    ("IJR", "iShares S&P Small-Cap 600", "Broad market"), ("VUG", "Vanguard Growth", "Broad market"), ("VTV", "Vanguard Value", "Broad market"),
    ("SCHG", "Schwab US Large-Cap Growth", "Broad market"), ("SCHB", "Schwab US Broad Market", "Broad market"), ("SPLG", "SPDR Portfolio S&P 500", "Broad market"),
    ("VB", "Vanguard Small-Cap", "Broad market"), ("VO", "Vanguard Mid-Cap", "Broad market"), ("MTUM", "iShares MSCI USA Momentum", "Broad market"),
    ("QUAL", "iShares MSCI USA Quality", "Broad market"), ("USMV", "iShares MSCI USA Min Vol", "Broad market"),
    ("SCHD", "Schwab US Dividend Equity", "Dividend"), ("VYM", "Vanguard High Dividend Yield", "Dividend"), ("DVY", "iShares Select Dividend", "Dividend"),
    ("VIG", "Vanguard Dividend Appreciation", "Dividend"), ("NOBL", "ProShares S&P 500 Dividend Aristocrats", "Dividend"), ("SPHD", "Invesco S&P 500 High Dividend Low Vol", "Dividend"),
    ("XLK", "Technology Select Sector SPDR", "Information Technology"), ("VGT", "Vanguard Information Technology", "Information Technology"),
    ("SMH", "VanEck Semiconductor", "Information Technology"), ("SOXX", "iShares Semiconductor", "Information Technology"), ("IGV", "iShares Expanded Tech-Software", "Information Technology"),
    ("XLF", "Financial Select Sector SPDR", "Financials"), ("KRE", "SPDR S&P Regional Banking", "Financials"), ("KBE", "SPDR S&P Bank", "Financials"),
    ("XLV", "Health Care Select Sector SPDR", "Health Care"), ("XBI", "SPDR S&P Biotech", "Health Care"), ("IBB", "iShares Biotechnology", "Health Care"),
    ("XLE", "Energy Select Sector SPDR", "Energy"), ("XOP", "SPDR S&P Oil & Gas Exploration", "Energy"), ("OIH", "VanEck Oil Services", "Energy"),
    ("XLY", "Consumer Discretionary Select Sector SPDR", "Consumer Discretionary"), ("XHB", "SPDR S&P Homebuilders", "Consumer Discretionary"), ("ITB", "iShares US Home Construction", "Consumer Discretionary"),
    ("XLP", "Consumer Staples Select Sector SPDR", "Consumer Staples"), ("XLI", "Industrial Select Sector SPDR", "Industrials"), ("JETS", "US Global Jets", "Industrials"),
    ("XLB", "Materials Select Sector SPDR", "Materials"), ("XME", "SPDR S&P Metals & Mining", "Materials"), ("XLU", "Utilities Select Sector SPDR", "Utilities"),
    ("XLRE", "Real Estate Select Sector SPDR", "Real Estate"), ("VNQ", "Vanguard Real Estate", "Real Estate"), ("XLC", "Communication Services Select Sector SPDR", "Communication Services"),
    ("ARKK", "ARK Innovation", "Thematic"), ("ARKW", "ARK Next Generation Internet", "Thematic"), ("ARKG", "ARK Genomic Revolution", "Thematic"),
    ("ARKF", "ARK Fintech Innovation", "Thematic"), ("AIQ", "Global X Artificial Intelligence & Technology", "Thematic"), ("BOTZ", "Global X Robotics & AI", "Thematic"),
    ("ROBO", "ROBO Global Robotics & Automation", "Thematic"), ("CLOU", "Global X Cloud Computing", "Thematic"), ("HACK", "Amplify Cybersecurity", "Thematic"),
    ("CIBR", "First Trust NASDAQ Cybersecurity", "Thematic"), ("SKYY", "First Trust Cloud Computing", "Thematic"), ("DRIV", "Global X Autonomous & Electric Vehicles", "Thematic"),
    ("ICLN", "iShares Global Clean Energy", "Thematic"), ("TAN", "Invesco Solar", "Thematic"), ("LIT", "Global X Lithium & Battery Tech", "Thematic"), ("URA", "Global X Uranium", "Thematic"),
    ("GLD", "SPDR Gold Shares", "Commodities"), ("IAU", "iShares Gold Trust", "Commodities"), ("SLV", "iShares Silver Trust", "Commodities"),
    ("USO", "United States Oil Fund", "Commodities"), ("UNG", "United States Natural Gas Fund", "Commodities"),
    ("TLT", "iShares 20+ Year Treasury", "Bonds"), ("IEF", "iShares 7-10 Year Treasury", "Bonds"), ("SHY", "iShares 1-3 Year Treasury", "Bonds"),
    ("BND", "Vanguard Total Bond Market", "Bonds"), ("AGG", "iShares Core US Aggregate Bond", "Bonds"), ("LQD", "iShares Investment Grade Corporate Bond", "Bonds"),
    ("HYG", "iShares High Yield Corporate Bond", "Bonds"), ("JNK", "SPDR High Yield Bond", "Bonds"), ("TIP", "iShares TIPS Bond", "Bonds"),
    ("VEA", "Vanguard FTSE Developed Markets", "International"), ("VWO", "Vanguard FTSE Emerging Markets", "International"), ("EFA", "iShares MSCI EAFE", "International"),
    ("EEM", "iShares MSCI Emerging Markets", "International"), ("IEFA", "iShares Core MSCI EAFE", "International"), ("IEMG", "iShares Core MSCI Emerging Markets", "International"),
    ("VXUS", "Vanguard Total International Stock", "International"), ("FXI", "iShares China Large-Cap", "International"), ("KWEB", "KraneShares CSI China Internet", "International"),
    ("EWJ", "iShares MSCI Japan", "International"), ("EWZ", "iShares MSCI Brazil", "International"), ("INDA", "iShares MSCI India", "International"),
    ("IBIT", "iShares Bitcoin Trust", "Crypto"), ("FBTC", "Fidelity Wise Origin Bitcoin", "Crypto"), ("ETHA", "iShares Ethereum Trust", "Crypto"), ("BITO", "ProShares Bitcoin Strategy", "Crypto"),
    ("TQQQ", "ProShares UltraPro QQQ (3x)", "Leveraged"), ("SQQQ", "ProShares UltraPro Short QQQ (-3x)", "Leveraged"), ("SOXL", "Direxion Semiconductor Bull 3x", "Leveraged"),
    ("SOXS", "Direxion Semiconductor Bear 3x", "Leveraged"), ("UPRO", "ProShares UltraPro S&P 500 (3x)", "Leveraged"), ("SPXU", "ProShares UltraPro Short S&P 500", "Leveraged"),
    ("TECL", "Direxion Technology Bull 3x", "Leveraged"),
)

# Themes a person might name ("AI stocks"): a list of tickers, or industry words found in the GICS sub-industry.
THEMES = {
    "ai": {"label": "AI", "tickers": (
        "NVDA", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "AMD", "AVGO", "PLTR", "ORCL", "CRM", "NOW", "SNOW", "ARM", "TSM", "SMCI", "MRVL",
        "ANET", "MU", "INTC", "ADBE", "IBM", "DELL", "VRT", "CRWV", "AI", "PATH", "TSLA", "APP", "ASML", "SMH", "SOXX", "AIQ", "BOTZ", "ROBO", "IGV", "ARKW")},
    "semiconductors": {"label": "Semiconductors", "industries": ("Semiconductor",), "tickers": ("SMH", "SOXX", "SOXL")},
    "software": {"label": "Software", "industries": ("Software",), "tickers": ("IGV", "CLOU", "SKYY")},
    "cybersecurity": {"label": "Cybersecurity", "tickers": ("CRWD", "PANW", "ZS", "FTNT", "NET", "OKTA", "S", "CHKP", "HACK", "CIBR")},
    "crypto": {"label": "Crypto", "tickers": ("COIN", "MSTR", "HOOD", "IBIT", "FBTC", "ETHA", "BITO")},
    "biotech": {"label": "Biotech", "industries": ("Biotechnology",), "tickers": ("XBI", "IBB", "ARKG")},
    "banks": {"label": "Banks", "industries": ("Bank",), "tickers": ("KRE", "KBE")},
    "energy transition": {"label": "Clean energy", "tickers": ("ENPH", "FSLR", "NEE", "TAN", "ICLN", "LIT", "URA")},
}

_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,4}([.\-][A-Z])?$")
_cache: list[dict] | None = None


def clean_symbol(raw) -> str | None:
    sym = str(raw or "").strip().upper()
    if re.fullmatch(r"[A-Z]{1,5}-[A-Z]", sym):
        sym = sym.replace("-", ".")           # BRK-B -> BRK.B
    return sym if _SYMBOL.match(sym) else None


def yahoo_symbol(sym: str) -> str:
    return sym.replace(".", "-")


def market_entries() -> list[dict]:
    """The S&P 500, the extra stocks and the ETFs (cached)."""
    global _cache
    if _cache is not None:
        return _cache
    out, seen = [], set()
    with open(_SP500, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sym = row["symbol"].strip().upper()
            if sym and sym not in seen:
                seen.add(sym)
                out.append({"symbol": sym, "name": row["name"], "sector": row["sector"], "industry": row["industry"], "type": "stock"})
    for sym, name, sector, industry in _EXTRAS:
        if sym not in seen:
            seen.add(sym)
            out.append({"symbol": sym, "name": name, "sector": sector, "industry": industry, "type": "stock"})
    for sym, name, sector in _ETFS:
        if sym not in seen:
            seen.add(sym)
            out.append({"symbol": sym, "name": name, "sector": sector, "industry": "", "type": "etf"})
    _cache = out
    return out


def _known() -> dict[str, dict]:
    return {e["symbol"]: e for e in market_entries()}


def custom_entries(symbols) -> list[dict]:
    """Entries for tickers typed or saved by the person, using the bundled sector where the ticker is known."""
    known, out, seen = _known(), [], set()
    for raw in symbols or []:
        sym = clean_symbol(raw)
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(known.get(sym) or {"symbol": sym, "name": "", "sector": "", "industry": "", "type": "stock"})
    return out


_HELD_KEY = "screener_broker_held"


def remember_broker_positions(broker: str, positions) -> None:
    """Called whenever a trading tab reads its positions: keeps symbol, name, shares and value so "my holdings" can include what is
    held directly at Alpaca, IBKR or E*TRADE (not linked through Plaid) and the Risk tab can add it all up. Never raises."""
    try:
        import json
        from datetime import datetime
        from source.common import db
        merged: dict[str, dict] = {}
        for p in positions or []:
            sym = clean_symbol((p or {}).get("symbol"))
            if not sym:
                continue
            row = merged.setdefault(sym, {"symbol": sym, "name": str(p.get("name") or "")[:60], "qty": 0.0, "value": 0.0})
            try:
                row["qty"] += float(p.get("qty") or 0)
                row["value"] += float(p.get("market_value") or 0)
            except (TypeError, ValueError):
                pass
        rows = [{**r, "qty": round(r["qty"], 4), "value": round(r["value"], 2)} for r in merged.values()]
        raw = db.get_meta(_HELD_KEY)
        data = json.loads(raw) if raw else {}
        data = data if isinstance(data, dict) else {}
        if (data.get(broker) or {}).get("rows") != rows:
            data[broker] = {"rows": rows, "at": datetime.now().isoformat(timespec="minutes")}
            db.set_meta(_HELD_KEY, json.dumps(data))
    except Exception:       # noqa: BLE001 -- bookkeeping must never break a trading page
        pass


def broker_positions() -> dict:
    """{broker: {"rows": [{symbol, name, qty, value}], "at": iso}} as last shown on the Alpaca / IBKR / E*TRADE tabs."""
    try:
        import json
        from source.common import db
        raw = db.get_meta(_HELD_KEY)
        data = json.loads(raw) if raw else {}
        return {b: v for b, v in data.items() if isinstance(v, dict) and isinstance(v.get("rows"), list)} if isinstance(data, dict) else {}
    except Exception:       # noqa: BLE001
        return {}


def broker_held_symbols() -> list[str]:
    return [r["symbol"] for b, v in sorted(broker_positions().items()) for r in v["rows"] if clean_symbol(r.get("symbol"))]


def holdings_symbols() -> list[str]:
    """Tickers of everything held: accounts linked through Plaid (stocks, ETFs and funds with a ticker) plus what the Alpaca, IBKR
    and E*TRADE tabs last showed as positions."""
    from source.common import db
    syms, seen = [], set()
    for h in db.list_plaid_holdings():
        sym = clean_symbol(h.get("ticker_symbol"))
        if sym and sym not in seen and str(h.get("security_type") or "").lower() in ("equity", "etf", "mutual fund", ""):
            seen.add(sym)
            syms.append(sym)
    for sym in broker_held_symbols():
        if sym not in seen:
            seen.add(sym)
            syms.append(sym)
    return syms


def watchlist_symbols() -> list[str]:
    from source.common import db
    return [i["symbol"] for i in db.watchlist.list_items()]


def entries_for(universes, tickers=None) -> list[dict]:
    """The entries to scan for the chosen universes: any of "market", "holdings", "watchlist", "custom"."""
    chosen = list(universes or ["market"])
    out, seen = [], set()

    def add(items):
        for e in items:
            if e["symbol"] not in seen:
                seen.add(e["symbol"])
                out.append(e)

    if "market" in chosen:
        add(market_entries())
    if "holdings" in chosen:
        add(custom_entries(holdings_symbols()))
    if "watchlist" in chosen:
        add(custom_entries(watchlist_symbols()))
    if "custom" in chosen or tickers:
        add(custom_entries(tickers))
    return out
