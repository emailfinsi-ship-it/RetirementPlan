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

16. **Fix: amounts typed into the Add forms and the live-trading limits no longer vanish.** The comma
    formatting for dollar boxes was also being applied to number-type boxes (which cannot hold "12,345"), so the
    browser wiped the value when you tabbed away. It now formats text boxes only. Affects the Add dialogs and
    the live-trading "Most per order / Most per day" boxes.

17. **Technical detail in the "i" pop-ups, and longer tables folded.** Every main tile and card now has a
    collapsible *Technical detail* section in its "i" pop-up: how the figure is calculated (formulas, steps, the
    tax tables and RMD divisors used), the assumptions and limits, where the numbers come from, and the terms.
    It stays precise whichever wording mode is on, and opens by default in Technical mode. The text lives in
    `source/webapp/explain_tech.py`. The longest tables now sit under one-line bars that open on tap: Actual Spending's
    *All transactions* (it opens by itself when you click a chart bar to filter it), Drawdown's *Year-by-year
    withdrawal sequence*, Legacy's *Year-by-year projection*, and Risk's *Your mix by institution*.

18. **Trading: quote, rating and advanced chart (practice and live pages).** A new *Quote and chart* card sits above the
    order form on both Trading pages (and works while live trading is off, since it only reads prices). Type a symbol,
    or click a position's symbol, to see the price and today's change, open / high / low / previous close, volume,
    bid and ask, a **day-range** bar and a **52-week-range** bar, short / medium / long **trends**, and a **technical
    Buy / Sell rating** (Strong Buy to Strong Sell) with each signal explained: price versus the 20, 50 and 200-day averages,
    the 20-day versus the 50-day, RSI, MACD and volume. The chart shows candles with the moving averages (VWAP on the
    1-day view), a **volume** panel with its 20-day average and an **RSI(14)** panel with its 30 / 70 bands, for 1D, 1M,
    3M, 6M and 1Y; move over it to read any bar. "Use SYMBOL in the order form" copies the symbol into the ticket.
    Prices come from Alpaca's free IEX feed (so volume is IEX's share, and the pop-up says so). The rating is a count of
    chart signals, not advice, and nothing here places an order. Code: `source/reporting/technicals.py`,
    `source/webapp/pages/quote_chart.py`, `source/webapp/pages/quote_panel.py`, route `/api/alpaca/quote`.

19. **Stock Analysis tab, watchlist, and Live account first.** *Quote and chart* moved off the Trading pages into a
    **Stock Analysis** page, with a new **Watchlist** table above it. The watchlist keeps your tickers (up to 50,
    with an optional note each) and shows price, day change, a day-range bar, a 52-week-range bar, volume, RSI (green at
    30 or less, red at 70 or more), short / medium / long trend arrows and the technical Buy / Sell rating; click a
    heading to sort, click a symbol to open its chart below, add several tickers at once ("AAPL, MSFT"), and prices
    refresh by themselves every minute. The whole list costs two Alpaca calls (one for quotes, one paged call for daily
    bars). The tab reads prices with the practice keys, or the live keys when only those are saved; it never places an
    order, and owner only like Trading. From a quote, buttons add it to the watchlist or open the practice or live
    order form with the symbol filled in. The **Trading** tab now has a section row like My Plan
    and Explore: **Live Account**, **Stock Analysis**, **Practice Account** (the tab opens on Live Account), and a
    position's symbol opens in Stock Analysis. Code:
    `source/webapp/pages/stock_analysis.py`, `source/webapp/pages/watchlist.py`, `source/common/db/watchlist.py`,
    `alpaca.get_bars_multi` / `get_snapshots`, routes `/api/watchlist/*`.

