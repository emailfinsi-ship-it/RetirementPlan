# FinSi Version 3 (branch `version3`)

Built on Version 2. Every calculation is unchanged; this version changes what you see first
and how you ask "what if?".

## Run it
    cd ~/Downloads/RetirementPlan/Code-v3
    ./scripts/run_version3.sh            # http://127.0.0.1:8900/
    ./scripts/stop_dashboard.sh 8900     # to stop

It uses a copy of your data in `Code-v3/data`, so your original app (8898) and Version 2 (8899)
are not touched.

## What changed
1. **Three tabs instead of eight:** **Today**, **My Plan**, **Explore** (plus Setup). The old
   pages live as small tabs under My Plan (Assets & Debts, Real Estate, Income & Expenses,
   Accounts, Actual Spending, Positions, Budget vs Actual) and Explore (Will my money last?,
   Risk & Suggestions, Drawdown Planning, Legacy Planning). The "More tools" button is gone.
2. **A ring gauge for the verdict.** The chance your money lasts is a ring with the answer in
   words beside it.
3. **Live answers.** On Today, two sliders (spending, retirement age) update the chance of
   lasting as you drag. The quick chips (spend 10% less, retire 2 years later, claim Social
   Security at 70) also answer instantly. Nothing is saved.
4. **"What changed since last time"** in one sentence under the verdict, for example
   "Since Sep 20, your net worth is up $12,300, mostly from investments. Your chance of lasting
   is steady at 88%."
5. **Suggested spending from your real transactions.** On Income & Expenses, a card lists real
   spending categories that are not in your plan yet. Tick the ones you want and press Add.
6. The quick tour now describes Today / My Plan / Explore.
7. **Fin, the robot guide.** In the setup wizard a small robot says what each step is for in a
   speech bubble and can say it out loud (**Hear this**; **Voice on/off** is remembered). Fin
   also narrates the tutorial video.
8. **Tax buckets moved to Linked Accounts.** The "resources by source" table (tax bucket and owner
   of every account) and "Split a linked account across tax buckets" now live at the bottom of
   Linked Accounts. Drawdown Planning keeps a link to them.
9. Clearer "show more" toggles (chevron badge, larger label); the safe-spending confidence level
   you pick is remembered on the Summary; header buttons stay at the top right.
10. **Every tab leads with its answer, then the detail.**
    - *Will my money last?* shows the chance and chart first, then the stress scenarios (Great
      Depression, dot-com bust, year-by-year returns), then the biggest levers, assumptions,
      saved scenarios and safe spending. The year-by-year numbers are open by default. Social
      Security details are folded below.
    - *Drawdown Planning* and *Legacy Planning* open with "this year's plan" and the year-by-year
      sequence or strategy comparison; background cards move down.
    - *Summary* order: plan on track, where you stand, summary insight, spending sources, what you own and owe, total asset over time, data check, then "What should I do next?" at the end.
    - *Income & Expenses* and *Accounts* and *Positions*: the tables come first and the charts
      last. *Risk & Suggestions*: your risk choice, then "what to do in each account", then the
      mix by institution.
    - "If you sold your real estate" now appears only on *Will my money last?*; Drawdown and Legacy link to it.
    - The Simple/Full switch is removed; every tab and tool is always shown. The header button is now "Report Download". The Tutorial page lists the User guide above the video.
    - The tutorial video is now two videos (Setting up; A tour of every screen), narrated by an illustrated presenter named Fin instead of the robot. Every tab's "About this page" bar has a "Watch this screen" link that opens the screens video at that tab. A Quit button sits after the Theme button; the Setup Wizard is a banner at the top of Setup; the spreadsheet import is last on Setup.
    - Setup Wizard guide is now the person (Fin) as in the videos; the V3 videos were re-recorded with the new My Plan tab order.
