"""Unit tests for durable and streamed scan progress."""

from __future__ import annotations

import json
import io
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tests.support import TemporaryDatabaseTestCase, load_bin_module


class StreamProtocolTests(unittest.TestCase):
    def setUp(self):
        self.scan_gmail = load_bin_module("scan_gmail")

    def test_discovery_output_deduplicates_thread_ids(self):
        raw = json.dumps(
            {"structured_output": {"thread_ids": ["t1", "t2", "t1", ""]}}
        )
        self.assertEqual(self.scan_gmail.parse_discovery_output(raw), ["t1", "t2"])

    def test_tool_results_advance_unique_thread_progress(self):
        pending: dict[str, str] = {}
        completed: set[str] = set()
        tool_event = {
            "type": "assistant",
            "message": {
                "content": [{
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "mcp__claude_ai_Gmail__get_thread",
                    "input": {"thread_id": "thread-a"},
                }]
            },
        }
        current, result = self.scan_gmail.process_stream_event(
            tool_event, pending, completed
        )
        self.assertEqual(current, "thread-a")
        self.assertIsNone(result)
        result_event = {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "tool-1"}]
            },
        }
        self.scan_gmail.process_stream_event(result_event, pending, completed)
        self.scan_gmail.process_stream_event(result_event, pending, completed)
        self.assertEqual(completed, {"thread-a"})

    def test_result_event_returns_structured_output(self):
        value = {"interviews": [], "latest_email_date_seen": None}
        _, result = self.scan_gmail.process_stream_event(
            {"type": "result", "structured_output": value}, {}, set()
        )
        self.assertEqual(result, value)

    def test_streaming_runner_tracks_tool_results_and_final_output(self):
        tool = {
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "id": "use-1",
                "name": "mcp__claude_ai_Gmail__get_thread",
                "input": {"thread_id": "thread-1"},
            }]},
        }
        result = {
            "type": "result",
            "structured_output": {
                "interviews": [],
                "latest_email_date_seen": None,
            },
        }
        fake_process = mock.Mock()
        fake_process.stdout = io.StringIO(
            "\n".join([
                json.dumps(tool),
                json.dumps({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "use-1"}
                ]}}),
                json.dumps(result),
            ]) + "\n"
        )
        fake_process.stderr = io.StringIO("diagnostic\n")
        fake_process.wait.return_value = 0
        emitter = mock.Mock()
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            log_file = Path(temp) / "scan.log"
            with mock.patch.object(
                self.scan_gmail.subprocess, "Popen", return_value=fake_process
            ):
                code, output, stderr = self.scan_gmail.run_streaming_extraction(
                    ["claude"],
                    cwd=Path(temp),
                    env={},
                    log_file=log_file,
                    emitter=emitter,
                    total=1,
                )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["interviews"], [])
        self.assertIn("diagnostic", stderr)
        self.assertTrue(any(call.kwargs.get("current") == 1 for call in emitter.emit.call_args_list))


class DurableProgressTests(TemporaryDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.scan_runner = load_bin_module("scan_runner")

    def test_progress_write_is_structured_and_atomic(self):
        path = self.scan_runner.progress_file(self.data_dir)
        self.scan_runner.write_progress_file(
            path,
            "extracting",
            run_id="run-1",
            source="scheduled",
            sequence=4,
            current=2,
            total=5,
            thread_id="t2",
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["source"], "scheduled")
        self.assertEqual(payload["current"], 2)
        self.assertEqual(payload["total"], 5)
        self.assertFalse(list(self.data_dir.glob(".scan_progress.json.*")))

    def test_snapshot_detects_external_scheduled_scan(self):
        self.scan_runner.lock_dir(self.data_dir).mkdir()
        self.scan_runner.write_progress_file(
            self.scan_runner.progress_file(self.data_dir),
            "extracting",
            run_id="scheduled-1",
            source="scheduled",
            sequence=3,
            current=1,
            total=4,
        )
        runner = self.scan_runner.ScanRunner(self.root, self.data_dir, self.db_path)
        snapshot = runner.snapshot()
        self.assertEqual(snapshot["state"], "running")
        self.assertEqual(snapshot["source"], "scheduled")
        self.assertEqual(snapshot["current"], 1)
        self.assertEqual(snapshot["total"], 4)


if __name__ == "__main__":
    unittest.main()
