"""Writes this program's own account_balances.csv/.html and
portfolio_positions.csv/.html -- the "and html" half of the direct Plaid
integration: after every sync (source.collector.sync), a portable
snapshot lands in the output folder, same column names and same
sortable-table styling as FamilyFinanceTracker's own exports (so anyone
who's used that app recognizes these immediately), but generated purely
from this program's own plaid_accounts/plaid_holdings tables -- no
dependency on FamilyFinanceTracker's files.
"""

from __future__ import annotations

import csv
import html

from source.common import branding, config, db

ACCOUNT_CSV_COLUMNS = ("Financial Institution", "Last 4 Digits", "Balance", "Last Update", "Account Type")
POSITION_CSV_COLUMNS = (
    "Financial Institution", "Account", "Security Name", "Ticker", "Security Type",
    "Quantity", "Price", "Market Value", "Cost Basis", "Currency",
)

# Plaid's own account `type` for anything you owe rather than hold --
# credit cards and every kind of loan. Plaid reports current_balance for
# these as a plain positive "amount owed", so summing naively overstates
# net worth; sign debts negative here, same convention as
# FamilyFinanceTracker's export_account_csv.py.
_LIABILITY_TYPES = {"credit", "loan"}


def _is_liability_type(typ) -> bool:
    return str(typ or "").strip().lower() in _LIABILITY_TYPES


def _account_type_label(typ, subtype) -> str:
    sub = str(subtype or "").strip().lower()
    if sub:
        return sub.replace("_", " ").title()
    raw = str(typ or "").strip().lower()
    return raw.title() if raw else ""


SORT_SCRIPT = """<script>
function initSortableTables() {
  document.querySelectorAll('table').forEach(function(table) {
    var headRow = table.querySelector('thead tr');
    if (!headRow) return;
    var ths = headRow.querySelectorAll('th');
    ths.forEach(function(th, idx) {
      th.style.cursor = 'pointer';
      var indicator = document.createElement('span');
      indicator.className = 'sort-indicator';
      indicator.style.marginLeft = '4px';
      indicator.style.fontSize = '10px';
      th.appendChild(indicator);
      th.addEventListener('click', function() { sortTableByColumn(table, idx); });
    });
  });
}
function cellSortValue(td) {
  var text = td.textContent.trim();
  var cleaned = text.replace(/[$,%]/g, '');
  if (cleaned !== '' && cleaned !== '-' && /^-?[0-9.]+$/.test(cleaned)) {
    return { num: parseFloat(cleaned), text: text.toLowerCase() };
  }
  return { num: null, text: text.toLowerCase() };
}
function sortTableByColumn(table, colIdx) {
  var tbody = table.tBodies[0];
  if (!tbody) return;
  var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
  if (rows.length < 2) return;
  var ths = table.querySelectorAll('thead th');
  var th = ths[colIdx];
  var nextDir = th.getAttribute('data-sort-dir') === 'asc' ? 'desc' : 'asc';
  ths.forEach(function(h) { h.removeAttribute('data-sort-dir'); var i = h.querySelector('.sort-indicator'); if (i) i.textContent = ''; });
  th.setAttribute('data-sort-dir', nextDir);
  var indicator = th.querySelector('.sort-indicator');
  if (indicator) indicator.textContent = nextDir === 'asc' ? '▲' : '▼';
  var mult = nextDir === 'asc' ? 1 : -1;
  rows.sort(function(r1, r2) {
    var c1 = cellSortValue(r1.children[colIdx]);
    var c2 = cellSortValue(r2.children[colIdx]);
    if (c1.num !== null && c2.num !== null) return (c1.num - c2.num) * mult;
    return c1.text.localeCompare(c2.text) * mult;
  });
  rows.forEach(function(r) { tbody.appendChild(r); });
}
initSortableTables();
</script>"""

