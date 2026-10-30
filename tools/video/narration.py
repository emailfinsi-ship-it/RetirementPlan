"""What Fin says, scene by scene, in each of the five tour videos (Today, My Plan, Explore, Trading, Setup).

Each part is {"intro", "outro", "scenes"}. A scene is {"name", "path", "chapter", "steps": [...]}; a step is
{"sel": what to scroll to ("top" or a Playwright selector), "cap": the caption on screen, "say": the narration,
 "act": an optional named action in make_tour.py}. The product name is spelled "Fin-See" so the voice says it right."""

PARTS = {}

PARTS["today"] = {
    "title": "Today", "intro": "Hi, I'm Fin, your guide. This video is about the Today tab, the page Fin-See opens on, and how the app is laid out.",
    "outro": "That's the Today tab. Next, watch the My Plan video to see where these numbers come from. Fin-See gives estimates, not advice, and your data stays on your own computer.",
    "scenes": [
        {"name": "today", "path": "/summary.html", "chapter": "Your whole picture", "steps": [
            {"sel": "top", "cap": "Today: your whole retirement picture on one page", "say": "Today is your whole picture on one page. It tells you in plain words whether your plan is on track, using the made-up sample household we'll use throughout these videos."},
            {"sel": "nav", "cap": "Five tabs: Today, My Plan, Explore, Trading, Setup", "say": "Along the top are five tabs. Today is this page. My Plan is what you own, owe, earn and spend. Explore is where you test what might happen. Trading is for your brokerage accounts. And Setup is where you connect everything.", "act": "tour_tabs"},
            {"sel": "#alerts", "cap": "Alerts show only when something needs a look", "say": "When something needs a look, an alert appears here, and a red bell shows the count at the top of every page."},
            {"sel": "#data-check", "cap": "Data check: problems that quietly skew your numbers", "say": "The data check finds problems that quietly skew your numbers, like a fund with the wrong tag, and some can be fixed in one click."},
            {"sel": "#next-steps", "cap": "What should I do next?", "say": "And what should I do next puts the most important steps first, each with a link that takes you straight to the right place."},
            {"sel": "top", "cap": "Hide balances with the eye button", "say": "Sharing your screen? The eye button blurs every dollar amount.", "act": "hide_balances"},
            {"sel": "top", "cap": "Every tab has a Watch this video button", "say": "Every tab has an about this page note and a Watch this video button, so the matching video and guide are always one click away. The Tutorial button at the top opens them all.", "act": "show_help"},
        ]},
    ],
}

PARTS["myplan"] = {
    "title": "My Plan", "intro": "Hi, it's Fin again. In this video we'll go through My Plan: everything you enter or link, what you own and owe, and what comes in and goes out.",
    "outro": "That's My Plan. Next, the Explore video shows how Fin-See uses all of this to test your plan against thousands of possible futures.",
    "scenes": [
        {"name": "accounts", "path": "/linked-accounts.html", "chapter": "Accounts", "steps": [
            {"sel": "top", "cap": "Accounts: linked through Plaid, refreshed by themselves", "say": "Accounts lists the banks and brokerages you connected through Plaid. They refresh by themselves, and a Classify button appears for any account the plan does not count yet."}]},
        {"name": "positions", "path": "/linked-positions.html", "chapter": "Positions and Review my holdings", "steps": [
            {"sel": "top", "cap": "Positions: every holding, with its tax type and cost", "say": "Positions lists every holding, with its tax type and cost."},
            {"sel": "#checkup, h3:has-text('check-up'), .card:has-text('PORTFOLIO CHECK-UP')", "cap": "Portfolio check-up warns about concentration", "say": "The portfolio check-up warns you if one stock, one sector, or one firm is too big a share of your money."},
            {"sel": "#holdings-review", "cap": "Review my holdings", "say": "New: review my holdings. One click screens every stock and fund you own, including what your Alpaca, IBKR and E-Trade tabs show, on trend, momentum and size.", "act": "review_holdings"},
            {"sel": "#hr-table", "cap": "Worth a look first, then the rest", "say": "The ones worth a second look come first, each with the reasons in plain words, like a large position that has run up fast. These are prompts to think about, not instructions to buy or sell."}]},
        {"name": "assets", "path": "/asset.html", "chapter": "Assets and Debts", "steps": [
            {"sel": "top", "cap": "Assets & Debts: click any number to change it", "say": "Assets and debts is everything you own and owe. Click any number to change it, and tick the money you want the plan to spend. Set each account's tax type and owner here too."}]},
        {"name": "real-estate", "path": "/real-estate.html", "chapter": "Real Estate", "steps": [
            {"sel": "top", "cap": "Real Estate: value, loan and rent", "say": "Real estate tracks each property's value, loan and rent. Its equity counts toward your net worth."}]},
        {"name": "income", "path": "/expense.html", "chapter": "Income and Expenses", "steps": [
            {"sel": "top", "cap": "Income & Expenses: what comes in and goes out", "say": "Income and expenses is what comes in and what goes out, now and in retirement."},
            {"sel": ".li-del", "cap": "Tick rows to delete, or link a line to real spending", "say": "Tick rows to delete them, or link a line to real spending to see what you actually spent."}]},
        {"name": "spending", "path": "/real-expenditure.html", "chapter": "Actual Spending", "steps": [
            {"sel": "top", "cap": "Actual Spending: what really left your accounts", "say": "Actual spending shows what really left your accounts, from your linked transactions, so you can compare it with what you planned."}]},
        {"name": "budget", "path": "/budget-vs-actual.html", "chapter": "Budget vs Actual", "steps": [
            {"sel": "top", "cap": "Budget vs Actual", "say": "And budget versus actual puts the two side by side, so you can see where real life differs from the plan."}]},
    ],
}

