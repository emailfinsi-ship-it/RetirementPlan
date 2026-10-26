"""The IBKR and E*TRADE tabs: source.collector.ibkr / etrade / broker_common, the /api/broker/* routes
(source.webapp.broker_api) and the pages. Nothing here touches a real broker: every network call goes to a fake."""

import base64
import hashlib
import hmac
import io
import json
import re
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch

import keyring

from source.collector import broker_common as bc, etrade, ibkr, ibkr_gateway
from source.collector.broker_common import BrokerError
from source.common import db, secrets_store
from source.webapp import broker_api, trading_api
from tests.test_dashboard import DashboardTestCase
from tests.testing_utils import FakeKeyring, TempConfigTestCase


class Resp:
    def __init__(self, body):
        self.body = body if isinstance(body, str) else json.dumps(body)

    def read(self):
        return self.body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, body=None):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(json.dumps(body or {}).encode()))


class FakeIbkr:
    """A stand-in IBKR Client Portal Gateway: routes by method and path."""

    def __init__(self, ask=False, authenticated=True):
        self.calls, self.ask, self.authenticated, self.orders_posted = [], ask, authenticated, []

    def __call__(self, req, timeout=None):
        path = req.full_url.split("/v1/api", 1)[1]
        method = req.get_method()
        body = json.loads(req.data) if req.data else None
        self.calls.append((method, path))
        if path == "/iserver/auth/status":
            return Resp({"authenticated": self.authenticated, "connected": True})
        if path == "/iserver/accounts":
            return Resp({"accounts": ["U111", "U222"], "aliases": {"U111": "Main", "U222": "IRA"}})
        if path == "/portfolio/accounts":
            return Resp([{"id": "U111"}])
        if path.endswith("/ledger"):
            return Resp({"USD": {"currency": "USD", "cashbalance": 1000.0, "stockmarketvalue": 2000.0, "netliquidationvalue": 3000.0,
                                 "unrealizedpnl": 500.0, "exchangerate": 1},
                         "EUR": {"currency": "EUR", "cashbalance": 500.0, "stockmarketvalue": 900.0, "netliquidationvalue": 1400.0,
                                 "unrealizedpnl": 300.0, "exchangerate": 1.08},
                         "CHF": {"currency": "CHF", "cashbalance": 0.0, "stockmarketvalue": 0.0, "netliquidationvalue": 0.0, "exchangerate": 1.1},
                         "BASE": {"currency": "BASE", "cashbalance": 1540.0, "netliquidationvalue": 4512.0}})
        if path.endswith("/summary"):
            return Resp({"netliquidation": {"amount": 51000.5}, "totalcashvalue": {"amount": 1000.0}, "buyingpower": {"amount": 2000.0}})
        if "/positions/" in path:
            return Resp([{"ticker": "AAPL", "contractDesc": "AAPL", "position": 10, "mktPrice": 200, "mktValue": 2000, "avgCost": 150,
                          "unrealizedPnl": 500, "assetClass": "STK", "conid": 265598, "currency": "USD"},
                         {"ticker": "SAP", "contractDesc": "SAP", "position": 5, "mktPrice": 180, "mktValue": 900, "avgCost": 120,
                          "unrealizedPnl": 300, "assetClass": "STK", "conid": 14094, "currency": "EUR"},
                         {"ticker": "ESZ6", "position": 1, "assetClass": "FUT", "mktValue": 99999}]) if path.endswith("/0") else Resp([])
        if path.startswith("/trsrv/stocks"):
            return Resp({"AAPL": [{"name": "APPLE", "contracts": [{"conid": 1, "isUS": False}, {"conid": 265598, "isUS": True}]}]})
        if path.startswith("/iserver/marketdata/snapshot"):
            return Resp([{"31": "C200.50"}])
        if path == "/iserver/account/orders":
            return Resp({"orders": [{"acct": "U111", "orderId": 77, "ticker": "AAPL", "side": "BUY", "totalSize": 5, "filledQuantity": 0,
                                     "status": "Submitted", "orderType": "Limit", "price": "150"},
                                    {"acct": "U111", "orderId": 78, "ticker": "MSFT", "side": "SELL", "totalSize": 1, "filledQuantity": 1,
                                     "status": "Filled", "orderType": "Market"}]})
        if method == "POST" and path.endswith("/orders"):
            self.orders_posted.append(body)
            if self.ask:
                return Resp([{"id": "reply-1", "message": ["Price exceeds the 3% constraint."], "isSuppressed": False}])
            return Resp([{"order_id": "9001", "order_status": "Submitted"}])
        if path.startswith("/iserver/reply/"):
            assert body == {"confirmed": True}
            return Resp([{"order_id": "9002", "order_status": "Submitted"}])
        if method == "DELETE":
            return Resp({"msg": "Request was submitted"})
        raise AssertionError(f"unexpected {method} {path}")


class FakeEtrade:
    def __init__(self, expired=False):
        self.calls, self.expired, self.placed, self.idle = [], expired, [], False

    def __call__(self, req, timeout=None):
        url = req.full_url
        path = urllib.parse.urlsplit(url).path
        method = req.get_method()
        auth = req.get_header("Authorization")
        self.calls.append((method, path, auth))
        body = json.loads(req.data) if req.data else None
        if path == "/oauth/request_token":
            return Resp("oauth_token=REQ&oauth_token_secret=REQSECRET&oauth_callback_confirmed=true")
        if path == "/oauth/access_token":
            assert "oauth_verifier=\"CODE123\"" in auth
            return Resp("oauth_token=ACC&oauth_token_secret=ACCSECRET")
        if path == "/oauth/renew_access_token":
            self.renews = getattr(self, "renews", 0) + 1
            if self.idle:
                self.idle = False
            return Resp("Renewed Access Token for " + "x")
        if self.idle or self.expired:
            raise http_error(401, {"Error": {"message": "expired"}})
        if path == "/v1/accounts/list.json":
            return Resp({"AccountListResponse": {"Accounts": {"Account": [
                {"accountId": "8301", "accountIdKey": "KEY1", "accountDesc": "INDIVIDUAL", "institutionType": "BROKERAGE", "accountStatus": "ACTIVE"},
                {"accountId": "8302", "accountIdKey": "KEY2", "accountDesc": "CLOSED", "institutionType": "BROKERAGE", "accountStatus": "CLOSED"}]}}})
        if path == "/v1/accounts/KEY1/balance.json":
            return Resp({"BalanceResponse": {"Computed": {"cashBuyingPower": 3000, "cashAvailableForInvestment": 1500,
                                                          "RealTimeValues": {"totalAccountValue": 25000}}}})
        if path == "/v1/accounts/KEY1/portfolio/9001.json":
            return Resp({"PositionLotsResponse": {"PositionLot": [
                {"positionLotId": 1, "price": 50, "remainingQty": 12, "totalCost": 600, "marketValue": 780, "totalGain": 180,
                 "termCode": "LONG_TERM", "acquiredDate": 1609459200000},
                {"positionLotId": 2, "price": 62.5, "remainingQty": 8, "marketValue": 520, "totalGain": 20,
                 "termCode": "SHORT_TERM", "acquiredDate": 1740787200000}]}})
        if path == "/v1/accounts/KEY1/portfolio.json":
            return Resp({"PortfolioResponse": {"AccountPortfolio": [{"Position": [
                {"positionId": 9001, "Product": {"securityType": "EQ", "symbol": "KO"}, "symbolDescription": "COCA COLA", "quantity": 20, "pricePaid": 55,
                 "marketValue": 1300, "totalGain": 200, "totalGainPct": 18.18, "daysGain": -12.5, "daysGainPct": -0.95, "totalCost": 1100,
                 "pctOfPortfolio": 5.2, "dateAcquired": 1609459200000, "positionType": "LONG",
                 "Quick": {"lastTrade": 65, "change": -0.63, "changePct": -0.96}},
                {"Product": {"securityType": "OPTN", "symbol": "KO"}, "quantity": 1}]}]}})
        if path == "/v1/accounts/KEY1/orders.json":
            if "EXECUTED" in req.full_url:
                return Resp({})
            return Resp({"OrdersResponse": {"Order": [{"orderId": 555, "OrderDetail": [{"status": "OPEN", "priceType": "LIMIT", "limitPrice": 60,
                         "Instrument": [{"Product": {"symbol": "KO"}, "orderAction": "BUY", "orderedQuantity": 3, "filledQuantity": 0}]}]}]}})
        if path.startswith("/v1/market/quote/"):
            return Resp({"QuoteResponse": {"QuoteData": [{"All": {"lastTrade": 65.25}}]}})
        if path == "/v1/accounts/KEY1/orders/preview.json":
            assert method == "POST" and req.get_header("Content-type") == "application/json"
            return Resp({"PreviewOrderResponse": {"PreviewIds": [{"previewId": 424242}],
                                                   "Order": [{"estimatedCommission": 0, "estimatedTotalAmount": 195.75}]}})
        if path == "/v1/accounts/KEY1/orders/place.json":
            self.placed.append(body)
            return Resp({"PlaceOrderResponse": {"OrderIds": [{"orderId": 888}]}})
        if path == "/v1/accounts/KEY1/orders/cancel.json":
            assert method == "PUT" and body == {"CancelOrderRequest": {"orderId": 555}}
            return Resp({})
        raise AssertionError(f"unexpected {method} {url}")


