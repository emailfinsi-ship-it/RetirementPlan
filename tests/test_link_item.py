import unittest
from unittest.mock import MagicMock, patch

from source.collector import link_item
from source.common import db, secrets_store
from tests.testing_utils import PlaidVaultTestCase


class TestLinkRealItem(PlaidVaultTestCase):
    def test_stores_token_and_item_metadata_on_success(self):
        client = MagicMock()
        client.link_token_create.return_value = {"link_token": "link-token-abc"}
        client.item_public_token_exchange.return_value = {
            "access_token": "access-token-xyz", "item_id": "plaid-item-1",
        }
        fake_result = link_item._LinkResult()
        fake_result.public_token = "public-token-abc"
        fake_result.metadata = {"institution": {"institution_id": "ins_1", "name": "Fidelity"}}

        with patch("source.collector.link_item.build_client", return_value=client), \
             patch("source.collector.link_item._run_local_link", return_value=fake_result):
            plaid_item_id = link_item.link_real_item(
                "fidelity_401k", products=["investments"], environment="sandbox",
            )

        self.assertEqual(plaid_item_id, "plaid-item-1")
        self.assertEqual(secrets_store.get_item_access_token("fidelity_401k"), "access-token-xyz")
        row = db.get_plaid_item("fidelity_401k")
        self.assertEqual(row["plaid_item_id"], "plaid-item-1")
        self.assertEqual(row["institution_name"], "Fidelity")
        self.assertEqual(row["environment"], "sandbox")
        self.assertEqual(row["products"], "investments")

    def test_defaults_products_to_investments(self):
        client = MagicMock()
        client.link_token_create.return_value = {"link_token": "link-token-abc"}
        client.item_public_token_exchange.return_value = {"access_token": "t", "item_id": "i"}
        fake_result = link_item._LinkResult()
        fake_result.public_token = "public-token-abc"

        with patch("source.collector.link_item.build_client", return_value=client), \
             patch("source.collector.link_item._run_local_link", return_value=fake_result) as run_local:
            link_item.link_real_item("k")

        self.assertEqual(db.get_plaid_item("k")["products"], "investments")
        run_local.assert_called_once()

    def test_link_timeout_propagates_and_stores_nothing(self):
        client = MagicMock()
        client.link_token_create.return_value = {"link_token": "link-token-abc"}
        with patch("source.collector.link_item.build_client", return_value=client), \
             patch("source.collector.link_item._run_local_link", side_effect=TimeoutError("timed out")):
            with self.assertRaises(TimeoutError):
                link_item.link_real_item("fidelity_401k")
        self.assertIsNone(db.get_plaid_item("fidelity_401k"))

    def test_defaults_to_primary_credential_profile(self):
        client = MagicMock()
        client.link_token_create.return_value = {"link_token": "link-token-abc"}
        client.item_public_token_exchange.return_value = {"access_token": "t", "item_id": "i"}
        fake_result = link_item._LinkResult()
        fake_result.public_token = "public-token-abc"

        with patch("source.collector.link_item.build_client", return_value=client) as mock_build, \
             patch("source.collector.link_item._run_local_link", return_value=fake_result):
            link_item.link_real_item("k")

        mock_build.assert_called_once_with("production", profile="primary")
        self.assertEqual(db.get_plaid_item("k")["credential_profile"], "primary")

    def test_links_with_a_named_credential_profile(self):
        client = MagicMock()
        client.link_token_create.return_value = {"link_token": "link-token-abc"}
        client.item_public_token_exchange.return_value = {"access_token": "t", "item_id": "i"}
        fake_result = link_item._LinkResult()
        fake_result.public_token = "public-token-abc"

        with patch("source.collector.link_item.build_client", return_value=client) as mock_build, \
             patch("source.collector.link_item._run_local_link", return_value=fake_result):
            link_item.link_real_item("second_app_item", environment="sandbox", profile="secondary")

        mock_build.assert_called_once_with("sandbox", profile="secondary")
        self.assertEqual(db.get_plaid_item("second_app_item")["credential_profile"], "secondary")


