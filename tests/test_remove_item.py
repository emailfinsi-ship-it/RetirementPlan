import unittest
from unittest.mock import MagicMock, patch

from source.collector import remove_item
from source.common import db, secrets_store
from tests.testing_utils import PlaidVaultTestCase


def _seed_item(item_key="fidelity_401k", *, credential_profile="primary"):
    db.upsert_plaid_item(
        item_key=item_key, plaid_item_id="item-1", institution_id="ins_1", institution_name="Fidelity",
        products=["investments"], environment="sandbox", credential_profile=credential_profile,
        linked_at="2026-09-01T00:00:00+00:00",
    )
    secrets_store.set_item_access_token(item_key, "access-token-abc")


class TestRemoveItem(PlaidVaultTestCase):
    def test_removes_local_state_and_calls_plaid(self):
        _seed_item()
        client = MagicMock()
        with patch("source.collector.remove_item.build_client", return_value=client):
            remove_item.remove_item("fidelity_401k")
        client.item_remove.assert_called_once()
        self.assertIsNone(db.get_plaid_item("fidelity_401k"))
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.get_item_access_token("fidelity_401k")

    def test_plaid_call_failure_does_not_block_local_cleanup(self):
        _seed_item()
        client = MagicMock()
        client.item_remove.side_effect = RuntimeError("network down")
        with patch("source.collector.remove_item.build_client", return_value=client):
            remove_item.remove_item("fidelity_401k")  # should not raise
        self.assertIsNone(db.get_plaid_item("fidelity_401k"))

    def test_unknown_item_key_raises(self):
        with self.assertRaises(ValueError):
            remove_item.remove_item("never_existed")

    def test_removes_with_the_items_own_credential_profile(self):
        _seed_item("second_app_item", credential_profile="secondary")
        client = MagicMock()
        with patch("source.collector.remove_item.build_client", return_value=client) as mock_build:
            remove_item.remove_item("second_app_item")
        mock_build.assert_called_once_with("sandbox", profile="secondary")


if __name__ == "__main__":
    unittest.main()
