"""The Screener: the plain-English parser, the filters, the engine on made-up price histories, background jobs, the API and the
data readers (all faked: no network)."""

import time
import unittest
from unittest.mock import patch

import pandas as pd

from source.collector import etrade, yahoo
from source.screener import engine, filters, jobs, parser, universe
from source.webapp import screener_api


def bars_from(closes, vols=None, spread=0.01):
    return [{"t": f"2026-01-{i % 28 + 1:02d}T05:00:00Z", "o": c, "h": c * (1 + spread), "l": c * (1 - spread), "c": c,
             "v": (vols[i] if vols else 1000.0)} for i, c in enumerate(closes)]


def rising_then_cross(n=120):
    """A long decline then a sharp rise: MACD crosses up recently."""
    closes = [100 - i * 0.4 for i in range(n - 12)]
    last = closes[-1]
    closes += [last + (i + 1) * 1.2 for i in range(12)]
    return bars_from(closes)


class TestParser(unittest.TestCase):
    def p(self, text):
        return parser.parse(text)["filters"]

    def test_macd_rsi_and_etfs(self):
        f = self.p("ETFs where MACD crossed up in the last 3 days and RSI is under 40")
        self.assertEqual(f["assets"], ["etf"])
        self.assertEqual(f["macd"], {"cross": "bullish", "within_days": 3})
        self.assertEqual(f["rsi"], {"min": None, "max": 40.0})

    def test_direction_words_are_judged_inside_the_macd_clause(self):
        f = self.p("tech stocks with MACD bullish crossover in the last 3 days, RSI below 35")
        self.assertEqual(f["macd"]["cross"], "bullish")
        self.assertEqual(f["sectors"], ["Information Technology"])

    def test_swing_in_percent_and_dollars(self):
        f = self.p("stocks up at least 5% this week")
        self.assertEqual(f["swing"], [{"kind": "move", "window": "1w", "direction": "up", "pct": 5.0, "usd": None}])
        f = self.p("Health Care and Energy stocks that moved down $20 in a month")
        self.assertEqual(f["sectors"], ["Health Care", "Energy"])
        self.assertEqual((f["swing"][0]["usd"], f["swing"][0]["window"], f["swing"][0]["direction"]), (20.0, "1m", "down"))

    def test_day_range_and_either_way(self):
        self.assertEqual(self.p("stocks that swing more than 5% in a day")["swing"][0]["kind"], "range")
        self.assertEqual(self.p("ETFs up or down 3% this week")["swing"][0]["direction"], "either")

    def test_rsi_forms(self):
        self.assertEqual(self.p("rsi between 50 and 70")["rsi"], {"min": 50.0, "max": 70.0})
        self.assertEqual(self.p("oversold stocks")["rsi"], {"min": None, "max": 30.0})
        self.assertEqual(self.p("rsi over 60")["rsi"], {"min": 60.0, "max": None})

    def test_put_call(self):
        self.assertEqual(self.p("put/call volume ratio above 1.2")["put_call"], {"min": 1.2, "max": None})
        self.assertEqual(self.p("more calls than puts")["put_call"], {"min": None, "max": 0.7})
        self.assertEqual(self.p("more puts than calls")["put_call"], {"min": 1.2, "max": None})

    def test_price_is_not_confused_with_a_swing_and_other_filters(self):
        f = self.p("AI stocks near 52-week high, price under $200, volume 2x, above the 50-day average")
        self.assertEqual(f["price"], {"min": None, "max": 200.0})
        self.assertEqual(f["swing"], [])
        self.assertEqual(f["theme"], "ai")
        self.assertEqual(f["near_52w"]["side"], "high")
        self.assertEqual(f["volume_ratio_min"], 2.0)
        self.assertEqual(f["sma"], {"window": 50, "relation": "above"})

    def test_typed_tickers_and_where_to_scan(self):
        f = self.p("among AAPL, MSFT and BRK.B show MACD bearish cross")
        self.assertEqual(f["tickers"], ["AAPL", "MSFT", "BRK.B"])
        self.assertIn("custom", f["universe"])
        self.assertEqual(self.p("my holdings with rsi < 30")["universe"], ["holdings"])
        self.assertEqual(self.p("ETFs please")["tickers"], [])           # "ETFs" is not a ticker

    def test_nothing_recognised(self):
        out = parser.parse("hello there")
        self.assertEqual(out["understood"], [])


class TestFilters(unittest.TestCase):
    def test_bad_numbers_are_refused_in_plain_words(self):
        with self.assertRaises(ValueError):
            filters.normalize({"rsi": {"min": 80, "max": 20}})
        with self.assertRaises(ValueError):
            filters.normalize({"rsi": {"min": "abc"}})

    def test_normalize_is_safe_on_junk(self):
        f = filters.normalize({"sectors": ["tech", "Energy"], "assets": ["bond"], "swing": [{"pct": "5", "window": "zz"}], "limit": 9999 and 99})
        self.assertEqual(f["sectors"], ["Energy"])
        self.assertEqual(f["assets"], ["stock", "etf"])
        self.assertEqual(f["swing"][0]["window"], "1w")

    def test_describe_reads_back(self):
        f = filters.normalize({"macd": {"cross": "bullish", "within_days": 3}, "rsi": {"max": 40}, "swing": [{"pct": 5, "window": "1w", "direction": "up"}]})
        text = " | ".join(filters.describe(f))
        self.assertIn("MACD bullish crossover in the last 3 days", text)
        self.assertIn("RSI below 40", text)
        self.assertIn("up at least 5% over 1 week", text)


