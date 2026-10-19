"""Data check card, backup verification and the sample-data issues it flags."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from source.common import backup, db, demo_data
from source.reporting import data_check as dc
from tests.test_dashboard import DashboardTestCase


def pos(sid, value, kind="mutual fund", name="", ticker="", tax="taxable", basis=None, **kw):
    return {"security_id": sid, "market_value": value, "security_type": kind, "security_name": name or sid,
            "ticker": ticker or sid, "tax_treatment": tax, "cost_basis": basis, "institution": "Inst", "account": "Acct", **kw}


class TestChecks(unittest.TestCase):
    def test_negative_cash_is_flagged(self):
        ids = [i["id"] for i in dc.check_positions([pos("c", -5000, "cash"), pos("a", 100)])]
        self.assertIn("negative-holdings", ids)

    def test_tag_mismatch_gets_a_one_click_fix(self):
        issues = dc.check_positions([pos("x", 50_000, name="Vg Inst 500 Idx", manual_sector="International"),
                                     pos("ok", 50_000, name="Total Bond Market", industry="Bond")])
        mismatch = next(i for i in issues if i["id"] == "tag-mismatch")
        self.assertEqual(mismatch["fix"]["payload"]["security_ids"], ["x"])
        self.assertEqual(mismatch["level"], "warn")

    def test_bond_named_fund_tagged_as_stocks_is_flagged_and_matching_tags_are_not(self):
        issues = dc.check_positions([pos("b", 10_000, name="Sample Aggregate Bond ETF", industry="Technology")])
        self.assertTrue(any(i["id"] == "tag-mismatch" for i in issues))
        self.assertEqual(dc.check_positions([pos("b", 10_000, name="Sample Aggregate Bond ETF", industry="Bond", basis=9_000)]), [])

    def test_no_cost_basis_only_for_big_taxable_noncash(self):
        issues = dc.check_positions([pos("a", 5000, "equity", basis=None), pos("c", 5000, "cash", basis=None),
                                     pos("r", 5000, "equity", tax="roth"), pos("s", 500, "equity")])
        self.assertEqual([i["id"] for i in issues], ["no-cost-basis"])
        self.assertIn("1 taxable holding", issues[0]["title"])

    def test_stale_sync_and_bad_years_and_untyped(self):
        old = (datetime.now() - timedelta(days=10)).isoformat()
        summary = {"linked_status": {"configured": True, "last_synced_at": old},
                   "assets": [{"include_in_monte_carlo": 1, "tax_treatment": "", "kind": "asset"}],
                   "expenses": [{"name": "Trip", "start_year": 2030, "end_year": 2028, "annual_amount": 0}], "income": []}
        ids = {i["id"] for i in dc.check_plan(summary)}
        self.assertEqual(ids, {"stale-sync", "no-tax-type", "bad-years-expenses", "zero-expenses"})

    def test_backup_states(self):
        self.assertEqual(dc.check_backup({"exists": False})[0]["id"], "no-backup")
        self.assertEqual(dc.check_backup({"exists": True, "ok": False, "error": "x"})[0]["id"], "bad-backup")
        self.assertEqual(dc.check_backup({"exists": True, "ok": True, "age_days": 5})[0]["id"], "old-backup")
        self.assertEqual(dc.check_backup({"exists": True, "ok": True, "age_days": 0.2}), [])

    def test_warnings_sort_first(self):
        issues = dc.run_checks({"assets": [{"include_in_monte_carlo": 1, "tax_treatment": ""}]}, [pos("c", -1, "cash")],
                               {"exists": False})
        self.assertEqual(issues[0]["level"], "warn")
        self.assertEqual(issues[-1]["level"], "info")


class TestBackupVerify(unittest.TestCase):
    def test_good_and_corrupt_files(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / "good.db"
            conn = sqlite3.connect(good)
            for t in backup._KEY_TABLES:
                conn.execute(f"CREATE TABLE {t} (id INTEGER)")
            conn.commit(); conn.close()
            self.assertTrue(backup.verify_backup(good)["ok"])
            bad = Path(d) / "bad.db"
            bad.write_bytes(b"this is not a database" * 50)
            self.assertFalse(backup.verify_backup(bad)["ok"])
            partial = Path(d) / "partial.db"
            conn = sqlite3.connect(partial); conn.execute("CREATE TABLE assets (id INTEGER)"); conn.commit(); conn.close()
            self.assertIn("Missing tables", backup.verify_backup(partial)["error"])


class TestDataCheckPages(DashboardTestCase):
    def tearDown(self):
        demo_data.remove_sample_data()

    def test_summary_shows_data_check_with_sample_issues_and_fix_clears_the_tag(self):
        demo_data.seed_sample_household(with_linked=True)
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertIn('id="data-check"', body)
        self.assertIn("negative value", body)
        self.assertIn("wrong sector tag", body)
        self.assertIn("Clear these tags", body)
        status, d = self._post("/api/clear-sector-tags", {"security_ids": ["smp-sp500"]})
        self.assertEqual(status, 200)
        body = self._get("/summary.html").read().decode("utf-8")
        self.assertNotIn("wrong sector tag", body)

    def test_backup_verify_endpoint_and_setup_health_line(self):
        backup.create_backup(reason="manual")
        status, d = self._post("/api/backup-verify", {})
        self.assertEqual(status, 200)
        self.assertTrue(d["exists"])
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn("Test latest backup", body)
        self.assertIn("Health:", body)


if __name__ == "__main__":
    unittest.main()
