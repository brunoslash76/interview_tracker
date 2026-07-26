#!/usr/bin/env python3
"""Render and reload the Interview Tracker scheduler from SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import database
import platform_utils

if platform_utils.is_darwin():
    import scheduler_launchd as _backend
elif platform_utils.is_windows():
    import scheduler_windows as _backend
elif platform_utils.is_linux():
    import scheduler_systemd as _backend
else:
    _backend = None  # type: ignore[assignment]

# Re-export macOS helpers for tests and tooling.
if platform_utils.is_darwin():
    SCHEDULER_LABEL = _backend.SCHEDULER_LABEL
    build_plist_dict = _backend.build_plist_dict
    write_plist = _backend.write_plist
    bootout_scheduler = _backend.bootout_scheduler
    bootstrap_scheduler = _backend.bootstrap_scheduler
    _installed_plist_path = _backend._installed_plist_path


def sync_scheduler(
    root: Path,
    home: Path,
    data_dir: Path,
    db_path: Optional[Path] = None,
    load_agent: bool = True,
) -> dict[str, Any]:
    if _backend is None:
        raise RuntimeError("scheduler is not supported on this platform")
    database.initialize_database(db_path)
    intervals = database.get_enabled_scan_intervals(db_path)
    return _backend.sync_scheduler(root, home, data_dir, intervals, load_agent=load_agent)


def apply_settings_with_rollback(
    email: Any,
    scan_times: list[Any],
    root: Path,
    home: Path,
    data_dir: Path,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    if _backend is None:
        raise RuntimeError("scheduler is not supported on this platform")
    previous = database.get_user_settings(db_path)
    if platform_utils.is_darwin():
        installed = _backend._installed_plist_path()
        backup = installed.read_bytes() if installed.exists() else None
    else:
        backup = _backend.read_scheduler_backup(data_dir)
    try:
        saved = database.update_user_settings(email, scan_times, db_path)
        sync_scheduler(root, home, data_dir, db_path, load_agent=True)
        return {"status": "ok", **saved}
    except Exception:
        database.update_user_settings(
            previous["email"], previous["scan_times"], db_path
        )
        if platform_utils.is_darwin():
            _backend.restore_scheduler_backup(installed, backup)
        else:
            _backend.restore_scheduler_backup(data_dir, backup)
        raise


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Interview Tracker scheduler sync")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--data-dir", type=Path, default=platform_utils.default_data_dir())
    parser.add_argument("--db", type=Path)
    parser.add_argument("--no-load", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("sync", help="render and reload scheduler from SQLite")
    apply_parser = subparsers.add_parser("apply-settings", help="save settings and reload")
    apply_parser.add_argument("--payload", required=True, help="JSON settings payload")
    args = parser.parse_args(argv)

    db_path = args.db or (args.data_dir.expanduser() / database.DEFAULT_DB_NAME)
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
