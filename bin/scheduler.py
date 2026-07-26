#!/usr/bin/env python3
"""Render and reload the Interview Tracker launchd scheduler from SQLite."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import database

SCHEDULER_LABEL = "com.interview-tracker.scheduler"
DEFAULT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


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
    plist: dict[str, Any] = {
        "Label": SCHEDULER_LABEL,
        "ProgramArguments": ["/bin/bash", str(root / "bin" / "scan_gmail.sh")],
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
    db_path: Optional[Path] = None,
    load_agent: bool = True,
) -> dict[str, Any]:
    database.initialize_database(db_path)
    intervals = database.get_enabled_scan_intervals(db_path)
    installed = _installed_plist_path()
    plist = build_plist_dict(root, home, data_dir, intervals)
    write_plist(installed, plist)
    if load_agent:
        bootout_scheduler()
        bootstrap_scheduler(installed)
    return {"intervals": intervals, "installed_plist": str(installed)}


def apply_settings_with_rollback(
    email: Any,
    scan_times: list[Any],
    root: Path,
    home: Path,
    data_dir: Path,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    previous = database.get_user_settings(db_path)
    installed = _installed_plist_path()
    plist_backup = installed.read_bytes() if installed.exists() else None
    try:
        saved = database.update_user_settings(email, scan_times, db_path)
        sync_scheduler(root, home, data_dir, db_path, load_agent=True)
        return {"status": "ok", **saved}
    except Exception:
        database.update_user_settings(
            previous["email"], previous["scan_times"], db_path
        )
        if plist_backup is not None:
            installed.write_bytes(plist_backup)
            subprocess.run(["/usr/bin/plutil", "-lint", str(installed)], check=False)
            bootout_scheduler()
            bootstrap_scheduler(installed)
        raise


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Interview Tracker scheduler sync")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "INTERVIEW_TRACKER_DATA_DIR",
                Path.home() / "Library" / "Application Support" / "InterviewTracker",
            )
        ).expanduser(),
    )
    parser.add_argument("--db", type=Path)
    parser.add_argument("--no-load", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("sync", help="render and reload scheduler from SQLite")
    apply_parser = subparsers.add_parser("apply-settings", help="save settings and reload")
    apply_parser.add_argument("--payload", required=True, help="JSON settings payload")
    args = parser.parse_args(argv)

    db_path = args.db or (args.data_dir / database.DEFAULT_DB_NAME)
    if args.command in (None, "sync"):
        result = sync_scheduler(
            args.root.expanduser(),
            args.home.expanduser(),
            args.data_dir.expanduser(),
            db_path,
            load_agent=not args.no_load,
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "apply-settings":
        payload = json.loads(args.payload)
        result = apply_settings_with_rollback(
            payload.get("email", ""),
            payload.get("scan_times", []),
            args.root.expanduser(),
            args.home.expanduser(),
            args.data_dir.expanduser(),
            db_path,
        )
        print(json.dumps(result, indent=2))
        return 0
    parser.error("command required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
