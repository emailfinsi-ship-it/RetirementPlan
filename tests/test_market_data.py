"""Yahoo Finance as the fallback price source (source.collector.yahoo and market_data). No network: yfinance is faked."""

import unittest
from unittest.mock import patch

import pandas as pd

from source.collector import alpaca, market_data, yahoo
from source.webapp.pages import quote_chart, watchlist

KEYS = ("K", "S")


def frame(closes, start="2026-09-01"):
    idx = pd.date_range(start, periods=len(closes), freq="B", tz="America/New_York")
    return pd.DataFrame({"Open": closes, "High": [c + 1 for c in closes], "Low": [c - 1 for c in closes],
                         "Close": closes, "Volume": [1000] * len(closes)}, index=idx)


class FakeTicker:
    def __init__(self, sym, frames, calls):
        self.sym, self.frames, self.calls = sym, frames, calls
        self.info = {"longName": "Apple Inc. Common Stock"}
        self.news = [{"content": {"title": "Apple rises", "summary": "Shares up.", "pubDate": "2026-10-01T10:00:00Z",
                                  "provider": {"displayName": "Reuters"}, "canonicalUrl": {"url": "https://example.com/a"}}},
                     {"title": "Old shape", "link": "https://example.com/b", "publisher": "AP", "providerPublishTime": 1760000000},
                     {"title": "No link"}]

    def history(self, **kw):
        self.calls.append((self.sym, kw))
        if self.sym not in self.frames:
            raise RuntimeError("no data")
        return self.frames[self.sym]


class FakeYF:
    def __init__(self, frames):
        self.frames, self.calls = frames, []

    def Ticker(self, sym):
        return FakeTicker(sym, self.frames, self.calls)


def enabled(frames):
    yf = FakeYF(frames)
    return yf, patch.object(yahoo, "_yf", lambda: yf), patch.object(market_data, "YAHOO_ENABLED", True)


class TestYahoo(unittest.TestCase):
    def setUp(self):
        market_data.reset()

    def test_bars_have_alpacas_shape_and_dots_become_dashes(self):
        yf, a, b = enabled({"BRK-B": frame([10.0, 11.0, 12.0])})
        with a, b:
            bars = yahoo.get_bars("brk.b", start="2026-08-01T00:00:00Z")
        self.assertEqual(len(bars), 3)
        self.assertEqual(set(bars[0]), {"t", "o", "h", "l", "c", "v"})
        self.assertTrue(bars[0]["t"].endswith("Z"))
        self.assertEqual(yf.calls[0][0], "BRK-B")
        self.assertEqual(yf.calls[0][1]["start"], "2026-08-01")

    def test_snapshot_comes_from_the_last_two_bars(self):
        _yf, a, b = enabled({"AAPL": frame([100.0, 102.0])})
        with a, b:
            snap = yahoo.get_snapshot("AAPL")
        self.assertEqual(snap["price"], 102.0)
        self.assertEqual(snap["prev_day"]["c"], 100.0)

    def test_name_and_news_are_cleaned(self):
        _yf, a, b = enabled({})
        with a, b:
            self.assertEqual(yahoo.get_asset_name("AAPL"), "Apple Inc.")
            news = yahoo.get_news("AAPL")
        self.assertEqual([n["headline"] for n in news], ["Apple rises", "Old shape"])      # the item with no link is dropped
        self.assertEqual(news[0]["source"], "Reuters")

    def test_a_failure_is_a_market_data_error(self):
        _yf, a, b = enabled({})
        with a, b, self.assertRaises(alpaca.AlpacaError):
            yahoo.get_bars("ZZZ", start="2026-08-01T00:00:00Z")


