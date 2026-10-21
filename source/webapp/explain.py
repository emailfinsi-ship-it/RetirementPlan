"""The little "i" buttons: tap one next to a tile or card title and a pop-up
explains it in plain words -- what it is, how to read it, what you can do.
Every tab also gets an "About this page" button.

How it works: every page is built as usual, then annotate() looks at each card
title and tile label, and where the registry below knows it, adds an "i"
button. Only the explanations used on the page are sent to the browser.
Pages and tiles that have no entry simply get no button.

To explain a new tile: add one entry with _add() and one matching rule in
RULES (a regex tested against the lower-cased title/label text).
"""

from __future__ import annotations

import html
import json
import re

from source.reporting import presentation as pres

_E: dict[str, dict] = {}


def _add(key: str, title: str, what: str, read: str = "", do: str = "") -> None:
    _E[key] = {"title": title, "what": what, "read": read, "do": do}


_ON = f"{pres.ON_TRACK_AT * 100:.0f}%"
_REVIEW = f"{pres.REVIEW_AT * 100:.0f}%"

# --------------------------------------------------------------------------
# Whole pages ("About this page")
# --------------------------------------------------------------------------
_add("page:summary.html", "About the Summary page",
     "Your whole retirement picture on one page: how the plan looks, what you own, how it changed, and what to do next.",
     "Read from the top. The big card says whether you are on track. Below it are the details behind that answer.",
     "Start with 'What should I do next?' near the bottom. Tap the i next to any tile to learn what it means.")
_add("page:asset.html", "About Assets & Debts",
     "Everything you own and owe, in your own words, grouped by category: retirement accounts, brokerage, cash, insurance and loans.",
     "Each row is one item with a balance. The 'In the plan?' box says whether that money counts toward your retirement spending.",
     "Click any number to change it. Use + Add (bottom right) for new items. Real estate has its own tab.")
_add("page:real-estate.html", "About Real Estate",
     "Each property's value, loan and rent. The equity (value minus loan) counts toward your net worth.",
     "Rent adds to your income. Properties marked 'In the plan?' can be sold in the simulation to fund spending.",
     "Update values now and then. Use 'What if I sold?' to see the effect of selling.")
_add("page:linked-accounts.html", "About Linked Accounts",
     "Bank, credit and investment balances pulled live from your institutions through Plaid. This is read-only: nothing here can move money.",
     "Balances refresh when you press Sync now. Totals are grouped by institution and by account type.",
     "Classify any account that is not counted yet so its balance joins your plan.")
_add("page:linked-positions.html", "About Linked Positions",
     "Every investment holding in your linked accounts: what you own, how much, its tax type and its cost.",
     "The check-up near the top warns if one stock, sector or firm is too large a share of your money.",
     "Fix any wrong sector or tax tag so the charts and advice stay right.")
_add("page:rebalance.html", "About Risk & Suggestions",
     "Compares your mix of stocks, bonds and cash with the mix that suits how much risk you are comfortable with, and suggests what to move.",
     "'Your mix today' is what you hold. The suggestions per account say what to buy or sell to get closer to your goal.",
     "Pick a risk level first. This app only suggests; it never buys or sells anything.")
_add("page:expense.html", "About Income & Expenses",
     "What comes in and what goes out each year, now and in retirement. These numbers drive how much you need to withdraw from savings.",
     "Each row is a yearly amount, optionally limited to certain years. Rows that inflate grow with the inflation rate.",
     "Keep it honest: spending you leave out makes the plan look better than it is.")
_add("page:real-expenditure.html", "About Actual Spending",
     "What you really spent and earned, from your linked accounts' transactions, as opposed to what you planned.",
     "Charts group the money by category and by month. Click a bar to filter the list of transactions.",
     "Use it to spot spending that is higher than your plan, and to link plan lines to real spending.")
_add("page:budget-vs-actual.html", "About Budget vs Actual",
     "Your planned income and spending for this year next to what actually happened so far.",
     "Variance is actual minus plan. The projected full-year figure estimates where the year will end if the pace continues.",
     "If you are far over plan, adjust the plan on Income & Expenses so the simulation stays realistic.")
_add("page:monte-carlo.html", "About 'Will my money last?'",
     "Runs your plan through thousands of possible market futures, good and bad, and shows how often the money lasts.",
     "The chance is the share of those futures in which you never run out. Cautious, typical and strong cases show what is left at the end.",
     "Try a what-if (nothing is saved) to see how spending less or retiring later changes the odds.")
_add("page:drawdown-planning.html", "About Drawdown Planning",
     "Which account to draw from each year in retirement, and how taxes and required withdrawals affect it.",
     "Money is grouped by tax type: taxable, tax-deferred (401k and traditional IRA) and Roth. The order you spend them in changes your tax bill.",
     "Check the cheapest split for this year, and set the age to start using tax-deferred money if you want.")
_add("page:legacy-planning.html", "About Legacy Planning",
     "Compares ways to leave more to your heirs, such as converting tax-deferred money to Roth, after tax.",
     "Each strategy is ranked by what is left for heirs. The recommended one is shown at the top.",
     "Set your heirs' tax assumptions, then try your own strategy. These are estimates, so check with a tax professional.")
