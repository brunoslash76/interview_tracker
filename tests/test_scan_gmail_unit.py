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

    def test_main_runs_streamed_extraction_for_discovered_threads(self):
        scan_gmail = load_bin_module("scan_gmail")
        database.initialize_database(self.data_dir / database.DEFAULT_DB_NAME)
        fake_claude = self.root / "fake-claude"
        fake_claude.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_claude.chmod(0o755)
        discovery = json.dumps({"structured_output": {"thread_ids": ["t1", "t1"]}})
        extracted = json.dumps({
            "interviews": [{
                "thread_id": "t1",
                "company": "Acme",
                "stage": "Phone Screen",
                "status": "Scheduled",
            }],
            "latest_email_date_seen": "2026-07-27T12:00:00Z",
        })

        def fake_run(cmd, **kwargs):
            if cmd[0] == str(fake_claude):
                return mock.Mock(returncode=0, stdout=discovery, stderr="")
            return mock.Mock(returncode=0, stdout="merged\n", stderr="")

        with mock.patch.object(scan_gmail, "_data_dir", return_value=self.data_dir), mock.patch.object(
            scan_gmail.platform_utils, "resolve_claude_bin", return_value=str(fake_claude)
        ), mock.patch.object(
            scan_gmail.subprocess, "run", side_effect=fake_run
        ), mock.patch.object(
            scan_gmail,
            "run_streaming_extraction",
            return_value=(0, extracted, ""),
        ) as streamed:
            code = scan_gmail.main()
        self.assertEqual(code, 0)
        self.assertEqual(streamed.call_args.kwargs["total"], 1)

    def test_main_rejects_undiscovered_extraction_thread(self):
        scan_gmail = load_bin_module("scan_gmail")
        database.initialize_database(self.data_dir / database.DEFAULT_DB_NAME)
        fake_claude = self.root / "fake-claude"
        fake_claude.write_text("", encoding="utf-8")
        discovery = json.dumps({"structured_output": {"thread_ids": ["expected"]}})
        extracted = json.dumps({
            "interviews": [{
                "thread_id": "unexpected", "company": "Acme",
                "stage": "Phone Screen", "status": "Active",
            }],
            "latest_email_date_seen": None,
        })
        with mock.patch.object(scan_gmail, "_data_dir", return_value=self.data_dir), mock.patch.object(
            scan_gmail.platform_utils, "resolve_claude_bin", return_value=str(fake_claude)
        ), mock.patch.object(
            scan_gmail.subprocess, "run",
            return_value=mock.Mock(returncode=0, stdout=discovery, stderr=""),
        ), mock.patch.object(
            scan_gmail, "run_streaming_extraction",
            return_value=(0, extracted, ""),
        ):
            code = scan_gmail.main()
        self.assertEqual(code, 1)
        progress = json.loads((self.data_dir / ".scan_progress.json").read_text())
        self.assertIn("undiscovered", progress["error"])

    def test_main_reports_stream_process_failure(self):
        scan_gmail = load_bin_module("scan_gmail")
        database.initialize_database(self.data_dir / database.DEFAULT_DB_NAME)
        fake_claude = self.root / "fake-claude"
        fake_claude.write_text("", encoding="utf-8")
        discovery = json.dumps({"structured_output": {"thread_ids": ["t1"]}})
        with mock.patch.object(scan_gmail, "_data_dir", return_value=self.data_dir), mock.patch.object(
            scan_gmail.platform_utils, "resolve_claude_bin", return_value=str(fake_claude)
        ), mock.patch.object(
            scan_gmail.subprocess, "run",
            return_value=mock.Mock(returncode=0, stdout=discovery, stderr=""),
        ), mock.patch.object(
            scan_gmail, "run_streaming_extraction",
            return_value=(1, "", "old Claude CLI"),
        ):
            code = scan_gmail.main()
        self.assertEqual(code, 1)
        progress = json.loads((self.data_dir / ".scan_progress.json").read_text())
        self.assertIn("old Claude CLI", progress["error"])


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
