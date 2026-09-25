import unittest
from unittest.mock import MagicMock, patch

from source.collector import sync
from source.common import config, db, secrets_store
from tests.testing_utils import PlaidVaultTestCase


def _seed_item(item_key="fidelity_401k", *, products=("investments",), environment="sandbox", credential_profile="primary"):
    db.upsert_plaid_item(
        item_key=item_key, plaid_item_id=f"item-{item_key}", institution_id="ins_1",
        institution_name="Fidelity", products=list(products), environment=environment,
        credential_profile=credential_profile, linked_at="2026-09-01T00:00:00+00:00",
    )
    secrets_store.set_item_access_token(item_key, "access-token-abc")


class TestSyncOneItem(PlaidVaultTestCase):
    def test_pulls_balances_only_when_investments_not_requested(self):
        _seed_item(products=())
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {
            "accounts": [{"account_id": "acc-1", "name": "Checking", "type": "depository",
                          "subtype": "checking", "mask": "1234", "balances": {"current": 100.0}}],
        }
        with patch("source.collector.sync.build_client", return_value=client):
            accounts, holdings, numbers = sync._sync_one_item(db.get_plaid_item("fidelity_401k"))
        self.assertEqual((accounts, holdings, numbers), (1, 0, 0))
        client.investments_holdings_get.assert_not_called()
        client.auth_get.assert_not_called()
        self.assertEqual(len(db.list_plaid_accounts()), 1)

    def test_pulls_holdings_when_investments_requested(self):
        _seed_item(products=("investments",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {
            "accounts": [{"account_id": "acc-1", "name": "Brokerage", "type": "investment",
                          "subtype": "brokerage", "mask": "5678", "balances": {"current": 1500.0}}],
        }
        client.investments_holdings_get.return_value.to_dict.return_value = {
            "securities": [{"security_id": "sec-1", "ticker_symbol": "AAPL", "name": "Apple Inc", "type": "equity"}],
            "holdings": [{"account_id": "acc-1", "security_id": "sec-1", "quantity": 10,
                          "institution_price": 150, "institution_value": 1500, "cost_basis": 1000}],
        }
        with patch("source.collector.sync.build_client", return_value=client):
            accounts, holdings, numbers = sync._sync_one_item(db.get_plaid_item("fidelity_401k"))
        self.assertEqual((accounts, holdings, numbers), (1, 1, 0))
        rows = db.list_plaid_holdings()
        self.assertEqual(rows[0]["ticker_symbol"], "AAPL")
        self.assertEqual(rows[0]["security_name"], "Apple Inc")

    def test_syncs_with_the_items_own_credential_profile(self):
        _seed_item("second_app_item", products=(), credential_profile="secondary")
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {"accounts": []}
        with patch("source.collector.sync.build_client", return_value=client) as mock_build:
            sync._sync_one_item(db.get_plaid_item("second_app_item"))
        mock_build.assert_called_once_with("sandbox", profile="secondary")

    def test_marks_item_synced(self):
        _seed_item(products=())
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {"accounts": []}
        with patch("source.collector.sync.build_client", return_value=client):
            sync._sync_one_item(db.get_plaid_item("fidelity_401k"))
        self.assertIsNotNone(db.get_plaid_item("fidelity_401k")["last_synced_at"])

    def test_pulls_full_account_and_routing_numbers_when_auth_requested(self):
        _seed_item("wells_fargo_checking", products=("auth",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {
            "accounts": [{"account_id": "acc-checking", "name": "Checking", "type": "depository",
                          "subtype": "checking", "mask": "6789", "balances": {"current": 5_000.0}}],
        }
        client.auth_get.return_value.to_dict.return_value = {
            "numbers": {"ach": [{
                "account_id": "acc-checking", "account": "1234567890", "routing": "121000248",
                "is_tokenized_account_number": False,
            }]},
        }
        with patch("source.collector.sync.build_client", return_value=client):
            accounts, holdings, numbers = sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        self.assertEqual((accounts, holdings, numbers), (1, 0, 1))
        row = db.get_plaid_account("acc-checking")
        self.assertEqual(row["account_number"], "1234567890")
        self.assertEqual(row["routing_number"], "121000248")
        self.assertFalse(row["is_tokenized_account_number"])

    def test_does_not_call_auth_when_not_requested(self):
        _seed_item("fidelity_401k", products=("investments",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {"accounts": []}
        client.investments_holdings_get.return_value.to_dict.return_value = {"securities": [], "holdings": []}
        with patch("source.collector.sync.build_client", return_value=client):
            sync._sync_one_item(db.get_plaid_item("fidelity_401k"))
        client.auth_get.assert_not_called()

    def test_a_failing_auth_call_does_not_block_the_balance_sync_that_already_succeeded(self):
        _seed_item("wells_fargo_checking", products=("auth",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {
            "accounts": [{"account_id": "acc-checking", "name": "Checking", "type": "depository",
                          "subtype": "checking", "mask": "6789", "balances": {"current": 5_000.0}}],
        }
        client.auth_get.side_effect = RuntimeError("PRODUCT_NOT_READY")
        with patch("source.collector.sync.build_client", return_value=client):
            accounts, holdings, numbers = sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        self.assertEqual((accounts, holdings, numbers), (1, 0, 0))
        self.assertEqual(len(db.list_plaid_accounts()), 1)  # the balance still landed


class TestSyncAll(PlaidVaultTestCase):
    def test_one_failing_item_does_not_block_others(self):
        _seed_item("good_item", products=())
        _seed_item("bad_item", products=())

        def fake_sync_one(item_row):
            if item_row["item_key"] == "bad_item":
                raise RuntimeError("revoked token")
            return (1, 0, 0)

        with patch("source.collector.sync._sync_one_item", side_effect=fake_sync_one):
            result = sync.sync_all()

        self.assertEqual(result["items_synced"], ["good_item"])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["item_key"], "bad_item")
        self.assertEqual(result["accounts"], 1)

    def test_regenerates_export_files(self):
        _seed_item(products=())
        with patch("source.collector.sync.build_client") as build_client:
            build_client.return_value.accounts_balance_get.return_value.to_dict.return_value = {"accounts": []}
            sync.sync_all()
        self.assertTrue(config.account_balances_csv_path().exists())
        self.assertTrue(config.portfolio_positions_csv_path().exists())

    def test_no_items_returns_clean_summary(self):
        result = sync.sync_all()
        self.assertEqual(result, {
            "items_synced": [], "errors": [], "accounts": 0, "holdings": 0, "account_numbers": 0,
            "industries_classified": 0, "synced_at": result["synced_at"],
        })

    def test_classifies_industries_for_synced_holdings(self):
        _seed_item("fidelity_401k", products=("investments",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {
            "accounts": [{"account_id": "acc-brokerage", "name": "Brokerage", "type": "investment",
                          "subtype": "brokerage", "mask": "5678", "balances": {"current": 1500.0}}],
        }
        client.investments_holdings_get.return_value.to_dict.return_value = {
            "securities": [{"security_id": "sec-aapl", "ticker_symbol": "AAPL", "name": "Apple Inc", "type": "equity"}],
            "holdings": [{"account_id": "acc-brokerage", "security_id": "sec-aapl", "quantity": 10,
                          "institution_price": 150, "institution_value": 1500, "cost_basis": 1000}],
        }
        with patch("source.collector.sync.build_client", return_value=client), \
             patch("source.collector.sync_industries._fetch_industry", return_value="Consumer Electronics"), \
             patch.dict("sys.modules", {"yfinance": object()}):
            result = sync.sync_all()
        self.assertEqual(result["industries_classified"], 1)
        self.assertEqual(db.get_security_industries(), {"sec-aapl": "Consumer Electronics"})


if __name__ == "__main__":
    unittest.main()
