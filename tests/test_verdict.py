"""The Summary's sentence must quote the real number of simulation runs."""

import unittest

from source.reporting import presentation as p


class TestVerdict(unittest.TestCase):
    def test_uses_actual_run_count(self):
        m = lambda x: f"${x:,.0f}"
        self.assertIn("In 982 of 1,000 market simulations", p.verdict_sentence({"success_rate": 0.982, "iterations": 1000}, {}, 0, m))
        self.assertIn("In 4,500 of 5,000", p.verdict_sentence({"success_rate": 0.9, "iterations": 5000}, {}, 0, m))
        self.assertIn("In more than 99% of 1,000", p.verdict_sentence({"success_rate": 0.999, "iterations": 1000}, {}, 0, m))


if __name__ == "__main__":
    unittest.main()
