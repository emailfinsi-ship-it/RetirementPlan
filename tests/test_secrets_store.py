import json
import unittest

from source.common import secrets_store
from tests.testing_utils import PlaidVaultTestCase


class TestClientIdAndSecret(PlaidVaultTestCase):
    def test_client_id_round_trip(self):
        secrets_store.set_plaid_client_id("client-abc")
        self.assertEqual(secrets_store.get_plaid_client_id(), "client-abc")

    def test_client_id_missing_raises(self):
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.get_plaid_client_id()

    def test_client_id_blank_rejected(self):
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.set_plaid_client_id("   ")

    def test_secret_is_scoped_per_environment(self):
        secrets_store.set_plaid_secret("sandbox-secret", env="sandbox")
        secrets_store.set_plaid_secret("prod-secret", env="production")
        self.assertEqual(secrets_store.get_plaid_secret(env="sandbox"), "sandbox-secret")
        self.assertEqual(secrets_store.get_plaid_secret(env="production"), "prod-secret")

    def test_secret_missing_for_env_raises(self):
        secrets_store.set_plaid_secret("sandbox-secret", env="sandbox")
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.get_plaid_secret(env="production")


class TestSecondCredentialProfile(PlaidVaultTestCase):
    """A second, independent Plaid app's credentials ("secondary") --
    see source.common.secrets_store's module docstring."""

    def test_defaults_to_primary_profile(self):
        secrets_store.set_plaid_client_id("client-primary")
        self.assertEqual(secrets_store.get_plaid_client_id(profile="primary"), "client-primary")

    def test_profiles_are_isolated(self):
        secrets_store.set_plaid_client_id("client-primary", profile="primary")
        secrets_store.set_plaid_client_id("client-secondary", profile="secondary")
        secrets_store.set_plaid_secret("primary-sandbox", env="sandbox", profile="primary")
        secrets_store.set_plaid_secret("secondary-sandbox", env="sandbox", profile="secondary")

        self.assertEqual(secrets_store.get_plaid_client_id(profile="primary"), "client-primary")
        self.assertEqual(secrets_store.get_plaid_client_id(profile="secondary"), "client-secondary")
        self.assertEqual(secrets_store.get_plaid_secret(env="sandbox", profile="primary"), "primary-sandbox")
        self.assertEqual(secrets_store.get_plaid_secret(env="sandbox", profile="secondary"), "secondary-sandbox")

    def test_secondary_missing_raises_even_when_primary_is_set(self):
        secrets_store.set_plaid_client_id("client-primary", profile="primary")
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.get_plaid_client_id(profile="secondary")

    def test_unknown_profile_rejected_on_write(self):
        with self.assertRaises(ValueError):
            secrets_store.set_plaid_client_id("client-x", profile="tertiary")

    def test_unknown_profile_rejected_on_read(self):
        with self.assertRaises(ValueError):
            secrets_store.get_plaid_client_id(profile="tertiary")


class TestOldFlatVaultShapeMigrates(PlaidVaultTestCase):
    """A vault saved before the Secondary profile existed (flat
    plaid_client_id/plaid_secrets, no plaid_profiles) must keep working
    -- its one client_id/secrets become the "primary" profile the first
    time this module reads it."""

    def _seed_old_shape_vault(self, *, client_id="old-client", secrets=None, access_tokens=None):
        raw = {
            "version": 1,
            "plaid_client_id": client_id,
            "plaid_secrets": secrets or {},
            "access_tokens": access_tokens or {},
        }
        self.fake_keyring.set_password(secrets_store.keychain_service(), secrets_store.VAULT_ACCOUNT, json.dumps(raw))
        secrets_store.clear_vault_cache()

    def test_old_client_id_reads_back_under_primary(self):
        self._seed_old_shape_vault(client_id="old-client")
        self.assertEqual(secrets_store.get_plaid_client_id(profile="primary"), "old-client")

    def test_old_secrets_read_back_under_primary(self):
        self._seed_old_shape_vault(secrets={"sandbox": "old-sandbox-secret"})
        self.assertEqual(secrets_store.get_plaid_secret(env="sandbox", profile="primary"), "old-sandbox-secret")

    def test_old_vault_has_nothing_in_secondary(self):
        self._seed_old_shape_vault(client_id="old-client")
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.get_plaid_client_id(profile="secondary")

    def test_access_tokens_survive_migration_untouched(self):
        self._seed_old_shape_vault(access_tokens={"fidelity_401k": "token-abc"})
        self.assertEqual(secrets_store.get_item_access_token("fidelity_401k"), "token-abc")

    def test_setting_secondary_after_migration_does_not_disturb_primary(self):
        self._seed_old_shape_vault(client_id="old-client")
        secrets_store.set_plaid_client_id("new-secondary", profile="secondary")
        self.assertEqual(secrets_store.get_plaid_client_id(profile="primary"), "old-client")
        self.assertEqual(secrets_store.get_plaid_client_id(profile="secondary"), "new-secondary")