_add("page:setup.html", "About Setup",
     "Where you set up and look after the app: your household, bank connections, password and recovery key, alerts, backups and moving to a new Mac.",
     "Common things are near the top. Less common settings are folded under Advanced settings.",
     "A good order: household, accounts, password and recovery key, then alerts and backups.")

# --------------------------------------------------------------------------
# Summary page
# --------------------------------------------------------------------------
_add("alerts", "Alerts",
     "Things that need a look: your chance of lasting dropped, a data problem, or an investment that is too concentrated.",
     "Each alert says what happened and links to where to look. The bell at the top shows the same count.",
     "Open the link, fix or review it, then Dismiss it. A weekly email and Mac notifications can be turned on in Setup.")
_add("plan_status", "Is my plan on track?",
     "A one-word answer from the simulation: your chance of not running out of money.",
     f"Above {_ON} means on track. {_REVIEW} to {_ON} is worth a second look. Below {_REVIEW} needs attention. The sentence under it says how many simulated futures worked.",
     "If it is not green, open the 'Will my money last?' tab and try spending a little less or retiring a little later.")
_add("net_worth", "Net worth",
     "Everything you own minus everything you owe, including the equity in your property.",
     "It is the total picture, but not all of it can be spent. Home equity, for example, is not cash.",
     "Compare it with 'Investable savings' to see how much is actually available to fund retirement.")
_add("investable", "Investable savings",
     "The money in your plan that you could actually draw on: accounts marked 'In the plan?' minus any debts.",
     "This is the starting point for the simulation, not your full net worth.",
     "If it looks too low, check the Assets tab to see that the right accounts are ticked 'In the plan?'.")
_add("yearly_spending", "Yearly spending",
     "How much you expect to spend next year, with inflation added, from your Income & Expenses tab.",
     "This is the amount your plan must cover each year, before other income is subtracted.",
     "Change it on the Income & Expenses tab.")
_add("where_you_stand", "Where you stand",
     "Three quick checks: progress toward financial independence, how much you can safely spend, and what changed since last time.",
     "Each box answers one question in plain words.")
_add("fi", "Financial independence",
     "How close your savings are to the amount that could pay your yearly costs for life. The target is 25 times the spending your income does not cover.",
     "100% means you have reached the number. The line below says about when you could, at your assumed growth and adding nothing new.",
     "Raise savings, lower spending, or add income to move the date earlier.")
_add("safe_spend", "How much can I safely spend?",
     "The most you could spend each year in retirement and still have your chosen chance of the money lasting.",
     "It comes from the same simulation as your plan check. A higher confidence level gives a smaller, safer number.",
     "Change the confidence level on the 'Will my money last?' tab.")
_add("since_then", "What changed",
     "How your net worth has moved since about a month ago, and which accounts drove it.",
     "The list shows each part of the change. 'Biggest moves' names the accounts that moved most.",
     "A big drop is usually the market. Check it against your plan check before acting.")
_add("own_owe", "What you own and owe",
     "A simple list of your assets and your debts, added up to your net worth.",
     "Debts come off the total. Items you have not marked 'In the plan?' still count here but are not spent in the simulation.",
     "Click a number to see where it comes from, or change it on the Assets tab.")
_add("money_last", "Will your money last?",
     "A chart of thousands of possible market futures for your savings through retirement.",
     "Each thin line is one possible future. The shaded band holds the middle 8 in 10 outcomes and the solid line is the typical one.",
     "The wider the band, the more uncertain the result. Try what-ifs on the 'Will my money last?' tab.")
_add("start_balance", "Starting balance",
     "The money the simulation starts with: accounts marked 'In the plan?' plus property you chose to include, less debts.",
     "It can differ from your net worth because it leaves out things you would not spend, such as a home you live in.")
_add("chance", "Chance your money lasts",
     "Out of all the simulated futures, how often you do not run out of money before the end of the plan.",
     f"Planners often want {_ON} or more. 100% does not mean certain, it means it never failed in these tests.",
     "Raise it by spending a little less, retiring a little later, or saving more.")
_add("cautious", "Cautious case",
     "What is left at the end of the plan in a bad but not extreme future: 1 time in 10 does worse than this.",
     "Think of it as the unlucky-markets result.",
     "If this number is zero, your plan can run out in bad markets. See 'What could go wrong?'.")
_add("typical", "Typical case",
     "What is left at the end in the middle future: half the futures do better and half do worse.",
     "Figures can be shown in today's dollars or future dollars; the toggle above the chart switches them.")
_add("strong", "Strong case",
     "What is left at the end in a good future: 1 time in 10 does better than this.",
     "A large number here only means good luck is possible. Plan for the cautious case.")
_add("spending_sources", "Where your retirement spending comes from",
     "A bar for each year of retirement showing which money pays the bills: income, taxable accounts, tax-deferred accounts or Roth.",
     "The dashed line is that year's spending plus taxes. Hover or tap a year for exact amounts.",
     "The Drawdown tab shows the same plan in more detail, and lets you change the order.")
_add("trend", "Total asset over time",
     "A daily record of your total assets, captured automatically each day the app runs.",
     "The figure beside the title is the change over the period shown. Dips usually follow the market.",
     "Give it a few days of history first; the line fills in over time.")
_add("insight", "Summary insight",
     "A quick health check of the plan as a whole: how well income covers spending, how liquid you are, how much debt you carry, and where your money is concentrated.",
     "Three tiles on top, then a chart of your assets and one of your expenses.")
