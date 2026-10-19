"""Setup tab card for alerts: the weekly e-mail digest (your own e-mail
account) and Mac notifications. The e-mail password is stored in the
Keychain, never shown again after saving."""

from __future__ import annotations

import html

from source.common import secrets_store
from source.reporting import alerts


def alerts_settings_card_html() -> str:
    cfg = alerts.settings()
    e = lambda k: html.escape(str(cfg[k]))  # noqa: E731
    pw_note = "A password is saved." if secrets_store.has_smtp_password() else "No password saved yet."
    chk = lambda k: " checked" if cfg[k] else ""  # noqa: E731
    return f"""
<details class="card" id="alerts-card" style="padding:12px 16px; margin:16px 0;">
<summary style="font-weight:650; font-size:15px; cursor:pointer;">Alerts &amp; weekly email <span class="muted">(get told when something needs a look)</span></summary>
<p class="muted">The bell at the top of every page and the Alerts card on the Summary are always on. Here you can also get a short
weekly email and a Mac notification. Nothing leaves your computer except the email you set up here, sent through your own email account.</p>
<form id="alerts-form" onsubmit="event.preventDefault(); var f = this;
  postJSON('/api/alert-settings', {{
    email_to: f.email_to.value, smtp_host: f.smtp_host.value, smtp_port: f.smtp_port.value, smtp_user: f.smtp_user.value,
    smtp_from: f.smtp_from.value, smtp_password: f.smtp_password.value, digest: f.digest.checked, mac_notify: f.mac_notify.checked
  }}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label style="display:block;margin:6px 0"><input type="checkbox" name="digest"{chk("digest")}> Send me a weekly email</label>
  <label style="display:block;margin:6px 0"><input type="checkbox" name="mac_notify"{chk("mac_notify")}> Show a Mac notification when a new alert appears</label>
  <div class="field-grid">
    <label>Send to (your email)<input name="email_to" type="email" value="{e("email_to")}" placeholder="you@example.com"></label>
    <label>Email server<input name="smtp_host" value="{e("smtp_host")}" placeholder="smtp.gmail.com"></label>
    <label>Port<input name="smtp_port" type="number" value="{e("smtp_port")}" style="width:90px"></label>
    <label>Login (usually your email)<input name="smtp_user" value="{e("smtp_user")}" autocomplete="off"></label>
    <label>Password or app password<input name="smtp_password" type="password" autocomplete="new-password" placeholder="{pw_note}"></label>
    <label>Send from (optional)<input name="smtp_from" value="{e("smtp_from")}" placeholder="same as login"></label>
  </div>
  <p class="small muted">Gmail and iCloud need an <em>app password</em> (made in your account's security settings), not your normal password.</p>
  <button type="submit" class="primary">Save</button>
  <button type="button" onclick="var b = this; b.disabled = true; postJSON('/api/alert-test-email', {{}}).then(function() {{ b.disabled = false; document.getElementById('alert-test-result').textContent = 'Sent. Check your inbox.'; }}).catch(function(e) {{ b.disabled = false; document.getElementById('alert-test-result').textContent = e.message; }});">Send test email</button>
  <span id="alert-test-result" class="small muted"></span>
</form>
</details>
"""