class TestAccessTokens(PlaidVaultTestCase):
    def test_token_round_trip(self):
        secrets_store.set_item_access_token("fidelity_401k", "access-token-abc")
        self.assertEqual(secrets_store.get_item_access_token("fidelity_401k"), "access-token-abc")

    def test_token_missing_raises(self):
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.get_item_access_token("nope")

    def test_delete_token_removes_only_that_item(self):
        secrets_store.set_item_access_token("item_a", "token-a")
        secrets_store.set_item_access_token("item_b", "token-b")
        secrets_store.delete_item_access_token("item_a")
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.get_item_access_token("item_a")
        self.assertEqual(secrets_store.get_item_access_token("item_b"), "token-b")

    def test_delete_last_secret_removes_the_keychain_item_entirely(self):
        secrets_store.set_item_access_token("only_item", "token")
        secrets_store.delete_item_access_token("only_item")
        raw = self.fake_keyring.get_password(secrets_store.keychain_service(), secrets_store.VAULT_ACCOUNT)
        self.assertIsNone(raw)

    def test_delete_missing_token_does_not_raise(self):
        secrets_store.delete_item_access_token("never_existed")  # should be a no-op


class TestVaultPresence(PlaidVaultTestCase):
    def test_empty_vault_presence(self):
        presence = secrets_store.vault_presence()
        self.assertTrue(presence.readable)
        self.assertFalse(presence.profiles["primary"].has_client_id)
        self.assertFalse(presence.profiles["secondary"].has_client_id)
        self.assertEqual(presence.profiles["primary"].secret_envs, ())
        self.assertEqual(presence.item_keys, ())

    def test_presence_reflects_saved_fields_without_leaking_values(self):
        secrets_store.set_plaid_client_id("client-abc")
        secrets_store.set_plaid_secret("s1", env="sandbox")
        secrets_store.set_item_access_token("item_a", "token-a")
        presence = secrets_store.vault_presence()
        self.assertTrue(presence.profiles["primary"].has_client_id)
        self.assertEqual(presence.profiles["primary"].secret_envs, ("sandbox",))
        self.assertEqual(presence.item_keys, ("item_a",))

    def test_presence_is_independent_per_profile(self):
        secrets_store.set_plaid_client_id("client-primary", profile="primary")
        secrets_store.set_plaid_secret("secondary-secret", env="production", profile="secondary")
        presence = secrets_store.vault_presence()
        self.assertTrue(presence.profiles["primary"].has_client_id)
        self.assertFalse(presence.profiles["secondary"].has_client_id)
        self.assertEqual(presence.profiles["primary"].secret_envs, ())
        self.assertEqual(presence.profiles["secondary"].secret_envs, ("production",))

    def test_corrupt_vault_raises_on_probe(self):
        self.fake_keyring.set_password(secrets_store.keychain_service(), secrets_store.VAULT_ACCOUNT, "not json")
        with self.assertRaises(secrets_store.VaultCorruptError):
            secrets_store.probe_vault()


class TestVaultCacheIsolatedAcrossTests(PlaidVaultTestCase):
    """Guards against a regression where the module-level _vault_cache
    leaks a previous test's secrets into this one."""

    def test_starts_empty(self):
        with self.assertRaises(secrets_store.SecretNotFoundError):
            secrets_store.get_plaid_client_id()


if __name__ == "__main__":
    unittest.main()