_add("coverage", "Income covers expenses",
     "The share of this year's spending that your income already pays for.",
     "100% or more means income covers your spending. Below 100% means savings fill the gap.",
     "If it is low and you are still working, saving more helps. In retirement, this gap is what you draw from savings.")
_add("liquid_share", "Liquid share of net worth",
     "How much of your net worth is in money you could use soon, as opposed to property or other assets that are hard to sell.",
     "A low share means much of your wealth is tied up, which can make a bad year harder to ride out.")
_add("debt_ratio", "Debt-to-asset ratio",
     "How much of what you hold is financed by debt: debts divided by total assets plus debts.",
     "Lower is safer. Zero means no debt.",
     "Paying down expensive debt improves this and your plan.")
_add("asset_alloc", "Asset allocation",
     "How your assets are split between categories such as retirement accounts, cash and property.",
     "A big slice means a big concentration. The Risk & Suggestions tab compares your investments with a goal mix.")
_add("expense_chart", "Expenses by category",
     "Where your yearly spending goes, by category, in nominal dollars (before inflation adjustments).",
     "The longest bars are the best places to look if you want to cut spending.")
_add("data_check", "Data check",
     "Finds problems in your data that quietly skew the numbers, such as a fund with the wrong sector, an account that has not synced, or holdings with no cost.",
     "Each item says what is wrong and why it matters. Some have a one-click fix.",
     "Fix warnings first; they affect your results most.")
_add("next_steps", "What should I do next?",
     "A short list of the most useful things to do, most important first, pulled from every check the app makes.",
     "Each step says why it matters and links to the right tab.",
     "Do the top one first. It changes as your plan changes.")

# --------------------------------------------------------------------------
# Other tabs
# --------------------------------------------------------------------------
_add("assets_card", "Assets",
     "Your own list of what you own, grouped by category, with the current balance of each.",
     "'In the plan?' decides whether that money is spent in the retirement simulation. The tax type and owner columns affect tax and required withdrawals.",
     "Click a value to edit it. Add more with + Add.")
_add("liabilities", "Liabilities",
     "What you owe: loans, mortgages on non-listed property and other debts.",
     "Debts reduce your net worth and, if included, your starting balance.")
_add("liquid_trend", "Net liquid asset over time",
     "A daily record of your investable savings, captured automatically.",
     "The change shown is for the period on the chart.")
_add("re_card", "Real Estate",
     "Your properties: value, loan, rent and costs. Equity (value minus loan) counts toward net worth.",
     "Properties marked 'In the plan?' can be sold in the simulation to pay for spending.",
     "Keep values up to date. RentCast can estimate values if you add a key in Setup.")
_add("re_sell", "What if I sold?",
     "Shows the effect of selling every property in one year: the sale money joins your taxable savings and the rent stops.",
     "It estimates costs and tax on the gain. Other tabs show Keep and Sell side by side.",
     "Pick the year, then compare. These are estimates, so ask a tax professional before selling.")
_add("linked_accounts", "Linked Accounts",
     "Live balances from the institutions you connected through Plaid. Read-only.",
     "An account not yet counted shows a Classify control so you can add it to your plan.",
     "Press Sync now to refresh, and Classify any new account.")
_add("la_group", "Balances by institution and type",
     "Your linked balances grouped two ways: by the bank or broker, and by kind of account.",
     "Use it to see where your money sits.")
_add("positions", "Linked Positions",
     "Every holding in your linked investment accounts, with its type, tax bucket and cost.",
     "Cost and tax type feed the tax estimates.",
     "Fix a wrong tag so charts and advice stay right.")
_add("checkup", "Portfolio check-up",
     "Warns when one stock, sector or firm is too big a share of your investments.",
     "A warning means a single downturn there would hurt you more than a spread-out portfolio.",
     "Spread the money out, or accept the risk knowingly.")
_add("pos_charts", "Positions by type, institution, sector and industry",
     "Your investments split different ways so you can see where they are concentrated.",
     "Large slices mean concentration. Sectors and industries come from market data and may be missing for funds or cash.")
_add("risk_level", "How much risk are you comfortable with?",
     "Your choice sets a goal mix of stocks, bonds and cash. More stocks means more growth and more ups and downs.",
     "If you have not chosen, Moderate is shown.",
     "Pick the level you could stay calm with in a bad year.")
_add("mix_today", "Your mix today",
     "What you hold across all linked accounts, split into stocks, bonds, cash and other, compared with your goal.",
     "Drift is how many points you are above or below the goal in each group.",
     "Large drift is a sign it is time to rebalance.")
_add("mix_class", "Stocks, bonds, cash, other",
     "The share of your linked money in each broad group, against your goal.",
     "A positive drift means you hold more than your goal; negative means less.")
_add("mix_inst", "Your mix by institution",
     "The same stocks, bonds and cash split, shown for each bank or broker.",
     "Useful for seeing which account to change first.")
_add("what_to_do", "What to do in each account",
     "For each account, which kinds of holdings to buy or sell to move toward your goal mix.",
     "These are suggestions in plain dollars. The app never trades for you.",
     "Selling in a taxable account can create tax. The Drawdown tab explains the tax types.")
