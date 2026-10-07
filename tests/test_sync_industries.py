"""sync_industries never touches the real network in tests -- _fetch_industry
and the yfinance import are mocked/monkeypatched throughout."""

import unittest
from unittest.mock import patch

from source.collector import sync_industries
from source.common import db
from tests.testing_utils import TempConfigTestCase


def _seed_holding(security_id, ticker, name, security_type, *, item_key="schwab", account_id="acc_brokerage"):
    db.upsert_plaid_holding(item_key=item_key, holding={
        "account_id": account_id, "security_id": security_id, "ticker_symbol": ticker,
        "security_name": name, "security_type": security_type, "quantity": 1,
        "institution_price": 100.0, "institution_value": 100.0, "cost_basis": 100.0,
        "iso_currency_code": "USD",
    })


class TestSyncMissingIndustries(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        db.upsert_plaid_item(
            item_key="schwab", plaid_item_id="p2", institution_id="ins_schwab",
            institution_name="Charles Schwab", products=["investments"], environment="sandbox",
            linked_at="2026-01-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="schwab", account={
            "account_id": "acc_brokerage", "name": "Brokerage", "type": "investment",
            "subtype": "brokerage", "mask": "9021", "balances": {"current": 42_000},
        })
        _seed_holding("sec_aapl", "AAPL", "Apple Inc", "equity")
        _seed_holding("sec_nvda", "NVDA", "NVIDIA Corp", "equity")
        _seed_holding("sec_bad", "BADTICKER", "Unknown Co", "equity")
        _seed_holding("sec_voo", "VOO", "Vanguard S&P 500 ETF", "etf")

    def test_classifies_only_equities_and_caches_results(self):
        industries_by_ticker = {"AAPL": "Consumer Electronics", "NVDA": "Semiconductors"}  # BADTICKER absent -> unresolved

        with patch.object(sync_industries, "_fetch_industry", side_effect=lambda t: industries_by_ticker.get(t)), \
             patch.dict("sys.modules", {"yfinance": object()}):
            result = sync_industries.sync_missing_industries()

        self.assertEqual(result["checked"], 3)  # AAPL, NVDA, BADTICKER -- VOO is an ETF, never a candidate
        self.assertEqual(result["classified"], 2)
        self.assertEqual(result.get("unresolved_tickers"), ["BADTICKER"])
        self.assertEqual(
            db.get_security_industries(),
            # BADTICKER is cached too, with industry='' -- a failed lookup
            # is remembered just like a successful one, so it isn't
            # re-fetched (and re-failed) on every future sync. See
            # sync_industries.py's module docstring.
            {"sec_aapl": "Consumer Electronics", "sec_nvda": "Semiconductors", "sec_bad": ""},
        )

    def test_a_previously_failed_lookup_is_not_refetched(self):
        db.set_security_industry(security_id="sec_bad", ticker="BADTICKER", industry="", updated_at="2026-09-13T00:00:00+00:00")

        calls = []

        def fake_fetch(ticker):
            calls.append(ticker)
            return {"AAPL": "Consumer Electronics", "NVDA": "Semiconductors"}.get(ticker)

        with patch.object(sync_industries, "_fetch_industry", side_effect=fake_fetch), \
             patch.dict("sys.modules", {"yfinance": object()}):
            result = sync_industries.sync_missing_industries()

        self.assertNotIn("BADTICKER", calls)  # cached failure -- never re-fetched
        self.assertEqual(result["checked"], 2)  # only AAPL, NVDA -- BADTICKER already cached

    def test_already_classified_security_is_not_refetched(self):
        db.set_security_industry(security_id="sec_aapl", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")

        calls = []

        def fake_fetch(ticker):
            calls.append(ticker)
            return "Semiconductors" if ticker == "NVDA" else None

        with patch.object(sync_industries, "_fetch_industry", side_effect=fake_fetch), \
             patch.dict("sys.modules", {"yfinance": object()}):
            sync_industries.sync_missing_industries()

        self.assertNotIn("AAPL", calls)  # already cached -- never re-fetched
        self.assertIn("NVDA", calls)

    def test_no_pending_tickers_short_circuits_without_importing_yfinance(self):
        for sec_id, ticker in [("sec_aapl", "AAPL"), ("sec_nvda", "NVDA"), ("sec_bad", "BADTICKER")]:
            db.set_security_industry(security_id=sec_id, ticker=ticker, industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")

        # No mock for _fetch_industry or yfinance -- if the function tried
        # to import yfinance here (not installed in this test env), it
        # would raise.
        result = sync_industries.sync_missing_industries()
        self.assertEqual(result, {"checked": 0, "classified": 0, "skipped_no_ticker": 0})

    def test_yfinance_not_installed_fails_soft(self):
        import builtins
        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "yfinance":
                raise ImportError("no module named yfinance")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=blocked_import):
            result = sync_industries.sync_missing_industries()
        self.assertEqual(result["classified"], 0)
        self.assertEqual(result.get("error"), "yfinance not installed")


class TestYfinanceWarningFilter(unittest.TestCase):
    def test_pandas_utcnow_deprecation_noise_from_yfinance_is_silenced(self):
        # Run in a fresh interpreter: the unittest runner installs its own
        # "default" warning filter ahead of anything a module sets up.
        import pathlib
        import subprocess
        import sys

        root = str(pathlib.Path(__file__).resolve().parent.parent)
        code = (
            "import warnings\n"
            "import source.collector.sync_industries\n"
            "warnings.warn('Timestamp.utcnow is deprecated and will be removed', DeprecationWarning)\n"
            "warnings.warn('some other deprecation', DeprecationWarning)\n"
        )
        result = subprocess.run(
            [sys.executable, "-W", "default", "-c", code], cwd=root, capture_output=True, text=True, timeout=60,
        )
        self.assertNotIn("utcnow", result.stderr)
        self.assertIn("some other deprecation", result.stderr)  # only that one message is filtered


if __name__ == "__main__":
    unittest.main()
