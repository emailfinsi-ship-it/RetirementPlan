"""Real Plaid Link flow for connecting a bank/brokerage account directly
to this program -- no dependency on FamilyFinanceTracker.

Mirrors FamilyFinanceTracker's own source.collector.link_item almost
exactly (same mechanism, same reasoning -- see that module's docstring
for the full "why"): creates a link_token server-side, opens a
local-only ephemeral HTTP server hosting Plaid's own Link widget (loaded
from https://cdn.plaid.com, never bundled here), waits for you to log in
to your bank there (your credentials go straight to the bank/Plaid, this
program never sees them), exchanges the public_token for a real access
token, and stores it in the Keychain plus the Item's metadata in the
local database.

Usage (also reachable from the dashboard's Setup page -- see
source.webapp.dashboard._handle_plaid_connect):
    python3 -m source.collector.link_item --item-key fidelity_401k --products investments
"""

from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products

from source.collector.plaid_client import build_client
from source.common import db, secrets_store

CLIENT_NAME = "Retirement Plan"
DEFAULT_PORT = 8766
# Single-user local app -- this is just Plaid's required opaque user
# identifier, not a real account/username.
LOCAL_USER_ID = "retirement_plan_primary_user"

_LINK_PAGE_TEMPLATE = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Retirement Plan - Link your account</title></head>
<body style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 80px auto; text-align: center;">
  <h2>Retirement Plan</h2>
  <p id="status">Opening Plaid Link...</p>
  <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
  <script>
    var handler = Plaid.create({
      token: %(link_token_json)s,
      onSuccess: function(public_token, metadata) {
        document.getElementById('status').innerText = 'Linked! Finishing up...';
        fetch('/exchange', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({public_token: public_token, metadata: metadata})
        }).then(function() {
          document.getElementById('status').innerText = 'Done - you can close this tab.';
        });
      },
      onExit: function(err, metadata) {
        document.getElementById('status').innerText = err
          ? 'Link exited with an error - check the Terminal.'
          : 'Link closed without finishing - you can close this tab.';
        fetch('/exit', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({error: err, metadata: metadata})
        });
      },
    });
    handler.open();
  </script>
</body>
</html>
"""


class _LinkResult:
    def __init__(self) -> None:
        self.public_token: str | None = None
        self.metadata: dict = {}
        self.error: dict | None = None
        self.done = threading.Event()


def _make_handler(link_token: str, result: _LinkResult):
    page = (_LINK_PAGE_TEMPLATE % {"link_token_json": json.dumps(link_token)}).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # quiet
            pass

        def do_GET(self) -> None:
            if self.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw or b"{}")
            if self.path == "/exchange":
                result.public_token = payload.get("public_token")
                result.metadata = payload.get("metadata") or {}
                result.done.set()
            elif self.path == "/exit":
                result.error = payload.get("error")
                result.done.set()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

    return Handler


def _create_link_token(client, products: list[str]) -> str:
    request = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=LOCAL_USER_ID),
        client_name=CLIENT_NAME,
        country_codes=[CountryCode("US")],
        language="en",
        products=[Products(p) for p in products],
    )
    response = client.link_token_create(request)
    return response["link_token"]


def _run_local_link(link_token: str, *, port: int, timeout_seconds: int) -> _LinkResult:
    result = _LinkResult()
    server = HTTPServer(("127.0.0.1", port), _make_handler(link_token, result))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    url = f"http://127.0.0.1:{port}/"
    print(f"Opening {url} in your browser - log in to your bank/brokerage there.", flush=True)
    print("(Local only - nothing here is hosted outside this Mac.)", flush=True)
    webbrowser.open(url)

    try:
        finished = result.done.wait(timeout=timeout_seconds)
    finally:
        server.shutdown()
        server_thread.join(timeout=5)
        server.server_close()

    if not finished:
        raise TimeoutError(f"Timed out after {timeout_seconds}s waiting for Link to complete in the browser.")
    if result.error:
        raise RuntimeError(f"Plaid Link exited with an error: {result.error}")
    if not result.public_token:
        raise RuntimeError("Link closed without returning a public_token - nothing was linked.")
    return result


def link_real_item(
    item_key: str,
    *,
    products: list[str] | None = None,
    environment: str = "production",
    profile: str = "primary",
    port: int = DEFAULT_PORT,
    timeout_seconds: int = 300,
) -> str:
    """profile picks which saved Plaid app (source.common.secrets_store.
    PROFILES) this Item is linked -- and, via source.collector.sync/
    remove_item reading credential_profile back off the stored item row,
    always re-synced/removed -- with. Defaults to "primary", the one
    Plaid app this program has always used."""
    products = products or ["investments"]
    client = build_client(environment, profile=profile)
    link_token = _create_link_token(client, products)
    result = _run_local_link(link_token, port=port, timeout_seconds=timeout_seconds)

    exchange_response = client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=result.public_token)
    )
    access_token = exchange_response["access_token"]
    plaid_item_id = exchange_response["item_id"]

    institution = result.metadata.get("institution") or {}
    institution_id = institution.get("institution_id")
    institution_name = institution.get("name")

    secrets_store.set_item_access_token(item_key, access_token)

    linked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    db.upsert_plaid_item(
        item_key=item_key,
        plaid_item_id=plaid_item_id,
        institution_id=institution_id,
        institution_name=institution_name,
        products=products,
        environment=environment,
        credential_profile=profile,
        linked_at=linked_at,
    )
    return plaid_item_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--item-key", required=True, help="Short label for this Item, e.g. 'fidelity_401k'.")
    parser.add_argument("--products", nargs="+", default=["investments"])
    parser.add_argument("--env", default="production", choices=["sandbox", "production"])
    parser.add_argument(
        "--profile", default="primary", choices=["primary", "secondary"],
        help="Which saved Plaid app's credentials to link with (see the Setup page's Plaid API keys card).",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()

    item_id = link_real_item(
        args.item_key, products=args.products, environment=args.env, profile=args.profile,
        port=args.port, timeout_seconds=args.timeout_seconds,
    )
    print(f"Linked '{args.item_key}' -> Plaid item_id {item_id}")
    print("Access token stored in Keychain, metadata stored in the local database.")


if __name__ == "__main__":
    main()
