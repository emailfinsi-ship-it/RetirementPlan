import time
import unittest

from source.common import auth_store
from tests.testing_utils import PlaidVaultTestCase


class TestPasswordSetAndVerify(PlaidVaultTestCase):
    def test_no_password_set_initially(self):
        self.assertFalse(auth_store.is_password_set())

    def test_set_password_then_verify_succeeds(self):
        auth_store.set_password("correct horse battery")
        self.assertTrue(auth_store.is_password_set())
        self.assertTrue(auth_store.verify_password("correct horse battery"))

    def test_wrong_password_fails(self):
        auth_store.set_password("correct horse battery")
        self.assertFalse(auth_store.verify_password("wrong password"))

    def test_verify_before_any_password_set_fails(self):
        self.assertFalse(auth_store.verify_password("anything"))

    def test_password_too_short_is_rejected(self):
        with self.assertRaises(ValueError):
            auth_store.set_password("short")
        self.assertFalse(auth_store.is_password_set())

    def test_plaintext_password_is_never_stored(self):
        auth_store.set_password("correct horse battery")
        raw = self.fake_keyring.get_password(auth_store.keychain_service(), auth_store.AUTH_ACCOUNT)
        self.assertNotIn("correct horse battery", raw)

    def test_changing_password_replaces_the_old_one(self):
        auth_store.set_password("first password here")
        auth_store.set_password("second password here")
        self.assertFalse(auth_store.verify_password("first password here"))
        self.assertTrue(auth_store.verify_password("second password here"))


class TestSessionTokens(PlaidVaultTestCase):
    def test_token_issued_after_set_password_verifies(self):
        auth_store.set_password("correct horse battery")
        token = auth_store.issue_session_token()
        self.assertTrue(auth_store.verify_session_token(token))

    def test_missing_token_fails(self):
        auth_store.set_password("correct horse battery")
        self.assertFalse(auth_store.verify_session_token(None))
        self.assertFalse(auth_store.verify_session_token(""))

    def test_tampered_token_fails(self):
        auth_store.set_password("correct horse battery")
        token = auth_store.issue_session_token()
        payload, _, signature = token.partition(".")
        tampered = f"{payload}.{'0' * len(signature)}"
        self.assertFalse(auth_store.verify_session_token(tampered))

    def test_garbage_token_fails(self):
        auth_store.set_password("correct horse battery")
        self.assertFalse(auth_store.verify_session_token("not-a-real-token"))

    def test_expired_token_fails(self):
        auth_store.set_password("correct horse battery")
        real_time = time.time
        token = auth_store.issue_session_token()
        try:
            time.time = lambda: real_time() + auth_store._SESSION_LIFETIME_SECONDS + 60
            self.assertFalse(auth_store.verify_session_token(token))
        finally:
            time.time = real_time

    def test_changing_password_invalidates_every_prior_session(self):
        auth_store.set_password("first password here")
        token = auth_store.issue_session_token()
        self.assertTrue(auth_store.verify_session_token(token))
        auth_store.set_password("second password here")
        self.assertFalse(auth_store.verify_session_token(token))

    def test_token_from_one_vault_does_not_verify_before_any_password(self):
        # Nothing set yet -- issuing should fail outright, not silently
        # sign with an empty/missing secret.
        with self.assertRaises(RuntimeError):
            auth_store.issue_session_token()


if __name__ == "__main__":
    unittest.main()
