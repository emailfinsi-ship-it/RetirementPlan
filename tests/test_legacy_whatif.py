"""Legacy Planning: the "How we arrived at this recommendation" panel and
the "Try your own strategy" what-if row."""

from __future__ import annotations

import unittest

from source.common import db, demo_data
from source.reporting.aggregate import build_summary
from source.reporting.monte_carlo import compare_roth_conversion_strategies, normalize_custom_strategy
from source.reporting.monte_carlo.legacy_planning import custom_strategy_label
from tests.test_dashboard import DashboardTestCase
from tests.testing_utils import TempConfigTestCase


class TestNormalize(unittest.TestCase):
    def test_empty_means_no_what_if(self):
        self.assertIsNone(normalize_custom_strategy(None))
        self.assertIsNone(normalize_custom_strategy({}))

    def test_percent_forms_and_blank_fields(self):
        self.assertEqual(
            normalize_custom_strategy({"bracket": "24", "annual_cap": "", "stop_age": ""}),
            {"bracket": 0.24, "annual_cap": None, "stop_age": None},
        )
        self.assertEqual(normalize_custom_strategy({"bracket": 0.22, "annual_cap": "$200,000", "stop_age": "72"}),
                         {"bracket": 0.22, "annual_cap": 200000.0, "stop_age": 72})
        self.assertEqual(normalize_custom_strategy({"bracket": "none", "annual_cap": 1000})["bracket"], "none")

    def test_25_percent_is_not_a_bracket(self):
        with self.assertRaises(ValueError) as ctx:
            normalize_custom_strategy({"bracket": "25"})
        self.assertIn("not a federal bracket", str(ctx.exception))

    def test_bad_cap_and_age_are_rejected(self):
        for bad in ({"bracket": "24", "annual_cap": "-5"}, {"bracket": "24", "annual_cap": "abc"},
                    {"bracket": "24", "stop_age": "5"}):
            with self.assertRaises(ValueError):
                normalize_custom_strategy(bad)

    def test_label_mentions_every_setting(self):
        label = custom_strategy_label({"bracket": 0.24, "annual_cap": 150000.0, "stop_age": 72})
        self.assertIn("24%", label)
        self.assertIn("$150,000", label)
        self.assertIn("age 72", label)


class TestEngine(TempConfigTestCase):
    def setUp(self):
        super().setUp()
        demo_data.seed_sample_household()
        s = build_summary()
        self.kw = dict(
            pools=s["drawdown_pools"], expenses=s["expenses"], income=s["income_for_simulation"],
            assumptions={**s["assumptions"], "spouse_tax_deferred_share": s["drawdown_spouse_tax_deferred_share"]},
        )

    def _by_key(self, result):
        return {r["key"]: r for r in result["strategies"]}

    def test_without_a_what_if_nothing_changes(self):
        r = compare_roth_conversion_strategies(**self.kw)
        self.assertNotIn("custom", self._by_key(r))
        self.assertIsNone(r["custom"])

    def test_a_bare_24_what_if_reproduces_the_24_row(self):
        r = self._by_key(compare_roth_conversion_strategies(**self.kw, custom={"bracket": 0.24}))
        for field in ("total_converted", "total_lifetime_tax", "net_after_tax_legacy"):
            self.assertAlmostEqual(r["custom"][field], r["fill_24"][field], places=2)
        self.assertTrue(r["custom"]["is_custom"])

    def test_a_cap_limits_each_years_conversion(self):
        r = self._by_key(compare_roth_conversion_strategies(**self.kw, custom={"bracket": 0.24, "annual_cap": 50_000}))
        rows = r["custom"]["rows"]
        base_year = rows[0]["year"]
        # today's-dollar cap grown by inflation (the sample plan's own assumption)
        infl = float(self.kw["assumptions"].get("inflation_rate") or 0.0)
        for row in rows:
            self.assertLessEqual(row["conversion"], 50_000 * (1 + infl) ** (row["year"] - base_year) + 0.01)

    def test_stop_age_ends_conversions(self):
        r = self._by_key(compare_roth_conversion_strategies(**self.kw, custom={"bracket": 0.24, "stop_age": 65}))
        for row in r["custom"]["rows"]:
            if row["age"] is not None and row["age"] > 65:
                self.assertEqual(row["conversion"], 0.0)
        self.assertGreater(r["custom"]["total_converted"], 0.0)

    def test_the_what_if_is_ranked_and_can_win(self):
        result = compare_roth_conversion_strategies(**self.kw, custom={"bracket": 0.24, "annual_cap": 150_000, "stop_age": 72})
        ranked = [r["net_after_tax_legacy"] for r in result["strategies"]]
        self.assertEqual(ranked, sorted(ranked, reverse=True))
        self.assertEqual(len(result["strategies"]), 8)

    def test_every_row_reports_its_tax_deferred_after_heir_tax(self):
        for r in compare_roth_conversion_strategies(**self.kw)["strategies"]:
            self.assertAlmostEqual(
                r["net_after_tax_legacy"],
                r["ending_taxable"] + r["ending_roth"] + r["ending_real_estate"] + r["tax_deferred_after_heir_tax"], places=4,
            )


class TestLegacyPage(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household()

    def tearDown(self):
        demo_data.remove_sample_data()
        db.set_legacy_whatif(None)

    def test_panel_shows_the_rule_the_sum_and_the_caveats(self):
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn("How we arrived at this recommendation", body)
        self.assertIn("net after-tax legacy", body)
        self.assertIn("= Net after-tax legacy", body)
        self.assertIn("What it costs and what it buys", body)
        self.assertIn("What this does not model", body)
        self.assertIn("IRMAA", body)

    def test_panel_sum_matches_the_tables_recommended_row(self):
        from source.reporting.monte_carlo import compare_roth_conversion_strategies as cmp_

        s = build_summary()
        r = cmp_(
            pools=s["drawdown_pools"], expenses=s["expenses"], income=s["income_for_simulation"],
            assumptions={**s["assumptions"], "spouse_tax_deferred_share": s["drawdown_spouse_tax_deferred_share"]},
        )
        top = r["strategies"][0]
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        formatted = f"${top['net_after_tax_legacy']:,.0f}"
        self.assertGreaterEqual(body.count(formatted), 2)  # once in the panel, once in the table

    def test_what_if_card_is_there_and_explains_there_is_no_25_bracket(self):
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn("Try your own strategy", body)
        self.assertIn("no 25% bracket", body)
        self.assertNotIn("Your what-if</span>", body)

    def test_saving_a_what_if_adds_a_row_and_clearing_removes_it(self):
        status, payload = self._post("/api/legacy-whatif", {"bracket": "24", "annual_cap": "150000", "stop_age": "72"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["whatif"]["annual_cap"], 150000.0)
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertIn("Your what-if</span>", body)
        self.assertIn("Your what-if ranks", body)
        self.assertIn("Remove my what-if", body)
        status, _ = self._post("/api/legacy-whatif", {"clear": True})
        self.assertEqual(status, 200)
        body = self._get("/legacy-planning.html").read().decode("utf-8")
        self.assertNotIn("Your what-if</span>", body)

    def test_an_invalid_what_if_is_refused_and_not_saved(self):
        status, _ = self._post("/api/legacy-whatif", {"bracket": "25"})
        self.assertNotEqual(status, 200)
        self.assertIsNone(db.legacy_whatif())


if __name__ == "__main__":
    unittest.main()