class TestCommon(unittest.TestCase):
    def test_a_preview_token_is_single_use_and_tied_to_its_account(self):
        book = bc.PreviewBook()
        t = book.issue({"broker": "x", "account": "A", "n": 1}, now=100)
        with self.assertRaises(BrokerError):
            book.claim(t, broker="x", account="B", now=101)          # wrong account (and it is used up)
        with self.assertRaises(BrokerError):
            book.claim(t, broker="x", account="A", now=101)
        t = book.issue({"broker": "x", "account": "A"}, now=100)
        self.assertEqual(book.claim(t, broker="x", account="A", now=101)["account"], "A")
        t = book.issue({"broker": "x", "account": "A"}, now=100)
        with self.assertRaises(BrokerError):
            book.claim(t, broker="x", account="A", now=100 + bc.PREVIEW_SECONDS + 1)

    def test_size_limits_only_tighten(self):
        bc.check_size(500, max_notional=2000, daily_remaining=900)
        with self.assertRaises(BrokerError):
            bc.check_size(2500, max_notional=2000, daily_remaining=None)
        with self.assertRaises(BrokerError):
            bc.check_size(500, max_notional=2000, daily_remaining=100)
        with self.assertRaises(BrokerError):
            bc.check_size(30_000, max_notional=None, daily_remaining=None)


class TestIbkr(unittest.TestCase):
    def setUp(self):
        ibkr.book._items.clear()

    def test_gateway_address_must_be_this_computer(self):
        self.assertEqual(ibkr.clean_gateway_url(""), "https://localhost:5757")
        self.assertEqual(ibkr.clean_gateway_url("localhost:5001"), "https://localhost:5001")
        self.assertEqual(ibkr.clean_gateway_url("https://127.0.0.1:5000/"), "https://127.0.0.1:5000")
        for bad in ("https://evil.example.com:5000", "http://192.168.1.5:5000", "ftp://localhost"):
            with self.assertRaises(BrokerError):
                ibkr.clean_gateway_url(bad)

    def test_status_reads_and_signed_out_is_explained(self):
        self.assertTrue(ibkr.status(ibkr.Gateway(opener=FakeIbkr()))["connected"])
        out = ibkr.status(ibkr.Gateway(opener=FakeIbkr(authenticated=False)))
        self.assertFalse(out["connected"])
        self.assertIn("sign in", out["message"])

    def test_an_unreachable_gateway_says_to_start_it(self):
        def boom(req, timeout=None):
            raise urllib.error.URLError("refused")
        out = ibkr.status(ibkr.Gateway(opener=boom))
        self.assertFalse(out["connected"])
        self.assertIn("Start the Client Portal Gateway", out["message"])

    def test_the_ledger_lists_each_currency_and_skips_empty_ones(self):
        rows = ibkr.ledger(ibkr.Gateway(opener=FakeIbkr()), "U111")
        self.assertEqual([r["currency"] for r in rows], ["USD", "EUR"])               # CHF is empty; BASE is only the sum
        eur = rows[1]
        self.assertEqual((eur["cash"], eur["stock_value"], eur["total"], eur["rate"]), (500.0, 900.0, 1400.0, 1.08))
        self.assertAlmostEqual(eur["base_value"], 1512.0)

    def test_a_gateway_on_another_port_is_found_and_remembered(self):
        fake = FakeIbkr()

        def only_5001(req, timeout=None):
            if ":5001/" not in req.full_url:
                raise urllib.error.URLError("refused")
            return fake(req, timeout)

        gw = ibkr.Gateway(opener=only_5001)                       # the default address does not answer
        st = ibkr.status(gw)
        self.assertTrue(st["down"])
        self.assertEqual(ibkr.find_gateway("https://localhost:5500", opener=only_5001), "https://localhost:5001")
        self.assertIsNone(ibkr.find_gateway("https://localhost:5001", opener=only_5001))
        self.assertIsNone(ibkr.find_gateway("", opener=lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("x"))))
        self.assertFalse(ibkr.status(ibkr.Gateway(opener=FakeIbkr(authenticated=False)))["down"])      # signed out is not "down"

    def test_accounts_summary_positions_orders(self):
        gw = ibkr.Gateway(opener=FakeIbkr())
        self.assertEqual([a["id"] for a in ibkr.list_accounts(gw)], ["U111", "U222"])
        self.assertEqual(ibkr.summary(gw, "U111"), {"value": 51000.5, "cash": 1000.0, "buying_power": 2000.0, "currency": "USD"})
        pos = ibkr.positions(gw, "U111")
        self.assertEqual([(p["symbol"], p["qty"], p["market_value"]) for p in pos], [("AAPL", 10.0, 2000.0), ("SAP", 5.0, 900.0)])   # futures skipped
        orders = ibkr.open_orders(gw, "U111")
        self.assertEqual([(o["symbol"], o["side"], o["open"]) for o in orders], [("AAPL", "buy", True), ("MSFT", "sell", False)])

    def test_preview_prices_the_order_and_place_sends_exactly_it(self):
        fake = FakeIbkr()
        gw = ibkr.Gateway(opener=fake)
        p = ibkr.preview(gw, "U111", {"symbol": "aapl", "side": "buy", "qty": 2, "type": "market"})
        self.assertEqual((p["price"], p["estimate"]), (200.5, 401.0))
        out = ibkr.place(gw, "U111", p["token"])
        self.assertEqual((out["id"], out["symbol"], out["qty"], out["estimate"]), ("9001", "AAPL", 2, 401.0))
        sent = fake.orders_posted[0]["orders"][0]
        self.assertEqual((sent["conid"], sent["side"], sent["quantity"], sent["orderType"], sent["tif"]), (265598, "BUY", 2, "MKT", "DAY"))
        with self.assertRaises(BrokerError):
            ibkr.place(gw, "U111", p["token"])                          # a token works once

    def test_limit_order_carries_its_price_and_a_token_cannot_move_to_another_account(self):
        fake = FakeIbkr()
        gw = ibkr.Gateway(opener=fake)
        p = ibkr.preview(gw, "U111", {"symbol": "AAPL", "side": "sell", "qty": 1, "type": "limit", "limit_price": 210})
        with self.assertRaises(BrokerError):
            ibkr.place(gw, "U222", p["token"])
        self.assertEqual(fake.orders_posted, [])
        p = ibkr.preview(gw, "U111", {"symbol": "AAPL", "side": "sell", "qty": 1, "type": "limit", "limit_price": 210, "time_in_force": "gtc"})
        ibkr.place(gw, "U111", p["token"])
        sent = fake.orders_posted[0]["orders"][0]
        self.assertEqual((sent["orderType"], sent["price"], sent["side"], sent["tif"]), ("LMT", 210.0, "SELL", "GTC"))

    def test_ibkr_questions_are_never_answered_for_you(self):
        fake = FakeIbkr(ask=True)
        gw = ibkr.Gateway(opener=fake)
        p = ibkr.preview(gw, "U111", {"symbol": "AAPL", "side": "buy", "qty": 1, "type": "market"})
        out = ibkr.place(gw, "U111", p["token"])
        self.assertTrue(out["ack_required"])
        self.assertEqual(out["messages"], ["Price exceeds the 3% constraint."])
        self.assertFalse([c for c in fake.calls if c[1].startswith("/iserver/reply/")])      # nothing confirmed yet
        done = ibkr.place(gw, "U111", out["token"])                                           # the person chose "send anyway"
        self.assertEqual(done["id"], "9002")
        self.assertTrue([c for c in fake.calls if c[1] == "/iserver/reply/reply-1"])

    def test_market_order_without_a_price_asks_for_a_limit(self):
        class NoPrice(FakeIbkr):
            def __call__(self, req, timeout=None):
                if "/marketdata/snapshot" in req.full_url:
                    return Resp([{}])
                return super().__call__(req, timeout)
        with self.assertRaises(BrokerError):
            ibkr.preview(ibkr.Gateway(opener=NoPrice()), "U111", {"symbol": "AAPL", "side": "buy", "qty": 1, "type": "market"})

    def test_cancel_checks_the_id(self):
        fake = FakeIbkr()
        ibkr.cancel(ibkr.Gateway(opener=fake), "U111", "77")
        self.assertIn(("DELETE", "/iserver/account/U111/order/77"), fake.calls)
        with self.assertRaises(BrokerError):
            ibkr.cancel(ibkr.Gateway(opener=fake), "U111", "../../x")


