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
