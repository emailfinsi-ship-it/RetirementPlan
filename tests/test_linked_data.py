import unittest

from source.common import db, linked_data
from tests.testing_utils import TempConfigTestCase


def _seed_item(item_key="fidelity_401k", *, products=("investments",), synced_at=None):
    db.upsert_plaid_item(
        item_key=item_key, plaid_item_id=f"item-{item_key}", institution_id="ins_1",
        institution_name="Fidelity", products=list(products), environment="sandbox",
        linked_at="2026-09-01T00:00:00+00:00",
    )
    if synced_at:
        db.mark_plaid_item_synced(item_key, synced_at)


class TestLinkedDataStatus(TempConfigTestCase):
    def test_not_configured_by_default(self):
        status = linked_data.linked_data_status()
        self.assertFalse(status["configured"])
        self.assertEqual(status["item_count"], 0)
        self.assertIsNone(status["last_synced_at"])

    def test_configured_once_an_item_is_linked(self):
        _seed_item()
        status = linked_data.linked_data_status()
        self.assertTrue(status["configured"])
        self.assertEqual(status["item_count"], 1)
        self.assertIsNone(status["last_synced_at"])

    def test_last_synced_at_reflects_most_recent_sync(self):
        _seed_item("item_a", synced_at="2026-09-01T00:00:00+00:00")
        _seed_item("item_b", synced_at="2026-09-05T00:00:00+00:00")
        status = linked_data.linked_data_status()
        self.assertEqual(status["item_count"], 2)
        self.assertEqual(status["last_synced_at"], "2026-09-05T00:00:00+00:00")