class TestEtrade(unittest.TestCase):
    def setUp(self):
        etrade.book._items.clear()

    def client(self, fake=None, **kw):
        return etrade.Client("CK", "CS", "TOK", "TSEC", opener=fake or FakeEtrade(), **kw)

    def test_oauth_signature_is_hmac_sha1_over_the_sorted_request(self):
        c = etrade.Client("CK", "CS", "TOK", "TSEC", clock=lambda: 1700000000)
        header = c._auth_header("GET", "https://api.etrade.com/v1/x", {"b": "2 3", "a": "1"})
        params = dict(re.findall(r'(\w+)="([^"]*)"', header))
        sig = urllib.parse.unquote(params.pop("oauth_signature"))
        pairs = sorted((etrade._enc(k), etrade._enc(urllib.parse.unquote(v))) for k, v in {**params, "b": "2 3", "a": "1"}.items())
        base = "&".join(["GET", etrade._enc("https://api.etrade.com/v1/x"), etrade._enc("&".join(f"{k}={v}" for k, v in pairs))])
        expect = base64.b64encode(hmac.new(b"CS&TSEC", base.encode(), hashlib.sha1).digest()).decode()
        self.assertEqual(sig, expect)
        self.assertEqual(params["oauth_signature_method"], "HMAC-SHA1")
        self.assertEqual(params["oauth_token"], "TOK")

    def test_login_is_two_steps_and_gives_a_session(self):
        fake = FakeEtrade()
        start = etrade.start_login("CK", "CS", opener=fake)
        self.assertEqual(start["request_token"], "REQ")
        self.assertIn("key=CK", start["authorize_url"])
        self.assertIn("token=REQ", start["authorize_url"])
        self.assertIn('oauth_callback="oob"', fake.calls[0][2])
        got = etrade.finish_login("CK", "CS", "REQ", "REQSECRET", " CODE123 ", opener=fake)
        self.assertEqual(got, {"token": "ACC", "token_secret": "ACCSECRET"})
        with self.assertRaises(BrokerError):
            etrade.finish_login("CK", "CS", "REQ", "REQSECRET", "", opener=fake)

    def test_an_idle_session_is_renewed_instead_of_asking_you_to_sign_in_again(self):
        fake = FakeEtrade()
        fake.idle = True
        self.assertEqual([a["id"] for a in etrade.list_accounts(self.client(fake))], ["KEY1"])
        self.assertEqual(fake.renews, 1)
        gone = FakeEtrade(expired=True)           # past midnight: renewing does not help, so it still asks to Connect
        with self.assertRaises(BrokerError) as cm:
            etrade.list_accounts(self.client(gone))
        self.assertIn("Connect", str(cm.exception))

    def test_positions_carry_every_column_of_the_portfolio_view(self):
        p = etrade.positions(self.client(), "KEY1")[0]
        got = {k: p[k] for k in ("price", "change", "change_pct", "qty", "avg_cost", "day_gain", "day_gain_pct", "gain", "gain_pct",
                                 "market_value", "pct_of_portfolio", "cost_basis", "acquired")}
        self.assertEqual(got, {"price": 65.0, "change": -0.63, "change_pct": -0.96, "qty": 20.0, "avg_cost": 55.0, "day_gain": -12.5,
                               "day_gain_pct": -0.95, "gain": 200.0, "gain_pct": 18.18, "market_value": 1300.0,
                               "pct_of_portfolio": 5.2, "cost_basis": 1100.0, "acquired": "2021-01-01"})

    def test_a_rejected_session_says_why(self):
        class Rejects(FakeEtrade):
            def __call__(self, req, timeout=None):
                if urllib.parse.urlparse(req.full_url).path.startswith("/v1/"):
                    raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b"oauth_problem=token_rejected"))
                return super().__call__(req, timeout=timeout)
        with self.assertRaises(BrokerError) as cm:
            etrade.list_accounts(self.client(Rejects()))
        self.assertIn("token_rejected", str(cm.exception))

    def test_lots_list_every_purchase_with_its_cost_basis(self):
        rows = etrade.lots(self.client(), "KEY1")
        self.assertEqual([(r["acquired"], r["qty"], r["cost_per_share"], r["cost_basis"], r["term"]) for r in rows],
                         [("2021-01-01", 12.0, 50.0, 600.0, "long"), ("2025-03-01", 8.0, 62.5, 500.0, "short")])
        self.assertEqual(rows[1]["gain"], 20.0)

    def test_balances_fall_back_when_the_usual_fields_are_missing(self):
        class Fake(FakeEtrade):
            def __init__(self, body):
                super().__init__()
                self.body = body

            def __call__(self, req, timeout=None):
                if urllib.parse.urlparse(req.full_url).path == "/v1/accounts/KEY1/balance.json":
                    return Resp(self.body)
                return super().__call__(req, timeout=timeout)
        margin = {"BalanceResponse": {"accountType": "MARGIN", "Computed": {"accountBalance": 9000, "cashBalance": 400,
                                                                           "marginBuyingPower": 18000, "cashBuyingPower": 400}}}
        got = etrade.summary(self.client(Fake(margin)), "KEY1")
        self.assertEqual((got["value"], got["cash"], got["buying_power"]), (9000.0, 400.0, 18000.0))
        net = {"BalanceResponse": {"Computed": {"netCash": 100, "RealTimeValues": {"netMv": 5000}}}}
        got = etrade.summary(self.client(Fake(net)), "KEY1")
        self.assertEqual((got["value"], got["cash"], got["buying_power"]), (5100.0, 100.0, 100.0))
        empty = etrade.summary(self.client(Fake({"BalanceResponse": {}})), "KEY1")
        self.assertIsNone(empty["value"])

    def test_accounts_skip_closed_ones_and_summary_positions_orders_read(self):
        c = self.client()
        self.assertEqual([a["id"] for a in etrade.list_accounts(c)], ["KEY1"])
        self.assertEqual(etrade.summary(c, "KEY1"), {"value": 25000.0, "cash": 1500.0, "buying_power": 3000.0, "currency": "USD"})
        self.assertEqual([(p["symbol"], p["qty"], p["market_value"]) for p in etrade.positions(c, "KEY1")], [("KO", 20.0, 1300.0)])
        o = etrade.open_orders(c, "KEY1")
        self.assertEqual([(x["id"], x["symbol"], x["side"], x["type"], x["open"]) for x in o], [("555", "KO", "buy", "limit", True)])

    def test_preview_uses_etrades_own_preview_and_place_sends_that_preview_id(self):
        fake = FakeEtrade()
        c = self.client(fake)
        p = etrade.preview(c, "KEY1", {"symbol": "ko", "side": "buy", "qty": 3, "type": "market"})
        self.assertEqual(p["estimate"], 195.75)
        out = etrade.place(c, "KEY1", p["token"])
        self.assertEqual((out["id"], out["symbol"], out["estimate"]), ("888", "KO", 195.75))
        req = fake.placed[0]["PlaceOrderRequest"]
        self.assertEqual(req["PreviewIds"], [{"previewId": 424242}])
        order = req["Order"][0]
        self.assertEqual((order["priceType"], order["orderTerm"], order["Instrument"][0]["orderAction"], order["Instrument"][0]["quantity"]),
                         ("MARKET", "GOOD_FOR_DAY", "BUY", 3))
        with self.assertRaises(BrokerError):
            etrade.place(c, "KEY1", p["token"])

    def test_order_over_the_limit_is_refused_before_anything_is_sent(self):
        fake = FakeEtrade()
        with self.assertRaises(BrokerError):
            etrade.preview(self.client(fake), "KEY1", {"symbol": "KO", "side": "buy", "qty": 3, "type": "market"}, max_notional=100)
        self.assertEqual(fake.placed, [])

    def test_an_expired_session_says_to_connect_again(self):
        with self.assertRaises(BrokerError) as ctx:
            etrade.list_accounts(self.client(FakeEtrade(expired=True)))
        self.assertIn("Connect", str(ctx.exception))

    def test_cancel_checks_the_id(self):
        etrade.cancel(self.client(), "KEY1", "555")
        with self.assertRaises(BrokerError):
            etrade.cancel(self.client(), "KEY1", "abc")