_add("ie_card", "Income & Expenses",
     "Each row is a yearly amount, for all years or a range of years. Together they show what you need to withdraw from savings.",
     "Rows that inflate grow with your inflation rate each year.",
     "Click an amount to edit it, or tick rows to delete them.")
_add("ie_income", "Income this year",
     "What you expect to earn this year from all your income lines.")
_add("ie_need", "Expense need",
     "What you expect to spend this year, including inflation, from your expense lines.")
_add("ie_withdraw", "Net withdrawal need",
     "Spending minus income: the part your savings must pay this year.",
     "If it is negative, income covers all of your spending.")
_add("inflation", "Inflation %",
     "How fast prices are assumed to rise each year. Rows marked to inflate grow by this rate.",
     "Higher inflation makes future spending, and the amount you need to withdraw, larger.",
     "Change it with your other assumptions on the 'Will my money last?' tab.")
_add("ie_income_list", "Income",
     "Every source of income: pay, pensions, Social Security, rent and so on, each with a yearly amount and optional years.",
     "Social Security and Medicare planning is in the folded planner on this page.")
_add("ie_expense_list", "Expenses",
     "Every spending line, each with a yearly amount and optional years.",
     "Fixed costs stay the same; variable costs can inflate. Being complete here matters more than being exact.")
_add("ie_charts", "Income and expenses by category",
     "Your yearly income and spending grouped by category, in nominal dollars.",
     "The longest bars show where most of the money comes from and goes.")
_add("real_exp", "Actual spending and income",
     "Totals from the real transactions in your linked accounts over the period shown.",
     "These are what happened, not what you planned. Transfers between your own accounts are left out when they can be recognized.")
_add("real_charts", "Real spending and income by category and month",
     "The same transactions grouped by category and by month.",
     "Click a bar to filter the transaction list underneath to just that category or month.")
_add("real_tables", "Monthly, annual and all transactions",
     "The same real transactions as tables: month by month, year by year, and one line each.",
     "Recategorize a transaction or add a rule in Setup if something is in the wrong category.")
_add("bva_expense", "Expense budget vs actual",
     "Your planned spending for this year against what you have really spent so far.",
     "Projected full-year spend assumes the pace so far continues. A positive variance means you spent more than planned.",
     "If you are far over, update your expense plan so the simulation stays realistic.")
_add("bva_income", "Income plan vs actual",
     "Your planned income for this year against what has really arrived so far.",
     "A negative variance means less came in than planned.")
_add("bva_charts", "Budgeted vs actual by month",
     "Month by month: what you planned against what happened.",
     "Look for months that stand out, not small differences.")
_add("mc_what_if", "When could I retire?",
     "Drag the retirement year to see how one decision changes your chance of lasting. Nothing is saved.",
     "Later retirement usually raises the chance because savings grow longer and are spent for fewer years.")
_add("mc_how", "How this works",
     "The simulation runs your plan through many random market futures and counts how many end with money left.",
     "More runs give steadier answers. It uses your growth, inflation, spending, income and tax settings.")
_add("mc_wrong", "What could go wrong?",
     "Three ways to test your plan against bad luck: real market history replayed, real recessions starting right as you retire, and selling a property.")
_add("mc_sp", "Real market history",
     "Instead of random returns, this replays actual S&P 500 history year by year to test your plan.",
     "It shows how the plan would have fared in the real past, including bad stretches.")
_add("mc_sp_chance", "S&P 500 chance your money lasts",
     "How often your plan lasted when tested against real past S&P 500 returns.",
     "Compare it with the main chance. A big gap means the answer depends on what markets do.")
_add("mc_sp_range", "S&P 500 cases",
     "What is left at the end when the plan is tested against real market history: cautious, typical and strong cases.")
_add("mc_sell", "If you sold your real estate",
     "The same simulation with every property sold, on the same random markets so the only difference is the sale.",
     "It shows whether keeping or selling gives a better chance of lasting.")
_add("mc_stress", "Historical recession stress test",
     "Replays real past recessions starting the very year your plan begins, to see whether you would have run out of money.",
     "This is the 'retire right before a crash' test, and is often the hardest one.")
_add("mc_yearly", "Year-by-year detail",
     "The cautious, typical and strong balances for each year of the plan.",
     "Use it to see when money could run low.")
_add("mc_levers", "What moves your plan most",
     "Tests how much your chance of lasting changes when you shift one assumption at a time.",
     "The one at the top is the biggest lever for your plan.")
_add("mc_scenarios", "Saved scenarios",
     "Ideas you saved so you can compare them side by side.",
     "Save a what-if you like, then compare it with your plan later.")
_add("mc_assumptions", "Assumptions and what-if",
     "Two ways to change the plan: test an idea first (nothing saved), then enter the numbers you want to keep.",
     "Saved assumptions are used on every tab.")
_add("mc_whatif", "Try a what-if",
     "Change spending, retirement age or growth and see the effect on your chance of lasting. Nothing is saved.",
     "Press Compare to see your plan next to the changed version.")
_add("mc_assump_saved", "Your assumptions",
     "The numbers your whole plan is built on: growth, inflation, birth years and retirement year.",
     "Saving changes them everywhere in the app.",
     "Be realistic: a higher growth assumption makes the plan look better but is riskier to rely on.")
_add("dd_pools", "Resources by tax type",
     "Your retirement money grouped by how it is taxed: taxable, tax-deferred (401k and traditional IRA), Roth, and property you chose to include.",
     "Taxable money is taxed on gains, tax-deferred money is taxed when withdrawn, and Roth money comes out tax-free.")
