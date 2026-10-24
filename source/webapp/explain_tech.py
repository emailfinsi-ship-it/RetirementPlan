"""The "Technical detail" part of the "i" pop-ups.

Each entry adds a collapsible section under the plain explanation in
explain.py, for people who want to know exactly how a number is produced:
how it is calculated, what is assumed or left out, where its inputs come from,
and what the financial terms mean. The text is written from the code itself
(source/reporting/...), so when a calculation changes, change its entry here.

Keys match explain._E; headings are fixed so every pop-up reads the same way.
Technical text is never run through the plain-words rewrite: it stays precise
in both wording modes.
"""

from __future__ import annotations

from source.reporting import presentation as pres

HOW, LIMITS, SOURCE, TERMS = "How it is calculated", "Assumptions and limits", "Where the numbers come from", "Terms"

_ON = f"{pres.ON_TRACK_AT * 100:.0f}%"
_REVIEW = f"{pres.REVIEW_AT * 100:.0f}%"

TECH: dict[str, list[tuple[str, str]]] = {}


def _t(key: str, *, how: str = "", limits: str = "", source: str = "", terms: str = "") -> None:
    TECH[key] = [(h, t) for h, t in ((HOW, how), (LIMITS, limits), (SOURCE, source), (TERMS, terms)) if t]


# ---------------------------------------------------------------- Summary

_t("plan_status",
   how=f"The status is a threshold on the success rate of the Monte Carlo run: {_ON} or more is On track, {_REVIEW} to under {_ON} is "
       f"Worth a second look, under {_REVIEW} is Needs attention. The success rate is 1 minus (paths that ran out of money / paths simulated).",
   limits="The thresholds are rules of thumb, not a standard. A path counts as failed the first year the balance reaches zero; "
          "there is no borrowing and no partial credit for how close it came.",
   source="Same simulation as the 'Will my money last?' tab (same seed, so the two always agree).")
_t("net_worth",
   how="Net worth = investments and savings + real estate at full market value + other assets - mortgages and property loans - other debts. "
       "Home equity is counted in full for every property, whether or not it is 'In the plan?'.",
   limits="Values are as last entered or last synced; real estate has no live pricing unless a property-value estimate is set up in Setup. "
          "Illiquid items (a home, a business) are included at the value you entered.",
   source="Assets & Debts and Real Estate tabs; a row linked to a Plaid account uses the live balance instead of the typed one.")
_t("investable",
   how="Investable savings = the sum of asset rows ticked 'In the plan?' (grouped Tax-deferred, Roth, Taxable) minus liabilities. "
       "Property equity is a separate pool and appears only when ticked on the Real Estate tab.",
   limits="Liabilities are netted against the pools before the simulation starts, so a debt reduces the starting balance rather than being paid as a yearly expense.",
   source="Assets & Debts tab ('In the plan?' and 'Tax treatment' columns).",
   terms="Tax-deferred: 401(k)/traditional IRA, taxed as ordinary income when withdrawn. Roth: withdrawals are tax-free. Taxable: brokerage, taxed on gains.")
_t("yearly_spending",
   how="The sum of Expense rows that cover next year. A row with 'Inflates' set grows from its Base Year at the plan's inflation rate: "
       "amount x (1 + inflation)^(year - base year). Rows outside their start/end years count as zero.",
   limits="This is gross spending before income is subtracted and before any estimated tax. One-time costs need their own start and end year.",
   source="Income & Expenses tab, Expenses list; inflation rate from the Assumptions form.")
_t("fi",
   how="Target = 25 x (next year's spending - income that has already started, capped at spending). Progress = savings / target. "
       "The 'about when' date solves savings x (1 + real return)^n = target for n, where real return = (1 + expected return) / (1 + inflation) - 1, "
       "adding nothing new.",
   limits="25x is the inverse of the 4% rule, which was derived from US historical returns over 30-year retirements. Income that starts later "
          "(for example Social Security at 67) is left out on purpose, which keeps the target a little high. No taxes are modeled in this figure. "
          "Home equity you did not tick 'In the plan?' is shown as a cushion and never added to savings.",
   source="Investable savings, the Expenses list and Income rows ticked 'In simulation?'.",
   terms="Financial independence (FI): savings large enough that a sustainable withdrawal covers your spending.")
