"""The Setup tab: one-time workbook import, data/output/log locations,
Plaid linking, and the automatic-backups card."""

from __future__ import annotations

import html

from source.webapp.pages.alerts_card import alerts_settings_card_html
from source.webapp.pages.about_card import about_card_html, transfer_card_html
from source.collector import auto_sync
from source.common import app_settings, auth_store, backup, branding, config, db, plaid_categorize, secrets_store
from source.webapp.render_helpers import _shell


def _render_setup_page() -> str:
    data_status = config.data_dir_status()
    output_status = config.output_dir_status()
    import_path = str(config.import_xlsx_path())
    last_import = db.get_meta("last_import_at")
    last_export = db.get_meta("last_export_at")
    backups = backup.list_backups()

    presence = secrets_store.vault_presence()
    items = db.list_plaid_items()
    plaid_accounts = db.list_plaid_accounts()

    def item_row(item):
        synced = item["last_synced_at"] or "never"
        profile = (item.get("credential_profile") or "primary").strip().lower()
        profile_label = secrets_store.PROFILE_LABELS.get(profile, profile)
        products = {p.strip() for p in (item["products"] or "").split(",") if p.strip()}
        # An Item only ever gets the products it was originally linked
        # with -- one linked before Actual Spending existed (or linked
        # without explicitly requesting "transactions") needs this
        # one-time re-consent via Plaid "update mode" Link before it has
        # anything to sync there; see source.collector.link_item.
        # enable_transactions_for_item. Once granted, "transactions" shows
        # up in the Products column like any other product and this
        # button is gone -- nothing left to enable.
        enable_transactions_button = (
            "" if "transactions" in products else
            f'<button onclick="enableTransactionsForItem({item["item_key"]!r})">Enable Transactions</button>'
        )
        # Full account numbers come only from Plaid's Auth product, and only for deposit accounts.
        has_deposit_account = any(a["item_key"] == item["item_key"] and a["type"] == "depository" for a in plaid_accounts)
        enable_auth_button = (
            "" if "auth" in products or not has_deposit_account else
            f'<button onclick="enableAuthForItem({item["item_key"]!r})">Enable full account numbers</button>'
        )
        return (
            f'<tr><td>{html.escape(item["item_key"])}</td>'
            f'<td>{html.escape(item["institution_name"] or "")}</td>'
            f'<td>{html.escape(item["products"] or "")}</td>'
            f'<td>{html.escape(item["environment"])}</td>'
            f'<td>{html.escape(profile_label)}</td>'
            f'<td>{html.escape(synced)}</td>'
            f'<td>{enable_transactions_button}{enable_auth_button}'
            f'<button class="danger" onclick="removePlaidItem({item["item_key"]!r})">Remove</button></td></tr>'
        )

    items_rows_html = "".join(item_row(i) for i in items) or (
        '<tr><td colspan="7" class="muted">No accounts linked yet.</td></tr>'
    )

    def backup_row(b):
        return (
            f'<tr><td>{html.escape(b["modified_at"])}</td>'
            f'<td>{html.escape(b["filename"])}</td>'
            f'<td class="num">{_format_bytes(b["size_bytes"])}</td></tr>'
        )

    backup_rows_html = "".join(backup_row(b) for b in backups[:10]) or (
        '<tr><td colspan="3" class="muted">No backups yet -- the first one is taken automatically the next time you open this app.</td></tr>'
    )
    backup_status_line = (
        f"{len(backups)} backup{'s' if len(backups) != 1 else ''} on disk, most recent {html.escape(backups[0]['modified_at'])}."
        if backups else "No backups yet."
    )

    health = backup.verify_latest()
    if not health["exists"]:
        backup_health_line = "Health: no backup to check yet."
    elif health["ok"]:
        backup_health_line = f"Health: latest backup is {health['age_days']:.0f} day(s) old and opens correctly."
    else:
        backup_health_line = f"Health: PROBLEM with the latest backup &mdash; {html.escape(health['error'])}"

    password_set = auth_store.is_password_set()
    restore_html = _restore_form_html(backups, password_set)
    bind_host = app_settings.get_bind_host()
    quit_html = _quit_card_html()
    security_html = _security_card_html(password_set=password_set)
    network_html = _network_access_card_html(bind_host=bind_host, password_set=password_set)
    known_transaction_categories = sorted({
        (t["category"] or "").strip() for t in db.list_plaid_transactions() if (t["category"] or "").strip()
    })
    category_options_html = "".join(f"<option>{html.escape(c)}</option>" for c in known_transaction_categories)
    category_rules_html = _category_rules_card_html(
        rules=db.list_category_rules(), category_options_html=category_options_html,
    )
    auto_sync_html = _auto_sync_card_html()
    live_limits_html = _live_limits_card_html()
    rentcast_html = _rentcast_card_html(has_key=secrets_store.has_rentcast_api_key())
    plaid_credentials_html = "".join(
        _plaid_credentials_profile_html(profile=name, presence=presence.profiles[name]) for name in secrets_store.PROFILES
    )
    profile_options_html = "".join(
        f'<option value="{name}">{html.escape(label)}</option>'
        for name, label in secrets_store.PROFILE_LABELS.items()
    )

    household_html = _household_card_html()
    sample_html = _sample_data_card_html()
    body = f"""
<div class="wizard-callout">
<div><strong>New here? Start with the Setup Wizard.</strong><br><span>A guided walk through the basics, with Fin to explain each step.</span></div>
<a class="wizard-btn" href="/setup-wizard.html">Run the Setup Wizard</a>
</div>
<style>
.wizard-callout {{ display:flex; align-items:center; justify-content:space-between; gap:14px; flex-wrap:wrap; margin:6px 0 16px; padding:16px 20px;
  border-radius:16px; border:2px solid var(--brand); background:color-mix(in srgb, var(--brand) 12%, var(--surface)); }}
.wizard-callout strong {{ font-size:18px; font-weight:700; color:var(--ink); }}
.wizard-callout span {{ font-size:14.5px; color:var(--ink-soft); }}
.wizard-btn {{ display:inline-block; padding:11px 22px; border-radius:999px; background:var(--brand); color:#fff !important; font-size:16px; font-weight:700; text-decoration:none; }}
.wizard-btn:hover {{ background:var(--brand-dark); }}
</style>
{household_html}
{sample_html}

<h2 id="plaid-keys">Plaid API keys</h2>
<p class="muted">Two independent Plaid credential profiles -- Primary and Secondary -- each with its own client ID and per-environment secret, stored only in this Mac's Keychain (never sent anywhere except directly to Plaid). Most people only ever need Primary; Secondary is there if you have a second Plaid developer account (e.g. a separate app, or you've hit a per-app linked-Item limit) and want this dashboard to link/sync accounts under both side by side.</p>
{plaid_credentials_html}

<h2 id="connect-account">Connect an account</h2>
<p class="muted">Opens Plaid Link in a new browser tab -- log in to your bank/brokerage there (your credentials go straight to the bank/Plaid, never through this program). This request waits (up to 5 minutes) until you finish in that tab.</p>
<p class="muted">"Full account number" only works for a checking, savings, or cash-management account (Plaid's Auth product doesn't cover investment, loan, or credit accounts at all) -- check it when connecting one of those and this program stores the real account/routing number alongside the balance, instead of just the last few digits.</p>
<form class="inline" onsubmit="event.preventDefault();
  var btn = this.querySelector('button');
  btn.disabled = true; btn.textContent = 'Waiting for Plaid Link in the new tab...';
  var products = this.products.value;
  var wantAuth = this.full_account_number.checked;
  var list = products.split(',').map(function(p) {{ return p.trim(); }}).filter(function(p) {{ return p; }});
  if (wantAuth && list.indexOf('auth') === -1) {{ list.push('auth'); }}
  postJSON('/api/plaid-connect', {{item_key: this.item_key.value, products: list.join(','), environment: this.environment.value, profile: this.profile.value}})
    .then(function() {{ location.reload(); }})
    .catch(function(e) {{ alert(e.message); btn.disabled = false; btn.textContent = 'Connect'; }});">
  <label>Item key<input name="item_key" placeholder="e.g. wells_fargo_checking" required></label>
  <label>Products<input name="products" value="investments" placeholder="investments, transactions"></label>
  <label style="flex-direction: row; align-items: center; gap: 6px;"><input type="checkbox" name="full_account_number" style="width: auto;"> Full account number (checking/savings only)</label>
  <label>Environment<select name="environment"><option value="production">production</option><option value="sandbox">sandbox</option></select></label>
  <label>Plaid app<select name="profile">{profile_options_html}</select></label>
  <button type="submit" class="primary">Connect</button>
</form>

<details class="card" id="linked-accounts-card" style="padding:12px 16px;">
<summary style="font-weight:600;">Linked accounts ({len(items)})</summary>
<table class="sortable">
<thead><tr><th>Item key</th><th>Institution</th><th>Products</th><th>Env</th><th>Plaid app</th><th>Last synced</th><th></th></tr></thead>
<tbody>{items_rows_html}</tbody>
</table>
<p class="muted">"Sync now" (pulls current balances/holdings/transactions from Plaid) has moved -- it's on the <a href="/summary.html">Summary</a>, <a href="/linked-accounts.html">Linked Accounts</a>, <a href="/linked-positions.html">Linked Positions</a>, and <a href="/real-expenditure.html">Actual Spending</a> pages now, next to the data it actually refreshes. An Item's "Enable Transactions" button above (shown until its Products column already includes "transactions") opens Plaid Link once more so it can start syncing spend history for <a href="/real-expenditure.html">Actual Spending</a> -- no need to unlink and relink it from scratch.</p>
</details>

{security_html}

{alerts_settings_card_html()}

{about_card_html()}

{transfer_card_html()}

<details class="advanced-group" id="advanced-settings" style="margin:16px 0;">
<summary style="font-weight:650; font-size:15px; cursor:pointer;">Advanced settings <span class="muted">(data locations, category rules, automatic sync, property values, network access)</span></summary>
<h2>Data &amp; output locations</h2>
<p class="status-line">Data (retirement_plan.db): {html.escape(data_status['current'])}</p>
<p class="status-line">Output (Excel exports): {html.escape(output_status['current'])}</p>
<p class="status-line">{'Last export: ' + html.escape(last_export) if last_export else 'No export generated yet.'}</p>
<form class="inline" onsubmit="event.preventDefault(); postJSON('/api/export', {{}}).then(function(d) {{ alert('Exported: ' + d.path); }}).catch(function(e) {{ alert(e.message); }});">
  <button type="submit" class="primary">Generate Excel export</button>
</form>
<p class="muted">Writes a fresh .xlsx snapshot of everything currently in this program to the output folder.</p>

<details class="card" id="backups-card" style="padding:12px 16px;">
<summary style="font-weight:600;">Backups ({len(backups)})</summary>
<p class="muted">A timestamped copy of retirement_plan.db is taken automatically the first time you open this app each day, and again right before every workbook import -- the two moments most likely to need a way back. Backups live in {html.escape(str(backup.backup_dir()))}, keeping the most recent {backup.keep_count()} (older ones are deleted automatically). To go back to an earlier copy, use <strong>Restore a backup</strong> below. Your current data is saved first, so a restore can itself be undone.</p>
<p class="status-line">{backup_status_line}</p>
<p class="small" id="backup-health">{backup_health_line}
  <button type="button" class="chip" onclick="var b = this; b.disabled = true; postJSON('/api/backup-verify', {{}}).then(function(r) {{ b.disabled = false; document.getElementById('backup-health-result').textContent = r.ok ? ('Passed: ' + r.filename + ' opens correctly and passes SQLite\\'s integrity check.') : ('Problem: ' + (r.error || 'could not be opened')); }}).catch(function(e) {{ b.disabled = false; alert(e.message); }});">Test latest backup</button>
  <span id="backup-health-result" class="muted"></span></p>
<form class="inline" onsubmit="event.preventDefault();
  var btn = this.querySelector('button');
  btn.disabled = true; btn.textContent = 'Backing up...';
  postJSON('/api/backup-now', {{}})
    .then(function() {{ location.reload(); }})
    .catch(function(e) {{ alert(e.message); btn.disabled = false; btn.textContent = 'Back up now'; }});">
  <button type="submit" class="primary">Back up now</button>
</form>
<table class="sortable">
<thead><tr><th>When</th><th>File</th><th class="num">Size</th></tr></thead>
<tbody>{backup_rows_html}</tbody>
</table>
{restore_html}
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/backup-keep', {{keep: this.keep.value}})
    .then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Backups to keep (1-100)<input name="keep" type="number" min="1" max="100" step="1" value="{backup.keep_count()}" style="width:80px"></label>
  <button type="submit">Save</button>
</form>
</details>

<details class="card" id="category-rules-card" style="padding:12px 16px;">
<summary style="font-weight:600;">Category rules ({len(db.list_category_rules())})</summary>
{category_rules_html}
</details>
{auto_sync_html}
{rentcast_html}
{network_html}
</details>
{live_limits_html}
{quit_html}

<details class="card" style="padding:12px 16px;">
<summary style="font-weight:600;">Advanced: import a spreadsheet (one time)</summary>
<h2 style="margin-top:8px">One-time workbook import</h2>
<p class="muted">Point this at a retirement-plan .xlsx once to seed Real Estate, Assets (401k/IRA, Liquid), Expenses, Income (Rental, Social Security), and the plan assumptions from its Summary &amp; Assumptions and Real Estate sheets. This program becomes the system of record after that -- re-running this only refreshes rows it previously imported (source='imported'); anything you've typed in by hand is left alone.</p>
<p class="status-line">{'Last imported: ' + html.escape(last_import) if last_import else 'Not imported yet.'}</p>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/import', {{path: this.path.value, password: this.password.value}})
    .then(function(d) {{ alert('Imported: ' + JSON.stringify(d.summary)); location.reload(); }})
    .catch(function(e) {{ alert(e.message); }});">
  <label>Workbook path<input name="path" style="width:300px" value="{html.escape(import_path)}"></label>
  <button type="button" onclick="chooseWorkbookFile(this.form)">Browse&hellip;</button>
  <label>Password (if protected)<input name="password" type="password"></label>
  <button type="submit" class="primary">Import</button>
</form>
</details>
"""
    return _shell(title="Setup", active="setup.html", body=body)