20. **Stock Analysis: company names, news, and a Trade button.** Every ticker now shows its company or fund name (under
    the symbol in the watchlist, beside it on a quote). Names are looked up once from Alpaca and remembered. A quote
    also lists **Latest news** about the stock (headline, source, how long ago, a short summary; links open the
    publisher's page in a new tab), and shows a note instead when news can't be loaded. Each watchlist row, and each
    quote, has a **Trade** button that opens the Live Account page with the symbol already in the order form (if live
    trading is off, the page says to turn it on first and keeps the symbol). Nothing is sent until you preview and
    confirm there, as before. Code: `alpaca.get_asset_name` / `get_news`, `quote_chart.company_names`, table `symbol_names`.

21. **Current price in the order form (practice and live).** Under the order form, the symbol you type (or arrive with
    from a Trade button) shows its current price, today's change, bid and ask and the time of the last trade, with
    one-click choices: **Market** (fills at about this price), **Limit at the price**, **Limit at bid**, **Limit at ask**
    (these fill in the Type and Limit price boxes). It refreshes every 20 seconds, says that free IEX prices can lag
    the full market, and is read-only. Route `/api/alpaca/price`, `quote_chart.build_price`.

22. **Full account numbers: why only four digits show, and a button to fix it.** The Accounts page's "show / hide all"
    switch reveals whatever number is stored, but Plaid only shares a full account and routing number for checking,
    savings and cash accounts at a bank that has been allowed the **Auth** product, and never for investment, loan or
    credit-card accounts. The Accounts page now says how many deposit accounts are showing only four digits and why,
    and Setup has a new **Enable full account numbers** button next to each such bank (the same one-time Plaid
    window as Enable Transactions; press Sync now afterwards). Code: `link_item.enable_auth_for_item`,
    route `/api/plaid-connect-auth`.

23. **Auto-push to GitHub.** `bash scripts/install_auto_push.sh` (once, on the Mac) sets up a background job that every
    5 minutes pushes master, version2 and version3 to GitHub if they have new commits, using the GitHub login your own
    Keychain already holds. It only does a plain push (never forced), never asks for a password, and logs to
    `~/Library/Logs/finsi-auto-push.log`. `bash scripts/auto_push.sh --dry-run` shows what it would push;
    `bash scripts/install_auto_push.sh --remove` turns it off.

24. **Investment balance chart: pick the lines.** The *Investment balance over time* chart now has **All**, **None** and
    **Total only** buttons, and every account name under it is a button that shows or hides that line. The chart redraws
    for what is showing and re-fits its scale (so one small account can be read on its own), and the headline change
    follows the lines showing. Works for any chart drawn with `_multi_line_chart_html`.

25. **One standard for every graph.** All charts now follow the Net Worth chart's look: labelled axes (the Investment
    balance chart gained *Balance* / *Date* axis titles, a y-axis with dollar ticks, an x-axis with dates, a dotted
    guide line and a hover box listing every visible line's value for that day; the Monte Carlo chart gained
    *Balance* / *Year* titles), and the same styled hover box everywhere. The pie/donut wedges and the bar charts
    used to show a slow, plain browser tooltip; they now show the shared box (name, amount and percent, and a
    "Click to filter" hint) instantly, and it also appears when you tab onto a wedge. The trend line and Monte Carlo
    hover boxes were restyled to match. One shared handler (`data-ctip` attributes, `_tip_attrs` in `charts.py`)
    draws them, so any future chart gets the same behaviour. The log-scale chart also shows more gridline values
    when the balances sit within one decade.

26. **Watchlist always shows what you saved.** The saved tickers (and notes) are kept in the database and now appear the
    moment the Stock Analysis page opens, drawn from the database, with prices filling in after. If prices cannot be
    read (Alpaca down or offline, keys missing or not yet readable after a restart) the list is still shown with
    "Price not available right now" and the reason, instead of looking empty. The watchlist is also shown when no
    Alpaca keys are saved yet (the connect prompt sits above it). Code: `watchlist.stored_rows`, `/api/watchlist/data`
    returns `warning` instead of failing.

27. **MACD crossover everywhere, and a prettier stock chart.** The *Quote and chart* card now says whether MACD is above
    or below its signal line and when it last crossed (bullish = up through, bearish = down through), the watchlist has
    a **MACD** column (a crossover from the last 5 trading days is highlighted, otherwise "Above / Below signal"; click
    the heading to sort), and the chart gained a **MACD panel** (histogram, MACD line, signal line, green up / red down
    triangles at each crossover). The chart itself was restyled: soft rounded panels, dotted gridlines, a price tag with
    the latest close on the right axis, red / green tinted overbought / oversold zones on RSI, smoother candles, and an
    instant floating hover box with open / high / low / close, volume, averages, RSI and MACD for the day under the
    pointer. Code: `technicals.macd_status`, `quote_chart.chart_html` / `macd_crosses`.

28. **Next earnings date, and an "Earnings this week" panel.** The watchlist has a **Next earnings** column (a report within
    7 days is highlighted; ETFs and funds show a dash because they do not report) and the *Quote and chart* card shows
    "Next earnings: Wed, Nov 6, 2026 (in 11 days)". A new **Earnings this week** card on the Stock Analysis tab lists, by
    day from Monday to Sunday, which tickers on your watchlist or held as stocks in your linked accounts report that
    week (tags say "watchlist" / "you own"; click one to open its chart; a company that already reported earlier in the
    week stays listed, tagged "reported"). Dates come from Yahoo Finance through the yfinance library the app already
    uses for industry names (Alpaca has no earnings calendar), are cached in the database (table `earnings_dates`) and
    refreshed about twice a day, so the page stays quick; if Yahoo cannot be reached the page says so and keeps the last
    known dates. Dates can change until the company confirms them. Code: `source/collector/earnings.py`,
    `pages/earnings_panel.py`, routes `/api/earnings` and `/api/earnings/week` (owner only).

