__APP_NAME__ -- QUICK START
=======================

1. Drag "__APP_NAME__.app" into your Applications folder.

2. The first time only: right-click (or Control-click) __APP_NAME__.app, choose
   "Open", then click "Open" again. macOS shows an "unidentified developer"
   warning for any app that isn't from the App Store; this is expected.

3. Your browser opens to your private dashboard (it only runs on this Mac,
   at http://127.0.0.1:8898/). Opening __APP_NAME__ again just reopens that page.

4. To stop it: Setup tab > "Quit __APP_NAME__".

WHERE YOUR DATA LIVES
  ~/Library/Application Support/__DATA_FOLDER__/   (data, backups, logs, exports)
Nothing is stored inside the app, so you can replace or delete the app
without losing anything. __APP_NAME__ makes automatic backups there.

FIRST STEPS
  - Setup tab > Household: enter your name (and a partner's, or turn the
    second person off).
  - Add accounts, spending and income on the Asset and Income/Expense tabs.
  - Optional: connect accounts with Plaid (Setup tab) -- you need your own
    Plaid developer keys; everything also works with balances typed by hand.

IF macOS ASKS ABOUT THE KEYCHAIN
  __APP_NAME__ keeps your login password and Plaid keys in your Mac's Keychain.
  If macOS asks whether "__SERVER_NAME__" may use them, enter your Mac login
  password and choose "Always Allow".

MOVING AN EXISTING INSTALL'S DATA
  Quit the old dashboard, then in Terminal:
    mkdir -p ~/Library/Application\ Support/__DATA_FOLDER__/data
    cp -R /path/to/old/Code/data/. ~/Library/Application\ Support/__DATA_FOLDER__/data/

__APP_NAME__ projects outcomes from the numbers you enter; it is a planning tool,
not financial, tax or legal advice.
