"""Move to another Mac: one encrypted file that carries your Keychain items
(Plaid keys and tokens, your login password and recovery key), your database
and, if you like, your backups.

The file is locked with a passphrase you choose (scrypt + Fernet), so it is
safe to AirDrop or put on a USB stick. Without the passphrase it is
unreadable. On the new Mac, the welcome screen's "Moving from another Mac?"
reads it back in; no new password is needed, you log in with your old one.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

import keyring
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from source.common import app_settings, auth_store, backup, branding, config, secrets_store
from source.common.auth_store import AUTH_ACCOUNT
from source.common.secrets_store import VAULT_ACCOUNT, keychain_service

MAGIC = b"FINSITRANSFER1\n"
FORMAT = "finsi-transfer-v1"
# Settings that describe THIS Mac's folders or network, so they are not carried over.
_LOCAL_ONLY_SETTINGS = {"data_dir", "output_dir", "bind_host"}


def _fernet(passphrase: str, salt: bytes) -> Fernet:
    key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def _check_passphrase(passphrase: str) -> str:
    value = passphrase or ""
    if len(value.strip()) < 8:
        raise ValueError("The passphrase must be at least 8 characters.")
    return value


def _pack_file(path: Path) -> str:
    return base64.b64encode(gzip.compress(path.read_bytes())).decode("ascii")


def _unpack_to(text: str, dest: Path) -> None:
    dest.write_bytes(gzip.decompress(base64.b64decode(text)))


def build_bundle(passphrase: str, *, include_backups: bool = True) -> bytes:
    """The encrypted transfer file as bytes."""
    _check_passphrase(passphrase)
    service = keychain_service()
    payload: dict = {
        "format": FORMAT,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "app_version": branding.APP_VERSION,
        "keychain": {
            "vault": keyring.get_password(service, VAULT_ACCOUNT),
            "auth": keyring.get_password(service, AUTH_ACCOUNT),
        },
        "settings": {k: v for k, v in app_settings._read().items() if k not in _LOCAL_ONLY_SETTINGS},
        "database": None,
        "backups": {},
    }
    if config.DB_PATH.exists():
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snapshot.db"
            backup._copy_db_safely(config.DB_PATH, snap)      # a consistent copy, even while the app is open
            payload["database"] = _pack_file(snap)
    if include_backups:
        for b in backup.list_backups():
            payload["backups"][b["filename"]] = _pack_file(Path(b["path"]))
    salt = os.urandom(16)
    token = _fernet(passphrase, salt).encrypt(json.dumps(payload).encode("utf-8"))
    return MAGIC + salt + token


def read_bundle(blob: bytes, passphrase: str) -> dict:
    """Decrypts and checks a transfer file. ValueError with a plain message if it cannot."""
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 17:
        raise ValueError("That is not a transfer file from this app.")
    body = blob[len(MAGIC):]
    try:
        raw = _fernet(passphrase or "", body[:16]).decrypt(body[16:])
        payload = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError):
        raise ValueError("Wrong passphrase, or the file is damaged.") from None
    if payload.get("format") != FORMAT:
        raise ValueError("That transfer file is from a newer or unknown version.")
    return payload


def summary(payload: dict) -> dict:
    """What a transfer file holds, in words (used before and after importing)."""
    return {
        "created": payload.get("created", ""),
        "app_version": payload.get("app_version", ""),
        "has_plaid_keys": bool(payload.get("keychain", {}).get("vault")),
        "has_password": bool(payload.get("keychain", {}).get("auth")),
        "has_database": bool(payload.get("database")),
        "backups": len(payload.get("backups") or {}),
    }


def apply_bundle(payload: dict, *, replace_existing: bool = False) -> dict:
    """Writes a transfer file's contents onto this Mac. Refuses (changing
    nothing) if this Mac already has a password or data, unless
    replace_existing is set."""
    from source.common import db

    if not replace_existing:
        if auth_store.is_password_set() or keyring.get_password(keychain_service(), VAULT_ACCOUNT):
            raise ValueError("This Mac already has a password or saved keys. Nothing was changed.")
        if config.DB_PATH.exists() and not db.setup_needed():
            raise ValueError("This Mac already has data. Nothing was changed.")
    service = keychain_service()
    keychain = payload.get("keychain") or {}
    for account, key in ((VAULT_ACCOUNT, "vault"), (AUTH_ACCOUNT, "auth")):
        if keychain.get(key):
            keyring.set_password(service, account, keychain[key])
    secrets_store.clear_vault_cache()
    auth_store.clear_auth_cache()
    for k, v in (payload.get("settings") or {}).items():
        if k not in _LOCAL_ONLY_SETTINGS:
            data = app_settings._read()
            data[k] = v
            app_settings._write(data)
    config.ensure_directories()
    restored_db = False
    if payload.get("database"):
        with tempfile.TemporaryDirectory() as tmp:
            incoming = Path(tmp) / "incoming.db"
            _unpack_to(payload["database"], incoming)
            checked = backup.verify_backup(incoming)
            if not checked["ok"]:
                raise ValueError("The database in the file did not pass its health check: " + (checked["error"] or "unknown problem"))
            src = sqlite3.connect(str(incoming))
            try:
                dst = sqlite3.connect(str(config.DB_PATH))
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
        restored_db = True
    db.init_db()
    count = 0
    for name, text in (payload.get("backups") or {}).items():
        safe = Path(name).name
        if safe != name or not safe.startswith("retirement_plan-") or not safe.endswith(".db"):
            continue
        folder = backup.backup_dir()
        folder.mkdir(parents=True, exist_ok=True)
        _unpack_to(text, folder / safe)
        count += 1
    return {**summary(payload), "database": restored_db, "backups": count}
