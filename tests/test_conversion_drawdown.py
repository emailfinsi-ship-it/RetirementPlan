"""Roth conversions shown with the drawdown: the shared conversion step, the 'only age 62 to 70' strategy, the 'why so little' diagnosis, and the
Drawdown tab's choice of a strategy to include in its table."""

import unittest

from source.common import db, demo_data
from source.reporting.aggregate import build_summary
from source.reporting.monte_carlo import (
    apply_conversion_step, compare_roth_conversion_strategies, deterministic_drawdown_schedule, normalize_custom_strategy,
    strategy_configs, window_diagnosis,
)
from source.reporting.monte_carlo.legacy_planning import _run_conversion_schedule
from tests.test_dashboard import DashboardTestCase


def pools(**kw):
    return {"tax_deferred": 1_000_000.0, "roth": 0.0, "taxable": 500_000.0, "real_estate": 0.0, **kw}


class TestConversionStep(unittest.TestCase):
    def step(self, **kw):
        p = kw.pop("p", pools())
        args = dict(path_pools=p, target_rate=0.24, other_ordinary_income=0.0, year=2030, current_year=2026, inflation_rate=0.03, age=65)
        args.update(kw)
        return p, apply_conversion_step(**args)

    def test_it_moves_money_and_takes_the_tax_from_taxable(self):
        p, r = self.step()
        self.assertGreater(r["conversion"], 100_000)
        self.assertAlmostEqual(p["tax_deferred"], 1_000_000 - r["conversion"], 2)
        self.assertAlmostEqual(p["roth"], r["conversion"], 2)
        self.assertAlmostEqual(p["taxable"], 500_000 - r["conversion_tax"], 2)

    def test_nothing_converts_before_the_start_age_or_after_the_stop_age(self):
        for age in (61, 71):
            p, r = self.step(age=age, start_age=62, stop_age=70)
            self.assertEqual(r["conversion"], 0.0)
            self.assertEqual(p["roth"], 0.0)
        _p, r = self.step(age=62, start_age=62, stop_age=70)
        self.assertGreater(r["conversion"], 0.0)

    def test_a_full_bracket_means_no_room(self):
        _p, r = self.step(other_ordinary_income=700_000.0)
        self.assertEqual((r["conversion"], r["room"]), (0.0, 0.0))

    def test_the_yearly_cap_applies_and_grows_with_inflation(self):
        _p, r = self.step(annual_cap=50_000.0)
        self.assertAlmostEqual(r["conversion"], 50_000 * 1.03 ** 4, 0)


class TestStrategies(unittest.TestCase):
    def test_start_age_is_checked(self):
        self.assertEqual(normalize_custom_strategy({"bracket": 0.24, "start_age": "62", "stop_age": "70"})["start_age"], 62)
        with self.assertRaises(ValueError):
            normalize_custom_strategy({"bracket": 0.24, "start_age": 71, "stop_age": 70})
        with self.assertRaises(ValueError):
            normalize_custom_strategy({"bracket": 0.24, "start_age": 5})

    def test_the_window_strategy_exists_and_ignores_the_early_draw_setting(self):
        cfg = {c["key"]: c for c in strategy_configs({"early_tax_deferred_age": "60"}, None)}
        self.assertEqual((cfg["window_24"]["start_age"], cfg["window_24"]["stop_age"]), (62, 70))
        self.assertIsNone(cfg["window_24"]["early_spend_from_age"])
        self.assertEqual(cfg["fill_22"]["early_spend_from_age"], 60)