_t("safe_spend",
   how="Every Expense row is scaled by one factor, then the simulation is re-run and the factor is found by bisection (7 halving steps between 0.2x and 3x) "
       "so the success rate is just at or above your chosen confidence (default 90%). The answer is today's yearly spending x that factor. "
       "Every probe reuses the same random market paths, so the answer moves smoothly instead of jittering.",
   limits="It scales all spending proportionally, so it cannot tell which category to cut. It uses 400 paths, so it can differ from the main run by a point or two. "
          "If even 3x spending still clears the target, or even 0.2x cannot, the answer is capped at that limit and the card says so.",
   source="Same inputs as the plan check; the confidence level is set on the 'Will my money last?' tab.")
_t("since_then",
   how="Compares today with the daily snapshot nearest 30 days ago (or the oldest snapshot if there is less than 30 days of history, as long as it is at least 2 days old). "
       "The change is split into investments, other assets and home equity, with the accounts that moved most listed.",
   limits="Needs at least two days of history. A big move in one account is usually a market move, a deposit, a withdrawal or a changed typed balance, and the snapshots cannot tell these apart.",
   source="net_worth_snapshots and asset_balance_snapshots, written once a day when the app runs.")
_t("own_owe",
   how="Own = investments and savings + real estate (market value) + other assets. Owe = mortgages and property loans + other debts. Net worth = own - owe. "
       "Mortgages are shown against the property's full value; the plan itself uses equity.",
   limits="Ownership % on a property scales your share of the loan in 'your share'; the market value shown is the full value.",
   source="Assets & Debts and Real Estate tabs.")
_t("data_check",
   how="A fixed list of rule checks run on every Summary load: margin loans tagged, negative holdings, funds with a mismatched sector tag, taxable holdings with no cost basis, "
       "stale sync, assets with no tax type, Social Security possibly counted twice, retirement money held mostly by one spouse, flat-rent properties, rows that end before they start, "
       "rows with a zero amount, and backup age/health. Each returns a warning or an info item.",
   limits="These are consistency checks, not proof of an error. A flagged item can be intentional; use 'Clear these tags' or fix the row.",
   source="Linked positions, line items and the latest backup.")
_t("next_steps",
   how="Each possible action gets a score: the chance of lasting (100 if under 70%, 90 if under 85%), data-check warnings (80), missing plan inputs (75 warn / 20 info), "
       "concentration (50), mix drift (55) and the Social Security claiming prompt (40). They are sorted by score and the top three are shown.",
   limits="A heuristic ranking, not advice. Scores are fixed in code (source/reporting/advice.py).",
   source="Plan check, data check, plan health items and the portfolio check-up.")
_t("alerts",
   how="Alerts fire when: the chance of lasting fell 5 percentage points or more versus about a week ago; the chance is under 70%; a data-check item is a warning; "
       "a holding or sector is flagged too concentrated; or the biggest asset-class gap from your target mix is 10 points or more.",
   limits="Checked when the app runs. Email and Mac notifications need to be switched on in Setup. Dismissed alerts stay dismissed until their condition clears and returns.",
   source="Plan-check history kept once a day, linked positions and your target mix.")
_t("trend",
   how="One point per day: the total of assets recorded by the daily snapshot. Liquid assets exclude property.",
   limits="History starts the day the app first ran; a gap means the app was not opened that day. Typed balance edits show up as jumps.",
   source="The net_worth_snapshots table, written by the app's daily capture.")

# ----------------------------------------------------- Simulation results

_t("money_last",
   how="Each of N paths (default 1,000) draws a yearly return from a normal distribution with your expected return and volatility, applies it to the balance, then subtracts that year's net withdrawal need. "
       "The shaded band shows the 10th to 90th percentile of the combined balance each year and the solid line the median.",
   limits="One blended return applies to all accounts, with no separate stock/bond model. Returns are independent year to year (no streaks or mean reversion), "
          "which understates how long real bear markets last. A path that hits zero stays at zero. Results are seeded from your inputs, so reopening the page gives the same answer.",
   source="Assumptions form (expected return, volatility, inflation, horizon, iterations); Assets, Income and Expenses tabs.",
   terms="Percentile: the 10th percentile is the value that 10% of paths fall below. Volatility: the standard deviation of yearly returns.")
