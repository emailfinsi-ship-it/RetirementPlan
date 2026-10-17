"""Household settings (names, optional second person), the display-only
brand, and the app's health/quit endpoints."""

from __future__ import annotations

import unittest
from pathlib import Path
from source.common import app_settings, branding, config, db, secrets_store
from source.reporting import benefits, plan_health
from source.reporting.aggregate import build_summary
from tests.test_dashboard import DashboardTestCase
from tests.testing_utils import TempConfigTestCase


class TestHouseholdSettings(TempConfigTestCase):
    def test_defaults_are_neutral_and_two_people(self):
        self.assertEqual(db.household(), {"self_name": "Person 1", "spouse_name": "Person 2", "has_spouse": True})
        self.assertEqual([label for _, label in db.owner_options()], ["Unassigned", "Person 1", "Person 2"])

    def test_names_round_trip_and_blank_falls_back(self):
        db.set_household(self_name="  Maya ", spouse_name="Jo", has_spouse=True)
        self.assertEqual(db.self_name(), "Maya")
        self.assertEqual(db.spouse_name(), "Jo")
        db.set_household(self_name="", spouse_name="", has_spouse=True)
        self.assertEqual(db.self_name(), "Person 1")

    def test_one_person_household_drops_the_second_owner(self):
        db.set_household(self_name="Maya", spouse_name="Jo", has_spouse=False)
        self.assertFalse(db.has_spouse())
        self.assertEqual(db.owner_options(), (("", "Unassigned"), ("self", "Maya")))

    def test_build_summary_carries_the_household(self):
        db.set_household(self_name="Maya", spouse_name="Jo", has_spouse=False)
        self.assertEqual(build_summary()["household"]["self_name"], "Maya")

    def test_plan_health_uses_the_names_and_skips_a_missing_second_person(self):
        summary = {
            "assumptions": {"apply_drawdown_tax": "1"},
            "household": {"self_name": "Maya", "spouse_name": "Jo", "has_spouse": False},
            "drawdown_tax_deferred_by_owner": {"self": 1.0, "spouse": 50.0, "unassigned": 0.0},
            "expenses": [{"name": "x"}], "income": [], "retirement_pools": {"tax_deferred": 1.0}, "real_estate": [],
        }
        texts = " | ".join(i["text"] for i in plan_health.plan_health_items(summary))
        self.assertIn("Maya's birth year", texts)
        self.assertNotIn("Jo", texts)


class TestBenefitsPlannerFollowsTheHousehold(TempConfigTestCase):
    _A = {"birth_year": "1965", "spouse_birth_year": "1967", "ss_benefit_self": "30000", "ss_claim_age_self": "67",
          "ss_benefit_spouse": "20000", "ss_claim_age_spouse": "62"}

    def test_rows_are_named_after_the_household(self):
        db.set_household(self_name="Maya", spouse_name="Jo", has_spouse=True)
        names = {r["name"] for r in benefits.planned_rows(self._A)["income"]}
        self.assertEqual(names, {"Social Security (Maya)", "Social Security (Jo)"})

    def test_a_one_person_household_has_one_person(self):
        db.set_household(self_name="Maya", spouse_name="Jo", has_spouse=False)
        self.assertEqual([p["name"] for p in benefits.planner_people(self._A)], ["Maya"])
        self.assertEqual([r["name"] for r in benefits.planned_rows(self._A)["income"]], ["Social Security (Maya)"])

    def test_apply_removes_rows_for_someone_no_longer_in_the_plan(self):
        db.set_household(self_name="Maya", spouse_name="Jo", has_spouse=True)
        benefits.apply_benefits_plan(self._A)
        self.assertEqual(len(db.list_line_items("income")), 2)
        db.set_household(self_name="Maya", spouse_name="Jo", has_spouse=False)
        result = benefits.apply_benefits_plan(self._A)
        self.assertEqual(result["removed"], ["Social Security (Jo)"])
        self.assertEqual([r["name"] for r in db.list_line_items("income")], ["Social Security (Maya)"])

    def test_apply_after_a_rename_does_not_double_count(self):
        db.set_household(self_name="Maya", spouse_name="Jo", has_spouse=False)
        benefits.apply_benefits_plan(self._A)
        db.set_household(self_name="Mia", spouse_name="Jo", has_spouse=False)
        benefits.apply_benefits_plan(self._A)
        self.assertEqual([r["name"] for r in db.list_line_items("income")], ["Social Security (Mia)"])

    def test_rows_the_user_typed_are_never_removed(self):
        db.add_line_item("income", {"name": "Pension", "category": "Pension", "annual_amount": 1000})
        db.set_household(self_name="Maya", spouse_name="Jo", has_spouse=False)
        benefits.apply_benefits_plan(self._A)
        self.assertIn("Pension", [r["name"] for r in db.list_line_items("income")])


