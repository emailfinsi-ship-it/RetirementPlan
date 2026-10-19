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
        "viewer_hash": "",
        "viewer_salt": "",
        "viewer_iterations": 0,
        "recovery_hash": "",
        "recovery_salt": "",
        "recovery_iterations": 0,
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


def _check(candidate: str, hash_hex: str, salt_hex: str, iterations) -> bool:
    if not hash_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        digest = hashlib.pbkdf2_hmac("sha256", (candidate or "").encode("utf-8"), salt, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def verify_password(candidate: str) -> bool:
    """True for the OWNER password (the one that can change things)."""
    vault = _load_vault()
    return _check(candidate, vault.get("password_hash", ""), vault.get("password_salt", ""), vault.get("password_iterations", 0))


# ---- the recovery key ----
# A one-time key shown at first launch. It is the only way back in if the
# password is forgotten, and it is stored only as a hash, so it can never be
# shown again -- using it (or asking for a new one) replaces it.

_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I mix-ups


def _normalize_key(raw: str) -> str:
    return "".join(ch for ch in (raw or "").upper() if ch.isalnum())


def has_recovery_key() -> bool:
    return bool(_load_vault().get("recovery_hash"))


def new_recovery_key() -> str:
    """Makes a fresh recovery key, stores its hash (replacing any old one) and
    returns it ONCE, formatted like XXXX-XXXX-XXXX-XXXX-XXXX."""
    import secrets as _secrets

    raw = "".join(_secrets.choice(_RECOVERY_ALPHABET) for _ in range(20))
    salt = os.urandom(16)
    vault = _load_vault()
    vault["recovery_hash"] = hashlib.pbkdf2_hmac("sha256", raw.encode("ascii"), salt, _PBKDF2_ITERATIONS).hex()
    vault["recovery_salt"] = salt.hex()
    vault["recovery_iterations"] = _PBKDF2_ITERATIONS
    _save_vault(vault)
    return "-".join(raw[i:i + 4] for i in range(0, 20, 4))


def verify_recovery_key(candidate: str) -> bool:
    vault = _load_vault()
    return _check(_normalize_key(candidate), vault.get("recovery_hash", ""),
                  vault.get("recovery_salt", ""), vault.get("recovery_iterations", 0))


def reset_password_with_recovery_key(candidate: str, new_password: str) -> str:
    """Sets a new password when the recovery key is right, signs out every old
    session, and returns a NEW recovery key (the used one stops working)."""
    if not verify_recovery_key(candidate):
        raise PermissionError("That recovery key is not right.")
    set_password(new_password)        # also rotates the session secret
    return new_recovery_key()


# ---- the optional view-only ("viewer") login ----
# A second password that can look at everything but change nothing (handy for
# a spouse, an advisor or an accountant). It has its own hash, and its
# sessions are signed with a key that depends on it, so changing or removing
# the viewer password signs every viewer out at once.

def is_viewer_password_set() -> bool:
    return bool(_load_vault().get("viewer_hash"))


def set_viewer_password(new_password: str) -> None:
    value = (new_password or "").strip()
    if len(value) < 8:
        raise ValueError("The viewer password must be at least 8 characters.")
    if not is_password_set():
        raise ValueError("Set your own login password first; the viewer password is a second one next to it.")
    if verify_password(value):
        raise ValueError("The viewer password must be different from your own password.")
    salt = os.urandom(16)
    vault = _load_vault()
    vault["viewer_hash"] = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, _PBKDF2_ITERATIONS).hex()
    vault["viewer_salt"] = salt.hex()
    vault["viewer_iterations"] = _PBKDF2_ITERATIONS
    _save_vault(vault)


def clear_viewer_password() -> None:
    vault = _load_vault()
    vault["viewer_hash"], vault["viewer_salt"], vault["viewer_iterations"] = "", "", 0
    _save_vault(vault)


def login_role(candidate: str) -> str | None:
    """"owner", "viewer" or None for a password typed on the login page."""
    if verify_password(candidate):
        return "owner"
    vault = _load_vault()
    if _check(candidate, vault.get("viewer_hash", ""), vault.get("viewer_salt", ""), vault.get("viewer_iterations", 0)):
        return "viewer"
    return None


def _session_secret() -> bytes:
    vault = _load_vault()
    secret = vault.get("session_secret") or ""
    if not secret:
        raise RuntimeError("No password set yet -- there's no session secret to sign with.")
    return bytes.fromhex(secret)


def _signing_key(role: str) -> bytes:
    secret = _session_secret()
    if role == "viewer":
        # Depends on the viewer password's hash: change or remove it and old viewer cookies stop verifying.
        return hmac.new(secret, ("viewer:" + (_load_vault().get("viewer_hash") or "none")).encode("utf-8"), hashlib.sha256).digest()
    return secret


def issue_session_token(role: str = "owner") -> str:
    """A fresh signed session cookie value, valid for
    _SESSION_LIFETIME_SECONDS from now. Call after the password check
    succeeds (see source.webapp.dashboard's /api/login handler)."""
    role = "viewer" if role == "viewer" else "owner"
    payload = json.dumps({"exp": int(time.time()) + _SESSION_LIFETIME_SECONDS, "role": role}).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(_signing_key(role), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def session_role(token: str | None) -> str | None:
    """"owner" or "viewer" for a valid, unexpired session cookie value,
    else None (missing, tampered, expired, or signed before the password
    last changed). Cookies from before roles existed count as owner."""
    if not token or "." not in token:
        return None
    payload_b64, _, signature = token.partition(".")
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        exp = int(payload["exp"])
        role = "viewer" if payload.get("role") == "viewer" else "owner"
        key = _signing_key(role)
    except (ValueError, KeyError, TypeError, RuntimeError, json.JSONDecodeError):
        return None
    expected_signature = hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None
    if role == "viewer" and not is_viewer_password_set():
        return None
    return role if time.time() < exp else None


def verify_session_token(token: str | None) -> bool:
    """True if `token` is a valid session cookie of either role (see session_role)."""
    return session_role(token) is not None
