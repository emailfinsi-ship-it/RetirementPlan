"""Plain / Technical wording: the switch, the rewrite engine, the rule table and
the grammar fixes that apply in both modes."""

from __future__ import annotations

import html
import json
import re
import unittest
from unittest.mock import patch

from source.common import db, demo_data
from source.reporting import presentation
from source.reporting.portfolio_checkup import portfolio_checkup
from source.webapp import explain, plain_rules, wording
from source.webapp.pages import legacy_planning
from source.webapp.render_helpers import shell
from tests.test_dashboard import DashboardTestCase


def _plain(fragment: str) -> str:
    """The page fragment as plain mode would show it."""
    with patch.object(wording, "is_plain", return_value=True):
        return wording.plain_html(fragment)


def _apply(kind: str, old: str, new: str, text: str) -> str:
    rule = wording.compile_rule(kind, old, new)
    return rule.pattern.sub(lambda m: wording._render(rule, m, html_mode=True), text)


class TestTypography(unittest.TestCase):
    def test_spaced_double_hyphen_becomes_a_dash(self):
        self.assertEqual(wording.fix_typography("<p>one -- two</p>"), "<p>one — two</p>")

    def test_style_blocks_are_left_alone(self):
        css = "<style>:root { --bg: #fff; } a { color: var(--bg) }</style><p>x -- y</p>"
        self.assertEqual(wording.fix_typography(css), css.replace("x -- y", "x — y"))

    def test_hyphens_inside_words_are_left_alone(self):
        self.assertEqual(wording.fix_typography("<p>a--b and a --c</p>"), "<p>a--b and a --c</p>")


class TestGrammar(unittest.TestCase):
    def test_a_or_an_before_a_rate(self):
        self.assertEqual(legacy_planning._a_an("11.0"), "an")
        self.assertEqual(legacy_planning._a_an("18.5"), "an")
        self.assertEqual(legacy_planning._a_an("8.0"), "an")
        self.assertEqual(legacy_planning._a_an("12.0"), "a")
        self.assertEqual(legacy_planning._a_an("110.0"), "a")

    def test_total_assets_chart_title(self):
        self.assertEqual(explain._E["trend"]["title"], "Total assets over time")


class TestRuleEngine(unittest.TestCase):
    def test_phrase_rule_with_placeholders(self):
        out = _apply("s", "In {n} of {m} runs", "{n} out of {m}", "<p>In 12 of 300 runs it works</p>")
        self.assertEqual(out, "<p>12 out of 300 it works</p>")

    def test_text_rule_only_matches_a_whole_text_node(self):
        self.assertEqual(_apply("t", "Moderate", "Balanced", "<b>Moderate</b>"), "<b>Balanced</b>")
        self.assertEqual(_apply("t", "Moderate", "Balanced", "<p>Moderate risk</p>"), "<p>Moderate risk</p>")

    def test_heading_rule_leaves_other_text_alone(self):
        self.assertEqual(_apply("h", "Where", "Here", "<h3 class='x'>Where</h3><p>Where</p>"), "<h3 class='x'>Here</h3><p>Where</p>")

    def test_label_rule_only_matches_tile_labels(self):
        text = '<div class="label">Net</div><div class="value">Net</div>'
        self.assertEqual(_apply("l", "Net", "Total", text), '<div class="label">Total</div><div class="value">Net</div>')

    def test_dash_quote_and_symbol_spellings_all_match(self):
        for page in ("a -- b", "a — b", "a &mdash; b", "a—b"):
            self.assertEqual(_apply("s", "a — b", "X", page), "X", page)
        for page in ("it's", "it&#x27;s", "it’s", "it&rsquo;s"):
            self.assertEqual(_apply("s", "it’s", "X", page), "X", page)
        for page in ("say “hi”", "say &quot;hi&quot;", "say &ldquo;hi&rdquo;"):
            self.assertEqual(_apply("s", "say “hi”", "X", page), "X", page)
        for page in ("go → on", "go &rarr; on", "go &#8594; on"):
            self.assertEqual(_apply("s", "go → on", "X", page), "X", page)
        for page in ("age 59½", "age 59&#189;", "age 59&frac12;"):
            self.assertEqual(_apply("s", "age 59½", "X", page), "X", page)
        for page in ("a -> b", "a -&gt; b"):
            self.assertEqual(_apply("s", "a -> b", "X", page), "X", page)
        self.assertEqual(_apply("s", "Tom & Jerry", "X", "Tom &amp; Jerry"), "X")

    def test_ampersand_in_new_text_is_escaped_in_html(self):
        self.assertEqual(_apply("s", "old", "Q&A", "<p>old</p>"), "<p>Q&amp;A</p>")

    def test_plain_text_mode_uses_the_same_rules(self):
        rule = wording.compile_rule("s", "a — b {n}", "X {n}")
        self.assertEqual(rule.text_pattern.sub(lambda m: wording._render(rule, m, html_mode=False), "a -- b 5"), "X 5")


