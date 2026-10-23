"""The Alpaca paper-trading client (source.collector.alpaca): paper-only host,
order validation, the preview -> single-use-token -> place flow, the size
limit, error messages, and the Keychain storage of the key pair. No test
touches the network -- every call goes through a fake urlopen."""

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from source.collector import alpaca
from source.common import secrets_store
from tests.testing_utils import FakeKeyring

KEYS = ("PKTEST", "secret")


class FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8") if payload is not None else b""

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeAlpaca:
    """Records every request and answers by (method, path)."""

    def __init__(self, routes=None):
        self.calls = []
        self.routes = routes or {}

    def __call__(self, request, timeout=None):
        from urllib.parse import urlparse
        parsed = urlparse(request.full_url)
        key = (request.get_method(), parsed.netloc + parsed.path)
        self.calls.append({
            "method": request.get_method(), "url": request.full_url, "headers": dict(request.header_items()),
            "body": json.loads(request.data) if request.data else None,
        })
        answer = self.routes.get(key)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise urllib.error.HTTPError(request.full_url, 404, "nf", {}, io.BytesIO(b"{}"))
        return FakeResponse(answer)


def http_error(code, message=""):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(json.dumps({"message": message}).encode()))


def trade_route(price):
    return {("GET", "data.alpaca.markets/v2/stocks/VTI/trades/latest"): {"trade": {"p": price}}}


class TestPaperOnly(unittest.TestCase):
    def test_every_trading_call_goes_to_the_paper_host(self):
        fake = FakeAlpaca({
            ("GET", "paper-api.alpaca.markets/v2/account"): {"equity": "100", "cash": "50"},
            ("GET", "paper-api.alpaca.markets/v2/positions"): [],
            ("GET", "paper-api.alpaca.markets/v2/orders"): [],
        })
        alpaca.get_account(KEYS, urlopen=fake)
        alpaca.list_positions(KEYS, urlopen=fake)
        alpaca.list_orders(KEYS, urlopen=fake)
        self.assertTrue(all(c["url"].startswith("https://paper-api.alpaca.markets/") for c in fake.calls))
        self.assertEqual(alpaca.PAPER_URL, "https://paper-api.alpaca.markets")

    def test_keys_are_sent_as_headers_not_in_the_url(self):
        fake = FakeAlpaca({("GET", "paper-api.alpaca.markets/v2/account"): {}})
        alpaca.get_account(KEYS, urlopen=fake)
        call = fake.calls[0]
        self.assertEqual(call["headers"]["Apca-api-key-id"], "PKTEST")
        self.assertEqual(call["headers"]["Apca-api-secret-key"], "secret")
        self.assertNotIn("PKTEST", call["url"])

    def test_the_live_host_is_used_only_when_live_is_asked_for(self):
        fake = FakeAlpaca({
            ("GET", "paper-api.alpaca.markets/v2/account"): {}, ("GET", "api.alpaca.markets/v2/account"): {},
            ("GET", "paper-api.alpaca.markets/v2/positions"): [], ("GET", "paper-api.alpaca.markets/v2/orders"): [],
        })
        alpaca.get_account(KEYS, urlopen=fake)
        alpaca.list_positions(KEYS, urlopen=fake)
        alpaca.list_orders(KEYS, urlopen=fake)
        self.assertTrue(all("paper-api" in c["url"] for c in fake.calls))
        alpaca.get_account(KEYS, mode="live", urlopen=fake)
        self.assertEqual(fake.calls[-1]["url"], "https://api.alpaca.markets/v2/account")

    def test_an_unknown_mode_is_refused_before_any_request(self):
        fake = FakeAlpaca()
        with self.assertRaises(alpaca.AlpacaError):
            alpaca.get_account(KEYS, mode="sandbox", urlopen=fake)
        with self.assertRaises(alpaca.AlpacaError):
            alpaca.preview_order({"symbol": "VTI", "side": "buy", "qty": 1, "type": "limit", "limit_price": 1}, KEYS, mode="x", urlopen=fake)
        self.assertEqual(fake.calls, [])


