"""Separate RMDs for the plan owner and the spouse: account Owner storage
(source.common.db.owners + assets.owner), the per-owner Tax-deferred
totals build_summary derives from it, and the Monte Carlo engine's
per-person RMD/withdrawal behavior (source.reporting.monte_carlo.pools)."""

from __future__ import annotations

import unittest

from source.common import db
from source.reporting import rmd
from source.reporting.aggregate import build_summary
from source.reporting.monte_carlo import deterministic_drawdown_schedule
from source.reporting.monte_carlo.pools import (
    _apply_year_withdrawal,
    _split_extra_tax_deferred,
    _sync_owner_balances,
    new_owner_state,
)
from tests.test_dashboard import DashboardTestCase
from tests.testing_utils import TempConfigTestCase

_COMMON = dict(gains_fraction=0.4, inflation_rate=0.0, apply_drawdown_tax=False)


class TestNewOwnerState(unittest.TestCase):
    def test_none_when_the_spouse_owns_no_tax_deferred_money(self):
        self.assertIsNone(new_owner_state(1_000_000, {}))
        self.assertIsNone(new_owner_state(1_000_000, {"spouse_tax_deferred_share": "0"}))
        self.assertIsNone(new_owner_state(1_000_000, {"spouse_tax_deferred_share": "garbage"}))

    def test_splits_the_pool_by_the_spouse_share(self):
        state = new_owner_state(1_000_000, {"spouse_tax_deferred_share": 0.25, "spouse_birth_year": "1962"})
        self.assertAlmostEqual(state["self"], 750_000)
        self.assertAlmostEqual(state["spouse"], 250_000)
        self.assertEqual(state["spouse_birth_year"], 1962)

    def test_unset_spouse_birth_year_is_none(self):
        state = new_owner_state(100, {"spouse_tax_deferred_share": 0.5})
        self.assertIsNone(state["spouse_birth_year"])


class TestSyncOwnerBalances(unittest.TestCase):
    def test_rescales_to_the_pools_current_total_keeping_proportions(self):
        owners = {"self": 600.0, "spouse": 400.0}
        _sync_owner_balances(owners, 2_000.0)  # e.g. after a year of growth
        self.assertAlmostEqual(owners["self"], 1_200.0)
        self.assertAlmostEqual(owners["spouse"], 800.0)

    def test_an_emptied_pool_zeroes_both(self):
        owners = {"self": 5.0, "spouse": 5.0}
        _sync_owner_balances(owners, 0.0)
        self.assertEqual(owners["self"], 0.0)
        self.assertEqual(owners["spouse"], 0.0)


class TestSplitExtraTaxDeferred(unittest.TestCase):
    def test_older_spouse_is_drawn_first(self):
        # self born 1955 (older), wife 1962: all of a small draw comes from self.
        from_self, from_spouse = _split_extra_tax_deferred(100.0, 500.0, 500.0, 1955, 1962)
        self.assertEqual((from_self, from_spouse), (100.0, 0.0))

    def test_younger_birth_year_older_spouse_flips_it(self):
        from_self, from_spouse = _split_extra_tax_deferred(100.0, 500.0, 500.0, 1965, 1958)
        self.assertEqual((from_self, from_spouse), (0.0, 100.0))

    def test_spills_to_the_other_once_the_older_is_exhausted(self):
        from_self, from_spouse = _split_extra_tax_deferred(700.0, 500.0, 500.0, 1955, 1962)
        self.assertEqual((from_self, from_spouse), (500.0, 200.0))

    def test_equal_or_unknown_birth_years_split_proportionally(self):
        self.assertEqual(_split_extra_tax_deferred(100.0, 300.0, 100.0, 1960, 1960), (75.0, 25.0))
        self.assertEqual(_split_extra_tax_deferred(100.0, 300.0, 100.0, None, 1960), (75.0, 25.0))
        self.assertEqual(_split_extra_tax_deferred(100.0, 300.0, 100.0, 1960, None), (75.0, 25.0))

    def test_never_exceeds_what_is_left(self):
        from_self, from_spouse = _split_extra_tax_deferred(10_000.0, 300.0, 100.0, 1955, 1962)
        self.assertEqual(from_self + from_spouse, 400.0)

    def test_nothing_to_draw_or_nothing_left(self):
        self.assertEqual(_split_extra_tax_deferred(0.0, 100.0, 100.0, 1955, 1962), (0.0, 0.0))
        self.assertEqual(_split_extra_tax_deferred(50.0, 0.0, 0.0, 1955, 1962), (0.0, 0.0))


