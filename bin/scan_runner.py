#!/usr/bin/env python3
"""Background coordinator for manual Gmail scans from the dashboard."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

import database
import platform_utils

PROGRESS_FILENAME = ".scan_progress.json"
LOCK_DIRNAME = "scan.lock"

KNOWN_PHASES = (
    "starting",
    "config",
    "extracting",
    "merging",
    "complete",
    "failed",
    "busy",
)


class ScanState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _empty_snapshot() -> dict[str, Any]:
    return {
        "state": ScanState.IDLE,
        "phase": "idle",
        "started_at": None,
        "finished_at": None,
        "elapsed_seconds": 0.0,
        "error": None,
        "new_count": 0,
        "updated_count": 0,
        "extracted_count": None,
        "run_id": None,
    }


def snapshot_to_dict(snap: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    state = snap["state"]
    state_value = state.value if isinstance(state, ScanState) else str(state)
    out = {
        "state": state_value,
        "phase": snap.get("phase", "idle"),
        "started_at": snap.get("started_at"),
        "finished_at": snap.get("finished_at"),
        "elapsed_seconds": round(float(snap.get("elapsed_seconds") or 0.0), 1),
        "error": snap.get("error"),
        "new_count": int(snap.get("new_count") or 0),
        "updated_count": int(snap.get("updated_count") or 0),
        "extracted_count": snap.get("extracted_count"),
        "run_id": snap.get("run_id"),
    }
    if out["started_at"] and state_value == ScanState.RUNNING.value:
        started = datetime.fromisoformat(str(out["started_at"]).replace("Z", "+00:00"))
        out["elapsed_seconds"] = round(
            max(0.0, (datetime.now(timezone.utc) - started).total_seconds()), 1
        )
    file_phase = read_progress_file(progress_file(data_dir)).get("phase")
    if state_value == ScanState.RUNNING.value and isinstance(file_phase, str) and file_phase:
        out["phase"] = file_phase
    return out


def progress_file(data_dir: Path) -> Path:
    return data_dir / PROGRESS_FILENAME


def lock_dir(data_dir: Path) -> Path:
    return data_dir / LOCK_DIRNAME


def read_progress_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_progress_file(path: Path, phase: str, detail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "phase": phase,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if detail:
        payload["detail"] = detail
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def parse_progress_line(line: str) -> Optional[str]:
    marker = "IT_PROGRESS:"
    stripped = line.strip()
    if stripped.startswith(marker):
        return stripped[len(marker) :].strip()
    return None


class ScanRunner:
    """Thread-safe single-flight scan launcher."""

    def __init__(
        self,
        root: Path,
        data_dir: Path,
        db_path: Path,
        scan_script: Optional[Path] = None,
        subprocess_runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
    ) -> None:
        self.root = root
        self.data_dir = data_dir
        self.db_path = db_path
        self.scan_script = scan_script or (root / "bin" / "scan_gmail.py")
        self._subprocess_runner = subprocess_runner or subprocess.run
        self._lock = threading.Lock()
        self._snapshot = _empty_snapshot()
        self._worker: Optional[threading.Thread] = None
        self._stop_poll = threading.Event()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snap = dict(self._snapshot)
        return snapshot_to_dict(snap, self.data_dir)

    def is_running(self) -> bool:
        with self._lock:
            return self._snapshot["state"] == ScanState.RUNNING

    def start(self) -> tuple[bool, dict[str, Any]]:
        with self._lock:
            if self._snapshot["state"] == ScanState.RUNNING:
                return False, {
                    "error": "scan already in progress",
                    "status": snapshot_to_dict(dict(self._snapshot), self.data_dir),
                }
            if lock_dir(self.data_dir).is_dir():
                return False, {
                    "error": "scan already in progress",
                    "status": snapshot_to_dict(dict(self._snapshot), self.data_dir),
                }
            run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            started_at = datetime.now(timezone.utc).isoformat()
            self._snapshot = _empty_snapshot()
            self._snapshot.update(
                {
                    "state": ScanState.RUNNING,
                    "phase": "starting",
                    "started_at": started_at,
                    "run_id": run_id,
                }
            )
            self._stop_poll.clear()
            self._worker = threading.Thread(target=self._run_scan, args=(run_id,), daemon=True)
            self._worker.start()
            return True, snapshot_to_dict(dict(self._snapshot), self.data_dir)

    def _run_scan(self, run_id: str) -> None:
        prog_path = progress_file(self.data_dir)
        write_progress_file(prog_path, "starting")
        env = os.environ.copy()
        env.setdefault("HOME", str(Path.home()))
        env["INTERVIEW_TRACKER_DATA_DIR"] = str(self.data_dir)

        stderr_lines: list[str] = []
        try:
            result = self._subprocess_runner(
                [
                    platform_utils.resolve_python_for_subprocess(self.root),
                    str(self.scan_script),
                ],
                cwd=str(self.root),
                env=env,
                capture_output=True,
                text=True,
                timeout=660,
            )
            if result.stderr:
                for line in result.stderr.splitlines():
                    phase = parse_progress_line(line)
                    if phase:
                        with self._lock:
                            if self._snapshot["state"] == ScanState.RUNNING:
                                self._snapshot["phase"] = phase
                    stderr_lines.append(line)
        except subprocess.TimeoutExpired:
            self._finish_failed(run_id, "scan timed out")
            write_progress_file(prog_path, "failed", "timeout")
            return
        except Exception as exc:
            self._finish_failed(run_id, str(exc))
            write_progress_file(prog_path, "failed", str(exc))
            return

        file_progress = read_progress_file(prog_path)
        phase = str(file_progress.get("phase") or "")
        if result.returncode == 2 or phase == "busy":
            self._finish_failed(run_id, "another scan is already running")
            write_progress_file(prog_path, "busy", "scan lock held")
            return
        if result.returncode != 0:
            detail = file_progress.get("detail") or result.stderr.strip() or "scan script failed"
            self._finish_failed(run_id, str(detail))
            write_progress_file(prog_path, "failed", str(detail))
            return

        summary = database.get_latest_summary(self.db_path) or {}
        with self._lock:
            self._snapshot["state"] = ScanState.SUCCEEDED
            self._snapshot["phase"] = "complete"
            self._snapshot["finished_at"] = datetime.now(timezone.utc).isoformat()
            self._snapshot["new_count"] = int(summary.get("new_count") or 0)
            self._snapshot["updated_count"] = int(summary.get("updated_count") or 0)
            detail = file_progress.get("detail")
            if isinstance(detail, str) and detail.isdigit():
                self._snapshot["extracted_count"] = int(detail)
        write_progress_file(prog_path, "complete")

    def _finish_failed(self, run_id: str, message: str) -> None:
        with self._lock:
            if self._snapshot.get("run_id") != run_id:
                return
            self._snapshot["state"] = ScanState.FAILED
            self._snapshot["phase"] = "failed"
            self._snapshot["error"] = message
            self._snapshot["finished_at"] = datetime.now(timezone.utc).isoformat()


def dashboard_payload(db_path: Path) -> dict[str, Any]:
    records = database.get_records(db_path)
    summary = database.get_latest_summary(db_path)
    generated_at = platform_utils.format_dashboard_timestamp()
    return {
        "records": records,
        "generated_at": generated_at,
        "summary": summary,
        "stats": database.compute_stats(records),
    }
