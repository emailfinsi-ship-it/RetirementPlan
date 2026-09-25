"""source.reporting.rmd -- IRS Required Minimum Distribution timing and
divisor table, used by the Monte Carlo tab's three-pool withdrawal
engine (source.reporting.monte_carlo)."""

from __future__ import annotations

import unittest

from source.reporting import rmd


class TestRmdAgeForBirthYear(unittest.TestCase):
    def test_born_1959_or_earlier_is_age_73(self):
        self.assertEqual(rmd.rmd_age_for_birth_year(1959), 73)
        self.assertEqual(rmd.rmd_age_for_birth_year(1951), 73)
        self.assertEqual(rmd.rmd_age_for_birth_year(1940), 73)

    def test_born_1960_or_later_is_age_75(self):
        self.assertEqual(rmd.rmd_age_for_birth_year(1960), 75)
        self.assertEqual(rmd.rmd_age_for_birth_year(1975), 75)


class TestRequiredMinimumDistribution(unittest.TestCase):
    def test_zero_before_rmd_age(self):
        self.assertEqual(rmd.required_minimum_distribution(1_000_000, 72, 1959), 0.0)
        self.assertEqual(rmd.required_minimum_distribution(1_000_000, 74, 1965), 0.0)

    def test_zero_for_nonpositive_balance(self):
        self.assertEqual(rmd.required_minimum_distribution(0, 80, 1950), 0.0)
        self.assertEqual(rmd.required_minimum_distribution(-500, 80, 1950), 0.0)

    def test_matches_published_divisor_at_73(self):
        # $1,000,000 / 26.5 (age 73's IRS divisor)
        self.assertAlmostEqual(rmd.required_minimum_distribution(1_000_000, 73, 1955), 1_000_000 / 26.5)

    def test_matches_published_divisor_at_75_cohort_boundary(self):
        # Someone born 1960 doesn't owe an RMD at 73 or 74 (their threshold is 75)...
        self.assertEqual(rmd.required_minimum_distribution(1_000_000, 74, 1960), 0.0)
        # ...but does at 75, using the age-75 divisor.
        self.assertAlmostEqual(rmd.required_minimum_distribution(1_000_000, 75, 1960), 1_000_000 / 24.6)

    def test_divisor_shrinks_and_rmd_grows_with_age(self):
        rmd_80 = rmd.required_minimum_distribution(1_000_000, 80, 1940)
        rmd_90 = rmd.required_minimum_distribution(1_000_000, 90, 1940)
        self.assertGreater(rmd_90, rmd_80)

    def test_ages_beyond_the_table_use_the_final_divisor(self):
        expected = 1_000_000 / 2.0
        self.assertAlmostEqual(rmd.required_minimum_distribution(1_000_000, 119, 1940), 1_000_000 / 2.3)
        self.assertAlmostEqual(rmd.required_minimum_distribution(1_000_000, 120, 1940), expected)
        self.assertAlmostEqual(rmd.required_minimum_distribution(1_000_000, 140, 1940), expected)


if __name__ == "__main__":
    unittest.main()
