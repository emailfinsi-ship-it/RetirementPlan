"""LIVE (real-money) Alpaca trading: the arming switch, the limits, the audit
log, and the route logic in source.webapp.trading_api. Every Alpaca call goes
through a fake urlopen; no test touches the network or a real account."""

import unittest
from datetime import date, datetime
from unittest.mock import patch

from source.collector import alpaca
from source.common import db, secrets_store
from source.webapp import trading_api
from source.webapp.pages.trading import _render_trading_page
from tests.test_alpaca import FakeAlpaca, http_error, trade_route
from tests.testing_utils import FakeKeyring, TempConfigTestCase

LT = db.live_trading
ORDER = {"mode": "live", "symbol": "VTI", "side": "buy", "qty": "4", "type": "market"}   # $1,000 at the fake's $250


class TestArmingAndLimits(TempConfigTestCase):
    def test_live_trading_is_off_by_default(self):
        self.assertFalse(LT.is_armed())
        self.assertIsNone(LT.armed_until())

    def test_the_phrase_must_be_typed_exactly(self):
        for wrong in ("", "trade real money please", "yes", "TRADE REAL"):
            with self.assertRaises(ValueError):
                LT.arm(wrong)
        self.assertFalse(LT.is_armed())
        LT.arm(" TRADE REAL MONEY ")
        self.assertTrue(LT.is_armed())

    def test_arming_expires_by_itself_and_can_be_switched_off(self):
        LT.arm(LT.CONFIRM_PHRASE, now=1_000.0)
        self.assertTrue(LT.is_armed(now=1_000.0 + LT.ARM_HOURS * 3600 - 1))
        self.assertFalse(LT.is_armed(now=1_000.0 + LT.ARM_HOURS * 3600 + 1))
        LT.arm(LT.CONFIRM_PHRASE)
        LT.disarm()
        self.assertFalse(LT.is_armed())

    def test_limits_default_and_validate(self):
        self.assertEqual((LT.per_order_limit(), LT.daily_limit()), (LT.DEFAULT_PER_ORDER, LT.DEFAULT_DAILY))
        LT.set_limits(500, 1500)
        self.assertEqual((LT.per_order_limit(), LT.daily_limit()), (500.0, 1500.0))
        for per_order, daily in ((0, 100), (100, 0), (LT.PER_ORDER_CEILING + 1, LT.DAILY_CEILING),
                                 (100, LT.DAILY_CEILING + 1), (2000, 1000), ("x", 5), (None, None)):
            with self.subTest(per_order=per_order, daily=daily):
                with self.assertRaises(ValueError):
                    LT.set_limits(per_order, daily)
        self.assertEqual((LT.per_order_limit(), LT.daily_limit()), (500.0, 1500.0))

    def test_a_tampered_limit_is_held_to_the_ceiling(self):
        db.set_meta("live_trading_per_order_limit", "9999999")
        db.set_meta("live_trading_daily_limit", "9999999")
        self.assertEqual((LT.per_order_limit(), LT.daily_limit()), (LT.PER_ORDER_CEILING, LT.DAILY_CEILING))
        db.set_meta("live_trading_daily_limit", "garbage")
        self.assertEqual(LT.daily_limit(), LT.DEFAULT_DAILY)

    def test_the_daily_total_counts_only_today(self):
        LT.log_live_order(symbol="VTI", side="buy", qty=1, order_type="market", estimate=300.0, order_id="a", status="accepted",
                          placed_at=datetime(2026, 10, 1, 10, 0))
        LT.log_live_order(symbol="BND", side="buy", qty=2, order_type="market", estimate=200.0, order_id="b", status="accepted",
                          placed_at=datetime(2026, 10, 2, 10, 0))
        self.assertEqual(LT.spent_today(today=date(2026, 10, 1)), 300.0)
        self.assertEqual(LT.spent_today(today=date(2026, 10, 2)), 200.0)
        self.assertEqual(LT.spent_today(today=date(2026, 10, 3)), 0.0)
        LT.set_limits(500, 1000)
        self.assertEqual(LT.daily_remaining(today=date(2026, 10, 1)), 700.0)
        self.assertEqual([r["order_id"] for r in LT.list_live_orders()], ["b", "a"])


