"""The Stock Analysis tab (/stock-analysis.html): your watchlist as a table, and
a "Quote and chart" card for any ticker (price, day and 52-week range, trend,
a technical buy / sell rating and a price / volume / RSI chart).

Prices come from the Alpaca keys saved on the Trading tab (the practice keys
when there are any, otherwise the live ones). Everything here is read-only: it
never places an order. Owner only, like the Trading tab."""

from __future__ import annotations

from source.common import secrets_store
from source.webapp.pages.quote_panel import quote_panel_html
from source.webapp.pages.watchlist import watchlist_card_html
from source.webapp.render_helpers import _shell


def _render_stock_analysis_page() -> str:
    intro = (
        '<h2 style="margin-top:0">Stock Analysis</h2>'
        '<p class="muted">Follow the stocks and ETFs you care about and look at any one in detail. This is read-only research: '
        'nothing here buys or sells, and none of it is counted in your net worth or retirement plan.</p>'
    )
    if not (secrets_store.has_alpaca_keys(mode="paper") or secrets_store.has_alpaca_keys(mode="live")):
        # Keys are only needed for prices: the saved watchlist is still shown (and can be added to).
        return _shell(title="Stock Analysis", active="stock-analysis.html", body=intro + (
            '<div class="card"><h3 style="margin-top:0;">Connect Alpaca to see prices</h3>'
            '<p class="muted">Prices come from Alpaca&rsquo;s free market data. Save a free practice (paper) account&rsquo;s keys, '
            'or your live keys, on the Trading tab and this page fills in. Your saved watchlist is kept below meanwhile.</p>'
            '<p><a href="/trading.html" class="pill-link"><button type="button" class="primary">Connect on the Trading tab</button></a></p></div>'
        ) + watchlist_card_html())
    return _shell(title="Stock Analysis", active="stock-analysis.html", body=intro + watchlist_card_html() + quote_panel_html())