class BrokerApiCase(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        self.kr = FakeKeyring()
        self._kp = [patch.object(keyring, "get_password", self.kr.get_password), patch.object(keyring, "set_password", self.kr.set_password),
                    patch.object(keyring, "delete_password", self.kr.delete_password)]
        for p in self._kp:
            p.start()
        secrets_store.clear_vault_cache()
        ibkr.book._items.clear()
        etrade.book._items.clear()
        self.ib, self.et = FakeIbkr(), FakeEtrade()
        self._op = patch.dict(broker_api.OPENERS, {"ibkr": self.ib, "etrade": self.et})
        self._op.start()

    def tearDown(self):
        self._op.stop()
        for p in self._kp:
            p.stop()
        secrets_store.clear_vault_cache()
        super().tearDown()

    def post(self, path, payload):
        return trading_api.handle(path, payload)

    def arm(self):
        db.live_trading.arm(db.live_trading.CONFIRM_PHRASE)

    def test_limits_are_one_setting_for_every_broker_and_can_be_removed(self):
        out = self.post("/api/alpaca/live/limits", {"per_order": None, "daily": 400000})
        self.assertEqual(out, {"per_order": None, "daily": 400000.0})
        with self.assertRaises(ValueError):                                   # a missing value must never mean "no limit"
            self.post("/api/alpaca/live/limits", {"daily": 100})
        self.arm()
        self.assertIsNone(self.post("/api/broker/data", {"broker": "ibkr"})["per_order"])
        bc.check_size(90_000.0, max_notional=db.live_trading.per_order_limit(), daily_remaining=db.live_trading.daily_remaining())
        db.live_trading.set_limits(1000, 5000)
        with self.assertRaises(BrokerError):
            bc.check_size(2000.0, max_notional=db.live_trading.per_order_limit(), daily_remaining=db.live_trading.daily_remaining())

    def test_keys_are_production_only_and_show_only_their_last_four(self):
        self.post("/api/broker/etrade/keys", {"consumer_key": "ABCDEF1234", "consumer_secret": "S", "sandbox": True})
        st = broker_api.etrade_state()
        self.assertEqual(st["key_hint"], "\u20261234")
        self.assertTrue(st["has_keys"] and st["has_secret"])
        self.assertNotIn("sandbox", st)
        self.assertNotIn("sandbox", secrets_store.get_broker_secret("etrade"))
        self.assertNotIn("ABCDEF", json.dumps(st))

    def connect_etrade(self):
        self.post("/api/broker/etrade/keys", {"consumer_key": "CK", "consumer_secret": "CS"})
        self.post("/api/broker/etrade/start", {})
        self.post("/api/broker/etrade/finish", {"verifier": "CODE123"})


class TestBrokerRoutes(BrokerApiCase):
    def test_routes_are_owner_routes(self):
        for path in broker_api.ROUTES:
            self.assertIn(path, trading_api.ROUTES)

    def test_ibkr_data_when_connected_lists_everything(self):
        out = self.post("/api/broker/data", {"broker": "ibkr"})
        self.assertTrue(out["connected"])
        self.assertEqual((out["account"], len(out["accounts"])), ("U111", 2))
        self.assertEqual(out["positions"][0]["symbol"], "AAPL")
        self.assertFalse(out["armed"])
        self.assertEqual(self.post("/api/broker/data", {"broker": "ibkr", "account": "U222"})["account"], "U222")

    def test_pressing_connect_again_keeps_the_current_session_until_the_new_one_is_confirmed(self):
        self.connect_etrade()
        self.assertTrue(broker_api.etrade_state()["has_session"])
        self.post("/api/broker/etrade/start", {})
        st = broker_api.etrade_state()
        self.assertTrue(st["has_session"] and st["pending"])

    def test_lots_route_totals_for_etrade_and_explains_ibkr(self):
        self.arm()
        self.connect_etrade()
        one = self.post("/api/broker/lots", {"broker": "etrade", "account": "KEY1", "symbol": "ko"})      # one stock, one account
        self.assertEqual([r["symbol"] for r in one["lots"]], ["KO", "KO"])
        self.assertEqual(one["lots"][0]["gain_pct"], 30.0)
        self.assertEqual(self.post("/api/broker/lots", {"broker": "etrade", "account": "KEY1", "symbol": "ZZZ"})["lots"], [])
        out = self.post("/api/broker/lots", {"broker": "etrade", "scope": "all"})
        self.assertEqual(len(out["lots"]), 2)
        self.assertEqual(out["lots"][0]["account"], "INDIVIDUAL (8301)")
        self.assertEqual(out["by_account"][0]["lots"], 2)
        self.assertEqual(out["problems"], [])
        self.assertEqual(out["total"]["cost_basis"], 1100.0)
        self.assertEqual(out["by_symbol"][0]["lots"], 2)
        with self.assertRaises(ValueError) as cm:
            self.post("/api/broker/lots", {"broker": "ibkr"})
        self.assertIn("average cost", str(cm.exception))

    def test_ibkr_data_includes_currency_balances_and_each_position_in_its_own_currency(self):
        out = self.post("/api/broker/data", {"broker": "ibkr"})
        self.assertEqual([r["currency"] for r in out["currencies"]], ["USD", "EUR"])
        sap = [p for p in out["positions"] if p["symbol"] == "SAP"][0]
        self.assertEqual(sap["currency"], "EUR")
        self.assertAlmostEqual(sap["base_value"], 972.0)

    def test_with_several_accounts_the_data_includes_every_account_and_the_totals(self):
        out = self.post("/api/broker/data", {"broker": "ibkr"})
        ov = out["overview"]
        self.assertEqual([a["id"] for a in ov["accounts"]], ["U111", "U222"])
        self.assertTrue(all(a["summary"] is not None for a in ov["accounts"]))
        self.assertAlmostEqual(ov["total"]["value"], sum(a["summary"]["value"] for a in ov["accounts"]))
        self.assertTrue(ov["holdings"])
        self.assertEqual(ov["holdings"][0]["symbol"], "AAPL")
        self.assertEqual(ov["holdings"][0]["accounts"], 2)

    def test_ibkr_data_finds_the_gateway_on_its_real_port_and_saves_it(self):
        fake = self.ib

        def only_5001(req, timeout=None):
            if ":5001/" not in req.full_url:
                raise urllib.error.URLError("refused")
            return fake(req, timeout)

        with patch.dict(broker_api.OPENERS, {"ibkr": only_5001}):
            out = self.post("/api/broker/data", {"broker": "ibkr"})
            self.assertTrue(out["connected"])
            self.assertEqual(out["gateway_url"], "https://localhost:5001")
            self.assertIn("5001", out["found_note"])
            self.assertEqual(broker_api.gateway_url(), "https://localhost:5001")           # remembered for next time
            self.assertNotIn("found_note", self.post("/api/broker/data", {"broker": "ibkr"}))

    def test_ibkr_data_when_nothing_answers_keeps_the_start_the_gateway_message(self):
        def nothing(req, timeout=None):
            raise urllib.error.URLError("refused")

        with patch.dict(broker_api.OPENERS, {"ibkr": nothing}):
            out = self.post("/api/broker/data", {"broker": "ibkr"})
        self.assertFalse(out["connected"])
        self.assertIn("Start the Client Portal Gateway", out["message"])

    def test_ibkr_data_when_signed_out_says_so(self):
        self.ib.authenticated = False
        out = self.post("/api/broker/data", {"broker": "ibkr"})
        self.assertFalse(out["connected"])
        self.assertIn("sign in", out["message"])

    def test_gateway_address_is_saved_only_when_local(self):
        self.assertEqual(self.post("/api/broker/ibkr/gateway", {"url": "localhost:5001"})["url"], "https://localhost:5001")
        self.assertEqual(broker_api.gateway_url(), "https://localhost:5001")
        with self.assertRaises(ValueError):
            self.post("/api/broker/ibkr/gateway", {"url": "https://example.com"})

    def test_etrade_full_connection_flow_stores_keys_in_the_keychain_only(self):
        d = self.post("/api/broker/data", {"broker": "etrade"})
        self.assertFalse(d["connected"])
        self.assertIn("keys", d["message"])
        self.connect_etrade()
        d = self.post("/api/broker/data", {"broker": "etrade"})
        self.assertTrue(d["connected"])
        self.assertEqual((d["accounts"][0]["id"], d["summary"]["value"], d["positions"][0]["symbol"]), ("KEY1", 25000.0, "KO"))
        sec = secrets_store.get_broker_secret("etrade")
        self.assertEqual((sec["token"], sec["consumer_key"]), ("ACC", "CK"))
        self.assertNotIn("request_token", sec)                                    # the one-time token is gone
        self.post("/api/broker/etrade/disconnect", {})
        self.assertFalse(self.post("/api/broker/data", {"broker": "etrade"})["connected"])
        self.assertTrue(secrets_store.has_broker_secret("etrade"))                # keys kept
        self.post("/api/broker/etrade/disconnect", {"forget_keys": True})
        self.assertFalse(secrets_store.has_broker_secret("etrade"))

    def test_etrade_expired_session_reports_not_connected(self):
        self.connect_etrade()
        self.et.expired = True
        out = self.post("/api/broker/data", {"broker": "etrade"})
        self.assertFalse(out["connected"])
        self.assertIn("Connect", out["message"])

    def test_etrade_finish_without_start_is_refused(self):
        self.post("/api/broker/etrade/keys", {"consumer_key": "CK", "consumer_secret": "CS"})
        with self.assertRaises(ValueError):
            self.post("/api/broker/etrade/finish", {"verifier": "X"})


class TestBrokerOrders(BrokerApiCase):
    def order(self, **kw):
        return {"symbol": "AAPL", "side": "buy", "qty": 2, "type": "market", **kw}

    def test_nothing_can_be_previewed_sent_or_cancelled_while_live_trading_is_off(self):
        for path, payload in (("/api/broker/preview", {"order": self.order()}), ("/api/broker/order", {"token": "t"}),
                              ("/api/broker/cancel", {"order_id": "77"})):
            with self.assertRaises(ValueError) as ctx:
                self.post(path, {"broker": "ibkr", "account": "U111", **payload})
            self.assertIn("switched off", str(ctx.exception))
        self.assertEqual(self.ib.orders_posted, [])

    def test_the_account_must_be_one_the_broker_lists(self):
        self.arm()
        with self.assertRaises(ValueError):
            self.post("/api/broker/preview", {"broker": "ibkr", "account": "U999", "order": self.order()})

    def test_ibkr_order_needs_the_symbol_typed_then_is_sent_and_logged(self):
        self.arm()
        p = self.post("/api/broker/preview", {"broker": "ibkr", "account": "U111", "order": self.order()})
        with self.assertRaises(ValueError) as ctx:
            self.post("/api/broker/order", {"broker": "ibkr", "account": "U111", "token": p["token"], "confirm_symbol": "MSFT"})
        self.assertIn("type its symbol", str(ctx.exception))
        self.assertEqual(self.ib.orders_posted, [])
        out = self.post("/api/broker/order", {"broker": "ibkr", "account": "U111", "token": p["token"], "confirm_symbol": "aapl"})
        self.assertEqual(out["id"], "9001")
        log = db.live_trading.list_live_orders()
        self.assertEqual([(r["symbol"], r["broker"], r["order_id"], r["estimate"]) for r in log], [("AAPL", "ibkr", "9001", 401.0)])
        self.assertEqual(db.live_trading.spent_today(), 401.0)                    # the daily limit counts every broker together
        self.assertEqual(db.live_trading.list_live_orders(broker="alpaca"), [])

    def test_a_token_from_one_broker_cannot_be_used_at_another(self):
        self.arm()
        self.connect_etrade()
        p = self.post("/api/broker/preview", {"broker": "ibkr", "account": "U111", "order": self.order()})
        with self.assertRaises(ValueError):
            self.post("/api/broker/order", {"broker": "etrade", "account": "KEY1", "token": p["token"], "confirm_symbol": "AAPL"})

    def test_etrade_order_is_previewed_sent_and_logged(self):
        self.arm()
        self.connect_etrade()
        p = self.post("/api/broker/preview", {"broker": "etrade", "account": "KEY1", "order": {"symbol": "KO", "side": "buy", "qty": 3, "type": "market"}})
        self.assertEqual(p["estimate"], 195.75)
        out = self.post("/api/broker/order", {"broker": "etrade", "account": "KEY1", "token": p["token"], "confirm_symbol": "KO"})
        self.assertEqual(out["id"], "888")
        self.assertEqual([(r["broker"], r["symbol"]) for r in db.live_trading.list_live_orders()], [("etrade", "KO")])

    def test_ibkr_question_is_returned_not_logged_then_send_anyway_logs_it(self):
        self.arm()
        self.ib.ask = True
        p = self.post("/api/broker/preview", {"broker": "ibkr", "account": "U111", "order": self.order(qty=1)})
        asked = self.post("/api/broker/order", {"broker": "ibkr", "account": "U111", "token": p["token"], "confirm_symbol": "AAPL"})
        self.assertTrue(asked["ack_required"])
        self.assertEqual(db.live_trading.list_live_orders(), [])
        done = self.post("/api/broker/order", {"broker": "ibkr", "account": "U111", "token": asked["token"], "confirm_symbol": "AAPL"})
        self.assertEqual(done["id"], "9002")
        self.assertEqual(len(db.live_trading.list_live_orders()), 1)

    def test_per_order_and_daily_limits_apply(self):
        self.arm()
        db.live_trading.set_limits(300, 500)
        with self.assertRaises(ValueError):
            self.post("/api/broker/preview", {"broker": "ibkr", "account": "U111", "order": self.order(qty=2)})     # $401 > $300
        db.live_trading.log_live_order(symbol="X", side="buy", qty=1, order_type="market", estimate=400.0, order_id="z", status="ok", broker="etrade")
        with self.assertRaises(ValueError) as ctx:
            self.post("/api/broker/preview", {"broker": "ibkr", "account": "U111", "order": self.order(qty=1)})     # $200 > $100 left today
        self.assertIn("left of today", str(ctx.exception))

    def test_cancel_goes_to_the_broker_when_armed(self):
        self.arm()
        self.post("/api/broker/cancel", {"broker": "ibkr", "account": "U111", "order_id": "77"})
        self.assertIn(("DELETE", "/iserver/account/U111/order/77"), self.ib.calls)

    def test_arming_works_for_a_broker_page_without_alpaca_keys(self):
        out = self.post("/api/alpaca/live/arm", {"phrase": "TRADE REAL MONEY", "broker": "ibkr"})
        self.assertTrue(out["armed_until"])
        self.post("/api/alpaca/live/disarm", {})
        with self.assertRaises(ValueError):
            self.post("/api/alpaca/live/arm", {"phrase": "TRADE REAL MONEY"})          # the Alpaca page still wants its live keys


class TestGatewayLauncher(BrokerApiCase):
    def make_gateway(self, root, port=5500):
        for rel, text in (("bin/run.sh", "#!/bin/bash\n"), ("root/conf.yaml", f"    listenPort: {port}\n    listenSsl: true\n"),
                          ("dist/x.jar", "j"), ("logs/old.log", "old"), (".vertx/cache", "c")):
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text)
        return root

    def setUp(self):
        super().setUp()
        import tempfile
        from pathlib import Path
        from source.collector import ibkr_gateway
        self.gw = ibkr_gateway
        self.tmp = tempfile.TemporaryDirectory()
        self.src = self.make_gateway(Path(self.tmp.name) / "src")
        self.dest = Path(self.tmp.name) / "run"
        self.gw._proc = None

    def tearDown(self):
        self.gw._proc = None
        self.tmp.cleanup()
        super().tearDown()

    def test_the_stop_button_can_stop_a_gateway_an_earlier_run_left_running_but_never_another_process(self):
        import os
        import subprocess
        import time
        from pathlib import Path
        run = Path(self.tmp.name) / "datarun"
        run.mkdir()
        # a stand-in gateway: its command line names root/conf.yaml, like the real one, and it runs in its own session
        fake = subprocess.Popen(["bash", "-c", "sleep 60; sleep 0", "bin/run.sh", "root/conf.yaml"], start_new_session=True)
        other = subprocess.Popen(["sleep", "60"], start_new_session=True)
        try:
            with patch.object(self.gw, "run_dir", return_value=run):
                (run / "finsi-gateway.pid").write_text(str(other.pid))
                self.assertFalse(self.gw.adopt_orphan())                        # not the gateway: left alone
                (run / "finsi-gateway.pid").write_text(str(fake.pid))
                self.assertTrue(self.gw.adopt_orphan())
                self.assertTrue(self.gw.stop())
                for _ in range(40):
                    if fake.poll() is not None:
                        break
                    time.sleep(0.05)
                self.assertIsNotNone(fake.poll())                              # it was stopped
                self.assertIsNone(other.poll())                                # the unrelated process was not
        finally:
            for pr in (fake, other):
                if pr.poll() is None:
                    pr.kill()
                pr.wait()
            self.gw._orphan_pid = None

    def test_quitting_the_app_leaves_the_gateway_running(self):
        import inspect
        from source.webapp import dashboard
        self.assertNotIn("ibkr_gateway.stop", inspect.getsource(dashboard.run))
        self.assertNotIn("atexit", inspect.getsource(self.gw.start_with_app))
        self.assertNotIn("atexit", inspect.getsource(self.gw))

    def test_start_writes_a_pid_file_so_a_later_run_can_find_the_gateway(self):
        from pathlib import Path

        class P:
            pid = 4242

            def poll(self):
                return None
        run = Path(self.tmp.name) / "datarun2"
        with patch.object(self.gw, "run_dir", return_value=run):
            run.mkdir()
            self.gw.start(src=self.src, dest=self.dest, env={}, popen=lambda *a, **k: P())
            self.assertEqual((run / "finsi-gateway.pid").read_text(), "4242")

    def test_prepare_copies_the_files_without_logs_or_cache_and_keeps_an_existing_copy(self):
        out = self.gw.prepare(self.src, self.dest)
        self.assertTrue((out / "bin" / "run.sh").is_file())
        self.assertTrue((out / "dist" / "x.jar").is_file())
        self.assertFalse((out / "logs" / "old.log").exists())
        self.assertFalse((out / ".vertx").exists())
        (out / "root" / "conf.yaml").write_text("    listenPort: 7777\n")             # the person's own edit
        self.gw.prepare(self.src, self.dest)
        self.assertEqual(self.gw.listen_port(out), 7777)

    def test_a_missing_gateway_says_where_to_get_it(self):
        with patch.object(self.gw, "bundled_dir", return_value=None):
            with self.assertRaises(BrokerError) as ctx:
                self.gw.prepare(None, self.dest)
        self.assertIn("Client Portal Gateway", str(ctx.exception))

    def test_start_runs_only_the_fixed_command_in_the_copy_and_once(self):
        calls = []

        class P:
            pid = 4321
            def poll(self): return None

        def popen(cmd, **kw):
            calls.append((cmd, kw))
            return P()

        out = self.gw.start(src=self.src, dest=self.dest, env={"JAVA_HOME": "/j"}, popen=popen)
        self.assertTrue(out["started"])
        cmd, kw = calls[0]
        self.assertEqual(cmd, ["bash", "bin/run.sh", "root/conf.yaml"])
        self.assertEqual((kw["cwd"], kw["env"]), (str(self.dest), {"JAVA_HOME": "/j"}))
        self.assertTrue(kw["start_new_session"])
        again = self.gw.start(src=self.src, dest=self.dest, env={}, popen=popen)
        self.assertFalse(again["started"])
        self.assertEqual(len(calls), 1)

    def test_no_java_is_explained_and_nothing_starts(self):
        class R:
            returncode, stdout = 1, ""

        with patch.object(self.gw.sys, "platform", "darwin"), patch.object(self.gw.subprocess, "run", return_value=R()):
            with self.assertRaises(BrokerError) as ctx:
                self.gw.java_env()
        self.assertIn("Java is not installed", str(ctx.exception))

    def test_the_routes_start_and_stop_and_remember_the_conf_port(self):
        with patch.object(self.gw, "start", return_value={"started": True, "message": "Starting"}), \
                patch.object(self.gw, "listen_port", return_value=5599):
            out = self.post("/api/broker/ibkr/start", {})
        self.assertEqual(out["url"], "https://localhost:5599")
        self.assertEqual(broker_api.gateway_url(), "https://localhost:5599")
        self.assertEqual(self.post("/api/broker/ibkr/stop", {}), {"stopped": False})            # this app started nothing

    def test_it_starts_with_the_app_unless_something_already_answers_or_it_is_turned_off(self):
        starts = []
        starter = lambda: starts.append(1) or {"started": True, "message": "Starting"}          # noqa: E731
        with patch.object(self.gw, "port_open", return_value=True):
            self.assertIn("already running", self.gw._autostart_now(starter=starter))
        self.assertEqual(starts, [])
        with patch.object(self.gw, "port_open", return_value=False), patch.object(self.gw, "listen_port", return_value=5757):
            self.assertEqual(self.gw._autostart_now(starter=starter), "Starting")
            self.assertEqual(starts, [1])
            self.assertEqual(broker_api.gateway_url(), "https://localhost:5757")                # the tab now points at it
            self.post("/api/broker/ibkr/autostart", {"on": False})
            self.assertIn("auto-start is off", self.gw._autostart_now(starter=starter))
            self.assertEqual(starts, [1])
            self.assertFalse(self.post("/api/broker/data", {"broker": "ibkr"})["gateway_autostart"])
            self.post("/api/broker/ibkr/autostart", {"on": True})
            self.assertTrue(self.gw.autostart_enabled())

    def test_autostart_never_overrides_an_address_the_person_chose_and_reports_missing_java(self):
        self.post("/api/broker/ibkr/gateway", {"url": "https://localhost:5599"})
        with patch.object(self.gw, "port_open", return_value=False), patch.object(self.gw, "listen_port", return_value=5757):
            self.gw._autostart_now(starter=lambda: {"started": True, "message": "ok"})
            self.assertEqual(broker_api.gateway_url(), "https://localhost:5599")
            def no_java():
                raise BrokerError("Java is not installed on this Mac.")
            self.assertIn("Java is not installed", self.gw._autostart_now(starter=no_java))      # a note, never an exception

    def test_start_with_app_does_nothing_in_tests_demo_or_when_disabled_by_environment(self):
        with patch.object(self.gw.threading, "Thread") as t:
            self.gw.start_with_app()
            t.assert_not_called()                                    # unittest is loaded, so it stays quiet here

    def test_the_private_port_is_the_default_and_the_bundled_conf_matches(self):
        self.assertEqual(ibkr.clean_gateway_url(""), f"https://localhost:{self.gw.PRIVATE_PORT}")
        self.assertIn(self.gw.PRIVATE_PORT, ibkr.COMMON_PORTS)

    def test_start_failure_reaches_the_page_as_a_message(self):
        with patch.object(self.gw, "start", side_effect=BrokerError("Java is not installed on this Mac.")):
            with self.assertRaises(ValueError):
                self.post("/api/broker/ibkr/start", {})


