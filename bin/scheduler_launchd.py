"""macOS launchd scheduler backend."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path
from typing import Any, Optional

import platform_utils

SCHEDULER_LABEL = "com.interview-tracker.scheduler"
DEFAULT_PATH = platform_utils.default_path_env()


def _agent_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _installed_plist_path() -> Path:
    return _agent_dir() / f"{SCHEDULER_LABEL}.plist"


def build_plist_dict(
    root: Path,
    home: Path,
    data_dir: Path,
    intervals: list[tuple[int, int]],
) -> dict[str, Any]:
    python = platform_utils.resolve_python_for_subprocess(root)
    plist: dict[str, Any] = {
        "Label": SCHEDULER_LABEL,
        "ProgramArguments": [python, str(root / "bin" / "scan_gmail.py")],
        "RunAtLoad": False,
        "WorkingDirectory": str(root),
        "StandardOutPath": str(data_dir / "logs" / "scheduler.out.log"),
        "StandardErrorPath": str(data_dir / "logs" / "scheduler.err.log"),
        "EnvironmentVariables": {
            "PATH": DEFAULT_PATH,
            "HOME": str(home),
            "INTERVIEW_TRACKER_DATA_DIR": str(data_dir),
        },
        "ProcessType": "Background",
    }
    if intervals:
        plist["StartCalendarInterval"] = [
            {"Hour": hour, "Minute": minute} for hour, minute in intervals
        ]
    return plist


def write_plist(path: Path, plist: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as handle:
        plistlib.dump(plist, handle)
    tmp.replace(path)
    subprocess.run(["/usr/bin/plutil", "-lint", str(path)], check=True, capture_output=True)


def gui_domain() -> str:
    uid = os.getuid()
    return f"gui/{uid}"


def bootout_scheduler() -> None:
    subprocess.run(
        ["/bin/launchctl", "bootout", f"{gui_domain()}/{SCHEDULER_LABEL}"],
        capture_output=True,
        text=True,
    )


def bootstrap_scheduler(installed: Path) -> None:
    domain = gui_domain()
    result = subprocess.run(
        ["/bin/launchctl", "bootstrap", domain, str(installed)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        subprocess.run(
            ["/bin/launchctl", "load", str(installed)],
            check=True,
            capture_output=True,
            text=True,
        )


def sync_scheduler(
    root: Path,
    home: Path,
    data_dir: Path,
    intervals: list[tuple[int, int]],
    load_agent: bool = True,
) -> dict[str, Any]:
    installed = _installed_plist_path()
    plist = build_plist_dict(root, home, data_dir, intervals)
    write_plist(installed, plist)
    if load_agent:
        bootout_scheduler()
        bootstrap_scheduler(installed)
    return {"intervals": intervals, "installed_plist": str(installed)}


def restore_scheduler_backup(installed: Path, backup: bytes | None) -> None:
    if backup is None:
        return
    installed.write_bytes(backup)
    subprocess.run(["/usr/bin/plutil", "-lint", str(installed)], check=False)
    bootout_scheduler()
    bootstrap_scheduler(installed)


def scheduler_state_path(data_dir: Path) -> Path:
    return data_dir / ".scheduler_launchd_backup"