29. **Compact watchlist.** The table now fits without sideways scrolling: the company name shows in the hover box over the
    symbol (instead of a second line), change % and change $ share one cell, the MACD and next-earnings cells are two-line,
    and the **Note** box is the last column.

30. **Real-money order status stays current.** The "Real-money orders sent from this app" table used to keep the status
    Alpaca gave at the instant the order was sent ("pending new"). It is now refreshed from Alpaca's own order list each
    time the Live Account page opens (and saved), so a filled order reads "filled: 1 at $343.62". Orders older than
    Alpaca's most recent 30 keep their last known status. Code: `live_trading.sync_statuses`.

31. **Sell button beside each position.** On the Live Account and Practice Account pages every position has a **Sell** button.
    It fills the order form below with a sale of that stock (all the whole shares you hold; change the number to sell
    fewer) and leaves Type on Market; switch Type to Limit and type your price to sell only at that price or better.
    Nothing is sent from the button: you still press Preview and (for real money) type the symbol to confirm. On a
    switched-off Live Account page it points you to the switch.

32. **Earnings card now covers this week and next, biggest holdings first.** The card is "Earnings this week and next" (two
    rows of Monday to Friday, weekends only when something reports). Held stocks are summed over your accounts and
    checked from the largest position down (the watchlist is always checked in full; up to 150 tickers, so only the
    smallest holdings can ever be skipped, and the card says how many). Within a day the biggest holding is listed
    first and each chip shows its share of the stocks in your linked accounts (e.g. AAPL 55%); the summary line names
    your biggest holding that reports. Code: `earnings_panel.week_universe/build_week`, `earnings.week_bounds(weeks)`.

33. **Add to watchlist now sits beside Trade on the quote card.** Look up a stock and the header shows **Add KLAC to watchlist**
    next to **Trade KLAC** (and again under the chart). Once saved it reads "On your watchlist (click to remove)" and
    removes it if pressed again. The separate "Add tickers" box on the watchlist was removed; an empty watchlist tells you
    to look a stock up below (or pick one of the examples). Code: `quote_panel.watchButton/quoteWatch`, `watchlist.watchHas`.

34. **Watchlist and Earnings cards start collapsed.** On Stock Analysis both cards show just their title (with a short count such as
    "5 stocks" or "3 tickers report in the next 2 weeks") and open when you click the title; they still load in the background so
    the counts are ready. Code: `<details class="card fold">` in `watchlist.py` and `earnings_panel.py`.

35. **IBKR and E*TRADE tabs (real money), and the Practice tab hidden.** The Trading row is now Alpaca | IBKR | E*TRADE | Stock Analysis
    (the Alpaca practice page still exists but is not offered for now). Each broker tab has: a connect card, account picker,
    balances, positions with a **Sell** button and a technical **Rating**, open and recent orders with **Cancel**, and the same
    preview-then-confirm ticket as Alpaca (type the symbol to send). All the safety rules are shared: live trading must be switched on
    (the phrase works from any of these tabs), the per-order limit and the **daily limit count every broker together**, the account
    sent by the page must be one the broker lists, a preview token works once for one broker and account, and every order is written
    to the audit log with the broker's name (`live_order_log.broker`). *IBKR* connects through IBKR's own Client Portal Gateway on this
    computer (address accepted only if it is localhost; you sign in to IBKR in your browser; if IBKR asks a question before accepting an
    order the app shows it and waits for "Send anyway", it never answers for you). *E*TRADE* uses OAuth 1.0a: save your consumer key and
    secret (Keychain), press Connect, approve in the browser and paste the code; the session ends every night. Code:
    `collector/ibkr.py`, `collector/etrade.py`, `collector/broker_common.py`, `webapp/broker_api.py`, `pages/broker_page.py`. **Not yet
    tried against the real brokers** (they cannot be reached from where this was built): the response shapes follow each broker's
    published API and are tested with simulated responses, so first use should be read-only (balances and positions), then a small order.

36. **Trade button chooses the account.** On the quote card the **Trade** button is a small menu (Alpaca, IBKR and, once its keys are
    saved, E*TRADE) that opens that account's order form with the symbol filled in; with one account it stays a plain button.
    The "Practice order" button was removed.