_t("start_balance",
   how="Starting balance = the sum of the Tax-deferred, Roth and Taxable pools (rows ticked 'In the plan?', net of liabilities) + the Real estate pool (equity of properties ticked 'In the plan?').",
   limits="The real estate pool is spent last and has no tax modeled. Pools are rolled forward with one return, so the split matters only for taxes and required withdrawals.",
   source="Assets & Debts and Real Estate tabs.")
_t("chance",
   how="Chance = 1 - (paths where the balance hit zero before the end of the plan / paths simulated). A path counts as failed the first year any shortfall remains after drawing from every pool.",
   limits=f"It depends heavily on the assumed return and volatility; a 1-point change in expected return can move it by several points. Over {_ON} is the usual rule of thumb, not a guarantee. "
          "Spending is fixed to your rows; real retirees adjust spending, which this does not model.",
   source="Simulation inputs listed under 'Will your money last?'.")
_t("cautious",
   how="The 10th percentile of ending balances: sort every path's final balance and take the value 10% of the way up. Shown in today's dollars or future dollars per the toggle.",
   limits="Zero means 10% or more of paths ran out. It is a percentile of the whole distribution, not the worst case.",
   terms="P10: the 10th percentile, the label used for this case in the year-by-year detail table.")
_t("typical", how="The median (50th percentile) ending balance across paths, in today's dollars or future dollars per the toggle.",
   limits="Today's dollars divide each future figure by (1 + inflation)^(years from now).")
_t("strong", how="The 90th percentile of ending balances: 10% of paths ended higher.",
   limits="Not a forecast. It exists to show the width of the range.")
_t("spending_sources",
   how="A deterministic year-by-year projection (no randomness) at your expected return: for each year it applies required minimum distributions, then draws the rest of the spending need Taxable first, then Tax-deferred, then Roth, then property equity. "
       "The dashed line is that year's spending plus estimated tax.",
   limits="A single smooth return path, so it shows the shape of the plan, not a market that falls early. Withdrawals beyond spending (a required distribution larger than you need) are reinvested and not drawn as bars.",
   source="Drawdown Planning engine, same as that tab's year-by-year table.")
_t("mc_how",
   how="Monte Carlo simulation: many random market histories are run against the same spending plan and the share that survive is reported. Each year: grow every pool by that year's return, "
       "take required minimum distributions, draw the remaining need in order, then pay the tax on those withdrawals out of the pools too.",
   limits="Historical bootstrap and recession replays on this tab test the same plan against real returns instead of a bell curve.")
_t("mc_wrong",
   how="Shows the stress tests and the one-lever-at-a-time sweep side by side: see 'What if markets fall?' and 'What moves your plan most' for the method.",
   limits="Only the cases listed are tested; combined bad luck is worse than any single one.")
_t("mc_sp",
   how="Instead of a normal distribution, each simulated year draws (with replacement) one of the recorded annual S&P 500 total returns (dividends reinvested). This is a historical bootstrap.",
   limits="It uses a US large-cap stock index only, for all accounts, so a portfolio with bonds will have lower returns and lower volatility than this assumes. Years are drawn independently, so sequences of crashes are no more likely than in the normal model.",
   source="The recorded series is built into the program (source/reporting/monte_carlo/stress_test.py).")
_t("mc_sp_chance", how="The share of bootstrap paths that never ran out of money, from the same withdrawal schedule as the main run.",
   limits="Compare it with the main chance: a large gap means the plan's result depends on the assumed return and volatility.")
_t("mc_stress",
   how="A deterministic replay: the same starting balance and withdrawal schedule, but yearly returns taken from the real S&P 500 sequence beginning in 1929, 2000, 2007 and 1973, plus two flat lines (your expected return, and the S&P average over the last N years where N is your plan horizon). "
       "Tax and required withdrawals are recomputed along each path.",
   limits="Each scenario starts at the first year of your plan, whatever your actual retirement year. Years after the recorded history ends use a 10% placeholder. Spending does not adjust to the crash.",
   source="The recorded annual S&P 500 returns and replay logic in source/reporting/monte_carlo/stress_test.py.")
