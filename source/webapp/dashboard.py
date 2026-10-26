"""Local dashboard for the standalone Retirement Plan program.

Same shape as FamilyFinanceTracker's own dashboard (plain
http.server.BaseHTTPRequestHandler / ThreadingHTTPServer, no framework,
binds 127.0.0.1 only) but a completely separate program/process/port --
this one deliberately doesn't import anything from that app. Port 8898,
one below FamilyFinanceTracker's 8899, so both can run side by side.

Tabs mirror the old workbook's own sheet names (Summary, Asset, Expense,
Real Estate, Monte Carlo Simulation) since that's the layout the
user asked this program to keep. Unlike the retired FamilyFinanceTracker
feature, every section here is a live, editable table backed by this
program's own database (source.common.db) -- add a line item, edit or
delete it, right from the page -- seeded once from the old workbook
(Setup page's one-time import) and from then on standing on its own.
"""

from __future__ import annotations

import html
import base64
import json
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from source.collector import auto_sync
from source.collector import link_item as plaid_link_item
from source.collector import rentcast
from source.collector import remove_item as plaid_remove_item
from source.collector import sync as plaid_sync
from source.common import app_settings, auth_store, backup, branding, config, db, demo_data, first_run, linked_data, production, secrets_store, transfer
from source.importer import xlsx_import
from source.reporting import benefits, excel_export, scenarios as scenarios_module, what_if
from source.reporting.aggregate import (
    build_summary,
    capture_daily_snapshots_if_new_day,
    capture_investment_account_balances,
    capture_net_worth_snapshot,
)
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
from source.webapp import trading_api, wording
from source.webapp.render_helpers.shell import set_request_role
from source.webapp.pages.asset import _group_by_category, _render_asset_page, _sync_linked_institution_fields
from source.webapp.pages.budget_vs_actual import _render_budget_vs_actual_page
from source.webapp.pages.drawdown_planning import _render_drawdown_planning_page
from source.webapp.pages.expense import _render_expense_page
from source.webapp.pages.legacy_planning import _render_legacy_planning_page
from source.webapp.pages.linked_accounts import _render_linked_accounts_page
from source.webapp.pages.rebalance_page import _render_rebalance_page
from source.webapp.pages.trading import _render_trading_page
from source.collector import ibkr_gateway
from source.webapp.pages.broker_page import _render_broker_page
from source.webapp.pages.stock_analysis import _render_stock_analysis_page
from source.webapp.pages.tutorial import TUTORIAL_DIR, _render_tutorial_page
from source.webapp.pages.linked_positions import _render_linked_positions_page, _sector_for_industry
from source.webapp.pages.login import _render_login_page
from source.webapp.pages.welcome import _render_welcome_page
from source.webapp.pages.forgot import _render_forgot_page
from source.webapp.pages.legal import _render_legal_page
from source.webapp.pages.monte_carlo_page import _render_monte_carlo_page
from source.webapp.pages.real_estate import _render_real_estate_page
from source.webapp.pages.real_expenditure import _render_real_expenditure_page
from source.webapp.pages.setup import _render_setup_page
from source.webapp.pages.report import _render_report_page
from source.webapp.pages.setup_wizard import _render_wizard_page
from source.webapp import warm
from source.common import tls
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
_PUBLIC_PATHS = {"/login.html", "/api/login", "/manifest.json", "/service-worker.js", "/welcome.html", "/api/first-run", "/forgot.html", "/api/reset-password", "/legal.html", "/api/transfer-import"}


# POST routes a view-only ("viewer") login may still use: they only calculate or
# show something, and change nothing that is saved.
_VIEWER_POSTS = {
    "/api/logout", "/api/login", "/api/reset-password", "/api/what-if", "/api/safe-spending", "/api/benefits/claiming-analysis",
    "/api/scenarios/compare", "/api/backup-verify", "/api/dollars-mode", "/api/view-mode", "/api/wording-mode", "/api/tour-seen",
}
# Pages a viewer never sees (they hold settings and secrets).
_OWNER_ONLY_PAGES = {"/setup.html", "/setup-wizard.html", "/trading.html", "/trading-live.html", "/stock-analysis.html", "/ibkr.html", "/etrade.html"}


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



_SAFE_SPENDING_CACHE: dict = {}


