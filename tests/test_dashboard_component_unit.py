"""Static-export safety checks for legacy dashboard templates."""

from __future__ import annotations

import unittest

from tests.support import PROJECT_ROOT


class DashboardTemplateSafetyTests(unittest.TestCase):
    template = PROJECT_ROOT / "dashboard_template.html"
    settings_template = PROJECT_ROOT / "settings_template.html"

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
