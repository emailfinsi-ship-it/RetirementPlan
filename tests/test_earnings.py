"""Next-earnings dates and the "Earnings this week" panel (source.collector.earnings,
pages/earnings_panel.py, /api/earnings*). Nothing here touches the network: the Yahoo
lookup is replaced by a fake."""

import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from source.collector import earnings
from source.common import db
from source.webapp import trading_api
from source.webapp.pages import earnings_panel
from tests.testing_utils import TempConfigTestCase

TODAY = date(2026, 10, 28)          # a Wednesday
NOW = datetime(2026, 10, 28, 9, 0, 0)


class Fetcher:
    def __init__(self, table):
        self.table, self.calls = table, []

    def __call__(self, symbol, today=None):
        self.calls.append(symbol)
        value = self.table.get(symbol, None)
        if isinstance(value, Exception):
            raise value
        return value


class TestParseCalendar(unittest.TestCase):
    def test_takes_the_first_upcoming_date(self):
        cal = {"Earnings Date": [date(2026, 10, 1), date(2026, 11, 6), date(2026, 11, 3)]}
        self.assertEqual(earnings.parse_calendar(cal, TODAY), "2026-11-03")

    def test_today_counts_and_datetimes_and_text_are_read(self):
        self.assertEqual(earnings.parse_calendar({"Earnings Date": [datetime(2026, 10, 28, 16, 0)]}, TODAY), "2026-10-28")
        self.assertEqual(earnings.parse_calendar({"Earnings Date": ["2026-12-01"]}, TODAY), "2026-12-01")

    def test_nothing_upcoming_or_no_calendar_is_none(self):
        self.assertIsNone(earnings.parse_calendar({"Earnings Date": [date(2026, 1, 1)]}, TODAY))
        self.assertIsNone(earnings.parse_calendar({}, TODAY))
        self.assertIsNone(earnings.parse_calendar(None, TODAY))

    def test_week_runs_monday_to_sunday(self):
        self.assertEqual(earnings.week_bounds(TODAY), (date(2026, 10, 26), date(2026, 11, 1)))
        self.assertEqual(earnings.week_bounds(date(2026, 11, 1)), (date(2026, 10, 26), date(2026, 11, 1)))


class TestLookup(TempConfigTestCase):
    def test_fetches_then_serves_from_the_cache(self):
        f = Fetcher({"AAPL": "2026-10-30", "VTI": None})
        out = earnings.lookup(["aapl", "VTI"], today=TODAY, now=NOW, fetch=f)
        self.assertEqual(out["items"]["AAPL"]["date"], "2026-10-30")
        self.assertEqual(out["items"]["AAPL"]["days"], 2)
        self.assertTrue(out["items"]["VTI"]["known"])
        self.assertIsNone(out["items"]["VTI"]["date"])
        self.assertEqual(sorted(f.calls), ["AAPL", "VTI"])
        again = earnings.lookup(["AAPL", "VTI"], today=TODAY, now=NOW + timedelta(hours=1), fetch=f)
        self.assertEqual(sorted(f.calls), ["AAPL", "VTI"])           # nothing re-fetched within the day
        self.assertEqual(again["items"]["AAPL"]["date"], "2026-10-30")
        self.assertEqual(db.earnings_db.get_many(["AAPL"])["AAPL"]["date"], "2026-10-30")

    def test_entries_older_than_half_a_day_are_asked_again(self):
        db.earnings_db.save("AAPL", "2026-10-30", now=NOW - timedelta(hours=13))
        db.earnings_db.save("MSFT", "2026-10-30", now=NOW - timedelta(hours=1))
        f = Fetcher({"AAPL": "2026-11-02", "MSFT": "2026-11-02"})
        out = earnings.lookup(["AAPL", "MSFT"], today=TODAY, now=NOW, fetch=f)
        self.assertEqual(f.calls, ["AAPL"])
        self.assertEqual(out["items"]["AAPL"]["date"], "2026-11-02")
        self.assertEqual(out["items"]["MSFT"]["date"], "2026-10-30")

    def test_an_entry_looked_up_before_its_report_day_is_refreshed_once_the_day_has_passed(self):
        db.earnings_db.save("AAPL", "2026-10-28", now=datetime(2026, 10, 28, 23, 0))
        f = Fetcher({"AAPL": "2027-01-27"})
        out = earnings.lookup(["AAPL"], today=date(2026, 10, 29), now=datetime(2026, 10, 29, 1, 0), fetch=f)
        self.assertEqual(f.calls, ["AAPL"])
        self.assertEqual(out["items"]["AAPL"]["date"], "2027-01-27")
        self.assertEqual(out["items"]["AAPL"]["last_date"], "2026-10-28")      # the one just gone by is kept

    def test_a_failed_lookup_keeps_the_old_date_and_reports_why(self):
        db.earnings_db.save("AAPL", "2026-11-05", now=NOW - timedelta(hours=20))
        f = Fetcher({"AAPL": earnings.EarningsUnavailable("offline"), "NEW": earnings.EarningsUnavailable("offline")})
        out = earnings.lookup(["AAPL", "NEW"], today=TODAY, now=NOW, fetch=f)
        self.assertEqual(out["items"]["AAPL"]["date"], "2026-11-05")      # last known date still shown
        self.assertFalse(out["items"]["NEW"]["known"])                    # never looked up successfully
        self.assertEqual(out["error"], "offline")

    def test_an_unexpected_error_for_one_ticker_does_not_break_the_rest(self):
        f = Fetcher({"BAD": RuntimeError("boom"), "OK": "2026-10-29"})
        out = earnings.lookup(["BAD", "OK"], today=TODAY, now=NOW, fetch=f)
        self.assertEqual(out["items"]["OK"]["date"], "2026-10-29")
        self.assertFalse(out["items"]["BAD"]["known"])

    def test_missing_library_is_reported_not_raised(self):
        with patch.dict("sys.modules", {"yfinance": None}):
            with self.assertRaises(earnings.EarningsUnavailable):
                earnings.fetch_next("AAPL", TODAY)