class TestReading(unittest.TestCase):
    def test_account_positions_orders_are_parsed(self):
        fake = FakeAlpaca({
            ("GET", "paper-api.alpaca.markets/v2/account"): {
                "status": "ACTIVE", "account_number": "PA1", "equity": "100500.5", "last_equity": "100000",
                "cash": "90000", "buying_power": "180000", "trading_blocked": False},
            ("GET", "paper-api.alpaca.markets/v2/positions"): [
                {"symbol": "VTI", "qty": "10", "avg_entry_price": "200", "current_price": "210",
                 "market_value": "2100", "unrealized_pl": "100", "unrealized_plpc": "0.05"}],
            ("GET", "paper-api.alpaca.markets/v2/orders"): [
                {"id": "abc-123", "symbol": "VTI", "side": "buy", "qty": "10", "type": "market", "status": "filled",
                 "filled_qty": "10", "filled_avg_price": "200", "submitted_at": "2026-10-01T14:30:00Z"}],
        })
        acct = alpaca.get_account(KEYS, urlopen=fake)
        self.assertEqual((acct["equity"], acct["cash"], acct["status"]), (100500.5, 90000.0, "ACTIVE"))
        pos = alpaca.list_positions(KEYS, urlopen=fake)
        self.assertEqual((pos[0]["symbol"], pos[0]["qty"], pos[0]["unrealized_pl"]), ("VTI", 10.0, 100.0))
        orders = alpaca.list_orders(KEYS, urlopen=fake)
        self.assertEqual((orders[0]["id"], orders[0]["status"], orders[0]["filled_avg_price"]), ("abc-123", "filled", 200.0))

    def test_readable_errors(self):
        for code, text in ((401, "rejected the keys"), (429, "request limit")):
            fake = FakeAlpaca({("GET", "paper-api.alpaca.markets/v2/account"): http_error(code)})
            with self.assertRaises(alpaca.AlpacaError) as ctx:
                alpaca.get_account(KEYS, urlopen=fake)
            self.assertIn(text, str(ctx.exception))
        fake = FakeAlpaca({("GET", "paper-api.alpaca.markets/v2/account"): urllib.error.URLError("down")})
        with self.assertRaises(alpaca.AlpacaError) as ctx:
            alpaca.get_account(KEYS, urlopen=fake)
        self.assertIn("Couldn't reach Alpaca", str(ctx.exception))


class TestOrderValidation(unittest.TestCase):
    def good(self, **over):
        return {"symbol": "vti", "side": "buy", "qty": "10", "type": "market", **over}

    def test_a_good_order_is_normalised(self):
        clean = alpaca.clean_order(self.good())
        self.assertEqual(clean, {"symbol": "VTI", "side": "buy", "qty": 10, "type": "market",
                                 "limit_price": None, "time_in_force": "day"})

    def test_bad_orders_are_refused_in_plain_words(self):
        bad = [
            ({"symbol": ""}, "symbol"), ({"symbol": "VT I$"}, "symbol"), ({"side": "short"}, "buy or sell"),
            ({"qty": "0"}, "whole number"), ({"qty": "1.5"}, "whole number"), ({"qty": "abc"}, "how many"),
            ({"qty": str(alpaca.MAX_SHARES + 1)}, "at most"), ({"type": "stop"}, "market or limit"),
            ({"type": "limit"}, "limit price"), ({"type": "limit", "limit_price": "-1"}, "limit price"),
            ({"time_in_force": "forever"}, "open"),
        ]
        for over, text in bad:
            with self.subTest(over=over):
                with self.assertRaises(alpaca.AlpacaError) as ctx:
                    alpaca.clean_order(self.good(**over))
                self.assertIn(text, str(ctx.exception))

    def test_a_market_order_is_always_day_only(self):
        self.assertEqual(alpaca.clean_order(self.good(time_in_force="gtc"))["time_in_force"], "day")
        self.assertEqual(alpaca.clean_order(self.good(type="limit", limit_price="9.999", time_in_force="gtc"))["time_in_force"], "gtc")


