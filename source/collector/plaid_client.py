"""Thin wrapper around the Plaid API client -- the only module in this
program that talks to Plaid's API directly. Credentials come from
source.common.secrets_store (Keychain), never from a file.

Mirrors FamilyFinanceTracker's own source.collector.plaid_client, on
purpose: same shape, so the same mental model applies to anyone who's
used that app. This program has its own Keychain vault, its own Plaid
API calls, and its own database -- see source.common.secrets_store's
module docstring for how a user who already has FamilyFinanceTracker set
up can copy their existing credentials/Items across in one step instead
of relinking every bank from scratch.
"""

from __future__ import annotations

import plaid
from plaid.api import plaid_api

from source.common import config, secrets_store

_ENV_MAP = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


def build_client(environment: str | None = None, *, profile: str = "primary") -> plaid_api.PlaidApi:
    """profile selects which of the two saved Plaid credential profiles
    (source.common.secrets_store.PROFILES) to authenticate with -- lets
    this program talk to two separate Plaid apps side by side, e.g. if
    you've hit a per-app Item limit or simply have two Plaid developer
    accounts. Defaults to "primary" so every pre-existing caller (and
    anyone who's only ever set up one Plaid app) is unaffected."""
    env = (environment or config.PLAID_ENV).strip().lower()
    if env not in _ENV_MAP:
        raise ValueError(f"Unknown Plaid environment '{env}'. Expected one of: {sorted(_ENV_MAP)}")

    configuration = plaid.Configuration(
        host=_ENV_MAP[env],
        api_key={
            "clientId": secrets_store.get_plaid_client_id(profile=profile),
            "secret": secrets_store.get_plaid_secret(env=env, profile=profile),
        },
    )
    api_client = plaid.ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)