_add("dd_pool_tile", "Tax buckets",
     "The total in each tax type.",
     "Each tax type is taxed differently, so which you draw from first changes your tax bill.")
_add("dd_rmd", "Required Minimum Distributions",
     "The yearly amount the law makes you withdraw from tax-deferred accounts once you reach a certain age (73 or 75).",
     "It is worked out per person from that person's own accounts, so assign each account to its owner.",
     "Large RMDs can push you into a higher bracket; Roth conversions can lower them.")
_add("dd_split", "Split a linked account across tax buckets",
     "A single account sometimes holds pre-tax, Roth and after-tax money. Here you can split it into pieces.",
     "Use your institution's breakdown of 'sources' for the exact amounts.")
_add("dd_order", "Withdrawal order",
     "The order in which the plan spends your accounts. The default spends taxable first, then tax-deferred, then Roth.",
     "You can set an age to start using tax-deferred money earlier, which sometimes lowers lifetime tax.")
_add("dd_sell", "If you sold your real estate",
     "Your year-by-year plan re-run with every property sold, so you can compare.",
     "Sale money joins your taxable pool and rent stops.")
_add("dd_sequence", "Year-by-year withdrawal sequence",
     "A table of each year of retirement: what you need, where it comes from, and the tax.",
     "Use it to see when each account gets used up.")
_add("dd_year", "Your plan for this year",
     "What to take from which account this year to cover your spending, including the tax on that withdrawal.",
     "These are estimates for planning, not tax advice.")
_add("dd_best", "Which account should I take it from?",
     "Compares the usual order (spend the brokerage first) with a suggested split that has the least tax for this year.",
     "The saving shown is the estimated tax difference for this year.",
     "If the saving is worth it, follow the suggested split this year.")
_add("lg_card", "Your plan for this year (legacy)",
     "The recommended strategy for what is left to your heirs, and what to do this year to follow it.",
     "It is the strategy with the most left to heirs after tax among those tested, and may include converting some tax-deferred money to Roth.",
     "Ask a tax professional before you convert anything.")
_add("lg_heirs", "Heir assumptions",
     "How your heirs are taxed: their tax rate and how long they hold inherited accounts.",
     "These change which strategy looks best, because heirs often pay tax on tax-deferred money they inherit.")
_add("lg_compare", "Strategy comparison",
     "Each strategy side by side, ranked by what is left to your heirs after tax.",
     "'Baseline' means no conversions. A strategy that beats it is worth discussing with a tax professional.")
_add("lg_own", "Try your own strategy",
     "Adds one more row to the comparison using the tax bracket and yearly cap you choose.",
     "Brackets are 10, 12, 22, 24, 32, 35 and 37%. Use the cap to land between two of them.")
_add("lg_year", "Year-by-year (legacy)",
     "The recommended strategy's yearly projection, with columns for how much moved to Roth and the tax paid.")

# Setup
_add("su_household", "Household",
     "Who the plan is for: your name and, if there is one, your partner's.",
     "Names appear everywhere and drive the owner columns and Social Security planning.",
     "Turn the second person off for a one-person plan.")
_add("su_sample", "Sample data",
     "Fills the app with a made-up household so you can explore. Remove it before you enter your own numbers.",
     "Only the sample rows are removed; anything you typed yourself stays.")
_add("su_plaid_keys", "Plaid API keys",
     "Your own free keys from plaid.com. They let the app read your accounts. They are stored in your Mac's Keychain and sent only to Plaid.",
     "Start with the sandbox, which has pretend banks.")
_add("su_connect", "Connect an account",
     "Link a bank or brokerage. Give it a short name, choose what to pull, then press Connect and log in on Plaid's secure window.",
     "Your bank password never goes through this app.")
_add("su_security", "Security",
     "Your login password, a recovery key in case you forget it, and an optional view-only password.",
     "Changing the password signs out every other browser.")
_add("su_viewer", "View-only login",
     "A second password for a spouse, advisor or accountant. They can look at everything but change nothing.",
     "Changing or removing it signs them out right away.")
_add("su_about", "About, protection and updates",
     "Your version, whether the disk is encrypted, a support report you can send if something goes wrong, and a button to check for updates.",
     "Nothing is sent unless you press a button and send it yourself.")
_add("su_transfer", "Move to another Mac",
     "Saves your keys, password, data and backups into one passphrase-locked file to open on a new Mac.",
     "Keep the passphrase safe. Without it the file cannot be opened.")
_add("su_locations", "Data and output locations",
     "Where your database and your Excel exports are kept on this Mac, and a button to make a new export.")
_add("su_rules", "Category rules",
     "Your own rules for sorting transactions into categories, for example every 'Netflix' goes under Entertainment.",
     "Your rules run before the built-in ones.")
_add("su_autosync", "Automatic sync",
     "When on, the app refreshes your linked accounts by itself once they are a set number of days old, each time you open it.")
_add("su_rentcast", "Property value estimates",
     "Optional. With a RentCast key the app can suggest current values for your properties.")
_add("su_network", "Network access",
     "By default only this Mac can reach the app. You can allow your iPhone or other devices, but a password is then required.",
     "Changes take effect after you restart the app.")
