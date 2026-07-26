"""Browser-component regression tests for dashboard controls."""

from __future__ import annotations

import shutil
import subprocess
import unittest

from tests.support import PROJECT_ROOT


class DashboardComponentTests(unittest.TestCase):
    harness = PROJECT_ROOT / "tests" / "dashboard_component_harness.js"
    template = PROJECT_ROOT / "dashboard_template.html"

    def run_scenario(self, scenario: str) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for dashboard component tests")
        result = subprocess.run(
            [node, str(self.harness), str(self.template), scenario],
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


if __name__ == "__main__":
    unittest.main()
