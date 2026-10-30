"""The Trading tab: Alpaca balances, positions and orders plus a preview-then-
confirm order ticket, for a PRACTICE (paper) account (/trading.html) and, as a
separate page, a LIVE real-money account (/trading-live.html). Live trading is
off until the owner arms it (see source.common.db.live_trading and
source.webapp.trading_api). Neither account's balances are counted in net
worth or the retirement plan."""

from __future__ import annotations

import html
from datetime import datetime

from source.collector import alpaca, alpaca_view
from source.common import db, secrets_store
from source.webapp.pages import position_ratings
from source.webapp.render_helpers import _money, _shell

_OPEN_STATUSES = {"new", "accepted", "pending_new", "partially_filled", "held", "accepted_for_bidding", "pending_replace"}


def _num(value, places: int = 2) -> str:
    return "--" if value is None else f"{value:,.{places}f}"


def _signed_money(value) -> str:
    if value is None:
        return "--"
    return f"{'+' if value >= 0 else '-'}{_money(abs(value), cents=True)}"


def _connect_card_html(mode: str, again: bool = False) -> str:
    if mode == "live":
        blurb = (
            '<p class="status-line status-warn"><strong>Real money.</strong> These are your live Alpaca keys. Orders sent from this tab '
            'buy and sell real investments in your Alpaca brokerage account. Keys are stored in the macOS Keychain, never in the database, '
            'and live trading stays switched off until you turn it on here.</p>'
            '<p class="muted">In your Alpaca dashboard, switch to <em>Live</em>, open <em>API Keys</em>, generate a key and paste both parts. '
            'A key you create for this app can be revoked at any time from the Alpaca dashboard.</p>'
        )
        title = "Enter your Alpaca live keys again" if again else "Connect your Alpaca live account"
    else:
        blurb = (
            '<p class="muted">Alpaca offers a free <strong>paper trading</strong> account: play money, real market prices. In your Alpaca '
            'dashboard switch to <em>Paper</em>, open <em>API Keys</em>, generate a key, and paste both parts here. They are stored in the '
            'macOS Keychain with your other credentials, never in the database.</p>'
        )
        title = "Enter your Alpaca practice keys again" if again else "Connect your Alpaca practice account"
    return f"""
<div class="card">
<h3 style="margin-top:0;">{title}</h3>
{blurb}
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/alpaca-keys', {{key_id: this.key_id.value, secret: this.secret.value, mode: '{mode}'}})
    .then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Key ID<input name="key_id" autocomplete="off" style="width:220px" required></label>
  <label>Secret<input name="secret" type="password" autocomplete="off" style="width:260px" required></label>
  <button type="submit" class="primary">Connect</button>
</form>
</div>
"""


def _disconnect_js(mode: str) -> str:
    return (
        "if (confirm('Remove the saved Alpaca keys from this computer?')) "
        f"postJSON('/api/alpaca-keys/delete', {{mode: '{mode}'}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});"
    )


def _account_card_html(acct: dict, mode: str) -> str:
    change = None
    if acct["equity"] is not None and acct["last_equity"] is not None:
        change = acct["equity"] - acct["last_equity"]
    blocked = (
        '<p class="status-line status-warn">Alpaca reports trading is blocked on this account.</p>'
        if acct["trading_blocked"] else ""
    )
    return f"""
<div class="card">
<div class="tiles">
  <div class="tile"><div class="label">{"Account value" if mode == "live" else "Practice account value"}</div><div class="value">{_money(acct["equity"], cents=True)}</div></div>
  <div class="tile"><div class="label">Cash</div><div class="value">{_money(acct["cash"], cents=True)}</div></div>
  <div class="tile"><div class="label">Buying power</div><div class="value">{_money(acct["buying_power"], cents=True)}</div></div>
  <div class="tile"><div class="label">Change since yesterday</div><div class="value">{_signed_money(change)}</div></div>
</div>
{blocked}
<p class="muted" style="margin-bottom:0;">Account {html.escape(acct["account_number"] or "--")} ({html.escape(acct["status"] or "unknown")}).
<button type="button" onclick="{html.escape(_disconnect_js(mode))}">Disconnect</button></p>
</div>
"""


