RETIREMENT PLAN -- QUICK SETUP
================================

1. UNZIP this folder anywhere you like (Desktop, Documents, wherever).

2. DOUBLE-CLICK "Start Retirement Plan.command".

   The first time, macOS will say it's from an "unidentified developer"
   and refuse to open it. That's expected for an app that isn't sold
   through the App Store -- to allow it:
     - Right-click (or Control-click) "Start Retirement Plan.command"
     - Choose "Open"
     - Click "Open" again in the dialog that appears
   You only need to do this once.

3. A Terminal window opens, and your browser should open automatically
   to the dashboard at http://127.0.0.1:8898/. If it doesn't open on
   its own, open that address in any browser yourself.

   KEEP the Terminal window open while you're using the dashboard --
   closing it (or pressing Ctrl+C inside it) stops the program. You can
   also stop it any time by double-clicking "Stop Retirement Plan.command".

4. FIRST TIME IN THE APP -- go to the "Setup" tab and either:
     - Import your existing retirement-plan Excel file (one-time import
       -- after that, this app is the source of truth, not the Excel
       file), or
     - Just start adding your accounts, expenses, and income by hand on
       the Asset / Expense / Income tabs.
   Optionally, you can also connect a bank or brokerage account there
   (via Plaid) so balances and investment positions update on their own.

5. YOUR DATA lives in the "data" folder right next to this file -- it
   never leaves this Mac and isn't synced anywhere. Back up that folder
   (or this whole unzipped folder) the same way you'd back up any other
   file.

That's it -- everything else you can figure out from inside the app.
Every tab has its own short description of what it does at the top.

MOVING TO ANOTHER MAC? Copy the WHOLE unzipped folder (including the
"data" folder) to the new machine and start it the same way -- nothing
else to install. Every line item, assumption, and cached balance comes
along with it. The one thing that does NOT come along: your saved Plaid
API keys and linked bank/brokerage accounts -- those live in this Mac's
own Keychain, not in the "data" folder, so on the new Mac go to the
Setup tab and re-enter your Plaid keys and re-link each account (a
couple of minutes). Everything else -- your Asset/Expense/Real Estate
line items, assumptions, and the last-synced balances -- is already
there and needs nothing re-done.

TROUBLE OPENING IT? If macOS still refuses after the right-click steps
above, go to System Settings -> Privacy & Security, scroll down, and
look for a message about "Start Retirement Plan.command" being blocked
-- there's an "Open Anyway" button there too.
