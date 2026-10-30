"""The safety checks shown with an order preview: pure rules, and that each broker's preview route carries them."""

import unittest
from datetime import date
from unittest.mock import patch

from source.collector import trade_checks as tc
from source.webapp import trade_context


def order(**kw):
    base = {"symbol": "AAPL", "side": "buy", "qty": 10, "type": "market", "limit_price": None, "session": "regular", "time_in_force": "day"}
    return {**base, **kw}


def texts(res, level=None):
    return " | ".join(c["text"] for c in res["checks"] if level in (None, c["level"]))


class TestRules(unittest.TestCase):
    def test_a_large_order_and_a_new_big_position_are_flagged(self):
        res = tc.evaluate(order(), estimate=3000, price=300, market_price=300, account_value=10000, held_qty=0)
        self.assertEqual(round(res["pct_of_account"], 2), 0.30)
        self.assertIn("30% of the account", texts(res, "warn"))
        self.assertIn("would be about 30%", texts(res, "warn"))
        small = tc.evaluate(order(qty=1), estimate=300, price=300, market_price=300, account_value=100000, held_qty=0)
        self.assertEqual(small["checks"], [])

    def test_buying_more_of_a_stock_you_hold_counts_what_you_already_own(self):
        res = tc.evaluate(order(qty=2), estimate=600, price=300, market_price=300, account_value=10000, held_qty=5)
        self.assertIn("would be about 21%", texts(res, "warn"))     # (5 held + 2 bought) * 300 = 2100 of 10,000

    def test_selling_more_than_held_warns_and_selling_all_says_so(self):
        over = tc.evaluate(order(side="sell", qty=12), estimate=3600, price=300, market_price=300, account_value=100000, held_qty=10)
        self.assertIn("hold 10 shares of AAPL here but this sells 12", texts(over, "warn"))
        whole = tc.evaluate(order(side="sell", qty=10), estimate=3000, price=300, market_price=300, account_value=100000, held_qty=10)
        self.assertIn("sells your whole AAPL position", texts(whole, "info"))

    def test_selling_below_cost_mentions_wash_sales(self):
        res = tc.evaluate(order(side="sell", qty=5), estimate=1500, price=300, market_price=300, account_value=100000, held_qty=10, held_avg_cost=400)
        self.assertIn("below your average cost of $400", texts(res, "info"))
        self.assertIn("wash sale", texts(res))
        up = tc.evaluate(order(side="sell", qty=5), estimate=1500, price=300, market_price=300, account_value=100000, held_qty=10, held_avg_cost=100)
        self.assertNotIn("wash", texts(up))

    def test_buying_back_something_sold_from_this_app_lately(self):
        res = tc.evaluate(order(), estimate=300, price=30, market_price=30, account_value=100000, held_qty=0, recent_sells=[{"symbol": "AAPL", "days_ago": 12}])
        self.assertIn("sold AAPL from this app 12 days ago", texts(res, "info"))
        old = tc.evaluate(order(), estimate=300, price=30, market_price=30, account_value=100000, held_qty=0, recent_sells=[{"symbol": "AAPL", "days_ago": 45}])
        self.assertNotIn("sold AAPL", texts(old))

    def test_wide_spread_extended_hours_and_far_limits(self):
        wide = tc.evaluate(order(), estimate=100, price=10, bid=9.90, ask=10.10, account_value=1e6)
        self.assertIn("gap between the buy price", texts(wide, "warn"))
        tight = tc.evaluate(order(), estimate=100, price=10, bid=9.999, ask=10.001, account_value=1e6)
        self.assertNotIn("gap", texts(tight))
        ext = tc.evaluate(order(type="limit", limit_price=10, session="extended"), estimate=100, price=10, market_price=10, account_value=1e6)
        self.assertIn("Extended hours", texts(ext, "info"))
        generous = tc.evaluate(order(type="limit", limit_price=105), estimate=1050, price=105, market_price=100, account_value=1e6)
        self.assertIn("5.0% above the current price", texts(generous, "warn"))
        stale = tc.evaluate(order(type="limit", limit_price=80), estimate=800, price=80, market_price=100, account_value=1e6)
        self.assertIn("may not fill", texts(stale, "info"))
        sell_low = tc.evaluate(order(side="sell", type="limit", limit_price=95), estimate=950, price=95, market_price=100, account_value=1e6, held_qty=10)
        self.assertIn("below the current price", texts(sell_low, "warn"))

    def test_warnings_sort_before_info_and_unknowns_are_skipped(self):
        res = tc.evaluate(order(side="sell", qty=10), estimate=3000, price=300, market_price=300, account_value=10000, held_qty=10)
        self.assertEqual([c["level"] for c in res["checks"]], sorted((c["level"] for c in res["checks"]), key=lambda l: l != "warn"))
        nothing = tc.evaluate(order(), estimate=100, price=10)
        self.assertEqual((nothing["checks"], nothing["pct_of_account"]), ([], None))

    def test_recent_sales_come_from_the_app_order_log(self):
        log = [{"symbol": "aapl", "side": "sell", "status": "filled", "placed_at": "2026-10-01T10:00:00"},
               {"symbol": "MSFT", "side": "sell", "status": "canceled", "placed_at": "2026-10-02T10:00:00"},
               {"symbol": "NVDA", "side": "buy", "status": "filled", "placed_at": "2026-10-02T10:00:00"},
               {"symbol": "OLD", "side": "sell", "status": "filled", "placed_at": "2026-06-01T10:00:00"}]
        self.assertEqual(tc.recent_sells(log, today=date(2026, 10, 6)), [{"symbol": "AAPL", "days_ago": 5}])


