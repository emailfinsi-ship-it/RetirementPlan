"""Report accuracy checks: which year the 'one thing to watch' sentence blames on required withdrawals, the table of what is taken from
savings versus reinvested required withdrawals, and the warning when the assumed volatility is low."""

import unittest

from source.common import demo_data
from source.reporting import benefits, data_check
from source.reporting import presentation as pres
from source.reporting.monte_carlo.withdrawal import annual_expense_need
from source.webapp.pages import report
from tests.test_dashboard import DashboardTestCase


def row(year, expenses=100000.0, tax=5000.0, rmd=0.0, rmd_spouse=0.0, **kw):
    return {"year": year, "expenses": expenses, "tax": tax, "rmd": rmd, "rmd_spouse": rmd_spouse, **kw}


def money(v):
    return f"${v:,.0f}"


class TestWatchSentence(unittest.TestCase):
    def test_the_first_year_of_required_withdrawals_says_the_irs_starts_them(self):
        rows = [row(2044), row(2045, expenses=190000.0, rmd=90000.0)]
        self.assertIn("starts requiring withdrawals from your retirement accounts", pres.watch_sentence(rows, money))

    def test_a_spouses_later_start_is_not_called_the_first_start(self):
        # the plan owner's own required withdrawals began in 2045; the spouse's begin five years later
        rows = [row(2045, expenses=190000.0, rmd=90000.0), row(2049, rmd=95000.0), row(2050, expenses=190000.0, rmd=190000.0, rmd_spouse=95000.0)]
        out = pres.watch_sentence(rows[1:], money)
        self.assertIn("spouse", out)
        self.assertNotIn("starts requiring withdrawals from your retirement accounts", out)

    def test_a_jump_that_is_not_about_required_withdrawals_says_so(self):
        rows = [row(2050, rmd=50000.0), row(2051, expenses=200000.0, rmd=50500.0)]
        self.assertIn("spending and taxes step up", pres.watch_sentence(rows, money))


class TestVolatilityNote(unittest.TestCase):
    def test_a_low_figure_gets_a_plain_warning_with_the_rerun_chance(self):
        out = pres.volatility_note(0.1157, 0.20, 0.995, 0.93)
        self.assertIn("11.6%", out)
        self.assertIn("about 20% a year", out)
        self.assertIn("93%", out)
        self.assertIn(">99%", out)

    def test_a_normal_or_high_figure_gets_no_warning(self):
        self.assertEqual(pres.volatility_note(0.16, 0.20, 0.9, None), "")


class TestReinvestedNote(unittest.TestCase):
    def test_it_names_the_biggest_year_where_the_required_draw_exceeds_spending(self):
        rows = [
            {"year": 2056, "expenses": 290000.0, "tax": 4000.0, "income_social_security": 0.0, "income_rental": 0.0, "income_other": 0.0,
             "drawn_tax_deferred": 294000.0, "drawn_taxable": 0.0, "drawn_roth": 0.0, "drawn_real_estate": 0.0},
            {"year": 2057, "expenses": 290000.0, "tax": 4000.0, "income_social_security": 0.0, "income_rental": 0.0, "income_other": 0.0,
             "drawn_tax_deferred": 773000.0, "drawn_taxable": 0.0, "drawn_roth": 0.0, "drawn_real_estate": 0.0},
        ]
        out = report._reinvested_note(rows, lambda value, year: value)
        self.assertIn("2057", out)
        self.assertIn("$773,000", out)
        self.assertIn("$294,000", out)
        self.assertIn("$479,000", out)
        self.assertIn("moved into a regular (taxable) account", out)

    def test_nothing_is_said_when_every_year_is_spending(self):
        rows = [{"year": 2050, "expenses": 100000.0, "tax": 0.0, "income_social_security": 0.0, "income_rental": 0.0, "income_other": 0.0,
                 "drawn_tax_deferred": 100000.0, "drawn_taxable": 0.0, "drawn_roth": 0.0, "drawn_real_estate": 0.0}]
        self.assertEqual(report._reinvested_note(rows, lambda value, year: value), "")


def _exp(name, category, amount, start=None, end=None, base=2026, inflates=1):
    return {"name": name, "category": category, "annual_amount": amount, "start_year": start, "end_year": end, "base_year": base, "inflates": inflates}


