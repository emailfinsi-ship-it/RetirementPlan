"""Privacy and Terms, in plain words, served at /legal.html (no login needed,
so people can read them before they set up). The privacy section describes
what this app really does; keep it in step with the code. Have a lawyer
review the final wording before you distribute the app (see PRODUCTION.md)."""

from __future__ import annotations

import html

from source.common import branding

from source.webapp.render_helpers.shell import DISCLAIMER_TEXT
from source.webapp.render_helpers.styles import PAGE_CSS, THEME_INIT_SCRIPT


def _contact() -> str:
    if branding.SUPPORT_EMAIL:
        return f'Questions? Write to <a href="mailto:{html.escape(branding.SUPPORT_EMAIL)}">{html.escape(branding.SUPPORT_EMAIL)}</a>.'
    return "Questions? Contact the person or company that gave you this app."


def _render_legal_page() -> str:
    name = html.escape(branding.PRODUCT_NAME)
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{name} -- Privacy and terms</title>
<link rel="icon" type="image/svg+xml" href="/icons/logo.svg">
<style>{PAGE_CSS}
  body {{ max-width: 720px; padding-top: 5vh; }}
  h2 {{ margin-top: 26px; }}
</style>
{THEME_INIT_SCRIPT}
</head>
<body>
<div style="text-align:center; margin-bottom:12px;">
<img src="/icons/logo.svg" alt="{name} logo" width="64" height="64" style="border-radius:14px;">
<h1 style="margin:6px 0 0;">{name}</h1>
<p class="muted" style="margin:0">Privacy and terms &middot; version {html.escape(branding.APP_VERSION)}</p>
</div>

<div class="card" id="privacy">
<h2 style="margin-top:0">Privacy: your numbers stay with you</h2>
<ul>
<li><strong>Your data lives on your computer.</strong> Everything you enter or link is saved in a database file on this computer (and its backups). {name} has no accounts, no servers of its own, and does not collect or sell your information.</li>
<li><strong>No tracking.</strong> There are no analytics, ads or hidden reports. A support report is made only if you press the button, and you choose whether to send it. It leaves out balances, names and passwords.</li>
<li><strong>Your password.</strong> It is stored only as a one-way scramble (hash) in your Mac's Keychain. So is your recovery key. We cannot read or reset either one.</li>
<li><strong>Bank connections.</strong> If you connect accounts, you do it through Plaid, using your own Plaid keys. Plaid, your bank and you decide what is shared; read Plaid's own privacy policy. Your Plaid keys are kept in your Keychain.</li>
<li><strong>Other things the app may contact, only if you use them:</strong> your own email server for the weekly summary email; the property-value service (RentCast) with your own key; a public market-data service to look up the industry of the stocks you hold (it sees ticker symbols, not amounts); and an update address if you set one up and press "Check for updates".</li>
<li><strong>Sharing.</strong> The app listens only on this computer unless you change Network access, and then it needs your password. A view-only password lets someone look but not change anything.</li>
<li><strong>Deleting your data.</strong> Quit the app and delete its data folder (shown in Setup). Remove the saved items from Keychain Access if you want them gone too.</li>
</ul>
</div>

<div class="card" id="terms">
<h2 style="margin-top:0">Terms of use</h2>
<ul>
<li><strong>A planning tool, not advice.</strong> {html.escape(DISCLAIMER_TEXT)}</li>
<li><strong>Estimates only.</strong> Results come from the numbers you enter and from simulated markets. The future will differ. Past returns do not predict future returns.</li>
<li><strong>You are responsible for your inputs and decisions.</strong> Check important figures against your own statements. Do not rely on this app alone for tax, legal or investment choices.</li>
<li><strong>It never moves money.</strong> {name} cannot buy, sell or transfer anything.</li>
<li><strong>Keep your password and recovery key safe.</strong> If both are lost, nobody can recover access to the app. Your data file and backups stay on your computer.</li>
<li><strong>No warranty.</strong> The app is provided "as is". To the extent the law allows, the publisher is not liable for losses that come from using it.</li>
</ul>
<p class="muted">{_contact()}</p>
</div>
<p style="text-align:center"><a href="/">Back to the app</a></p>
</body>
</html>
"""