_add("su_quit", "Quit",
     "Stops the app on this Mac. Your data stays where it is.")

# --------------------------------------------------------------------------
# Matching: (regex on lower-cased text, key, pages or None for every page)
# --------------------------------------------------------------------------
_S = {"summary.html"}
RULES: list[tuple[str, str, set | None]] = [
    (r"^alerts \(", "alerts", None),
    (r"^your plan (is on track|is worth a second look|needs attention)", "plan_status", _S),
    (r"^net worth$", "net_worth", None),
    (r"^investable savings$", "investable", None),
    (r"^yearly spending in \d{4}$", "yearly_spending", None),
    (r"^where you stand$", "where_you_stand", None),
    (r"^financial independence$", "fi", None),
    (r"^how much can i safely spend\?", "safe_spend", None),
    (r"^since ", "since_then", None),
    (r"^what you own and owe$", "own_owe", None),
    (r"^will your money last\?$", "money_last", None),
    (r"^starting balance$", "start_balance", None),
    (r"^s&p 500 chance your money lasts", "mc_sp_chance", None),
    (r"^s&p 500 (cautious|typical|strong) case", "mc_sp_range", None),
    (r"^chance your money lasts$", "chance", None),
    (r"^cautious case", "cautious", None),
    (r"^typical case", "typical", None),
    (r"^strong case", "strong", None),
    (r"^where your retirement spending comes from$", "spending_sources", None),
    (r"^total asset over time", "trend", None),
    (r"^net liquid asset over time", "liquid_trend", None),
    (r"^summary insight$", "insight", None),
    (r"income covers expenses$", "coverage", None),
    (r"^liquid share of net worth$", "liquid_share", None),
    (r"^debt-to-asset ratio$", "debt_ratio", None),
    (r"^asset allocation by category", "asset_alloc", None),
    (r"^expenses by category", "expense_chart", {"summary.html"}),
    (r"^data check", "data_check", None),
    (r"^what should i do next\?$", "next_steps", None),
    # Assets / real estate
    (r"^assets$", "assets_card", {"asset.html"}),
    (r"^liabilities$", "liabilities", {"asset.html"}),
    (r"^real estate$", "re_card", {"real-estate.html"}),
    (r"^what if i sold\?", "re_sell", None),
    # Linked accounts and positions
    (r"^linked accounts \(live", "linked_accounts", None),
    (r"^(assets|liabilities) by (institution|account type)", "la_group", {"linked-accounts.html"}),
    (r"^linked positions \(live", "positions", None),
    (r"^portfolio check-up$", "checkup", None),
    (r"^positions by (type|institution|sector|industry)", "pos_charts", None),
    # Risk
    (r"^how much risk are you comfortable with\?", "risk_level", None),
    (r"^your mix today", "mix_today", None),
    (r"^(stocks|bonds|cash|other)$", "mix_class", {"rebalance.html"}),
    (r"^your mix by institution", "mix_inst", None),
    (r"^what to do in each account", "what_to_do", None),
    # Income & expenses
    (r"^income & expenses$", "ie_card", {"expense.html"}),
    (r"^\d{4} income$", "ie_income", {"expense.html"}),
    (r"^\d{4} expense need$", "ie_need", {"expense.html"}),
    (r"^\d{4} net withdrawal need$", "ie_withdraw", {"expense.html"}),
    (r"^inflation %$", "inflation", {"expense.html"}),
    (r"^income$", "ie_income_list", {"expense.html"}),
    (r"^expenses$", "ie_expense_list", {"expense.html"}),
    (r"^(income|expenses) by category", "ie_charts", {"expense.html"}),
    # Actual spending
    (r"^total real (expenditure|income)$", "real_exp", None),
    (r"^real (expenditure|income) by (category|month)", "real_charts", None),
    (r"^(monthly summary|annual summary|all transactions)$", "real_tables", None),
    # Budget vs actual
    (r"^\d{4} expense budget$|^actual spend so far$|^projected full-year spend$|^spend variance vs budget$", "bva_expense", None),
    (r"^\d{4} income plan$|^actual income so far$|^projected full-year income$|^income variance vs plan$", "bva_income", None),
    (r"^(expense|income): (budgeted|planned) vs actual", "bva_charts", None),
    # Will my money last?
    (r"^when could i retire\?", "mc_what_if", None),
    (r"^how this works$", "mc_how", {"monte-carlo.html"}),
    (r"^what could go wrong\?", "mc_wrong", None),
    (r"^real market history", "mc_sp", None),
    (r"^if you sold your real estate", "mc_sell", {"monte-carlo.html"}),
    (r"^what if markets fall\?", "mc_stress", None),
    (r"^year-by-year detail", "mc_yearly", None),
    (r"^what moves your plan most", "mc_levers", None),
    (r"^saved scenarios", "mc_scenarios", None),
    (r"^assumptions & what-if", "mc_assumptions", None),
    (r"^try a what-if", "mc_whatif", None),
    (r"^your assumptions", "mc_assump_saved", None),
    (r"^(tax-deferred \(401k|roth \(tax-free|taxable \(brokerage|real estate \(opted in|total$)", "dd_pool_tile", {"drawdown-planning.html"}),
    (r"^resources by tax bucket", "dd_pools", None),
    (r"^required minimum distributions", "dd_rmd", None),
    (r"^split a linked account", "dd_split", None),
    (r"^withdrawal order$", "dd_order", None),
    (r"^if you sold your real estate", "dd_sell", {"drawdown-planning.html"}),
    (r"^year-by-year withdrawal sequence", "dd_sequence", None),
    (r"^your plan for \d{4}$", "dd_year", {"drawdown-planning.html"}),
    (r"^which account should i take it from", "dd_best", None),
    # Legacy
    (r"^your plan for \d{4}", "lg_card", {"legacy-planning.html"}),
    (r"^if you sold your real estate", "mc_sell", {"legacy-planning.html"}),
    (r"^heir assumptions", "lg_heirs", None),
    (r"^strategy comparison", "lg_compare", None),
    (r"^try your own strategy", "lg_own", None),
    (r"^year-by-year: ", "lg_year", None),
    # Setup
    (r"^household$", "su_household", None),
    (r"^sample data$", "su_sample", None),
    (r"^plaid api keys$", "su_plaid_keys", None),
    (r"^connect an account$", "su_connect", None),
    (r"^security$", "su_security", None),
    (r"^view-only login$", "su_viewer", None),
    (r"^about, protection and updates$", "su_about", None),
    (r"^move to another mac$", "su_transfer", None),
    (r"^data & output locations$", "su_locations", None),
    (r"^category rules$", "su_rules", None),
    (r"^automatic sync$", "su_autosync", None),
    (r"^property value estimates", "su_rentcast", None),
    (r"^network access", "su_network", None),
    (r"^quit ", "su_quit", None),
]
# A tile on the Monte Carlo tab with the same label as the Summary's means the same thing.
_COMPILED = [(re.compile(rx), key, pages) for rx, key, pages in RULES]