class TestSpendingByCategory(unittest.TestCase):
    EXPENSES = [
        _exp("Medical Insurance", "Insurance", 30000.0, 2027, 2045, base=2027),
        _exp("Medicare premiums (Sam)", "Healthcare", 7054.8, 2035),
        _exp("House insurance", "Insurance", 7000.0, 2027, base=2027),
        _exp("Moorpark loan", "House-Loan", 35400.0, None, 2040, base=2027, inflates=0),
        _exp("Vacation fund", "Travel", 24000.0, 2027, base=2027),
    ]

    def test_health_care_rows_are_grouped_under_healthcare_whatever_their_category(self):
        self.assertEqual(report._spending_category(self.EXPENSES[0]), "Healthcare")
        self.assertEqual(report._spending_category(self.EXPENSES[1]), "Healthcare")
        self.assertEqual(report._spending_category(self.EXPENSES[2]), "Insurance")
        self.assertEqual(report._spending_category(self.EXPENSES[4]), "Travel")        # "vacation" is not "ACA"

    def test_columns_follow_start_and_end_years_and_add_up_to_the_spending_figure(self):
        s = {"expenses": self.EXPENSES, "this_year": 2026}
        a = {"inflation_rate": "0.03", "plan_horizon_years": "45"}
        out = report._spending_by_category_html(s, a, "future", {"retirement_year": 2027})
        for year in (2027, 2037, 2047):
            self.assertIn(f"<th class=\"num\">{year}</th>", out)
        # healthcare in 2027 is only the medical insurance (Medicare has not started): $30,000, not the $37,000 of both rows' base amounts
        self.assertIn("$30,000", out)
        total_2037 = annual_expense_need(self.EXPENSES, 2037, 0.03)
        self.assertIn(f"${total_2037:,.0f}", out)
        self.assertIn("Medical Insurance, Medicare premiums (Sam)", out)

    def test_a_cost_that_has_ended_shows_a_dash(self):
        s = {"expenses": self.EXPENSES, "this_year": 2026}
        out = report._spending_by_category_html(s, {"inflation_rate": "0.03", "plan_horizon_years": "45"}, "future", {"retirement_year": 2027})
        self.assertIn('<td class="">House-Loan</td><td class="num">$35,400</td><td class="num">$35,400</td><td class="num">&ndash;</td>', out)   # paid in 2027 and 2037, over by 2047


class TestVolatilityWording(unittest.TestCase):
    def test_same_display_reads_still(self):
        t = pres.volatility_note(0.1157, 0.2, 0.999, 0.998)
        self.assertIn("is still >99%", t)
        self.assertNotIn("instead of", t)
        self.assertIn("instead of", pres.volatility_note(0.1157, 0.2, 0.95, 0.80))


class TestHealthOverlap(unittest.TestCase):
    def summary(self, private_end):
        s = benefits.BENEFITS_SOURCE
        return {"assumptions": {"inflation_rate": "0.03"}, "expenses": [
            {"id": 1, "name": "Medical Insurance", "category": "Insurance", "annual_amount": 30000, "start_year": 2027, "end_year": private_end,
             "base_year": 2027, "inflates": 1},
            {"id": 2, "name": "Medicare premiums (A)", "category": "Healthcare", "annual_amount": 7054.8, "start_year": 2035, "base_year": 2026,
             "inflates": 1, "source": s},
            {"id": 3, "name": "Medicare premiums (B)", "category": "Healthcare", "annual_amount": 7054.8, "start_year": 2040, "base_year": 2026,
             "inflates": 1, "source": s},
        ]}

    def test_a_private_plan_that_runs_past_the_first_medicare_start_is_flagged(self):
        out = data_check._health_overlap(self.summary(2045))
        self.assertEqual(len(out), 1)
        self.assertIn("Medical Insurance", out[0]["title"])
        self.assertIn("start in 2035", out[0]["detail"])
        self.assertIn("extra in 2035", out[0]["detail"])

    def test_a_private_plan_that_ends_before_medicare_is_fine(self):
        self.assertEqual(data_check._health_overlap(self.summary(2034)), [])

    def test_a_row_naming_one_person_is_compared_with_that_persons_medicare(self):
        s = self.summary(2034)
        s["expenses"].append({"id": 4, "name": "medical-B", "category": "Healthcare", "annual_amount": 15000, "start_year": 2035, "end_year": 2039,
                              "base_year": 2027, "inflates": 1})
        self.assertEqual(data_check._health_overlap(s), [])    # B's Medicare starts in 2040, after this row ends
        s["expenses"][-1]["end_year"] = 2040
        out = data_check._health_overlap(s)
        self.assertEqual(len(out), 1)
        self.assertIn("start in 2040", out[0]["detail"])

    def test_nothing_is_flagged_without_medicare_rows(self):
        s = self.summary(2045)
        s["expenses"] = s["expenses"][:1]
        self.assertEqual(data_check._health_overlap(s), [])


class TestReportPage(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household()

    def tearDown(self):
        demo_data.remove_sample_data()

    def test_the_report_warns_about_low_volatility_and_explains_reinvested_withdrawals(self):
        body = self._get("/report.html").read().decode("utf-8")
        self.assertIn("A check on the 12.0% yearly ups and downs", body)      # the sample plan assumes 12%
        self.assertIn("Re-run at 16%", body)
        self.assertIn("is moved into a regular (taxable) account", body)
        self.assertIn("Tax is figured on the whole required withdrawal", body)


if __name__ == "__main__":
    unittest.main()
