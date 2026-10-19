"""Remembered simulation runs and the background warm-up."""

import random
import unittest

from source.reporting.monte_carlo import simulation as sim
from source.webapp import warm

ARGS = dict(
    starting_balance=1_000_000.0,
    expenses=[{"name": "Living", "amount": 60_000.0, "start_year": 2026, "end_year": 2060}],
    income=[],
    assumptions={"iterations": 40, "expected_return": 0.06, "return_volatility": 0.12,
                 "inflation": 0.03, "birth_year": "1970", "retirement_year": "2030", "horizon_years": 20},
)


class TestMemo(unittest.TestCase):
    def setUp(self):
        sim.enable_memo(False)

    def tearDown(self):
        sim.enable_memo(False)

    def test_off_by_default(self):
        self.assertFalse(sim._memo_on)
        sim.run_simulation(**ARGS, rng=random.Random(1))
        self.assertEqual(len(sim._memo), 0)

    def test_same_inputs_same_answer_and_remembered(self):
        plain = sim.run_simulation(**ARGS, rng=random.Random(1))
        sim.enable_memo(True)
        first = sim.run_simulation(**ARGS, rng=random.Random(1))
        self.assertEqual(len(sim._memo), 1)
        second = sim.run_simulation(**ARGS, rng=random.Random(1))
        self.assertEqual(plain, first)
        self.assertEqual(first, second)

    def test_different_seed_or_inputs_are_not_mixed_up(self):
        sim.enable_memo(True)
        sim.run_simulation(**ARGS, rng=random.Random(1))
        sim.run_simulation(**ARGS, rng=random.Random(2))
        bigger = dict(ARGS, starting_balance=2_000_000.0)
        sim.run_simulation(**bigger, rng=random.Random(1))
        sim.run_historical_bootstrap_simulation(**ARGS, rng=random.Random(1))
        self.assertEqual(len(sim._memo), 4)

    def test_unseeded_runs_are_never_remembered(self):
        sim.enable_memo(True)
        sim.run_simulation(**ARGS)
        self.assertEqual(len(sim._memo), 0)

    def test_changing_a_returned_result_does_not_change_the_memory(self):
        sim.enable_memo(True)
        a = sim.run_simulation(**ARGS, rng=random.Random(3))
        a["success_rate"] = -1
        b = sim.run_simulation(**ARGS, rng=random.Random(3))
        self.assertNotEqual(b["success_rate"], -1)

    def test_memory_is_capped(self):
        sim.enable_memo(True)
        for i in range(sim._MEMO_MAX + 5):
            sim._memo_put(f"k{i}", {"x": i})
        self.assertEqual(len(sim._memo), sim._MEMO_MAX)


class TestWarm(unittest.TestCase):
    def tearDown(self):
        warm.enable(False)

    def test_does_nothing_unless_enabled(self):
        warm.enable(False)
        before = warm._timer
        warm.schedule(delay=0)
        self.assertIs(warm._timer, before)   # nothing was scheduled

    def test_enable_turns_the_memory_on_and_off(self):
        warm.enable(True)
        self.assertTrue(sim._memo_on)
        warm.enable(False)
        self.assertFalse(sim._memo_on)


if __name__ == "__main__":
    unittest.main()