class TestFallback(unittest.TestCase):
    def setUp(self):
        market_data.reset()

    def test_no_keys_uses_yahoo_and_says_so(self):
        _yf, a, b = enabled({"AAPL": frame([100.0, 101.0])})
        with a, b:
            bars = market_data.get_bars("AAPL", None, start="2026-08-01T00:00:00Z")
            self.assertEqual(len(bars), 2)
            self.assertEqual(market_data.last_source(), "yahoo")

    def test_alpaca_down_falls_back_then_skips_alpaca_for_a_minute(self):
        _yf, a, b = enabled({"AAPL": frame([100.0, 101.0])})
        err = alpaca.AlpacaError("Couldn't reach Alpaca.")
        err.status = 0
        with a, b, patch.object(alpaca, "get_bars", side_effect=err) as ga:
            market_data.get_bars("AAPL", KEYS, start="2026-08-01T00:00:00Z")
            market_data.get_bars("AAPL", KEYS, start="2026-08-01T00:00:00Z")
        self.assertEqual(ga.call_count, 1)             # the second call did not wait on Alpaca again

    def test_a_bad_ticker_does_not_trip_the_breaker(self):
        _yf, a, b = enabled({"AAPL": frame([100.0, 101.0])})
        err = alpaca.AlpacaError("Alpaca could not find that.")
        err.status = 404
        with a, b, patch.object(alpaca, "get_bars", side_effect=err) as ga:
            market_data.get_bars("AAPL", KEYS, start="2026-08-01T00:00:00Z")
            market_data.get_bars("AAPL", KEYS, start="2026-08-01T00:00:00Z")
        self.assertEqual(ga.call_count, 2)

    def test_both_down_reports_alpacas_error(self):
        _yf, a, b = enabled({})
        err = alpaca.AlpacaError("Alpaca rejected the keys.")
        err.status = 401
        with a, b, patch.object(alpaca, "get_bars", side_effect=err):
            with self.assertRaises(alpaca.AlpacaError) as ctx:
                market_data.get_bars("AAPL", KEYS, start="2026-08-01T00:00:00Z")
        self.assertIn("rejected the keys", str(ctx.exception))

    def test_a_ticker_iex_has_no_bars_for_is_filled_from_yahoo(self):
        _yf, a, b = enabled({"VTI": frame([200.0, 201.0])})
        good = [{"t": "2026-10-01T04:00:00Z", "o": 1, "h": 2, "l": 1, "c": 1.5, "v": 5}]
        with a, b, patch.object(alpaca, "get_bars_multi", return_value={"AAPL": good, "VTI": []}):
            got = market_data.get_bars_multi(["AAPL", "VTI"], KEYS, start="2026-08-01T00:00:00Z")
        self.assertEqual(got["AAPL"], good)
        self.assertEqual(len(got["VTI"]), 2)

    def test_off_under_the_test_runner_alpaca_errors_still_surface(self):
        with patch.object(alpaca, "get_bars", side_effect=alpaca.AlpacaError("down")):
            with self.assertRaises(alpaca.AlpacaError):
                market_data.get_bars("AAPL", KEYS, start="2026-08-01T00:00:00Z")

    def test_stock_analysis_works_with_no_alpaca_keys(self):
        long = frame([100.0 + i * 0.5 for i in range(260)], start="2025-10-01")
        _yf, a, b = enabled({"AAPL": long})
        from source.common import db
        with a, b, patch.object(db.watchlist, "cached_names", return_value={}), patch.object(db.watchlist, "remember_name"):
            out = quote_chart.build_quote("AAPL", None, "3M", mode="")
            rows = watchlist.build_rows([{"symbol": "AAPL", "note": ""}], None, mode="")
        self.assertEqual(out["data_source"], "yahoo")
        self.assertEqual(out["name"], "Apple Inc.")
        self.assertTrue(out["news"])
        self.assertEqual(rows[0]["name"], "Apple Inc.")
        self.assertGreater(rows[0]["price"], 100)

    def test_market_data_source_without_keys(self):
        from source.common import secrets_store
        with patch.object(secrets_store, "get_alpaca_keys", side_effect=secrets_store.SecretNotFoundError("x")):
            with self.assertRaises(ValueError):                    # the test runner has Yahoo off: the old message
                quote_chart.market_data_source()
            with patch.object(market_data, "YAHOO_ENABLED", True):
                self.assertEqual(quote_chart.market_data_source(), (None, ""))