def _quit_card_html() -> str:
    """The Mac app runs without a window of its own, so this is how it is
    closed: it stops the program (the next launch starts it again)."""
    return f"""
<div class="card">
<h2 style="margin-top:0">Quit {html.escape(branding.PRODUCT_NAME)}</h2>
<p class="muted">Stops the program running on this computer. Open the app again any time to start it; your data is kept.</p>
<button type="button" onclick="if (confirm('Quit {html.escape(branding.PRODUCT_NAME)}?')) {{ postJSON('/api/quit', {{}}).then(function() {{ document.body.innerHTML = '<p style=&quot;font-family:sans-serif;padding:40px&quot;>{html.escape(branding.PRODUCT_NAME)} has quit. You can close this tab.</p>'; }}); }}">Quit {html.escape(branding.PRODUCT_NAME)}</button>
</div>
"""


def _sample_data_card_html() -> str:
    """Offered only while sample rows exist: one click removes every row the
    "Load sample household" button added, and nothing you typed yourself."""
    from source.common import demo_data

    if not demo_data.has_sample_data():
        return ""
    linked = demo_data.has_sample_linked()
    linked_note = (
        "Pretend linked accounts (a brokerage and a bank, with holdings and a year of transactions) are loaded too."
        if linked else
        "You can also add pretend linked accounts, holdings and a year of transactions to try every tab."
    )
    add_button = "" if linked else (
        """<button type="button" class="primary" onclick="postJSON('/api/sample-data', {with_linked: true}).then(function() { location.reload(); }).catch(function(e) { alert(e.message); });">Add sample linked accounts</button> """
    )
    return f"""
<div class="card" id="sample-data">
<h2 style="margin-top:0">Sample data</h2>
<p class="muted">The example household (Alex and Sam) is loaded so you can look around. {linked_note} Remove it before entering your own numbers -- only the sample rows are deleted, anything you typed stays. Names and assumptions it set can be changed above and on the Will my money last? page.</p>
{add_button}<button type="button" onclick="if (confirm('Remove the sample household rows and sample accounts?')) {{ postJSON('/api/sample-data', {{action: 'remove'}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }}); }}">Remove sample data</button>
</div>
"""


