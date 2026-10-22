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

## Plain / Technical wording
A **Wording** button in the header (next to Theme) switches every page between everyday words
(the default) and the full financial wording. Page names never change and no number changes.
The words live in `source/webapp/plain_rules.py`; `source/webapp/wording.py` applies them.
Grammar fixes apply in both modes (proper dash, "Total assets over time", "an 11.0%", and more).