class TestOnSampleHousehold(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household()
        db.set_drawdown_conversion("")
        s = build_summary()
        self.s = s
        self.a = {**s["assumptions"], "spouse_tax_deferred_share": s["drawdown_spouse_tax_deferred_share"], "early_tax_deferred_age": "60"}

    def tearDown(self):
        db.set_drawdown_conversion("")
        demo_data.remove_sample_data()

    def compare(self, a=None):
        return compare_roth_conversion_strategies(pools=self.s["drawdown_pools"], expenses=self.s["expenses"],
                                                   income=self.s["income_for_simulation"], assumptions=a or self.a)

    def test_the_window_row_converts_only_between_62_and_70(self):
        row = next(r for r in self.compare()["strategies"] if r["key"] == "window_24")
        ages = [r["age"] for r in row["rows"] if r["conversion"] > 1]
        self.assertTrue(ages)
        self.assertGreaterEqual(min(ages), 62)
        self.assertLessEqual(max(ages), 70)

    def test_the_drawdown_table_and_the_legacy_engine_agree_on_conversions(self):
        cfg = next(c for c in strategy_configs(self.a, None) if c["key"] == "fill_22")
        legacy = _run_conversion_schedule(pools=self.s["drawdown_pools"], expenses=self.s["expenses"], income=self.s["income_for_simulation"],
                                          assumptions=self.a, target_rate=cfg["target_rate"], early_spend_from_age=cfg["early_spend_from_age"])
        sched = deterministic_drawdown_schedule(pools=self.s["drawdown_pools"], expenses=self.s["expenses"],
                                                income=self.s["income_for_simulation"], assumptions=self.a, conversion=cfg)
        self.assertEqual([round(r["conversion"]) for r in legacy["rows"]], [round(r["conversion"]) for r in sched["rows"]])
        self.assertAlmostEqual(legacy["rows"][-1]["total"], sched["rows"][-1]["total"], 0)

    def test_without_a_conversion_the_schedule_is_unchanged(self):
        plain = deterministic_drawdown_schedule(pools=self.s["drawdown_pools"], expenses=self.s["expenses"],
                                                income=self.s["income_for_simulation"], assumptions=self.a)
        self.assertNotIn("conversion", plain["rows"][0])
        self.assertIsNone(plain["conversion"])

    def test_the_diagnosis_blames_the_early_draw_and_shows_the_alternative(self):
        top = next(r for r in self.compare()["strategies"] if r["key"] == "fill_12")
        d = window_diagnosis(top, pools=self.s["drawdown_pools"], expenses=self.s["expenses"],
                             income=self.s["income_for_simulation"], assumptions=self.a)
        self.assertGreater(d["no_room_years"], 0)
        self.assertEqual(d["plan_early_age"], 60)
        self.assertGreater(d["spend_draw"], 0)
        self.assertGreater(d["alt_converted"], d["converted"])

    def test_no_diagnosis_for_the_baseline(self):
        base = next(r for r in self.compare()["strategies"] if r["key"] == "no_conversions")
        self.assertIsNone(window_diagnosis(base, pools=self.s["drawdown_pools"], expenses=self.s["expenses"],
                                           income=self.s["income_for_simulation"], assumptions=self.a))

    def test_the_drawdown_tab_includes_the_chosen_strategy_and_remembers_it(self):
        self.assertNotIn("Roth conversion</th>", self._get("/drawdown-planning.html").read().decode())
        status, out = self._post("/api/drawdown-conversion", {"key": "fill_24"})
        self.assertEqual((status, out["key"]), (200, "fill_24"))
        page = self._get("/drawdown-planning.html").read().decode()
        self.assertIn("Roth conversion</th>", page)
        self.assertIn("Conversion tax</th>", page)
        self.assertIn("Also convert", page)
        self.assertIn('value="fill_24" selected', page)
        status, _ = self._post("/api/drawdown-conversion", {"key": ""})
        self.assertNotIn("Roth conversion</th>", self._get("/drawdown-planning.html").read().decode())

    def test_an_unknown_strategy_is_refused(self):
        status, out = self._post("/api/drawdown-conversion", {"key": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("Legacy Planning", out["error"])

    def test_the_legacy_page_explains_small_conversions_and_offers_the_drawdown_button(self):
        db.set_assumption("early_tax_deferred_age", "60")
        page = self._get("/legacy-planning.html").read().decode()
        self.assertIn("Why so little converted between 62 and 70?", page)
        self.assertIn("starts spending from Tax-deferred at age 60", page)
        self.assertIn("only from age 62 to 70", page)
        self.assertIn("Show on Drawdown", page)
        self.assertIn('name="start_age"', page)


if __name__ == "__main__":
    unittest.main()
