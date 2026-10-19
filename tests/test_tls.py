"""Secure connections use the Mac's own trusted certificates."""
import unittest

from source.common import tls


class TlsTests(unittest.TestCase):
    def test_friendly_error_explains_certificate_failures(self):
        raw = "HTTPSConnectionPool(host='sandbox.plaid.com'): SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed'))"
        msg = tls.friendly_error(raw)
        self.assertIn("work or school network", msg)
        self.assertIn("another network", msg)
        self.assertIn("CERTIFICATE_VERIFY_FAILED", msg)   # details kept for support

    def test_other_errors_pass_through(self):
        self.assertEqual(tls.friendly_error("Item key is required."), "Item key is required.")
        self.assertEqual(tls.friendly_error(""), "")

    def test_requirements_list_truststore(self):
        from pathlib import Path
        text = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text()
        self.assertIn("truststore", text)


if __name__ == "__main__":
    unittest.main()