class TestEngine(unittest.TestCase):
    def test_metrics_need_history(self):
        self.assertIsNone(engine.metrics(bars_from([100.0] * 10)))

    def test_a_recent_bullish_cross_with_a_big_week_matches(self):
        m = engine.metrics(rising_then_cross())
        self.assertEqual(m["macd_cross"], "bullish")
        f = filters.normalize({"macd": {"cross": "bullish", "within_days": 12}, "swing": [{"pct": 3, "window": "1w", "direction": "up"}]})
        why = engine.technical_match(m, f)
        self.assertTrue(why and any("crossover" in w for w in why))
        down = filters.normalize({"swing": [{"pct": 3, "window": "1w", "direction": "down"}]})
        self.assertIsNone(engine.technical_match(m, down))

    def test_dollar_swing_and_day_range(self):
        closes = [100.0] * 60 + [100 + i for i in range(1, 6)]
        m = engine.metrics(bars_from(closes, spread=0.03))
        self.assertIsNotNone(engine.technical_match(m, filters.normalize({"swing": [{"usd": 4, "window": "1w", "direction": "up"}]})))
        self.assertIsNone(engine.technical_match(m, filters.normalize({"swing": [{"usd": 40, "window": "1w", "direction": "up"}]})))
        self.assertIsNotNone(engine.technical_match(m, filters.normalize({"swing": [{"kind": "range", "pct": 5}]})))

    def test_scan_filters_sectors_and_asset_types_before_fetching(self):
        f = filters.normalize({"sectors": ["Energy"], "assets": ["stock"]})
        cands = engine.candidates(f)
        self.assertTrue(cands and all(e["sector"] == "Energy" and e["type"] == "stock" for e in cands))
        etfs = engine.candidates(filters.normalize({"assets": ["etf"], "sectors": ["Bonds"]}))
        self.assertTrue(etfs and all(e["type"] == "etf" for e in etfs))

    def test_scan_with_fake_readers_and_put_call(self):
        f = filters.normalize({"tickers": ["AAA", "BBB", "CCC"], "universe": ["custom"], "put_call": {"max": 0.7}, "rsi": {"min": 0, "max": 100}})
        series = {"AAA": rising_then_cross(), "BBB": rising_then_cross(), "CCC": bars_from([100.0] * 10)}
        opts = {"AAA": {"call_volume": 900.0, "put_volume": 300.0, "ratio": 0.33}, "BBB": {"call_volume": 100.0, "put_volume": 400.0, "ratio": 4.0}}
        seen = []
        res = engine.scan(f, load_bars=lambda syms, progress=None: {s: series.get(s, []) for s in syms},
                          load_options=lambda syms: (seen.append(list(syms)) or opts))
        self.assertEqual([r["symbol"] for r in res["rows"]], ["AAA"])           # BBB's put/call is too high, CCC has too little history
        self.assertEqual(res["no_data"], 1)
        self.assertEqual(sorted(seen[0]), ["AAA", "BBB"])                       # option chains are read only for names that passed
        self.assertIn("put/call volume 0.33", res["rows"][0]["why"])

    def test_themes_pull_in_named_tickers_and_industry_words(self):
        f = filters.normalize({"theme": "semiconductors"})
        syms = {e["symbol"] for e in engine.candidates(f)}
        self.assertIn("NVDA", syms)
        self.assertNotIn("XOM", syms)