class TestApplyYearWithdrawalWithOwners(unittest.TestCase):
    def _pools(self, td=1_000_000.0):
        return {"tax_deferred": td, "roth": 0.0, "taxable": 0.0, "real_estate": 0.0}

    def test_each_person_uses_their_own_age_and_start_age(self):
        # 2035: self (born 1955) is 80 -> RMD age 73 reached; wife (born
        # 1965) is 70 -> not yet (her RMD age is 75). Only HIS 60% share
        # owes an RMD, at age 80's divisor.
        pools = self._pools()
        owners = {"self": 600_000.0, "spouse": 400_000.0, "spouse_birth_year": 1965}
        result = _apply_year_withdrawal(
            pools, need=0.0, age=80, birth_year=1955, year=2035, owners=owners, **_COMMON,
        )
        expected_self = 600_000.0 / rmd.UNIFORM_LIFETIME_TABLE[80]
        self.assertAlmostEqual(result["rmd_by_owner"]["self"], expected_self)
        self.assertEqual(result["rmd_by_owner"]["spouse"], 0.0)
        self.assertAlmostEqual(result["rmd"], expected_self)

    def test_both_owe_an_rmd_and_they_sum(self):
        # 2040: self born 1955 is 85; wife born 1962 is 78 (both past 73/75).
        pools = self._pools()
        owners = {"self": 600_000.0, "spouse": 400_000.0, "spouse_birth_year": 1962}
        result = _apply_year_withdrawal(
            pools, need=0.0, age=85, birth_year=1955, year=2040, owners=owners, **_COMMON,
        )
        want_self = 600_000.0 / rmd.UNIFORM_LIFETIME_TABLE[85]
        want_spouse = 400_000.0 / rmd.UNIFORM_LIFETIME_TABLE[78]
        self.assertAlmostEqual(result["rmd_by_owner"]["self"], want_self)
        self.assertAlmostEqual(result["rmd_by_owner"]["spouse"], want_spouse)
        self.assertAlmostEqual(result["rmd"], want_self + want_spouse)
        # Owner balances drop by exactly their own RMD and still sum to the pool.
        self.assertAlmostEqual(owners["self"], 600_000.0 - want_self)
        self.assertAlmostEqual(owners["spouse"], 400_000.0 - want_spouse)
        self.assertAlmostEqual(owners["self"] + owners["spouse"], pools["tax_deferred"])

    def test_an_unset_spouse_birth_year_means_no_rmd_for_her(self):
        pools = self._pools()
        owners = {"self": 500_000.0, "spouse": 500_000.0, "spouse_birth_year": None}
        result = _apply_year_withdrawal(
            pools, need=0.0, age=85, birth_year=1955, year=2040, owners=owners, **_COMMON,
        )
        self.assertEqual(result["rmd_by_owner"]["spouse"], 0.0)
        self.assertGreater(result["rmd_by_owner"]["self"], 0.0)

    def test_an_unset_own_birth_year_means_no_rmd_for_me_but_hers_still_applies(self):
        pools = self._pools()
        owners = {"self": 500_000.0, "spouse": 500_000.0, "spouse_birth_year": 1950}
        result = _apply_year_withdrawal(
            pools, need=0.0, age=None, birth_year=None, year=2040, owners=owners, **_COMMON,
        )
        self.assertEqual(result["rmd_by_owner"]["self"], 0.0)
        self.assertGreater(result["rmd_by_owner"]["spouse"], 0.0)

    def test_extra_spending_beyond_the_rmds_comes_from_the_older_spouse_first(self):
        # Nothing taxable/roth, so every spending dollar must come from
        # Tax-deferred; self (born 1950) is older than wife (1960).
        pools = self._pools(100_000.0)
        owners = {"self": 50_000.0, "spouse": 50_000.0, "spouse_birth_year": 1960}
        # 2026: self is 76 (RMD at 73 applies), wife is 66 (no RMD yet).
        result = _apply_year_withdrawal(
            pools, need=20_000.0, age=76, birth_year=1950, year=2026, owners=owners, **_COMMON,
        )
        rmd_self = 50_000.0 / rmd.UNIFORM_LIFETIME_TABLE[76]
        extra = 20_000.0 - rmd_self
        # His account paid the RMD plus all the extra; hers is untouched.
        self.assertAlmostEqual(owners["self"], 50_000.0 - rmd_self - extra)
        self.assertAlmostEqual(owners["spouse"], 50_000.0)

    def test_owners_none_is_byte_identical_to_the_original_single_owner_path(self):
        base = _apply_year_withdrawal(
            self._pools(), need=30_000.0, age=80, birth_year=1950, year=2030, owners=None, **_COMMON,
        )
        self.assertNotIn("rmd_by_owner", base)
        again = _apply_year_withdrawal(
            self._pools(), need=30_000.0, age=80, birth_year=1950, year=2030, **_COMMON,
        )
        self.assertEqual(base, again)
        self.assertAlmostEqual(base["rmd"], 1_000_000.0 / rmd.UNIFORM_LIFETIME_TABLE[80])