class TestReadLinkedAccountBalances(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        _seed_item()

    def test_read_account_balances(self):
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-checking", "name": "Chase", "official_name": "Chase Checking",
            "type": "depository", "subtype": "checking", "mask": "1234",
            "balances": {"current": 5000.00, "available": 4900.00, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-credit", "name": "Chase", "official_name": "Chase Credit Card",
            "type": "credit", "subtype": "credit card", "mask": "9999",
            "balances": {"current": 2000.00, "available": None, "iso_currency_code": "USD"},
        })
        rows = linked_data.read_linked_account_balances()
        self.assertEqual(len(rows), 2)
        by_last4 = {r["last4"]: r for r in rows}
        # "institution" is the parent Item's real institution name
        # ("Fidelity", from _seed_item()'s institution_name) -- NOT the
        # account's own Plaid name/official_name ("Chase" here), which is
        # exposed separately as "account_name". See
        # TestInstitutionIsTheItemsRealName below for the regression this
        # guards against.
        self.assertEqual(by_last4["1234"]["institution"], "Fidelity")
        self.assertEqual(by_last4["1234"]["account_name"], "Chase Checking")
        self.assertEqual(by_last4["1234"]["item_key"], "fidelity_401k")
        self.assertEqual(by_last4["1234"]["balance"], 5000.00)
        # A credit account's balance is signed negative (it's owed, not held).
        self.assertEqual(by_last4["9999"]["balance"], -2000.00)
        # Neither account had an Auth fetch, so no full number yet.
        self.assertIsNone(by_last4["1234"]["account_number"])

    def test_read_account_balances_includes_the_full_account_number_once_auth_synced(self):
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-checking", "name": "Wells Fargo", "official_name": "Wells Fargo Checking",
            "type": "depository", "subtype": "checking", "mask": "6789",
            "balances": {"current": 5_000.0, "available": 4_900.0, "iso_currency_code": "USD"},
        })
        db.set_plaid_account_numbers("acc-checking", account_number="1234567890", routing_number="121000248")
        rows = linked_data.read_linked_account_balances()
        row = next(r for r in rows if r["account_id"] == "acc-checking")
        self.assertEqual(row["account_number"], "1234567890")
        self.assertEqual(row["routing_number"], "121000248")
        self.assertFalse(row["is_tokenized_account_number"])

    def test_read_portfolio_positions(self):
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-brokerage", "name": "Fidelity", "official_name": "Fidelity Brokerage",
            "type": "investment", "subtype": "brokerage", "mask": "5678",
            "balances": {"current": 1500.0, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_holding(item_key="fidelity_401k", holding={
            "account_id": "acc-brokerage", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 10,
            "institution_price": 150, "institution_value": 1500, "cost_basis": 1000,
            "iso_currency_code": "USD",
        })
        rows = linked_data.read_linked_portfolio_positions()
        self.assertEqual(len(rows), 1)
        # security_id is exposed so the dashboard's multi-select
        # bulk-classify UI can post it back on /api/classify-industry.
        self.assertEqual(rows[0]["security_id"], "sec-aapl")
        self.assertEqual(rows[0]["ticker"], "AAPL")
        self.assertEqual(rows[0]["market_value"], 1500.0)
        self.assertEqual(rows[0]["institution"], "Fidelity")
        # An ordinary (non-stock-plan) holding never carries Plaid's
        # vested_value -- market_value falls back to the plain
        # institution_value, and total_value/is_vested_only reflect that.
        self.assertEqual(rows[0]["total_value"], 1500.0)
        self.assertFalse(rows[0]["is_vested_only"])
        # Not classified yet (no security_industries row) -- blank, not
        # an error; the dashboard shows this as "Unclassified"/"Unknown".
        self.assertEqual(rows[0]["industry"], "")

    def test_market_value_uses_vested_value_when_plaid_provides_it(self):
        # A stock-plan holding (an employer RSU/ESPP grant) is reported
        # by Plaid at its FULL institution_value, unvested shares
        # included, with vested_value as a separate, optional field --
        # market_value here should prefer the vested-only figure, while
        # total_value keeps the full grant so a caller can still show it.
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-stockplan", "name": "Stock Plan (AAPL) -2013",
            "type": "investment", "subtype": "stock plan", "mask": "2013",
            "balances": {"current": 1_352_943.76, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_holding(item_key="fidelity_401k", holding={
            "account_id": "acc-stockplan", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 1000,
            "institution_price": 150, "institution_value": 150_000, "cost_basis": 100_000,
            "vested_quantity": 400, "vested_value": 60_000,
        })
        rows = linked_data.read_linked_portfolio_positions()
        self.assertEqual(rows[0]["market_value"], 60_000)
        self.assertEqual(rows[0]["total_value"], 150_000)
        self.assertTrue(rows[0]["is_vested_only"])

    def test_market_value_falls_back_to_institution_value_when_vested_value_is_explicitly_zero(self):
        # 0.0 is a real, meaningful vested_value (nothing has vested
        # yet), distinct from None ("Plaid doesn't provide this split") --
        # must not be treated as falsy/missing.
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-stockplan", "name": "New Grant", "type": "investment",
            "subtype": "stock plan", "mask": "9999", "balances": {"current": 50_000.0},
        })
        db.upsert_plaid_holding(item_key="fidelity_401k", holding={
            "account_id": "acc-stockplan", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 500,
            "institution_price": 150, "institution_value": 75_000, "vested_quantity": 0, "vested_value": 0,
        })
        rows = linked_data.read_linked_portfolio_positions()
        self.assertEqual(rows[0]["market_value"], 0.0)
        self.assertTrue(rows[0]["is_vested_only"])

    def test_institution_is_the_items_real_name_not_the_account_label(self):
        # Regression: this used to read the holding's own account row's
        # Plaid `name` (e.g. "Individual Brokerage") as "institution" --
        # wrong whenever that doesn't happen to read like a bank/brokerage
        # name, and the reason the Linked Positions tab's Institution
        # column/chart could disagree with the Linked Accounts tab (which
        # always used the parent Item's real institution_name) for the
        # very same account.
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-brokerage", "name": "Individual Brokerage",
            "official_name": "Fidelity Brokerage Account",
            "type": "investment", "subtype": "brokerage", "mask": "5678",
            "balances": {"current": 1500.0, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_holding(item_key="fidelity_401k", holding={
            "account_id": "acc-brokerage", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 10,
            "institution_price": 150, "institution_value": 1500, "cost_basis": 1000,
            "iso_currency_code": "USD",
        })
        rows = linked_data.read_linked_portfolio_positions()
        self.assertEqual(rows[0]["institution"], "Fidelity")  # from _seed_item's institution_name
        self.assertEqual(rows[0]["account"], "Fidelity Brokerage Account")  # still the account's own label

    def test_read_portfolio_positions_includes_a_classified_industry(self):
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-brokerage", "name": "Fidelity", "official_name": "Fidelity Brokerage",
            "type": "investment", "subtype": "brokerage", "mask": "5678",
            "balances": {"current": 1500.0, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_holding(item_key="fidelity_401k", holding={
            "account_id": "acc-brokerage", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 10,
            "institution_price": 150, "institution_value": 1500, "cost_basis": 1000,
            "iso_currency_code": "USD",
        })
        db.set_security_industry(security_id="sec-aapl", ticker="AAPL", industry="Consumer Electronics", updated_at="2026-09-13T00:00:00+00:00")
        rows = linked_data.read_linked_portfolio_positions()
        self.assertEqual(rows[0]["industry"], "Consumer Electronics")

    def test_linked_totals(self):
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-checking", "name": "Chase", "official_name": "Chase Checking",
            "type": "depository", "subtype": "checking", "mask": "1234",
            "balances": {"current": 5000.00, "available": None, "iso_currency_code": "USD"},
        })
        db.upsert_plaid_holding(item_key="fidelity_401k", holding={
            "account_id": "acc-checking", "security_id": "sec-aapl", "ticker_symbol": "AAPL",
            "security_name": "Apple Inc", "security_type": "equity", "quantity": 10,
            "institution_price": 150, "institution_value": 1500, "cost_basis": 1000,
            "iso_currency_code": "USD",
        })
        totals = linked_data.linked_totals()
        self.assertEqual(totals["account_balances_total"], 5000.00)
        self.assertEqual(totals["account_count"], 1)
        self.assertEqual(totals["portfolio_market_value_total"], 1500.0)
        self.assertEqual(totals["position_count"], 1)

    def test_no_synced_data_returns_empty_not_error(self):
        self.assertEqual(linked_data.read_linked_account_balances(), [])
        self.assertEqual(linked_data.read_linked_portfolio_positions(), [])

    def test_account_balances_include_account_id_for_linking(self):
        db.upsert_plaid_account(item_key="fidelity_401k", account={
            "account_id": "acc-1", "name": "401k", "official_name": "Fidelity 401k",
            "type": "investment", "subtype": "401k", "mask": "1234",
            "balances": {"current": 500.0, "available": None, "iso_currency_code": "USD"},
        })
        rows = linked_data.read_linked_account_balances()
        self.assertEqual(rows[0]["account_id"], "acc-1")


