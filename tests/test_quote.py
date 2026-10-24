"""The Trading tab's quote panel: indicators and rating (source.reporting.
technicals), Alpaca market-data parsing, the chart and the /api/alpaca/quote
route. No test touches the network."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from source.collector import alpaca
from source.reporting import technicals as ta
from source.webapp import trading_api
from source.webapp.pages import quote_chart
from tests.test_alpaca import FakeAlpaca, KEYS, http_error


def make_bars(closes, volume=1_000_000.0, start=datetime(2025, 1, 2, tzinfo=timezone.utc), step=timedelta(days=1), vols=None):
    bars = []
    for i, c in enumerate(closes):
        bars.append({"t": (start + step * i).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": c - 0.2, "h": c + 0.5, "l": c - 0.6, "c": c,
                     "v": vols[i] if vols else volume})
    return bars


WILDER = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
          46.03, 46.41, 46.22, 45.64]


class TestIndicators(unittest.TestCase):
    def test_sma_and_ema(self):
        self.assertEqual(ta.sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])
        e = ta.ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(e[:2], [None, None])
        self.assertAlmostEqual(e[2], 2.0)
        self.assertAlmostEqual(e[3], 3.0)       # 4 * 0.5 + 2 * 0.5

    def test_rsi_matches_the_classic_worked_example(self):
        r = ta.rsi(WILDER)
        self.assertIsNone(r[13])
        self.assertAlmostEqual(r[14], 70.53, delta=0.1)
        self.assertTrue(all(0 <= v <= 100 for v in r if v is not None))

    def test_rsi_is_100_on_a_straight_rise_and_0_on_a_straight_fall(self):
        self.assertEqual(ta.rsi([float(i) for i in range(1, 40)])[-1], 100.0)
        self.assertEqual(ta.rsi([float(i) for i in range(40, 1, -1)])[-1], 0.0)

    def test_macd_of_a_flat_price_is_zero(self):
        line, sig, hist = ta.macd([10.0] * 60)
        self.assertAlmostEqual(line[-1], 0.0)
        self.assertAlmostEqual(hist[-1], 0.0)

    def test_vwap_weights_by_volume(self):
        bars = [{"h": 10, "l": 10, "c": 10, "v": 100}, {"h": 20, "l": 20, "c": 20, "v": 300}]
        v = ta.vwap(bars)
        self.assertEqual(v[0], 10.0)
        self.assertAlmostEqual(v[1], 17.5)


class TestRatingAndTrends(unittest.TestCase):
    def test_a_steady_climb_rates_buy_and_a_steady_fall_rates_sell(self):
        up = ta.rating(make_bars([100 * 1.006 ** i for i in range(80)]))          # compounding climb: MACD widens too
        down = ta.rating(make_bars([200 - 0.015 * i * i for i in range(80)]))   # falling faster and faster
        self.assertIn(up["label"], ("Buy", "Strong Buy"))
        self.assertIn(down["label"], ("Sell", "Strong Sell"))
        self.assertGreater(up["buy_votes"], up["sell_votes"])
        self.assertTrue(all(s["text"] and s["vote"] in (-1, 0, 1) for s in up["signals"]))

    def test_too_little_history_is_said_plainly(self):
        r = ta.rating(make_bars([10.0] * 10))
        self.assertEqual(r["label"], "Not enough history")
        self.assertEqual(r["signals"], [])

    def test_the_200_day_signal_needs_200_bars(self):
        short = {s["name"] for s in ta.rating(make_bars([100 + i * 0.1 for i in range(120)]))["signals"]}
        long = {s["name"] for s in ta.rating(make_bars([100 + i * 0.1 for i in range(260)]))["signals"]}
        self.assertNotIn("Price vs 200-day average", short)
        self.assertIn("Price vs 200-day average", long)

    def test_a_volume_spike_on_an_up_day_votes_bullish(self):
        closes = [100.0] * 40 + [101.0]
        vols = [1_000_000.0] * 40 + [3_000_000.0]
        sig = {s["name"]: s for s in ta.rating(make_bars(closes, vols=vols))["signals"]}
        self.assertEqual(sig["Volume"]["vote"], 1)

    def test_labels_follow_the_thresholds(self):
        self.assertEqual(ta.label_for(0.9), "Strong Buy")
        self.assertEqual(ta.label_for(0.3), "Buy")
        self.assertEqual(ta.label_for(0.0), "Hold")
        self.assertEqual(ta.label_for(-0.3), "Sell")
        self.assertEqual(ta.label_for(-0.9), "Strong Sell")

    def test_trends_up_down_sideways_and_not_enough(self):
        up = ta.trends(make_bars([100 + i for i in range(260)]))
        self.assertEqual([t["direction"] for t in up], ["Up", "Up", "Up"])
        down = ta.trends(make_bars([400 - i for i in range(260)]))
        self.assertEqual([t["direction"] for t in down], ["Down", "Down", "Down"])
        short = ta.trends(make_bars([100.0 + i for i in range(60)]))
        self.assertEqual(short[2]["direction"], "Not enough history")
        flat = ta.trends(make_bars([100.0] * 80))
        self.assertEqual(flat[0]["direction"], "Sideways")

    def test_range_position(self):
        r = ta.range_stats(make_bars([10, 20, 30]), 25.0)
        self.assertEqual((r["low"], r["high"]), (9.4, 30.5))
        self.assertGreater(r["position"], 0.5)


def bars_payload(bars):
    return {"bars": [{"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]} for b in bars]}


class TestMarketData(unittest.TestCase):
    def test_bars_are_read_from_the_data_host_with_the_free_feed(self):
        data = make_bars([10, 11, 12])
        fake = FakeAlpaca({("GET", "data.alpaca.markets/v2/stocks/VTI/bars"): bars_payload(data)})
        got = alpaca.get_bars("vti", KEYS, start="2025-01-01T00:00:00Z", urlopen=fake)
        self.assertEqual([b["c"] for b in got], [10, 11, 12])
        url = fake.calls[0]["url"]
        self.assertTrue(url.startswith("https://data.alpaca.markets/"))
        self.assertIn("feed=iex", url)
        self.assertNotIn("PKTEST", url)             # keys travel as headers only

    def test_a_bad_symbol_is_refused_before_any_request(self):
        fake = FakeAlpaca({})
        with self.assertRaises(alpaca.AlpacaError):
            alpaca.get_bars("not a ticker!", KEYS, start="2025-01-01T00:00:00Z", urlopen=fake)
        self.assertEqual(fake.calls, [])

    def test_snapshot_is_parsed_flat_or_keyed_by_symbol(self):
        flat = {"latestTrade": {"p": 101.5, "t": "2026-10-01T15:00:00Z"}, "latestQuote": {"bp": 101.4, "ap": 101.6, "bs": 3, "as": 2},
                "dailyBar": {"o": 100, "h": 102, "l": 99.5, "c": 101.5, "v": 5000}, "prevDailyBar": {"o": 99, "h": 100, "l": 98, "c": 99.8, "v": 4000}}
        for payload in (flat, {"VTI": flat}):
            fake = FakeAlpaca({("GET", "data.alpaca.markets/v2/stocks/VTI/snapshot"): payload})
            snap = alpaca.get_snapshot("VTI", KEYS, urlopen=fake)
            self.assertEqual(snap["price"], 101.5)
            self.assertEqual((snap["bid"], snap["ask"]), (101.4, 101.6))
            self.assertEqual(snap["day"]["h"], 102)
            self.assertEqual(snap["prev_day"]["c"], 99.8)


class FakeFeed:
    """Stands in for alpaca.get_bars / get_snapshot inside build_quote."""

    def __init__(self, daily, intraday=None, snapshot=None):
        self.daily, self.intraday, self.snapshot = daily, intraday or [], snapshot

    def get_bars(self, symbol, keys, *, timeframe, start, limit, **kw):
        return self.daily if timeframe == "1Day" else self.intraday

    def get_snapshot(self, symbol, keys, **kw):
        if self.snapshot is None:
            raise alpaca.AlpacaError("no snapshot")
        return self.snapshot


def run_build(feed, range_key="3M", now=datetime(2026, 10, 2, 21, 0, tzinfo=timezone.utc)):
    with patch.object(alpaca, "get_bars", feed.get_bars), patch.object(alpaca, "get_snapshot", feed.get_snapshot):
        return quote_chart.build_quote("VTI", KEYS, range_key, now=now)


class TestBuildQuote(unittest.TestCase):
    def setUp(self):
        closes = [100 + i * 0.3 + (2 if i % 7 == 0 else 0) for i in range(300)]
        self.daily = make_bars(closes, vols=[900_000 + (i % 5) * 100_000 for i in range(300)])

    def test_a_three_month_view_has_every_part(self):
        out = run_build(FakeFeed(self.daily))
        self.assertEqual(out["symbol"], "VTI")
        self.assertEqual(out["range"], "3M")
        q = out["quote"]
        self.assertEqual(q["price"], self.daily[-1]["c"])
        self.assertAlmostEqual(q["change"], self.daily[-1]["c"] - self.daily[-2]["c"])
        self.assertTrue(0 <= q["day_position"] <= 1)
        self.assertIn(out["rating"]["label"], ("Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"))
        self.assertEqual(len(out["trends"]), 3)
        self.assertLess(out["week52"]["low"], out["week52"]["high"])
        self.assertEqual(len(out["rows"]), quote_chart.RANGES["3M"])
        for part in ('class="qc"', "qc-hit", "qc-rsi", "qc-vup", "20-day average", "200-day average"):
            self.assertIn(part, out["chart"])

    def test_every_daily_range_draws_the_right_number_of_bars(self):
        for key in ("1M", "3M", "6M", "1Y"):
            out = run_build(FakeFeed(self.daily), key)
            self.assertEqual(len(out["rows"]), quote_chart.RANGES[key], key)

    def test_the_snapshot_supplies_bid_ask_and_the_day_range(self):
        snap = {"symbol": "VTI", "price": 123.45, "trade_time": "x", "bid": 123.4, "ask": 123.5, "bid_size": 1, "ask_size": 2,
                "day": {"o": 120.0, "h": 125.0, "l": 119.0, "c": 123.45, "v": 777}, "prev_day": {"o": 1, "h": 2, "l": 1, "c": 121.0, "v": 1}}
        q = run_build(FakeFeed(self.daily, snapshot=snap))["quote"]
        self.assertEqual((q["bid"], q["ask"], q["volume"]), (123.4, 123.5, 777))
        self.assertAlmostEqual(q["change"], 2.45)
        self.assertAlmostEqual(q["day_position"], (123.45 - 119.0) / 6.0)

    def test_one_day_view_uses_the_latest_regular_session_only(self):
        # 5-minute bars: an earlier day, then the latest day with pre-market and after-hours bars that must be dropped
        ny_open = datetime(2026, 10, 2, 13, 30, tzinfo=timezone.utc)      # 9:30 New York (EDT)
        day = [ny_open + timedelta(minutes=5 * i) for i in range(78)]
        pre = [ny_open - timedelta(minutes=5 * (i + 1)) for i in range(5)]
        old = [ny_open - timedelta(days=1) + timedelta(minutes=5 * i) for i in range(20)]
        stamps = sorted(old + pre + day)
        intraday = []
        for i, t in enumerate(stamps):
            c = 50 + i * 0.01
            intraday.append({"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "o": c, "h": c + 0.05, "l": c - 0.05, "c": c, "v": 1000.0})
        out = run_build(FakeFeed(self.daily, intraday=intraday), "1D")
        self.assertEqual(out["range"], "1D")
        self.assertEqual(len(out["rows"]), 78)
        self.assertEqual(out["rows"][0]["t"], "Oct 2, 9:30 AM")
        self.assertIn("VWAP", out["chart"])
        self.assertNotIn("200-day", out["chart"])

    def test_one_day_view_falls_back_to_a_month_when_there_are_no_intraday_bars(self):
        out = run_build(FakeFeed(self.daily, intraday=[]), "1D")
        self.assertEqual(out["range"], "1M")

    def test_no_history_is_an_error_the_person_can_read(self):
        with self.assertRaises(alpaca.AlpacaError) as ctx:
            run_build(FakeFeed([]))
        self.assertIn("VTI", str(ctx.exception))

    def test_a_short_history_still_draws_but_says_the_rating_needs_more(self):
        out = run_build(FakeFeed(make_bars([10 + i * 0.1 for i in range(20)])))
        self.assertEqual(out["rating"]["label"], "Not enough history")
        self.assertIn("qc-hit", out["chart"])

    def test_the_chart_helper_handles_too_few_rows(self):
        self.assertIn("Not enough price data", quote_chart.chart_html([], "daily"))


class TestQuoteRoute(unittest.TestCase):
    def test_the_route_is_read_only_and_needs_no_arming_even_for_live(self):
        calls = []

        def fake_build(symbol, keys, range_key):
            calls.append((symbol, keys, range_key))
            return {"symbol": symbol}

        with patch("source.common.secrets_store.get_alpaca_keys", return_value=("K", "S")) as keys, \
                patch.object(quote_chart, "build_quote", fake_build), \
                patch("source.common.db.live_trading.is_armed", return_value=False):
            out = trading_api.handle("/api/alpaca/quote", {"mode": "live", "symbol": "AAPL", "range": "1Y"})
        self.assertEqual(out, {"symbol": "AAPL"})
        self.assertEqual(calls, [("AAPL", ("K", "S"), "1Y")])
        keys.assert_called_once_with(mode="live")

    def test_a_data_error_reaches_the_person_as_a_message(self):
        with patch("source.common.secrets_store.get_alpaca_keys", return_value=("K", "S")), \
                patch.object(quote_chart, "build_quote", side_effect=alpaca.AlpacaError("No price history was found for ZZZZ.")):
            with self.assertRaises(ValueError) as ctx:
                trading_api.handle("/api/alpaca/quote", {"mode": "paper", "symbol": "ZZZZ"})
        self.assertIn("ZZZZ", str(ctx.exception))

    def test_a_rejected_key_is_explained(self):
        fake = FakeAlpaca({("GET", "data.alpaca.markets/v2/stocks/VTI/bars"): http_error(401)})
        with self.assertRaises(alpaca.AlpacaError) as ctx:
            alpaca.get_bars("VTI", KEYS, start="2025-01-01T00:00:00Z", urlopen=fake)
        self.assertIn("rejected the keys", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
