"""Regression tests for the version-controlled Git hooks."""

from __future__ import annotations

import os
import subprocess
import unittest

from tests.support import PROJECT_ROOT


class GitHooksTests(unittest.TestCase):
    def test_hooks_are_executable_and_run_expected_check_levels(self):
        expectations = {
            ".githooks/pre-commit": "run_checks.sh\" quick",
            ".githooks/pre-push": "run_checks.sh\" full",
        }
        for relative_path, expected_command in expectations.items():
            with self.subTest(hook=relative_path):
                path = PROJECT_ROOT / relative_path
                self.assertTrue(path.is_file())
                self.assertTrue(os.access(path, os.X_OK))
                self.assertIn(
                    expected_command,
                    path.read_text(encoding="utf-8"),
                )

    def test_check_runner_rejects_unknown_mode(self):
        runner = PROJECT_ROOT / "scripts" / "run_checks.sh"
        result = subprocess.run(
            ["/bin/bash", str(runner), "unknown"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)

    def test_installer_configures_version_controlled_hooks(self):
        installer = (PROJECT_ROOT / "install.sh").read_text(encoding="utf-8")
        hook_installer = (
            PROJECT_ROOT / "scripts" / "install_git_hooks.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('scripts/install_git_hooks.sh"', installer)
        self.assertIn("core.hooksPath .githooks", hook_installer)


if __name__ == "__main__":
    unittest.main()