if __name__ == "__main__":
    unittest.main()


class TestAlpacaView(unittest.TestCase):
    """The Alpaca trading page keeps its numbers for a moment so coming back to the tab is instant."""

    def setUp(self):
        from source.collector import alpaca_view
        self.v = alpaca_view
        self.v.invalidate()
        self.calls = 0
        outer = self

        def acct(keys, mode="paper", **kw):
            outer.calls += 1
            return {"equity": 1.0}
        self.patches = [patch.object(self.v, "ENABLED", True), patch.object(alpaca, "get_account", acct),
                        patch.object(alpaca, "list_positions", lambda *a, **k: []), patch.object(alpaca, "list_orders", lambda *a, **k: [])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.v.invalidate()

    def test_a_second_look_within_20_seconds_does_not_ask_alpaca_again(self):
        self.v.get(KEYS, "paper")
        got = self.v.get(KEYS, "paper")
        self.assertEqual(self.calls, 1)
        self.assertFalse(got["stale"])

    def test_an_older_copy_is_shown_at_once_and_refreshed_behind_the_scenes(self):
        self.v.get(KEYS, "paper")
        self.v._cache["paper"]["at"] -= 120
        got = self.v.get(KEYS, "paper")
        self.assertTrue(got["stale"])
        for _ in range(100):                 # the background refresh lands shortly
            if not self.v._refreshing and not self.v.get(KEYS, "paper")["stale"]:
                break
            import time as _t
            _t.sleep(0.02)
        self.assertEqual(self.calls, 2)

    def test_when_alpaca_is_down_the_last_copy_is_shown_with_the_reason(self):
        self.v.get(KEYS, "paper")
        self.v._cache["paper"]["at"] -= 3600
        with patch.object(alpaca, "get_account", side_effect=alpaca.AlpacaError("Couldn't reach Alpaca.")):
            got = self.v.get(KEYS, "paper")
        self.assertTrue(got["stale"])
        self.assertIn("reach Alpaca", got["error"])

    def test_nothing_kept_and_alpaca_down_is_still_an_error(self):
        with patch.object(alpaca, "get_account", side_effect=alpaca.AlpacaError("down")):
            with self.assertRaises(alpaca.AlpacaError):
                self.v.get(KEYS, "paper")

    def test_invalidate_forces_a_fresh_read(self):
        self.v.get(KEYS, "paper")
        self.v.invalidate("paper")
        self.v.get(KEYS, "paper")
        self.assertEqual(self.calls, 2)


class TestInstantReturn(unittest.TestCase):
    def test_broker_and_watchlist_pages_keep_the_last_view_in_the_browser_tab(self):
        from source.webapp.pages import broker_page
        from source.webapp import broker_api
        for broker in ("etrade", "ibkr"):
            with patch.object(broker_api, "etrade_state", return_value={"has_keys": False, "has_session": False, "key_hint": "", "has_secret": False}), \
                    patch.object(broker_api, "gateway_url", return_value="https://localhost:5757"):
                page = broker_page._render_broker_page(broker)
            self.assertIn("sessionStorage.setItem(CACHE_KEY", page)
            self.assertIn("cacheShow();", page)
        self.assertIn("finsi.watchlist", watchlist._JS)

    def test_the_rating_hover_box_has_one_fact_per_line(self):
        from source.webapp.pages import position_ratings
        self.assertIn("p.join('\\n')", position_ratings.JS)
        self.assertIn("white-space:pre-line", position_ratings.CSS)

    def test_a_stale_alpaca_page_says_so_and_reloads_once(self):
        from source.webapp.pages import trading
        note = trading._stale_note_html({"at": 1_700_000_000, "error": ""})
        self.assertIn("refreshing", note)
        self.assertIn("location.reload()", note)
        down = trading._stale_note_html({"at": 1_700_000_000, "error": "Couldn't reach Alpaca."})
        self.assertIn("Showing what was loaded at", down)
        self.assertNotIn("location.reload()", down)