class TestDeterministicScheduleWithSpouse(unittest.TestCase):
    _ASSUMPTIONS = {
        "expected_return": "0.05", "inflation_rate": "0", "plan_horizon_years": "6", "current_year": "2030",
        "birth_year": "1955", "spouse_birth_year": "1957", "apply_drawdown_tax": "0",
        "annual_income_offset": "0", "spouse_tax_deferred_share": "0.4",
    }

    def test_rows_carry_per_person_rmds_that_sum_to_the_total(self):
        schedule = deterministic_drawdown_schedule(
            pools={"tax_deferred": 1_000_000.0, "roth": 0.0, "taxable": 0.0, "real_estate": 0.0},
            expenses=[], assumptions=dict(self._ASSUMPTIONS),
        )
        self.assertTrue(schedule["has_spouse"])
        for row in schedule["rows"]:
            self.assertAlmostEqual(row["rmd_self"] + row["rmd_spouse"], row["rmd"])
            self.assertAlmostEqual(row["tax_deferred_self"] + row["tax_deferred_spouse"], row["tax_deferred"])
            self.assertEqual(row["spouse_age"], row["year"] - 1957)

    def test_without_a_spouse_share_there_are_no_per_person_fields(self):
        assumptions = dict(self._ASSUMPTIONS, spouse_tax_deferred_share="0")
        schedule = deterministic_drawdown_schedule(
            pools={"tax_deferred": 1_000_000.0, "roth": 0.0, "taxable": 0.0, "real_estate": 0.0},
            expenses=[], assumptions=assumptions,
        )
        self.assertFalse(schedule["has_spouse"])
        self.assertNotIn("rmd_self", schedule["rows"][0])

    def test_a_younger_spouse_starts_their_rmds_later(self):
        # Self born 1955 (RMD at 73 -> 2028); wife born 1962 (RMD at 75 ->
        # 2037). Over 2030-2035 only HIS RMDs are non-zero.
        assumptions = dict(self._ASSUMPTIONS, spouse_birth_year="1962")
        schedule = deterministic_drawdown_schedule(
            pools={"tax_deferred": 1_000_000.0, "roth": 0.0, "taxable": 0.0, "real_estate": 0.0},
            expenses=[], assumptions=assumptions,
        )
        for row in schedule["rows"]:
            self.assertGreater(row["rmd_self"], 0.0)
            self.assertEqual(row["rmd_spouse"], 0.0)


class TestOwnerStorage(TempConfigTestCase):
    def test_normalize_owner(self):
        self.assertEqual(db.normalize_owner(" Spouse "), "spouse")
        self.assertEqual(db.normalize_owner("SELF"), "self")
        self.assertEqual(db.normalize_owner("cousin"), "")
        self.assertEqual(db.normalize_owner(None), "")

    def test_asset_owner_defaults_to_unassigned(self):
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 1})
        self.assertEqual(db.get_line_item("assets", item_id)["owner"], "")

    def test_asset_owner_can_be_set_and_an_unknown_value_is_unassigned(self):
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 1, "owner": "spouse"})
        self.assertEqual(db.get_line_item("assets", item_id)["owner"], "spouse")
        db.update_line_item("assets", item_id, {"owner": "self"})
        self.assertEqual(db.get_line_item("assets", item_id)["owner"], "self")
        db.update_line_item("assets", item_id, {"owner": "somebody else"})
        self.assertEqual(db.get_line_item("assets", item_id)["owner"], "")

    def test_set_and_get_account_owner(self):
        db.set_account_owner("acc-1", "spouse")
        db.set_account_owner("acc-2", "self")
        self.assertEqual(db.get_account_owners(), {"acc-1": "spouse", "acc-2": "self"})
        db.set_account_owner("acc-1", "self")
        self.assertEqual(db.get_account_owners()["acc-1"], "self")

    def test_assigning_unassigned_removes_the_row(self):
        db.set_account_owner("acc-1", "spouse")
        db.set_account_owner("acc-1", "")
        self.assertEqual(db.get_account_owners(), {})

    def test_set_account_owner_requires_an_account_id(self):
        with self.assertRaises(ValueError):
            db.set_account_owner("  ", "self")

    def test_the_owner_column_migrates_onto_an_existing_database(self):
        with db.connect() as conn:
            conn.execute("ALTER TABLE assets DROP COLUMN owner")
            self.assertNotIn("owner", {r["name"] for r in conn.execute("PRAGMA table_info(assets)")})
        db.init_db()
        with db.connect() as conn:
            self.assertIn("owner", {r["name"] for r in conn.execute("PRAGMA table_info(assets)")})

    def test_spouse_birth_year_defaults_to_blank(self):
        self.assertEqual(db.get_assumptions().get("spouse_birth_year"), "")


