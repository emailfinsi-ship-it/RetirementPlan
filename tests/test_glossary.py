"""The hover explanations of technical terms on Stock Analysis."""

import unittest
from unittest.mock import patch

from source.common import db
from source.webapp.pages import glossary, quote_panel, watchlist


class TestGlossary(unittest.TestCase):
    def test_every_term_the_pages_use_is_defined(self):
        for key in ("macd", "rsi", "sma", "volume", "rating", "trend", "dayrange", "week52", "change", "prevclose", "bid", "ask", "earnings", "vwap"):
            self.assertIn(f"    {key}: [", glossary.JS)

    def test_the_watchlist_headers_and_quote_panel_labels_carry_the_explanations(self):
        self.assertIn("HEAD_TERM", watchlist._JS)
        self.assertIn("rsi: 'rsi'", watchlist._JS)
        for term in ("termAttrs('rating')", "termAttrs('trend')", "termAttrs('bid')", "'Day range', 'dayrange'", "termKeyForSignal(s.name)", "macdTipAttrs("):
            self.assertIn(term, quote_panel._PANEL_JS)

    def test_the_cards_load_the_glossary_and_the_hover_css(self):
        with patch.object(db.watchlist, "list_items", return_value=[]), patch.object(db.watchlist, "cached_names", return_value={}), \
                patch.object(quote_panel, "trade_targets", return_value=[("Alpaca", "/trading.html")]):
            cards = watchlist.watchlist_card_html() + quote_panel.quote_panel_html("paper")
        self.assertIn("window.termAttrs = function", cards)
        self.assertIn("white-space:pre-line", cards)
        self.assertIn(".has-tip", cards)


if __name__ == "__main__":
    unittest.main()