PARTS["explore"] = {
    "title": "Explore", "intro": "Hi, it's Fin. This video covers Explore, where Fin-See answers the big question: will my money last, and what could I change?",
    "outro": "That's Explore. Fin-See only suggests; it never moves money. Next, the Trading video covers your brokerage accounts, the stock screener, and your order history.",
    "scenes": [
        {"name": "will-it-last", "path": "/monte-carlo.html", "chapter": "Will my money last?", "steps": [
            {"sel": "top", "cap": "Will my money last? Thousands of possible futures", "say": "Will my money last runs thousands of possible futures, good markets and bad, and tells you in how many of them your savings last. About eighty five percent or more is a good target."},
            {"sel": "#assumptions", "cap": "Change the assumptions, or try a what-if", "say": "Change the assumptions here, or try a what-if, like spending ten percent less or retiring two years later. Nothing is saved until you say so."}]},
        {"name": "risk", "path": "/rebalance.html", "chapter": "Risk & Suggestions", "steps": [
            {"sel": "top", "cap": "Risk & Suggestions: how much risk are you comfortable with?", "say": "On Risk and Suggestions, you choose how much risk you are comfortable with."},
            {"sel": "h2 ~ .card, .card:nth-of-type(3)", "cap": "What to buy or sell in each account", "say": "It compares your mix of stocks, bonds and cash with that goal, and says in plain dollars what to buy or sell in each account. It only suggests. It never places an order."}]},
        {"name": "drawdown", "path": "/drawdown-planning.html", "chapter": "Drawdown Planning", "steps": [
            {"sel": "top", "cap": "Drawdown Planning: which accounts to draw from", "say": "Drawdown planning shows which accounts to draw from, year by year, including required minimum distributions and tax."},
            {"sel": "#withdrawal-order", "cap": "The split that costs the least tax this year", "say": "This card compares the usual order with the split that costs the least tax this year, and shows how much tax you could save."}]},
        {"name": "legacy", "path": "/legacy-planning.html", "chapter": "Legacy Planning", "steps": [
            {"sel": "top", "cap": "Legacy Planning: compare strategies", "say": "Legacy planning compares strategies, like Roth conversions, for what you could leave to your heirs."}]},
    ],
}