37. **Rating beside each position, and analysis on hover.** The Alpaca Live Account, IBKR and E*TRADE position tables show a **Rating**
    (Strong Buy to Strong Sell, the same technical rating as Stock Analysis) next to Sell, and hovering the symbol or the rating shows
    the signals behind it (bullish and bearish count, RSI, MACD crossover, trends). Needs Alpaca market-data keys saved (practice or
    live); without them the cell shows a dash. Code: `pages/position_ratings.py`, route `/api/ratings`.

38. **IBKR gateway port is found for you.** If the saved gateway address does not answer, the IBKR tab tries the usual ports on this
    computer (5000, 5001, 5500, 5555, 8888, 8443) and, when one answers, saves it and says so. The connect card now shows the
    Terminal command to start the gateway and where its port is set (`listenPort` in `root/conf.yaml`). Code: `ibkr.find_gateway`.

39. **IBKR gateway comes with the app and starts with it.** IBKR's Client Portal Gateway files are kept in `vendor/clientportal`
    (IBKR's own software, unchanged apart from `root/conf.yaml`: it listens on port 5757, a port private to this app, and its allow-list
    is cut down to this computer, 127.0.0.1, only) and are included in the Mac app by `scripts/build_mac_app.sh`. When the dashboard
    starts (`scripts/run_dashboard.sh`, the other run scripts and the Mac app all go through `dashboard.run`) it starts the gateway in the
    background unless one already answers on that port, and stops it when the app quits. The first start copies the files to the app's
    data folder (so the app itself is never written to) and runs IBKR's own `bin/run.sh root/conf.yaml` there. The IBKR tab has
    **Start gateway**, **Sign in to IBKR** (IBKR's own page: you still sign in to IBKR in the browser), **Stop gateway**, and a switch
    for starting with the app (on by default). Only that one fixed command is ever run. Java is not bundled: it must be installed on the
    Mac; if it is not, the app starts normally, the IBKR tab says so, and nothing else is affected. Set `FINSI_NO_GATEWAY=1` to skip
    the auto-start. Code: `collector/ibkr_gateway.py`, `dashboard.run`.
40. **Broker tabs: run a check, clear messages, all accounts.** The IBKR and E*TRADE tabs have a **Run a check** button that runs each read
    call in turn and shows what each returned as structure only (field names, types, list lengths: never balances, account numbers or
    tokens), so a tab that shows nothing can be diagnosed. Connect shows its progress inline. With more than one account the tab adds an
    **All accounts** card: each account's value, cash and buying power, the total, and every stock held added up across accounts.
    E*TRADE balances fall back through the other fields E*TRADE uses (cash vs margin accounts, missing real-time block) instead of
    showing $0. Code: `webapp/broker_api.py` (`_diagnose`, `_overview`), `collector/etrade.py` (`summary`).
41. **Live trading can stay on.** The turn-on form has **Keep it on until I turn it off** (ticked by default); without it live trading
    still switches itself off after 8 hours. Either way the phrase, the per-order and daily limits, the typed-symbol check and the audit
    log apply to every order, and **Turn live trading OFF now** works at any time. Code: `db/live_trading.py` (`arm(stay_on=)`, `is_persistent`).
42. **E*TRADE is production only.** The sandbox-keys option is gone; the tab shows the last four characters of the saved consumer key
    (and says if the secret is missing) so saved keys can be checked without showing them.
43. **Tax lots and cost basis, all accounts (E*TRADE).** **Show tax lots and cost basis** on the E*TRADE tab lists every purchase (lot) in
    every account the login can see: account, symbol, date bought, shares left, cost per share, cost basis, value now, gain, short/long
    term, with a subtotal per account, a grand total, and a CSV download. IBKR's gateway only reports one average cost per position
    (lots come from IBKR's Flex reports), and Alpaca reports average entry price, so those tabs keep showing the average cost.
    Code: `collector/etrade.py` (`lots`), `webapp/broker_api.py` (`_all_lots`, `/api/broker/lots`).
44. **Fewer sign-ins.** An E*TRADE session that went idle for two hours is renewed automatically instead of asking you to Connect
    (E*TRADE still ends every session at midnight US Eastern, which no program can extend). While the app runs it pings the IBKR
    gateway once a minute so a session you signed in to is not dropped for being idle (IBKR's own daily reset still applies).
    Code: `etrade.Client.json`, `ibkr_gateway.keepalive_once`.
45. **E*TRADE sign-in is easier to read.** The tab says "Signed in" while a session is valid; pressing Connect again no longer drops the
    current session until the new one is confirmed; and when E*TRADE rejects a session the message includes E*TRADE's own reason.
46. **Buy and Sell on every position** (IBKR and E*TRADE tabs): Buy fills the order ticket with that stock; Sell fills it with your shares.
    "Everything held, added up across accounts" is now collapsed, and only appears when two or more accounts hold stocks.
47. **Full positions table, sortable.** The IBKR and E*TRADE Positions table now has the same columns as E*TRADE's own portfolio view: last
    price, change $ and %, shares, price paid, day's gain $ and %, total gain $ and %, value, % of portfolio, rating, plus Buy/Sell. Click any
    heading to sort (click again to reverse; empty values always go last). E*TRADE supplies every column; IBKR's gateway has no day change, so
    those cells show "--" there. Total gain % and % of portfolio are worked out when the broker does not send them.
48. **IBKR balances by currency.** The IBKR tab adds a **Balances by currency** table (cash, stocks and total in each currency the account
    holds, the rate to the base currency, and the value in the base currency; empty currencies are hidden), and each position is shown
    in the currency it trades in, with its % of portfolio worked out in the base currency. Code: `collector/ibkr.py` (`ledger`),
    `webapp/broker_api.py` (`_add_currencies`).
49. **The IBKR gateway keeps running when FinSi quits.** Quitting and reopening FinSi no longer ends your IBKR sign-in: the gateway is
    started with the app only if nothing already answers on its port, and it is left running on quit. Only the **Stop gateway** button
    ends it. The gateway's process number is saved, so after the app is reopened the Stop button can still stop a gateway an earlier run
    started (only a process whose command line is this app's gateway, `root/conf.yaml`, is ever stopped). The app also turns macOS
    quit signals into a clean exit. Code: `ibkr_gateway.start_with_app` / `adopt_orphan` / `stop`, `dashboard._quit_cleanly`.
50. **Positions and tax lots in one table (E*TRADE).** Each stock in the Positions table has an arrow: click it to open that stock's lots
    right under it (date bought, price paid per share, shares, today's and total gain, value), and click again to collapse. Rows start
    collapsed. **Expand all lots** / **Collapse all** open and close every stock; sorting keeps each stock's lots with it. **Download
    every lot, all accounts (CSV)** replaces the old separate lots table. The lot's Sell button fills the ticket with that lot's shares
    (E*TRADE sells by the lot method set on your account). Code: `broker_page.py` (`lotRows`, `toggleLots`), `etrade.lots(symbol=)`.
51. **Orders collapse (IBKR and E*TRADE).** The Orders list starts collapsed with a count ("14 recent, 1 open"), opens with a click, and
    stays as you leave it when the page refreshes.
52. **Quieter broker tabs.** The Connect Interactive Brokers / Connect E*TRADE card is collapsible (it opens by itself when you are not
    signed in, and stays as you leave it). The long "Live trading is ON until ... Limit per order ... left today" line is replaced by a
    small "Live trading: ON / OFF" control with a Turn off button and a Limits link; the limits themselves are still enforced and are
    set on the Alpaca tab.
53. **Trading limits moved to Setup, one setting for every broker, no built-in cap.** Setup has a **Real-money trading limits** card:
    the most one order may be worth and the most that may be sent per day, applied to Alpaca, IBKR and E*TRADE together (the daily
    total adds all three). Either can be set to **No limit**. The old $25,000 per order / $50,000 per day maximums are gone; the
    practice (paper) account keeps its own small cap. The Alpaca tab now just shows today's total and a link to Setup. Every order
    still needs live trading on, a preview, the retyped symbol, and is written to the audit log. A request that leaves a limit out is
    refused (it never means "no limit"). Code: `db/live_trading.py` (`set_limits`, `NO_LIMIT`), `pages/setup.py`.
54. **All accounts at once.** The E*TRADE / IBKR / Alpaca-style broker pages with more than one account no longer open on whichever
    account happens to be first (which was often the empty one). They open on **All accounts**: the totals table, then every
    account's balances, positions (with expandable tax lots), currencies (IBKR) and a collapsed Orders section, one under the other.
    The "Show" menu still narrows to a single account, and Refresh keeps your choice. If you pick one account, or a broker has only
    one, the page looks as before. The order ticket gained an **Account** menu (set by the Buy/Sell button you press, hidden when
    there is one account), and Preview/Send/Cancel act on that account. Code: `broker_api._data` (`view`, `overview.accounts`),
    `pages/broker_page.py`.
55. **Order ticket at the top.** On the IBKR and E*TRADE tabs the order ticket now sits directly under the real-money warning, above
    Connect and the account data (it still only appears once you are connected). Code: `pages/broker_page.py`.
