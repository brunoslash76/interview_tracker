#!/usr/bin/env python3
"""Interview Tracker — macOS menu bar viewer backed by SQLite."""
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

import database

try:
    import local_server
except ImportError:
    local_server = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(
    os.environ.get(
        "INTERVIEW_TRACKER_DATA_DIR",
        Path.home() / "Library" / "Application Support" / "InterviewTracker",
    )
).expanduser()
DB_FILE = DATA_DIR / database.DEFAULT_DB_NAME
DASHBOARD_FILE = DATA_DIR / "dashboard.html"
SCAN_SCRIPT = ROOT / "bin" / "scan_gmail.sh"
DEBUG_LOG = DATA_DIR / "logs" / "menubar_debug.log"

# No Dock icon / app switcher entry — menu bar only.
NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)


def parse_dt(value):
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def fmt_dt(dt):
    return dt.strftime("%a %b %-d, %-I:%M %p")


def is_rejected(r):
    s = (r.get("status") or "").lower()
    return any(w in s for w in ("reject", "withdraw", "declin"))


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
        now = datetime.now().astimezone()
        upcoming = []
        for r in self.records:
            if is_rejected(r):
                continue
            dt = parse_dt(r.get("interview_datetime"))
            if dt and dt >= now:
                upcoming.append((dt, r))
        upcoming.sort(key=lambda pair: pair[0])
        return upcoming[:limit]

    def action_count(self):
        """Count records where the ball is in the user's court: an upcoming
        interview, or a next-step naming an action still owed."""
        cues = ("take-home", "book ", "calendly", "not yet booked", "sign nda",
                "docusign", "complete", "respond", "reference")
        n = 0
        now = datetime.now().astimezone()
        for r in self.records:
            if is_rejected(r):
                continue
            dt = parse_dt(r.get("interview_datetime"))
            if dt and dt >= now:
                n += 1
                continue
            blob = ((r.get("next_steps") or "") + " " + (r.get("status") or "")).lower()
            if any(c in blob for c in cues):
                n += 1
        return n

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
        if url:
            subprocess.run(["/usr/bin/open", url], capture_output=True, text=True)
        else:
            subprocess.run(["/usr/bin/open", str(fallback)], capture_output=True, text=True)

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
            subprocess.run(["/bin/bash", str(SCAN_SCRIPT)], check=False)
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