_t("mc_yearly",
   how="For each year and scenario: return applied, tax, total withdrawal (need + tax) and ending balance. Total expense - total income - any flat income offset = yearly drawdown need.",
   limits="Rows before your retirement year are hidden but still walk the balance forward.")
_t("mc_levers",
   how="A tornado sweep: the full simulation is re-run with one lever changed down and up (expected return +/-1 point, volatility +/-2 points, inflation +/-1 point, plan horizon +/-5 years, expenses +/-10%, income +/-10%) with everything else fixed. "
       "The swing is the larger absolute change in success rate. Each variant is seeded from its own inputs.",
   limits="Levers are tested one at a time, in fixed amounts, so the ranking says which assumption the plan is most fragile to, not how likely each change is.")
_t("mc_assumptions",
   how="The inputs: expected return and volatility (the normal distribution each year), inflation (grows rows set to inflate and the tax brackets), plan horizon (years simulated), iterations (paths), "
       "birth year and retirement year (when spending starts and required withdrawals begin), an optional flat income offset, taxable gains % and whether to apply drawdown tax.",
   limits="Changing any value changes the random seed, so a tiny change can shift the result slightly even when it should not matter.")
_t("mc_whatif",
   how="Re-runs the simulation with the changes you enter and reports the new chance and the difference from the base run at the same path count.",
   limits="300 paths is enough to compare, not to quote; the main figure uses your full path count. Nothing is saved.")
_t("inflation",
   how="Inflation compounds from each row's Base Year: amount x (1 + rate)^(year - base year). The same rate grows the tax brackets and standard deduction in later years.",
   limits="One rate for every category; medical costs and housing often rise faster. Rows without Inflates stay flat.")

# ----------------------------------------------------- Drawdown and legacy

_t("dd_pool_tile",
   how="Each asset row is assigned to Tax-deferred, Roth or Taxable by its Tax treatment. A linked account can be split across buckets by percentage ('Split a linked account'). "
       "The tile is the balance of that bucket now.",
   limits="A linked account's type (401k, IRA, Roth) is detected from Plaid unless you set Tax treatment explicitly; rows with no tax type are flagged by the data check.",
   terms="Tax-deferred: pre-tax contributions, withdrawals are ordinary income. Roth: after-tax, qualified withdrawals tax-free. Taxable: ordinary brokerage, gains taxed.")
_t("dd_pools", how="The balance of each tax bucket, summed from asset rows by their Tax treatment and by any split you set on linked accounts.",
   source="Assets & Debts tab and 'Split a linked account'.")
_t("dd_rmd",
   how="The minimum yearly withdrawal from Tax-deferred accounts once the owner reaches the starting age: balance entering the year / the IRS Uniform Lifetime Table divisor for that age (for example 26.5 at 73, 24.6 at 75, 16.0 at 85). "
       "Starting age is 73 if born 1959 or earlier and 75 if born 1960 or later (SECURE 2.0). Any amount beyond what spending needs is moved into the Taxable pool.",
   limits="Uses the prior-year-end balance approximated as the balance entering the year. Does not model the joint table for a spouse more than 10 years younger. With a spouse, each owner's share of the Tax-deferred balance gets its own required distribution.",
   source="Birth years on the Assumptions form; source/reporting/rmd.py.",
   terms="RMD: required minimum distribution.")
_t("dd_order",
   how="Spending is drawn Taxable first, then Tax-deferred, then Roth, then property equity. Required distributions come out of Tax-deferred first regardless. "
       "If you set an 'early Tax-deferred age', the order becomes Tax-deferred first from that age.",
   limits="This is the common tax-efficient default, not an optimization. The best order depends on brackets, Social Security timing and heirs, which the Legacy tab compares.")
