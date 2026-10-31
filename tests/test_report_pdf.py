"""The Download PDF button on the plan report: a real PDF file made on the computer, not the browser's print dialog."""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from source.common import demo_data
from source.reporting import report_pdf
from tests.test_dashboard import DashboardTestCase

_PAGE = """<html><head><title>Hidden title</title><style>.x { color: red }</style></head><body>
<script>var secret = 'not in the pdf';</script>
<div class="report-bar"><button>Print</button></div>
<section class="rep-page first"><h2 class="rep-title">1. Plan</h2>
<p>You have <strong>98%</strong> chance.</p>
<div class="tile"><div class="label">Net worth</div><div class="value">$4,170,000</div></div>
<ul><li><span>Investments</span><span class="mny">$3,230,000</span></li></ul>
<table class="rep"><thead><tr><th>Year</th><th class="num">Balance</th></tr></thead>
<tbody><tr><td>2031</td><td class="num">$2,459,342</td></tr></tbody></table>
<svg><text>chart label</text></svg></section>
<section class="rep-page"><h2 class="rep-title">2. Goals</h2><p>Plan goes to 97 → fine ● ok.</p></section>
</body></html>"""


def _pages(pdf: bytes):
    from pypdf import PdfReader

    return PdfReader(io.BytesIO(pdf)).pages


class TestReportPdf(unittest.TestCase):
    def test_it_makes_a_pdf_with_a_page_for_each_report_page(self):
        pdf = report_pdf.report_pdf(_PAGE)
        self.assertTrue(pdf.startswith(b"%PDF"))
        try:
            pages = _pages(pdf)
        except ImportError:
            self.skipTest("pypdf is not installed here")
        self.assertEqual(len(pages), 2)
        first = pages[0].extract_text()
        for word in ("1. Plan", "98%", "chance", "Net worth", "$4,170,000", "Investments", "$3,230,000", "Year", "$2,459,342"):
            self.assertIn(word, first)
        for gone in ("not in the pdf", "Hidden title", "chart label", "Print"):
            self.assertNotIn(gone, first)                       # scripts, the head, charts and buttons are left out
        self.assertIn("Plan goes to 97", pages[1].extract_text())   # symbols the PDF font lacks become plain ones, not blanks

    def test_names_and_amounts_written_side_by_side_do_not_run_together(self):
        text = report_pdf.report_pdf(_PAGE)
        try:
            body = _pages(text)[0].extract_text()
        except ImportError:
            self.skipTest("pypdf is not installed here")
        self.assertRegex(body, r"Investments\s+\$3,230,000")

    def test_without_reportlab_it_says_so_instead_of_failing(self):
        with patch.dict("sys.modules", {"reportlab": None, "reportlab.lib": None}):
            with self.assertRaises(report_pdf.ReportPdfUnavailable):
                report_pdf.report_pdf(_PAGE)


class TestReportPdfDownload(DashboardTestCase):
    def setUp(self):
        demo_data.seed_sample_household()

    def tearDown(self):
        demo_data.remove_sample_data()

    def test_the_report_page_offers_the_download_and_the_endpoint_sends_a_pdf_file(self):
        body = self._get("/report.html").read().decode("utf-8")
        self.assertIn('href="/report.pdf"', body)
        self.assertIn("Download PDF", body)
        resp = self._get("/report.pdf")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "application/pdf")
        self.assertRegex(resp.getheader("Content-Disposition"), r'attachment; filename="[\w-]+-plan-report-\d{4}-\d{2}-\d{2}\.pdf"')
        data = resp.read()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertEqual(int(resp.getheader("Content-Length")), len(data))
        try:
            pages = _pages(data)
        except ImportError:
            return
        self.assertGreaterEqual(len(pages), 5)                                    # the five report pages (the tables can run longer)
        self.assertIn("Your plan at a glance", pages[0].extract_text())
        self.assertTrue(all(len(p.extract_text().strip()) > 50 for p in pages))   # none of them blank

    def test_a_missing_pdf_library_gives_a_message_and_the_print_button_still_works(self):
        with patch("source.reporting.report_pdf.report_pdf", side_effect=report_pdf.ReportPdfUnavailable("PDF download needs the reportlab package.")):
            resp = self._get("/report.pdf")
        self.assertEqual(resp.status, 503)
        self.assertIn("choose Save as PDF", resp.read().decode("utf-8"))
