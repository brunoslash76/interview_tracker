#!/usr/bin/env python3
"""Hermetic FastAPI server for Playwright full-stack tests."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "bin"))

from tests.support import load_bin_module  # noqa: E402

import database  # noqa: E402


def _seed_records(db_path: Path) -> None:
    database.initialize_database(db_path)
    records = []
    for index in range(15):
        records.append(
            {
                "thread_id": f"seed-{index}",
                "company": f"Company {index:02d}",
                "position": "Engineer",
                "stage": "Phone Screen" if index % 2 == 0 else "Initial Contact",
                "status": "Active",
                "last_email_date": "2026-07-01T12:00:00Z",
            }
        )
    database.import_records(records, db_path)


def _patch_scheduler(local_server) -> None:
    def apply_settings(email, scan_times, root, home, data_dir, db_path=None):
        saved = database.update_user_settings(email, scan_times, db_path or local_server.DB_FILE)
        return {"status": "ok", **saved}

    # Patch the exact scheduler module referenced by local_server. Loading
    # scheduler.py a second time creates a different module and leaves the
    # real launchd/systemd/schtasks backend active.
    local_server.scheduler.apply_settings_with_rollback = apply_settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("E2E_PORT", "8765")))
    args = parser.parse_args()

    data_dir = Path(os.environ["INTERVIEW_TRACKER_E2E_DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / database.DEFAULT_DB_NAME
    claude_bin = Path(os.environ["CLAUDE_BIN"])

    local_server = load_bin_module("local_server")
    local_server.DATA_DIR = data_dir
    local_server.DB_FILE = db_path
    local_server.STATE.host = args.host
    local_server.STATE.port = args.port

    _seed_records(db_path)
    _patch_scheduler(local_server)

    config_env = data_dir / "config.env"
    config_env.write_text(f'CLAUDE_BIN="{claude_bin}"\n', encoding="utf-8")

    config = uvicorn.Config(
        local_server.APP,
        host=args.host,
        port=args.port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 15
    while time.time() < deadline:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex((args.host, args.port)) == 0:
                break
        time.sleep(0.1)
    else:
        print("E2E server failed to start", file=sys.stderr)
        return 1

    print(f"E2E server ready at http://{args.host}:{args.port}/dashboard", flush=True)

    stop = threading.Event()

    def _shutdown(*_args):
        server.should_exit = True
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    stop.wait()
    thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