class TestThisWeek(TempConfigTestCase):
    def test_only_tickers_reporting_monday_to_sunday_are_listed_in_date_order(self):
        f = Fetcher({"AAA": "2026-10-30", "BBB": "2026-10-26", "CCC": "2026-11-02", "DDD": "2026-11-01", "EEE": None})
        universe = {s: ["watchlist"] for s in ("AAA", "BBB", "CCC", "DDD", "EEE")}
        out = earnings.this_week(universe, today=TODAY, now=NOW, fetch=f)
        self.assertEqual([i["symbol"] for i in out["items"]], ["BBB", "AAA", "DDD"])
        self.assertEqual(out["items"][1]["weekday"], "Friday")
        self.assertEqual((out["start"], out["end"]), ("2026-10-26", "2026-11-01"))
        self.assertEqual(out["checked"], 5)
        self.assertEqual(out["items"][0]["days"], -2)          # Monday's report has already happened

    def test_a_company_that_reported_earlier_this_week_stays_listed(self):
        db.earnings_db.save("AAA", "2026-10-26", now=NOW - timedelta(hours=30))
        db.earnings_db.save("AAA", "2027-01-20", now=NOW - timedelta(hours=1))   # Yahoo has moved on to next quarter
        out = earnings.this_week({"AAA": ["holding"]}, today=TODAY, now=NOW, fetch=Fetcher({}))
        self.assertEqual([(i["symbol"], i["date"]) for i in out["items"]], [("AAA", "2026-10-26")])


class TestPanelAndRoutes(TempConfigTestCase):
    def test_universe_is_the_watchlist_plus_held_stocks_only(self):
        db.watchlist.add("AAPL, VTI")
        db.upsert_plaid_item(item_key="k", plaid_item_id="i", institution_id="x", institution_name="Fidelity",
                             products=["investments"], environment="production", linked_at="2026-10-01T00:00:00")
        db.upsert_plaid_account(item_key="k", account={"account_id": "a", "name": "B", "official_name": "B", "type": "investment",
                                                         "subtype": "brokerage", "mask": "1",
                                                         "balances": {"current": 1.0, "available": None, "iso_currency_code": "USD"}})
        for i, (sym, typ) in enumerate((("NVDA", "equity"), ("AAPL", "equity"), ("BND", "etf"), ("USD", "cash"))):
            db.upsert_plaid_holding(item_key="k", holding={"account_id": "a", "security_id": f"s{i}", "ticker_symbol": sym,
                                                           "security_name": sym, "security_type": typ, "quantity": 1,
                                                           "institution_price": 1, "institution_value": 1, "cost_basis": 1,
                                                           "iso_currency_code": "USD"})
        self.assertEqual(earnings_panel.week_universe(),
                         {"AAPL": ["watchlist", "holding"], "VTI": ["watchlist"], "NVDA": ["holding"]})

    def test_week_route_lists_reporters_with_names(self):
        db.watchlist.add("AAPL")
        db.watchlist.remember_name("AAPL", "Apple Inc.")
        monday = earnings.week_bounds()[0]
        f = Fetcher({"AAPL": (monday + timedelta(days=1)).isoformat()})
        with patch.object(earnings, "fetch_next", f):
            out = trading_api.handle("/api/earnings/week", {})
        self.assertEqual([i["symbol"] for i in out["items"]], ["AAPL"])
        self.assertEqual(out["items"][0]["name"], "Apple Inc.")
        self.assertEqual(out["items"][0]["sources"], ["watchlist"])
        self.assertEqual(out["today"], date.today().isoformat())

    def test_week_route_with_nothing_to_check_is_empty(self):
        out = trading_api.handle("/api/earnings/week", {})
        self.assertEqual((out["items"], out["checked"]), ([], 0))

    def test_symbol_route_skips_bad_tickers(self):
        f = Fetcher({"AAPL": (date.today() + timedelta(days=3)).isoformat()})
        with patch.object(earnings, "fetch_next", f):
            out = trading_api.handle("/api/earnings", {"symbols": ["aapl", "$$$"]})
        self.assertEqual([i["symbol"] for i in out["items"]], ["AAPL"])
        self.assertEqual(out["items"][0]["days"], 3)

    def test_routes_are_owner_only_routes(self):
        self.assertIn("/api/earnings", trading_api.ROUTES)
        self.assertIn("/api/earnings/week", trading_api.ROUTES)


if __name__ == "__main__":
    unittest.main()
