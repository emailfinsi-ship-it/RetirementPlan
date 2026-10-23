"""Secret storage for Plaid credentials and per-Item access tokens.

Originally byte-for-byte the same vault shape as FamilyFinanceTracker's
own source.common.secrets_store (one Keychain generic-password item,
service "RetirementPlan", account "vault"). This program has since grown
support for a SECOND Plaid app's credentials (see PROFILES below) --
useful if you've hit a per-app Item limit, or simply have two separate
Plaid developer accounts you want this dashboard to link/sync accounts
under side by side -- so the vault now nests client_id/secrets under a
named "profile" instead of storing one flat client_id. Everything else
(per-Item access tokens) is unaffected and stays exactly as before.

scripts/copy_plaid_credentials_from_familyfinancetracker.py (run once, by
the user, in their own Terminal) copies FamilyFinanceTracker's own
(profile-less) vault into this program's "primary" profile via this
module's public functions -- it's the only supported way credentials move
between the two apps; this module never reads another app's Keychain item
itself.

This is a trimmed copy: no legacy pre-vault migration logic (nothing to
migrate -- this app has never stored secrets any other way, beyond the
flat-to-profiled vault-shape migration in _normalize_vault below).
"""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass, field

import keyring

from source.common import branding

SERVICE_NAME = branding.INTERNAL_ID
VAULT_ACCOUNT = "vault"
KEYCHAIN_SERVICE_ENV = "RP_KEYCHAIN_SERVICE"

# The two Plaid credential profiles this program supports -- see the
# module docstring. Fixed (not user-defined/arbitrary-length) on purpose:
# two covers "I have a second Plaid app" without the extra complexity of
# an open-ended list of profiles nobody asked for. PROFILE_LABELS is the
# human-facing name used on the Setup page.
PROFILES = ("primary", "secondary")
PROFILE_LABELS = {"primary": "Primary", "secondary": "Secondary"}

_lock = threading.Lock()
_vault_cache: dict | None = None


def _running_under_unittest() -> bool:
    if "unittest" in sys.modules:
        return True
    return "unittest" in " ".join(sys.argv).lower()


def keychain_service() -> str:
    """Production default, or a test service so unittest cannot touch the
    live vault. Set RP_KEYCHAIN_SERVICE to override; RP_USE_LIVE_KEYCHAIN=1
    forces the real service even under a test runner (deliberate migration
    testing only)."""
    explicit = os.environ.get(KEYCHAIN_SERVICE_ENV)
    if explicit:
        return explicit
    if os.environ.get("RP_USE_LIVE_KEYCHAIN") == "1":
        return SERVICE_NAME
    if _running_under_unittest():
        return f"{SERVICE_NAME}-test"
    return SERVICE_NAME