def _household_card_html() -> str:
    """Who the plan is for: the first person's name, an optional second
    person (spouse or partner) and their name. Drives every label, the
    Owner dropdowns and the second birth-year fields across the app."""
    household = db.household()
    checked = " checked" if household["has_spouse"] else ""
    return f"""
<div class="card" id="household">
<h2 style="margin-top:0">Household</h2>
<p class="muted">The names shown on every page and in the Owner dropdowns. Turn the second person off for a one-person plan -- their fields, columns and Social Security rows then disappear (rows the Social Security planner wrote for them are removed the next time you apply it).</p>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/household', {{self_name: this.self_name.value, spouse_name: this.spouse_name.value, has_spouse: this.has_spouse.checked}})
    .then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>First person<input name="self_name" maxlength="40" value="{html.escape(household['self_name'])}"></label>
  <label style="flex-direction: row; align-items: center; gap: 6px;"><input type="checkbox" name="has_spouse" style="width:auto;"{checked}> Spouse or partner</label>
  <label>Their name<input name="spouse_name" maxlength="40" value="{html.escape(household['spouse_name'])}"></label>
  <button type="submit" class="primary">Save</button>
</form>
</div>
"""


def _rentcast_card_html(*, has_key: bool) -> str:
    status = (
        '<p class="status-line status-ok">A RentCast API key is saved in your Keychain.</p>' if has_key
        else '<p class="status-line">No RentCast key saved. Property values stay as you type them.</p>'
    )
    return f"""
<div class="card">
<h2 style="margin-top:0">Property value estimates (RentCast, optional)</h2>
<p class="muted">With a RentCast API key, each property on the <a href="/real-estate.html">Real Estate</a> tab gets an
"Update value" button that fetches RentCast's estimated market value for its address and puts it in Current Value.
It only runs when you press the button, and each press uses one request from your RentCast plan's monthly allowance.
Get a key from your RentCast account (its free plan includes a small monthly allowance). The key is stored in the
macOS Keychain with your other credentials, never in the database.</p>
{status}
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/rentcast-key', {{api_key: this.api_key.value}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>RentCast API key<input name="api_key" type="password" autocomplete="off" style="width:280px" required></label>
  <button type="submit" class="primary">Save key</button>
</form>
</div>
"""


