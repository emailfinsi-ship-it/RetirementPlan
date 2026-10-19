"""The Mac launcher template must stay valid and fully filled in."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "assets" / "launcher.sh"


class LauncherTemplateTests(unittest.TestCase):
    def test_fills_in_and_parses(self):
        text = TEMPLATE.read_text()
        for key in ("@PORT@", "@SERVER_NAME@", "@DATA_FOLDER@", "@APP_NAME@"):
            self.assertIn(key, text)
        filled = (text.replace("@PORT@", "8898").replace("@SERVER_NAME@", "app-server")
                  .replace("@DATA_FOLDER@", "X").replace("@APP_NAME@", "App"))
        self.assertNotIn("@", filled.replace("$@", ""))
        out = subprocess.run(["bash", "-n"], input=filled, text=True, capture_output=True)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_handles_the_new_mac_problems(self):
        text = TEMPLATE.read_text()
        self.assertIn("com.apple.quarantine", text)
        self.assertIn("osascript", text)
        self.assertIn("launch.log", text)

    def test_explains_wrong_chip(self):
        text = TEMPLATE.read_text()
        self.assertIn("lipo -archs", text)
        self.assertIn("Rosetta", text)
        self.assertIn("Intel", text)

    def test_build_script_uses_template(self):
        self.assertIn("scripts/assets/launcher.sh", (ROOT / "scripts" / "build_mac_app.sh").read_text())


if __name__ == "__main__":
    unittest.main()