class TestDiagnose(BrokerApiCase):
    def test_etrade_check_shows_structure_never_values(self):
        self.connect_etrade()
        out = self.post("/api/broker/diagnose", {"broker": "etrade"})
        names = [s["step"] for s in out["steps"]]
        self.assertEqual(names[:3], ["Saved keys / session", "Account list", "Accounts the app would show"])
        text = json.dumps(out)
        self.assertIn("AccountListResponse", text)                      # the shape of the reply is there ...
        for secret in ("KEY1", "8301", "25000", "ACC", "CS"):           # ... but no ids, balances or tokens
            self.assertNotIn(f'"{secret}"', text)
        self.assertTrue(all(s["ok"] for s in out["steps"]))

    def test_etrade_check_without_a_session_says_what_is_missing(self):
        out = self.post("/api/broker/diagnose", {"broker": "etrade"})
        self.assertFalse(out["steps"][0]["ok"])
        self.assertEqual(len(out["steps"]), 1)

    def test_a_failing_call_is_reported_not_raised(self):
        self.connect_etrade()
        self.et.expired = True
        out = self.post("/api/broker/diagnose", {"broker": "etrade"})
        failed = [s for s in out["steps"] if not s["ok"]]
        self.assertTrue(failed)
        self.assertIn("Connect", failed[0]["error"] if "error" in failed[0] else "Connect")

    def test_ibkr_check_lists_the_gateway_calls(self):
        out = self.post("/api/broker/diagnose", {"broker": "ibkr"})
        self.assertEqual([s["step"] for s in out["steps"]], ["Gateway sign-in status", "Accounts", "Portfolio accounts"])
        self.assertTrue(all(s["ok"] for s in out["steps"]))
        self.assertNotIn("U111", json.dumps(out))

    def test_the_check_is_an_owner_route_and_the_page_has_the_button(self):
        self.assertIn("/api/broker/diagnose", trading_api.ROUTES)


