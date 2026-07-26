#!/usr/bin/env python3
"""Interview Tracker — macOS menu bar viewer backed by SQLite."""
import os
import subprocess
import threading
from pathlib import Path

import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

import database
import menubar_logic
import platform_utils

try:
    import local_server
except ImportError:
    local_server = None  # type: ignore[assignment]

ROOT = platform_utils.project_root()
DATA_DIR = platform_utils.default_data_dir()
DB_FILE = DATA_DIR / database.DEFAULT_DB_NAME
DASHBOARD_FILE = DATA_DIR / "dashboard.html"
SCAN_SCRIPT = ROOT / "bin" / "scan_gmail.py"
DEBUG_LOG = DATA_DIR / "logs" / "menubar_debug.log"

# No Dock icon / app switcher entry — menu bar only.
NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def parse_dt(value):
    return menubar_logic.parse_dt(value)


def fmt_dt(dt):
    return platform_utils.format_menubar_datetime(dt)


def is_rejected(r):
    return menubar_logic.is_rejected(r)


class InterviewTrackerApp(rumps.App):
    def __init__(self):
        super().__init__("Interview Tracker", title="💼 …")
        self.refreshing = False
        if local_server is not None:
            try:
                local_server.start_local_server()
            except Exception:
                pass
        self.load_data()
        self.rebuild_menu()
        rumps.Timer(self.check_for_local_updates, 60).start()
        self._last_mtime = self._current_mtime()

    def _current_mtime(self):
        try:
            return DB_FILE.stat().st_mtime
        except FileNotFoundError:
            return None

    def load_data(self):
        try:
            self.records = database.get_records(db_path=DB_FILE)
            self.summary = database.get_latest_summary(db_path=DB_FILE) or {}
        except Exception:
            self.records = []
            self.summary = {}

    def upcoming_records(self, limit=5):
        return menubar_logic.upcoming_records(self.records, limit=limit)

    def action_count(self):
        return menubar_logic.action_count(self.records)

    def rebuild_menu(self):
        upcoming = self.upcoming_records()
        self.title = "💼 …" if self.refreshing else f"💼 {len(upcoming)}"

        items = []
        total = self.summary.get("total", len(self.records))
        offers = self.summary.get("offers", sum(1 for r in self.records if r.get("stage") == "Offer"))
        items.append(rumps.MenuItem(f"Total tracked: {total}"))
        items.append(rumps.MenuItem(f"Your move: {self.action_count()}"))
        items.append(rumps.MenuItem(f"Upcoming: {len(upcoming)}"))
        items.append(rumps.MenuItem(f"Offers: {offers}"))
        items.append(rumps.separator)

        if upcoming:
            items.append(rumps.MenuItem("Upcoming interviews:"))
            for dt, r in upcoming:
                items.append(rumps.MenuItem(f"  {r.get('company', '?')} — {fmt_dt(dt)}"))
        else:
            items.append(rumps.MenuItem("No upcoming interviews scheduled"))
        items.append(rumps.separator)

        items.append(rumps.MenuItem("Open Full Dashboard", callback=self.open_dashboard))
        items.append(rumps.MenuItem("Settings", callback=self.open_settings))
        refresh_label = "Refreshing…" if self.refreshing else "Refresh Now"
        items.append(rumps.MenuItem(refresh_label, callback=None if self.refreshing else self.refresh_now))
        items.append(rumps.separator)
        items.append(rumps.MenuItem(f"Last scan: {self.summary.get('timestamp', 'never')}"))

        self.menu.clear()
        self.menu.update(items)

    def _open_url(self, url: str, fallback: Path):
        platform_utils.open_url_or_file(url, fallback)

    def open_dashboard(self, _sender):
        url = local_server.dashboard_url() if local_server else None
        self._open_url(url or "", DASHBOARD_FILE)

    def open_settings(self, _sender):
        if local_server is not None:
            try:
                local_server.start_local_server()
            except Exception:
                pass
        url = local_server.settings_url() if local_server else None
        self._open_url(url or "", DASHBOARD_FILE)

    def refresh_now(self, _sender):
        if self.refreshing:
            return
        self.refreshing = True
        self.rebuild_menu()
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self):
        try:
            subprocess.run(
                [platform_utils.resolve_python_for_subprocess(ROOT), str(SCAN_SCRIPT)],
                check=False,
                cwd=str(ROOT),
            )
        finally:
            self.refreshing = False
            self.load_data()
            self._last_mtime = self._current_mtime()
            self.rebuild_menu()

    def check_for_local_updates(self, _timer):
        if self.refreshing:
            return
        mtime = self._current_mtime()
        if mtime != self._last_mtime:
            self._last_mtime = mtime
            self.load_data()
            self.rebuild_menu()


if __name__ == "__main__":
    InterviewTrackerApp().run()