_TEXT_HEAD = re.compile(r"(<(h[23])\b[^>]*>)(.*?)(</\2>)", re.S)
_TEXT_LABEL = re.compile(r'(<div class="label">)(.*?)(</div>)', re.S)
_TAGS = re.compile(r"<[^>]+>")


def _norm(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub("", fragment))).strip().lower()


def key_for(text: str, page: str) -> str | None:
    """The explanation key for a title/label on a page, or None."""
    t = _norm(text)
    for rx, key, pages in _COMPILED:
        if (pages is None or page in pages) and rx.search(t):
            return key
    return None


def annotate(body: str, page: str) -> tuple[str, list[list[str]]]:
    """Finds the card titles and tile labels on this page that have an
    explanation. The page's own HTML is left exactly as it is; the browser
    adds the "i" buttons next to the matching titles (see _JS). Returns
    (body, [[normalized title text, key], ...])."""
    targets: dict[str, str] = {}
    for m in _TEXT_HEAD.finditer(body):
        text = _norm(m.group(3))
        key = key_for(text, page)
        if key and key in _E:
            targets.setdefault(text, key)
    for m in _TEXT_LABEL.finditer(body):
        text = _norm(m.group(2))
        key = key_for(text, page)
        if key and key in _E:
            targets.setdefault(text, key)
    return body, [[t, k] for t, k in targets.items()]


_LONG_P = re.compile(r'<p class="(muted[^"]*)"([^>]*)>(.*?)</p>', re.S)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z<(])")
_MIN_LONG_TEXT = 150
_MAX_SHORT_TEXT = 170


def _short_version(raw: str) -> str:
    """The first sentence of a paragraph's HTML (links kept), or a trimmed
    plain-text start when that sentence is itself very long."""
    first = _SENTENCE_END.split(raw, maxsplit=1)[0]
    plain = _norm_case(first)
    if len(plain) <= _MAX_SHORT_TEXT:
        return first.strip()
    cut = plain[:_MAX_SHORT_TEXT].rsplit(" ", 1)[0].rstrip(",;:")
    return html.escape(cut) + "&hellip;"


def _norm_case(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub("", fragment))).strip()


def condense(body: str) -> tuple[str, dict[str, dict]]:
    """Long grey explanatory paragraphs get a one-sentence twin in front of
    them, with an "i" button that opens the whole text in the same pop-up the
    other "i" buttons use. The original paragraph is left byte-for-byte as it
    was; the page's view setting (simple/full) decides which one is shown --
    see the .tx-short rules in the page CSS. Returns (body, extra pop-up
    entries keyed "tx:N")."""
    extras: dict[str, dict] = {}

    def repl(m: re.Match) -> str:
        text = _norm_case(m.group(3))
        if len(text) < _MIN_LONG_TEXT:
            return m.group(0)
        key = f"tx:{len(extras) + 1}"
        extras[key] = {"title": "More detail", "what": text, "read": "", "do": ""}
        short = _short_version(m.group(3))
        twin = (
            f'<p class="muted tx-short">{short} '
            f'<button type="button" class="ex-btn" data-ex="{key}" aria-label="Read the full explanation" title="Read more">i</button></p>'
        )
        return twin + m.group(0)

    return _LONG_P.sub(repl, body), extras


def page_button_html(page: str) -> str:
    key = f"page:{page}"
    if key not in _E:
        return ""
    tour = (' <button type="button" class="ex-btn ex-page-btn" onclick="startTour()">Take a quick tour</button>'
            if page == "summary.html" else "")
    from source.webapp.pages.tutorial import chapter_link_html
    return ('<div class="ex-pagebar"><button type="button" class="ex-btn ex-page-btn" data-ex="'
            f'{html.escape(key, quote=True)}">i&nbsp; About this page</button>{tour}{chapter_link_html(page)}</div>')


