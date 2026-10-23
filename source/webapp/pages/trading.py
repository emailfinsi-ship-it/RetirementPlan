"""The Trading tab: an Alpaca PAPER (practice) account -- balances, positions and
orders, plus a preview-then-confirm order ticket. Paper only (see
source.collector.alpaca): no real money can move here, and the practice
balances are never counted in net worth or the retirement plan."""

from __future__ import annotations

import html

from source.collector import alpaca
from source.common import secrets_store
from source.webapp.render_helpers import _money, _shell

_OPEN_STATUSES = {"new", "accepted", "pending_new", "partially_filled", "held", "accepted_for_bidding", "pending_replace"}


def _num(value, places: int = 2) -> str:
    return "--" if value is None else f"{value:,.{places}f}"


def _signed_money(value) -> str:
    if value is None:
        return "--"
    return f"{'+' if value >= 0 else '-'}{_money(abs(value), cents=True)}"


def _connect_card_html() -> str:
    return """
<div class="card">
<h3 style="margin-top:0;">Connect your Alpaca practice account</h3>
<p class="muted">Alpaca offers a free <strong>paper trading</strong> account: play money, real market prices. In your Alpaca
dashboard switch to <em>Paper</em>, open <em>API Keys</em>, generate a key, and paste both parts here. They are stored in the
macOS Keychain with your other credentials, never in the database. Live (real-money) keys are not supported.</p>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/alpaca-keys', {key_id: this.key_id.value, secret: this.secret.value})
    .then(function() { location.reload(); }).catch(function(e) { alert(e.message); });">
  <label>Key ID<input name="key_id" autocomplete="off" style="width:220px" required></label>
  <label>Secret<input name="secret" type="password" autocomplete="off" style="width:260px" required></label>
  <button type="submit" class="primary">Connect</button>
</form>
</div>
"""


_DISCONNECT_JS = (
    "if (confirm('Remove the saved Alpaca keys from this computer?')) "
    "postJSON('/api/alpaca-keys/delete', {}).then(function() { location.reload(); }).catch(function(e) { alert(e.message); });"
)


def _account_card_html(acct: dict) -> str:
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
  <div class="tile"><div class="label">Practice account value</div><div class="value">{_money(acct["equity"], cents=True)}</div></div>
  <div class="tile"><div class="label">Cash</div><div class="value">{_money(acct["cash"], cents=True)}</div></div>
  <div class="tile"><div class="label">Buying power</div><div class="value">{_money(acct["buying_power"], cents=True)}</div></div>
  <div class="tile"><div class="label">Change since yesterday</div><div class="value">{_signed_money(change)}</div></div>
</div>
{blocked}
<p class="muted" style="margin-bottom:0;">Account {html.escape(acct["account_number"] or "--")} ({html.escape(acct["status"] or "unknown")}).
<button type="button" onclick="{html.escape(_DISCONNECT_JS)}">Disconnect</button></p>
</div>
"""


def _gain_cell(p: dict) -> str:
    pl = p["unrealized_pl"]
    pct = "" if p["unrealized_plpc"] is None else f" ({p['unrealized_plpc'] * 100:+.1f}%)"
    color = "#1baf7a" if (pl or 0) >= 0 else "#c94a4a"
    return f'<td class="num" style="color:{color};">{_signed_money(pl)}{pct}</td>'


def _positions_html(positions: list[dict]) -> str:
    if not positions:
        return '<p class="muted">No positions yet. Place a practice order below to see it here.</p>'
    rows = "".join(
        f"<tr><td><strong>{html.escape(p['symbol'])}</strong></td>"
        f"<td class=\"num\">{html.escape(_num(p['qty'], 4).rstrip('0').rstrip('.'))}</td>"
        f"<td class=\"num\">{_money(p['avg_entry_price'], cents=True)}</td>"
        f"<td class=\"num\">{_money(p['current_price'], cents=True)}</td>"
        f"<td class=\"num\">{_money(p['market_value'], cents=True)}</td>{_gain_cell(p)}</tr>"
        for p in positions
    )
    return (
        '<table><thead><tr><th>Symbol</th><th class="num">Shares</th><th class="num">Avg cost</th><th class="num">Price</th>'
        f'<th class="num">Value</th><th class="num">Gain / loss</th></tr></thead><tbody>{rows}</tbody></table>'
    )


def _orders_html(orders: list[dict]) -> str:
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


_TICKET_HTML = """
<div class="card">
<h3 style="margin-top:0;">Place a practice order</h3>
<p class="muted">Step 1: fill in the order and press Preview. Step 2: read the summary and confirm. Orders are practice orders only
and are limited to $__LIMIT__ each.</p>
<form id="ticket" class="inline" onsubmit="event.preventDefault(); previewOrder(this);">
  <label>Buy or sell<select name="side"><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
  <label>Symbol<input name="symbol" autocomplete="off" style="width:90px; text-transform:uppercase;" required></label>
  <label>Shares<input name="qty" type="number" min="1" step="1" style="width:90px" required></label>
  <label>Type<select name="type" onchange="this.form.limit_price.disabled = this.value !== 'limit';"><option value="market">Market (current price)</option><option value="limit">Limit (my price)</option></select></label>
  <label>Limit price<input name="limit_price" type="number" min="0.01" step="0.01" style="width:100px" disabled></label>
  <label>Stays open<select name="time_in_force"><option value="day">Today only</option><option value="gtc">Until cancelled</option></select></label>
  <button type="submit" class="primary">Preview order</button>
