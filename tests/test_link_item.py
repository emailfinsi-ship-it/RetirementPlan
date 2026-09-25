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


if __name__ == "__main__":
    unittest.main()