class TestJobsAndApi(unittest.TestCase):
    def test_a_job_reports_progress_and_the_result(self):
        def fake_scan(f, progress=None, cancelled=lambda: False):
            progress(1, 2, "Reading prices")
            return {"rows": [], "scanned": 2, "no_data": 0, "matched": 0}
        job = jobs.start(filters.normalize({}), scan=fake_scan)
        for _ in range(100):
            st = jobs.status(job)
            if st["state"] != "running":
                break
            time.sleep(0.02)
        self.assertEqual(st["state"], "done")
        self.assertEqual(st["result"]["scanned"], 2)
        with self.assertRaises(ValueError):
            jobs.status("nope")

    def test_a_failing_scan_is_reported_not_raised(self):
        def boom(f, progress=None, cancelled=lambda: False):
            raise RuntimeError("Yahoo down")
        job = jobs.start(filters.normalize({}), scan=boom)
        for _ in range(100):
            st = jobs.status(job)
            if st["state"] != "running":
                break
            time.sleep(0.02)
        self.assertEqual((st["state"], st["error"]), ("error", "Yahoo down"))

    @patch.object(engine, "_alpaca_keys", return_value=None)
    def test_routes(self, _keys):
        cfg = screener_api.handle("/api/screener/config", {})
        self.assertIn("Energy", cfg["sectors"])
        self.assertGreater(cfg["universe_size"], 500)
        out = screener_api.handle("/api/screener/parse", {"text": "oversold tech stocks"})
        self.assertEqual(out["filters"]["rsi"]["max"], 30.0)
        with self.assertRaises(ValueError):
            screener_api.handle("/api/screener/parse", {"text": " "})
        with self.assertRaises(ValueError):
            screener_api.handle("/api/screener/run", {"filters": {"sectors": ["Energy"], "assets": ["etf"], "universe": ["custom"], "tickers": []}})

    @patch.object(engine, "_alpaca_keys", return_value=None)
    def test_the_page_and_the_tab_exist(self, _keys):
        from source.common import auth_store
        from source.webapp.pages.screener_page import _render_screener_page
        with patch.object(auth_store, "is_password_set", return_value=False):
            self._check_page(_render_screener_page)

    def _check_page(self, render):
        from source.webapp.render_helpers import shell
        page = render()
        self.assertIn('id="sc-form"', page)
        self.assertIn("/api/screener/run", page)
        self.assertIn('name="sector"', page)
        self.assertTrue(any(href == "screener.html" for group in shell.NAV_GROUPS for href, _ in group))


class FakeYF:
    """yf.download / Ticker with canned data."""

    def __init__(self):
        idx = pd.date_range("2026-01-01", periods=40, freq="B", tz="America/New_York")

        def frame(base):
            return pd.DataFrame({"Open": base, "High": base + 1, "Low": base - 1, "Close": base, "Volume": 1000}, index=idx)
        self.frames = {"AAA": frame(10.0), "BBB": frame(20.0)}
        self.downloads = []

    def download(self, tickers, **kw):
        self.downloads.append(tickers)
        names = tickers.split()
        if len(names) == 1:
            return self.frames[names[0]]
        return pd.concat({n: self.frames[n] for n in names if n in self.frames}, axis=1)

    def Ticker(self, sym):
        outer = self

        class T:
            options = ["2099-01-15"]

            def option_chain(self, exp):
                class C:
                    calls = pd.DataFrame({"volume": [100.0, 50.0], "openInterest": [10, 10]})
                    puts = pd.DataFrame({"volume": [30.0, float("nan")], "openInterest": [5, 5]})
                return C()
        return T()


class TestReaders(unittest.TestCase):
    def test_yahoo_batch_bars_split_per_symbol(self):
        yf = FakeYF()
        with patch.object(yahoo, "_yf", lambda: yf):
            got = yahoo.get_bars_batch(["AAA", "BBB", "ZZZ"], start="2026-01-01T00:00:00Z")
        self.assertEqual(len(got["AAA"]), 40)
        self.assertEqual(got["BBB"][0]["c"], 20.0)
        self.assertEqual(got["ZZZ"], [])

    def test_yahoo_option_volume_sums_calls_and_puts(self):
        with patch.object(yahoo, "_yf", lambda: FakeYF()), patch.object(yahoo, "datetime") as dt:
            from datetime import datetime as real
            dt.now.return_value = real(2026, 10, 30)
            dt.strptime = real.strptime
            got = yahoo.get_option_volume("AAA", max_days=100000)
        self.assertEqual((got["call_volume"], got["put_volume"]), (150.0, 30.0))
        self.assertAlmostEqual(got["ratio"], 0.2)

    def test_etrade_option_volume(self):
        class C:
            def json(self, method, path, query=None, body=None):
                if path.endswith("optionexpiredate"):
                    return {"OptionExpireDateResponse": {"ExpirationDate": [{"year": 2099, "month": 1, "day": 15}]}}
                return {"OptionChainResponse": {"OptionPair": [{"Call": {"volume": 200, "openInterest": 1}, "Put": {"volume": 50, "openInterest": 2}},
                                                              {"Call": {"volume": 100}, "Put": {"volume": 50}}]}}
        got = etrade.option_volume(C(), "AAA", max_days=10**6)
        self.assertEqual((got["call_volume"], got["put_volume"], got["ratio"]), (300.0, 100.0, 100.0 / 300.0))

    def test_bars_come_from_alpaca_first_and_yahoo_fills_the_gaps(self):
        from source.collector import alpaca
        engine._BARS.clear()
        good = bars_from([100 + i * 0.1 for i in range(60)])
        with patch.object(engine, "_alpaca_keys", return_value=("k", "s")), \
                patch.object(alpaca, "get_bars_multi", return_value={"AAA": good, "BBB": []}), \
                patch.object(yahoo, "get_bars_batch", return_value={"BBB": good}) as y:
            out = engine.default_load_bars(["AAA", "BBB"])
        self.assertEqual(len(out["AAA"]), 60)
        self.assertEqual(len(out["BBB"]), 60)
        self.assertEqual(y.call_args.args[0], ["BBB"])
        self.assertEqual(engine.SOURCES, {"alpaca": 1, "yahoo": 1})
        engine._BARS.clear()


if __name__ == "__main__":
    unittest.main()