class TestRuleTable(unittest.TestCase):
    def test_every_rule_is_well_formed(self):
        seen = set()
        for kind, old, new in plain_rules.RULES:
            self.assertIn(kind, ("s", "t", "h", "l"))
            self.assertTrue(old.strip() and new.strip(), old)
            self.assertNotEqual(old, new)
            self.assertNotIn((kind, old), seen, f"duplicate rule: {old[:60]}")
            seen.add((kind, old))
            old_names = set(re.findall(r"\{(\w+)\}", old))
            new_names = set(re.findall(r"\{(\w+)\}", new))
            self.assertLessEqual(new_names, old_names, f"{old[:60]} uses a placeholder it does not capture")
            self.assertNotIn("FinSi", old + new)
            self.assertNotIn(" -- ", new)

    def test_every_rule_compiles(self):
        self.assertEqual(len(wording.rules()), len(plain_rules.RULES))

    def test_a_rule_never_starts_with_a_several_word_piece(self):
        for kind, old, _new in plain_rules.RULES:
            if kind == "s":
                self.assertFalse(old.startswith("{m_"), old[:60])


class TestDynamicSentences(unittest.TestCase):
    """Sentences that only appear for some households, built by the real code
    where that is simple and copied from the page source otherwise."""

    def test_verdict_sentence(self):
        money = lambda v: f"${v:,.0f}"  # noqa: E731
        result = {"success_rate": 0.999, "iterations": 1000, "years": []}
        for rate, expect in ((0.999, "In more than 99% of the 1,000 possible stock-market futures we tried"),
                             (0.5, "In 500 of the 1,000 possible stock-market futures we tried")):
            result["success_rate"] = rate
            sentence = presentation.verdict_sentence(result, {"birth_year": "1965"}, 100000, money)
            out = _plain("<p>" + html.escape(sentence) + "</p>")
            self.assertIn(expect, out)
            self.assertIn("while you spend about $100,000 a year", out)

    def test_watch_sentence_both_causes(self):
        money = lambda v: f"${v:,.0f}"  # noqa: E731
        base = [{"year": 2040, "expenses": 100000, "tax": 10000, "rmd": 0},
                {"year": 2041, "expenses": 160000, "tax": 40000, "rmd": 0}]
        out = _plain(presentation.watch_sentence(base, money))
        self.assertIn("your yearly cost (spending plus tax) jumps from $110,000 to $200,000", out)
        self.assertNotIn("yearly spending plus taxes", out)
        rmd = [dict(base[0], rmd=0), dict(base[1], rmd=50000)]
        out = _plain(presentation.watch_sentence(rmd, money))
        self.assertIn("That is when the IRS makes you start taking money out of your retirement accounts", out)

    def test_portfolio_checkup_findings(self):
        positions = [
            {"ticker": "AAA", "security_name": "Big Co", "security_type": "equity", "market_value": 600000,
             "institution": "Alpha Bank", "sector": "Technology"},
            {"ticker": "CASH", "security_name": "Cash", "security_type": "cash", "market_value": 300000,
             "institution": "Alpha Bank"},
            {"ticker": "BBB", "security_name": "Other", "security_type": "equity", "market_value": 100000,
             "institution": "Beta Bank", "sector": "Energy"},
        ]
        texts = [f["text"] for f in portfolio_checkup(positions)["findings"]]
        joined = " ".join(_plain("<p>" + html.escape(t) + "</p>") for t in texts)
        self.assertIn("of your investments", joined)
        self.assertNotIn("linked investments", joined)
        self.assertIn("is sitting in cash. A little cash is wise", joined)
        self.assertIn("Using more than one firm limits the damage", joined)
        ok = _plain("<p>" + html.escape(portfolio_checkup([{"ticker": "X", "security_name": "X", "security_type": "etf", "market_value": 10, "institution": "A", "sector": "Q"}])["findings"][0]["text"]) + "</p>")
        self.assertNotIn("linked investments", ok)

    def test_summary_sentences_that_depend_on_the_household(self):
        page = (
            '<p class="hero-note">Retirement year 2031 (5 years away). We tried 300 possible market futures, assuming\n'
            "6.00% yearly growth and 3.00% price rises. Amounts are in future dollars (grown by inflation).\n"
            '<a href="/monte-carlo.html#assumptions">Change assumptions</a></p>'
            '<div class="trust-footer muted small">\n<strong>How to read this:</strong> projections use 6.00% average yearly growth,\n'
            "3.00% inflation, a 40-year horizon and 300 simulated markets;\ndollars shown are future (inflated). x\n</div>"
            '<p class="small" style="margin:6px 0 0">Includes <strong>$10</strong> of home equity '
            "you marked &ldquo;In the plan?&rdquo; on Real Estate.</p>"
            "<li>2 funds may have the wrong sector tag (AAA, BBB)</li>"
            "<li>3 holdings with a negative value ($5 below zero)</li>"
            "<li>1 asset in the plan with no tax type</li>"
        )
        out = _plain(page)
        self.assertIn("All amounts are in future dollars, which are grown to match rising prices.", out)
        self.assertIn("Amounts are in future dollars, which are grown to match rising prices.", out)
        self.assertIn("Count in my plan?", out)
        self.assertIn("The labels on 2 funds may be wrong (AAA, BBB)", out)
        self.assertIn("3 investments show a negative amount ($5 below zero)", out)
        self.assertIn("1 account in your plan is missing a tax type", out)
        self.assertNotIn("market futures, assuming", out)

    def test_lever_sentence_for_every_lever(self):
        for label, expect in (("expected return", "how fast your investments grow"),
                              ("return volatility", "how bumpy the ride is"),
                              ("inflation", "how fast prices rise"),
                              ("plan horizon", "how many years you plan for"),
                              ("expense level", "how much you spend"),
                              ("income level", "how much income you have")):
            page = (f"<p><strong>The biggest lever for your plan is {label}.</strong> Testing ±1 percentage point moves "
                    "your chance of lasting between 80% and 96%. That is the first place to look if you want to improve your odds.</p>")
            out = _plain(page)
            self.assertIn(f"matters most for your plan is {expect}.", out)


