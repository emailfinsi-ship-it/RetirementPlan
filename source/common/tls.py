"""Secure connections that work on any Mac.

Python brings its own list of trusted websites. On a work or school network
that inspects traffic (or on a Python that never had its certificates
installed) that list does not include everything the Mac itself trusts, and
every connection to Plaid or Yahoo fails with "certificate verify failed".
use_system_certificates() makes the app trust whatever the Mac's own Keychain
trusts, which is what the browser already does.
"""

from __future__ import annotations


def use_system_certificates() -> bool:
    """True when the Mac's own trust store is now in use."""
    try:
        import truststore

        truststore.inject_into_ssl()
        return True
    except Exception:
        return False


def friendly_error(message: str) -> str:
    """Turns a raw certificate failure into words a person can act on."""
    text = message or ""
    if "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text:
        return (
            "Could not make a secure connection: this Mac does not trust the site's certificate. "
            "This usually means a work or school network, VPN or security filter that inspects web traffic. "
            "Try another network (such as your phone's hotspot) or turn the filter off, then try again. "
            "(Details: " + text[:200] + ")"
        )
    return text