</form>
<div id="ticket-preview" style="margin-top:10px;"></div>
</div>
<script>
var pendingToken = null;
function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
function previewOrder(form) {
  var box = document.getElementById('ticket-preview');
  pendingToken = null;
  var body = {side: form.side.value, symbol: form.symbol.value, qty: form.qty.value, type: form.type.value,
              limit_price: form.limit_price.value, time_in_force: form.time_in_force.value};
  postJSON('/api/alpaca/preview', body).then(function (r) {
    pendingToken = r.token;
    var o = r.order;
    box.innerHTML = '<div class="status-line"><strong>' + esc(o.side.toUpperCase()) + ' ' + o.qty + ' ' + esc(o.symbol) + '</strong> as a ' +
      esc(o.type) + ' order' + (o.limit_price ? ' at $' + o.limit_price.toFixed(2) : '') + ', about <strong>$' +
      r.estimate.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '</strong> (at about $' + r.price.toFixed(2) +
      ' a share). Practice account, no real money.</div>' +
      '<button type="button" class="primary" onclick="confirmOrder()">Place practice order</button> ' +
      '<button type="button" onclick="clearPreview()">Cancel</button>';
  }).catch(function (e) { box.innerHTML = '<p class="status-line status-warn">' + esc(e.message) + '</p>'; });
}
function clearPreview() { pendingToken = null; document.getElementById('ticket-preview').innerHTML = ''; }
function confirmOrder() {
  if (!pendingToken) { return; }
  var token = pendingToken;
  pendingToken = null;
  postJSON('/api/alpaca/order', {token: token}).then(function () { location.reload(); })
    .catch(function (e) { document.getElementById('ticket-preview').innerHTML = '<p class="status-line status-warn">' + esc(e.message) + '</p>'; });
}
function cancelOrder(id) {
  postJSON('/api/alpaca/cancel', {id: id}).then(function () { location.reload(); }).catch(function (e) { alert(e.message); });
}
</script>
""".replace("__LIMIT__", f"{alpaca.MAX_ORDER_NOTIONAL:,.0f}")


def _render_trading_page() -> str:
    intro = (
        '<h2 style="margin-top:0">Trading (practice account)</h2>'
        '<p class="muted"><strong>Practice only.</strong> This tab uses an Alpaca <em>paper</em> account: real market prices, play money. '
        'No real money can be spent here, and these balances are not counted in your net worth or your retirement plan.</p>'
    )
    if not secrets_store.has_alpaca_keys():
        return _shell(title="Trading", active="trading.html", body=intro + _connect_card_html())
    problem = ""
    acct, positions, orders = None, [], []
    try:
        keys = secrets_store.get_alpaca_keys()
        acct = alpaca.get_account(keys)
        positions = alpaca.list_positions(keys)
        orders = alpaca.list_orders(keys)
    except (alpaca.AlpacaError, secrets_store.SecretNotFoundError) as exc:
        problem = f'<p class="status-line status-warn">{html.escape(str(exc))}</p>'
    body = intro + problem
    if acct is not None:
        body += _account_card_html(acct)
        body += f"<h3>Positions</h3>{_positions_html(positions)}"
        body += _TICKET_HTML
        body += f"<h3>Recent orders</h3>{_orders_html(orders)}"
    else:
        body += (
            f'<p><button type="button" onclick="{html.escape(_DISCONNECT_JS)}">Remove saved keys</button></p>'
        )
    return _shell(title="Trading", active="trading.html", body=body)
