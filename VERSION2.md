# FinSi Version 2 (branch `version2`)

Version 1 is the tag `v1`. Version 2 keeps every calculation the same and changes
what you see and where you type.

## Run it
    cd ~/Downloads/RetirementPlan/Code-v2
    ./scripts/run_version2.sh            # http://127.0.0.1:8899/
    ./scripts/stop_dashboard.sh 8899     # to stop

It uses a copy of your data in `Code-v2/data`, so changes made there do not touch your
original app (port 8898).

## What changed
1. **Simple | Full switch** (page header). Simple is the default: short sentences, advanced
   tools tucked away, a "More tools" button in the tab bar. Full is the old behavior.
2. **Short sentences, detail behind an "i".** Long grey paragraphs show their first sentence;
   tap the small i to read the rest. (Full view shows everything as before.)
3. **Social Security moved** to the "Will my money last?" tab: two questions per person
   (monthly amount, start age), one Save. Medicare costs are under Advanced. The Income tab
   shows those rows as "set by the planner" and read-only, and points to the new place.
4. **Plainer wording:** "Investable savings" (was Net Liquid Asset), "Expected yearly growth",
   "Price rises (inflation)", "Pre-tax (401k / traditional IRA)", no "Monte Carlo" on the
   main pages.
5. **Summary:** a "One thing to watch" line (for example the year required withdrawals jump),
   "Amounts are in today's dollars" note, only the top 3 next steps (rest folded), and a
   **What if...?** card (spend 10% less/more, retire 2 years later, claim Social Security at 70).
6. **Setup wizard:** plain questions, asks for monthly spending, growth as Cautious / Typical /
   Optimistic buttons.
7. **Data check** also warns about a lopsided 401(k)/IRA split and rent that never grows.
8. **Quick tour** (7 steps) shows once on the Summary; "Take a quick tour" replays it.

## Not changed
All calculations, saved data and the Plaid connection. The tutorial video was not re-recorded.

## Added after review
- **Fin, the robot guide** in the setup wizard (speech bubble, spoken voice with an on/off switch) and in the tutorial video.
- **Tax buckets moved to Linked Accounts:** the "resources by source" table and "Split a linked account across tax buckets".
- Clearer "show more" toggles; the safe-spending confidence level is remembered on the Summary; header buttons stay at the top right.
- **Every tab leads with its answer, then the detail.**
  - *Will my money last?* shows the chance and chart first, then the stress scenarios (Great
    Depression, dot-com bust, year-by-year returns), then the biggest levers, assumptions,
    saved scenarios and safe spending. The year-by-year numbers are open by default. Social
    Security details are folded below.
  - *Drawdown Planning* and *Legacy Planning* open with "this year's plan" and the year-by-year
    sequence or strategy comparison; background cards move down.
  - *Summary* order: plan on track, where you stand, summary insight, spending sources, what you own and owe, total asset over time, data check, then "What should I do next?" at the end.
  - *Income & Expenses*, *Accounts* and *Positions* keep their charts first (the charts filter the
    table below them). *Risk & Suggestions*: your risk choice, then "what to do in each account", then the
    mix by institution.
  - "If you sold your real estate" now appears only on *Will my money last?*; Drawdown and Legacy link to it.
  - The Simple/Full switch is removed; every tab and tool is always shown. The header button is now "Report Download". The Tutorial page lists the User guide above the video.
  - The tutorial video is now two videos (Setting up; A tour of every screen), narrated by an illustrated presenter named Fin instead of the robot. Every tab's "About this page" bar has a "Watch this screen" link that opens the screens video at that tab. A Quit button sits after the Theme button; the Setup Wizard is a banner at the top of Setup; the spreadsheet import is last on Setup.

- **Debt paydown over time (Assets & Debts).** A "Debt paydown over time" chart now sits right
    under the Liabilities table. It follows every liability and every home mortgage (your share of
    the loan) one point a day, with a "paid down $X since DATE" headline (falling is green). The
    default line is All debts (liabilities plus mortgages); chips plot Liabilities, Home mortgages
    or any single debt, in $ or % change. Each debt's own history starts the day this ships
    (new table `debt_balance_snapshots`, filled by the same daily capture as net worth); the
    Liabilities total already had history. A workbook re-import keeps the history of imported
    loans and properties (matched by name).

- **Trading tab (Alpaca practice account).** A new *Trading* tab (Explore menu, owner login only) connects to your
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

## Summary quick glance and client report (also in version 3)

