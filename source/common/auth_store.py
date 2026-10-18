"""Login password + session-cookie signing for the dashboard.

Added when this program became reachable from outside the Mac it runs
on (see source.webapp.dashboard's module docstring on bind_host) --
until then, anyone who could reach 127.0.0.1:8898 was already sitting
at this Mac, so a login screen would have protected against nothing.
Once the server can be reached over the network (a home Wi-Fi bind, or
a Tailscale Funnel URL reachable from anywhere), it's the only thing
standing between the internet and this program's financial data, so it
has to hold up on its own.

Storage: same Keychain-backed vault pattern as
source.common.secrets_store (a single JSON blob under one Keychain
item, "RetirementPlan-auth" this time so a Plaid-vault reset never
touches the login password or vice versa), holding:
  - password_hash / password_salt / password_iterations -- PBKDF2-HMAC-
    SHA256 of the password the user chose. The plaintext password is
    never stored, ever -- only this salted hash.
  - session_secret -- a random 32-byte key, generated once the first
    time a password is set, used to HMAC-sign session cookies (see
    issue_session_token/verify_session_token below). Regenerating it
    (which changing the password does, deliberately) invalidates every
    session cookie anyone's browser is currently holding -- the
    "log out everywhere" a password change should always do.

Sessions are stateless: a cookie is just
base64(json({"exp": <unix timestamp>})) + "." + hex(HMAC-SHA256 of that
payload, keyed by session_secret). Verifying a cookie is just
recomputing that HMAC and comparing (constant-time) -- no server-side
session table, so a session survives the dashboard process restarting,
and nothing needs cleaning up when one expires (it just stops verifying).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

import keyring

from source.common.secrets_store import keychain_service

AUTH_ACCOUNT = "auth"

_PBKDF2_ITERATIONS = 200_000
_SESSION_LIFETIME_SECONDS = 30 * 24 * 60 * 60  # 30 days -- a personal single-user app's
# session doesn't need to expire aggressively; logging in again every
# month on a phone you use daily would just be friction with no real
# security benefit (the session_secret rotation on password change is
# what actually revokes access, not a short expiry).

_lock_cache: dict | None = None


def _empty_vault() -> dict:
    return {
        "version": 1,
        "password_hash": "",
        "password_salt": "",
        "password_iterations": 0,
        "session_secret": "",
    }


def _load_vault() -> dict:
    global _lock_cache
    if _lock_cache is not None:
        return _lock_cache
    raw = keyring.get_password(keychain_service(), AUTH_ACCOUNT)
    if raw is None:
        _lock_cache = _empty_vault()
        return _lock_cache
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        _lock_cache = _empty_vault()
        return _lock_cache
    vault = _empty_vault()
    vault.update({k: parsed.get(k, vault[k]) for k in vault})
    _lock_cache = vault
    return _lock_cache


def _save_vault(vault: dict) -> None:
    global _lock_cache
    keyring.set_password(keychain_service(), AUTH_ACCOUNT, json.dumps(vault))
    _lock_cache = vault


def clear_auth_cache() -> None:
    """Test-only escape hatch (same role as secrets_store.clear_vault_cache)
    -- forces the next read to hit the Keychain again instead of the
    in-process cache."""
    global _lock_cache
    _lock_cache = None


def is_password_set() -> bool:
    if os.environ.get("FINSI_DEMO") == "1":
        return False   # demo mode: throwaway data, no login screen
    return bool(_load_vault().get("password_hash"))


def set_password(new_password: str) -> None:
    """Sets (or changes) the login password. Deliberately regenerates
    session_secret every time, including on a first-time set -- changing
    the password always invalidates every previously-issued session
    cookie, the "log out everywhere" a password change should do."""
    value = (new_password or "").strip()
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    vault = _load_vault()
    vault["password_hash"] = digest.hex()
    vault["password_salt"] = salt.hex()
    vault["password_iterations"] = _PBKDF2_ITERATIONS
    vault["session_secret"] = os.urandom(32).hex()
    _save_vault(vault)


def verify_password(candidate: str) -> bool:
    vault = _load_vault()
    if not vault.get("password_hash"):
        return False
    try:
        salt = bytes.fromhex(vault["password_salt"])
        iterations = int(vault["password_iterations"])
        expected = bytes.fromhex(vault["password_hash"])
    except (ValueError, KeyError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", (candidate or "").encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


def _session_secret() -> bytes:
    vault = _load_vault()
    secret = vault.get("session_secret") or ""
    if not secret:
        raise RuntimeError("No password set yet -- there's no session secret to sign with.")
    return bytes.fromhex(secret)


def issue_session_token() -> str:
    """A fresh signed session cookie value, valid for
    _SESSION_LIFETIME_SECONDS from now. Call after verify_password
    succeeds (see source.webapp.dashboard's /api/login handler)."""
    payload = json.dumps({"exp": int(time.time()) + _SESSION_LIFETIME_SECONDS}).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(_session_secret(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_session_token(token: str | None) -> bool:
    """True if `token` is a session cookie value this vault's current
    session_secret actually signed, and it hasn't expired yet. False for
    anything else (missing cookie, tampered value, expired, or no
    password set at all -- e.g. right after a password change, every
    previously-issued cookie stops verifying immediately since
    session_secret rotated)."""
    if not token or "." not in token:
        return False
    payload_b64, _, signature = token.partition(".")
    try:
        secret = _session_secret()
    except RuntimeError:
        return False
    expected_signature = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return False
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        exp = int(payload["exp"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return False
    return time.time() < exp
