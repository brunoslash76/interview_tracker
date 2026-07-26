"""Unit tests for bin/scan_gmail.py."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from tests.support import TemporaryDatabaseTestCase, database, load_bin_module


class ScanGmailUnitTests(TemporaryDatabaseTestCase):
    def test_build_prompt_includes_recent_guardrail(self):
        scan_gmail = load_bin_module("scan_gmail")
        prompt = scan_gmail.build_prompt(
            "after:123",
            "recent-watermark",
            "2026-01-01T00:00:00Z",
            "me@example.com",
            '(from:"me@example.com")',
        )
        self.assertIn("RECENT-SCAN GUARDRAIL", prompt)
        self.assertIn("after:123", prompt)

    def test_build_prompt_includes_involvement_filter(self):
        scan_gmail = load_bin_module("scan_gmail")
        prompt = scan_gmail.build_prompt(
            "after:1",
            "overlap",
            "",
            "me@example.com",
            'from:"me@example.com"',
        )
        self.assertIn("involvement filter", prompt)

    def test_parse_claude_output_normalizes_envelope(self):
        scan_gmail = load_bin_module("scan_gmail")
        inner = {"interviews": [{"thread_id": "t1"}], "latest_email_date_seen": None}
        outer = {"result": json.dumps(inner)}
        parsed = scan_gmail.parse_claude_output(json.dumps(outer))
        self.assertEqual(len(parsed["interviews"]), 1)

    def test_main_returns_busy_when_lock_held(self):
        scan_gmail = load_bin_module("scan_gmail")
        lock = self.data_dir / "scan.lock"
        lock.mkdir()
        with mock.patch.object(scan_gmail, "_data_dir", return_value=self.data_dir):
            code = scan_gmail.main()
        self.assertEqual(code, 2)


class ScanGmailMainSuccessTests(TemporaryDatabaseTestCase):
    def test_main_runs_merge_on_success(self):
        scan_gmail = load_bin_module("scan_gmail")
        database.initialize_database(self.data_dir / database.DEFAULT_DB_NAME)
        fake_claude = self.root / "fake-claude"
        fake_claude.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        fake_claude.chmod(0o755)
        envelope = json.dumps(
            {
                "result": json.dumps(
                    {
                        "interviews": [],
                        "latest_email_date_seen": None,
                    }
                )
            }
        )

        def fake_run(cmd, **kwargs):
            if cmd[0] == str(fake_claude):
                return mock.Mock(returncode=0, stdout=envelope, stderr="")
            return mock.Mock(returncode=0, stdout="merged: 0 total\n", stderr="")

        with mock.patch.object(scan_gmail, "_data_dir", return_value=self.data_dir), mock.patch.object(
            scan_gmail.platform_utils, "resolve_claude_bin", return_value=str(fake_claude)
        ), mock.patch.object(scan_gmail.subprocess, "run", side_effect=fake_run):
            code = scan_gmail.main()
        self.assertEqual(code, 0)


class ScanGmailFailureTests(TemporaryDatabaseTestCase):
    def test_main_fails_when_claude_missing(self):
        scan_gmail = load_bin_module("scan_gmail")
        with mock.patch.object(scan_gmail, "_data_dir", return_value=self.data_dir), mock.patch.object(
            scan_gmail.platform_utils, "resolve_claude_bin", return_value=None
        ):
            code = scan_gmail.main()
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