def _plaid_credentials_profile_html(*, profile: str, presence) -> str:
    """One profile's (Primary/Secondary) client ID + per-environment
    secret status and save form, for the Plaid API keys card. presence
    is a source.common.secrets_store.ProfilePresence -- never carries
    actual secret values, just which fields are saved."""
    label = secrets_store.PROFILE_LABELS.get(profile, profile)
    return f"""
<div class="card">
<h3 style="margin-top:0; font-size:14px;">{html.escape(label)}</h3>
<p class="status-line {'status-ok' if presence.has_client_id else 'status-warn'}">
  Client ID: {'saved' if presence.has_client_id else 'not saved'}.
  Secrets saved for: {html.escape(', '.join(presence.secret_envs)) if presence.secret_envs else 'none'}.
</p>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/plaid-credentials', {{client_id: this.client_id.value, secret: this.secret.value, environment: this.environment.value, profile: {profile!r}}})
    .then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Client ID<input name="client_id" style="width:220px"></label>
  <label>Secret<input name="secret" type="password" style="width:220px"></label>
  <label>Environment<select name="environment"><option value="sandbox">sandbox</option><option value="production">production</option></select></label>
  <button type="submit" class="primary">Save</button>
</form>
</div>
"""


def _restore_form_html(backups: list[dict], password_set: bool) -> str:
    """Go back to an earlier backup. Asks for the password (it replaces
    everything you have now) and saves the current data first."""
    if not backups:
        return ""
    options = "".join(
        f'<option value="{html.escape(b["filename"])}">{html.escape(b["modified_at"])} ({_format_bytes(b["size_bytes"])})</option>'
        for b in backups
    )
    password_field = ('<label>Your password<input name="password" type="password" required autocomplete="current-password"></label>'
                      if password_set else "")
    return f"""
<form class="inline" id="restore-backup" onsubmit="event.preventDefault();
  var f = this;
  if (!confirm('Replace everything you have now with the backup from ' + f.filename.options[f.filename.selectedIndex].text.split(' (')[0] + '? Your current data is saved first.')) return;
  var btn = f.querySelector('button'); btn.disabled = true; btn.textContent = 'Restoring...';
  postJSON('/api/backup-restore', {{filename: f.filename.value, password: f.password ? f.password.value : ''}})
    .then(function(r) {{ alert('Restored. Your previous data was saved as ' + r.safety_copy + '.'); location.href = '/'; }})
    .catch(function(e) {{ alert(e.message); btn.disabled = false; btn.textContent = 'Restore this backup'; }});">
  <h3 style="font-size:13px; margin:12px 0 4px; flex-basis:100%;">Restore a backup</h3>
  <label>Backup<select name="filename">{options}</select></label>
  {password_field}
  <button type="submit">Restore this backup</button>
</form>
<p class="muted" style="font-size:12px">Replaces your current data with the chosen backup. A copy of what you have now is saved first (look for "pre-restore" in the list), so you can undo a restore the same way.</p>
"""


