# Going to production: checklist

What the app now does by itself, and what only you can do.

## Built into the app (done)

| Need | What is in place |
|---|---|
| First-launch setup | Welcome screen with the logo asks for an admin password and sets up the database. Nothing else works until it is done. Same on the Mac app and from source. |
| Forgotten password | A one-time **recovery key** is shown at setup. The login page has "Forgot your password?". Setup → Security can make a new key. Stored only as a hash. |
| Private data files | The data folder, database, backups and logs are readable only by your Mac user. Setup → About shows whether FileVault (disk encryption) is on. |
| Privacy and terms | In-app page at `/legal.html`, linked from every footer. Describes exactly what the app does with data. |
| Support | Setup → About → **Download support report**: versions, sizes, recent logs, with emails, long numbers and secrets removed. Nothing is sent automatically. |
| Restore | Setup → Backups → **Restore a backup**: asks for the password, checks the backup, saves a "pre-restore" copy of your current data, then replaces it. |
| Move to a new Mac | Setup → **Move to another Mac** saves Keychain items, database and backups into one passphrase-encrypted file. The new Mac's welcome screen imports it ("Moving from another Mac?"). Same from Terminal: `scripts/transfer.py`. |
| Updates | Setup → About → **Check for updates** reads one small JSON file you host. With no address set, the app never contacts anyone. |
| Version | `APP_VERSION` in `source/common/branding.py` (shown in the app, the Mac app and the .dmg name). |
| Automatic tests | `.github/workflows/tests.yml` runs every test plus the fresh-install check on Linux and Mac for each push. |
| Fresh-install check | `python3 scripts/smoke_test.py` (add `--server dist/app-server/app-server` for the built app). Uses a throwaway home and keychain name, so it is safe on your Mac. |
| Installer | `bash scripts/build_mac_app.sh` now also makes `dist/<Brand>-<version>.dmg` and `dist/latest.json`. |

## Steps only you can do

### 1. Sign and notarize (removes the "unidentified developer" warning)
1. Join the Apple Developer Program (about $99 a year) and create a **Developer ID Application** certificate in Xcode (Settings → Accounts → Manage Certificates).
2. Once: `xcrun notarytool store-credentials "finsi-notary"` (Apple ID, Team ID, app-specific password from appleid.apple.com).
3. Build:
   ```
   SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
   NOTARY_PROFILE="finsi-notary" bash scripts/build_mac_app.sh
   ```
4. Check: `spctl -a -vv dist/FinSi.app` should say "accepted, source=Notarized Developer ID".

### 2. Publish updates
Upload the `.dmg` and `latest.json` (edit its `url`) to any https host (your website, GitHub Releases). Put the json's address in Setup → About → Update address. To release: raise `APP_VERSION`, rebuild, upload both files again.

### 3. Plaid production access
Each person today brings their own Plaid keys. If you sell the app, decide:
- **Keep "bring your own keys"** (simplest, no Plaid review for you; users need their own Plaid account), or
- **Use your own Plaid keys for everyone**: apply for Production access in the Plaid dashboard (company details, use case, security questionnaire, privacy policy URL), and expect Plaid to ask how you protect tokens. Your keys would then have to be delivered or proxied securely, which is a new server-side piece.

### 4. Legal review
Have a lawyer read the Privacy and Terms text in `source/webapp/pages/legal.py` and the disclaimer in `source/webapp/render_helpers/shell.py` before you distribute widely. Things to fill in: the publisher's legal name and a contact email (`SUPPORT_EMAIL` in `branding.py`), governing law, and any refund or support promises. Giving financial advice to the public can bring regulation; the app is worded as a planning tool, and a lawyer should confirm that fits where you sell.

### 5. Test on a clean Mac
On a Mac that never had the app (or a new user account): install the .dmg, open it, create the password, save the recovery key, add sample data, quit, reopen and log in. Then upgrade: install the next version over it and confirm data and password are still there. `scripts/smoke_test.py --server ...` automates the first half.

### 6. Disk encryption
Files are private to your Mac user and FileVault covers a lost laptop. Encrypting the database file itself (for example SQLCipher) is a larger change; do it if you will hold other people's data, or if customers or auditors ask.

### 7. Windows or a hosted version
Not started. The app is built for the Mac (Keychain, Mac app bundle). A Windows version needs a different secrets store and installer. A hosted multi-user version is a separate product: accounts, a real database, encryption at rest, backups, monitoring, and security review. Decide with your first customers before building either.

## Not covered yet
- Crash reports sent to you automatically (by design nothing is sent; people send the support report).