class TestBuildSummaryByOwner(TempConfigTestCase):
    def _asset(self, name, balance, *, owner="", treatment="tax_deferred"):
        item_id = db.add_line_item("assets", {
            "kind": "asset", "category": "401k", "name": name, "balance": balance,
            "include_in_monte_carlo": 1, "owner": owner,
        })
        db.update_line_item("assets", item_id, {"tax_treatment": treatment})
        return item_id

    def test_tax_deferred_is_split_by_owner_and_unassigned_is_reported_separately(self):
        self._asset("My 401k", 600_000, owner="self")
        self._asset("Her IRA", 300_000, owner="spouse")
        self._asset("Mystery", 100_000, owner="")
        by_owner = build_summary()["tax_deferred_by_owner"]
        self.assertEqual(by_owner, {"self": 600_000, "spouse": 300_000, "unassigned": 100_000})

    def test_only_tax_deferred_money_counts(self):
        self._asset("Her Roth", 200_000, owner="spouse", treatment="roth")
        self._asset("Her IRA", 50_000, owner="spouse")
        self.assertEqual(build_summary()["tax_deferred_by_owner"]["spouse"], 50_000)

    def test_the_spouse_share_is_injected_into_the_assumptions(self):
        self._asset("My 401k", 750_000, owner="self")
        self._asset("Her IRA", 250_000, owner="spouse")
        s = build_summary()
        self.assertAlmostEqual(float(s["assumptions"]["spouse_tax_deferred_share"]), 0.25)
        self.assertAlmostEqual(s["drawdown_spouse_tax_deferred_share"], 0.25)

    def test_no_spouse_money_means_a_zero_share(self):
        self._asset("My 401k", 750_000, owner="self")
        self.assertEqual(float(build_summary()["assumptions"]["spouse_tax_deferred_share"]), 0.0)

    def test_the_derived_share_is_never_persisted(self):
        self._asset("Her IRA", 100_000, owner="spouse")
        build_summary()
        self.assertNotIn("spouse_tax_deferred_share", db.get_assumptions())

    def test_a_manually_split_account_follows_its_rows_owner(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-fidelity", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-401k", "name": "401K", "official_name": "401K", "type": "investment",
            "subtype": "401k", "mask": "1111",
            "balances": {"current": 400_000.0, "available": None, "iso_currency_code": "USD"},
        })
        item_id = self._asset("Her 401k", 0, owner="spouse")
        db.update_line_item("assets", item_id, {"linked_account_id": "acc-401k"})
        db.add_line_item("account_tax_splits", {"account_id": "acc-401k", "name": "Pre-tax", "tax_treatment": "tax_deferred", "amount": 300_000})
        db.add_line_item("account_tax_splits", {"account_id": "acc-401k", "name": "Roth", "tax_treatment": "roth", "amount": 100_000})
        self.assertEqual(build_summary()["tax_deferred_by_owner"]["spouse"], 300_000)

    def test_an_unlinked_live_account_takes_its_owner_from_account_owners(self):
        db.upsert_plaid_item(
            item_key="fidelity", plaid_item_id="item-fidelity", institution_id="ins_1",
            institution_name="Fidelity", products=["investments"], environment="sandbox",
            linked_at="2026-09-01T00:00:00+00:00",
        )
        db.upsert_plaid_account(item_key="fidelity", account={
            "account_id": "acc-ira", "name": "IRA", "official_name": "IRA", "type": "investment",
            "subtype": "ira", "mask": "2222",
            "balances": {"current": 80_000.0, "available": None, "iso_currency_code": "USD"},
        })
        before = build_summary()
        self.assertEqual(before["drawdown_tax_deferred_by_owner"]["unassigned"], 80_000)
        db.set_account_owner("acc-ira", "spouse")
        after = build_summary()
        self.assertEqual(after["drawdown_tax_deferred_by_owner"]["spouse"], 80_000)
        self.assertEqual(after["drawdown_tax_deferred_by_owner"]["unassigned"], 0)
        # The Monte Carlo-side pools never include an unlinked account.
        self.assertEqual(after["tax_deferred_by_owner"]["spouse"], 0)
        source = next(x for x in after["drawdown_sources"] if x["name"].endswith("IRA"))
        self.assertEqual(source["owner"], "spouse")
        self.assertEqual(source["owner_target"], {"kind": "account", "id": "acc-ira"})


