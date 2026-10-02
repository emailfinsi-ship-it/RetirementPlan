"""The login page -- shown instead of any other tab whenever a login
password has been set (source.common.auth_store) and the request has no
valid session cookie yet. Deliberately does NOT use the normal _shell()
page chrome (no nav bar, no "+ Add" button, none of the other tabs'
data) -- there's nothing on this page but the password form, and
nothing here should render before a session is verified.
"""

from __future__ import annotations

import html

from source.webapp.render_helpers.styles import PAGE_CSS


def _render_login_page(*, error: str | None = None, first_time: bool = False) -> str:
    error_html = f'<p class="status-line status-err">{html.escape(error)}</p>' if error else ""
    if first_time:
        heading = "Set a login password"
        intro = (
            "This dashboard is about to be reachable outside this Mac, so it needs a password first -- "
            "anyone with the link would otherwise see your full financial picture. Pick something you "
            "can remember (at least 8 characters); there's no username, just this one password."
        )
        submit_label = "Set password &amp; continue"
        endpoint = "/api/set-password"
        extra_field = ""
    else:
        heading = "Retirement Plan"
        intro = "Enter your password to continue."
        submit_label = "Log in"
        endpoint = "/api/login"
        extra_field = ""
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Retirement Plan -- Log in</title>
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/icons/icon-180.png">
<meta name="theme-color" content="#0071e3">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Retirement Plan">
<style>{PAGE_CSS}
  body {{ max-width: 380px; padding-top: 18vh; }}
  .login-card {{ text-align: left; }}
  .login-card input[type=password] {{ width: 100%; font-size: 16px; padding: 10px 12px; margin-top: 10px; }}
  .login-card button {{ width: 100%; margin-top: 14px; padding: 10px; font-size: 14px; }}
</style>
</head>
<body>
<h1 style="text-align:center;">Retirement Plan</h1>
<div class="card login-card">
<h2 style="margin-top:0">{heading}</h2>
<p class="muted">{intro}</p>
{error_html}
<form onsubmit="event.preventDefault();
  var btn = this.querySelector('button');
  btn.disabled = true;
  fetch('{endpoint}', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{password: this.password.value{', confirm: this.confirm.value' if first_time else ''}}})}})
    .then(function(resp) {{ return resp.json().then(function(d) {{ if (!resp.ok || !d.ok) throw new Error(d.error || 'Failed'); return d; }}); }})
    .then(function() {{ location.href = '/'; }})
    .catch(function(e) {{ btn.disabled = false; alert(e.message); }});">
  {extra_field}
  <label>Password<input type="password" name="password" autofocus required></label>
  {'<label>Confirm password<input type="password" name="confirm" required></label>' if first_time else ''}
  <button type="submit" class="primary">{submit_label}</button>
</form>
</div>
</body>
</html>
"""
