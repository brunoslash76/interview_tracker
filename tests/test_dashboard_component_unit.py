"""Browser-component regression tests for dashboard controls."""

from __future__ import annotations

import shutil
import subprocess
import unittest

from tests.support import PROJECT_ROOT


class DashboardComponentTests(unittest.TestCase):
    harness = PROJECT_ROOT / "tests" / "dashboard_component_harness.js"
    template = PROJECT_ROOT / "dashboard_template.html"
    settings_template = PROJECT_ROOT / "settings_template.html"

    def run_scenario(self, scenario: str, template=None) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for dashboard component tests")
        result = subprocess.run(
            [node, str(self.harness), str(template or self.template), scenario],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"component scenario {scenario!r} failed:\n{result.stdout}\n{result.stderr}",
        )

    def test_theme_button_toggles_dark_mode(self) -> None:
        self.run_scenario("theme")

    def test_scan_button_opens_modal_and_posts_csrf_token(self) -> None:
        self.run_scenario("scan")

    def test_settings_theme_button_toggles_dark_mode(self) -> None:
        self.run_scenario("settings-theme", self.settings_template)

    def test_settings_reuses_dashboard_visual_tokens(self) -> None:
        dashboard = self.template.read_text(encoding="utf-8")
        settings = self.settings_template.read_text(encoding="utf-8")
        shared_tokens = (
            "--bg:#eef1f7",
            "--surface:#ffffff",
            "--accent:#5b5bf0",
            "--radius:14px",
            "--bg:#0c0e14",
            "--surface:#161a24",
            "--accent:#7b7bff",
        )
        for token in shared_tokens:
            with self.subTest(token=token):
                self.assertIn(token, dashboard)
                self.assertIn(token, settings)


if __name__ == "__main__":
    unittest.main()
