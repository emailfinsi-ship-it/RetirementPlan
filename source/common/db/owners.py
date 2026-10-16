"""Who owns each retirement account -- the plan owner ("self") or the
spouse -- so the Monte Carlo/Drawdown engines can compute each person's
own Required Minimum Distribution from their own balance and birth year
rather than treating every 401k/IRA as one pool owned by one person.

Two places an owner lives, mirroring the two ways an account enters the
plan: an Asset-tab row carries its own `assets.owner` column (edited like
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

# The two people in the plan, as shown on screen. The stored values stay
# "self"/"spouse" so renaming here never touches saved data.
SELF_NAME = "Sri"
SPOUSE_NAME = "Anu"

# (stored value, display label). "" first -- the default.
OWNER_OPTIONS: tuple[tuple[str, str], ...] = (("", "Unassigned"), ("self", SELF_NAME), ("spouse", SPOUSE_NAME))
_VALID_OWNERS = {value for value, _ in OWNER_OPTIONS}
OWNER_LABELS: dict[str, str] = dict(OWNER_OPTIONS)


def normalize_owner(raw) -> str:
    """'self'/'spouse'/'' for a valid value (case/whitespace-insensitive);
    anything else -- None, garbage, an unknown name -- is Unassigned
    rather than an error, since this is only ever fed UI-selected values
    and a blank/odd one should just mean "not assigned"."""
    value = str(raw or "").strip().lower()
    return value if value in _VALID_OWNERS else ""


def set_account_owner(account_id: str, owner: str) -> None:
    """Records which person a live linked account (one NOT tied to an
    Asset-tab row) belongs to. Assigning '' (Unassigned) removes the row
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
