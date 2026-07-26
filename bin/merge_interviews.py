#!/usr/bin/env python3
"""Interview Tracker — merge a scan into SQLite and regenerate the dashboard.

Usage:
    merge_interviews.py <raw_extraction.json>   # merge a fresh scan, then render
    merge_interviews.py                         # no scan: just re-render from the store
"""
import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import database

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(
    os.environ.get(
        "INTERVIEW_TRACKER_DATA_DIR",
        Path.home() / "Library" / "Application Support" / "InterviewTracker",
    )
).expanduser()
DB_FILE = DATA_DIR / database.DEFAULT_DB_NAME
TEMPLATE_FILE = ROOT / "dashboard_template.html"
DASHBOARD_FILE = DATA_DIR / "dashboard.html"


def atomic_write(path: Path, content: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(path)


def render_dashboard(records):
    safe_json = json.dumps(records, ensure_ascii=False).replace("</", "<\\/")
    generated_at = html.escape(datetime.now().astimezone().strftime("%b %-d, %Y at %-I:%M %p"))
    template = TEMPLATE_FILE.read_text()
    return template.replace("__DATA_JSON__", safe_json).replace("__GENERATED_AT__", generated_at)


def main():
    if len(sys.argv) > 2:
        raise SystemExit("usage: merge_interviews.py [raw_extraction.json]")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) == 2:
        incoming = json.loads(Path(sys.argv[1]).read_text())
        if not isinstance(incoming, list):
            raise ValueError("raw extraction must be a JSON array")
        summary = database.merge_scan(incoming, db_path=DB_FILE)
        new_company_names = summary["new_company_names"]
        updated_count = summary["updated_count"]
    else:
        summary = None
        new_company_names = []
        updated_count = 0

    records = database.get_records(db_path=DB_FILE)
    atomic_write(DASHBOARD_FILE, render_dashboard(records))
    stats = database.compute_stats(records)
    action = "merged" if summary is not None else "rendered"
    print(
        f"{action}: {len(records)} total | {len(new_company_names)} new | "
        f"{updated_count} updated | stats={stats}"
    )
    if new_company_names:
        print("NEW: " + ", ".join(new_company_names), file=sys.stderr)


if __name__ == "__main__":
    main()
