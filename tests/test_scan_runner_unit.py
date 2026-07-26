"""Unit tests for bin/scan_runner.py."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tests.support import TemporaryDatabaseTestCase, load_bin_module


class ScanRunnerTests(TemporaryDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.scan_runner = load_bin_module("scan_runner")
        self.database = load_bin_module("database")
        self.database.initialize_database(self.db_path)
        self.script = self.root / "fake_scan.sh"

    def _runner(self, side_effect):
        return self.scan_runner.ScanRunner(
            self.root,
            self.data_dir,
            self.db_path,
            scan_script=self.script,
            subprocess_runner=mock.Mock(side_effect=side_effect),
        )

    def test_start_rejects_when_lock_held(self):
        (self.data_dir / "scan.lock").mkdir()
        runner = self._runner([])
        ok, payload = runner.start()
        self.assertFalse(ok)
        self.assertIn("already", payload["error"].lower())

    def test_successful_run_updates_snapshot(self):
        interviews = [
            {
                "thread_id": "t1",
                "company": "Co",
                "stage": "Initial Contact",
                "status": "Active",
            }
        ]
        prog = self.scan_runner.progress_file(self.data_dir)

        def fake_run(*args, **kwargs):
            self.scan_runner.write_progress_file(prog, "complete", "1")
            return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="IT_PROGRESS:complete\n")

        runner = self._runner(fake_run)
        with mock.patch.object(
            self.scan_runner.database,
            "get_latest_summary",
            return_value={"new_count": 1, "updated_count": 0},
        ):
            ok, _ = runner.start()
            self.assertTrue(ok)
            runner._worker.join(timeout=2)
        snap = runner.snapshot()
        self.assertEqual(snap["state"], "succeeded")
        self.assertEqual(snap["new_count"], 1)

    def test_parse_progress_line(self):
        self.assertEqual(self.scan_runner.parse_progress_line("IT_PROGRESS:extracting"), "extracting")
        self.assertIsNone(self.scan_runner.parse_progress_line("noise"))

    def test_busy_exit_marks_failed(self):
        prog = self.scan_runner.progress_file(self.data_dir)
        self.scan_runner.write_progress_file(prog, "busy", "scan lock held")

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 2, stdout="", stderr="")

        runner = self._runner(fake_run)
        ok, _ = runner.start()
        self.assertTrue(ok)
        runner._worker.join(timeout=2)
        snap = runner.snapshot()
        self.assertEqual(snap["state"], "failed")
        self.assertIn("already running", (snap["error"] or "").lower())


if __name__ == "__main__":
    unittest.main()
