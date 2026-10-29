"""Extended-hours and overnight orders, and the pre-market / after-hours price. No network."""

import unittest
from unittest.mock import patch

from source.collector import alpaca, etrade, ibkr, market_data, yahoo
from source.collector.broker_common import BrokerError
from tests.test_alpaca import FakeAlpaca, KEYS, trade_route

LIMIT = {"symbol": "VTI", "side": "buy", "qty": "10", "type": "limit", "limit_price": "250", "time_in_force": "gtc"}


class TestSessionRules(unittest.TestCase):
    def test_regular_is_the_default(self):
        self.assertEqual(alpaca.clean_order(LIMIT)["session"], "regular")

    def test_outside_regular_hours_needs_a_limit_and_is_day_only(self):
        clean = alpaca.clean_order({**LIMIT, "session": "extended"})
        self.assertEqual((clean["session"], clean["time_in_force"]), ("extended", "day"))     # "until cancelled" does not carry over
        with self.assertRaises(alpaca.AlpacaError) as ctx:
            alpaca.clean_order({**LIMIT, "type": "market", "session": "extended"})
        self.assertIn("limit", str(ctx.exception).lower())
        with self.assertRaises(alpaca.AlpacaError):
            alpaca.clean_order({**LIMIT, "session": "midnight"})

    def test_each_broker_only_accepts_the_sessions_its_connection_can_send(self):
        with self.assertRaises(BrokerError):
            etrade.bc.clean_order({**LIMIT, "session": "overnight"}, sessions=etrade.SESSIONS)
        self.assertEqual(etrade.bc.clean_order({**LIMIT, "session": "extended"}, sessions=etrade.SESSIONS)["session"], "extended")
        self.assertEqual(ibkr.bc.clean_order({**LIMIT, "session": "overnight"}, sessions=ibkr.SESSIONS)["session"], "overnight")


class TestOrdersCarryTheSession(unittest.TestCase):
    def setUp(self):
        alpaca._previews.clear()

    def test_alpaca_sends_extended_hours_only_when_asked(self):
        routes = {**trade_route(250.0), ("POST", "api.alpaca.markets/v2/orders"): {"id": "L-1", "status": "accepted"}}
        for session, expect in (("regular", None), ("extended", True)):
            fake = FakeAlpaca(routes)
            token = alpaca.preview_order({**LIMIT, "session": session}, KEYS, mode="live", urlopen=fake)["token"]
            alpaca.place_order(token, KEYS, mode="live", urlopen=fake)
            body = [c for c in fake.calls if c["method"] == "POST"][0]["body"]
            self.assertEqual(body.get("extended_hours"), expect)
            if expect:
                self.assertEqual((body["type"], body["time_in_force"]), ("limit", "day"))

    def test_etrade_marks_the_market_session(self):
        regular = etrade._order_request(alpaca.clean_order(LIMIT), "c")["Order"][0]
        ext = etrade._order_request(alpaca.clean_order({**LIMIT, "session": "extended"}), "c")["Order"][0]
        self.assertEqual(regular["marketSession"], "REGULAR")
        self.assertEqual((ext["marketSession"], ext["orderTerm"], ext["priceType"]), ("EXTENDED", "GOOD_FOR_DAY", "LIMIT"))

    def test_ibkr_uses_outside_rth_for_extended_and_ovt_for_overnight(self):
        def body(session):
            return ibkr._order_body("U1", alpaca.clean_order({**LIMIT, "session": session}), 123)["orders"][0]
        self.assertFalse(body("regular")["outsideRTH"])
        ext = body("extended")
        self.assertTrue(ext["outsideRTH"])
        self.assertEqual(ext["tif"], "DAY")
        night = body("overnight")
        self.assertEqual(night["tif"], "OVT")
        self.assertEqual(night["orderType"], "LMT")


class TestExtendedPrice(unittest.TestCase):
    def test_after_hours_price_and_change(self):
        info = {"marketState": "POST", "postMarketPrice": 101.5, "postMarketChange": 1.5, "postMarketChangePercent": 1.5, "regularMarketPrice": 100.0}

        class T:
            def __init__(self, sym):
                self.info = info
        with patch.object(yahoo, "_ticker", lambda sym: T(sym)):
            got = yahoo.get_extended(["aapl"])
        self.assertEqual(got["AAPL"]["label"], "After hours")
        self.assertEqual(got["AAPL"]["price"], 101.5)

    def test_nothing_while_the_market_is_open_and_nothing_when_yahoo_is_off(self):
        class T:
            info = {"marketState": "REGULAR", "postMarketPrice": 5.0}
        with patch.object(yahoo, "_ticker", lambda sym: T()):
            self.assertEqual(yahoo.get_extended(["AAPL"]), {})
        self.assertEqual(market_data.get_extended(["AAPL"]), {})          # off under the test runner


class TestPages(unittest.TestCase):
    def test_tickets_have_a_session_choice(self):
        from source.webapp.pages import broker_page, trading
        self.assertIn('name="session"', trading._TICKET_FORM)
        self.assertIn("session: form.session.value", trading._TICKET_JS)
        self.assertIn('name="session"', broker_page._TICKET)
        self.assertIn("session: f.session.value", broker_page._JS)
        self.assertIn("option[value=overnight]').remove()", broker_page._JS)      # E*TRADE's connection has no overnight session
        self.assertIn("/api/extended", broker_page._JS)


if __name__ == "__main__":
    unittest.main()