class TradingApiCase(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        self.keyring = FakeKeyring()
        patches = [
            patch("keyring.get_password", self.keyring.get_password),
            patch("keyring.set_password", self.keyring.set_password),
            patch("keyring.delete_password", self.keyring.delete_password),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        secrets_store.clear_vault_cache()
        self.addCleanup(secrets_store.clear_vault_cache)
        alpaca._previews.clear()
        self.fake = FakeAlpaca({
            ("GET", "api.alpaca.markets/v2/account"): {"status": "ACTIVE", "equity": "50000", "cash": "10000"},
            ("GET", "api.alpaca.markets/v2/positions"): [],
            ("GET", "api.alpaca.markets/v2/orders"): [],
            ("GET", "paper-api.alpaca.markets/v2/account"): {"status": "ACTIVE", "equity": "100000"},
            ("POST", "api.alpaca.markets/v2/orders"): {"id": "LIVE-1", "status": "accepted"},
            ("POST", "paper-api.alpaca.markets/v2/orders"): {"id": "PAPER-1", "status": "accepted"},
            **trade_route(250.0),
        })
        p = patch("urllib.request.urlopen", self.fake)
        p.start()
        self.addCleanup(p.stop)

    def handle(self, path, payload):
        return trading_api.handle(path, payload)

    def connect_live(self):
        self.handle("/api/alpaca-keys", {"mode": "live", "key_id": "AKLIVE", "secret": "S"})

    def arm(self):
        self.handle("/api/alpaca/live/arm", {"phrase": LT.CONFIRM_PHRASE})

    def posts(self):
        return [c for c in self.fake.calls if c["method"] == "POST"]


class TestLiveRoutes(TradingApiCase):
    def test_live_keys_are_checked_against_the_live_host_then_saved_separately(self):
        self.connect_live()
        self.assertTrue(secrets_store.has_alpaca_keys(mode="live"))
        self.assertFalse(secrets_store.has_alpaca_keys(mode="paper"))
        self.assertEqual(self.fake.calls[0]["url"], "https://api.alpaca.markets/v2/account")

    def test_wrong_live_keys_are_not_saved(self):
        self.fake.routes[("GET", "api.alpaca.markets/v2/account")] = http_error(401)
        with self.assertRaises(ValueError):
            self.connect_live()
        self.assertFalse(secrets_store.has_alpaca_keys(mode="live"))

    def test_arming_needs_saved_keys_and_the_phrase(self):
        with self.assertRaises(ValueError) as ctx:
            self.arm()
        self.assertIn("live Alpaca keys", str(ctx.exception))
        self.connect_live()
        with self.assertRaises(ValueError):
            self.handle("/api/alpaca/live/arm", {"phrase": "please"})
        self.assertFalse(LT.is_armed())
        self.arm()
        self.assertTrue(LT.is_armed())

    def test_nothing_live_can_be_previewed_or_sent_while_switched_off(self):
        self.connect_live()
        with self.assertRaises(ValueError) as ctx:
            self.handle("/api/alpaca/preview", ORDER)
        self.assertIn("switched off", str(ctx.exception))
        with self.assertRaises(ValueError):
            self.handle("/api/alpaca/order", {"mode": "live", "token": "x", "confirm_symbol": "VTI"})
        self.assertFalse(self.posts())

    def test_a_live_order_needs_preview_then_the_symbol_typed_again(self):
        self.connect_live()
        self.arm()
        preview = self.handle("/api/alpaca/preview", ORDER)
        self.assertEqual((preview["mode"], preview["estimate"]), ("live", 1000.0))
        for wrong in ({}, {"confirm_symbol": ""}, {"confirm_symbol": "BND"}):
            with self.assertRaises(ValueError) as ctx:
                self.handle("/api/alpaca/order", {"mode": "live", "token": preview["token"], **wrong})
            self.assertIn("type its symbol (VTI)", str(ctx.exception))
        self.assertFalse(self.posts())                     # wrong confirmations sent nothing...
        placed = self.handle("/api/alpaca/order", {"mode": "live", "token": preview["token"], "confirm_symbol": " vti "})
        self.assertEqual((placed["id"], placed["mode"]), ("LIVE-1", "live"))   # ...and did not use the token up
        post = self.posts()[0]
        self.assertEqual(post["url"], "https://api.alpaca.markets/v2/orders")
        self.assertEqual(post["headers"]["Apca-api-key-id"], "AKLIVE")
        with self.assertRaises(ValueError):
            self.handle("/api/alpaca/order", {"mode": "live", "token": preview["token"], "confirm_symbol": "VTI"})   # replay
        self.assertEqual(len(self.posts()), 1)

    def test_a_sent_order_is_written_to_the_audit_log_and_counts_toward_the_daily_limit(self):
        self.connect_live()
        self.arm()
        LT.set_limits(1_200, 1_500)
        preview = self.handle("/api/alpaca/preview", ORDER)
        self.handle("/api/alpaca/order", {"mode": "live", "token": preview["token"], "confirm_symbol": "VTI"})
        log = LT.list_live_orders()
        self.assertEqual([(r["symbol"], r["side"], r["qty"], r["estimate"], r["order_id"]) for r in log],
                         [("VTI", "buy", 4, 1000.0, "LIVE-1")])
        self.assertEqual(LT.spent_today(), 1000.0)
        with self.assertRaises(ValueError) as ctx:        # $1,000 more would pass $1,500 for the day
            self.handle("/api/alpaca/preview", ORDER)
        self.assertIn("today's trading limit", str(ctx.exception))
        small = self.handle("/api/alpaca/preview", {**ORDER, "qty": "2"})
        self.assertEqual(small["estimate"], 500.0)

    def test_the_daily_limit_is_rechecked_when_sending(self):
        self.connect_live()
        self.arm()
        LT.set_limits(1_200, 1_500)
        first = self.handle("/api/alpaca/preview", ORDER)
        second = self.handle("/api/alpaca/preview", ORDER)       # both fit on their own
        self.handle("/api/alpaca/order", {"mode": "live", "token": first["token"], "confirm_symbol": "VTI"})
        with self.assertRaises(ValueError) as ctx:
            self.handle("/api/alpaca/order", {"mode": "live", "token": second["token"], "confirm_symbol": "VTI"})
        self.assertIn("over today's trading limit", str(ctx.exception))
        self.assertEqual(len(self.posts()), 1)

    def test_the_per_order_limit_is_enforced(self):
        self.connect_live()
        self.arm()
        LT.set_limits(500, 5_000)
        with self.assertRaises(ValueError) as ctx:
            self.handle("/api/alpaca/preview", ORDER)             # $1,000 > $500
        self.assertIn("limited to $500", str(ctx.exception))

    def test_a_failed_send_is_not_logged(self):
        self.connect_live()
        self.arm()
        self.fake.routes[("POST", "api.alpaca.markets/v2/orders")] = http_error(422, "insufficient buying power")
        preview = self.handle("/api/alpaca/preview", ORDER)
        with self.assertRaises(ValueError) as ctx:
            self.handle("/api/alpaca/order", {"mode": "live", "token": preview["token"], "confirm_symbol": "VTI"})
        self.assertIn("insufficient buying power", str(ctx.exception))
        self.assertEqual(LT.list_live_orders(), [])
        self.assertEqual(LT.spent_today(), 0.0)

    def test_switching_off_stops_new_previews_and_removing_the_keys_switches_it_off(self):
        self.connect_live()
        self.arm()
        self.handle("/api/alpaca/live/disarm", {})
        with self.assertRaises(ValueError):
            self.handle("/api/alpaca/preview", ORDER)
        self.arm()
        self.handle("/api/alpaca-keys/delete", {"mode": "live"})
        self.assertFalse(LT.is_armed())
        self.assertFalse(secrets_store.has_alpaca_keys(mode="live"))

    def test_a_live_token_cannot_be_used_on_the_practice_account_or_the_reverse(self):
        self.connect_live()
        self.handle("/api/alpaca-keys", {"key_id": "PKPAPER", "secret": "S"})
        self.arm()
        live = self.handle("/api/alpaca/preview", ORDER)
        with self.assertRaises(ValueError):
            self.handle("/api/alpaca/order", {"token": live["token"]})        # paper route, live token
        paper = self.handle("/api/alpaca/preview", {**ORDER, "mode": "paper"})
        with self.assertRaises(ValueError):
            self.handle("/api/alpaca/order", {"mode": "live", "token": paper["token"], "confirm_symbol": "VTI"})
        self.assertFalse(self.posts())

    def test_practice_orders_need_no_arming_and_are_not_logged_as_real_money(self):
        self.handle("/api/alpaca-keys", {"key_id": "PKPAPER", "secret": "S"})
        preview = self.handle("/api/alpaca/preview", {**ORDER, "mode": "paper"})
        placed = self.handle("/api/alpaca/order", {"mode": "paper", "token": preview["token"]})
        self.assertEqual(placed["id"], "PAPER-1")
        self.assertTrue(self.posts()[0]["url"].startswith("https://paper-api.alpaca.markets/"))
        self.assertEqual(LT.list_live_orders(), [])

    def test_cancelling_never_needs_the_switch(self):
        self.connect_live()
        oid = "61e69015-8549-4bfd-b9c3-01e75843f47d"
        self.fake.routes[("DELETE", f"api.alpaca.markets/v2/orders/{oid}")] = {}
        self.handle("/api/alpaca/cancel", {"mode": "live", "id": oid})
        self.assertEqual(self.fake.calls[-1]["url"], f"https://api.alpaca.markets/v2/orders/{oid}")

    def test_unknown_mode_is_refused(self):
        with self.assertRaises(ValueError):
            self.handle("/api/alpaca/preview", {**ORDER, "mode": "sandbox"})


class TestLivePage(TradingApiCase):
    def test_without_live_keys_it_asks_for_them_with_a_real_money_warning(self):
        body = _render_trading_page("live")
        self.assertIn("Connect your Alpaca live account", body)
        self.assertIn("Real money", body)
        self.assertIn("mode: 'live'", body)

    def test_switched_off_the_page_shows_the_switch_and_no_order_form(self):
        self.connect_live()
        body = _render_trading_page("live")
        self.assertIn("Live trading is <strong>off</strong>", body)
        self.assertIn(LT.CONFIRM_PHRASE, body)
        self.assertIn("Turn live trading on above to place an order", body)
        self.assertNotIn('id="ticket"', body)
        self.assertIn("$50,000.00", body)                       # the account itself is still readable

    def test_switched_on_the_page_shows_a_red_banner_the_off_button_and_the_ticket(self):
        self.connect_live()
        self.arm()
        body = _render_trading_page("live")
        self.assertIn("LIVE TRADING IS ON", body)
        self.assertIn("Turn live trading OFF now", body)
        self.assertIn('id="ticket"', body)
        self.assertIn("Place a real-money order", body)
        self.assertIn("Send REAL order", body)

    def test_the_audit_log_is_listed(self):
        self.connect_live()
        LT.log_live_order(symbol="VTI", side="buy", qty=4, order_type="market", estimate=1000.0, order_id="x", status="accepted")
        body = _render_trading_page("live")
        self.assertIn("Real-money orders sent from this app", body)
        self.assertIn("$1,000.00", body)

    def test_a_sent_order_that_has_since_filled_shows_filled_not_pending_new(self):
        self.connect_live()
        LT.log_live_order(symbol="AAPL", side="buy", qty=1, order_type="market", estimate=343.59, order_id="o-1", status="pending_new")
        LT.log_live_order(symbol="VTI", side="buy", qty=1, order_type="limit", estimate=300.0, order_id="o-2", status="pending_new")
        self.fake.routes[("GET", "api.alpaca.markets/v2/orders")] = [
            {"id": "o-1", "symbol": "AAPL", "side": "buy", "qty": "1", "type": "market", "status": "filled",
             "filled_qty": "1", "filled_avg_price": "343.62"},
            {"id": "o-2", "symbol": "VTI", "side": "buy", "qty": "1", "type": "limit", "status": "new"},
        ]
        body = _render_trading_page("live")
        log = body.split("Real-money orders sent from this app")[1]
        self.assertIn("filled: 1 at $343.62", log)
        self.assertNotIn("pending new", log)
        statuses = {r["order_id"]: r["status"] for r in LT.list_live_orders()}
        self.assertEqual(statuses, {"o-1": "filled", "o-2": "new"})            # saved, so it stays right offline too

    def test_sync_statuses_only_touches_orders_it_knows(self):
        LT.log_live_order(symbol="VTI", side="buy", qty=1, order_type="market", estimate=1.0, order_id="a", status="pending_new")
        self.assertEqual(LT.sync_statuses([{"id": "a", "status": "filled"}, {"id": "zzz", "status": "filled"}, {"id": "", "status": "x"}]), 1)
        self.assertEqual(LT.sync_statuses([{"id": "a", "status": "filled"}]), 0)
        self.assertEqual(LT.list_live_orders()[0]["status"], "filled")

    def test_each_position_has_a_sell_button_that_fills_the_order_form(self):
        self.connect_live()
        self.arm()
        self.fake.routes[("GET", "api.alpaca.markets/v2/positions")] = [
            {"symbol": "AAPL", "qty": "3", "avg_entry_price": "300", "current_price": "344.5", "market_value": "1033.5",
             "unrealized_pl": "133.5", "unrealized_plpc": "0.148"},
            {"symbol": "TINY", "qty": "0.4", "avg_entry_price": "10", "current_price": "11", "market_value": "4.4",
             "unrealized_pl": "0.4", "unrealized_plpc": "0.1"},
        ]
        body = _render_trading_page("live")
        self.assertIn("onclick=\"sellPosition('AAPL', 3)\"", body)
        self.assertNotIn("sellPosition('TINY'", body)                # under one whole share: nothing the form can sell
        self.assertIn("function sellPosition(", body)
        self.assertIn('id="ticket-note"', body)

    def test_each_position_gets_a_rating_cell_and_the_hover_script(self):
        self.connect_live()
        self.fake.routes[("GET", "api.alpaca.markets/v2/positions")] = [
            {"symbol": "AAPL", "qty": "3", "avg_entry_price": "300", "current_price": "344.5", "market_value": "1033.5",
             "unrealized_pl": "133.5", "unrealized_plpc": "0.148"}]
        body = _render_trading_page("live")
        self.assertIn('<td data-rate-sym="AAPL">', body)
        self.assertIn("<th>Rating</th>", body)
        self.assertIn("/api/ratings", body)
        self.assertIn("data-ctip-val", body)                         # the symbol's hover box is filled by the script
        self.assertLess(body.index('data-rate-sym="AAPL"'), body.index("sellPosition('AAPL', 3)"))   # rating sits before Sell

    def test_the_sell_button_on_a_switched_off_live_page_points_to_the_switch(self):
        self.connect_live()
        self.fake.routes[("GET", "api.alpaca.markets/v2/positions")] = [
            {"symbol": "AAPL", "qty": "1", "avg_entry_price": "300", "current_price": "344.5", "market_value": "344.5",
             "unrealized_pl": "44.5", "unrealized_plpc": "0.148"}]
        body = _render_trading_page("live")
        self.assertIn("sellPosition('AAPL', 1)", body)
        self.assertIn("turn live trading on above", body)
        self.assertNotIn('id="ticket"', body)

    def test_the_practice_page_says_it_is_play_money_and_links_to_live(self):
        body = _render_trading_page("paper")
        self.assertIn("Practice only", body)
        self.assertIn('href="/trading-live.html"', body)
        self.assertNotIn("LIVE TRADING IS ON", body)


if __name__ == "__main__":
    unittest.main()
