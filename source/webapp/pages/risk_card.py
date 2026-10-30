"""The Stock Analysis tab's "Portfolio risk" card: how concentrated everything you hold is (one stock, one sector, cash, one firm),
across the accounts linked through Plaid and the Alpaca, IBKR and E*TRADE tabs, plus a heads-up for big holdings that report
earnings within a week. Read-only: it never places an order and is not advice."""

from __future__ import annotations

import html

from source.reporting import position_risk

_CSS = """
.rk-find { margin:6px 0; padding:8px 12px; border-radius:10px; border:1px solid var(--border); font-size:14px; }
.rk-find.warn { border-color:var(--warn); } .rk-find.ok { border-color:var(--success); }
.rk-cols { display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:14px 26px; margin-top:12px; }
.rk-bar { display:grid; grid-template-columns:minmax(90px,150px) 1fr 54px; gap:8px; align-items:center; font-size:13px; margin:4px 0; }
.rk-bar i { display:block; height:10px; border-radius:6px; background:var(--brand); min-width:2px; }
.rk-bar i.warn, .rk-bar i.big { background:var(--danger); } .rk-bar i.watch { background:var(--warn); }
.rk-bar .n { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.rk-bar .p { text-align:right; font-variant-numeric:tabular-nums; }
.rk-chip { display:inline-block; font-size:11px; font-weight:700; border-radius:999px; padding:0 7px; margin-left:4px; border:1px solid var(--warn); color:var(--warn); }
.rk-chip.big { border-color:var(--danger); color:var(--danger); }
"""

_JS = r"""
<script>
(function () {
  var box = document.getElementById('rk-earn'); if (!box || typeof postJSON !== 'function') { return; }
  postJSON('/api/earnings/week', {}).then(function (d) {
    var soon = (d.items || []).filter(function (i) {
      var days = (new Date(i.date + 'T12:00:00') - new Date(d.today + 'T12:00:00')) / 86400000;
      return i.pct != null && i.pct >= __MIN__ && days <= 7 && (i.sources || []).indexOf('holding') >= 0;
    });
    if (!soon.length) { return; }
    box.hidden = false;
    box.innerHTML = '<strong>Reporting earnings within a week:</strong> ' + soon.map(function (i) {
      return i.symbol + ' (' + Number(i.pct).toFixed(0) + '% of your stocks, ' + new Date(i.date + 'T12:00:00').toLocaleDateString('en-US', {weekday: 'short', month: 'short', day: 'numeric'}) + ')';
    }).join(', ') + '. Prices often jump after a report.';
  }).catch(function () {});
})();
</script>
"""


def _bar(label: str, pct: float, cls: str = "", title: str = "", link: str = "", top: float = 1.0) -> str:
    name = f'<a href="{link}">{html.escape(label)}</a>' if link else html.escape(label)
    return (f'<div class="rk-bar" title="{html.escape(title, quote=True)}"><span class="n">{name}</span>'
            f'<span><i class="{cls}" style="width:{min(100.0, pct / (top or 1.0) * 100):.1f}%"></i></span><span class="p">{pct * 100:.1f}%</span></div>')


def risk_card_html() -> str:
    try:
        data = position_risk.collect()
        res = position_risk.analyze(data["rows"])
    except Exception:       # noqa: BLE001 -- the risk card must never break the Stock Analysis page
        return ""
    if not res["total"]:
        return ('<div class="card"><h3 style="margin-top:0;">Portfolio risk</h3><p class="muted">Nothing to look at yet. Link your investment accounts in Setup, '
                'or open the Alpaca, IBKR or E*TRADE tab once so this card can add up what you hold there.</p></div>')
    finds = "".join(f'<div class="rk-find {f["level"]}">{html.escape(f["text"])}</div>' for f in res["findings"])
    pos = "".join(_bar(p["symbol"], p["pct"], p["flag"], f"{p['name']} · ${p['value']:,.0f} · {p['sector']} · {', '.join(p['firms'])}",
                       f"/stock-analysis.html?symbol={html.escape(p['symbol'], quote=True)}", res["positions"][0]["pct"]) for p in res["positions"])
    sec = "".join(_bar(s["sector"], s["pct"], "warn" if s["flag"] else "", f"${s['value']:,.0f}", "", res["sectors"][0]["pct"]) for s in res["sectors"][:8])
    firms = "".join(_bar(f["firm"], f["pct"], "", f"${f['value']:,.0f}", "", res["firms"][0]["pct"]) for f in res["firms"][:8])
    seen = [f"{s['name']} (as of {s['seen'].replace('T', ' ')})" for s in data["sources"] if s["seen"]]
    note = ("Added up from your linked accounts and from what the trading tabs last showed: " + ", ".join(seen) + ". Open a trading tab to refresh it."
            if seen else "Added up from your linked accounts. Open the Alpaca, IBKR or E*TRADE tab once to include what you hold there directly.")
    return (f'<style>{_CSS}</style><div class="card" id="risk-card"><h3 style="margin-top:0;">Portfolio risk</h3>'
            f'<p class="muted">What you hold in total: <strong>${res["total"]:,.0f}</strong> across {res.get("count", 0)} holdings. {html.escape(note)}</p>'
            f'{finds}<div class="rk-find warn" id="rk-earn" hidden></div>'
            f'<div class="rk-cols"><div><h4 style="margin:0 0 6px;">Biggest holdings (share of everything)</h4>{pos}</div>'
            f'<div><h4 style="margin:0 0 6px;">By sector</h4>{sec}<h4 style="margin:14px 0 6px;">By firm</h4>{firms}</div></div>'
            f'<p class="muted small">Rules of thumb, not advice: a single stock above {position_risk.SINGLE_HOLDING_LIMIT * 100:.0f}% or a sector above '
            f'{position_risk.SECTOR_LIMIT * 100:.0f}% is flagged. Funds count as one holding spread across many companies.</p></div>'
            + _JS.replace("__MIN__", str(position_risk.EARNINGS_MIN_PCT)))
