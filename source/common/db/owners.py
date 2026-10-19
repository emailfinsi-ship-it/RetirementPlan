"""Who owns each retirement account -- the plan owner ("self") or the
spouse -- so the Monte Carlo/Drawdown engines can compute each person's
own Required Minimum Distribution from their own balance and birth year
rather than treating every 401k/IRA as one pool owned by one person.

Two places an owner lives, mirroring the two ways an account enters the
plan: an Assets-tab row carries its own `assets.owner` column (edited like
any other line-item field), while a live Plaid investment account that
ISN'T tied to an Asset row has no row to hang an owner on, so it gets an
entry in the small `account_owners` table here instead.

'' means Unassigned -- the default for everything that existed before
this feature. The engine models Unassigned under the plan owner's own
birth year (exactly as every account was modeled before), and the
Drawdown Planning page flags any Unassigned Tax-deferred money so it gets
assigned deliberately rather than silently left that way.
"""

from __future__ import annotations

from source.common.db.connection import _now, connect

# The two people in the plan, as shown on screen. The stored owner values
# stay "self"/"spouse" so renaming never touches saved data; the display
# names and whether there is a second person at all are household
# settings (the meta table), edited on the Setup tab.
DEFAULT_SELF_NAME = "Person 1"
DEFAULT_SPOUSE_NAME = "Person 2"
_META_SELF_NAME = "household_self_name"
_META_SPOUSE_NAME = "household_spouse_name"
_META_HAS_SPOUSE = "household_has_spouse"
_MAX_NAME_LENGTH = 40
_VALID_OWNERS = {"", "self", "spouse"}


def _meta(key: str) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def self_name() -> str:
    return (_meta(_META_SELF_NAME) or "").strip() or DEFAULT_SELF_NAME


def spouse_name() -> str:
    return (_meta(_META_SPOUSE_NAME) or "").strip() or DEFAULT_SPOUSE_NAME


def has_spouse() -> bool:
    """Whether the household has a second person. Defaults to yes so a
    database from before this setting existed behaves exactly as it did."""
    return (_meta(_META_HAS_SPOUSE) or "1").strip() != "0"


def household() -> dict:
    """{"self_name", "spouse_name", "has_spouse"} -- one read for pages."""
    return {"self_name": self_name(), "spouse_name": spouse_name(), "has_spouse": has_spouse()}


def set_household(*, self_name: str, spouse_name: str, has_spouse: bool) -> None:
    """Saves the household's display names and whether there is a second
    person. Names are trimmed; a blank name falls back to the default."""
    values = {
        _META_SELF_NAME: (self_name or "").strip()[:_MAX_NAME_LENGTH],
        _META_SPOUSE_NAME: (spouse_name or "").strip()[:_MAX_NAME_LENGTH],
        _META_HAS_SPOUSE: "1" if has_spouse else "0",
    }
    with connect() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def owner_options() -> tuple[tuple[str, str], ...]:
    """(stored value, display label) pairs for every Owner dropdown --
    "" (Unassigned) first, then the first person, then the second one when
    the household has one."""
    options = [("", "Unassigned"), ("self", self_name())]
    if has_spouse():
        options.append(("spouse", spouse_name()))
    return tuple(options)


def owner_label(value: str) -> str:
    return dict(owner_options()).get(value, "Unassigned")


def normalize_owner(raw) -> str:
    """'self'/'spouse'/'' for a valid value (case/whitespace-insensitive);
    anything else -- None, garbage, an unknown name -- is Unassigned
    rather than an error, since this is only ever fed UI-selected values
    and a blank/odd one should just mean "not assigned"."""
    value = str(raw or "").strip().lower()
    return value if value in _VALID_OWNERS else ""


def set_account_owner(account_id: str, owner: str) -> None:
    """Records which person a live linked account (one NOT tied to an
    Assets-tab row) belongs to. Assigning '' (Unassigned) removes the row
    entirely, so the table only ever holds real assignments."""
    account_id = (account_id or "").strip()
    if not account_id:
        raise ValueError("An account id is required.")
    owner = normalize_owner(owner)
    with connect() as conn:
        if owner == "":
            conn.execute("DELETE FROM account_owners WHERE account_id = ?", (account_id,))
            return
        conn.execute(
            "INSERT INTO account_owners (account_id, owner, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(account_id) DO UPDATE SET owner = excluded.owner, updated_at = excluded.updated_at",
            (account_id, owner, _now()),
        )


def get_account_owners() -> dict[str, str]:
    """{account_id: 'self'|'spouse'} for every explicitly assigned
    unlinked account -- an account with no entry is Unassigned."""
    with connect() as conn:
        rows = conn.execute("SELECT account_id, owner FROM account_owners").fetchall()
        return {r["account_id"]: r["owner"] for r in rows}