def _security_card_html(*, password_set: bool) -> str:
    """Set/change the login password (source.common.auth_store) that
    gates every page and API route once it exists -- see
    source.webapp.dashboard.Handler. No card at all until a password is
    set would mean a first-time visitor to a Tailscale Funnel URL sees
    an unprotected dashboard; this card is how the very first password
    gets set, from the one place that's reachable before login exists
    (127.0.0.1, or a not-yet-gated network bind)."""
    if password_set:
        status = '<p class="status-line status-ok">Password protection is on -- every page and the "+ Add"/edit endpoints all require it.</p>'
        heading = "Change password"
        submit_label = "Change password"
    else:
        status = '<p class="status-line status-warn">No password set yet -- anyone who can reach this dashboard (see Network access below) can see and edit everything.</p>'
        heading = "Set a password"
        submit_label = "Set password"
    return f"""
<div class="card">
<h2 style="margin-top:0">Security</h2>
{status}
<h3 style="font-size:13px; margin-bottom:4px;">{heading}</h3>
<form class="inline" onsubmit="event.preventDefault();
  if (this.new_password.value !== this.confirm.value) {{ alert('Passwords do not match.'); return; }}
  postJSON('/api/set-password', {{password: this.new_password.value, confirm: this.confirm.value}})
    .then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>New password (8+ characters)<input name="new_password" type="password" required minlength="8"></label>
  <label>Confirm<input name="confirm" type="password" required minlength="8"></label>
  <button type="submit" class="primary">{submit_label}</button>
</form>
<p class="muted">Changing the password logs out every other browser/device currently signed in -- useful if a session cookie ever ends up somewhere it shouldn't.</p>
{_recovery_key_html(password_set)}
{_viewer_login_html(password_set)}
</div>
"""


def _recovery_key_html(password_set: bool) -> str:
    """The way back in if the password is forgotten: a one-time key, shown
    once, kept only as a hash."""
    if not password_set:
        return ""
    has_key = auth_store.has_recovery_key()
    status = ('<p class="status-line status-ok">A recovery key is saved. Keep your copy somewhere safe; it is the only way back in if you forget your password.</p>'
              if has_key else '<p class="status-line status-warn">You have no recovery key yet. Make one now so a forgotten password is not the end of your access.</p>')
    return f"""
<h3 style="font-size:13px; margin:16px 0 4px;" id="recovery-key">Recovery key</h3>
{status}
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/recovery-key', {{password: this.current.value}})
    .then(function(d) {{ document.getElementById('rk-new').style.display = 'block'; document.getElementById('rk-value').textContent = d.recovery_key; }})
    .catch(function(e) {{ alert(e.message); }});">
  <label>Your password<input name="current" type="password" required autocomplete="current-password"></label>
  <button type="submit" class="primary">{'Make a new recovery key' if has_key else 'Make a recovery key'}</button>
</form>
<div id="rk-new" style="display:none; margin-top:8px;">
  <p>Write this down or store it in a password manager. It is shown only now, and any older key stops working.</p>
  <p style="font-size:18px; letter-spacing:1px;"><code id="rk-value"></code></p>
</div>
"""


def _viewer_login_html(password_set: bool) -> str:
    """A second, view-only password -- someone who signs in with it can look at
    everything and try what-ifs, but cannot change or save anything."""
    if not password_set:
        return ('<h3 style="font-size:13px; margin:16px 0 4px;">View-only login</h3>'
                '<p class="muted">Set your own password above first. Then you can add a second, view-only password '
                'for a spouse, advisor or accountant.</p>')
    on = auth_store.is_viewer_password_set()
    status = ('<p class="status-line status-ok">A view-only password is set. Anyone who signs in with it can look but not change anything.</p>'
              if on else '<p class="muted">Give a spouse, advisor or accountant a password that lets them look at everything but change nothing. '
              'They sign in on the same login page with this password instead of yours.</p>')
    remove = ('<button type="button" onclick="postJSON(\'/api/viewer-password\', {{remove: true}}).then(function() {{ location.reload(); }})'
              '.catch(function(e) {{ alert(e.message); }});">Remove it</button>') if on else ""
    return f"""
<h3 style="font-size:13px; margin:16px 0 4px;" id="viewer-login">View-only login</h3>
{status}
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/viewer-password', {{password: this.viewer_password.value}})
    .then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>{'New view-only password' if on else 'View-only password'} (8+ characters, different from yours)<input name="viewer_password" type="password" required minlength="8" autocomplete="new-password"></label>
  <button type="submit" class="primary">{'Change' if on else 'Set view-only password'}</button>
  {remove}
</form>
"""