class TestOwnerEndpointsAndPages(DashboardTestCase):
    def setUp(self):
        db.clear_section("assets")

    def test_account_owner_endpoint_saves_and_clears(self):
        status, payload = self._post("/api/account-owner/set", {"account_id": "acc-x", "owner": "spouse"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(db.get_account_owners().get("acc-x"), "spouse")
        self._post("/api/account-owner/set", {"account_id": "acc-x", "owner": ""})
        self.assertNotIn("acc-x", db.get_account_owners())

    def test_account_owner_endpoint_rejects_a_missing_account_id(self):
        status, payload = self._post("/api/account-owner/set", {"account_id": "", "owner": "self"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_spouse_birth_year_saves_through_the_assumptions_endpoint(self):
        status, _ = self._post("/api/assumptions", {"spouse_birth_year": "1962"})
        self.assertEqual(status, 200)
        self.assertEqual(db.get_assumptions()["spouse_birth_year"], "1962")

    def test_line_item_update_can_set_an_assets_owner(self):
        item_id = db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "A", "balance": 5})
        status, _ = self._post("/api/line-item/update", {"section": "assets", "id": item_id, "fields": {"owner": "spouse"}})
        self.assertEqual(status, 200)
        self.assertEqual(db.get_line_item("assets", item_id)["owner"], "spouse")

    def test_asset_page_shows_an_owner_column(self):
        db.add_line_item("assets", {"kind": "asset", "category": "401k", "name": "OwnerCol 401k", "balance": 5})
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn("<th>Owner</th>", body)
        self.assertIn('data-field="owner"', body)
        self.assertIn(">Person 2</option>", body)

    def test_drawdown_page_shows_owner_column_and_rmd_by_person_card(self):
        item_id = db.add_line_item("assets", {
            "kind": "asset", "category": "401k", "name": "Her 401k", "balance": 500_000,
            "include_in_monte_carlo": 1, "owner": "spouse",
        })
        db.update_line_item("assets", item_id, {"tax_treatment": "tax_deferred"})
        db.set_assumption("birth_year", "1955")
        db.set_assumption("spouse_birth_year", "1962")
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        # The per-account Owner column moved to the Linked Accounts tab with the tax-bucket table.
        self.assertIn("<th>Owner</th>", self._get("/linked-accounts.html").read().decode("utf-8"))
        self.assertIn("Required Minimum Distributions, by person", body)
        self.assertIn("RMD: Person 2", body)
        self.assertIn("Person 2 age", body)

    def test_drawdown_page_warns_about_unassigned_and_a_missing_wife_birth_year(self):
        db.add_line_item("assets", {
            "kind": "asset", "category": "401k", "name": "Unowned 401k", "balance": 200_000, "include_in_monte_carlo": 1,
        })
        item_id = db.add_line_item("assets", {
            "kind": "asset", "category": "401k", "name": "Hers", "balance": 100_000,
            "include_in_monte_carlo": 1, "owner": "spouse",
        })
        db.update_line_item("assets", item_id, {"tax_treatment": "tax_deferred"})
        db.set_assumption("spouse_birth_year", "")
        body = self._get("/drawdown-planning.html").read().decode("utf-8")
        self.assertIn("has no Owner yet", body)
        self.assertIn("Person 2", body)

    def test_monte_carlo_page_has_the_wife_birth_year_field(self):
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn('name="spouse_birth_year"', body)


if __name__ == "__main__":
    unittest.main()