_t("dd_sequence",
   how="One deterministic path at your expected return. Each year: grow pools, take required distributions, draw the rest in order, and compute tax on ordinary income (Tax-deferred draws, taxable income rows) and capital gains (an assumed share of Taxable draws, default 40% gains). "
       "Tax is paid by withdrawing more, which is itself taxed, so the amount is solved by repeated iteration until it settles.",
   limits="Federal and California married-filing-jointly tax tables for 2026, grown by inflation (no law changes), standard deduction $32,200 federal. Not modeled: Social Security taxation specifics, IRMAA, ACA subsidies, state rules other than California, itemized deductions.",
   source="Tax tables in source/reporting/monte_carlo/tax.py.")
_t("dd_year",
   how="Picks this year's row of the schedule and states which pools to draw and how much, with the estimated tax.",
   limits="Estimates at your expected return; actual market moves will change the amounts.")
_t("lg_compare",
   how="The same deterministic projection is replayed once per strategy: no conversions (or your current plan), and converting Tax-deferred to Roth each year up to the top of the 12%, 22%, 24% or 32% federal bracket (or all of it), plus your own what-if. "
       "Room each year = bracket ceiling (grown by inflation) - standard deduction - ordinary income already that year. The conversion is trimmed so its tax can be paid from Taxable. "
       "Net after-tax legacy = Taxable + Roth + Real estate + remaining Tax-deferred net of estimated heir tax. Strategies are ranked by that figure, then by lower lifetime tax.",
   limits="Not modeled: IRMAA surcharges, ACA subsidy loss, state-law changes, spouse death and filing-status change, the 10-year inherited-IRA rule beyond the spread you set. A strategy that depletes your money is flagged rather than hidden. "
          "Results within about 2% of each other are called a close call.",
   source="Heir assumptions, your pools, Income and Expenses.",
   terms="Roth conversion: moving pre-tax money to Roth and paying ordinary tax on it now. Bracket filling: converting only up to the top of a chosen marginal bracket.")
_t("lg_heirs",
   how="The heir's tax on inherited Tax-deferred money is estimated by spreading it evenly over the number of years you choose and stacking it on the heir's assumed other income, using the same bracket tables.",
   limits="The default heir income is your own plan's current net yearly drawdown need (expenses minus income), floored at zero, as a stand-in. Real heirs differ; adjust the income and years to match.")
_t("lg_own", how="Adds one more row to the comparison using the bracket you pick, an optional yearly dollar cap (today's dollars, grown by inflation) and an optional age after which conversions stop.",
   limits="There is no 25% federal bracket: use the cap to land between two brackets.")
_t("lg_card", how="The first year of the top-ranked strategy: how much to withdraw from each pool for spending, and how much to convert, with the tax it costs paid from Taxable.",
   limits="Conversions are applied after required distributions, which cannot be satisfied by a conversion.")

# --------------------------------------------------------- Risk and mix

_t("risk_level",
   how="Stocks % = 110 - age, shifted by the level (Conservative -25, Moderate 0, Growth +10, Aggressive +20), then kept between 20% and (100 - cash)%. Cash is 10, 5, 5 and 3% respectively; the rest is bonds. "
       "The 'worst year' figure is about 0.37 x stocks - 0.05 x bonds, a 2008-style drop (stocks -37%, bonds +5%).",
   limits="An age rule of thumb, not a personal recommendation. With no birth year set it assumes a base of 60% stocks.",
   source="Birth year on the Assumptions form.")
_t("mix_today",
   how="Each linked holding is classified Stocks, Bonds, Cash or Other from its security type and name (bond, treasury, money market and similar words), with your manual overrides taking priority. "
       "Order of tests: your override; type 'cash'; a 'bond' or 'fixed income' sector tag; bond type; for stocks, ETFs and mutual funds a name with target-date, lifecycle or balanced words becomes Other and a name with bond words becomes Bonds; everything else of stock type is Stocks; anything unrecognized is Other.",
   limits="Classification is by label, not by looking through a fund's holdings, so a fund can be mislabeled (override it on this tab). A gap of 5 points or more from target is called drift.",
   source="Linked Positions and the target mix saved on this tab.")