PARTS["trading"] = {
    "title": "Trading", "intro": "Hi, it's Fin. This video is about the Trading tab: your Alpaca, IBKR and E-Trade accounts, researching stocks, the screener, and your order history. All the accounts and numbers you'll see here are made up.",
    "outro": "That's Trading, and that's the whole tour. Fin-See never places an order by itself, every real order needs your confirmation, and nothing here is investment advice. Press the Tutorial button any time to watch a video again.",
    "scenes": [
        {"name": "alpaca", "path": "/trading-live.html", "chapter": "Alpaca", "steps": [
            {"sel": "top", "cap": "Trading: Alpaca, IBKR, E*TRADE, research, screener, orders", "say": "The second row lists your brokers, then Stock Analysis, the Screener and Orders. This is Alpaca. These are real-money accounts, so this app only ever sends an order when you confirm it."},
            {"sel": "text=Live trading switch", "cap": "Live trading is off until you turn it on", "say": "Live trading is off until you switch it on by typing a confirmation phrase, and limits per order and per day keep a slip from getting expensive.", "act": "alpaca_arm"},
            {"sel": "h3:has-text('Positions')", "cap": "Positions with buy and sell ratings", "say": "Your positions show a rating on each holding, from strong buy in green to sell in red, based on trend and momentum.", "act": "alpaca_menu"},
            {"sel": "#ticket", "cap": "Order ticket, previewed before anything is sent", "say": "Choosing buy or sell fills in the order ticket. Press preview, and you get the estimated cost and plain-language safety checks, such as how big the order is next to your account, before you confirm anything.", "act": "alpaca_preview"}]},
        {"name": "etrade", "path": "/etrade.html", "chapter": "E*TRADE", "steps": [
            {"sel": "top", "cap": "E*TRADE: one Trade menu per position", "say": "E-Trade works the same way. Each position has a single Trade menu, like E-Trade's own, with buy and sell inside it.", "act": "broker_menu"},
            {"sel": ".lot-toggle", "cap": "Tax lots: see what each share cost", "say": "Open a position to see its tax lots, what each batch of shares cost, and whether it is a short or long term gain. Which lot sells depends on your account's lot method.", "act": "broker_lots"},
            {"sel": "#bk-preview", "cap": "Safety checks before you confirm", "say": "The preview adds safety checks: how big the order is, whether it sells your whole position, and a reminder about taxes and wash sales.", "act": "broker_preview"}]},
        {"name": "ibkr", "path": "/ibkr.html", "chapter": "IBKR", "steps": [
            {"sel": "top", "cap": "IBKR: the same layout through the IBKR gateway", "say": "Interactive Brokers uses the same layout. A small gateway program runs on your Mac, and you sign in to IBKR in your own browser, so your IBKR password never comes to this app."}]},
        {"name": "analysis", "path": "/stock-analysis.html", "chapter": "Stock Analysis", "steps": [
            {"sel": "text=Quote and chart", "cap": "Stock Analysis: research, nothing is bought or sold", "say": "Stock Analysis is for research. Look up any stock or fund for its price, chart, trend and a buy or sell rating. Nothing here buys or sells.", "act": "analysis_quote"},
            {"sel": "text=Watchlist", "cap": "Your watchlist", "say": "Add the ones you care about to your watchlist, and see them all side by side with notes of your own.", "act": "analysis_watch"}]},
        {"name": "screener", "path": "/screener.html", "chapter": "Screener", "steps": [
            {"sel": "top", "cap": "Screener: describe what you want in plain English", "say": "The screener finds stocks and funds that match what you describe. Just type it in plain English, like technology stocks that moved at least five percent this month.", "act": "screener_type"},
            {"sel": "#sc-result-card", "cap": "Results sorted by rating", "say": "Results show each name's recent moves and a rating pill, strong buy and buy in green, sell in red, and you can sort by rating. Tick rows to add them to your watchlist, download a C S V, and choose which columns to show.", "act": "screener_results"},
            {"sel": "#sc-result-card", "cap": "Trade menu on every row", "say": "Each row has a Trade menu. Pick buy or sell, choose the account, and the order form opens with the symbol filled in. Nothing is sent until you preview and confirm there.", "act": "screener_menu"},
            {"sel": "#sc-saved-card", "cap": "Save a screen and get told about new matches", "say": "Save a screen and tick tell me about new matches. The app re-checks it once a day and shows new names in the bell at the top.", "act": "screener_save"}]},
        {"name": "orders", "path": "/orders.html", "chapter": "Orders", "steps": [
            {"sel": "top", "cap": "Orders: every real order sent from the app", "say": "Orders lists every real-money order sent from this app, across all three brokers. Filter by days, broker or side, see today's total against your daily limit, and download it as a spreadsheet."}]},
    ],
}