def _safe_spending_cached(summary: dict, target: float) -> dict:
    """find_safe_spending takes a few seconds, so repeat page views reuse the
    last answer for an unchanged plan (keyed on every input it reads)."""
    import hashlib

    key = hashlib.md5(repr((
        round(target, 4), summary["assumptions"], summary["expenses"], summary["income_for_simulation"],
        summary["retirement_pools"], summary["net_liquid_asset"], summary.get("next_year_expense_need"),
    )).encode("utf-8")).hexdigest()
    if key not in _SAFE_SPENDING_CACHE:
        if len(_SAFE_SPENDING_CACHE) >= 16:
            _SAFE_SPENDING_CACHE.clear()
        _SAFE_SPENDING_CACHE[key] = what_if.find_safe_spending(summary, target)
    return _SAFE_SPENDING_CACHE[key]

class Handler(BaseHTTPRequestHandler):
    server_version = "PlanDashboard/1.0"

    def log_message(self, format, *args):  # noqa: A002 -- stdlib signature
        pass

    def _send_html(self, content: str, status: int = 200) -> None:
        body = wording.fix_typography(content).encode("utf-8")
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
        if rel_path == "manifest.json":
            # The brand lives in source.common.branding, not in this file.
            data = (
                data.decode("utf-8")
                .replace("__PRODUCT_NAME__", branding.PRODUCT_NAME)
                .replace("__PRODUCT_TAGLINE__", branding.PRODUCT_TAGLINE)
            ).encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _send_tutorial_file(self, rel_path: str) -> None:
        """Serves a bundled tutorial file (video / screenshot). Videos need HTTP
        Range support or Safari will not play them."""
        base = TUTORIAL_DIR.resolve()
        file_path = (base / rel_path).resolve()
        if base not in file_path.parents or not file_path.is_file():
            self._send_html("<h1>Not found</h1>", status=404)
            return
        ext = file_path.suffix.lower().lstrip(".")
        content_type = {"mp4": "video/mp4", "jpg": "image/jpeg", "png": "image/png"}.get(ext, "application/octet-stream")
        size = file_path.stat().st_size
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range") or ""
        if rng.startswith("bytes="):
            first, _, last = rng[6:].split(",")[0].partition("-")
            try:
                if first == "":
                    start = max(0, size - int(last))
                else:
                    start = int(first)
                    end = min(size - 1, int(last)) if last else size - 1
                if start > end or start >= size:
                    raise ValueError
                status = 206
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        length = end - start + 1
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if self.command != "HEAD":
                with file_path.open("rb") as fh:
                    fh.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = fh.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
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

    def _role(self) -> str:
        """"owner" or "viewer". With no password set there is no login, and the
        person at the keyboard is the owner."""
        if not auth_store.is_password_set():
            return "owner"
        return auth_store.session_role(self._session_cookie()) or "viewer"  # least privilege if anything is unclear

    def _set_session_cookie(self, role: str = "owner") -> str:
        token = auth_store.issue_session_token(role)
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
        set_request_role(self._role())
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
            if path == "/api/health":
                # Public on purpose: the app launcher polls it to learn whether a
                # copy is already running. Reveals nothing but the product name.
                self._send_json({"ok": True, "app": branding.PRODUCT_NAME})
                return
            if path == "/legal.html":
                self._send_html(_render_legal_page())
                return
            if path == "/welcome.html":
                if first_run.required():
                    self._send_html(_render_welcome_page())
                else:
                    self._send_redirect("/")
                return
            if first_run.required():
                # Brand-new install: nothing else is usable until the admin
                # password and the database exist.
                self._send_redirect("/welcome.html")
                return
            if path == "/forgot.html":
                self._send_html(_render_forgot_page())
                return
            if path == "/login.html":
                self._send_html(_render_login_page(first_time=not auth_store.is_password_set()))
                return
            if auth_store.is_password_set() and not self._has_valid_session():
                self._send_redirect("/login.html")
                return
            if path in _OWNER_ONLY_PAGES and self._role() == "viewer":
                self._send_redirect("/summary.html")
                return
            if path == "/" and db.setup_needed():
                # Brand-new install: land on the setup wizard, not an empty Summary.
                self._send_redirect("/setup-wizard.html")
            elif path in ("/", "/summary.html"):
                self._send_html(_render_summary_page())
            elif path == "/asset.html":
                self._send_html(_render_asset_page())
            elif path == "/linked-accounts.html":
                self._send_html(_render_linked_accounts_page())
            elif path == "/linked-positions.html":
                self._send_html(_render_linked_positions_page())
            elif path == "/rebalance.html":
                self._send_html(_render_rebalance_page())
            elif path == "/trading.html":
                self._send_html(_render_trading_page("paper"))
            elif path == "/trading-live.html":
                self._send_html(_render_trading_page("live"))
            elif path == "/stock-analysis.html":
                self._send_html(_render_stock_analysis_page())
            elif path in ("/ibkr.html", "/etrade.html"):
                self._send_html(_render_broker_page(path[1:-5]))
            elif path == "/diagnostics.txt":
                if self._role() == "viewer":
                    self._send_redirect("/summary.html")
                    return
                body = production.diagnostics_text().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{branding.INTERNAL_ID}-diagnostics.txt"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/tutorial.html":
                self._send_html(_render_tutorial_page())
            elif path.startswith("/tutorial/"):
                self._send_tutorial_file(path[len("/tutorial/"):])
            elif path == "/expense.html":
                self._send_html(_render_expense_page())
            elif path == "/real-expenditure.html":
                self._send_html(_render_real_expenditure_page())
            elif path == "/budget-vs-actual.html":
                self._send_html(_render_budget_vs_actual_page())
            elif path == "/real-estate.html":
                self._send_html(_render_real_estate_page())
            elif path == "/monte-carlo.html":
                self._send_html(_render_monte_carlo_page())
            elif path == "/drawdown-planning.html":
                self._send_html(_render_drawdown_planning_page())
            elif path == "/legacy-planning.html":
                self._send_html(_render_legacy_planning_page())
            elif path == "/setup.html":
                self._send_html(_render_setup_page())
            elif path == "/setup-wizard.html":
                self._send_html(_render_wizard_page())
            elif path == "/report.html":
                self._send_html(wording.plain_html(_render_report_page()))
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
        try:
            self._handle_post()
        finally:
            warm.schedule()   # anything saved may change the numbers; get the slow pages ready

    def _handle_post(self):
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            # /api/set-password is allowed through with no session ONLY
            # when there's no password yet at all (first-time setup --
            # nothing to have logged in with). The moment a password
            # exists, changing it goes through the same 401 gate as
            # everything else below, same as any other write.
            if first_run.required() and path not in ("/api/first-run", "/api/transfer-import"):
                self._send_json({"ok": False, "error": "Finish the first-time setup first."}, status=403)
                return
            if path == "/api/transfer-import":
                if not first_run.required():
                    self._send_json({"ok": False, "error": "This Mac is already set up. Importing is only offered on a brand-new install."}, status=400)
                    return
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
                if host not in ("127.0.0.1", "localhost", "::1"):
                    self._send_json({"ok": False, "error": "Importing must be done on this computer."}, status=403)
                    return
                try:
                    blob = base64.b64decode(payload.get("data_b64") or "", validate=True)
                except ValueError:
                    self._send_json({"ok": False, "error": "The file could not be read."}, status=400)
                    return
                try:
                    bundle = transfer.read_bundle(blob, payload.get("passphrase") or "")
                    result = transfer.apply_bundle(bundle)
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self._send_json({"ok": True, **result})
                return
            if path == "/api/transfer-export":
                if auth_store.is_password_set() and not auth_store.verify_password(payload.get("password") or ""):
                    self._send_json({"ok": False, "error": "Wrong password."}, status=401)
                    return
                try:
                    blob = transfer.build_bundle(payload.get("passphrase") or "", include_backups=bool(payload.get("include_backups", True)))
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self._send_json({"ok": True, "filename": f"{branding.INTERNAL_ID}-transfer-{time.strftime('%Y%m%d')}.finsi-transfer",
                                 "data_b64": base64.b64encode(blob).decode("ascii")})
                return
            if path == "/api/first-run":
                if not first_run.required():
                    self._send_json({"ok": False, "error": "Setup is already done."}, status=400)
                    return
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
                if host not in ("127.0.0.1", "localhost", "::1"):
                    self._send_json({"ok": False, "error": "First-time setup must be done on this computer."}, status=403)
                    return
                try:
                    result = first_run.complete(payload.get("password") or "", payload.get("confirm"), payload.get("data_dir"))
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._set_session_cookie()
                body = json.dumps({"ok": True, **result}).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            setting_first_password = path == "/api/set-password" and not auth_store.is_password_set()
            if (
                not setting_first_password
                and not _is_public_path(path)
                and auth_store.is_password_set()
                and not self._has_valid_session()
            ):
                self._send_json({"ok": False, "error": "Not logged in."}, status=401)
                return
            if self._role() == "viewer" and path not in _VIEWER_POSTS:
                self._send_json({"ok": False, "error": "You are signed in as a viewer, so this is view-only. Nothing was changed."}, status=403)
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
                role = auth_store.login_role(payload.get("password") or "")
                if role is None:
                    _record_login_failure(client_ip)
                    self._send_json({"ok": False, "error": "Wrong password."}, status=401)
                    return
                _clear_login_failures(client_ip)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._set_session_cookie(role)
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/reset-password":
                client_ip = self.client_address[0]
                if _login_rate_limited(client_ip):
                    self._send_json({"ok": False, "error": "Too many failed attempts -- wait a few minutes and try again."}, status=429)
                    return
                if not auth_store.is_password_set():
                    self._send_json({"ok": False, "error": "No password set yet."}, status=400)
                    return
                new_password = payload.get("password") or ""
                if payload.get("confirm") != new_password:
                    self._send_json({"ok": False, "error": "Passwords don't match."}, status=400)
                    return
                if len(new_password.strip()) < 8:
                    self._send_json({"ok": False, "error": "Password must be at least 8 characters."}, status=400)
                    return
                try:
                    new_key = auth_store.reset_password_with_recovery_key(payload.get("recovery_key") or "", new_password)
                except PermissionError as exc:
                    _record_login_failure(client_ip)
                    self._send_json({"ok": False, "error": str(exc)}, status=401)
                    return
                _clear_login_failures(client_ip)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._set_session_cookie()
                body = json.dumps({"ok": True, "recovery_key": new_key}).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/check-update":
                self._send_json(production.check_for_update())
                return
            if path == "/api/update-feed":
                url = (payload.get("url") or "").strip()
                if url and not url.lower().startswith("https://"):
                    self._send_json({"ok": False, "error": "The update address must start with https://."}, status=400)
                    return
                app_settings.set_update_feed_url(url)
                self._send_json({"ok": True})
                return
            if path == "/api/recovery-key":
                if not auth_store.verify_password(payload.get("password") or ""):
                    self._send_json({"ok": False, "error": "Wrong password."}, status=401)
                    return
                self._send_json({"ok": True, "recovery_key": auth_store.new_recovery_key()})
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
            if path == "/api/viewer-password":
                if payload.get("remove"):
                    auth_store.clear_viewer_password()
                else:
                    auth_store.set_viewer_password(payload.get("password") or "")
                self._send_json({"ok": True, "set": auth_store.is_viewer_password_set()})
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
                # new Assets-tab line item for a not-yet-classified Plaid
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
            elif path == "/api/account-owner/set":
                # Who owns a live linked account that isn't tied to an
                # Assets-tab row (an Asset row's own owner goes through
                # /api/line-item/update) -- see source.common.db.owners.
                db.set_account_owner(payload.get("account_id") or "", payload.get("owner") or "")
                self._send_json({"ok": True})
            elif path == "/api/assumptions":
                updates = {}
                for key, raw in payload.items():
                    if raw in (None, ""):
                        continue
                    if isinstance(raw, str):
                        # "$3,200" and "3,200" are fine to type; store the plain number.
                        raw = db.clean_number_text(raw)
                        if key.startswith(("ss_benefit_", "ss_claim_age_", "medicare_")):
                            try:
                                float(raw)
                            except ValueError:
                                raise ValueError("Enter a number only, for example 3,200.") from None
                    if key.endswith("_pct"):
                        updates[key[: -len("_pct")]] = float(raw) / 100.0
                    else:
                        updates[key] = raw
                db.set_assumptions(updates)
                self._send_json({"ok": True})
            elif path == "/api/benefits/claiming-analysis":
                self._send_json({"ok": True, **benefits.analyze_claiming(build_summary(), str(payload.get("person") or "self"))})
            elif path == "/api/benefits/apply":
                # Social Security & Medicare planner (Income & Expenses tab):
                # writes the saved planner inputs as ordinary rows.
                result = benefits.apply_benefits_plan(db.get_assumptions())
                self._send_json({"ok": True, **result})
            elif path == "/api/scenarios/save":
                scenario_id = db.save_scenario(
                    payload.get("name") or "", scenarios_module.snapshot_assumptions(db.get_assumptions()),
                )
                self._send_json({"ok": True, "id": scenario_id})
            elif path == "/api/scenarios/delete":
                self._send_json({"ok": db.delete_scenario(int(payload["id"]))})
            elif path == "/api/scenarios/load":
                self._send_json({"ok": scenarios_module.restore_scenario(int(payload["id"]))})
            elif path == "/api/scenarios/compare":
                results = scenarios_module.compare_scenarios(build_summary(), db.list_scenarios())
                self._send_json({"ok": True, "results": results})
            elif path == "/api/quit":
                # Setup's "Quit" button -- the app has no window of its own to close.
                self._send_json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif path == "/api/household":
                db.set_household(
                    self_name=str(payload.get("self_name") or ""),
                    spouse_name=str(payload.get("spouse_name") or ""),
                    has_spouse=bool(payload.get("has_spouse")),
                )
                self._send_json({"ok": True, "household": db.household()})
            elif path == "/api/backup-keep":
                keep = int(payload.get("keep"))
                if not 1 <= keep <= 100:
                    raise ValueError("Keep between 1 and 100 backups.")
                app_settings.set_backup_keep(keep)
                backup.prune_backups()
                self._send_json({"ok": True, "keep": backup.keep_count()})
            elif path == "/api/sample-data":
                if payload.get("action") == "remove":
                    self._send_json({"ok": True, "removed": demo_data.remove_sample_data()})
                else:
                    if db.setup_needed() is False and not demo_data.has_sample_data():
                        raise ValueError("Sample data can only be loaded into an empty plan.")
                    demo_data.seed_sample_household(with_linked=bool(payload.get("with_linked")))
                    self._send_json({"ok": True})
            elif path == "/api/legacy-whatif":
                if payload.get("clear"):
                    db.set_legacy_whatif(None)
                    self._send_json({"ok": True, "whatif": None})
                else:
                    from source.reporting.monte_carlo import normalize_custom_strategy

                    spec = normalize_custom_strategy(payload)
                    db.set_legacy_whatif(spec)
                    self._send_json({"ok": True, "whatif": spec})
            elif path == "/api/tour-seen":
                db.set_tour_seen(True)
                self._send_json({"ok": True})
            elif path == "/api/view-mode":
                db.set_view_mode(str(payload.get("mode") or ""))
                self._send_json({"ok": True, "mode": db.view_mode()})
            elif path == "/api/wording-mode":
                db.set_wording_mode(str(payload.get("mode") or ""))
                self._send_json({"ok": True, "mode": db.wording_mode()})
            elif path == "/api/dollars-mode":
                db.set_dollars_mode(str(payload.get("mode") or ""))
                self._send_json({"ok": True, "mode": db.dollars_mode()})
            elif path == "/api/what-if":
                if payload.get("custom"):
                    self._send_json({"ok": True, **what_if.run_custom_what_if(build_summary(), payload, db.dollars_mode())})
                else:
                    self._send_json({"ok": True, "results": what_if.run_what_ifs(build_summary())})
            elif path == "/api/target-allocation":
                from source.reporting import rebalance
                from source.webapp.pages.rebalance_page import _age

                if payload.get("use_suggested"):
                    target = rebalance.set_target(rebalance.suggested_target(_age(db.get_assumptions())))
                else:
                    target = rebalance.set_target(payload)
                self._send_json({"ok": True, "target": target})
            elif path == "/api/risk-appetite":
                from source.reporting import rebalance
                from source.webapp.pages.rebalance_page import _age

                target = rebalance.set_risk(str(payload.get("level") or ""), _age(db.get_assumptions()))
                self._send_json({"ok": True, "target": target})
            elif path == "/api/clear-sector-tags":
                ids = [str(x) for x in (payload.get("security_ids") or []) if str(x)]
                db.clear_security_sectors(ids)
                db.clear_security_industries(ids)
                self._send_json({"ok": True, "cleared": len(ids)})
            elif path == "/api/alerts-dismiss":
                from source.reporting import alerts

                if payload.get("all"):
                    alerts.dismiss_all()
                else:
                    alerts.dismiss(str(payload.get("id") or ""))
                self._send_json({"ok": True})
            elif path == "/api/alert-settings":
                from source.reporting import alerts

                self._send_json({"ok": True, "settings": alerts.save_settings(payload)})
            elif path == "/api/alert-test-email":
                from source.reporting import alerts

                alerts.send_test()
                self._send_json({"ok": True})
            elif path == "/api/backup-restore":
                if auth_store.is_password_set() and not auth_store.verify_password(payload.get("password") or ""):
                    self._send_json({"ok": False, "error": "Wrong password. Nothing was changed."}, status=401)
                    return
                try:
                    result = backup.restore_backup(payload.get("filename") or "")
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self._send_json({"ok": True, **result})
            elif path == "/api/backup-verify":
                self._send_json({"ok": True, **backup.verify_latest()})
            elif path == "/api/asset-class":
                from source.reporting import rebalance

                rebalance.set_override(str(payload.get("security_id") or ""), str(payload.get("asset_class") or ""))
                self._send_json({"ok": True})
            elif path == "/api/safe-spending":
                try:
                    target = float(payload.get("target") or db.safe_spend_target())
                except (TypeError, ValueError):
                    target = db.safe_spend_target()
                if not 0.5 <= target <= 0.99:
                    raise ValueError("Target must be between 50% and 99%.")
                if payload.get("save"):
                    db.set_safe_spend_target(target)   # the Summary shows the level picked on the Will my money last? tab
                self._send_json({"ok": True, **_safe_spending_cached(build_summary(), target)})
            elif path == "/api/setup-complete":
                db.set_setup_complete(True)
                self._send_json({"ok": True})
            elif path == "/api/rentcast-key":
                secrets_store.set_rentcast_api_key(payload.get("api_key") or "")
                self._send_json({"ok": True})
            elif path in trading_api.ROUTES:
                # The Trading tab (Alpaca practice and live accounts) -- see
                # source.webapp.trading_api for the safety rules.
                self._send_json({"ok": True, **trading_api.handle(path, payload)})
            elif path == "/api/real-estate/refresh-value":
                # One RentCast lookup (one request against the plan's monthly
                # allowance) for one property, on a button press only.
                row = db.get_line_item("real_estate", int(payload["id"]))
                if not row:
                    raise ValueError("That property no longer exists.")
                address = (row.get("address") or "").strip()
                if not address and (row.get("name") or "").strip()[:1].isdigit():
                    # Properties are often named by their street address.
                    address = row["name"].strip()
                try:
                    api_key = secrets_store.get_rentcast_api_key()
                    estimate = rentcast.fetch_value_estimate(address, api_key)
                except (secrets_store.SecretNotFoundError, rentcast.RentCastError) as exc:
                    raise ValueError(str(exc)) from exc
                db.update_line_item("real_estate", row["id"], {
                    "current_value": estimate["price"], "value_updated_at": date.today().isoformat(),
                })
                self._send_json({"ok": True, **estimate})
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
            elif path == "/api/auto-sync-settings":
                # Setup page's "Automatic sync" card -- see source.common.
                # app_settings and source.collector.auto_sync for what
                # these two settings actually do (and their real
                # limitation: only checked at app-open time, never on a
                # day nobody opens this app at all).
                if "enabled" in payload:
                    app_settings.set_auto_sync_enabled(bool(payload["enabled"]))
                if payload.get("interval_days"):
                    app_settings.set_auto_sync_interval_days(int(payload["interval_days"]))
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
                # Same idea, one investment-account balance point per
                # account for today -- see capture_investment_account_
                # balances' own docstring. Also best-effort/idempotent.
                try:
                    capture_investment_account_balances()
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
                # Always ADDS a new rule (or replaces the category/match_
                # mode on an existing one for the same rule_type+match_key
                # pair) -- see /api/category-rule/update just below for
                # editing an existing row's own match_key/rule_type.
                rule_id = db.upsert_category_rule(
                    rule_type=(payload.get("rule_type") or "").strip(),
                    match_key=payload.get("match_key") or "",
                    category=payload.get("category") or "",
                    match_mode=(payload.get("match_mode") or "contains").strip(),
                    kind=(payload.get("kind") or "").strip(),
                )
                changed = db.recategorize_all_transactions()
                self._send_json({"ok": True, "id": rule_id, "recategorized": changed})
            elif path == "/api/category-rule/update":
                # Setup page's per-row "Save" button once a rule is being
                # edited in place -- unlike /api/category-rule/save above,
                # this changes the SAME row (by id) no matter what about
                # it changes, including its own match_key/rule_type (see
                # source.common.db.category_rules.update_category_rule).
                # A ValueError here (bad rule_type/match_mode, or the
                # edited pair collides with a different existing rule)
                # surfaces as this request's own 400 -- see the broad
                # except below.
                db.update_category_rule(
                    int(payload.get("id")),
                    rule_type=(payload.get("rule_type") or "").strip(),
                    match_key=payload.get("match_key") or "",
                    category=payload.get("category") or "",
                    match_mode=(payload.get("match_mode") or "contains").strip(),
                    kind=(payload.get("kind") or "").strip(),
                )
                changed = db.recategorize_all_transactions()
                self._send_json({"ok": True, "recategorized": changed})
            elif path == "/api/category-rule/delete":
                deleted = db.delete_category_rule(int(payload.get("id")))
                changed = db.recategorize_all_transactions() if deleted else 0
                self._send_json({"ok": True, "deleted": deleted, "recategorized": changed})
            elif path == "/api/category-rule/apply":
                # Setup page's per-row "Apply" button -- force-applies
                # ONE rule to every transaction it matches, including
                # ones already hand-edited (category_edited_by_user=1),
                # and sets income_kind_override from the rule's own Kind
                # dropdown. See source.common.db.transactions.apply_
                # category_rule for exactly why this is a separate,
                # explicit action rather than automatic on every save --
                # a ValueError here (no such rule) surfaces as this
                # request's own 400 -- see the broad except below.
                result = db.apply_category_rule(int(payload.get("id")))
                self._send_json({"ok": True, **result})
            elif path == "/api/category-rule/apply-all":
                # Setup page's single "Apply all rules" button -- the
                # same force-apply as /api/category-rule/apply, for every
                # saved rule at once (see source.common.db.transactions.
                # apply_all_category_rules for the precedence order).
                result = db.apply_all_category_rules()
                self._send_json({"ok": True, **result})
            elif path == "/api/category-rule/apply-from-transaction":
                # Actual Spending page's per-row "Categorize similar"
                # link -- turns one transaction into a keyword rule from
                # its own already-set category, without a person having
                # to type a keyword by hand on Setup (see source.common.
                # db.transactions.apply_category_rule_from_transaction
                # for exactly how the keyword is derived and why this
                # applies retroactively too). A ValueError here (no such
                # transaction, or no usable keyword) surfaces as this
                # request's own 400 -- see the broad except below.
                result = db.apply_category_rule_from_transaction(payload.get("transaction_id") or "")
                self._send_json({"ok": True, **result})
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
                # Link) before Actual Spending has anything to sync for
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
            elif path == "/api/plaid-connect-auth":
                # Backs the Setup page's per-Item "Enable full account numbers"
                # button: the same one-time Plaid update-mode Link as Enable
                # Transactions, asking for the Auth product so a sync can
                # store the real account / routing numbers of that bank's
                # checking, savings and cash accounts.
                item_key = (payload.get("item_key") or "").strip()
                if not item_key:
                    raise ValueError("Item key is required.")
                plaid_link_item.enable_auth_for_item(item_key)
                self._send_json({"ok": True})
            elif path == "/api/classify-transaction-category":
                # Backs the Actual Spending page's multi-select "Set
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
                # Backs the Actual Spending page's "Exclude from total"/
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
            elif path == "/api/classify-transaction-income-kind":
                # Backs the Actual Spending page's "Mark as income"/"Mark
                # as expense"/"Auto-detect" buttons -- an explicit person-
                # set override (plaid_categorize.is_real_income's own
                # income_kind_override) that beats the text-based
                # heuristics outright, for exactly the case those
                # heuristics can't win: a manually-retyped category that
                # IS income but doesn't literally contain the word
                # "income" ("salary", "Rental-mp", "tax-refund" were real
                # examples that were falling out of "real income" with no
                # override to set instead).
                items = payload.get("items") or []
                transaction_ids = [item["transaction_id"] for item in items if item.get("transaction_id")]
                kind = (payload.get("kind") or "").strip().lower()
                count = db.update_plaid_transaction_income_kind(transaction_ids, kind)
                self._send_json({"ok": True, "count": count})
            else:
                self._send_json({"ok": False, "error": "Not found"}, status=404)
        except xlsx_import.ImportError_ as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
        except (KeyError, ValueError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json({"ok": False, "error": tls.friendly_error(str(exc))}, status=500)


_DAILY_SNAPSHOT_CHECK_SECONDS = 15 * 60


def _daily_snapshot_loop(*, interval_seconds: float = _DAILY_SNAPSHOT_CHECK_SECONDS, max_ticks: int | None = None) -> None:
    """Wakes every `interval_seconds` and records a new day's snapshot the
    first time the local date differs from the last one it captured (see
    aggregate.capture_daily_snapshots_if_new_day) -- it starts with none,
    so its first tick records today (idempotent after run()'s own startup
    capture, and a safety net if that one failed). A failed
    capture is logged and retried on the next tick rather than stopping
    the loop. `max_ticks` exists only so a test can run the loop a fixed
    number of times instead of forever."""
    # None, not today: capture_daily_snapshots_if_new_day treats "no previous
    # date" as "capture now", so the first tick still records a day that
    # rolled over (or a run() capture that failed) instead of waiting a day.
    last_captured = None
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        time.sleep(interval_seconds)
        ticks += 1
        try:
            last_captured = capture_daily_snapshots_if_new_day(last_captured)
        except Exception as exc:
            print(f"Daily snapshot failed (will retry): {exc}")
        try:
            from source.reporting import alerts

            alerts.run_daily_job()
        except Exception as exc:
            print(f"Daily alerts check failed (will retry): {exc}")


def _quit_cleanly() -> None:
    """Turns the "quit" signals a Mac sends an app (Quit, logout, shutdown) into a normal exit, so the shutdown code runs and the
    IBKR gateway started with the app is stopped too. (Without this the process just ends and the gateway is left running.)"""
    import signal as _signal
    if threading.current_thread() is not threading.main_thread() or "unittest" in sys.modules:
        return

    def _exit(signum, frame):
        raise SystemExit(0)
    for name in ("SIGTERM", "SIGHUP"):
        try:
            _signal.signal(getattr(_signal, name), _exit)
        except (AttributeError, ValueError, OSError):
            pass


def run(*, open_browser: bool = True) -> None:
    # Real launches (Mac app or from source) ask for an admin password and
    # database setup first; tests and the throwaway demo never do.
    first_run.enforce(not config.DEMO)
    tls.use_system_certificates()
    config.ensure_directories()
    db.init_db()
    if config.DEMO and not db.list_line_items("assets"):
        demo_data.seed_sample_household(with_history=True, with_linked=True)
        db.set_setup_complete(True)
    production.protect_files()
    # First time the app is opened today, today gets a backup -- see
    # source.common.backup's module docstring for why this (rather than
    # a cron job or background thread) is the "automatic" mechanism.
    # Best-effort: a backup failure (disk full, permissions) shouldn't
    # stop the dashboard itself from starting.
    try:
        backup.ensure_daily_backup()
    except Exception as exc:
        print(f"Startup backup failed (continuing anyway): {exc}")
    production.protect_files()     # includes the backup just taken

    # One net-worth-history data point for today, from whatever's already
    # in the database -- see aggregate.capture_net_worth_snapshot's own
    # docstring. Best-effort, same as the backup above: a snapshot
    # failure shouldn't stop the dashboard itself from starting.
    try:
        capture_net_worth_snapshot()
    except Exception as exc:
        print(f"Startup net-worth snapshot failed (continuing anyway): {exc}")

    # Same idea, one investment-account balance point per account for
    # today -- see aggregate.capture_investment_account_balances' own
    # docstring. Best-effort, same as above.
    try:
        capture_investment_account_balances()
    except Exception as exc:
        print(f"Startup investment-balance snapshot failed (continuing anyway): {exc}")

    # Keeps the history growing on days nobody opens the app: while this
    # process is running, a background timer re-checks the date every
    # few minutes and records that new day's net-worth/investment-balance
    # snapshot as soon as the date rolls over (see
    # aggregate.capture_daily_snapshots_if_new_day). A daemon thread, so
    # it never keeps the dashboard from shutting down; best-effort, same
    # as the startup captures above.
    threading.Thread(target=_daily_snapshot_loop, daemon=True).start()

    # Catches up on Plaid data if it's gone stale (see source.collector.
    # auto_sync's own module docstring for exactly when this fires, and
    # its real limitation -- it only ever runs at a moment this app is
    # already being opened). On a background thread so a slow sync (many
    # linked accounts/transactions) never delays the dashboard itself
    # from becoming reachable; best-effort, same as the backup/snapshot
    # above.
    def _run_auto_sync_in_background() -> None:
        try:
            if auto_sync.sync_if_due():
                print("Auto-sync: Plaid data was stale, synced automatically.")
        except Exception as exc:
            print(f"Auto-sync failed (continuing anyway): {exc}")

    threading.Thread(target=_run_auto_sync_in_background, daemon=True).start()

    bind_host = "127.0.0.1" if config.DEMO else app_settings.get_bind_host()
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
    # IBKR's Client Portal Gateway (bundled, runs on this computer only) starts with the app and stops when it quits.
    ibkr_gateway.start_with_app()
    _quit_cleanly()
    warm.enable(not config.DEMO)
    warm.schedule(delay=1.0)
    url = f"http://127.0.0.1:{PORT}/" if bind_host == "127.0.0.1" else f"http://{bind_host}:{PORT}/ (and http://127.0.0.1:{PORT}/)"
    print(f"{branding.PRODUCT_NAME} dashboard running at {url}")
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
    finally:
        server.server_close()
        ibkr_gateway.stop()


if __name__ == "__main__":
    run(open_browser="--no-browser" not in sys.argv)