def _delete_vault_item() -> None:
    try:
        keyring.delete_password(keychain_service(), VAULT_ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass


class SecretNotFoundError(RuntimeError):
    """Raised when a required secret hasn't been stored yet."""


class VaultCorruptError(RuntimeError):
    """Raised when the Keychain vault item exists but is not valid JSON."""


@dataclass(frozen=True)
class ProfilePresence:
    """Which fields exist for one Plaid credential profile. Never
    includes secret values."""

    has_client_id: bool = False
    secret_envs: tuple[str, ...] = ()


@dataclass(frozen=True)
class VaultPresence:
    """Which fields exist in the vault. Never includes secret values."""

    readable: bool
    profiles: dict = field(default_factory=dict)  # profile name -> ProfilePresence
    item_keys: tuple[str, ...] = ()


def _empty_profile() -> dict:
    return {"client_id": "", "secrets": {}}


def _empty_vault() -> dict:
    return {
        "version": 2,
        "plaid_profiles": {name: _empty_profile() for name in PROFILES},
        "access_tokens": {},
        "rentcast_api_key": "",
        "smtp_password": "",
        "alpaca_keys": {"key_id": "", "secret": ""},
    }


def _vault_has_any_secret(vault: dict) -> bool:
    for profile in (vault.get("plaid_profiles") or {}).values():
        if (profile.get("client_id") or "").strip():
            return True
        if any(str(v).strip() for v in (profile.get("secrets") or {}).values()):
            return True
    if str(vault.get("rentcast_api_key") or "").strip() or str(vault.get("smtp_password") or "").strip():
        return True
    if any(str(v).strip() for v in (vault.get("alpaca_keys") or {}).values()):
        return True
    return any(str(v).strip() for v in (vault.get("access_tokens") or {}).values())


def _normalize_vault(raw: dict) -> dict:
    vault = _empty_vault()
    if "plaid_profiles" in raw:
        # Already the profiled (version 2+) shape.
        raw_profiles = raw.get("plaid_profiles") or {}
        for name in PROFILES:
            p = raw_profiles.get(name) or {}
            vault["plaid_profiles"][name] = {
                "client_id": p.get("client_id") or "",
                "secrets": dict(p.get("secrets") or {}),
            }
    else:
        # Old flat (version 1, pre-multi-profile) shape -- the single
        # client_id/secrets this vault used to store become the
        # "primary" profile, so nobody's existing saved credentials
        # disappear the first time this runs after upgrading.
        vault["plaid_profiles"]["primary"] = {
            "client_id": raw.get("plaid_client_id") or "",
            "secrets": dict(raw.get("plaid_secrets") or {}),
        }
    vault["access_tokens"] = dict(raw.get("access_tokens") or {})
    vault["rentcast_api_key"] = str(raw.get("rentcast_api_key") or "")
    vault["smtp_password"] = str(raw.get("smtp_password") or "")
    alpaca = raw.get("alpaca_keys") or {}
    vault["alpaca_keys"] = {"key_id": str(alpaca.get("key_id") or ""), "secret": str(alpaca.get("secret") or "")}
    return vault


def _check_profile(profile: str) -> str:
    value = (profile or "primary").strip().lower()
    if value not in PROFILES:
        raise ValueError(f"Unknown Plaid credential profile '{profile}'. Expected one of: {', '.join(PROFILES)}.")
    return value


def _load_vault_unlocked() -> dict:
    global _vault_cache
    if _vault_cache is not None:
        return _vault_cache
    raw = keyring.get_password(keychain_service(), VAULT_ACCOUNT)
    if raw is None:
        _vault_cache = _empty_vault()
        return _vault_cache
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VaultCorruptError("The Plaid credential vault is not valid JSON.") from exc
    _vault_cache = _normalize_vault(parsed)
    return _vault_cache


def _save_vault_unlocked(vault: dict) -> None:
    global _vault_cache
    keyring.set_password(keychain_service(), VAULT_ACCOUNT, json.dumps(vault))
    _vault_cache = vault


def clear_vault_cache() -> None:
    global _vault_cache
    _vault_cache = None


def probe_vault() -> None:
    """Raises VaultCorruptError if the vault exists but isn't valid JSON;
    returns None (not the vault) otherwise -- callers that only need to
    know "is it readable" shouldn't be handed secret values."""
    with _lock:
        _load_vault_unlocked()


def vault_presence() -> VaultPresence:
    with _lock:
        vault = _load_vault_unlocked()
    profiles = {}
    for name in PROFILES:
        p = (vault.get("plaid_profiles") or {}).get(name, {})
        profiles[name] = ProfilePresence(
            has_client_id=bool((p.get("client_id") or "").strip()),
            secret_envs=tuple(sorted(k for k, v in (p.get("secrets") or {}).items() if str(v).strip())),
        )
    return VaultPresence(
        readable=True,
        profiles=profiles,
        item_keys=tuple(sorted(k for k, v in (vault.get("access_tokens") or {}).items() if str(v).strip())),
    )


def set_plaid_client_id(client_id: str, *, profile: str = "primary") -> None:
    profile = _check_profile(profile)
    value = (client_id or "").strip()
    if not value:
        raise SecretNotFoundError("Plaid client ID cannot be empty.")
    with _lock:
        vault = _load_vault_unlocked()
        vault["plaid_profiles"][profile]["client_id"] = value
        _save_vault_unlocked(vault)


def get_plaid_client_id(*, profile: str = "primary") -> str:
    profile = _check_profile(profile)
    with _lock:
        value = (_load_vault_unlocked()["plaid_profiles"].get(profile) or {}).get("client_id") or ""
    if not value:
        raise SecretNotFoundError(f"No Plaid client ID saved yet for the {PROFILE_LABELS[profile]} credential profile.")
    return value


def set_plaid_secret(secret: str, *, env: str, profile: str = "primary") -> None:
    profile = _check_profile(profile)
    value = (secret or "").strip()
    if not value:
        raise SecretNotFoundError("Plaid secret cannot be empty.")
    with _lock:
        vault = _load_vault_unlocked()
        vault["plaid_profiles"][profile]["secrets"][env] = value
        _save_vault_unlocked(vault)


def get_plaid_secret(*, env: str, profile: str = "primary") -> str:
    profile = _check_profile(profile)
    with _lock:
        p = _load_vault_unlocked()["plaid_profiles"].get(profile) or {}
        value = (p.get("secrets") or {}).get(env) or ""
    if not value:
        raise SecretNotFoundError(
            f"No Plaid secret saved for environment '{env}' in the {PROFILE_LABELS[profile]} credential profile."
        )
    return value


def set_rentcast_api_key(key: str) -> None:
    """The optional RentCast API key (property value estimates) -- kept in
    the same Keychain vault as the Plaid credentials."""
    value = (key or "").strip()
    if not value:
        raise SecretNotFoundError("RentCast API key cannot be empty.")
    with _lock:
        vault = _load_vault_unlocked()
        vault["rentcast_api_key"] = value
        _save_vault_unlocked(vault)


def get_rentcast_api_key() -> str:
    with _lock:
        value = str(_load_vault_unlocked().get("rentcast_api_key") or "")
    if not value:
        raise SecretNotFoundError("No RentCast API key saved yet. Add one on the Setup tab.")
    return value


def delete_rentcast_api_key() -> None:
    with _lock:
        vault = _load_vault_unlocked()
        vault["rentcast_api_key"] = ""
        if _vault_has_any_secret(vault):
            _save_vault_unlocked(vault)
        else:
            _delete_vault_item()
            clear_vault_cache()


def has_rentcast_api_key() -> bool:
    with _lock:
        return bool(str(_load_vault_unlocked().get("rentcast_api_key") or "").strip())


def set_alpaca_keys(key_id: str, secret: str) -> None:
    """The Alpaca PAPER-trading key pair (Trading tab) -- kept in the same
    Keychain vault as the Plaid credentials, never in the database."""
    key_id, secret = (key_id or "").strip(), (secret or "").strip()
    if not key_id or not secret:
        raise SecretNotFoundError("Both the Alpaca key ID and the secret are needed.")
    with _lock:
        vault = _load_vault_unlocked()
        vault["alpaca_keys"] = {"key_id": key_id, "secret": secret}
        _save_vault_unlocked(vault)


def get_alpaca_keys() -> tuple[str, str]:
    with _lock:
        keys = _load_vault_unlocked().get("alpaca_keys") or {}
    key_id, secret = str(keys.get("key_id") or ""), str(keys.get("secret") or "")
    if not key_id or not secret:
        raise SecretNotFoundError("No Alpaca keys saved yet. Add them on the Trading tab.")
    return key_id, secret


def has_alpaca_keys() -> bool:
    with _lock:
        keys = _load_vault_unlocked().get("alpaca_keys") or {}
        return bool(str(keys.get("key_id") or "").strip() and str(keys.get("secret") or "").strip())


def delete_alpaca_keys() -> None:
    with _lock:
        vault = _load_vault_unlocked()
        vault["alpaca_keys"] = {"key_id": "", "secret": ""}
        if _vault_has_any_secret(vault):
            _save_vault_unlocked(vault)
        else:
            _delete_vault_item()
            clear_vault_cache()


def set_smtp_password(password: str) -> None:
    """The e-mail account password (or app password) used for the weekly
    digest -- kept in the same Keychain vault, never in the database."""
    with _lock:
        vault = _load_vault_unlocked()
        vault["smtp_password"] = password or ""
        if _vault_has_any_secret(vault):
            _save_vault_unlocked(vault)
        else:
            _delete_vault_item()
            clear_vault_cache()


def get_smtp_password() -> str:
    with _lock:
        return str(_load_vault_unlocked().get("smtp_password") or "")


def has_smtp_password() -> bool:
    return bool(get_smtp_password())


def set_item_access_token(item_key: str, token: str) -> None:
    value = (token or "").strip()
    if not value:
        raise SecretNotFoundError("Access token cannot be empty.")
    with _lock:
        vault = _load_vault_unlocked()
        vault["access_tokens"][item_key] = value
        _save_vault_unlocked(vault)


def get_item_access_token(item_key: str) -> str:
    with _lock:
        value = (_load_vault_unlocked().get("access_tokens") or {}).get(item_key) or ""
    if not value:
        raise SecretNotFoundError(f"No access token saved for item '{item_key}'.")
    return value


def delete_item_access_token(item_key: str) -> None:
    with _lock:
        vault = _load_vault_unlocked()
        vault["access_tokens"].pop(item_key, None)
        if _vault_has_any_secret(vault):
            _save_vault_unlocked(vault)
        else:
            _delete_vault_item()
            clear_vault_cache()