def _network_access_card_html(*, bind_host: str, password_set: bool) -> str:
    """Which network interface(s) the dashboard's HTTP server listens on
    (source.webapp.dashboard.run, read from app_settings.get_bind_host)
    -- 127.0.0.1 (this Mac only, the original/default behavior) or
    0.0.0.0 (every interface, so a home Wi-Fi address or a Tailscale
    Funnel can reach it too). Takes effect on the NEXT restart, not
    live -- the HTTP server is already bound by the time this page can
    render."""
    is_local_only = bind_host == "127.0.0.1"
    status = (
        '<p class="status-line status-ok">Currently: this Mac only (127.0.0.1) -- nothing else on your network can reach this dashboard.</p>'
        if is_local_only else
        f'<p class="status-line status-warn">Currently: every network interface ({html.escape(bind_host)}) -- reachable from your home Wi-Fi, and from anywhere if you set up a Tailscale Funnel below.</p>'
    )
    guard_note = (
        "" if password_set else
        '<p class="muted">A password (Security card above) is required before this takes effect -- without one, the app starts on 127.0.0.1 regardless of this setting, to avoid ever exposing your data unprotected.</p>'
    )
    return f"""
<div class="card">
<h2 style="margin-top:0">Network access &amp; your iPhone</h2>
<p class="muted">By default this dashboard only listens on this Mac (127.0.0.1) -- nothing else on your network, let alone the internet, can reach it. To open it on your iPhone (on the same Wi-Fi, or from anywhere via Tailscale below), it needs to listen more broadly instead. Takes effect the next time you restart this app.</p>
{status}
{guard_note}
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/set-bind-host', {{bind_host: this.bind_host.value}})
    .then(function() {{ alert('Saved -- restart the app for this to take effect.'); location.reload(); }})
    .catch(function(e) {{ alert(e.message); }});">
  <label>Listen on<select name="bind_host">
    <option value="127.0.0.1"{' selected' if is_local_only else ''}>This Mac only (127.0.0.1)</option>
    <option value="0.0.0.0"{' selected' if not is_local_only else ''}>Every network interface (0.0.0.0)</option>
  </select></label>
  <button type="submit" class="primary">Save</button>
</form>
<h3 style="font-size:13px;">On the same Wi-Fi as this Mac</h3>
<p class="muted">Set "Listen on" to every interface above, restart the app, then find this Mac's local IP (System Settings -&gt; Wi-Fi -&gt; Details, or <code>ipconfig getifaddr en0</code> in Terminal) and open <code>http://&lt;that IP&gt;:{config.DASHBOARD_PORT}/</code> in Safari on your iPhone. Tap the Share icon, then "Add to Home Screen" for a full-screen app icon.</p>
<h3 style="font-size:13px;">From anywhere (cellular, away from home) -- Tailscale Funnel</h3>
<p class="muted">
Tailscale is a free (for personal use) VPN service; its Funnel feature gives one specific local port a public <code>https://&lt;name&gt;.ts.net</code> address with a real TLS certificate, without opening any port on your router. One-time setup, all in your Mac's Terminal:
</p>
<ol class="muted" style="padding-left:18px;">
<li>Install: <code>brew install tailscale</code> (or download from tailscale.com), then <code>sudo tailscale up</code> and sign in once in the browser tab it opens.</li>
<li>Set a password above first (required), and set "Listen on" to every interface, then restart this app.</li>
<li>Run <code>tailscale funnel {config.DASHBOARD_PORT}</code> and leave it running -- it prints the <code>https://&lt;name&gt;.ts.net</code> address to use, including from your iPhone on cellular data.</li>
</ol>
<p class="muted">The password above is what actually protects your data once it's reachable this way -- Funnel itself just forwards HTTPS traffic to this dashboard, it doesn't check who's asking.</p>
</div>
"""

_RULE_TYPE_LABELS = {"primary": "Plaid category", "detailed": "Plaid subcategory", "keyword": "Merchant/name keyword"}
_MATCH_MODE_LABELS = {
    "contains": "Contains", "starts_with": "Starts with", "ends_with": "Ends with", "regex": "Regex (advanced)",
    "exact": "Exact match",
}
_KIND_LABELS = {"": "Auto-detect", "income": "Income", "expense": "Expense"}


