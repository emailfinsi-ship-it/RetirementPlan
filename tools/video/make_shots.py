"""Takes the user-guide pictures (light mode, made-up sample household and made-up broker data) into /tmp/shots11.

    PYTHONPATH=. python3 tools/video/make_shots.py

The first-launch pictures (welcome, recovery key, wizard, Plaid keys) are kept from the earlier set; these are every other screen."""

import asyncio
import contextlib
import os
import unittest
from datetime import date, timedelta

from playwright.async_api import async_playwright

from source.common import db, demo_data
from tests.test_dashboard import DashboardTestCase
from tools.video import fakes

OUT = "/tmp/shots11"
PAGES = [("01-summary", "/summary.html"), ("02-assets", "/asset.html"), ("03-real-estate", "/real-estate.html"), ("04-accounts", "/linked-accounts.html"),
         ("05-positions", "/linked-positions.html"), ("06-risk", "/rebalance.html"), ("07-income-expenses", "/expense.html"),
         ("08-will-it-last", "/monte-carlo.html"), ("09-drawdown", "/drawdown-planning.html"), ("10-legacy", "/legacy-planning.html"),
         ("11-setup", "/setup.html"), ("13-actual-spending", "/real-expenditure.html"), ("14-budget-vs-actual", "/budget-vs-actual.html"),
         ("15-alpaca", "/trading-live.html"), ("16-etrade", "/etrade.html"), ("17-ibkr", "/ibkr.html"), ("18-stock-analysis", "/stock-analysis.html"),
         ("19-screener", "/screener.html"), ("20-orders", "/orders.html"), ("21-tutorial", "/tutorial.html")]


class T(DashboardTestCase):
    def test_shots(self):
        os.makedirs(OUT, exist_ok=True)
        for weeks_ago in range(52, -1, -4):
            growth = 1.0 - 0.11 * (weeks_ago / 52) + (0.012 if weeks_ago % 8 == 0 else -0.006) * (weeks_ago / 52)
            nw = 4_170_000 * growth
            db.record_snapshot(net_worth=nw, manual_asset_total=nw - 940_000 * growth, linked_asset_total=0.0, liability_total=0.0,
                               real_estate_equity_total=940_000 * growth, retirement_liquid_total=3_230_000 * growth,
                               snapshot_date=(date.today() - timedelta(weeks=weeks_ago)).isoformat())
        db.set_tour_seen(True)
        db.set_wording_mode("plain")
        demo_data.seed_sample_household(with_linked=True)
        db.set_view_mode("full")
        fakes.seed_orders()
        db.watchlist.add(["MSFT", "KO", "JPM", "VTI"])
        db.live_trading.arm(db.live_trading.CONFIRM_PHRASE, stay_on=True)

        async def run():
            with contextlib.ExitStack() as stack:
                fakes.install(stack)
                async with async_playwright() as p:
                    b = await p.chromium.launch()
                    ctx = await b.new_context(color_scheme="light", viewport={"width": 1280, "height": 800})
                    await fakes.broker_routes(ctx)
                    pg = await ctx.new_page()
                    pg.set_default_timeout(60000)
                    pg.on("pageerror", lambda e: print("PAGE ERROR:", e))
                    for name, path in PAGES:
                        await pg.goto(f"http://127.0.0.1:{self.port}{path}", wait_until="load")
                        await pg.wait_for_timeout(2500)
                        if name == "05-positions":
                            await pg.click("#hr-go")
                            await pg.wait_for_selector("#hr-table tbody tr", timeout=90000)
                            await pg.locator("#holdings-review").screenshot(path=f"{OUT}/05b-review-holdings.png")
                        if name == "15-alpaca":
                            await pg.locator(".trade-btn").first.evaluate("e => e.scrollIntoView({block: 'center'})")
                            await pg.locator(".trade-btn").first.evaluate("e => e.click()")
                            await pg.wait_for_timeout(500)
                            await pg.locator("#trade-menu").screenshot(path=f"{OUT}/15b-trade-menu.png")
                            await pg.keyboard.press("Escape")
                        if name == "16-etrade":
                            await pg.wait_for_selector(".lot-toggle", timeout=30000)
                            await pg.locator(".lot-toggle").first.click()
                            await pg.wait_for_selector("tr.bk-lot", timeout=15000)
                        if name == "18-stock-analysis":
                            await pg.fill("#quote input", "NVDA")
                            await pg.locator("#quote button:has-text('Look up')").first.click()
                            await pg.wait_for_timeout(3500)
                            await pg.locator("summary:has-text('Watchlist')").first.click()
                            await pg.wait_for_timeout(3000)
                        if name == "19-screener":
                            await pg.fill("#sc-text", "technology stocks that moved at least 5% this month")
                            await pg.click("#sc-find")
                            await pg.wait_for_timeout(2000)
                            await pg.select_option("select[name=sort]", "rating")
                            await pg.click("#sc-run")
                            await pg.wait_for_selector("#sc-result-card table tbody tr", timeout=90000)
                            await pg.wait_for_timeout(1500)
                        await pg.evaluate("window.scrollTo(0, 0)")
                        await pg.screenshot(path=f"{OUT}/{name}.png", full_page=True)
                        print("shot", name)
                    await b.close()
        asyncio.run(run())


unittest.main(argv=["x", "T"])
