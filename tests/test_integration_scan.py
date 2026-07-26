"""Cross-platform integration tests for bin/scan_gmail.py."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests.support import (
    BIN_DIR,
    FIXTURES_DIR,
    IsolatedRuntimeTestCase,
    PROJECT_ROOT,
    database,
    write_fake_claude,
)


class ScanGmailPythonIntegrationTests(IsolatedRuntimeTestCase):
    def setUp(self):
        super().setUp()
        database.initialize_database(self.db_path)

    def _run_scan_python(self, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = self.env.copy()
        if extra_env:
            env.update(extra_env)
        python = PROJECT_ROOT / "venv" / "bin" / "python3"
        if not python.is_file():
            python = Path(sys.executable)
        return subprocess.run(
            [str(python), str(BIN_DIR / "scan_gmail.py")],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
        )

    def test_scan_gmail_py_merges_records(self):
        interviews = json.loads(
            (FIXTURES_DIR / "sample_interviews.json").read_text(encoding="utf-8")
        )
        fake_claude = write_fake_claude(self.root / "fake_claude", interviews)
        result = self._run_scan_python(extra_env={"CLAUDE_BIN": str(fake_claude)})
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        records = database.get_records(self.db_path)
        self.assertEqual(len(records), 1)
        self.assertFalse((self.data_dir / "scan.lock").exists())


if __name__ == "__main__":
    unittest.main()
