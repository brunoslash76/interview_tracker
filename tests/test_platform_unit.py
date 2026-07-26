"""Unit tests for bin/platform_utils.py."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from tests.support import TemporaryDatabaseTestCase, load_bin_module


class PlatformUtilsTests(TemporaryDatabaseTestCase):
    def test_default_data_dir_honors_override(self):
        platform_utils = load_bin_module("platform_utils")
        with mock.patch.dict(os.environ, {"INTERVIEW_TRACKER_DATA_DIR": str(self.data_dir)}):
            self.assertEqual(platform_utils.default_data_dir(), self.data_dir)

    def test_default_data_dir_macos_layout(self):
        platform_utils = load_bin_module("platform_utils")
        with mock.patch.object(platform_utils, "is_windows", return_value=False), mock.patch.object(
            platform_utils, "is_linux", return_value=False
        ):
            with mock.patch.object(Path, "home", return_value=Path("/Users/tester")):
                self.assertEqual(
                    platform_utils.default_data_dir(),
                    Path("/Users/tester/Library/Application Support/InterviewTracker"),
                )

    def test_default_data_dir_linux_layout(self):
        platform_utils = load_bin_module("platform_utils")
        with mock.patch.object(platform_utils, "is_linux", return_value=True), mock.patch.object(
            platform_utils, "is_windows", return_value=False
        ):
            with mock.patch.dict(
                os.environ, {"XDG_DATA_HOME": "/home/tester/.local/share"}, clear=False
            ):
                self.assertEqual(
                    platform_utils.default_data_dir(),
                    Path("/home/tester/.local/share/InterviewTracker"),
                )

    def test_default_data_dir_windows_layout(self):
        platform_utils = load_bin_module("platform_utils")
        with mock.patch.object(platform_utils, "is_windows", return_value=True):
            with mock.patch.dict(
                os.environ, {"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"}, clear=False
            ):
                expected = Path(os.environ["LOCALAPPDATA"]) / "InterviewTracker"
                self.assertEqual(platform_utils.default_data_dir(), expected)

    def test_format_dashboard_timestamp_windows(self):
        platform_utils = load_bin_module("platform_utils")
        when = datetime(2026, 7, 25, 14, 5, tzinfo=datetime.now().astimezone().tzinfo)
        with mock.patch.object(platform_utils, "is_windows", return_value=True):
            formatted = platform_utils.format_dashboard_timestamp(when)
        self.assertIn("Jul", formatted)
        self.assertIn("2026", formatted)
        self.assertIn("2:05", formatted)

    def test_load_config_env_parses_values(self):
        platform_utils = load_bin_module("platform_utils")
        config_path = self.data_dir / "config.env"
        config_path.write_text('CLAUDE_BIN="/tmp/claude"\nNTFY_TOPIC=abc\n', encoding="utf-8")
        with mock.patch.dict(os.environ, {"INTERVIEW_TRACKER_CONFIG": str(config_path)}):
            values = platform_utils.load_config_env(self.data_dir)
        self.assertEqual(values["CLAUDE_BIN"], "/tmp/claude")
        self.assertEqual(values["NTFY_TOPIC"], "abc")

    def test_resolve_claude_bin_prefers_configured_path(self):
        platform_utils = load_bin_module("platform_utils")
        fake = self.root / "claude-custom"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        resolved = platform_utils.resolve_claude_bin(str(fake))
        self.assertEqual(resolved, str(fake))

    def test_format_menubar_datetime_on_macos(self):
        platform_utils = load_bin_module("platform_utils")
        when = datetime(2026, 3, 5, 15, 30, tzinfo=datetime.now().astimezone().tzinfo)
        with mock.patch.object(platform_utils, "is_windows", return_value=False), mock.patch.object(
            platform_utils, "is_linux", return_value=False
        ):
            formatted = platform_utils.format_menubar_datetime(when)
        self.assertIn("Mar", formatted)

    def test_systemd_user_unit_dir(self):
        platform_utils = load_bin_module("platform_utils")
        self.assertEqual(
            platform_utils.systemd_user_unit_dir(Path("/home/u")),
            Path("/home/u/.config/systemd/user"),
        )

    def test_default_path_env_linux(self):
        platform_utils = load_bin_module("platform_utils")
        with mock.patch.object(platform_utils, "is_linux", return_value=True):
            path_env = platform_utils.default_path_env()
        self.assertIn(".local/bin", path_env)
        self.assertIn("/usr/bin", path_env)


if __name__ == "__main__":
    unittest.main()