def _gain_cell(p: dict) -> str:
    pl = p["unrealized_pl"]
    pct = "" if p["unrealized_plpc"] is None else f" ({p['unrealized_plpc'] * 100:+.1f}%)"
    color = "#1baf7a" if (pl or 0) >= 0 else "#c94a4a"
    return f'<td class="num" style="color:{color};">{_signed_money(pl)}{pct}</td>'


def _sell_cell(p: dict) -> str:
    """A Sell button that fills the order form below (the person then picks Market or a Limit price and
    previews it as usual -- nothing is sent from here). Whole shares only, as the form takes whole shares."""
    qty = p.get("qty") or 0
    sym = html.escape(p["symbol"], quote=True)
    return (f'<td class="num"><button type="button" class="trade-btn" data-sym="{sym}" data-qty="{qty:g}" '
            f'title="Buy or sell {sym}: fills in the order form below; nothing is sent until you preview and confirm" '
            f'onclick="tradeMenu(this)">Trade &#9662;</button></td>')


def _positions_html(positions: list[dict]) -> str:
    if not positions:
        return '<p class="muted">No positions yet. Place a practice order below to see it here.</p>'
    rows = "".join(
        f"<tr><td><a href=\"/stock-analysis.html?symbol={html.escape(p['symbol'], quote=True)}\" title=\"Open in Stock Analysis\">"
        f"<strong>{html.escape(p['symbol'])}</strong></a></td>"
        f"<td class=\"num\">{html.escape(_num(p['qty'], 4).rstrip('0').rstrip('.'))}</td>"
        f"<td class=\"num\">{_money(p['avg_entry_price'], cents=True)}</td>"
        f"<td class=\"num\">{_money(p['current_price'], cents=True)}</td>"
        f"<td class=\"num\">{_money(p['market_value'], cents=True)}</td>{_gain_cell(p)}{position_ratings.rating_cell(p['symbol'])}{_sell_cell(p)}</tr>"
        for p in positions
    )
    return (
        '<table><thead><tr><th>Symbol</th><th class="num">Shares</th><th class="num">Avg cost</th><th class="num">Price</th>'
        f'<th class="num">Value</th><th class="num">Gain / loss</th><th>Rating</th><th></th></tr></thead><tbody>{rows}</tbody></table>'
    )