class TestPreviewThenPlace(unittest.TestCase):
    def setUp(self):
        alpaca._previews.clear()

    def order(self, **over):
        return {"symbol": "VTI", "side": "buy", "qty": "10", "type": "market", **over}

    def test_preview_prices_the_order_without_sending_it(self):
        fake = FakeAlpaca(trade_route(250.0))
        preview = alpaca.preview_order(self.order(), KEYS, urlopen=fake)
        self.assertEqual((preview["price"], preview["estimate"]), (250.0, 2500.0))
        self.assertTrue(preview["token"])
        self.assertTrue(all(c["method"] == "GET" for c in fake.calls))

    def test_place_sends_exactly_the_previewed_order_and_the_token_is_single_use(self):
        fake = FakeAlpaca({**trade_route(250.0), ("POST", "paper-api.alpaca.markets/v2/orders"): {"id": "o-1", "status": "accepted"}})
        token = alpaca.preview_order(self.order(), KEYS, urlopen=fake)["token"]
        placed = alpaca.place_order(token, KEYS, urlopen=fake)
        post = [c for c in fake.calls if c["method"] == "POST"][0]
        self.assertEqual(post["url"], "https://paper-api.alpaca.markets/v2/orders")
        self.assertEqual({k: post["body"][k] for k in ("symbol", "qty", "side", "type", "time_in_force")},
                         {"symbol": "VTI", "qty": "10", "side": "buy", "type": "market", "time_in_force": "day"})
        self.assertTrue(post["body"]["client_order_id"].startswith("fs-"))
        self.assertEqual((placed["id"], placed["status"]), ("o-1", "accepted"))
        with self.assertRaises(alpaca.AlpacaError):
            alpaca.place_order(token, KEYS, urlopen=fake)  # replay
        self.assertEqual(len([c for c in fake.calls if c["method"] == "POST"]), 1)

    def test_an_unknown_or_expired_token_places_nothing(self):
        fake = FakeAlpaca(trade_route(250.0))
        with self.assertRaises(alpaca.AlpacaError):
            alpaca.place_order("nope", KEYS, urlopen=fake)
        token = alpaca.preview_order(self.order(), KEYS, now=1000.0, urlopen=fake)["token"]
        with self.assertRaises(alpaca.AlpacaError) as ctx:
            alpaca.place_order(token, KEYS, now=1000.0 + alpaca.PREVIEW_SECONDS + 1, urlopen=fake)
        self.assertIn("expired", str(ctx.exception))
        self.assertFalse([c for c in fake.calls if c["method"] == "POST"])

    def test_the_size_limit_is_enforced_at_preview(self):
        fake = FakeAlpaca(trade_route(5_000.0))
        with self.assertRaises(alpaca.AlpacaError) as ctx:
            alpaca.preview_order(self.order(qty="6"), KEYS, urlopen=fake)  # $30,000
        self.assertIn("limited", str(ctx.exception))
        self.assertFalse(alpaca._previews)

    def test_a_limit_order_is_sized_by_its_own_price(self):
        fake = FakeAlpaca()  # no price feed needed
        preview = alpaca.preview_order(self.order(type="limit", limit_price="100"), KEYS, urlopen=fake)
        self.assertEqual(preview["estimate"], 1000.0)
        self.assertEqual(fake.calls, [])

    def test_a_market_order_with_no_price_cannot_be_sized_so_it_is_refused(self):
        fake = FakeAlpaca()  # trades/latest -> 404
        with self.assertRaises(alpaca.AlpacaError) as ctx:
            alpaca.preview_order(self.order(), KEYS, urlopen=fake)
        self.assertIn("recent price", str(ctx.exception))

    def test_alpacas_own_rejection_is_passed_on_readably(self):
        fake = FakeAlpaca({**trade_route(250.0),
                           ("POST", "paper-api.alpaca.markets/v2/orders"): http_error(422, "insufficient buying power")})
        token = alpaca.preview_order(self.order(), KEYS, urlopen=fake)["token"]
        with self.assertRaises(alpaca.AlpacaError) as ctx:
            alpaca.place_order(token, KEYS, urlopen=fake)
        self.assertIn("insufficient buying power", str(ctx.exception))


class TestLiveOrders(unittest.TestCase):
    def setUp(self):
        alpaca._previews.clear()

    ORDER = {"symbol": "VTI", "side": "buy", "qty": "10", "type": "market"}

    def routes(self):
        return {**trade_route(250.0), ("POST", "api.alpaca.markets/v2/orders"): {"id": "L-1", "status": "accepted"}}

    def test_a_live_order_goes_to_the_live_host_only(self):
        fake = FakeAlpaca(self.routes())
        token = alpaca.preview_order(self.ORDER, KEYS, mode="live", urlopen=fake)["token"]
        placed = alpaca.place_order(token, KEYS, mode="live", urlopen=fake)
        post = [c for c in fake.calls if c["method"] == "POST"][0]
        self.assertEqual(post["url"], "https://api.alpaca.markets/v2/orders")
        self.assertEqual((placed["mode"], placed["estimate"], placed["id"]), ("live", 2500.0, "L-1"))

    def test_a_preview_made_for_one_mode_cannot_place_in_the_other(self):
        fake = FakeAlpaca(self.routes())
        token = alpaca.preview_order(self.ORDER, KEYS, mode="paper", urlopen=fake)["token"]
        with self.assertRaises(alpaca.AlpacaError) as ctx:
            alpaca.place_order(token, KEYS, mode="live", urlopen=fake)
        self.assertIn("different account", str(ctx.exception))
        self.assertFalse([c for c in fake.calls if c["method"] == "POST"])

    def test_the_per_order_limit_can_only_tighten(self):
        fake = FakeAlpaca(self.routes())
        with self.assertRaises(alpaca.AlpacaError) as ctx:
            alpaca.preview_order(self.ORDER, KEYS, mode="live", max_notional=2_000.0, urlopen=fake)  # $2,500
        self.assertIn("limited to $2,000", str(ctx.exception))
        # a "higher" limit never lifts the built-in ceiling
        fake2 = FakeAlpaca(trade_route(5_000.0))
        with self.assertRaises(alpaca.AlpacaError):
            alpaca.preview_order({**self.ORDER, "qty": "6"}, KEYS, mode="live", max_notional=1e9, urlopen=fake2)

    def test_the_daily_limit_is_checked_at_preview_and_again_at_place(self):
        fake = FakeAlpaca(self.routes())
        with self.assertRaises(alpaca.AlpacaError) as ctx:
            alpaca.preview_order(self.ORDER, KEYS, mode="live", daily_remaining=1_000.0, urlopen=fake)
        self.assertIn("today's trading limit", str(ctx.exception))
        token = alpaca.preview_order(self.ORDER, KEYS, mode="live", daily_remaining=3_000.0, urlopen=fake)["token"]
        with self.assertRaises(alpaca.AlpacaError):
            alpaca.place_order(token, KEYS, mode="live", daily_remaining=1_000.0, urlopen=fake)  # spent elsewhere meanwhile
        self.assertFalse([c for c in fake.calls if c["method"] == "POST"])

    def test_preview_details_peeks_without_using_the_token_up(self):
        fake = FakeAlpaca(self.routes())
        token = alpaca.preview_order(self.ORDER, KEYS, mode="live", urlopen=fake)["token"]
        details = alpaca.preview_details(token)
        self.assertEqual((details["symbol"], details["mode"], details["estimate"]), ("VTI", "live", 2500.0))
        self.assertIsNotNone(alpaca.preview_details(token))
        self.assertIsNone(alpaca.preview_details("nope"))
        self.assertIsNone(alpaca.preview_details(token, now=9e12))


