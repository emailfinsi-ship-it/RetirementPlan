"""Fin, the robot guide: the drawing, and its place in the setup wizard."""

from __future__ import annotations

import unittest

from source.webapp.pages import setup_wizard
from source.webapp.render_helpers import robot
from tests.test_dashboard import DashboardTestCase


class TestRobotPieces(unittest.TestCase):
    def test_svg_has_a_mouth_to_animate_and_a_size(self):
        svg = robot.robot_svg(90)
        self.assertIn('class="rb-mouth"', svg)
        self.assertIn('width="90"', svg)
        self.assertNotIn("{size}", svg)

    def test_mouth_only_moves_while_talking_and_respects_reduced_motion(self):
        self.assertIn(".rb.talking .rb-mouth", robot.ROBOT_CSS)
        self.assertIn("prefers-reduced-motion", robot.ROBOT_CSS)

    def test_script_never_needs_speech_support(self):
        # It guards every speech call, so a browser without it just skips the voice.
        self.assertIn("synth()", robot.ROBOT_JS)
        self.assertIn("window.rpFin", robot.ROBOT_JS)


class TestWizardGuide(DashboardTestCase):
    def test_every_step_has_a_line_for_fin(self):
        self.assertEqual(len(setup_wizard.GUIDE_LINES), len(setup_wizard._STEPS))
        self.assertTrue(all(len(line) > 20 for line in setup_wizard.GUIDE_LINES))

    def test_wizard_shows_the_guide_with_voice_controls(self):
        body = self._get("/setup-wizard.html").read().decode("utf-8")
        self.assertIn('id="wz-guide"', body)
        self.assertIn('id="wz-bubble"', body)
        self.assertIn("wizardHear()", body)
        self.assertIn("wizardVoice()", body)
        self.assertIn("window.rpFin", body)
        self.assertIn(setup_wizard.GUIDE_LINES[0].split(",")[0], body)

    def test_css_braces_survived_the_page_template(self):
        body = self._get("/setup-wizard.html").read().decode("utf-8")
        self.assertIn(".rb.talking .rb-mouth {", body)
        self.assertNotIn(".rb-guide {{", body)
        self.assertIn(".rb-guide {", body)


if __name__ == "__main__":
    unittest.main()