SETUP_TEXT = {
 "SETUP1": "Let's start with setting up. After you create your password, a short wizard asks who the plan is for. Type your name and your partner's, or turn the second person off for a one-person plan.",
 "SETUP2": "Next, your birth years and the year you plan to retire. These decide when required withdrawals start, and when your savings begin to be spent.",
 "SETUP3": "Then the growth and inflation you expect. About six percent and three percent is a reasonable start, and you can change them any time.",
 "SETUP4": "Now bring in your accounts. You can connect your banks and brokerages through Plaid, or type everything in by hand. Let's look at Plaid first.",
 "SETUP5": "To use Plaid, make a free developer account at plaid dot com, and paste your Client I D and Secret here. Start with the sandbox environment, which has fake test banks. Your keys are stored only in your Mac's Keychain, and are sent nowhere except to Plaid.",
 "SETUP6": "Then connect an account. Give it a short name, choose what to pull, such as investments or transactions, and press Connect. Plaid's secure window opens, you log in to your bank there, and your bank password never passes through Fin-See. Repeat for each bank or brokerage.",
 "SETUP7": "If you would rather not link anything, press plus Add, and type in an asset, a debt, income, an expense or a property by hand.",
 "SETUP8": "Finally, on the Assets tab, mark which money is in the plan, and set each account's tax type and owner. That is all the setup.",
 "SETUP9": "To explore with example data, load the sample household. We'll use it for the rest of the tour, so none of these numbers are real.",
 "WELCOME1": "The very first time you open Fin-See, you see this welcome screen. It asks for two things, once: an admin password, and a place for your database.",
 "WELCOME2": "Choose a password of at least eight characters, and type it again to be sure. There is no username, just this one password.",
 "WELCOME3": "Your numbers are saved in a private database file on this computer. Most people keep the suggested folder, but you can choose another one. Then press create.",
 "WELCOME4": "Last, save your recovery key. If you ever forget your password, this key is the only way back in. It is shown just once, so write it down or keep it in a password manager.",
 "intro": "Hi, I'm Fin, your guide. In this video I'll walk you through getting started with Fin-See: your password, a few details about you, bringing in your accounts, and the Setup tab.",
 "outro": "That's setup. Your data stays on your own computer, and Fin-See gives estimates, not financial, investment, tax or legal advice. Next, watch the Today video to see your plan's big picture.",
 "tabs": [
  {
   "sel": "top",
   "cap": "Setup: link accounts, manage your password, keep backups",
   "say": "Setup is where you link accounts, manage your password and recovery key, and keep backups."
  },
  {
   "sel": "#recovery-key",
   "cap": "Lost your password? Your recovery key gets you back in",
   "say": "If you ever forget your password, the recovery key you saved gets you back in. You can make a new one here at any time."
  },
  {
   "sel": "#viewer-login",
   "cap": "Give a spouse or advisor a view-only password",
   "say": "You can give a spouse or advisor a view-only password. They can look at everything, but they cannot change anything."
  },
  {
   "sel": "#alerts-card",
   "cap": "Weekly email and Mac notifications",
   "say": "Turn on a weekly email and Mac notifications, so alerts find you."
  },
  {
   "sel": "#about-card",
   "cap": "About: version, disk protection, support report, updates",
   "say": "The about card shows your version, whether your disk is encrypted, a support report you can send if something goes wrong, and a button to check for updates. Nothing is ever sent without you asking."
  },
  {
   "sel": "#restore-backup",
   "cap": "Backups run daily and can be restored",
   "say": "Backups run every day. You can test the latest one with a single click, and if you ever need to go back, restore an earlier one. Your current data is saved first, so even a restore can be undone."
  },
  {
   "sel": "top",
   "cap": "Trading keys: Alpaca, IBKR and E*TRADE connect on the Trading tab",
   "say": "Your brokerage accounts connect on the Trading tab instead: Alpaca with keys, E-Trade with its own sign in, and I B K R through a small gateway. The Trading video shows how they work."
  }
 ]
}