_t("positions",
   how="Live holdings pulled from Plaid investment accounts: quantity, price, value and cost basis where the institution reports it.",
   limits="Prices are as of the last sync, not real time. Some brokers omit cost basis, which limits gain figures and tax-aware suggestions.",
   source="Plaid investments endpoint, synced on 'Sync now' and by auto-sync.")
_t("linked_accounts",
   how="Balances pulled from Plaid for every linked account; a row on the Assets tab can be linked so its balance follows the account.",
   limits="Liability balances are shown as amounts owed whatever sign the bank uses. Balances can lag the bank by a day.",
   source="The balances Plaid reports for each linked account, refreshed by Sync now.")

# --------------------------------------------------------- Pages

_t("page:monte-carlo.html",
   how="Everything here derives from one model: yearly returns, spending and income by row, taxes from 2026 federal and California brackets, three tax pools drawn in order, required distributions, and an optional property-equity pool.",
   limits="The model is deterministic for given inputs (seeded), so the same plan always shows the same figures.")
_t("page:stock-analysis.html",
   how="The watchlist makes two Alpaca calls for the whole list: today's snapshot for every ticker, and about 14 months of daily bars. RSI, trends, the 52-week range and the rating are then worked out from those bars here, the same way as in Quote and chart.",
   limits="Prices are from Alpaca's free IEX feed, so volume is IEX's share of the market and quotes can differ slightly from other sources. Outside market hours you see the last close.",
   source="Alpaca market data, read with the keys saved on the Trading tab (practice keys first). Only the ticker list and your notes are stored in this app.")
_t("page:drawdown-planning.html",
   how="A single projection at your expected return showing which pool each year's spending comes from and the estimated tax.",
   limits="See 'Year-by-year withdrawal sequence' for what is and is not modeled.")
_t("page:legacy-planning.html",
   how="Compares Roth-conversion strategies by the after-tax value left to heirs, using the Drawdown engine for each.",
   limits="See 'Strategy comparison' for the method and omissions.")

# --------------------------------------------------------- Trading quotes

_t("tr_quote",
   how="Daily bars (about 14 months, split-adjusted) and a live snapshot are read from Alpaca. Moving averages are simple averages of the last 20, 50 and 200 closes. "
       "RSI(14) is Wilder's: average gain divided by average loss over 14 days, smoothed as (previous x 13 + new) / 14, then scaled to 0-100 (30 or less is called oversold, 70 or more overbought). "
       "MACD is the 12-day exponential average minus the 26-day, with a 9-day average of that as its signal line. "
       "The rating gives each signal +1 (bullish), 0 or -1 (bearish): price above or below each of the 20, 50 and 200-day averages, the 20-day above or below the 50-day, "
       "RSI (oversold +1, overbought -1), MACD above or below its signal line, and a volume spike (1.5x the 20-day average or more) on an up day (+1) or a down day (-1). "
       "Rating = votes / signals counted: 0.6 or more Strong Buy, 0.25 or more Buy, above -0.25 Hold, above -0.6 Sell, otherwise Strong Sell. "
       "A trend is Up when the price is above its average and the average has risen over the last five days, Down for the reverse, otherwise Sideways. "
       "Day range uses today's low and high; the 52-week range uses the last year of daily highs and lows. On the 1D chart the line is VWAP, the running average price weighted by volume.",
   limits="Technical signals only: they describe past prices and say nothing about a company's earnings, news or value, and they often disagree with each other, which is why the rating is a count. "
          "RSI treats a strong run as overbought, so a stock in a powerful uptrend can show a lower rating than its trend suggests. "
          "Prices and volume come from Alpaca's free IEX feed, which covers IEX's own trades only: prices track the market closely but volume is a small share of the true total, "
          "and quotes can differ from other sites by a few cents. The 200-day signal needs about 200 trading days of history, so new listings omit it. "
          "A chart is not an order: nothing here places or changes a trade.",
   source="Alpaca market-data API (bars and snapshot), read with your saved keys; nothing is stored.",
   terms="SMA: simple moving average. RSI: relative strength index. MACD: moving average convergence divergence. VWAP: volume-weighted average price. IEX: the exchange whose data feed is free.")