class TestCancel(unittest.TestCase):
    def test_cancel_deletes_that_order_on_the_paper_host(self):
        oid = "61e69015-8549-4bfd-b9c3-01e75843f47d"
        fake = FakeAlpaca({("DELETE", f"paper-api.alpaca.markets/v2/orders/{oid}"): {}})
        alpaca.cancel_order(oid, KEYS, urlopen=fake)
        self.assertEqual((fake.calls[0]["method"], fake.calls[0]["url"]),
                         ("DELETE", f"https://paper-api.alpaca.markets/v2/orders/{oid}"))

    def test_a_strange_id_is_refused_before_any_request(self):
        fake = FakeAlpaca()
        with self.assertRaises(alpaca.AlpacaError):
            alpaca.cancel_order("../account", KEYS, urlopen=fake)
        self.assertEqual(fake.calls, [])


class TestKeyStorage(unittest.TestCase):
    def setUp(self):
        self.fake = FakeKeyring()
        self._patches = [
            patch("keyring.get_password", self.fake.get_password),
            patch("keyring.set_password", self.fake.set_password),
            patch("keyring.delete_password", self.fake.delete_password),
        ]
        for p in self._patches:
            p.start()
        secrets_store.clear_vault_cache()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        secrets_store.clear_vault_cache()

    def test_keys_round_trip_and_delete(self):
        self.assertFalse(secrets_store.has_alpaca_keys())
        secrets_store.set_alpaca_keys(" PKABC ", " sec ")
        self.assertTrue(secrets_store.has_alpaca_keys())
        self.assertEqual(secrets_store.get_alpaca_keys(), ("PKABC", "sec"))
        secrets_store.delete_alpaca_keys()
        self.assertFalse(secrets_store.has_alpaca_keys())
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.get_alpaca_keys()

    def test_live_keys_are_a_separate_pair_from_the_practice_keys(self):
        secrets_store.set_alpaca_keys("PKPAPER", "p-sec")
        secrets_store.set_alpaca_keys("AKLIVE", "l-sec", mode="live")
        self.assertEqual(secrets_store.get_alpaca_keys(), ("PKPAPER", "p-sec"))
        self.assertEqual(secrets_store.get_alpaca_keys(mode="live"), ("AKLIVE", "l-sec"))
        secrets_store.delete_alpaca_keys(mode="live")
        self.assertFalse(secrets_store.has_alpaca_keys(mode="live"))
        self.assertTrue(secrets_store.has_alpaca_keys())
        with self.assertRaises(ValueError):
            secrets_store.get_alpaca_keys(mode="other")

    def test_both_parts_are_required(self):
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.set_alpaca_keys("PKABC", "")

    def test_alpaca_keys_do_not_disturb_other_saved_secrets(self):
        secrets_store.set_rentcast_api_key("rc-key")
        secrets_store.set_alpaca_keys("PKABC", "sec")
        secrets_store.delete_alpaca_keys()
        self.assertEqual(secrets_store.get_rentcast_api_key(), "rc-key")


if __name__ == "__main__":
    unittest.main()