11. **Plain / Technical wording switch.** A **Wording** button in the header (next to Theme) flips
    every page between everyday words (the default) and the full financial wording. Plain mode
    uses short, friendly sentences ("Bad-luck case", "Count in my plan?", "Pre-tax retirement")
    and keeps the technical term behind the small "i". Page names (Drawdown Planning, Legacy
    Planning, Budget vs Actual) never change. It only changes words. No number changes.
    The choice is saved. A view-only login can switch it too.
    - The words live in `source/webapp/plain_rules.py`; `source/webapp/wording.py` applies them
      after a page is built. Technical mode applies nothing, so it is the original wording.
    - Grammar fixes in both modes: a spaced `--` is shown as a proper dash; "Total assets over
      time"; "an 11.0% rate"; "percentage points less in bonds than your goal"; "modeled",
      "organized".
12. **Debt paydown over time (Assets & Debts).** A "Debt paydown over time" chart now sits right
    under the Liabilities table. It follows every liability and every home mortgage (your share of
    the loan) one point a day, with a "paid down $X since DATE" headline (falling is green). The
    default line is All debts (liabilities plus mortgages); chips plot Liabilities, Home mortgages
    or any single debt, in $ or % change. Each debt's own history starts the day this ships
    (new table `debt_balance_snapshots`, filled by the same daily capture as net worth); the
    Liabilities total already had history. A workbook re-import keeps the history of imported
    loans and properties (matched by name).
13. **Trading tab (Alpaca practice account).** A new *Trading* tab (Explore menu, owner login only) connects to your
    Alpaca **paper** account: practice account value, cash, buying power, positions with gain/loss, and recent orders
    (open ones can be cancelled). A practice order ticket works in two steps: *Preview* prices and size-checks the
    order, then *Place practice order* sends exactly that order once. Safety is built in code, not just the page:
    the only host used for trading is Alpaca's paper host (live keys and live trading are not supported), one
    order is limited to $25,000, a market order needs a recent price to be sized, and the confirm step needs a
    single-use token that expires in 5 minutes. The key pair is stored in the Keychain vault, checked with Alpaca
    before it is saved, and removable with *Disconnect*. Practice balances are never counted in net worth or the
    plan. Code: `source/collector/alpaca.py`, `source/webapp/pages/trading.py`.

    **Live (real-money) trading, added to the Trading tab.** *Trading* is now its own main icon next to
    Explore, with two pages: the practice account and a separate **Live account (REAL money)** page. Live
    keys are stored apart from the practice keys and checked with Alpaca before saving. Live trading is
    **off** until you type `TRADE REAL MONEY`; it then stays on for 8 hours and switches itself off (or turn
    it off any time). While it is on, every order still needs *Preview*, then you must **type the symbol again**
    to send it. You set a per-order limit and a per-day limit (defaults $2,000 and $5,000; the app never allows
    more than $25,000 per order or $50,000 per day), the daily total counts what this app already sent today,
    and every real-money order sent is recorded in an audit list on the page. Cancelling an order never needs the
    switch. Removing the live keys also switches live trading off. Code: `source/webapp/trading_api.py`,
    `source/common/db/live_trading.py`.

14. **Summary: a quick glance first, detail on tap.** Today now opens with the answer (plan check and the three
    headline numbers), then *What should I do next?*, where you stand toward independence, and a one-line
    what-if. The longer cards -- where the money comes from, the plan projection, what you own and owe, trends
    and mix, and the data check -- sit under single-line bars that open on tap (the data check opens by itself when
    it has something to fix). The alerts card shows the top two and a "Show N more" link.

15. **Client-ready plan report.** *Report Download* now produces an adviser-style review for the household, under
    the FinSi name only: (1) your plan at a glance with the top three recommendations and a suggested review
    date, (2) goals and where you stand, (3) good / expected / bad market scenarios by year plus a replay of
    past market crashes, (4) the income and tax picture for the retirement years, and (5) assumptions and an
    "Important information" disclosures list. Each part starts on its own printed page, with page numbers; save it
    as a PDF from the print window. Code: `source/webapp/pages/report.py`.
