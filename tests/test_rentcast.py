import io
import json
import unittest
import urllib.error

from source.collector import rentcast
from source.common import secrets_store
from tests.testing_utils import PlaidVaultTestCase


class _Response:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(payload=None, error=None):
    captured = {}

    def opener(request, timeout=None):
        captured["url"] = request.full_url
        captured["key"] = request.get_header("X-api-key")
        if error:
            raise error
        return _Response(payload)

    opener.captured = captured
    return opener


class TestFetchValueEstimate(unittest.TestCase):
    def test_returns_price_and_range_and_sends_key_and_address(self):
        opener = _opener({"price": 512345, "priceRangeLow": 480000, "priceRangeHigh": 540000})
        result = rentcast.fetch_value_estimate("123 Main St, San Jose, CA 95112", "KEY", urlopen=opener)
        self.assertEqual(result, {"price": 512345.0, "low": 480000.0, "high": 540000.0})
        self.assertEqual(opener.captured["key"], "KEY")
        self.assertIn("api.rentcast.io/v1/avm/value?address=123+Main+St", opener.captured["url"])

    def test_missing_range_is_none(self):
        result = rentcast.fetch_value_estimate("1 A St", "K", urlopen=_opener({"price": 100}))
        self.assertEqual(result, {"price": 100.0, "low": None, "high": None})

    def test_blank_address_is_a_readable_error(self):
        with self.assertRaises(rentcast.RentCastError):
            rentcast.fetch_value_estimate("  ", "K", urlopen=_opener({"price": 1}))

    def test_http_errors_become_readable_messages(self):
        for code, text in ((401, "rejected the API key"), (404, "couldn't find"), (429, "limit"), (500, "HTTP 500")):
            err = urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))
            with self.subTest(code=code):
                with self.assertRaises(rentcast.RentCastError) as ctx:
                    rentcast.fetch_value_estimate("1 A St", "K", urlopen=_opener(error=err))
                self.assertIn(text, str(ctx.exception))

    def test_network_failure_and_empty_answer(self):
        with self.assertRaises(rentcast.RentCastError):
            rentcast.fetch_value_estimate("1 A St", "K", urlopen=_opener(error=urllib.error.URLError("down")))
        with self.assertRaises(rentcast.RentCastError):
            rentcast.fetch_value_estimate("1 A St", "K", urlopen=_opener({"price": 0}))
        with self.assertRaises(rentcast.RentCastError):
            rentcast.fetch_value_estimate("1 A St", "K", urlopen=_opener({}))


class TestRentCastKey(PlaidVaultTestCase):
    def test_key_round_trips_through_the_vault_and_survives_other_secrets(self):
        self.assertFalse(secrets_store.has_rentcast_api_key())
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.get_rentcast_api_key()
        secrets_store.set_rentcast_api_key("  abc123 ")
        secrets_store.set_item_access_token("item", "tok")
        secrets_store.clear_vault_cache()
        self.assertEqual(secrets_store.get_rentcast_api_key(), "abc123")
        self.assertTrue(secrets_store.has_rentcast_api_key())
        secrets_store.delete_item_access_token("item")   # the key alone keeps the vault alive
        self.assertEqual(secrets_store.get_rentcast_api_key(), "abc123")
        secrets_store.delete_rentcast_api_key()
        self.assertFalse(secrets_store.has_rentcast_api_key())

    def test_empty_key_is_rejected(self):
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.set_rentcast_api_key("  ")


if __name__ == "__main__":
    unittest.main()
