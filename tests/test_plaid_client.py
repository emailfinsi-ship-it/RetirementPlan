import unittest

from plaid.api.plaid_api import PlaidApi

from source.collector.plaid_client import build_client
from source.common import secrets_store
from tests.testing_utils import PlaidVaultTestCase


class TestBuildClient(PlaidVaultTestCase):
    def setUp(self):
        super().setUp()
        secrets_store.set_plaid_client_id("client-abc")
        secrets_store.set_plaid_secret("sandbox-secret", env="sandbox")
        secrets_store.set_plaid_secret("prod-secret", env="production")

    def test_builds_a_plaid_api_client_for_sandbox(self):
        client = build_client("sandbox")
        self.assertIsInstance(client, PlaidApi)

    def test_builds_a_plaid_api_client_for_production(self):
        client = build_client("production")
        self.assertIsInstance(client, PlaidApi)

    def test_unknown_environment_raises(self):
        with self.assertRaises(ValueError):
            build_client("staging")

    def test_defaults_to_config_plaid_env_when_unspecified(self):
        from source.common import config
        client = build_client(None)
        self.assertIsInstance(client, PlaidApi)
        # sanity: whatever environment config.PLAID_ENV resolves to must have a secret saved
        # by setUp, otherwise build_client(None) would raise before reaching this assertion.
        self.assertIn(config.PLAID_ENV, ("sandbox", "production"))


class TestBuildClientWithoutCredentials(PlaidVaultTestCase):
    def test_missing_client_id_raises_secret_not_found(self):
        with self.assertRaises(secrets_store.SecretNotFoundError):
            build_client("sandbox")


class TestBuildClientWithSecondProfile(PlaidVaultTestCase):
    """A second, independent Plaid app's credentials (profile="secondary")
    -- see source.common.secrets_store's module docstring."""

    def setUp(self):
        super().setUp()
        secrets_store.set_plaid_client_id("primary-client", profile="primary")
        secrets_store.set_plaid_secret("primary-secret", env="sandbox", profile="primary")
        secrets_store.set_plaid_client_id("secondary-client", profile="secondary")
        secrets_store.set_plaid_secret("secondary-secret", env="sandbox", profile="secondary")

    def test_builds_a_client_for_the_secondary_profile(self):
        client = build_client("sandbox", profile="secondary")
        self.assertIsInstance(client, PlaidApi)

    def test_secondary_profile_does_not_fall_back_to_primary(self):
        # A profile with no secret saved for the requested environment
        # must raise, not silently borrow the other profile's secret.
        with self.assertRaises(secrets_store.SecretNotFoundError):
            build_client("production", profile="secondary")

    def test_defaults_to_primary_when_profile_unspecified(self):
        client = build_client("sandbox")
        self.assertIsInstance(client, PlaidApi)


if __name__ == "__main__":
    unittest.main()
