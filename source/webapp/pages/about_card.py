"""Setup tab card: version, how well your data is protected, a support report
you can download, and a "Check for updates" button."""

from __future__ import annotations

import html

from source.common import app_settings, branding, config, production


def about_card_html() -> str:
    fv = production.filevault_status()
    if fv is True:
        disk = '<p class="status-line status-ok">Disk encryption (FileVault) is on, so your data file is protected if the Mac is lost.</p>'
    elif fv is False:
        disk = ('<p class="status-line status-warn">Disk encryption (FileVault) is off. Anyone who gets your Mac could read your data file. '
                'Turn it on in System Settings &rarr; Privacy &amp; Security &rarr; FileVault.</p>')
    else:
        disk = '<p class="muted">Could not tell whether disk encryption is on. On a Mac, check System Settings &rarr; Privacy &amp; Security &rarr; FileVault.</p>'
    feed = html.escape(app_settings.get_update_feed_url())
    return f"""
<div class="card" id="about-card">
<h2 style="margin-top:0">About, protection and updates</h2>
<p>{html.escape(branding.PRODUCT_NAME)} version <strong>{html.escape(branding.APP_VERSION)}</strong>
 &middot; <a href="/legal.html">Privacy &amp; terms</a></p>
{disk}
<p class="muted">Your data folder ({html.escape(str(config.DATA_DIR))}) is readable only by your Mac user account.</p>
<p>
  <button type="button" class="primary" id="check-update-btn" onclick="var b = this; b.disabled = true;
    postJSON('/api/check-update', {{}}).then(function(r) {{ b.disabled = false; var el = document.getElementById('update-result'); el.textContent = r.message; if (r.update && r.url) {{ el.innerHTML += ' <a href=&quot;' + r.url + '&quot; target=&quot;_blank&quot; rel=&quot;noopener&quot;>Download</a>'; }} }}).catch(function(e) {{ b.disabled = false; alert(e.message); }});">Check for updates</button>
  <a href="/diagnostics.txt"><button type="button">Download support report</button></a>
  <span id="update-result" class="muted"></span>
</p>
<p class="muted" style="font-size:12px">The support report holds versions, sizes and recent log lines. It leaves out balances, names and passwords, and nothing is sent anywhere unless you attach it to a message yourself.</p>
<details><summary class="muted">Update address (for whoever publishes this app)</summary>
<form class="inline" onsubmit="event.preventDefault();
  postJSON('/api/update-feed', {{url: this.url.value}}).then(function() {{ location.reload(); }}).catch(function(e) {{ alert(e.message); }});">
  <label>Address of the update file (https)<input name="url" value="{feed}" style="width:320px" placeholder="https://example.com/finsi-latest.json"></label>
  <button type="submit">Save</button>
</form>
<p class="muted" style="font-size:12px">A small JSON file such as {{"version": "1.2.0", "url": "https://...", "notes": "What changed"}}. With no address set, the app never contacts anyone about updates.</p>
</details>
</div>
"""