class TestWordingSwitch(DashboardTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        demo_data.seed_sample_household(with_linked=True)

    def tearDown(self):
        db.set_wording_mode("technical")

    def _page(self, path="/summary.html"):
        return self._get(path).read().decode("utf-8")

    def test_the_default_is_plain(self):
        self.assertEqual(wording.DEFAULT_MODE, "plain")
        with patch.object(db, "wording_mode", side_effect=RuntimeError("no database yet")):
            self.assertEqual(wording.current_mode(), "plain")

    def test_switch_changes_the_words_and_the_button(self):
        status, payload = self._post("/api/wording-mode", {"mode": "plain"})
        self.assertEqual((status, payload["mode"]), (200, "plain"))
        page = self._page()
        self.assertIn("possible stock-market futures we tried", page)
        self.assertNotIn("market simulations your savings last", page)
        self.assertIn("Wording: Plain", page)
        status, payload = self._post("/api/wording-mode", {"mode": "technical"})
        self.assertEqual(payload["mode"], "technical")
        page = self._page()
        self.assertIn("market simulations your savings last", page)
        self.assertIn("Wording: Technical", page)

    def test_an_unknown_mode_is_refused(self):
        db.set_wording_mode("plain")
        with self.assertRaises(ValueError):
            db.set_wording_mode("loud")
        self.assertEqual(db.wording_mode(), "plain")
        status, _payload = self._post("/api/wording-mode", {"mode": "loud"})
        self.assertEqual(status, 400)
        self.assertEqual(db.wording_mode(), "plain")

    def test_the_button_is_on_every_tab(self):
        for path in ("/summary.html", "/monte-carlo.html", "/expense.html", "/setup.html"):
            self.assertIn('id="wording-toggle"', self._page(path), path)

    def test_a_view_only_login_may_switch_wording(self):
        from source.webapp import dashboard

        self.assertIn("/api/wording-mode", dashboard._VIEWER_POSTS)

    def test_page_names_do_not_change(self):
        db.set_wording_mode("plain")
        for path, names in (("/monte-carlo.html", ("Will my money last?", "Drawdown Planning", "Legacy Planning")),
                            ("/asset.html", ("Budget vs Actual",))):
            page = self._page(path)
            for name in names:
                self.assertIn(name, page, path)

    def test_technical_mode_keeps_the_original_words(self):
        db.set_wording_mode("technical")
        page = self._page("/monte-carlo.html")
        for words in ("Cautious case (1 in 10 do worse)", "Tax-deferred", "Required Minimum Distributions"):
            self.assertIn(words, page)

    def test_the_add_window_follows_the_switch(self):
        db.set_wording_mode("plain")
        page = self._page("/asset.html")
        self.assertIn("Grows with prices</label>", page)
        self.assertIn("Yearly rent you collect", page)
        db.set_wording_mode("technical")
        page = self._page("/asset.html")
        self.assertIn("Inflates</label>", page)
        self.assertNotIn("Yearly rent you collect", page)

    def test_the_report_follows_the_switch(self):
        db.set_wording_mode("plain")
        self.assertIn("Bad-luck case", self._page("/report.html"))
        db.set_wording_mode("technical")
        self.assertIn("Cautious case", self._page("/report.html"))

    def test_the_branding_never_comes_from_a_rule(self):
        db.set_wording_mode("plain")
        self.assertIn("FinSi", self._page("/summary.html"))


class TestPlainPages(DashboardTestCase):
    """Plain mode on a full sample household: every rule finds its words, the
    "i" buttons still find their headings and the page names are untouched."""

    PAGES = (
        "summary", "monte-carlo", "drawdown-planning", "legacy-planning", "asset", "expense", "real-estate",
        "rebalance", "linked-accounts", "linked-positions", "budget-vs-actual", "real-expenditure", "setup",
        "setup-wizard", "tutorial", "report",
    )

    # Rules for sentences that only show for some households (a different
    # dollar mode, a very high chance, a single flagged holding...). They are
    # checked on their own in TestDynamicSentences.
    HOUSEHOLD_DEPENDENT = (
        "In more than 99%",
        "Retirement year {y} ({m_w}). We tried {n} possible market futures, assuming {g} yearly growth and {p} price rises. Amounts are in future",
        "One thing to watch: in {y} yearly spending plus taxes jumps from {a} to {b}",
        "Includes <strong>{a}</strong> of home equity",
        "<strong>How to read this:</strong> projections use {g} average yearly growth, {i} inflation, a {h}-year horizon and {n} simulated markets; dollars shown are future",
        "{n} funds may have the wrong sector tag",
        "{n} holdings with a negative value",
        "{n} asset in the plan with no tax type",
        "is {p} of your linked investments",
        "of your linked investments (",
        "of your linked investments are with",
        "No red flags:",
        "We ran {n} possible market futures against your own savings and spending. Ending balances are in future",
        "matters most for your plan is ",
        "Property equity if kept, at the end",
        "Strong",
        "Rental income is treated as sheltered by mortgage interest and depreciation until each property's Loan ends (year) on",
        "If you have not chosen, Moderate is shown.",
        "are folded under Advanced settings.",
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "Fidelity 401k", "balance": 1200000, "include_in_monte_carlo": 1})
        db.add_line_item("assets", {"kind": "asset", "category": "Liquid", "name": "Brokerage", "balance": 400000, "include_in_monte_carlo": 1})
        db.add_line_item("real_estate", {"name": "Rental", "purchase_price": 300000, "current_value": 600000, "loan_balance": 200000, "annual_income": 30000, "address": "1 Main St, San Jose CA"})
        db.add_line_item("expenses", {"name": "Living", "annual_amount": 90000})
        db.set_assumptions({"birth_year": "1965", "spouse_birth_year": "1967", "ss_benefit_self": "3500", "ss_claim_age_self": "62",
                            "ss_benefit_spouse": "3000", "ss_claim_age_spouse": "62", "medicare_magi": "150000", "iterations": "200"})
        for day, total in (("2026-08-01", 1.9e6), ("2026-09-01", 1.95e6), ("2026-10-01", 2.0e6)):
            db.record_snapshot(net_worth=total, manual_asset_total=total, linked_asset_total=0, liability_total=0,
                               real_estate_equity_total=400000, retirement_liquid_total=total - 4e5, snapshot_date=day)
        demo_data.seed_sample_household(with_linked=True)
        db.set_wording_mode("plain")
        shell._PLAIN_SHELL = None  # so the page template's own words count as used below
        wording.reset_hit_counts()
        cls.pages = {}
        for name in cls.PAGES:
            conn_page = cls._fetch(name)
            cls.pages[name] = conn_page

    @classmethod
    def _fetch(cls, name):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=cls._HTTP_TIMEOUT)
        try:
            conn.request("GET", f"/{name}.html")
            return conn.getresponse().read().decode("utf-8")
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        db.set_wording_mode("technical")
        super().tearDownClass()

    def test_every_rule_finds_its_words_somewhere(self):
        unused = [r.old for r in wording.unused_rules()]
        unexpected = [o for o in unused if not any(o.startswith(p) for p in self.HOUSEHOLD_DEPENDENT)]
        self.maxDiff = None
        self.assertEqual(unexpected, [], "rules whose words no longer appear on any page")

    def test_the_i_buttons_still_find_their_headings(self):
        def norm(s):
            return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip().lower()

        checked = 0
        for name, page in self.pages.items():
            m = re.search(r'id="ex-data">(.*?)</script>', page, re.S)
            if not m:
                continue
            data = json.loads(m.group(1).replace("<\\/", "</"))
            texts = {norm(x) for x in re.findall(r"<h[23]\b[^>]*>(.*?)</h[23]>", page, re.S)}
            texts |= {norm(x) for x in re.findall(r'<div class="label">(.*?)</div>', page, re.S)}
            for text, _key in data["targets"]:
                checked += 1
                self.assertIn(text, texts, f"{name}: no heading reads {text!r}")
        self.assertGreater(checked, 80)

    def test_popup_texts_are_rewritten_too(self):
        m = re.search(r'id="ex-data">(.*?)</script>', self.pages["summary"], re.S)
        entries = json.loads(m.group(1).replace("<\\/", "</"))["entries"]
        self.assertEqual(entries["cautious"]["title"], "Bad-luck case")
        self.assertEqual(entries["typical"]["title"], "Middle case")

    def test_menu_names_are_kept(self):
        for name in ("Drawdown Planning", "Legacy Planning"):
            self.assertIn(name, self.pages["monte-carlo"])
        self.assertIn("Budget vs Actual", self.pages["asset"])

    def test_no_leftover_double_hyphen_dashes(self):
        for name, page in self.pages.items():
            text = re.sub(r"<style.*?</style>|<script.*?</script>", "", page, flags=re.S)
            self.assertNotRegex(text, r"\w -- \w", name)

    def test_risk_levels_use_plain_names(self):
        page = self.pages["rebalance"]
        for word in ("Cautious", "Balanced", "Bold"):
            self.assertIn(word, page)
        self.assertNotIn(">Conservative<", page)


if __name__ == "__main__":
    unittest.main()