_CSS = """
<style>
  .ex-btn { display:inline-flex; align-items:center; justify-content:center; width:17px; height:17px; margin-left:6px; padding:0;
    border-radius:50%; border:1px solid var(--ink-muted, #6e6e73); background:transparent; color:var(--ink-muted, #6e6e73);
    font:italic 700 11px/1 Georgia, serif; cursor:pointer; vertical-align:middle; text-transform:none; letter-spacing:0; box-shadow:none; }
  .ex-btn:hover, .ex-btn:focus-visible { background:var(--brand, #0071e3); border-color:var(--brand, #0071e3); color:#fff; outline:none; }
  .ex-pagebar { text-align:right; margin:0 0 6px; }
  .ex-watch { display:inline-block; margin-left:6px; padding:4px 11px; border-radius:999px; border:1px solid var(--brand, #0071e3);
    background:var(--brand, #0071e3); color:#fff !important; font:600 12px/1.2 -apple-system, "Inter", sans-serif; text-decoration:none; }
  .ex-watch:hover { background:var(--brand-dark, #0059b2); }
  .ex-page-btn { width:auto; height:auto; border-radius:999px; padding:4px 11px; margin:0; font:600 12px/1.2 -apple-system, "Inter", sans-serif; }
  #ex-overlay { position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:100000; display:flex; align-items:center; justify-content:center; padding:18px; }
  #ex-modal { background:var(--surface, #fff); color:var(--ink, #1d1d1f); border:1px solid var(--border, #d2d2d7); border-radius:16px;
    max-width:460px; width:100%; max-height:84vh; overflow:auto; padding:20px 22px; box-shadow:0 20px 50px rgba(0,0,0,.35); }
  #ex-modal h3 { margin:0 0 10px; font-size:17px; }
  #ex-modal h4 { margin:12px 0 2px; font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--ink-muted, #6e6e73); }
  #ex-modal p { margin:0; font-size:14px; line-height:1.45; }
  #ex-modal .ex-close { margin-top:16px; width:100%; }
</style>
"""

_JS = """
<script>
(function() {
  var all = JSON.parse(document.getElementById('ex-data').textContent), data = all.entries, last = null;
  var want = {}; all.targets.forEach(function(t) { want[t[0]] = t[1]; });
  function norm(s) { return s.replace(/\\s+/g, ' ').trim().toLowerCase(); }
  document.querySelectorAll('h2, h3, div.label').forEach(function(el) {
    var key = want[norm(el.textContent)];
    if (!key || el.querySelector('.ex-btn')) return;
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'ex-btn'; b.setAttribute('data-ex', key);
    b.setAttribute('aria-label', 'What is this? ' + data[key].title); b.title = 'What is this?'; b.textContent = 'i';
    el.appendChild(document.createTextNode(' ')); el.appendChild(b);
  });
  function esc(s) { return String(s).replace(/[&<>"]/g, function(c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function close() {
    var o = document.getElementById('ex-overlay'); if (o) o.remove();
    document.removeEventListener('keydown', onKey);
    if (last) { try { last.focus(); } catch (e) {} }
  }
  function onKey(e) { if (e.key === 'Escape') close(); }
  function open(key, from) {
    var d = data[key]; if (!d) return;
    close(); last = from;
    var o = document.createElement('div'); o.id = 'ex-overlay';
    var html = '<div id="ex-modal" role="dialog" aria-modal="true" aria-labelledby="ex-title"><h3 id="ex-title">' + esc(d.title) + '</h3>' +
      (key.indexOf('tx:') === 0 ? '' : '<h4>What it is</h4>') + '<p>' + esc(d.what) + '</p>';
    if (d.read) html += '<h4>How to read it</h4><p>' + esc(d.read) + '</p>';
    if (d.do) html += '<h4>What you can do</h4><p>' + esc(d['do']) + '</p>';
    html += '<button type="button" class="primary ex-close">Got it</button></div>';
    o.innerHTML = html;
    o.addEventListener('click', function(e) { if (e.target === o) close(); });
    o.querySelector('.ex-close').addEventListener('click', close);
    document.body.appendChild(o);
    document.addEventListener('keydown', onKey);
    o.querySelector('.ex-close').focus();
  }
  document.addEventListener('click', function(e) {
    var b = e.target.closest && e.target.closest('.ex-btn'); if (!b) return;
    e.preventDefault(); e.stopPropagation(); open(b.getAttribute('data-ex'), b);
  });
})();
</script>
"""


def assets_html(page: str, targets: list[list[str]], extra: dict | None = None) -> str:
    """The pop-up's style, this page's explanations and title list, and its script."""
    keys = {k for _t, k in targets}
    if f"page:{page}" in _E:
        keys.add(f"page:{page}")
    extra = extra or {}
    if not keys and not extra:
        return ""
    entries = {k: _E[k] for k in sorted(keys)}
    entries.update(extra)
    payload = json.dumps({"entries": entries, "targets": targets}).replace("</", "<\\/")
    return f'{_CSS}<script type="application/json" id="ex-data">{payload}</script>{_JS}'


def all_keys() -> set[str]:
    return set(_E)
