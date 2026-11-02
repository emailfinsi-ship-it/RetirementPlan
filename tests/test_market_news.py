"""The Trading tab's Market news card: market-wide headlines from Alpaca and Yahoo, topic labels, an hourly refresh.
No network: both feeds are faked."""

import unittest
from unittest.mock import patch

from source.collector import alpaca, market_data, market_news, yahoo
from source.common import demo_data
from source.webapp import trading_api
from source.webapp.pages import market_news_card
from tests.test_dashboard import DashboardTestCase

KEYS = ("K", "S")


def item(head, url, when, summary="", source="Reuters"):
    return {"headline": head, "summary": summary, "source": source, "url": url, "time": when}


ALP = [item("Fed signals rate cut as inflation cools", "https://a/1", "2026-11-02T14:00:00Z"),
       item("Stocks close higher", "https://a/2", "2026-11-02T13:00:00Z")]
YAH = [item("Oil jumps as OPEC trims output", "https://y/1", "2026-11-02T15:00:00Z"),
       item("Stocks close higher", "https://y/2", "2026-11-02T12:30:00Z", source="AP")]       # the same story under another link


class TestMarketNews(unittest.TestCase):
    def setUp(self):
        market_news.reset()

    def test_topics_come_from_the_words_in_the_headline(self):
        t = market_news.topic_of
        self.assertEqual(t(item("Fed holds rates steady", "u", "")), "Fed & rates")
        self.assertEqual(t(item("Jobs report beats forecasts", "u", "")), "Economy")
        self.assertEqual(t(item("Crude oil slides", "u", "")), "Oil & energy")
        self.assertEqual(t(item("New tariffs on China announced", "u", "")), "World & trade")
        self.assertEqual(t(item("Stocks drift sideways", "u", "")), "Markets")

    def test_alpaca_and_yahoo_are_merged_newest_first_without_repeats(self):
        with patch.object(alpaca, "get_news_for", return_value=ALP), patch.object(yahoo, "get_topic_news", return_value=YAH), \
                patch.object(market_data, "YAHOO_ENABLED", True):
            out = market_news.get(KEYS, now=1000.0)
        heads = [n["headline"] for n in out["items"]]
        self.assertEqual(heads, ["Oil jumps as OPEC trims output", "Fed signals rate cut as inflation cools", "Stocks close higher"])
        self.assertEqual(out["source"], "Alpaca and Yahoo Finance")
        self.assertEqual(out["items"][0]["topic"], "Oil & energy")
        self.assertEqual(out["refresh_seconds"], 3600)

    def test_it_is_kept_for_most_of_an_hour_then_fetched_again(self):
        with patch.object(alpaca, "get_news_for", return_value=ALP * 6) as a, patch.object(market_data, "YAHOO_ENABLED", False):
            market_news.get(KEYS, now=1000.0)
            market_news.get(KEYS, now=1000.0 + 600)             # ten minutes later: from memory
            self.assertEqual(a.call_count, 1)
            market_news.get(KEYS, now=1000.0 + 3600)            # an hour later: fetched again
            self.assertEqual(a.call_count, 2)

    def test_refresh_button_waits_a_minute_between_fetches(self):
        with patch.object(alpaca, "get_news_for", return_value=ALP) as a, patch.object(market_data, "YAHOO_ENABLED", False):
            market_news.get(KEYS, now=1000.0)
            market_news.get(KEYS, force=True, now=1010.0)
            self.assertEqual(a.call_count, 1)
            market_news.get(KEYS, force=True, now=1100.0)
            self.assertEqual(a.call_count, 2)

    def test_a_failed_refresh_keeps_the_last_list_and_says_so(self):
        with patch.object(alpaca, "get_news_for", return_value=ALP), patch.object(market_data, "YAHOO_ENABLED", False):
            market_news.get(KEYS, now=1000.0)
        with patch.object(alpaca, "get_news_for", side_effect=alpaca.AlpacaError("Alpaca is down")), patch.object(market_data, "YAHOO_ENABLED", False):
            out = market_news.get(KEYS, now=1000.0 + 4000)
        self.assertTrue(out["stale"])
        self.assertEqual(len(out["items"]), 2)
        self.assertIn("down", out["error"])

    def test_nothing_to_show_and_nothing_cached_reports_the_error(self):
        with patch.object(alpaca, "get_news_for", side_effect=alpaca.AlpacaError("keys rejected")), patch.object(market_data, "YAHOO_ENABLED", False):
            out = market_news.get(KEYS)
        self.assertEqual(out["items"], [])
        self.assertIn("rejected", out["error"])

    def test_yahoo_alone_works_without_alpaca_keys(self):
        with patch.object(yahoo, "get_topic_news", return_value=YAH), patch.object(market_data, "YAHOO_ENABLED", True):
            out = market_news.get(None)
        self.assertEqual(out["source"], "Yahoo Finance")

    def test_yahoo_topic_news_skips_bad_symbols_and_repeats(self):
        class T:
            def __init__(self, sym):
                self.sym = sym

            @property
            def news(self):
                if self.sym == "BAD":
                    raise RuntimeError("no data")
                return [{"title": "Shared story", "link": "https://x/1", "publisher": "AP", "providerPublishTime": 1760000000}]

        class YF:
            Ticker = staticmethod(lambda sym: T(sym))

        with patch.object(yahoo, "_yf", lambda: YF):
            got = yahoo.get_topic_news(["^GSPC", "BAD", "^DJI"])
        self.assertEqual([n["headline"] for n in got], ["Shared story"])


class TestMarketNewsPage(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household()
        market_news.reset()

    def tearDown(self):
        demo_data.remove_sample_data()

    def test_the_route_is_registered_and_answers_with_the_list(self):
        self.assertIn("/api/market-news", trading_api.ROUTES)
        with patch.object(alpaca, "get_news_for", return_value=ALP), patch.object(market_data, "YAHOO_ENABLED", False), \
                patch("source.webapp.pages.quote_chart.market_data_source", return_value=(KEYS, "paper")):
            out = trading_api.handle("/api/market-news", {})
        self.assertEqual(len(out["items"]), 2)
        self.assertEqual(out["items"][0]["topic"], "Fed & rates")

    def test_the_route_without_any_feed_is_an_error_message_not_a_crash(self):
        out = trading_api.handle("/api/market-news", {})          # no keys saved and Yahoo is off under the tests
        self.assertEqual(out["items"], [])

    def test_the_card_asks_again_every_hour_and_marks_headlines_as_not_advice(self):
        card = market_news_card.market_news_card_html()
        self.assertIn("/api/market-news", card)
        self.assertIn("every hour", card)
        self.assertIn("not recommendations", card)
        self.assertIn("setTimeout", card)


if __name__ == "__main__":
    unittest.main()