class TestContext(unittest.TestCase):
    def test_attach_never_breaks_a_preview(self):
        res = {"order": order(), "estimate": 300.0, "price": 30.0}
        with patch.object(trade_context.db.live_trading, "list_live_orders", side_effect=RuntimeError("db down")):
            out = trade_context.attach(res, account_value=1000)
        self.assertEqual(out["checks"], [])
        self.assertIs(out, res)

    def test_attach_uses_held_shares_and_cost_from_positions(self):
        res = {"order": order(side="sell", qty=12), "estimate": 3600.0, "price": 300.0}
        with patch.object(trade_context.db.live_trading, "list_live_orders", return_value=[]):
            out = trade_context.attach(res, account_value=100000, positions=[{"symbol": "AAPL", "qty": 10, "avg_cost": 400}], market_price=300)
        self.assertIn("this sells 12", " ".join(c["text"] for c in out["checks"]))

    def test_the_broker_helper_reads_value_and_positions_from_the_broker(self):
        class Mod:
            __name__ = "source.collector.ibkr"
            @staticmethod
            def summary(c, a): return {"value": 10000}
            @staticmethod
            def positions(c, a): return [{"symbol": "AAPL", "qty": 1, "avg_cost": 100}]
        res = {"order": order(qty=10), "estimate": 3000.0, "price": 300.0}
        with patch.object(trade_context.db.live_trading, "list_live_orders", return_value=[]):
            out = trade_context.for_broker(Mod, object(), "A1", res)
        self.assertEqual(round(out["pct_of_account"], 2), 0.30)
        self.assertIn("30% of the account", " ".join(c["text"] for c in out["checks"]))


if __name__ == "__main__":
    unittest.main()


from datetime import datetime, timedelta

from source.common import db
from tests.testing_utils import TempConfigTestCase


class TestOrderHistory(TempConfigTestCase):
    def log(self, symbol, side, broker, days_ago=0, status="filled"):
        when = datetime.now() - timedelta(days=days_ago)
        db.live_trading.log_live_order(symbol=symbol, side=side, qty=3, order_type="market", estimate=300.0, order_id=f"id-{symbol}",
                                       status=status, broker=broker, placed_at=when)

    def test_history_lists_every_broker_newest_first_and_filters_by_days(self):
        from source.webapp import trading_api
        self.log("AAPL", "buy", "alpaca", 0)
        self.log("KO", "sell", "etrade", 3, "EXECUTED")
        self.log("OLD", "buy", "ibkr", 90)
        out = trading_api.handle("/api/orders/history", {"days": 30})
        # newest first by log id: the order they were logged is AAPL, KO, OLD -> reversed
        self.assertEqual([o["symbol"] for o in out["items"]], ["KO", "AAPL"])
        self.assertEqual({o["broker"] for o in out["items"]}, {"alpaca", "etrade"})
        self.assertEqual(len(trading_api.handle("/api/orders/history", {"days": 0})["items"]), 3)
        self.assertEqual([o["symbol"] for o in trading_api.handle("/api/orders/history", {"days": 1})["items"]], ["AAPL"])
        self.assertEqual(out["today"]["spent"], 300.0)

    def test_the_page_and_the_tab_exist_and_are_owner_only(self):
        from source.webapp import dashboard
        from source.webapp.pages.orders_page import _BODY
        from source.webapp.render_helpers import shell
        self.assertIn("/api/orders/history", _BODY)
        self.assertTrue(any(href == "orders.html" for group in shell.NAV_GROUPS for href, _ in group))
        self.assertIn("/orders.html", dashboard._OWNER_ONLY_PAGES)