class TestReadLinkedAccountBalancesInstitutionLabeling(TempConfigTestCase):
    """Regression coverage for the Linked Accounts page's "Institution"
    column showing the wrong thing -- read_linked_account_balances() used
    to just report the account's own Plaid name/official_name as
    "institution", which is wrong whenever that doesn't happen to read
    like a bank name (e.g. "Individual Brokerage", "401(k)", "Roth IRA").
    It now pulls the real institution name from the parent plaid_items
    row instead, same as linkable_accounts() already did (see
    TestLinkableAccounts below) -- and exposes the account's own
    name/official_name separately as "account_name" so that information
    isn't lost, plus "item_key" so a row can be tied back to the Item
    that owns it (surfaced on the Linked Accounts page as its own
    column, one per the user's own request)."""

    def test_institution_is_the_items_real_name_not_the_account_label(self):
        db.upsert_plaid_item(
            item_key="schwab", plaid_item_id="item-schwab", institution_id="ins_2",
            institution_name="Charles Schwab", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="schwab", account={
            "account_id": "acc-roth", "name": "Roth Contributory IRA", "official_name": "Roth Contributory IRA",
            "type": "investment", "subtype": "ira", "mask": "5678",
            "balances": {"current": 42_000.0, "available": None, "iso_currency_code": "USD"},
        })
        rows = linked_data.read_linked_account_balances()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["institution"], "Charles Schwab")
        self.assertEqual(rows[0]["account_name"], "Roth Contributory IRA")
        self.assertEqual(rows[0]["item_key"], "schwab")

    def test_two_items_are_not_confused_with_each_other(self):
        db.upsert_plaid_item(
            item_key="schwab", plaid_item_id="item-schwab", institution_id="ins_2",
            institution_name="Charles Schwab", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_item(
            item_key="wells_fargo_checking", plaid_item_id="item-wf", institution_id="ins_3",
            institution_name="Wells Fargo", products=["auth"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="schwab", account={
            "account_id": "acc-roth", "name": "Roth IRA", "type": "investment", "subtype": "ira", "mask": "5678",
            "balances": {"current": 42_000.0}, "iso_currency_code": "USD",
        })
        db.upsert_plaid_account(item_key="wells_fargo_checking", account={
            "account_id": "acc-checking", "name": "Checking", "type": "depository", "subtype": "checking", "mask": "6789",
            "balances": {"current": 5_000.0}, "iso_currency_code": "USD",
        })
        rows = {r["account_id"]: r for r in linked_data.read_linked_account_balances()}
        self.assertEqual(rows["acc-roth"]["institution"], "Charles Schwab")
        self.assertEqual(rows["acc-roth"]["item_key"], "schwab")
        self.assertEqual(rows["acc-checking"]["institution"], "Wells Fargo")
        self.assertEqual(rows["acc-checking"]["item_key"], "wells_fargo_checking")

    def test_account_with_no_official_name_falls_back_to_plain_name(self):
        db.upsert_plaid_item(
            item_key="schwab", plaid_item_id="item-schwab", institution_id="ins_2",
            institution_name="Charles Schwab", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="schwab", account={
            "account_id": "acc-roth", "name": "Roth IRA", "type": "investment", "subtype": "ira", "mask": "5678",
            "balances": {"current": 42_000.0}, "iso_currency_code": "USD",
        })
        row = linked_data.read_linked_account_balances()[0]
        self.assertEqual(row["account_name"], "Roth IRA")


class TestLinkableAccounts(TempConfigTestCase):
    def test_labels_use_the_parent_items_institution_name_not_the_account_name(self):
        db.upsert_plaid_item(
            item_key="schwab", plaid_item_id="item-schwab", institution_id="ins_2",
            institution_name="Charles Schwab", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="schwab", account={
            "account_id": "acc-roth", "name": "Roth Contributory IRA", "official_name": "Roth Contributory IRA",
            "type": "investment", "subtype": "ira", "mask": "5678",
            "balances": {"current": 42_000.0, "available": None, "iso_currency_code": "USD"},
        })
        accounts = linked_data.linkable_accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["account_id"], "acc-roth")
        self.assertEqual(accounts[0]["institution"], "Charles Schwab")
        self.assertEqual(accounts[0]["label"], "Roth Contributory IRA")
        self.assertEqual(accounts[0]["balance"], 42_000.0)
        self.assertIsNone(accounts[0]["account_number"])  # investment account -- Auth doesn't cover these

    def test_includes_the_full_account_number_once_auth_synced(self):
        db.upsert_plaid_item(
            item_key="wells_fargo_checking", plaid_item_id="item-wf-checking", institution_id="ins_3",
            institution_name="Wells Fargo", products=["auth"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="wells_fargo_checking", account={
            "account_id": "acc-checking", "name": "Checking", "official_name": "Everyday Checking",
            "type": "depository", "subtype": "checking", "mask": "6789",
            "balances": {"current": 5_000.0, "available": None, "iso_currency_code": "USD"},
        })
        db.set_plaid_account_numbers("acc-checking", account_number="1234567890", routing_number="121000248")
        accounts = linked_data.linkable_accounts()
        self.assertEqual(accounts[0]["account_number"], "1234567890")
        self.assertEqual(accounts[0]["routing_number"], "121000248")

    def test_liability_type_balance_is_signed_negative(self):
        db.upsert_plaid_item(
            item_key="chase", plaid_item_id="item-chase", institution_id="ins_3",
            institution_name="Chase", products=["transactions"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="chase", account={
            "account_id": "acc-cc", "name": "Chase Credit Card", "official_name": "Chase Credit Card",
            "type": "credit", "subtype": "credit card", "mask": "9999",
            "balances": {"current": 1_200.0, "available": None, "iso_currency_code": "USD"},
        })
        accounts = linked_data.linkable_accounts()
        self.assertEqual(accounts[0]["balance"], -1_200.0)

    def test_empty_when_nothing_linked(self):
        self.assertEqual(linked_data.linkable_accounts(), [])

    def test_exposes_type_subtype_and_detected_tax_treatment(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-fidelity", institution_id="ins_4",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-401k", "name": "APPLE 401(K) PLAN", "official_name": None,
            "type": "investment", "subtype": "401k", "mask": "1111",
            "balances": {"current": 250_000.0, "available": None, "iso_currency_code": "USD"},
        })
        accounts = linked_data.linkable_accounts()
        self.assertEqual(accounts[0]["type"], "investment")
        self.assertEqual(accounts[0]["subtype"], "401k")
        self.assertEqual(accounts[0]["detected_tax_treatment"], "tax_deferred")

    def test_detected_tax_treatment_is_none_for_a_brokerage_subtype(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-fidelity", institution_id="ins_4",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-brokerage", "name": "BrokerageLink", "official_name": None,
            "type": "investment", "subtype": "brokerage", "mask": "2222",
            "balances": {"current": 80_000.0, "available": None, "iso_currency_code": "USD"},
        })
        accounts = linked_data.linkable_accounts()
        self.assertIsNone(accounts[0]["detected_tax_treatment"])


class TestDetectedTaxTreatment(unittest.TestCase):
    """source.common.linked_data.detected_tax_treatment on its own --
    the raw subtype -> tax-bucket mapping, independent of the database
    (see TestLinkableAccounts above for it exposed through a real
    linked account)."""

    def test_roth_subtype_maps_to_roth(self):
        self.assertEqual(linked_data.detected_tax_treatment("roth"), "roth")

    def test_401k_subtype_maps_to_tax_deferred(self):
        self.assertEqual(linked_data.detected_tax_treatment("401k"), "tax_deferred")

    def test_ira_subtype_maps_to_tax_deferred(self):
        self.assertEqual(linked_data.detected_tax_treatment("ira"), "tax_deferred")

    def test_is_case_and_whitespace_insensitive(self):
        self.assertEqual(linked_data.detected_tax_treatment("  ROTH  "), "roth")

    def test_brokerage_stock_plan_and_crypto_are_unrecognized(self):
        self.assertIsNone(linked_data.detected_tax_treatment("brokerage"))
        self.assertIsNone(linked_data.detected_tax_treatment("stock plan"))
        self.assertIsNone(linked_data.detected_tax_treatment("crypto exchange"))

    def test_blank_or_none_subtype_is_unrecognized(self):
        self.assertIsNone(linked_data.detected_tax_treatment(""))
        self.assertIsNone(linked_data.detected_tax_treatment(None))


if __name__ == "__main__":
    unittest.main()
