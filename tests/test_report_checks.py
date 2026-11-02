"""Report accuracy checks: which year the 'one thing to watch' sentence blames on required withdrawals, the table of what is taken from
savings versus reinvested required withdrawals, and the warning when the assumed volatility is low."""

import unittest

from source.common import demo_data
from source.reporting import presentation as pres
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