def _category_rules_card_html(*, rules: list[dict], category_options_html: str) -> str:
    """Setup page card for source.common.db.category_rules -- lets a
    person add, edit in place, or delete an override on top of the
    broad-category rollup rules source.common.plaid_categorize.
    default_category otherwise hardcodes, without this program's own
    code ever changing. Saving (new or edited) or deleting a rule
    immediately re-runs recategorize_all_transactions() server-side (see
    dashboard.py's /api/category-rule/save|update|delete) so the Real
    Expenditure tab reflects it right away for every transaction that
    hasn't been manually re-labeled by hand.

    A 'keyword' rule (matched against a transaction's own merchant/name
    text) can use any of plaid_categorize.KEYWORD_MATCH_MODES -- plain
    substring "Contains" (the original, and still the default,
    behavior), "Starts with"/"Ends with" anchored to one end, or an
    advanced "Regex" pattern for anything those three can't express.
    Meaningless for a 'primary'/'detailed' rule (always an exact match
    on Plaid's own value), so the Match mode cell there is disabled.

    Every existing rule's own row IS the edit form -- its fields start
    populated with that rule's current values; retype any of them
    (including Value/Match on, unlike the old add-only behavior) and hit
    "Save" to update that same rule in place via updateCategoryRule() in
    shell.py, which posts straight to /api/category-rule/update rather
    than adding a second rule.

    Kind (Auto-detect/Income/Expense) is this rule's own opinion on
    whether everything it matches is real income or a real expense on
    the Actual Spending/Budget vs Actual pages (plaid_categorize.
    is_real_income's own income_kind_override) -- saving it alone does
    NOT touch any transaction (same as Save never force-overwrites a
    hand-edited category); the card's single "Apply all rules" button does, via
    applyAllCategoryRules() in shell.py, posting to /api/category-rule/
    apply-all -- see source.common.db.transactions.apply_all_category_rules
    (and apply_category_rule, which it loops over) for exactly why this
    needs to be a separate, explicit action rather than automatic on every
    save."""
    def _rule_type_select(r) -> str:
        options = "".join(
            f'<option value="{rt}"{" selected" if rt == r.get("rule_type") else ""}>'
            f'{html.escape(_RULE_TYPE_LABELS[rt])}</option>'
            for rt in plaid_categorize.RULE_TYPES
        )
        return f'<select name="rule_type" onchange="toggleCategoryRuleMatchMode(this)">{options}</select>'

    def _match_mode_select(r) -> str:
        current = r.get("match_mode") or "contains"
        disabled = r.get("rule_type") != "keyword"
        options = "".join(
            f'<option value="{m}"{" selected" if m == current else ""}>{html.escape(_MATCH_MODE_LABELS[m])}</option>'
            for m in plaid_categorize.KEYWORD_MATCH_MODES
        )
        return f'<select name="match_mode"{" disabled" if disabled else ""} style="width:115px;">{options}</select>'

    def _kind_select(r) -> str:
        current = r.get("kind") or ""
        options = "".join(
            f'<option value="{k}"{" selected" if k == current else ""}>{html.escape(label)}</option>'
            for k, label in _KIND_LABELS.items()
        )
        return f'<select name="kind" style="width:95px;">{options}</select>'

    def rule_row(r):
        return (
            f'<tr>'
            f'<td>{_rule_type_select(r)}</td>'
            f'<td><input type="text" name="match_key" value="{html.escape(r["match_key"])}" style="width:140px;"></td>'
            f'<td>{_match_mode_select(r)}</td>'
            f'<td><input type="text" name="category" list="category-rule-categories" '
            f'value="{html.escape(r["category"])}" style="width:115px;"></td>'
            f'<td>{_kind_select(r)}</td>'
            f'<td><span class="rule-actions">'
            f'<button onclick="updateCategoryRule({r["id"]}, this.closest(\'tr\'))">Save</button>'
            f'<button class="danger" onclick="deleteCategoryRule({r["id"]})">Delete</button>'
            f'</span></td>'
            f'</tr>'
        )

    rule_rows_html = "".join(rule_row(r) for r in rules) or (
        '<tr><td colspan="6" class="muted">No custom rules yet -- every transaction uses this program\'s built-in defaults below.</td></tr>'
    )

    def builtin_row(r):
        return (
            f'<tr><td>{html.escape(_RULE_TYPE_LABELS.get(r["rule_type"], r["rule_type"]))}</td>'
            f'<td><code>{html.escape(r["match_key"])}</code></td>'
            f'<td>{html.escape(_MATCH_MODE_LABELS.get(r["match_mode"], r["match_mode"]))}</td>'
            f'<td>{html.escape(r["category"])}</td></tr>'
        )

    builtin_rows_html = "".join(builtin_row(r) for r in plaid_categorize.list_built_in_rules())

    new_match_mode_select = _match_mode_select({"rule_type": "keyword", "match_mode": "contains"})

    new_kind_select = _kind_select({"kind": ""})

    return f"""
<div class="card">
<h2 style="margin-top:0">Category rules</h2>
<p class="muted">Every synced transaction's starting Category (on the <a href="/real-expenditure.html">Actual Spending</a> tab) comes from Plaid's own classification, rolled up into a short list of broad buckets by this program's built-in rules (see the reference table below). A rule you add here always wins over the matching built-in one, and applies immediately to every transaction that hasn't been individually re-typed by hand (a category set via Actual Spending's own bulk bar is never overwritten by either). This is separate from that per-transaction bulk-classify bar -- these rules change the *default*, going forward and retroactively, rather than one transaction at a time. A "Merchant/name keyword" rule's Match mode picks how its Value is compared against the transaction's own merchant/description text: Contains (a plain substring, the original behavior), Starts with, Ends with, or an advanced Regex pattern. Kind is this rule's own say on whether everything it matches counts as real income or a real expense on Actual Spending/Budget vs Actual (leave it "Auto-detect" to let the usual heuristic decide) -- saving a rule alone never overwrites a transaction you've already categorized by hand; click <strong>Apply all rules</strong> (above the table) to force every saved rule (category AND kind) onto all matching transactions at once, hand-edited ones included. Save any edited rows first -- only saved rules are applied.</p>
<datalist id="category-rule-categories">{category_options_html}</datalist>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/category-rule/save', {{
    rule_type: this.rule_type.value, match_key: this.match_key.value,
    match_mode: this.match_mode.value, category: this.category.value, kind: this.kind.value,
  }}).then(function(d) {{ alert(d.recategorized + ' existing transaction' + (d.recategorized === 1 ? '' : 's') +
    ' auto-recategorized (hand-edited ones were left alone -- use the Apply all rules button for those).');
    location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Match on<select name="rule_type" onchange="toggleCategoryRuleMatchMode(this)">
    <option value="primary">Plaid category (e.g. GENERAL_MERCHANDISE)</option>
    <option value="detailed">Plaid subcategory (e.g. GENERAL_MERCHANDISE_PET_SUPPLIES)</option>
    <option value="keyword" selected>Merchant/name keyword (e.g. peloton)</option>
  </select></label>
  <label>Value<input name="match_key" placeholder="e.g. peloton" required></label>
  <label>Match mode{new_match_mode_select}</label>
  <label>Category<input name="category" list="category-rule-categories" placeholder="e.g. Fitness" required></label>
  <label>Kind{new_kind_select}</label>
  <button type="submit" class="primary">Add rule</button>
</form>
<div class="rules-apply-bar" style="display:flex; justify-content:flex-end; margin:8px 0;">
  <button type="button" class="primary" onclick="applyAllCategoryRules()" title="Re-apply every saved rule to all matching transactions, including ones already categorized by hand">Apply all rules</button>
</div>
<table class="sortable">
<thead><tr><th>Matches on</th><th>Value</th><th>Match mode</th><th>Category</th><th>Kind</th><th></th></tr></thead>
<tbody>{rule_rows_html}</tbody>
</table>
<details style="margin-top:8px;">
<summary class="muted" style="cursor:pointer;">Built-in defaults (read-only reference, {len(plaid_categorize.list_built_in_rules())} rules)</summary>
<table class="sortable">
<thead><tr><th>Matches on</th><th>Value</th><th>Match mode</th><th>Category</th></tr></thead>
<tbody>{builtin_rows_html}</tbody>
</table>
</details>
</div>
"""


