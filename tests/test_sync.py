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
            accounts, holdings, numbers, transactions = sync._sync_one_item(db.get_plaid_item("fidelity_401k"))
        self.assertEqual((accounts, holdings, numbers, transactions), (1, 0, 0, 0))
        client.investments_holdings_get.assert_not_called()
        client.auth_get.assert_not_called()
        client.transactions_sync.assert_not_called()
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
            accounts, holdings, numbers, transactions = sync._sync_one_item(db.get_plaid_item("fidelity_401k"))
        self.assertEqual((accounts, holdings, numbers, transactions), (1, 1, 0, 0))
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
            accounts, holdings, numbers, transactions = sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        self.assertEqual((accounts, holdings, numbers, transactions), (1, 0, 1, 0))
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
            accounts, holdings, numbers, transactions = sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        self.assertEqual((accounts, holdings, numbers, transactions), (1, 0, 0, 0))
        self.assertEqual(len(db.list_plaid_accounts()), 1)  # the balance still landed


def _fake_transaction(transaction_id, *, account_id="acc-checking", amount=42.50, date="2026-09-01",
                       name="Coffee Shop", primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_COFFEE", pending=False):
    return {
        "transaction_id": transaction_id, "account_id": account_id, "amount": amount, "date": date,
        "name": name, "merchant_name": name, "pending": pending, "iso_currency_code": "USD",
        "personal_finance_category": {"primary": primary, "detailed": detailed},
    }


class TestSyncTransactions(PlaidVaultTestCase):
    """source.collector.sync._sync_transactions_for_item -- Plaid's
    cursor-based transactions_sync, gated by "transactions" being in an
    Item's own products (same pattern as "auth"/"investments" above)."""

    def test_does_not_call_transactions_sync_when_not_requested(self):
        _seed_item("fidelity_401k", products=("investments",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {"accounts": []}
        client.investments_holdings_get.return_value.to_dict.return_value = {"securities": [], "holdings": []}
        with patch("source.collector.sync.build_client", return_value=client):
            sync._sync_one_item(db.get_plaid_item("fidelity_401k"))
        client.transactions_sync.assert_not_called()

    def test_pulls_added_transactions_and_stores_them(self):
        _seed_item("wells_fargo_checking", products=("transactions",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {"accounts": []}
        client.transactions_sync.return_value.to_dict.return_value = {
            "added": [_fake_transaction("txn-1")], "modified": [], "removed": [],
            "next_cursor": "cursor-1", "has_more": False,
        }
        with patch("source.collector.sync.build_client", return_value=client):
            accounts, holdings, numbers, transactions = sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        self.assertEqual((accounts, holdings, numbers, transactions), (0, 0, 0, 1))
        rows = db.list_plaid_transactions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["transaction_id"], "txn-1")
        self.assertEqual(rows[0]["category"], "Food And Drink Coffee")
        self.assertEqual(rows[0]["excluded_from_expense"], 0)
        self.assertEqual(db.get_transactions_cursor("wells_fargo_checking"), "cursor-1")

    def test_transfers_and_credit_card_payments_are_excluded_by_default(self):
        _seed_item("wells_fargo_checking", products=("transactions",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {"accounts": []}
        client.transactions_sync.return_value.to_dict.return_value = {
            "added": [
                _fake_transaction("txn-transfer", primary="TRANSFER_OUT", detailed="TRANSFER_OUT_ACCOUNT_TRANSFER"),
                _fake_transaction("txn-cc-payment", primary="LOAN_PAYMENTS", detailed="LOAN_PAYMENTS_CREDIT_CARD_PAYMENT"),
                _fake_transaction("txn-groceries", primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_GROCERIES"),
            ],
            "modified": [], "removed": [], "next_cursor": "cursor-1", "has_more": False,
        }
        with patch("source.collector.sync.build_client", return_value=client):
            sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        by_id = {r["transaction_id"]: r for r in db.list_plaid_transactions()}
        self.assertEqual(by_id["txn-transfer"]["excluded_from_expense"], 1)
        self.assertEqual(by_id["txn-cc-payment"]["excluded_from_expense"], 1)
        self.assertEqual(by_id["txn-groceries"]["excluded_from_expense"], 0)

    def test_paginates_until_has_more_is_false_and_stores_the_final_cursor(self):
        _seed_item("wells_fargo_checking", products=("transactions",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {"accounts": []}
        client.transactions_sync.return_value.to_dict.side_effect = [
            {"added": [_fake_transaction("txn-1")], "modified": [], "removed": [],
             "next_cursor": "cursor-page-1", "has_more": True},
            {"added": [_fake_transaction("txn-2")], "modified": [], "removed": [],
             "next_cursor": "cursor-page-2", "has_more": False},
        ]
        with patch("source.collector.sync.build_client", return_value=client):
            accounts, holdings, numbers, transactions = sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        self.assertEqual(transactions, 2)
        self.assertEqual(client.transactions_sync.call_count, 2)
        self.assertEqual(db.get_transactions_cursor("wells_fargo_checking"), "cursor-page-2")

    def test_a_later_sync_reuses_the_stored_cursor(self):
        _seed_item("wells_fargo_checking", products=("transactions",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {"accounts": []}
        client.transactions_sync.return_value.to_dict.return_value = {
            "added": [_fake_transaction("txn-1")], "modified": [], "removed": [],
            "next_cursor": "cursor-1", "has_more": False,
        }
        with patch("source.collector.sync.build_client", return_value=client):
            sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
            sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        second_call_request = client.transactions_sync.call_args_list[1].args[0]
        self.assertEqual(second_call_request.cursor, "cursor-1")

    def test_removed_transactions_are_deleted(self):
        _seed_item("wells_fargo_checking", products=("transactions",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {"accounts": []}
        client.transactions_sync.return_value.to_dict.side_effect = [
            {"added": [_fake_transaction("txn-1")], "modified": [], "removed": [],
             "next_cursor": "cursor-1", "has_more": False},
            {"added": [], "modified": [], "removed": [{"transaction_id": "txn-1"}],
             "next_cursor": "cursor-2", "has_more": False},
        ]
        with patch("source.collector.sync.build_client", return_value=client):
            sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
            self.assertEqual(len(db.list_plaid_transactions()), 1)
            sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        self.assertEqual(len(db.list_plaid_transactions()), 0)

    def test_a_failing_transactions_sync_does_not_block_the_balance_sync(self):
        _seed_item("wells_fargo_checking", products=("transactions",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {
            "accounts": [{"account_id": "acc-checking", "name": "Checking", "type": "depository",
                          "subtype": "checking", "mask": "6789", "balances": {"current": 5_000.0}}],
        }
        client.transactions_sync.side_effect = RuntimeError("PRODUCT_NOT_READY")
        with patch("source.collector.sync.build_client", return_value=client):
            accounts, holdings, numbers, transactions = sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        self.assertEqual((accounts, transactions), (1, 0))
        self.assertEqual(len(db.list_plaid_accounts()), 1)

    def test_a_manual_category_edit_survives_a_later_resync(self):
        _seed_item("wells_fargo_checking", products=("transactions",))
        client = MagicMock()
        client.accounts_balance_get.return_value.to_dict.return_value = {"accounts": []}
        client.transactions_sync.return_value.to_dict.return_value = {
            "added": [_fake_transaction("txn-1")], "modified": [], "removed": [],
            "next_cursor": "cursor-1", "has_more": False,
        }
        with patch("source.collector.sync.build_client", return_value=client):
            sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        db.update_plaid_transaction_category(["txn-1"], "My Own Label")

        client.transactions_sync.return_value.to_dict.return_value = {
            "added": [], "modified": [_fake_transaction("txn-1", pending=False)], "removed": [],
            "next_cursor": "cursor-2", "has_more": False,
        }
        with patch("source.collector.sync.build_client", return_value=client):
            sync._sync_one_item(db.get_plaid_item("wells_fargo_checking"))
        self.assertEqual(db.list_plaid_transactions()[0]["category"], "My Own Label")


class TestSyncAll(PlaidVaultTestCase):
    def test_one_failing_item_does_not_block_others(self):
        _seed_item("good_item", products=())
        _seed_item("bad_item", products=())

        def fake_sync_one(item_row):
            if item_row["item_key"] == "bad_item":
                raise RuntimeError("revoked token")
            return (1, 0, 0, 0)

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
            "transactions": 0, "industries_classified": 0, "synced_at": result["synced_at"],
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
