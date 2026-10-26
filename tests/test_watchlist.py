"""The Stock Analysis tab's watchlist: the stored ticker list, Alpaca's multi-symbol
market-data calls, the table's rows, and the /api/watchlist/* routes. No test
touches the network."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from source.collector import alpaca
from source.common import db
from source.webapp import trading_api
from source.webapp.pages import quote_chart, watchlist as wl
from tests.test_alpaca import FakeAlpaca, FakeResponse, KEYS
from tests.test_quote import make_bars
from tests.testing_utils import TempConfigTestCase

NOW = datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc)


def multi_bars(**series):
    return {"bars": {sym: [{"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]} for b in bars]
                     for sym, bars in series.items()}, "next_page_token": None}


def climb(n=300, start=100.0):
    return make_bars([start * 1.004 ** i for i in range(n)], start=NOW - timedelta(days=n))


def fall(n=300, start=200.0):
    return make_bars([start * 0.996 ** i for i in range(n)], start=NOW - timedelta(days=n))


def snap(price, prev):
    return {"latestTrade": {"p": price, "t": "2026-10-02T19:59:00Z"}, "latestQuote": {"bp": price - .1, "ap": price + .1, "bs": 1, "as": 1},
            "dailyBar": {"o": price - 1, "h": price + 1, "l": price - 2, "c": price, "v": 5000},
            "prevDailyBar": {"o": 1, "h": 2, "l": 1, "c": prev, "v": 9}}


class TestWatchlistStore(TempConfigTestCase):
    def test_add_remove_and_order(self):
        self.assertEqual(db.watchlist.add("aapl, msft"), ["AAPL", "MSFT"])
        self.assertEqual(db.watchlist.add("AAPL vti"), ["VTI"])             # a repeat is skipped
        self.assertEqual(db.watchlist.list_symbols(), ["AAPL", "MSFT", "VTI"])
        db.watchlist.remove("msft")
        self.assertEqual(db.watchlist.list_symbols(), ["AAPL", "VTI"])

    def test_a_bad_ticker_adds_nothing(self):
        with self.assertRaises(ValueError) as ctx:
            db.watchlist.add("AAPL, $$$")
        self.assertIn("not a ticker", str(ctx.exception))
        self.assertEqual(db.watchlist.list_symbols(), [])
        with self.assertRaises(ValueError):
            db.watchlist.add("  ")

    def test_the_list_has_a_size_limit(self):
        letters = [a + b for a in "ABCDEFGHIJ" for b in "ABCDEF"]
        db.watchlist.add(letters[:db.watchlist.MAX_SYMBOLS])
        with self.assertRaises(ValueError) as ctx:
            db.watchlist.add("ZZZ")
        self.assertIn("up to 50", str(ctx.exception))

    def test_notes_are_kept_and_trimmed(self):
        db.watchlist.add("VTI")
        db.watchlist.set_note("vti", "  core holding " + "x" * 300)
        note = db.watchlist.list_items()[0]["note"]
        self.assertTrue(note.startswith("core holding"))
        self.assertEqual(len(note), db.watchlist.MAX_NOTE)


class TestMultiSymbolData(unittest.TestCase):
    def test_bars_for_the_whole_list_come_in_one_call(self):
        fake = FakeAlpaca({("GET", "data.alpaca.markets/v2/stocks/bars"): multi_bars(AAPL=climb(5), VTI=fall(5))})
        got = alpaca.get_bars_multi(["aapl", "vti", "zzz"], KEYS, start="2025-01-01T00:00:00Z", urlopen=fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("symbols=AAPL%2CVTI%2CZZZ", fake.calls[0]["url"])
        self.assertIn("feed=iex", fake.calls[0]["url"])
        self.assertEqual((len(got["AAPL"]), len(got["VTI"]), got["ZZZ"]), (5, 5, []))

    def test_bars_follow_the_next_page_token(self):
        page1 = {**multi_bars(AAPL=climb(3)), "next_page_token": "abc"}
        page2 = multi_bars(AAPL=climb(2))
        answers = iter([page1, page2])
        fake = FakeAlpaca()
        fake.routes = {}
        calls = []

        def opener(request, timeout=None):
            from tests.test_alpaca import FakeResponse
            calls.append(request.full_url)
            return FakeResponse(next(answers))

        got = alpaca.get_bars_multi(["AAPL"], KEYS, start="2025-01-01T00:00:00Z", urlopen=opener)
        self.assertEqual(len(got["AAPL"]), 5)
        self.assertIn("page_token=abc", calls[1])

    def test_snapshots_in_one_call_and_unknown_symbols_left_out(self):
        fake = FakeAlpaca({("GET", "data.alpaca.markets/v2/stocks/snapshots"): {"AAPL": snap(150, 148)}})
        got = alpaca.get_snapshots(["AAPL", "VTI"], KEYS, urlopen=fake)
        self.assertEqual(list(got), ["AAPL"])
        self.assertEqual(got["AAPL"]["price"], 150)
        self.assertEqual(got["AAPL"]["prev_day"]["c"], 148)
        self.assertEqual(len(fake.calls), 1)

    def test_a_bad_symbol_is_refused_before_any_call(self):
        fake = FakeAlpaca()
        with self.assertRaises(alpaca.AlpacaError):
            alpaca.get_snapshots(["AAPL", "$$"], KEYS, urlopen=fake)
        self.assertEqual(fake.calls, [])


class TestCompanyNames(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        quote_chart._NO_NAME.clear()

    def test_share_type_tails_are_dropped(self):
        for raw, want in (("Apple Inc. Common Stock", "Apple Inc."), ("Alphabet Inc. Class A Common Stock", "Alphabet Inc. Class A"),
                          ("SPDR S&P 500 ETF Trust", "SPDR S&P 500 ETF Trust"), ("Foo Corp - Ordinary Shares", "Foo Corp"), (None, "")):
            self.assertEqual(alpaca.clean_company_name(raw), want)

    def test_the_name_comes_from_the_host_of_the_account_asked(self):
        fake = FakeAlpaca({("GET", "paper-api.alpaca.markets/v2/assets/AAPL"): {"name": "Apple Inc. Common Stock"},
                           ("GET", "api.alpaca.markets/v2/assets/AAPL"): {"name": "Apple Live"}})
        self.assertEqual(alpaca.get_asset_name("aapl", KEYS, mode="paper", urlopen=fake), "Apple Inc.")
        self.assertEqual(alpaca.get_asset_name("AAPL", KEYS, mode="live", urlopen=fake), "Apple Live")
        self.assertIsNone(alpaca.get_asset_name("ZZZ", KEYS, urlopen=fake))        # no such asset: no name, no error

    def test_each_name_is_looked_up_once_then_remembered(self):
        fake = FakeAlpaca({("GET", "paper-api.alpaca.markets/v2/assets/AAPL"): {"name": "Apple Inc. Common Stock"}})
        self.assertEqual(quote_chart.company_names(["AAPL", "ZZZ"], KEYS, "paper", urlopen=fake), {"AAPL": "Apple Inc."})
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(quote_chart.company_names(["AAPL", "ZZZ"], KEYS, "paper", urlopen=fake), {"AAPL": "Apple Inc."})
        self.assertEqual(len(fake.calls), 2)                                        # neither is asked for again
        self.assertEqual(db.watchlist.cached_names(["AAPL"]), {"AAPL": "Apple Inc."})


class TestNews(unittest.TestCase):
    def test_headlines_are_cleaned_and_only_web_links_kept(self):
        fake = FakeAlpaca({("GET", "data.alpaca.markets/v1beta1/news"): {"news": [
            {"headline": "  Apple   beats estimates ", "summary": "x" * 400, "source": "benzinga", "url": "https://example.com/a",
             "created_at": "2026-10-02T14:00:00Z"},
            {"headline": "Bad link", "url": "javascript:alert(1)"},
            {"headline": "", "url": "https://example.com/b"},
        ]}})
        got = alpaca.get_news("aapl", KEYS, urlopen=fake)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["headline"], "Apple beats estimates")
        self.assertTrue(got[0]["summary"].endswith("...") and len(got[0]["summary"]) == 283)
        self.assertIn("symbols=AAPL", fake.calls[0]["url"])
        self.assertEqual(fake.calls[0]["method"], "GET")


class TestQuoteExtras(TempConfigTestCase):
    def build(self, news):
        from tests.test_quote import FakeFeed
        feed = FakeFeed(make_bars([100 + i * 0.3 for i in range(300)]))
        with patch.object(alpaca, "get_bars", feed.get_bars), patch.object(alpaca, "get_snapshot", feed.get_snapshot), \
                patch.object(alpaca, "get_asset_name", lambda *a, **k: "Vanguard Total Stock Market ETF"), \
                patch.object(alpaca, "get_news", news):
            return quote_chart.build_quote("VTI", KEYS, "3M", now=NOW, mode="paper")

    def test_a_quote_carries_the_company_name_and_news(self):
        out = self.build(lambda *a, **k: [{"headline": "H", "summary": "", "source": "S", "url": "https://x.test", "time": ""}])
        self.assertEqual(out["name"], "Vanguard Total Stock Market ETF")
        self.assertEqual(out["news"][0]["headline"], "H")
        self.assertFalse(out["news_error"])

    def test_news_trouble_never_breaks_the_quote(self):
        def boom(*a, **k):
            raise alpaca.AlpacaError("down")
        out = self.build(boom)
        self.assertEqual(out["news"], [])
        self.assertTrue(out["news_error"])
        self.assertIn("<svg", out["chart"])


class TestRows(unittest.TestCase):
    def feed(self):
        return FakeAlpaca({
            ("GET", "data.alpaca.markets/v2/stocks/bars"): multi_bars(UP=climb(), DOWN=fall()),
            ("GET", "data.alpaca.markets/v2/stocks/snapshots"): {"UP": snap(330.0, 328.0), "DOWN": snap(60.0, 61.0)},
        })

    def test_one_row_per_item_in_order_with_indicators(self):
        items = [{"symbol": "DOWN", "note": "n1"}, {"symbol": "UP", "note": ""}, {"symbol": "NONE", "note": ""}]
        fake = self.feed()
        rows = wl.build_rows(items, KEYS, now=NOW, urlopen=fake)
        self.assertEqual([r["symbol"] for r in rows], ["DOWN", "UP", "NONE"])
        self.assertEqual([r["name"] for r in rows], ["", "", ""])        # no mode given: names are not looked up
        down, up, none = rows
        self.assertEqual(down["note"], "n1")
        self.assertEqual(up["price"], 330.0)
        self.assertAlmostEqual(up["change"], 2.0)
        self.assertAlmostEqual(up["change_pct"], 2.0 / 328.0 * 100)
        self.assertEqual((up["trend_short"], up["trend_long"], down["trend_short"], down["trend_long"]), ("Up", "Up", "Down", "Down"))
        self.assertIn("Buy", up["rating"])
        self.assertIn("Sell", down["rating"])
        self.assertTrue(0 <= up["week_position"] <= 1 and 0 <= up["day_position"] <= 1)
        self.assertTrue(0 <= up["rsi"] <= 100)
        self.assertIn(up["macd_state"], ("above", "below"))
        self.assertIn(up["macd_sort"], (1, -1))
        self.assertIn("macd_cross", up)
        self.assertIn("No price history", none["error"])
        self.assertEqual(len(fake.calls), 2)                    # one for bars, one for quotes: not one per ticker

    def test_empty_list_makes_no_calls(self):
        fake = FakeAlpaca()
        self.assertEqual(wl.build_rows([], KEYS, now=NOW, urlopen=fake), [])
        self.assertEqual(fake.calls, [])

    def test_missing_snapshots_fall_back_to_the_last_daily_bar(self):
        fake = FakeAlpaca({("GET", "data.alpaca.markets/v2/stocks/bars"): multi_bars(UP=climb())})   # snapshots answer 404
        rows = wl.build_rows([{"symbol": "UP", "note": ""}], KEYS, now=NOW, urlopen=fake)
        self.assertAlmostEqual(rows[0]["price"], climb()[-1]["c"])

    def test_a_short_history_has_a_rating_that_says_so(self):
        fake = FakeAlpaca({("GET", "data.alpaca.markets/v2/stocks/bars"): multi_bars(NEW=climb(12))})
        row = wl.build_rows([{"symbol": "NEW", "note": ""}], KEYS, now=NOW, urlopen=fake)[0]
        self.assertEqual(row["rating"], "Not enough history")
        self.assertIsNone(row["rating_score"])


class TestPersistence(TempConfigTestCase):
    def test_the_list_and_notes_survive_a_restart_and_show_on_the_page_at_once(self):
        trading_api.handle("/api/watchlist/add", {"symbol": "aapl, vti"})
        trading_api.handle("/api/watchlist/note", {"symbol": "VTI", "note": "core"})
        db.init_db()                                   # what every start of the program runs
        self.assertEqual(db.watchlist.list_symbols(), ["AAPL", "VTI"])
        self.assertEqual(db.watchlist.list_items()[1]["note"], "core")
        with db.connect() as conn:                     # really in the database file
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0], 2)
        page = wl.watchlist_card_html()                # drawn from the database before any price call
        self.assertIn('"symbol": "AAPL"', page)
        self.assertIn('"note": "core"', page)

    def test_an_empty_list_page_has_an_empty_initial_list(self):
        self.assertIn("var rows = [], earnBy", wl.watchlist_card_html())


class TestRoutes(TempConfigTestCase):
    def test_add_remove_note_need_no_keys_and_never_order(self):
        out = trading_api.handle("/api/watchlist/add", {"symbol": "aapl, vti"})
        self.assertEqual(out, {"added": ["AAPL", "VTI"]})
        trading_api.handle("/api/watchlist/note", {"symbol": "VTI", "note": "core"})
        self.assertEqual(db.watchlist.list_items()[1]["note"], "core")
        trading_api.handle("/api/watchlist/remove", {"symbol": "aapl"})
        self.assertEqual(db.watchlist.list_symbols(), ["VTI"])

    def test_data_uses_practice_keys_first_then_live(self):
        db.watchlist.add("UP")
        seen = []

        def fake_rows(items, keys, **kw):
            seen.append(keys)
            return [{"symbol": "UP"}]

        def keys_for(*, mode="paper"):
            if mode == "paper" and have["paper"]:
                return ("P", "p")
            if mode == "live" and have["live"]:
                return ("L", "l")
            from source.common import secrets_store
            raise secrets_store.SecretNotFoundError("none")

        have = {"paper": True, "live": True}
        with patch("source.common.secrets_store.get_alpaca_keys", keys_for), patch.object(wl, "build_rows", fake_rows):
            trading_api.handle("/api/watchlist/data", {})
            have["paper"] = False
            trading_api.handle("/api/watchlist/data", {})
            have["live"] = False
            out = trading_api.handle("/api/watchlist/data", {})
        self.assertEqual(seen, [("P", "p"), ("L", "l")])
        # No keys: the saved tickers still come back, with the reason, instead of an error.
        self.assertEqual([r["symbol"] for r in out["rows"]], ["UP"])
        self.assertIn("Trading tab", out["warning"])

    def test_a_price_feed_failure_still_returns_the_saved_list(self):
        db.watchlist.add("AAPL, VTI")
        db.watchlist.remember_name("AAPL", "Apple Inc.")
        with patch.object(wl, "build_rows", side_effect=alpaca.AlpacaError("Alpaca is down")), \
                patch.object(trading_api.quote_chart, "market_data_source", return_value=(("k", "s"), "paper")):
            out = trading_api.handle("/api/watchlist/data", {})
        self.assertEqual([r["symbol"] for r in out["rows"]], ["AAPL", "VTI"])
        self.assertEqual(out["rows"][0]["name"], "Apple Inc.")
        self.assertIn("Alpaca is down", out["warning"])

    def test_an_empty_list_needs_no_keys(self):
        self.assertEqual(trading_api.handle("/api/watchlist/data", {}), {"rows": []})


if __name__ == "__main__":
    unittest.main()