def _live_limits_card_html() -> str:
    """Setup page card for the real-money trading limits. One setting for every broker (Alpaca, IBKR, E*TRADE): the same
    daily total is shared by all of them. Either limit can be switched off."""
    lt = db.live_trading
    per, daily = lt.per_order_limit(), lt.daily_limit()
    spent = lt.spent_today()

    def box(name: str, value: float, label: str) -> str:
        none = not lt.is_limited(value)
        shown = "" if none else f"{value:.0f}"
        return (f'<label>{label} ($)<input name="{name}" type="number" min="1" step="1" value="{shown}" style="width:130px"'
                f'{" disabled" if none else ""}></label>'
                f'<label style="flex-direction:row; align-items:center; gap:6px;"><input type="checkbox" name="{name}_none" style="width:auto"'
                f'{" checked" if none else ""} onchange="this.form.{name}.disabled = this.checked;"> No limit</label>')

    return f"""
<div class="card" id="live-limits">
<h2 style="margin-top:0">Real-money trading limits</h2>
<p class="muted">These apply to every real-money order sent from this app, on <strong>Alpaca, IBKR and E*TRADE together</strong>: the most one order
may be worth, and the most that may be sent in a day (the daily total adds up all three). Turn a box to <em>No limit</em> to remove that limit.
Sent today: <strong>${spent:,.2f}</strong>. Every order still needs a preview, retyping the symbol, and live trading switched on, and is written to the audit log.</p>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/alpaca/live/limits', {{per_order: this.per_order_none.checked ? null : this.per_order.value, daily: this.daily_none.checked ? null : this.daily.value}})
    .then(function() {{ location.reload(); }})
    .catch(function(e) {{ alert(e.message); }});">
  {box("per_order", per, "Most per order")}
  {box("daily", daily, "Most per day")}
  <button type="submit" class="primary">Save limits</button>
</form>
</div>
"""


def _auto_sync_card_html() -> str:
    """Setup page card for source.collector.auto_sync -- see that
    module's own docstring for exactly when it fires and its real
    limitation (only checked at app-open time, not a true background
    schedule)."""
    enabled = app_settings.get_auto_sync_enabled()
    interval_days = app_settings.get_auto_sync_interval_days()
    age = auto_sync.days_since_last_sync()
    if not db.list_plaid_items():
        status = '<p class="status-line muted">No Plaid accounts linked yet -- nothing for this to sync.</p>'
    elif age is None:
        status = '<p class="status-line status-warn">Never synced yet -- the next time you open this app, it will sync automatically (if enabled below).</p>'
    elif not enabled:
        status = f'<p class="status-line muted">Off -- last synced {age:.0f} day{"s" if age != 1 else ""} ago. Turn this on to catch up automatically instead of remembering to click "Sync now".</p>'
    elif age >= interval_days:
        status = f'<p class="status-line status-warn">Overdue -- last synced {age:.0f} days ago (every {interval_days}). Will sync automatically the next time you open this app.</p>'
    else:
        status = f'<p class="status-line status-ok">Up to date -- last synced {age:.0f} day{"s" if age != 1 else ""} ago, next automatic sync in {interval_days - age:.0f} day{"s" if interval_days - age != 1 else ""}.</p>'

    return f"""
<div class="card">
<h2 style="margin-top:0">Automatic sync</h2>
<p class="muted">When enabled, this program checks once every time it's opened whether it's been at least this many days since your accounts were last synced -- if so, it syncs automatically in the background, the same as clicking "Sync now" yourself. This only ever runs at a moment you've actually opened the app; it can't wake itself up on a day you never do (that needs a real OS-level scheduled task -- see <code>scripts/install_launchd_auto_sync.sh</code> if you want that instead of or in addition to this).</p>
{status}
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/auto-sync-settings', {{enabled: this.enabled.checked, interval_days: this.interval_days.value}})
    .then(function() {{ location.reload(); }})
    .catch(function(e) {{ alert(e.message); }});">
  <label style="flex-direction: row; align-items: center; gap: 6px;"><input type="checkbox" name="enabled" style="width:auto;"{' checked' if enabled else ''}> Enabled</label>
  <label>Every<input name="interval_days" type="number" min="1" value="{interval_days}" style="width:70px;"> days</label>
  <button type="submit" class="primary">Save</button>
</form>
</div>
"""


def _format_bytes(size: int) -> str:
    """A backup's file size for the Setup page's Backups card --
    KB/MB, not a raw byte count nobody reads at a glance."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