class TestHouseholdPages(DashboardTestCase):
    def tearDown(self):
        db.set_household(self_name="", spouse_name="", has_spouse=True)

    def test_household_endpoint_saves_and_pages_use_the_names(self):
        status, payload = self._post("/api/household", {"self_name": "Maya", "spouse_name": "Jo", "has_spouse": True})
        self.assertEqual(status, 200)
        self.assertEqual(payload["household"]["self_name"], "Maya")
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertIn("Maya&#x27;s birth year (for RMDs)", body.replace("Maya's", "Maya&#x27;s"))
        self.assertIn("Jo", body)
        self.assertNotIn("Sri", body)
        self.assertNotIn("Anu", body)

    def test_one_person_household_hides_the_second_birth_year_field(self):
        self._post("/api/household", {"self_name": "Maya", "spouse_name": "Jo", "has_spouse": False})
        body = self._get("/monte-carlo.html").read().decode("utf-8")
        self.assertNotIn('name="spouse_birth_year"', body)
        asset = self._get("/asset.html").read().decode("utf-8")
        self.assertNotIn(">Jo</option>", asset)

    def test_setup_page_has_the_household_card_and_quit_button(self):
        body = self._get("/setup.html").read().decode("utf-8")
        self.assertIn('id="household"', body)
        self.assertIn("/api/household", body)
        self.assertIn("Quit " + branding.PRODUCT_NAME, body)

    def test_add_modal_owner_options_follow_the_household(self):
        self._post("/api/household", {"self_name": "Maya", "spouse_name": "Jo", "has_spouse": True})
        body = self._get("/asset.html").read().decode("utf-8")
        self.assertIn('<select name="owner"><option value="">Unassigned</option><option value="self">Maya</option><option value="spouse">Jo</option></select>', body)


class TestBranding(DashboardTestCase):
    def test_product_name(self):
        self.assertTrue(branding.PRODUCT_NAME.strip())

    def test_pages_carry_the_product_name_and_no_personal_names(self):
        for path in ("/summary.html", "/setup.html", "/drawdown-planning.html", "/expense.html", "/asset.html"):
            body = self._get(path).read().decode("utf-8")
            self.assertIn(f"<title>{branding.PRODUCT_NAME} -- ", body, path)
            self.assertNotIn("Retirement Plan --", body, path)
            self.assertIn('src="/icons/logo.svg"', body, path)
            self.assertIn(branding.PRODUCT_TAGLINE, body, path)
            self.assertIn(branding.PRODUCT_HEADLINE, body, path)
            self.assertIn(branding.PRODUCT_MOTTO, body, path)
            self.assertNotIn("Sri", body, path)
            self.assertNotIn("Anu", body, path)

    def test_health_endpoint_is_public_and_names_the_app(self):
        resp = self._get("/api/health")
        self.assertEqual(resp.status, 200)
        self.assertIn(branding.PRODUCT_NAME.encode(), resp.read())


class TestLoginBranding(DashboardTestCase):
    def test_login_header_shows_logo_tagline_and_headline(self):
        from source.webapp.pages.login import _render_login_page

        page = _render_login_page()
        for text in (branding.PRODUCT_NAME, branding.PRODUCT_TAGLINE, branding.PRODUCT_HEADLINE,
                     branding.PRODUCT_SUBLINE, branding.PRODUCT_MOTTO, "/icons/logo.svg"):
            self.assertIn(text, page)

    def test_logo_is_served_without_login(self):
        resp = self._get("/icons/logo.svg")
        self.assertEqual(resp.status, 200)
        self.assertIn("image/svg+xml", resp.getheader("Content-Type"))


class TestBrandIsDisplayOnly(unittest.TestCase):
    """Renaming the product must never touch stored data: the Keychain
    service, the settings folder and the app-bundle data folder are keyed
    to branding.INTERNAL_ID, not to the brand."""

    def test_internal_id_is_fixed_and_brand_free(self):
        self.assertEqual(branding.INTERNAL_ID, "RetirementPlan")
        self.assertNotIn(branding.PRODUCT_NAME.lower(), branding.INTERNAL_ID.lower())

    def test_keychain_service_is_the_internal_id(self):
        self.assertEqual(secrets_store.SERVICE_NAME, branding.INTERNAL_ID)

    def test_settings_folder_is_the_internal_id(self):
        self.assertEqual(app_settings._SETTINGS_DIR.name, branding.INTERNAL_ID)

    def test_brand_text_appears_only_in_branding_py_among_source_python(self):
        import re

        root = Path(config.__file__).resolve().parent.parent
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == "branding.py":
                continue
            text = path.read_text(encoding="utf-8")
            if re.search(re.escape(branding.PRODUCT_NAME), text):
                offenders.append(str(path.relative_to(root)))
        self.assertEqual(offenders, [], "the brand name must come from source.common.branding")


class TestAppBundleDataLocation(unittest.TestCase):
    def test_inside_an_app_bundle_data_goes_to_application_support(self):
        base = config.resolve_base_dir(
            frozen=True, executable="/Applications/Brand.app/Contents/Resources/server/app-server",
            module_file="/ignored",
        )
        self.assertEqual(base, Path.home() / "Library" / "Application Support" / branding.INTERNAL_ID)

    def test_a_plain_frozen_folder_keeps_data_beside_the_executable(self):
        base = config.resolve_base_dir(frozen=True, executable="/opt/tool/server", module_file="/ignored")
        self.assertEqual(base, Path("/opt/tool"))

    def test_running_from_source_uses_the_project_root(self):
        base = config.resolve_base_dir(frozen=False, executable="/usr/bin/python3", module_file=config.__file__)
        self.assertTrue((base / "source").is_dir())


if __name__ == "__main__":
    unittest.main()
