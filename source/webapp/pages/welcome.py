"""The very first screen, shown once on a brand-new install (Mac app or
from-source): create the admin password and set up the database.

Like the login page it skips the normal page chrome -- nothing else may show
until this is done. The logo, name and tagline sit at the top.
"""

from __future__ import annotations

import html

from source.common import branding, config, first_run

from source.webapp.render_helpers.shell import _disclaimer_html
from source.webapp.render_helpers.styles import PAGE_CSS, THEME_INIT_SCRIPT


def _render_welcome_page(*, error: str | None = None) -> str:
    error_html = f'<p class="status-line status-err">{html.escape(error)}</p>' if error else ""
    folder = html.escape(str(config.DATA_DIR))
    if first_run.existing_database():
        db_block = (
            f'<p>We found your existing database in <code>{folder}</code>. It will be kept exactly as it is.</p>'
        )
    else:
        db_block = (
            f'<p>Your numbers are saved in a private database file on this computer. '
            f'It will be created in <code>{folder}</code>.</p>'
            '<details><summary>Keep it somewhere else</summary>'
            f'<label>Folder for the database<input id="fr-folder" value="{folder}" autocomplete="off"></label>'
            '<p class="muted" style="font-size:12px">Type the full folder path. Most people leave this as it is.</p>'
            '</details>'
        )
    body_fields = "password: this.password.value, confirm: this.confirm.value"
    if not first_run.existing_database():
        body_fields += ", data_dir: document.getElementById('fr-folder').value"
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{branding.PRODUCT_NAME} -- Welcome</title>
<link rel="manifest" href="/manifest.json">
<link rel="icon" type="image/svg+xml" href="/icons/logo.svg">
<link rel="apple-touch-icon" href="/icons/icon-180.png">
<meta name="theme-color" content="#0071e3">
<style>{PAGE_CSS}
  body {{ max-width: 440px; padding-top: 8vh; }}
  .fr-card label {{ display: block; margin-top: 10px; font-size: 13px; }}
  .fr-card input {{ width: 100%; font-size: 16px; padding: 10px 12px; margin-top: 4px; box-sizing: border-box; }}
  .fr-card button[type=submit] {{ width: 100%; margin-top: 16px; padding: 11px; font-size: 14px; }}
  .fr-card p {{ font-size: 13px; }}
  .fr-step {{ font-weight: 600; margin: 18px 0 4px; }}
  .fr-card details {{ margin-top: 8px; }}
  .fr-card code {{ word-break: break-all; }}
</style>
{THEME_INIT_SCRIPT}
</head>
<body>
<div style="text-align:center; padding-bottom:14px; border-bottom:1px solid var(--border, #e5e5ea); margin-bottom:16px;">
<img id="fr-logo" src="/icons/logo.svg" alt="{branding.PRODUCT_NAME} logo" width="96" height="96" style="border-radius:21px;">
<h1 style="margin:8px 0 2px;">{branding.PRODUCT_NAME}</h1>
<p class="brand-tagline" style="margin:0; font-size:14px;">{branding.PRODUCT_TAGLINE}</p>
<p style="margin:14px 0 4px; font-weight:600;">{branding.PRODUCT_HEADLINE}</p>
<p class="muted" style="margin:0; font-size:13px;">{branding.PRODUCT_SUBLINE}</p>
</div>
<div class="card fr-card" id="first-run">
<h2 style="margin-top:0">Welcome! Let's set things up</h2>
<p class="muted">Two quick things before you start. This only happens once.</p>
{error_html}
<form id="fr-form" onsubmit="event.preventDefault();
  var btn = this.querySelector('button[type=submit]');
  var msg = document.getElementById('fr-msg');
  msg.textContent = '';
  btn.disabled = true;
  fetch('/api/first-run', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{{body_fields}}})}})
    .then(function(resp) {{ return resp.json().then(function(d) {{ if (!resp.ok || !d.ok) throw new Error(d.error || 'Failed'); return d; }}); }})
    .then(function(d) {{ document.getElementById('fr-form').style.display = 'none'; document.getElementById('fr-import').style.display = 'none'; document.getElementById('fr-key').textContent = d.recovery_key; document.getElementById('fr-done').style.display = 'block'; }})
    .catch(function(e) {{ btn.disabled = false; msg.textContent = e.message; }});">
  <div class="fr-step">1. Create your admin password</div>
  <p class="muted" style="margin:0">This protects your financial picture. Use at least 8 characters. There is no username. You will get a recovery key next, which is the way back in if you forget it.</p>
  <label>Password<input type="password" name="password" autofocus required minlength="8" autocomplete="new-password"></label>
  <label>Type it again<input type="password" name="confirm" required minlength="8" autocomplete="new-password"></label>
  <div class="fr-step">2. Set up your database</div>
  {db_block}
  <p id="fr-msg" class="status-line status-err" role="alert"></p>
  <button type="submit" class="primary">Create password &amp; set up database</button>
</form>
<details id="fr-import" style="margin-top:14px">
  <summary>Moving from another Mac?</summary>
  <p class="muted">Choose the transfer file you saved from the old Mac (Setup &rarr; Move to another Mac) and type its passphrase. Your password, bank connections and data come across, so you do not make a new password.</p>
  <form onsubmit="event.preventDefault();
    var f = this, btn = f.querySelector('button'), msg = document.getElementById('fr-import-msg');
    var file = f.transfer_file.files[0];
    if (!file) {{ msg.textContent = 'Choose the transfer file first.'; return; }}
    msg.textContent = ''; btn.disabled = true; btn.textContent = 'Importing...';
    var rd = new FileReader();
    rd.onload = function() {{
      var b64 = rd.result.split(',')[1] || '';
      fetch('/api/transfer-import', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{data_b64: b64, passphrase: f.passphrase.value}})}})
        .then(function(r) {{ return r.json().then(function(d) {{ if (!r.ok || !d.ok) throw new Error(d.error || 'Failed'); return d; }}); }})
        .then(function() {{ location.href = '/login.html'; }})
        .catch(function(e) {{ btn.disabled = false; btn.textContent = 'Import and continue'; msg.textContent = e.message; }});
    }};
    rd.readAsDataURL(file);">
    <label>Transfer file<input type="file" name="transfer_file" id="fr-transfer-file"></label>
    <label>Its passphrase<input type="password" name="passphrase" autocomplete="off"></label>
    <p id="fr-import-msg" class="status-line status-err" role="alert"></p>
    <button type="submit">Import and continue</button>
  </form>
</details>
<div id="fr-done" style="display:none">
  <h3 style="margin-top:0">All set. One last thing: save your recovery key</h3>
  <p>If you ever forget your password, this key is the only way back in. It is shown just this once, so write it down or save it in a password manager.</p>
  <p style="font-size:18px; letter-spacing:1px;"><code id="fr-key"></code></p>
  <p><button type="button" onclick="navigator.clipboard &amp;&amp; navigator.clipboard.writeText(document.getElementById('fr-key').textContent); this.textContent = 'Copied';">Copy key</button></p>
  <label style="display:flex; gap:8px; align-items:center; font-size:13px;"><input type="checkbox" id="fr-saved" style="width:auto; margin:0" onchange="document.getElementById('fr-go').disabled = !this.checked;"> I saved my recovery key</label>
  <button type="button" class="primary" id="fr-go" disabled style="width:100%; margin-top:12px; padding:11px;" onclick="location.href = '/'">Continue</button>
</div>
</div>
{_disclaimer_html()}
</body>
</html>
"""