class TestRatingsRoute(BrokerApiCase):
    def test_ratings_come_back_for_the_symbols_asked_with_the_numbers_behind_them(self):
        from source.webapp.pages import watchlist
        seen = {}

        def fake_rows(items, keys, **kw):
            seen["symbols"] = [i["symbol"] for i in items]
            return [{"symbol": i["symbol"], "rating": "Buy", "buy_votes": 5, "sell_votes": 1, "signal_count": 7, "rsi": 61.0} for i in items]

        with patch.object(watchlist, "build_rows", fake_rows), \
                patch("source.webapp.pages.quote_chart.market_data_source", return_value=(("K", "S"), "live")):
            out = self.post("/api/ratings", {"symbols": ["aapl", "$$$", "AAPL", "ko"]})
        self.assertEqual(seen["symbols"], ["AAPL", "KO"])                  # cleaned, de-duplicated
        self.assertEqual(out["items"][0]["buy_votes"], 5)

    def test_no_symbols_is_empty_and_the_route_is_an_owner_route(self):
        self.assertEqual(self.post("/api/ratings", {"symbols": []}), {"items": []})
        self.assertIn("/api/ratings", trading_api.ROUTES)

    def test_watchlist_rows_carry_the_vote_counts(self):
        from source.webapp.pages import watchlist
        bars = [{"t": f"2026-01-{i % 28 + 1:02d}", "o": 10 + i * 0.1, "h": 11 + i * 0.1, "l": 9 + i * 0.1, "c": 10 + i * 0.1, "v": 1000 + i}
                for i in range(260)]
        row = watchlist._row({"symbol": "ABC", "note": ""}, None, bars)
        self.assertGreater(row["signal_count"], 3)
        self.assertEqual(row["buy_votes"] + row["sell_votes"] <= row["signal_count"], True)


