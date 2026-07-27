"""Tests for coverage configuration and README badge generation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import PROJECT_ROOT


class CoverageToolingTests(unittest.TestCase):
    def test_badge_generator_uses_report_percentage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "coverage.json"
            badge = root / "coverage.svg"
            report.write_text(
                json.dumps({"totals": {"percent_covered": 83.4}}),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "generate_coverage_badge.py"),
                    str(report),
                    str(badge),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            rendered = badge.read_text(encoding="utf-8")
            self.assertIn("coverage: 83%", rendered)
            self.assertIn("#97ca00", rendered)

    def test_full_gate_enforces_threshold_and_refreshes_badge(self):
        runner = (PROJECT_ROOT / "scripts" / "run_checks.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("coverage report --fail-under=80", runner)
        self.assertIn("coverage json -o coverage.json", runner)
        self.assertIn("coverage.svg", runner)
        self.assertIn("frontend-coverage.svg", runner)
        self.assertIn("coverage-summary.json", runner)

    def test_badge_generator_accepts_vitest_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "coverage-summary.json"
            badge = root / "frontend.svg"
            report.write_text(
                json.dumps({"total": {"statements": {"pct": 91.2}}}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "generate_coverage_badge.py"),
                    str(report),
                    str(badge),
                    "--label",
                    "frontend",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            rendered = badge.read_text(encoding="utf-8")
            self.assertIn("frontend: 91%", rendered)

    def test_readme_displays_generated_coverage_badges(self):
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("![Python coverage](coverage.svg)", readme)
        self.assertIn("![Frontend coverage](frontend-coverage.svg)", readme)


if __name__ == "__main__":
    unittest.main()
