"""Forgot-password page: sets a new password using the recovery key that was
shown at first launch. Like the login page it has no menu and no data."""

from __future__ import annotations

from source.common import branding

from source.webapp.render_helpers.shell import _disclaimer_html
from source.webapp.render_helpers.styles import PAGE_CSS, THEME_INIT_SCRIPT


def _render_forgot_page() -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{branding.PRODUCT_NAME} -- Reset password</title>
<link rel="icon" type="image/svg+xml" href="/icons/logo.svg">
<style>{PAGE_CSS}
  body {{ max-width: 420px; padding-top: 12vh; }}
  .fg-card label {{ display: block; margin-top: 10px; font-size: 13px; }}
  .fg-card input {{ width: 100%; font-size: 16px; padding: 10px 12px; margin-top: 4px; box-sizing: border-box; }}
  .fg-card button[type=submit] {{ width: 100%; margin-top: 14px; padding: 10px; font-size: 14px; }}
</style>
{THEME_INIT_SCRIPT}
</head>
<body>
<div style="text-align:center; padding-bottom:14px; border-bottom:1px solid var(--border, #e5e5ea); margin-bottom:16px;">
<img src="/icons/logo.svg" alt="{branding.PRODUCT_NAME} logo" width="76" height="76" style="border-radius:17px;">
<h1 style="margin:8px 0 2px;">{branding.PRODUCT_NAME}</h1>
<p class="brand-tagline" style="margin:0; font-size:14px;">{branding.PRODUCT_TAGLINE}</p>
</div>
<div class="card fg-card" id="forgot">
<h2 style="margin-top:0">Reset your password</h2>
<p class="muted">Type the recovery key you saved when you first set up. You will get a new recovery key afterwards.</p>
<form id="fg-form" onsubmit="event.preventDefault();
  var f = this, btn = f.querySelector('button[type=submit]'), msg = document.getElementById('fg-msg');
  msg.textContent = ''; btn.disabled = true;
  fetch('/api/reset-password', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{recovery_key: f.recovery_key.value, password: f.password.value, confirm: f.confirm.value}})}})
    .then(function(r) {{ return r.json().then(function(d) {{ if (!r.ok || !d.ok) throw new Error(d.error || 'Failed'); return d; }}); }})
    .then(function(d) {{ f.style.display = 'none'; document.getElementById('fg-done').style.display = 'block'; document.getElementById('fg-key').textContent = d.recovery_key; }})
    .catch(function(e) {{ btn.disabled = false; msg.textContent = e.message; }});">
  <label>Recovery key<input name="recovery_key" placeholder="XXXX-XXXX-XXXX-XXXX-XXXX" autocomplete="off" required></label>
  <label>New password (8+ characters)<input name="password" type="password" minlength="8" required autocomplete="new-password"></label>
  <label>Type it again<input name="confirm" type="password" minlength="8" required autocomplete="new-password"></label>
  <p id="fg-msg" class="status-line status-err" role="alert"></p>
  <button type="submit" class="primary">Reset password</button>
</form>
<div id="fg-done" style="display:none">
  <p><strong>Your password is changed.</strong> Here is your new recovery key. Save it now; it is shown only once.</p>
  <p style="font-size:18px; letter-spacing:1px;"><code id="fg-key"></code></p>
  <p><a href="/"><button type="button" class="primary" style="width:100%">Continue</button></a></p>
</div>
<p style="margin-top:14px"><a href="/login.html">Back to log in</a></p>
</div>
{_disclaimer_html()}
</body>
</html>
"""