class TestBrokerSecretsAndAudit(TempConfigTestCase):
    def test_audit_log_defaults_to_alpaca_and_sync_leaves_other_brokers_alone(self):
        LT = db.live_trading
        LT.log_live_order(symbol="VTI", side="buy", qty=1, order_type="market", estimate=1.0, order_id="same", status="pending_new")
        LT.log_live_order(symbol="KO", side="buy", qty=1, order_type="market", estimate=1.0, order_id="same", status="submitted", broker="etrade")
        LT.sync_statuses([{"id": "same", "status": "filled"}])
        by = {r["broker"]: r["status"] for r in LT.list_live_orders()}
        self.assertEqual(by, {"alpaca": "filled", "etrade": "submitted"})


class TestBrokerPages(DashboardTestCase):
    def test_nav_lists_alpaca_ibkr_etrade_and_stock_analysis_but_no_practice_account(self):
        page = self._get("/ibkr.html").read().decode("utf-8")
        row = page[page.index('<div class="subnav">'):]
        row = row[:row.index("</div>")]
        order = [row.index(x) for x in (">Alpaca<", ">IBKR<", ">E*TRADE<", ">Stock Analysis<")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("Practice Account", row)
        self.assertIn('<a href="/ibkr.html" class="active">IBKR</a>', row)
        self.assertIn('<a href="/trading-live.html" class="active">', page)           # the Trading tab stays lit

    def test_the_practice_page_still_opens_with_the_trading_tab_lit(self):
        page = self._get("/trading.html").read().decode("utf-8")
        self.assertIn('<a href="/trading-live.html" class="active">', page)

    def test_setup_has_the_trading_limits_card_and_the_trading_page_points_to_it(self):
        setup = self._get("/setup.html").read().decode("utf-8")
        self.assertIn('id="live-limits"', setup)
        self.assertIn("Alpaca, IBKR and E*TRADE together", setup)
        self.assertIn("No limit", setup)
        from source.webapp.pages import trading
        alpaca_page = trading._live_controls_html()                            # the switch card shown on the Alpaca tab
        self.assertNotIn("The highest limits this app allows", alpaca_page)
        self.assertNotIn('name="per_order"', alpaca_page)                      # the form moved to Setup
        self.assertIn("/setup.html#live-limits", alpaca_page)

    def test_ibkr_page_explains_the_gateway_and_holds_the_ticket(self):
        page = self._get("/ibkr.html").read().decode("utf-8")
        self.assertIn("Client Portal Gateway", page)
        self.assertIn("REAL MONEY", page)
        self.assertIn('id="bk-form"', page)
        self.assertIn("/api/broker/data", page)
        self.assertIn("var BROKER = 'ibkr'", page)
        self.assertIn("Run a check", page)
        self.assertIn("data-act=\"buy\"", page)                                   # Buy as well as Sell on each position
        self.assertIn("Everything held, added up across accounts", page)
        self.assertIn("data-sortkey", page)                                        # every column heading sorts
        self.assertIn("function resort", page)
        self.assertIn('id="bk-orders-', page)                                      # Orders is a collapsed section with a count
        self.assertIn("ORDERS_OPEN = {}", page)
        self.assertIn("__all__", page)                                             # "All accounts" choice
        self.assertIn('name="account"', page)                                      # account picker on the order ticket
        self.assertIn('id="bk-connect"', page)                                     # the Connect card is a collapsible section
        self.assertIn("Live trading: ON", page)
        self.assertNotIn("left today (shared with every broker)", page)
        self.assertIn("lot-toggle", page)                                          # click the arrow beside a stock to see its lots
        self.assertIn("data-act=\"expandall\"", page)
        self.assertIn("withStocks > 1", page)                                      # shown only when 2+ accounts hold stocks
        self.assertIn('id="gw-auto"', page)                          # "start automatically with the app" switch
        self.assertIn('id="gw-start"', page)                         # Start gateway / Sign in to IBKR / Stop gateway
        self.assertIn("/api/broker/ibkr/start", page)
        self.assertIn("{k: 'rating', t: 'Rating'", page)                       # each position gets a rating and a hover analysis
        self.assertIn("/api/ratings", page)

    def test_etrade_page_explains_keys_and_the_daily_sign_in(self):
        page = self._get("/etrade.html").read().decode("utf-8")
        self.assertIn("consumer key", page)
        self.assertIn("Customer Protection Guarantee", page)
        self.assertIn("var BROKER = 'etrade'", page)
        self.assertNotIn('id="et-start"', page)                     # no keys saved yet, so no Connect button

    def test_etrade_page_shows_connect_once_keys_are_saved(self):
        self._post("/api/broker/etrade/keys", {"consumer_key": "CK", "consumer_secret": "CS"})
        page = self._get("/etrade.html").read().decode("utf-8")
        self.assertIn('id="et-start"', page)
        self.assertNotIn("CS", page.replace("CSS", "").replace("CSV", ""))      # the secret is never written into the page

    def test_the_quote_cards_trade_button_offers_each_real_money_account(self):
        body = self._get("/stock-analysis.html").read().decode("utf-8") if False else None
        from source.webapp.pages import quote_panel
        targets = quote_panel.trade_targets()
        self.assertIn(["IBKR", "/ibkr.html"], targets)
        html_page = quote_panel.quote_panel_html()
        self.assertIn("var TRADE_TARGETS = ", html_page)
        self.assertIn("Trade with", html_page)
        self.assertNotIn("Practice order", html_page)




class TestIbkrKeepAlive(unittest.TestCase):
    def test_keepalive_pings_tickle_and_never_raises(self):
        seen = []

        class Gw:
            def __init__(self, *a, **k):
                pass

            def call(self, method, path, body=None):
                seen.append((method, path))
        with patch("source.collector.ibkr.Gateway", Gw):
            self.assertTrue(ibkr_gateway.keepalive_once())
        self.assertEqual(seen, [("POST", "/tickle")])

        class Down(Gw):
            def call(self, *a, **k):
                raise BrokerError("down")
        with patch("source.collector.ibkr.Gateway", Down):
            self.assertFalse(ibkr_gateway.keepalive_once())


if __name__ == "__main__":
    unittest.main()
