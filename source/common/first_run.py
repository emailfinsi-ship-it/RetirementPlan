"""First launch: make the owner create an admin password and set up the
database before anything else can be used.

Both ways of running the app (the packaged Mac app and the from-source
download) start through source.webapp.dashboard.run(), which switches this
on with enforce(). Until a password exists, every page sends you to the
welcome screen and every save is refused. The tests and the throwaway demo
never switch it on, so they keep working without a login.

"Set up the database" means: show where your data will be kept, let you
pick a different folder, then create the database file there. If a
database with your data already exists (an older install), it is kept
exactly as it is and only the password is added.
"""

from __future__ import annotations

import os
from pathlib import Path

from source.common import auth_store, config

_enforced = False


def enforce(on: bool = True) -> None:
    global _enforced
    _enforced = bool(on)


def required() -> bool:
    """True while the very first setup still has to be done."""
    if not _enforced or config.DEMO:
        return False
    return not auth_store.is_password_set()


def existing_database() -> bool:
    """True when this is an older install that already holds the user's data."""
    from source.common import db

    try:
        return config.DB_PATH.exists() and not db.setup_needed()
    except Exception:
        return False


def validate_folder(raw: str) -> Path:
    """Turns what was typed into a folder we can write to, or explains why not."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Type a folder, or leave the suggested one.")
    folder = Path(text).expanduser()
    if not folder.is_absolute():
        raise ValueError("Use the full folder path, for example /Users/you/MyPlanData.")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        raise ValueError("That folder cannot be written to. Pick another one.") from None
    return folder.resolve()


def complete(password: str, confirm: str | None, data_dir: str | None = None) -> dict:
    """Validates everything first, then creates the database and saves the
    password last -- so a mistake leaves the app still in first-launch mode."""
    from source.common import db

    value = (password or "").strip()
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if confirm is None or confirm != password:
        raise ValueError("Passwords don't match.")

    keep_existing = existing_database()
    target = None
    if data_dir and not keep_existing:
        target = validate_folder(data_dir)
        if target == config.DATA_DIR.resolve():
            target = None

    if target is not None:
        old_db = config.DB_PATH
        was_empty = old_db.exists() and db.setup_needed()
        config.set_data_dir(str(target))
        if was_empty and old_db != config.DB_PATH:
            try:
                os.remove(old_db)   # our own empty starter file; nothing of yours is in it
            except OSError:
                pass
    config.ensure_directories()
    db.init_db()
    auth_store.set_password(value)
    key = auth_store.new_recovery_key()
    return {"data_dir": str(config.DATA_DIR), "kept_existing": keep_existing, "recovery_key": key}