_HTML_PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 32px auto; padding: 0 16px; color: #1a1a1a; }}
  h1 {{ font-size: 18px; margin-bottom: 4px; }}
  .muted {{ color: #777; font-size: 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 16px; }}
  th, td {{ text-align: left; padding: 7px 8px; border-bottom: 1px solid #e5e5e5; }}
  th {{ background: #fafafa; }}
  th:hover {{ background: #eee; }}
  td.num, th.num {{ text-align: right; }}
  tfoot td {{ font-weight: 600; border-top: 2px solid #ccc; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="muted">Generated {generated_at} by {product_name}'s own Plaid sync. Same data as {csv_name} in this folder. Click a column header to sort.</p>
<table>
  <thead><tr>{header_cells}</tr></thead>
  <tbody>
{rows}
  </tbody>
  <tfoot><tr>{footer_cells}</tr></tfoot>
</table>
{sort_script}
</body>
</html>
"""


def _format_money(value) -> str:
    if value is None or value == "":
        return ""
    amount = float(value)
    return f"-${-amount:,.2f}" if amount < 0 else f"${amount:,.2f}"


def account_balance_records(*, downloaded_at: str) -> list:
    records = []
    for a in db.list_plaid_accounts():
        balance = a["current_balance"]
        signed = -abs(balance) if balance is not None and _is_liability_type(a["type"]) else balance
        records.append((
            a["name"] or "",
            (a["mask"] or "")[-4:],
            f"{signed:.2f}" if signed is not None else "",
            downloaded_at,
            _account_type_label(a["type"], a["subtype"]),
        ))
    return records


def write_account_balances(*, downloaded_at: str) -> None:
    config.ensure_directories()
    records = account_balance_records(downloaded_at=downloaded_at)

    csv_path = config.account_balances_csv_path()
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(ACCOUNT_CSV_COLUMNS)
        writer.writerows(records)

    row_lines = []
    total = 0.0
    for inst, last4, balance, when, typ in records:
        row_lines.append(
            f'    <tr><td>{html.escape(inst)}</td><td>{html.escape(typ)}</td><td>{html.escape(last4)}</td>'
            f'<td class="num">{html.escape(_format_money(balance))}</td><td>{html.escape(when)}</td></tr>'
        )
        if balance:
            total += float(balance)
    rows_html = "\n".join(row_lines) or '    <tr><td colspan="5" class="muted">No linked accounts yet.</td></tr>'

    html_path = config.account_balances_html_path()
    html_path.write_text(
        _HTML_PAGE.format(
            title="Account Balances",
            generated_at=html.escape(downloaded_at),
            csv_name=config.ACCOUNT_BALANCES_CSV_NAME,
            header_cells="<th>Financial Institution</th><th>Account Type</th><th>Last 4 Digits</th><th class=\"num\">Balance</th><th>Last Update</th>",
            rows=rows_html,
            footer_cells=f'<td colspan="3">Total</td><td class="num">{html.escape(_format_money(total))}</td><td></td>',
            sort_script=SORT_SCRIPT,
            product_name=branding.PRODUCT_NAME,
        ),
        encoding="utf-8",
    )


def portfolio_position_records() -> list:
    accounts_by_id = {a["account_id"]: a for a in db.list_plaid_accounts()}
    records = []
    for h in db.list_plaid_holdings():
        account = accounts_by_id.get(h["account_id"], {})
        records.append((
            account.get("name") or "",
            account.get("official_name") or account.get("name") or "",
            h["security_name"] or "",
            h["ticker_symbol"] or "",
            (h["security_type"] or "").replace("_", " ").title(),
            h["quantity"],
            h["institution_price"],
            h["institution_value"],
            h["cost_basis"],
            h["iso_currency_code"] or "USD",
        ))
    return records


def write_portfolio_positions(*, downloaded_at: str) -> None:
    config.ensure_directories()
    records = portfolio_position_records()

    csv_path = config.portfolio_positions_csv_path()
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(POSITION_CSV_COLUMNS)
        writer.writerows(records)

    row_lines = []
    total_value = 0.0
    for inst, account, name, ticker, sec_type, qty, price, value, cost, currency in records:
        row_lines.append(
            f'    <tr><td>{html.escape(inst)}</td><td>{html.escape(account)}</td>'
            f'<td>{html.escape(name)}</td><td>{html.escape(ticker)}</td><td>{html.escape(sec_type)}</td>'
            f'<td class="num">{qty if qty is not None else ""}</td>'
            f'<td class="num">{html.escape(_format_money(price))}</td>'
            f'<td class="num">{html.escape(_format_money(value))}</td>'
            f'<td class="num">{html.escape(_format_money(cost))}</td><td>{html.escape(currency)}</td></tr>'
        )
        if value:
            total_value += float(value)
    rows_html = "\n".join(row_lines) or '    <tr><td colspan="10" class="muted">No holdings yet.</td></tr>'

    html_path = config.portfolio_positions_html_path()
    html_path.write_text(
        _HTML_PAGE.format(
            title="Portfolio Positions",
            generated_at=html.escape(downloaded_at),
            csv_name=config.PORTFOLIO_POSITIONS_CSV_NAME,
            header_cells=(
                "<th>Financial Institution</th><th>Account</th><th>Security Name</th><th>Ticker</th>"
                "<th>Type</th><th class=\"num\">Quantity</th><th class=\"num\">Price</th>"
                "<th class=\"num\">Market Value</th><th class=\"num\">Cost Basis</th><th>Currency</th>"
            ),
            rows=rows_html,
            footer_cells=f'<td colspan="7">Total</td><td class="num">{html.escape(_format_money(total_value))}</td><td colspan="2"></td>',
            sort_script=SORT_SCRIPT,
            product_name=branding.PRODUCT_NAME,
        ),
        encoding="utf-8",
    )