class TestCreateLinkToken(unittest.TestCase):
    def test_requests_a_link_token_for_the_given_products(self):
        client = MagicMock()
        client.link_token_create.return_value = {"link_token": "link-token-abc"}
        token = link_item._create_link_token(client, ["investments"])
        self.assertEqual(token, "link-token-abc")
        client.link_token_create.assert_called_once()


class TestCreateUpdateModeLinkToken(unittest.TestCase):
    def test_requests_a_link_token_with_access_token_and_additional_products(self):
        client = MagicMock()
        client.link_token_create.return_value = {"link_token": "update-link-token-abc"}
        token = link_item._create_update_mode_link_token(client, "access-token-xyz", ["transactions"])
        self.assertEqual(token, "update-link-token-abc")
        request = client.link_token_create.call_args.args[0]
        self.assertEqual(request.access_token, "access-token-xyz")
        self.assertEqual([str(p) for p in request.additional_consented_products], ["transactions"])
        # Update mode requests the NEW product via access_token +
        # additional_consented_products, never a plain `products` list --
        # that's what makes Plaid treat this as "add to an existing Item"
        # instead of trying to open a brand-new Link flow.
        self.assertNotIn("products", request.to_dict())


class TestEnableTransactionsForItem(PlaidVaultTestCase):
    def _seed_item(self, item_key="fidelity_401k", *, products=("investments",), environment="sandbox",
                    credential_profile="primary"):
        db.upsert_plaid_item(
            item_key=item_key, plaid_item_id=f"item-{item_key}", institution_id="ins_1",
            institution_name="Fidelity", products=list(products), environment=environment,
            credential_profile=credential_profile, linked_at="2026-09-01T00:00:00+00:00",
        )
        secrets_store.set_item_access_token(item_key, "access-token-abc")

    def test_adds_transactions_to_the_items_products_on_success(self):
        self._seed_item(products=("investments",))
        client = MagicMock()
        client.link_token_create.return_value = {"link_token": "update-link-token-abc"}
        fake_result = link_item._LinkResult()
        fake_result.public_token = "public-token-abc"

        with patch("source.collector.link_item.build_client", return_value=client), \
             patch("source.collector.link_item._run_local_link", return_value=fake_result) as run_local:
            link_item.enable_transactions_for_item("fidelity_401k")

        run_local.assert_called_once()
        products = set(db.get_plaid_item("fidelity_401k")["products"].split(","))
        self.assertEqual(products, {"investments", "transactions"})
        # Update mode never mints a new access token -- the original one
        # (from the original link, not from this call) is still what's
        # stored, since there's nothing here to exchange a public_token
        # for.
        self.assertEqual(secrets_store.get_item_access_token("fidelity_401k"), "access-token-abc")

    def test_a_link_timeout_leaves_products_unchanged(self):
        self._seed_item(products=("investments",))
        client = MagicMock()
        client.link_token_create.return_value = {"link_token": "update-link-token-abc"}
        with patch("source.collector.link_item.build_client", return_value=client), \
             patch("source.collector.link_item._run_local_link", side_effect=TimeoutError("timed out")):
            with self.assertRaises(TimeoutError):
                link_item.enable_transactions_for_item("fidelity_401k")
        self.assertEqual(db.get_plaid_item("fidelity_401k")["products"], "investments")

    def test_unknown_item_key_raises(self):
        with self.assertRaises(ValueError):
            link_item.enable_transactions_for_item("never_linked")

    def test_uses_the_items_own_credential_profile(self):
        self._seed_item("second_app_item", products=("investments",), environment="sandbox", credential_profile="secondary")
        client = MagicMock()
        client.link_token_create.return_value = {"link_token": "update-link-token-abc"}
        fake_result = link_item._LinkResult()
        fake_result.public_token = "public-token-abc"

        with patch("source.collector.link_item.build_client", return_value=client) as mock_build, \
             patch("source.collector.link_item._run_local_link", return_value=fake_result):
            link_item.enable_transactions_for_item("second_app_item")

        mock_build.assert_called_once_with("sandbox", profile="secondary")
        self.assertEqual(db.get_plaid_item("second_app_item")["credential_profile"], "secondary")


if __name__ == "__main__":
    unittest.main()