- The Summary leads with the answer, *What should I do next?* and a quick what-if; the longer cards are tucked
  under one-line bars that open on tap.
- *Report Download* is now an adviser-style client report (plan at a glance with top recommendations, goals,
  good / expected / bad market scenarios, income and tax picture, assumptions and disclosures), FinSi branding only.

- The "i" pop-ups gain a collapsible *Technical detail* section (calculation, assumptions and limits, sources,
  terms), and the longest tables (All transactions, Drawdown year-by-year, Legacy year-by-year, mix by institution)
  fold under tap-open bars.

- Trading: a *Quote and chart* card (price, day and 52-week range, trends, technical Buy / Sell rating, and a price /
  volume / RSI chart with moving averages) above the order form on the practice and live pages.

- Stock Analysis: *Quote and chart* moved here from the Trading pages, with a watchlist table (price, change,
  day and 52-week range, RSI, trends, technical rating). The Trading tab now has a section row (Live Account,
  Stock Analysis, Practice Account) and opens on Live Account.

- Stock Analysis: company names, a Latest news list on each quote, and a Trade button (watchlist rows and quotes) that
  opens the Live Account order form with the symbol filled in.

- Order forms (practice and live) show the symbol's current price, change, bid and ask with Market / Limit-at-price /
  bid / ask buttons that fill in the order type and limit price.

- Accounts page explains why some accounts show only four digits; Setup gains **Enable full account numbers** (Plaid
  Auth) for banks with checking, savings or cash accounts.

- `scripts/auto_push.sh` / `scripts/install_auto_push.sh`: optional background push of the three branches to GitHub.

- Investment balance chart: All / None / Total only buttons and click-a-name to show or hide lines; scale re-fits.

- Earnings card is now "Earnings this week and next": two weeks, held stocks checked from the largest position down (up to 150 tickers), biggest holding first within each day, each chip tagged with its share of your stock holdings.

- Quote card: "Add to watchlist" button next to Trade (toggles to "On your watchlist"); the watchlist's separate "Add tickers" box was removed.

- Stock Analysis: the Watchlist and Earnings cards start collapsed (click the title to expand) and show a short count.

- IBKR and E*TRADE trading tabs (real money, preview-then-confirm, shared limits and audit log), Trade button menu on the quote card, Rating and hover analysis beside each position, Practice Account tab hidden. See VERSION3.md items 35-37 for the details.

- IBKR tab finds the gateway on its usual alternative ports and remembers the one that answers.

- IBKR gateway files bundled in vendor/clientportal; the IBKR tab has Start gateway / Sign in to IBKR / Stop gateway (needs Java on the Mac).

- IBKR / E*TRADE tabs: Run a check button, inline Connect messages, an All accounts overview (values, cash, totals, combined holdings), E*TRADE balance fallbacks, production-only E*TRADE keys with a last-four check, and a "keep live trading on until I turn it off" option on the turn-on forms.

- E*TRADE tax lots and cost basis for all accounts (with CSV), automatic renewal of an idle E*TRADE session, and a keep-alive for the IBKR gateway session.

- IBKR / E*TRADE tabs: Buy and Sell buttons on every position; the "added up across accounts" table is collapsed and only shown when two or more accounts hold stocks.

- IBKR / E*TRADE tabs: sortable positions table with every column of E*TRADE's portfolio view (change, day gain, total gain %, % of portfolio, rating).

- IBKR tab: balances by currency (cash, stocks, rate to base) and each position shown in its own currency.

- The IBKR gateway keeps running when FinSi quits (started only if not already up; only the Stop gateway button ends it), so quitting and reopening does not end your IBKR sign-in.

- E*TRADE tab: Positions and tax lots in one table (arrow beside each stock opens its lots; Expand all / Collapse all; CSV of every lot in all accounts).

- All accounts at once on the broker pages; no fixed live-order limits (set in Setup); Orders/Connect collapsible; live ON/OFF control.

- Order ticket at the top of the IBKR and E*TRADE tabs.

- Green and red gains in the IBKR / E*TRADE positions table.

- Yahoo Finance fallback for prices when Alpaca is unavailable; tabs show the last view instantly on return (IBKR/E*TRADE/Alpaca/watchlist).

- Yahoo Finance price fallback; instant return to trading tabs; extended-hours / overnight order session and after-hours prices; clearer rating hover box.

- Yahoo Finance price fallback; instant return to trading tabs; extended-hours / overnight order session and after-hours prices; clearer rating hover box.
