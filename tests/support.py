"""Shared helpers for Interview Tracker tests."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = PROJECT_ROOT / "bin"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))

import database  # noqa: E402


def load_bin_module(name: str):
    path = BIN_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"tests_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TemporaryDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "InterviewTracker"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / database.DEFAULT_DB_NAME
        self.home_dir = self.root / "home"
        self.home_dir.mkdir(parents=True, exist_ok=True)


class IsolatedRuntimeTestCase(TemporaryDatabaseTestCase):
    """Temp HOME + INTERVIEW_TRACKER_DATA_DIR for shell integration tests."""

    def setUp(self):
        super().setUp()
        self.env = os.environ.copy()
        self.env["HOME"] = str(self.home_dir)
        self.env["INTERVIEW_TRACKER_DATA_DIR"] = str(self.data_dir)
        self.env["PATH"] = str(FIXTURES_DIR) + os.pathsep + self.env.get("PATH", "")
        self.logs_dir = self.data_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def run_shell(self, script: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = self.env.copy()
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["/bin/bash", str(script)],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
        )


def write_fake_claude(output_path: Path, interviews: list[dict[str, Any]]) -> Path:
    """Create an executable fake claude that prints the scan_gmail.sh envelope."""
    import json

    dates = [
        str(record["last_email_date"])
        for record in interviews
        if record.get("last_email_date")
    ]
    inner = json.dumps(
        {
            "interviews": interviews,
            "latest_email_date_seen": max(dates) if dates else None,
        }
    )
    envelope = json.dumps({"result": inner})
    script = output_path
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        f"""#!/bin/bash
if [[ -n "${{CLAUDE_ARGS_LOG:-}}" ]]; then
  printf '%s\\n' "$@" >> "${{CLAUDE_ARGS_LOG}}"
fi
cat <<'EOF'
{envelope}
EOF
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def init_test_database(db_path: Path | None = None) -> Path:
    path = db_path or (Path(tempfile.mkdtemp()) / "test.sqlite3")
    database.initialize_database(path)
    return path