def _orders_html(orders: list[dict], mode: str) -> str:
    if not orders:
        return '<p class="muted">No orders yet.</p>'
    rows = []
    for o in orders:
        is_open = o["status"] in _OPEN_STATUSES
        price = (
            _money(o["filled_avg_price"], cents=True) if o["filled_avg_price"]
            else (f"limit {_money(o['limit_price'], cents=True)}" if o["limit_price"] else "market")
        )
        action = (
            f'<button type="button" data-order-id="{html.escape(o["id"])}" onclick="cancelOrder(this.dataset.orderId)">Cancel</button>'
            if is_open else ""
        )
        rows.append(
            f"<tr><td>{html.escape(o['submitted_at'][:16].replace('T', ' '))}</td>"
            f"<td>{html.escape(o['side'])}</td><td><strong>{html.escape(o['symbol'])}</strong></td>"
            f"<td class=\"num\">{_num(o['qty'], 0)}</td><td>{html.escape(price)}</td>"
            f"<td>{html.escape(o['status'].replace('_', ' '))}</td><td>{action}</td></tr>"
        )
    return (
        '<table><thead><tr><th>Placed</th><th>Side</th><th>Symbol</th><th class="num">Shares</th><th>Price</th>'
        f'<th>Status</th><th></th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


def _live_controls_html() -> str:
    """The live-trading switch, its limits, and today's usage."""
    lt = db.live_trading
    until = lt.armed_until()
    spent, daily, per_order = lt.spent_today(), lt.daily_limit(), lt.per_order_limit()
    per_text = _money(per_order) if lt.is_limited(per_order) else "no limit"
    daily_text = _money(daily) if lt.is_limited(daily) else "no limit"
    if until is not None:
        if lt.is_persistent():
            how = "LIVE TRADING IS ON until you turn it off."
        else:
            when = datetime.fromtimestamp(until).strftime("%I:%M %p").lstrip("0")
            how = f"LIVE TRADING IS ON until about {html.escape(when)} (it switches itself off)."
        state = f"""
<p class="status-line" style="color:#c94a4a; font-weight:700;">{how}</p>
<p><button type="button" class="primary" style="background:#c94a4a;" onclick="postJSON('/api/alpaca/live/disarm', {{}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">Turn live trading OFF now</button></p>"""
    else:
        state = f"""
<p class="status-line">Live trading is <strong>off</strong>. You can look at your account, but no real-money order can be previewed or sent.</p>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/alpaca/live/arm', {{phrase: this.phrase.value, stay_on: this.stay.checked}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>To turn it on, type <strong>{html.escape(lt.CONFIRM_PHRASE)}</strong>
    <input name="phrase" autocomplete="off" style="width:200px" required></label>
  <label style="flex-direction:row; align-items:center; gap:6px;"><input name="stay" type="checkbox" checked style="width:auto"> Keep it on until I turn it off (otherwise it switches off after {lt.ARM_HOURS} hours)</label>
  <button type="submit">Turn live trading on</button>
</form>"""
    return f"""
<div class="card" style="border:2px solid #c94a4a;">
<h3 style="margin-top:0; color:#c94a4a;">Live trading switch</h3>
{state}
<p class="muted" style="margin-bottom:0;">Sent from this app today (all brokers): <strong>{_money(spent, cents=True)}</strong>.
Limits: {per_text} per order, {daily_text} per day. <a href="/setup.html#live-limits">Change the limits in Setup</a>.</p>
</div>
"""


def _log_status(row: dict, order: dict | None) -> str:
    status = row["status"]
    if order and order.get("filled_qty") and order.get("filled_avg_price") and status in ("filled", "partially_filled"):
        return f"{status.replace('_', ' ')}: {order['filled_qty']:g} at {_money(order['filled_avg_price'], cents=True)}"
    return status.replace("_", " ")


def _live_log_html(orders: list[dict] | None = None) -> str:
    """The real-money orders this app sent. Their status is refreshed from Alpaca's order list first
    (an order is saved as "pending_new" when sent and fills afterwards); a filled order shows its fill."""
    if orders:
        db.live_trading.sync_statuses(orders)
    by_id = {o["id"]: o for o in orders or []}
    rows = db.live_trading.list_live_orders(15, broker="alpaca")
    if not rows:
        return '<p class="muted">No real-money orders have been sent from this app yet.</p>'
    body = "".join(
        f"<tr><td>{html.escape(r['placed_at'].replace('T', ' '))}</td><td>{html.escape(r['side'])}</td>"
        f"<td><strong>{html.escape(r['symbol'])}</strong></td><td class=\"num\">{r['qty']}</td>"
        f"<td>{html.escape(r['order_type'])}</td><td class=\"num\">{_money(r['estimate'], cents=True)}</td>"
        f"<td>{html.escape(_log_status(r, by_id.get(r['order_id'])))}</td></tr>"
        for r in rows
    )
    return (
        '<table><thead><tr><th>Sent</th><th>Side</th><th>Symbol</th><th class="num">Shares</th><th>Type</th>'
        f'<th class="num">About</th><th>Status</th></tr></thead><tbody>{body}</tbody></table>'
    )


_TICKET_FORM = """
<form id="ticket" class="inline" onsubmit="event.preventDefault(); previewOrder(this);">
  <label>Buy or sell<select name="side"><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
  <label>Symbol<input name="symbol" autocomplete="off" style="width:90px; text-transform:uppercase;" oninput="priceSoon(this.value)" required></label>
  <label>Shares<input name="qty" type="number" min="1" step="1" style="width:90px" required></label>
  <label>Type<select name="type" onchange="this.form.limit_price.disabled = this.value !== 'limit';"><option value="market">Market (current price)</option><option value="limit">Limit (my price)</option></select></label>
  <label>Limit price<input name="limit_price" type="number" min="0.01" step="0.01" style="width:100px" disabled></label>
  <label>Stays open<select name="time_in_force"><option value="day">Today only</option><option value="gtc">Until cancelled</option></select></label>
  <label>Session<select name="session" onchange="sessionChanged(this.form)"><option value="regular">Regular hours (9:30 AM &ndash; 4 PM ET)</option><option value="extended">Extended hours: pre-market, after-hours and overnight</option></select></label>
  <button type="submit" class="primary">Preview order</button>
</form>
<p id="ticket-note" class="muted small" style="margin:8px 0 0;"></p>
<p id="session-note" class="muted small" style="margin:4px 0 0;" hidden>Extended-hours orders must be limit orders and last for the day. Pre-market 4:00&ndash;9:30 AM, after-hours 4:00&ndash;8:00 PM, overnight 8:00 PM&ndash;4:00 AM ET (only stocks Alpaca lists as overnight-tradable). Fewer people trade then, so prices can jump and spreads are wide: set a limit price you are happy with.</p>
<div id="ticket-price" class="status-line" style="margin-top:10px;"><span class="muted">Type a symbol to see its current price.</span></div>
<div id="ticket-preview" style="margin-top:10px;"></div>
"""

_TICKET_JS = """
<style>
.trade-btn { cursor:pointer; padding:3px 12px; border-radius:999px; font-size:12px; font-weight:700; border:1px solid var(--brand); background:transparent; color:var(--brand); white-space:nowrap; }
.trade-btn:hover, .trade-btn.open { background:var(--brand-soft); }
#trade-menu { position:fixed; z-index:60; min-width:170px; padding:6px; border:1px solid var(--border); border-radius:10px; background:var(--surface); box-shadow:0 12px 28px rgba(0,0,0,.25); display:none; flex-direction:column; font-size:13px; }
#trade-menu button { text-align:left; border:0; background:transparent; padding:7px 10px; border-radius:6px; font-weight:600; cursor:pointer; }
#trade-menu button:hover { background:var(--brand-soft); }
.tk-check { margin:6px 0 0; padding:6px 10px; border-radius:8px; border:1px solid var(--border); font-size:13px; }
.tk-check.warn { border-color:var(--warn); font-weight:600; }
#trade-menu .tm-buy { color:var(--success); } #trade-menu .tm-sell { color:var(--danger); }
</style>
<script>
var TRADE_MODE = '__MODE__';
var pendingToken = null;
(function () {
  var sym = new URLSearchParams(location.search).get('symbol'), side = (new URLSearchParams(location.search).get('side') || '').toLowerCase(), f = document.getElementById('ticket');
  if (sym && f) { f.symbol.value = sym.toUpperCase(); if (side === 'buy' || side === 'sell') { f.side.value = side; } f.scrollIntoView({behavior: 'smooth', block: 'center'}); f.qty.focus(); }
})();
function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
var priceTimer = null, priceSym = '';
function priceSoon(v) { clearTimeout(priceTimer); priceTimer = setTimeout(function () { loadPrice(v); }, 500); }
function setLimit(p) {
  var f = document.getElementById('ticket'); if (!f) { return; }
  f.type.value = 'limit'; f.limit_price.disabled = false; f.limit_price.value = Number(p).toFixed(2);
}
function setMarket() { var f = document.getElementById('ticket'); if (f) { f.session.value = 'regular'; sessionChanged(f); f.type.value = 'market'; f.limit_price.disabled = true; f.limit_price.value = ''; } }
function loadPrice(v) {
  var box = document.getElementById('ticket-price'); if (!box) { return; }
  var sym = String(v || '').trim().toUpperCase();
  if (!/^[A-Z]{1,5}(\\.[A-Z])?$/.test(sym)) { priceSym = ''; box.innerHTML = '<span class="muted">Type a symbol to see its current price.</span>'; return; }
  var fresh = sym !== priceSym; priceSym = sym;
  if (fresh) { box.innerHTML = '<span class="muted">Looking up ' + esc(sym) + '&hellip;</span>'; }
  postJSON('/api/alpaca/price', {mode: TRADE_MODE, symbol: sym}).then(function (d) {
    if (d.symbol !== priceSym) { return; }
    var usd = function (n) { return n == null ? '--' : '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}); };
    var up = (d.change || 0) >= 0, when = d.as_of ? new Date(d.as_of) : null;
    var x = d.extended, xup = x && (x.change || 0) >= 0;
    var h = '<strong>' + esc(d.symbol) + '</strong> <span style="font-size:20px; font-weight:700;">' + usd(d.price) + '</span> ' +
      (d.change == null ? '' : '<span style="color:' + (up ? '#1baf7a' : '#c94a4a') + '; font-weight:600;">' + (up ? '\u25B2 +' : '\u25BC -') + Math.abs(d.change).toFixed(2) +
        ' (' + (up ? '+' : '-') + Math.abs(d.change_pct).toFixed(2) + '%) today</span> ') +
      '<span class="muted">Bid ' + usd(d.bid) + ' / Ask ' + usd(d.ask) + (when && !isNaN(when) ? ' &middot; last trade ' + when.toLocaleString([], {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) : '') + '</span>' +
      (x ? '<div style="margin-top:4px;"><strong>' + esc(x.label) + '</strong> ' + usd(x.price) + (x.change == null ? '' : ' <span style="color:' + (xup ? '#1baf7a' : '#c94a4a') + '; font-weight:600;">' + (xup ? '+' : '-') + Math.abs(x.change).toFixed(2) + (x.change_pct == null ? '' : ' (' + (xup ? '+' : '-') + Math.abs(x.change_pct).toFixed(2) + '%)') + '</span>') + ' <span class="muted small">(Yahoo Finance; the order form below can send an extended-hours limit order)</span></div>' : '') +
      '<div style="margin-top:6px;"><span class="muted">Choose: </span>' +
      '<button type="button" onclick="setMarket()">Market (fills at about ' + usd(d.price) + ')</button> ' +
      '<button type="button" onclick="setLimit(' + d.price + ')">Limit at ' + usd(d.price) + '</button>' +
      (d.bid ? ' <button type="button" onclick="setLimit(' + d.bid + ')">Limit at bid ' + usd(d.bid) + '</button>' : '') +
      (d.ask ? ' <button type="button" onclick="setLimit(' + d.ask + ')">Limit at ask ' + usd(d.ask) + '</button>' : '') + '</div>' +
      '<div class="muted small" style="margin-top:4px;">' + (d.data_source === 'yahoo' ? 'This price is from Yahoo Finance (Alpaca prices were not available) and can lag' : 'Free IEX prices can lag the full market') + ', so check the price before sending a real order. Refreshes every 20 seconds.</div>';
    box.innerHTML = h;
  }).catch(function (e) { if (sym === priceSym) { box.innerHTML = '<span class="status-warn">' + esc(e.message) + '</span>'; } });
}
setInterval(function () { if (priceSym && !document.hidden) { loadPrice(priceSym); } }, 20000);
document.addEventListener('DOMContentLoaded', function () { var f = document.getElementById('ticket'); if (f && f.symbol.value) { loadPrice(f.symbol.value); } });
function sessionChanged(form) {
  var ext = form.session.value !== 'regular';
  if (ext) { form.type.value = 'limit'; form.time_in_force.value = 'day'; }
  form.type.querySelector('option[value=market]').disabled = ext;
  form.time_in_force.disabled = ext;
  form.limit_price.disabled = form.type.value !== 'limit';
  document.getElementById('session-note').hidden = !ext;
}
function previewOrder(form) {
  var box = document.getElementById('ticket-preview');
  pendingToken = null;
  var body = {mode: TRADE_MODE, side: form.side.value, symbol: form.symbol.value, qty: form.qty.value, type: form.type.value,
              limit_price: form.limit_price.value, time_in_force: form.time_in_force.value, session: form.session.value};
  postJSON('/api/alpaca/preview', body).then(function (r) {
    pendingToken = r.token;
    var o = r.order, live = TRADE_MODE === 'live';
    var summary = '<strong>' + esc(o.side.toUpperCase()) + ' ' + o.qty + ' ' + esc(o.symbol) + '</strong> as a ' +
      esc(o.type) + ' order' + (o.limit_price ? ' at $' + o.limit_price.toFixed(2) : '') + (o.session && o.session !== 'regular' ? ' <strong>for extended hours</strong>' : '') + ', about <strong>$' +
      r.estimate.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '</strong> (at about $' + r.price.toFixed(2) + ' a share).';
    if (r.pct_of_account != null) { summary += ' That is ' + (r.pct_of_account * 100 >= 10 ? Math.round(r.pct_of_account * 100) : (r.pct_of_account * 100).toFixed(1)) + '% of this account.'; }
    var checks = (r.checks || []).map(function (c) {
      return '<div class="tk-check ' + esc(c.level) + '">' + (c.level === 'warn' ? '&#9888; ' : '&#9432; ') + esc(c.text) + '</div>';
    }).join('');
    if (live) {
      box.innerHTML = '<div class="status-line" style="border:2px solid #c94a4a; padding:10px; border-radius:10px;">' +
        '<div style="color:#c94a4a; font-weight:700;">REAL MONEY</div>' + summary + checks +
        '<div style="margin-top:8px;"><label>Type the symbol (<strong>' + esc(o.symbol) + '</strong>) to confirm ' +
        '<input id="confirm-symbol" autocomplete="off" style="width:90px; text-transform:uppercase;"></label></div></div>' +
        '<button type="button" class="primary" style="background:#c94a4a;" onclick="confirmOrder()">Send REAL order</button> ' +
        '<button type="button" onclick="clearPreview()">Cancel</button>';
    } else {
      box.innerHTML = '<div class="status-line">' + summary + ' Practice account, no real money.' + checks + '</div>' +
        '<button type="button" class="primary" onclick="confirmOrder()">Place practice order</button> ' +
        '<button type="button" onclick="clearPreview()">Cancel</button>';
    }
  }).catch(function (e) { box.innerHTML = '<p class="status-line status-warn">' + esc(e.message) + '</p>'; });
}
// The Sell button beside a position: fill the order form with a sale of that stock (all the whole shares
// held -- change the number to sell fewer), market type by default; the person picks Market or Limit and previews.
// One Trade button per position: a small menu with Buy more and Sell (fixed-position so the table cannot clip it).
var tradeMenuBox = null;
function closeTradeMenu() { if (tradeMenuBox) { tradeMenuBox.style.display = 'none'; } Array.prototype.forEach.call(document.querySelectorAll('.trade-btn.open'), function (b) { b.classList.remove('open'); }); }
function placeTradeMenu(btn) {
  var r = btn.getBoundingClientRect(), w = tradeMenuBox.offsetWidth, h = tradeMenuBox.offsetHeight;
  tradeMenuBox.style.left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8)) + 'px';
  tradeMenuBox.style.top = (r.bottom + h + 8 > window.innerHeight && r.top > h + 8 ? r.top - h - 4 : r.bottom + 4) + 'px';
}
function tradeMenu(btn) {
  var was = btn.classList.contains('open'); closeTradeMenu(); if (was) { return; }
  if (!tradeMenuBox) {
    tradeMenuBox = document.createElement('div'); tradeMenuBox.id = 'trade-menu'; document.body.appendChild(tradeMenuBox);
    document.addEventListener('click', function (ev) { if (!(ev.target.closest && (ev.target.closest('.trade-btn') || ev.target.closest('#trade-menu')))) { closeTradeMenu(); } });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { closeTradeMenu(); } });
    window.addEventListener('scroll', function () { var b = document.querySelector('.trade-btn.open'); if (b) { placeTradeMenu(b); } }, true);
  }
  var sym = btn.getAttribute('data-sym'), qty = Number(btn.getAttribute('data-qty') || 0);
  tradeMenuBox.innerHTML = '<button type="button" class="tm-buy" onclick="closeTradeMenu(); buyPosition(\\'' + sym + '\\')">Buy ' + esc(sym) + '</button>' +
    (qty >= 1 ? '<button type="button" class="tm-sell" onclick="closeTradeMenu(); sellPosition(\\'' + sym + '\\', ' + qty + ')">Sell ' + qty + ' (all)</button>' : '<span class="muted small" style="padding:6px 10px;">No whole shares to sell</span>');
  tradeMenuBox.style.display = 'flex'; btn.classList.add('open');
  placeTradeMenu(btn);
}
function buyPosition(sym) {
  var f = document.getElementById('ticket');
  if (!f) {
    var h = document.getElementById('ticket-hint');
    if (h) { h.style.display = ''; h.textContent = 'To buy ' + sym + ', turn live trading on above; this page then opens the order form with it filled in.'; h.scrollIntoView({behavior: 'smooth', block: 'center'}); }
    return;
  }
  f.side.value = 'buy'; f.symbol.value = sym; f.qty.value = 1; setMarket();
  var note = document.getElementById('ticket-note');
  if (note) { note.textContent = 'Buying ' + sym + ': set to 1 share. Change the number, then choose Market or a Limit price (buy only at that price or lower) and press Preview.'; }
  f.scrollIntoView({behavior: 'smooth', block: 'center'}); loadPrice(sym); f.qty.focus();
}
function sellPosition(sym, held) {
  var f = document.getElementById('ticket');
  if (!f) {
    var h = document.getElementById('ticket-hint');
    if (h) { h.style.display = ''; h.textContent = 'To sell ' + sym + ', turn live trading on above; this page then opens the order form with the sale filled in.'; h.scrollIntoView({behavior: 'smooth', block: 'center'}); }
    return;
  }
  var whole = Math.max(1, Math.floor(held));
  f.side.value = 'sell'; f.symbol.value = sym; f.qty.value = whole; setMarket();
  var note = document.getElementById('ticket-note');
  if (note) {
    note.textContent = 'Selling ' + sym + ': set to ' + whole + (whole === 1 ? ' share' : ' shares') + ' (you hold ' + held + '). Change the number to sell fewer, ' +
      'then choose Market (sell at the current price) or a Limit price (sell only at that price or better), and press Preview.' +
      (held !== whole ? ' The form takes whole shares only, so a fraction of a share stays.' : '');
  }
  f.scrollIntoView({behavior: 'smooth', block: 'center'}); loadPrice(sym); f.qty.focus();
}
function clearPreview() { pendingToken = null; document.getElementById('ticket-preview').innerHTML = ''; }
function confirmOrder() {
  if (!pendingToken) { return; }
  var box = document.getElementById('ticket-preview');
  var sym = document.getElementById('confirm-symbol');
  var body = {mode: TRADE_MODE, token: pendingToken};
  if (sym) { body.confirm_symbol = sym.value; }
  postJSON('/api/alpaca/order', body).then(function () { pendingToken = null; location.reload(); })
    .catch(function (e) { box.insertAdjacentHTML('beforeend', '<p class="status-line status-warn">' + esc(e.message) + '</p>'); });
}
function cancelOrder(id) {
  postJSON('/api/alpaca/cancel', {mode: TRADE_MODE, id: id}).then(function () { location.reload(); }).catch(function (e) { alert(e.message); });
}
</script>
"""


def _ticket_html(mode: str, *, armed: bool) -> str:
    limit_text = f"${alpaca.MAX_ORDER_NOTIONAL:,.0f}"
    js = _TICKET_JS.replace("__MODE__", mode)
    if mode == "live":
        if not armed:
            return (
                '<div class="card"><h3 style="margin-top:0;">Place a real-money order</h3>'
                '<p class="muted">Turn live trading on above to place an order.</p><p id="ticket-hint" class="status-line status-warn" style="display:none;"></p></div>' + js
                + "<script>(function () { var sym = new URLSearchParams(location.search).get('symbol'), h = document.getElementById('ticket-hint');"
                " if (sym && h) { h.style.display = ''; h.textContent = 'You came here to trade ' + sym.toUpperCase().replace(/[^A-Z.]/g, '') + '. Turn live trading on above and this page will open the order form with it filled in.'; } })();</script>"
            )
        return (
            '<div class="card" style="border:2px solid #c94a4a;"><h3 style="margin-top:0; color:#c94a4a;">Place a real-money order</h3>'
            '<p class="muted">Step 1: fill in the order and press Preview. Step 2: read the summary, type the symbol again and send. '
            f'Your per-order and daily limits above apply, and no order can be worth more than {limit_text}.</p>'
            + _TICKET_FORM + "</div>" + js
        )
    return (
        '<div class="card"><h3 style="margin-top:0;">Place a practice order</h3>'
        '<p class="muted">Step 1: fill in the order and press Preview. Step 2: read the summary and confirm. Orders are practice orders only '
        f'and are limited to {limit_text} each.</p>' + _TICKET_FORM + "</div>" + js
    )


def _stale_note_html(view: dict) -> str:
    """Shown when the page is built from a kept copy. With no error, the copy is being refreshed in the background, so the
    page reloads itself once (at most once a minute) to pick the new numbers up."""
    when = datetime.fromtimestamp(view["at"]).strftime("%-I:%M:%S %p")
    if view["error"]:
        return (f'<p class="status-line status-warn">Alpaca could not be reached ({html.escape(view["error"])}). '
                f'Showing what was loaded at {when}.</p>')
    return (f'<p class="muted small" id="stale-note">Showing what was loaded at {when} &mdash; refreshing&hellip;</p>'
            "<script>setTimeout(function () { try { var k = 'finsi.alpaca.reload', t = +sessionStorage.getItem(k) || 0;"
            " if (Date.now() - t > 60000) { sessionStorage.setItem(k, Date.now()); location.reload(); } } catch (e) {} }, 3000);</script>")


def _render_trading_page(mode: str = "paper") -> str:
    live = mode == "live"
    page = "trading-live.html" if live else "trading.html"   # the section row above the page lists both
    title = "Trading (live account)" if live else "Trading (practice account)"
    intro = f'<h2 style="margin-top:0">{title}</h2>'
    if live:
        intro += (
            '<p class="status-line" style="color:#c94a4a; font-weight:700;">REAL MONEY. Orders sent from this page buy and sell real investments '
            'in your Alpaca brokerage account. This app does not give investment advice and never places an order by itself.</p>'
            '<p class="muted">These balances are not added to your net worth or plan here. (Link the account with Plaid if you want it counted.)</p>'
        )
    else:
        intro += (
            '<p class="muted"><strong>Practice only.</strong> This page uses an Alpaca <em>paper</em> account: real market prices, play money. '
            'No real money can be spent here, and these balances are not counted in your net worth or your retirement plan.</p>'
        )
    if not secrets_store.has_alpaca_keys(mode=mode):
        return _shell(title="Trading", active=page, body=intro + _connect_card_html(mode))
    problem = ""
    acct, positions, orders = None, [], []
    try:
        keys = secrets_store.get_alpaca_keys(mode=mode)
        view = alpaca_view.get(keys, mode)
        acct, positions, orders = view["account"], view["positions"], view["orders"]
        if view["stale"]:
            problem = _stale_note_html(view)
    except (alpaca.AlpacaError, secrets_store.SecretNotFoundError) as exc:
        problem = f'<p class="status-line status-warn">{html.escape(str(exc))}</p>'
    body = intro + problem
    if live:
        body += _live_controls_html()
    if acct is not None:
        body += _account_card_html(acct, mode)
        body += f"<h3>Positions</h3>{_positions_html(positions)}"
        if positions:
            body += position_ratings.block()
        body += (
            '<p class="muted">Want to research a stock first? <a href="/stock-analysis.html">Stock Analysis</a> has quotes, '
            'charts, a buy / sell rating and your watchlist.</p>'
        )
        body += _ticket_html(mode, armed=db.live_trading.is_armed() if live else True)
        body += f"<h3>Recent orders at Alpaca</h3>{_orders_html(orders, mode)}"
    else:
        # The saved keys did not work (or Alpaca could not be reached): offer the key form right here, so there is no need to
        # remove them first. A wrong pair is refused before it is saved, so the old keys stay until a good pair replaces them.
        body += _connect_card_html(mode, again=True)
        body += (
            f'<p><button type="button" onclick="{html.escape(_disconnect_js(mode))}">Remove saved keys</button></p>'
        )
    if live:
        body += f"<h3>Real-money orders sent from this app</h3>{_live_log_html(orders)}"
    return _shell(title="Trading", active=page, body=body)
