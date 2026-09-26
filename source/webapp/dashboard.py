"""Local dashboard for the standalone Retirement Plan program.

Same shape as FamilyFinanceTracker's own dashboard (plain
http.server.BaseHTTPRequestHandler / ThreadingHTTPServer, no framework,
binds 127.0.0.1 only) but a completely separate program/process/port --
this one deliberately doesn't import anything from that app. Port 8898,
one below FamilyFinanceTracker's 8899, so both can run side by side.

Tabs mirror the old workbook's own sheet names (Summary, Asset, Expense,
Real Estate Analysis, Monte Carlo Simulation) since that's the layout the
user asked this program to keep. Unlike the retired FamilyFinanceTracker
feature, every section here is a live, editable table backed by this
program's own database (source.common.db) -- add a line item, edit or
delete it, right from the page -- seeded once from the old workbook
(Setup page's one-time import) and from then on standing on its own.
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from source.collector import link_item as plaid_link_item
from source.collector import remove_item as plaid_remove_item
from source.collector import sync as plaid_sync
from source.common import app_settings, auth_store, backup, config, db, linked_data, secrets_store
from source.importer import xlsx_import
from source.reporting import excel_export
from source.reporting.aggregate import capture_net_worth_snapshot
from source.webapp.render_helpers import (
    NAV_ITEMS,
    PAGE_CSS,
    PAGE_SHELL,
    _account_number_display,
    _asset_category_summary_html,
    _asset_rollup_summary_html,
    _bar_chart_html,
    _donut_chart_html,
    _DONUT_COLORS,
    _DONUT_OTHER_COLOR,
    _editable_number_cell,
    _editable_text_cell,
    _effective_balance_html,
    _grouped_slices,
    _link_select_html,
    _loan_cell_html,
    _money,
    _money_short,
    _nav_html,
    _pct,
    _shell,
    _sync_now_button_html,
)
from source.webapp.pages.asset import _group_by_category, _render_asset_page, _sync_linked_institution_fields
from source.webapp.pages.expense import _render_expense_page
from source.webapp.pages.linked_accounts import _render_linked_accounts_page
from source.webapp.pages.linked_positions import _render_linked_positions_page, _sector_for_industry
from source.webapp.pages.login import _render_login_page
from source.webapp.pages.monte_carlo_page import _render_monte_carlo_page
from source.webapp.pages.real_estate import _render_real_estate_page
from source.webapp.pages.real_expenditure import _render_real_expenditure_page
from source.webapp.pages.setup import _render_setup_page
from source.webapp.pages.summary import _render_summary_page

# Every name imported above from render_helpers/pages.* is a re-export:
# dashboard.py used to define all of them directly, and the test suite
# (plus anyone poking at this module interactively) still reaches them
# as dashboard._money(...), dashboard._sector_for_industry(...), etc.
# Keeping explicit `from X import Y` statements here (rather than
# collapsing dashboard.py's own callers to the new modules) means the
# split cost zero test changes -- see source/webapp/render_helpers.py
# and source/webapp/pages/ for where each of these actually lives now.

PORT = config.DASHBOARD_PORT

# PWA assets (manifest.json, service-worker.js, icons/) -- static files,
# never templated, served byte-for-byte by _send_static_file below. See
# source/webapp/static/README.md for what lives here and why.
_STATIC_DIR = Path(__file__).resolve().parent / "static"

SESSION_COOKIE_NAME = "rp_session"

# Requests to these paths (and anything under an /icons/ prefix) are
# served even without a valid session -- the login page itself (and the
# endpoint that verifies a password) obviously can't require a session
# to reach, and the PWA manifest/service worker/icons need to load on
# the login screen too so "Add to Home Screen" looks right before the
# user has ever logged in. /api/set-password is deliberately NOT here --
# see _may_set_password below, it needs a narrower rule than "always
# public", since a password change (as opposed to the very first
# password being set) must require an existing session.
_PUBLIC_PATHS = {"/login.html", "/api/login", "/manifest.json", "/service-worker.js"}


def _is_public_path(path: str) -> bool:
    return path in _PUBLIC_PATHS or path.startswith("/icons/")


# Login rate-limiting: a simple in-memory (per-process) counter of
# recent failures per client IP, since this program can now be reached
# over the open internet (a Tailscale Funnel URL) and a login form is
# exactly the kind of endpoint that gets brute-forced. Deliberately not
# persisted anywhere -- restarting the dashboard resets it, which is an
# acceptable tradeoff for a personal single-user app (nobody's own
# lockout should outlive a Mac reboot) in exchange for not needing a
# database table or file just for this.
_MAX_LOGIN_FAILURES = 8
_LOGIN_LOCKOUT_SECONDS = 5 * 60
_login_failures: dict[str, list[float]] = {}


def _login_rate_limited(client_ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _login_failures.get(client_ip, []) if now - t < _LOGIN_LOCKOUT_SECONDS]
    _login_failures[client_ip] = attempts
    return len(attempts) >= _MAX_LOGIN_FAILURES


def _record_login_failure(client_ip: str) -> None:
    _login_failures.setdefault(client_ip, []).append(time.time())


def _clear_login_failures(client_ip: str) -> None:
    _login_failures.pop(client_ip, None)


def _choose_file_dialog(prompt: str, *, file_types: list[str] | None = None) -> str | None:
    """Opens a native macOS "Open" dialog (via AppleScript/osascript, which
    ships with every Mac -- no extra dependency, unlike tkinter, which
    often isn't built with Tcl/Tk support on a pyenv-installed Python) and
    returns the chosen file's absolute path, or None if the user canceled.
    Blocks until the user responds, same as the Plaid Link flow's wait."""
    type_clause = ""
    if file_types:
        types = ", ".join(f'"{t}"' for t in file_types)
        type_clause = f" of type {{{types}}}"
    script = f'POSIX path of (choose file{type_clause} with prompt "{prompt}")'
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=300,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("The native file picker (osascript) isn't available -- type the path in by hand.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Timed out waiting for a file to be chosen.") from exc
    if result.returncode != 0:
        if "User canceled" in (result.stderr or ""):
            return None
        raise RuntimeError((result.stderr or "File picker failed.").strip())
    return result.stdout.strip()


def _linked_institution_fields(account_id: str) -> dict:
    """Institution/Account # for a Plaid account, in the shape the assets
    table stores them -- the real Plaid institution name and account
    number (full number when Auth returned one, else the mask), e.g.
    picking "Fidelity -- APPLE 401(K) PLAN" fills in "Fidelity"/"1234"
    instead of leaving those fields for the user to type in by hand.
    Shared by /api/line-item/link-account (an existing row's own "Linked
    account" dropdown) and /api/line-item/classify-linked-account (the
    Linked Accounts page's one-step "Classify" action) so the two paths
    can't drift into showing different values for the same account_id.
    Empty dict if the account isn't currently connected."""
    live_by_account_id = {a["account_id"]: a for a in linked_data.linkable_accounts()}
    acc = live_by_account_id.get(account_id)
    if acc is None:
        return {}
    return {
        "institution": acc["institution"] or "",
        "last4": _account_number_display(
            acc["mask"], acc.get("account_number"), acc.get("is_tokenized_account_number", False),
        ),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "RetirementPlanDashboard/1.0"

    def log_message(self, format, *args):  # noqa: A002 -- stdlib signature
        pass

    def _send_html(self, content: str, status: int = 200) -> None:
        body = content.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # The browser gave up on this request (tab closed, page
            # refreshed, or -- most commonly here -- a slow "Sync now"
            # outlasted however long it waits) before we finished
            # responding. Nothing left to send it, and nothing to do
            # about it: swallowing this here (rather than letting it
            # propagate into do_GET/do_POST's own `except Exception`,
            # which would try to write an *error* response into the same
            # dead socket and immediately raise the identical error a
            # second time, uncaught) is what keeps that from dumping a
            # noisy traceback to the terminal for a request whose actual
            # work -- e.g. the sync itself -- usually already succeeded.
            pass

    def _send_export_html(self, path: Path) -> None:
        if not path.exists():
            self._send_html(
                "<h1>Not generated yet</h1><p>Run \"Sync now\" on the Summary, Linked Accounts, or Linked Positions page first.</p>",
                status=404,
            )
            return
        self._send_html(path.read_text(encoding="utf-8"))

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # See _send_html's matching comment -- same client-gave-up
            # case, same reason it's safe (and quieter) to just stop here.
            pass

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _send_redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_static_file(self, rel_path: str, content_type: str) -> None:
        file_path = _STATIC_DIR / rel_path
        try:
            data = file_path.read_bytes()
        except OSError:
            self._send_html("<h1>Not found</h1>", status=404)
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _session_cookie(self) -> str | None:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE_NAME:
                return value
        return None

    def _has_valid_session(self) -> bool:
        return auth_store.verify_session_token(self._session_cookie())

    def _set_session_cookie(self) -> str:
        token = auth_store.issue_session_token()
        # HttpOnly (JS on the page can't read it -- irrelevant to an XSS
        # bug this app doesn't have, but free defense-in-depth) and
        # SameSite=Lax (a cross-site POST/fetch never attaches it, which
        # is most of what matters against CSRF here). Not marked Secure:
        # when reached through a Tailscale Funnel URL, Tailscale itself
        # terminates TLS and proxies to this process over localhost/the
        # tailnet, both already-trusted hops, so requiring Secure would
        # only break the plain-127.0.0.1 case this app also still needs
        # to support.
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000",
        )
        return token

    def _clear_session_cookie(self) -> None:
        self.send_header("Set-Cookie", f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")

    # -- GET --

    def do_GET(self):  # noqa: N802 -- stdlib method name
        path = urlparse(self.path).path
        try:
            if path == "/manifest.json":
                self._send_static_file("manifest.json", "application/manifest+json")
                return
            if path == "/service-worker.js":
                self._send_static_file("service-worker.js", "application/javascript")
                return
            if path.startswith("/icons/"):
                ext = path.rsplit(".", 1)[-1].lower()
                content_type = "image/svg+xml" if ext == "svg" else f"image/{ext}"
                self._send_static_file(path.lstrip("/"), content_type)
                return
            if path == "/login.html":
                self._send_html(_render_login_page(first_time=not auth_store.is_password_set()))
                return
            if auth_store.is_password_set() and not self._has_valid_session():
                self._send_redirect("/login.html")
                return
            if path in ("/", "/summary.html"):
                self._send_html(_render_summary_page())
            elif path == "/asset.html":
                self._send_html(_render_asset_page())
            elif path == "/linked-accounts.html":
                self._send_html(_render_linked_accounts_page())
            elif path == "/linked-positions.html":
                self._send_html(_render_linked_positions_page())
            elif path == "/expense.html":
                self._send_html(_render_expense_page())
            elif path == "/real-expenditure.html":
                self._send_html(_render_real_expenditure_page())
            elif path == "/real-estate.html":
                self._send_html(_render_real_estate_page())
            elif path == "/monte-carlo.html":
                self._send_html(_render_monte_carlo_page())
            elif path == "/setup.html":
                self._send_html(_render_setup_page())
            elif path == "/account-balances.html":
                self._send_export_html(config.account_balances_html_path())
            elif path == "/portfolio-positions.html":
                self._send_export_html(config.portfolio_positions_html_path())
            else:
                self._send_html("<h1>Not found</h1>", status=404)
        except Exception as exc:  # a broad catch here matters -- see FamilyFinanceTracker's
            # dashboard.py for the real incident (an unhandled exception mid-GET drops the
            # connection instead of showing a readable error) that this guards against.
            self._send_html(f"<h1>Something went wrong</h1><p>{html.escape(str(exc))}</p>", status=500)

    # -- POST --

    def do_POST(self):  # noqa: N802 -- stdlib method name
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            # /api/set-password is allowed through with no session ONLY
            # when there's no password yet at all (first-time setup --
            # nothing to have logged in with). The moment a password
            # exists, changing it goes through the same 401 gate as
            # everything else below, same as any other write.
            setting_first_password = path == "/api/set-password" and not auth_store.is_password_set()
            if (
                not setting_first_password
                and not _is_public_path(path)
                and auth_store.is_password_set()
                and not self._has_valid_session()
            ):
                self._send_json({"ok": False, "error": "Not logged in."}, status=401)
                return
            if path == "/api/login":
                client_ip = self.client_address[0]
                if _login_rate_limited(client_ip):
                    self._send_json(
                        {"ok": False, "error": "Too many failed attempts -- wait a few minutes and try again."},
                        status=429,
                    )
                    return
                if not auth_store.is_password_set():
                    self._send_json({"ok": False, "error": "No password set yet."}, status=400)
                    return
                if not auth_store.verify_password(payload.get("password") or ""):
                    _record_login_failure(client_ip)
                    self._send_json({"ok": False, "error": "Wrong password."}, status=401)
                    return
                _clear_login_failures(client_ip)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._set_session_cookie()
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/set-password":
                # First-time setup (no password exists yet) reaches here
                # via setting_first_password above with no session
                # needed -- there's nothing to log in with yet. Any
                # later call (changing an existing password) already had
                # to pass the ordinary 401 gate above, so it's always an
                # already-logged-in request.
                new_password = payload.get("password") or ""
                confirm = payload.get("confirm")
                if confirm is not None and confirm != new_password:
                    self._send_json({"ok": False, "error": "Passwords don't match."}, status=400)
                    return
                try:
                    auth_store.set_password(new_password)
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._set_session_cookie()
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/logout":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._clear_session_cookie()
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/line-item/add":
                item_id = db.add_line_item(payload["section"], payload.get("fields") or {})
                self._send_json({"ok": True, "id": item_id})
            elif path == "/api/line-item/update":
                ok = db.update_line_item(payload["section"], int(payload["id"]), payload.get("fields") or {})
                self._send_json({"ok": ok})
            elif path == "/api/line-item/delete":
                ok = db.delete_line_item(payload["section"], int(payload["id"]))
                self._send_json({"ok": ok})
            elif path == "/api/line-item/delete-bulk":
                # Backs the checkbox multi-select + "Delete selected" bar
                # (one request for the whole selection instead of the
                # browser firing N separate /delete calls). Tolerant of a
                # bad individual entry (already deleted by someone else,
                # unknown section) -- skips it and keeps going, rather than
                # aborting the whole batch and leaving the user unsure
                # which of their selected rows actually got deleted.
                items = payload.get("items") or []
                deleted = 0
                for item in items:
                    try:
                        if db.delete_line_item(item["section"], int(item["id"])):
                            deleted += 1
                    except (KeyError, ValueError, TypeError):
                        continue
                self._send_json({"ok": True, "deleted": deleted, "requested": len(items)})
            elif path == "/api/line-item/link-account":
                section = payload.get("section", "assets")
                item_id = int(payload["id"])
                account_id = (payload.get("account_id") or "").strip() or None
                if account_id is not None and db.get_plaid_account(account_id) is None:
                    raise ValueError("That linked account isn't connected anymore -- try Sync now on Summary or Linked Positions.")
                updates = {"linked_account_id": account_id}
                if account_id is not None and section == "assets":
                    # Only the assets table has Institution/Account #
                    # columns (real_estate doesn't) -- see
                    # _linked_institution_fields.
                    updates.update(_linked_institution_fields(account_id))
                ok = db.update_line_item(section, item_id, updates)
                self._send_json({"ok": ok})
            elif path == "/api/line-item/classify-linked-account":
                # The Linked Accounts page's "Classify" action: creates a
                # new Asset-tab line item for a not-yet-classified Plaid
                # account and links it to it in the same call, instead of
                # requiring the user to add a row by hand on the Asset
                # tab first and then use that row's own "Linked account"
                # dropdown (still there, and still how you'd re-link a
                # row later or link a second account to an existing
                # manual row) -- see linked_accounts.py.
                account_id = (payload.get("account_id") or "").strip()
                if not account_id:
                    raise ValueError("Pick an account to classify.")
                if db.get_plaid_account(account_id) is None:
                    raise ValueError("That linked account isn't connected anymore -- try Sync now on Summary or Linked Positions.")
                kind = payload.get("kind") or "asset"
                if kind not in ("asset", "liability"):
                    raise ValueError(f"Unknown kind: {kind!r}. Expected 'asset' or 'liability'.")
                category = (payload.get("category") or "").strip()
                if not category:
                    raise ValueError("Pick a category for this account.")
                fields = {
                    **_linked_institution_fields(account_id),
                    "kind": kind,
                    "category": category,
                    "name": (payload.get("name") or "").strip(),
                    "linked_account_id": account_id,
                }
                item_id = db.add_line_item("assets", fields)
                self._send_json({"ok": True, "id": item_id})
            elif path == "/api/assumptions":
                updates = {}
                for key, raw in payload.items():
                    if raw in (None, ""):
                        continue
                    if key.endswith("_pct"):
                        updates[key[: -len("_pct")]] = float(raw) / 100.0
                    else:
                        updates[key] = raw
                db.set_assumptions(updates)
                self._send_json({"ok": True})
            elif path == "/api/set-bind-host":
                # The Setup page's Network access card -- which
                # interface(s) the dashboard listens on. Only takes
                # effect on the NEXT restart (run() below reads it once
                # at startup, the already-running ThreadingHTTPServer
                # can't rebind live), which the card's own JS tells the
                # user after a successful save.
                host = (payload.get("bind_host") or "").strip()
                if host not in ("127.0.0.1", "0.0.0.0"):
                    raise ValueError("bind_host must be '127.0.0.1' or '0.0.0.0'.")
                app_settings.set_bind_host(host)
                self._send_json({"ok": True})
            elif path == "/api/import":
                # The highest-risk write this program does -- a wrong
                # workbook, a wrong password, or a bug could clobber
                # existing hand-entered line items. Back up first, so
                # there's always a pre-import snapshot to fall back to;
                # best-effort (a backup failure shouldn't block an
                # import the user is actively waiting on).
                try:
                    backup.create_backup(reason="pre-import")
                except Exception:
                    pass
                summary = xlsx_import.import_from_xlsx(
                    Path(payload["path"]), password=payload.get("password") or None
                )
                self._send_json({"ok": True, "summary": summary})
            elif path == "/api/backup-now":
                # The Setup page's "Back up now" button -- an
                # on-demand copy alongside the automatic startup/
                # pre-import ones, for "I'm about to try something
                # risky" moments (bulk edits, clearing industries, ...).
                dest = backup.create_backup(reason="manual")
                if dest is None:
                    self._send_json({"ok": False, "error": "No database exists yet -- nothing to back up."}, status=400)
                else:
                    self._send_json({"ok": True, "path": str(dest)})
            elif path == "/api/choose-file":
                # No file-type filter: AppleScript's "of type" extension
                # matching is unreliable across macOS versions (it grayed
                # out real .xlsx files in testing) -- showing every file
                # and letting xlsx_import.import_from_xlsx reject a
                # non-workbook with a clear error is more robust than a
                # picker that hides the file you actually want.
                chosen = _choose_file_dialog("Select your retirement-plan workbook")
                if chosen is None:
                    self._send_json({"ok": False, "error": "Canceled"}, status=400)
                else:
                    self._send_json({"ok": True, "path": chosen})
            elif path == "/api/plaid-credentials":
                client_id = (payload.get("client_id") or "").strip()
                secret = (payload.get("secret") or "").strip()
                environment = (payload.get("environment") or config.PLAID_ENV).strip().lower()
                profile = (payload.get("profile") or "primary").strip().lower()
                if client_id:
                    secrets_store.set_plaid_client_id(client_id, profile=profile)
                if secret:
                    secrets_store.set_plaid_secret(secret, env=environment, profile=profile)
                self._send_json({"ok": True})
            elif path == "/api/plaid-connect":
                item_key = (payload.get("item_key") or "").strip()
                if not item_key:
                    raise ValueError("Item key is required.")
                products = [
                    p.strip() for p in (payload.get("products") or "investments").split(",") if p.strip()
                ]
                environment = (payload.get("environment") or "production").strip().lower()
                profile = (payload.get("profile") or "primary").strip().lower()
                plaid_link_item.link_real_item(item_key, products=products, environment=environment, profile=profile)
                self._send_json({"ok": True})
            elif path == "/api/plaid-remove":
                item_key = (payload.get("item_key") or "").strip()
                if not item_key:
                    raise ValueError("Item key is required.")
                plaid_remove_item.remove_item(item_key)
                self._send_json({"ok": True})
            elif path == "/api/plaid-sync":
                summary = plaid_sync.sync_all()
                # Refreshes today's net-worth snapshot with the balances
                # this sync just pulled -- see capture_net_worth_
                # snapshot's own docstring on why re-capturing the same
                # day is safe (upsert, not a new point). Best-effort: a
                # snapshot hiccup shouldn't turn an otherwise-successful
                # sync into a failed request.
                try:
                    capture_net_worth_snapshot()
                except Exception:
                    pass
                self._send_json({"ok": True, "summary": summary})
            elif path == "/api/category-rule/save":
                # Setup page's "Category rules" card -- see source.common.
                # db.category_rules and plaid_categorize.default_category's
                # own docstring for exactly how a saved rule here takes
                # priority over this program's built-in category-rollup
                # defaults. Immediately re-runs recategorize_all_
                # transactions() so the change is visible on Real
                # Expenditure right away, not just for transactions synced
                # from here on -- cheap and idempotent for a personal
                # database's transaction volume (see that function's own
                # docstring), same call already made on every app startup.
                rule_id = db.upsert_category_rule(
                    rule_type=(payload.get("rule_type") or "").strip(),
                    match_key=payload.get("match_key") or "",
                    category=payload.get("category") or "",
                )
                changed = db.recategorize_all_transactions()
                self._send_json({"ok": True, "id": rule_id, "recategorized": changed})
            elif path == "/api/category-rule/delete":
                deleted = db.delete_category_rule(int(payload.get("id")))
                changed = db.recategorize_all_transactions() if deleted else 0
                self._send_json({"ok": True, "deleted": deleted, "recategorized": changed})
            elif path == "/api/export":
                out_path = excel_export.export_current_state()
                self._send_json({"ok": True, "path": str(out_path)})
            elif path == "/api/classify-industry":
                # Backs the Linked Positions page's multi-select "Set
                # industry"/"Clear industry" bar -- a manual override for
                # holdings Yahoo Finance will never classify on its own
                # (cash, money-market funds, REITs, international-equity
                # funds, etc). Same tolerant-per-item pattern as
                # /api/line-item/delete-bulk: a bad individual entry
                # (missing security_id) is skipped rather than aborting
                # the whole batch.
                items = payload.get("items") or []
                industry = (payload.get("industry") or "").strip()
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                count = 0
                if industry:
                    for item in items:
                        security_id = item.get("security_id")
                        if not security_id:
                            continue
                        db.set_security_industry(
                            security_id=security_id,
                            ticker=item.get("ticker") or "",
                            industry=industry,
                            updated_at=now,
                        )
                        count += 1
                else:
                    security_ids = [item["security_id"] for item in items if item.get("security_id")]
                    count = db.clear_security_industries(security_ids)
                self._send_json({"ok": True, "count": count})
            elif path == "/api/classify-sector":
                # Backs the Linked Positions page's multi-select "Set
                # sector"/"Clear sector" bar -- a manual override for
                # positions with no `industry` to derive a sector from at
                # all (a mutual fund, ETF, or target-date fund; see
                # db.set_security_sector's own docstring), so they can
                # still leave the "Unknown" sector bucket. Same tolerant-
                # per-item pattern as /api/classify-industry above.
                items = payload.get("items") or []
                sector = (payload.get("sector") or "").strip()
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                count = 0
                if sector:
                    for item in items:
                        security_id = item.get("security_id")
                        if not security_id:
                            continue
                        db.set_security_sector(
                            security_id=security_id,
                            ticker=item.get("ticker") or "",
                            sector=sector,
                            updated_at=now,
                        )
                        count += 1
                else:
                    security_ids = [item["security_id"] for item in items if item.get("security_id")]
                    count = db.clear_security_sectors(security_ids)
                self._send_json({"ok": True, "count": count})
            elif path == "/api/plaid-connect-transactions":
                # Backs the Setup page's per-Item "Enable Transactions"
                # button -- an Item linked before this feature existed
                # (or linked without explicitly requesting "transactions")
                # needs this one-time re-consent (Plaid "update mode"
                # Link) before Real Expenditure has anything to sync for
                # it; see source.collector.link_item.
                # enable_transactions_for_item's own docstring for why a
                # plain resync alone can't grant a new product. Same
                # synchronous "waits in this request for you to finish in
                # the new browser tab" shape as /api/plaid-connect above.
                item_key = (payload.get("item_key") or "").strip()
                if not item_key:
                    raise ValueError("Item key is required.")
                plaid_link_item.enable_transactions_for_item(item_key)
                self._send_json({"ok": True})
            elif path == "/api/classify-transaction-category":
                # Backs the Real Expenditure page's multi-select "Set
                # category"/"Reset category" bar -- same tolerant-per-item
                # pattern as /api/classify-industry above, just keyed by
                # transaction_id instead of security_id. An empty/missing
                # category resets the selected rows back to Plaid's own
                # classification (db.clear_plaid_transaction_category_
                # overrides) instead of blanking them -- unlike a
                # security's industry, a transaction always has SOME
                # starting category from Plaid, so "clear" means "go back
                # to that," not "make this blank."
                items = payload.get("items") or []
                transaction_ids = [item["transaction_id"] for item in items if item.get("transaction_id")]
                category = (payload.get("category") or "").strip()
                if category:
                    count = db.update_plaid_transaction_category(transaction_ids, category)
                else:
                    count = db.clear_plaid_transaction_category_overrides(transaction_ids)
                self._send_json({"ok": True, "count": count})
            elif path == "/api/classify-transaction-expense-flag":
                # Backs the Real Expenditure page's "Exclude from total"/
                # "Include in total"/"Reset to automatic" buttons -- lets a
                # person correct Plaid's own transfer/credit-card-payment
                # auto-tagging (source.common.plaid_categorize.default_
                # excluded_from_expense) by hand in either direction, or
                # put a row back under that automatic tagging.
                items = payload.get("items") or []
                transaction_ids = [item["transaction_id"] for item in items if item.get("transaction_id")]
                action = (payload.get("action") or "").strip().lower()
                if action == "exclude":
                    count = db.update_plaid_transaction_excluded(transaction_ids, True)
                elif action == "include":
                    count = db.update_plaid_transaction_excluded(transaction_ids, False)
                elif action == "reset":
                    count = db.clear_plaid_transaction_excluded_overrides(transaction_ids)
                else:
                    raise ValueError(f"Unknown action {action!r} -- expected 'exclude', 'include', or 'reset'.")
                self._send_json({"ok": True, "count": count})
            else:
                self._send_json({"ok": False, "error": "Not found"}, status=404)
        except xlsx_import.ImportError_ as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
        except (KeyError, ValueError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)


def run(*, open_browser: bool = True) -> None:
    config.ensure_directories()
    db.init_db()
    # First time the app is opened today, today gets a backup -- see
    # source.common.backup's module docstring for why this (rather than
    # a cron job or background thread) is the "automatic" mechanism.
    # Best-effort: a backup failure (disk full, permissions) shouldn't
    # stop the dashboard itself from starting.
    try:
        backup.ensure_daily_backup()
    except Exception as exc:
        print(f"Startup backup failed (continuing anyway): {exc}")

    # One net-worth-history data point for today, from whatever's already
    # in the database -- see aggregate.capture_net_worth_snapshot's own
    # docstring. Best-effort, same as the backup above: a snapshot
    # failure shouldn't stop the dashboard itself from starting.
    try:
        capture_net_worth_snapshot()
    except Exception as exc:
        print(f"Startup net-worth snapshot failed (continuing anyway): {exc}")

    bind_host = app_settings.get_bind_host()
    if bind_host != "127.0.0.1" and not auth_store.is_password_set():
        # Refuse to listen on anything but localhost until a login
        # password exists -- a misconfigured bind_host (Setup page's
        # Network access card, see that page for how it's set) should
        # never be the thing that first exposes this program's financial
        # data to a network with no password in front of it. Falls back
        # to 127.0.0.1 for THIS run only; the Setup page's own bind_host
        # setting is left as the user configured it, so setting a
        # password and restarting picks it back up automatically.
        print(
            f"bind_host is set to {bind_host!r} but no login password is set yet -- "
            "starting on 127.0.0.1 instead. Set a password on the Setup page, then restart."
        )
        bind_host = "127.0.0.1"

    server = ThreadingHTTPServer((bind_host, PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/" if bind_host == "127.0.0.1" else f"http://{bind_host}:{PORT}/ (and http://127.0.0.1:{PORT}/)"
    print(f"Retirement Plan dashboard running at {url}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down.")
        server.shutdown()


if __name__ == "__main__":
    run(open_browser="--no-browser" not in sys.argv)
