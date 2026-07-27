#!/usr/bin/env python3
"""Interview Tracker — desktop system tray viewer backed by SQLite."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import database
import menubar_logic
import platform_utils

try:
    import local_server
except ImportError:
    local_server = None  # type: ignore[assignment]

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover - optional at import on headless dev
    raise SystemExit(
        "pystray and Pillow are required for the tray app. "
        "Install with: pip install -r requirements-linux.txt (Linux) or "
        "requirements-windows.txt (Windows)."
    ) from exc

ROOT = platform_utils.project_root()
DATA_DIR = platform_utils.default_data_dir()
DB_FILE = DATA_DIR / database.DEFAULT_DB_NAME
DASHBOARD_FILE = DATA_DIR / "dashboard.html"
SCAN_SCRIPT = ROOT / "bin" / "scan_gmail.py"
POLL_SECONDS = 60


def fmt_dt(dt):
    return platform_utils.format_menubar_datetime(dt)


class TrayApp:
    def __init__(self) -> None:
        self.refreshing = False
        self.records: list[dict] = []
        self.summary: dict = {}
        self._last_mtime: float | None = None
        self._last_hash = ""
        self._stop_poll = threading.Event()
        if local_server is not None:
            try:
                local_server.start_local_server()
            except Exception:
                pass
        self.load_data()
        self.icon = pystray.Icon(
            "InterviewTracker",
            self._build_icon_image(),
            "Interview Tracker",
            menu=self._build_menu(),
        )
        self._last_mtime = self._current_mtime()

    def _build_icon_image(self):
        image = Image.new("RGB", (64, 64), color=(34, 139, 34))
        draw = ImageDraw.Draw(image)
        draw.rectangle((16, 16, 48, 48), fill=(255, 255, 255))
        return image

    def _current_mtime(self) -> float | None:
        try:
            return DB_FILE.stat().st_mtime
        except FileNotFoundError:
            return None

    def load_data(self) -> None:
        try:
            self.records = database.get_records(db_path=DB_FILE)
            self.summary = database.get_latest_summary(db_path=DB_FILE) or {}
        except Exception:
            self.records = []
            self.summary = {}

    def upcoming_records(self, limit: int = 5):
        return menubar_logic.upcoming_records(self.records, limit=limit)

    def action_count(self) -> int:
        return menubar_logic.action_count(self.records)

    def _open_url(self, url: str, fallback: Path) -> None:
        platform_utils.open_url_or_file(url, fallback)

    def open_dashboard(self, _icon, _item) -> None:
        url = local_server.dashboard_url() if local_server else ""
        self._open_url(url, DASHBOARD_FILE)

    def open_settings(self, _icon, _item) -> None:
        if local_server is not None:
            try:
                local_server.start_local_server()
            except Exception:
                pass
        url = local_server.settings_url() if local_server else ""
        self._open_url(url, DASHBOARD_FILE)

    def refresh_now(self, _icon, _item) -> None:
        if self.refreshing:
            return
        self.refreshing = True
        self.icon.menu = self._build_menu()
        threading.Thread(target=self._run_scan, daemon=True).start()

    def _run_scan(self) -> None:
        import subprocess

        try:
            subprocess.run(
                [
                    platform_utils.resolve_python_for_subprocess(ROOT),
                    str(SCAN_SCRIPT),
                    "--source",
                    "tray",
                ],
                cwd=str(ROOT),
                check=False,
            )
        finally:
            self.refreshing = False
            self.load_data()
            self._last_mtime = self._current_mtime()
            self.icon.menu = self._build_menu()

    def quit_app(self, _icon, _item) -> None:
        self.icon.stop()

    def _build_menu(self):
        upcoming = self.upcoming_records()
        total = self.summary.get("total", len(self.records))
        offers = self.summary.get(
            "offers", sum(1 for r in self.records if r.get("stage") == "Offer")
        )
        refresh_label = "Refreshing…" if self.refreshing else "Refresh Now"
        items = [
            pystray.MenuItem(f"Total tracked: {total}", None, enabled=False),
            pystray.MenuItem(f"Your move: {self.action_count()}", None, enabled=False),
            pystray.MenuItem(f"Upcoming: {len(upcoming)}", None, enabled=False),
            pystray.MenuItem(f"Offers: {offers}", None, enabled=False),
            pystray.Menu.SEPARATOR,
        ]
        if upcoming:
            items.append(pystray.MenuItem("Upcoming interviews:", None, enabled=False))
            for dt, record in upcoming:
                label = f"  {record.get('company', '?')} — {fmt_dt(dt)}"
                items.append(pystray.MenuItem(label, None, enabled=False))
        else:
            items.append(pystray.MenuItem("No upcoming interviews scheduled", None, enabled=False))
        items.extend(
            [
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Open Full Dashboard", self.open_dashboard),
                pystray.MenuItem("Settings", self.open_settings),
                pystray.MenuItem(refresh_label, self.refresh_now if not self.refreshing else None),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    f"Last scan: {self.summary.get('timestamp', 'never')}",
                    None,
                    enabled=False,
                ),
                pystray.MenuItem("Exit", self.quit_app),
            ]
        )
        return pystray.Menu(*items)

    def _maybe_notify(self) -> None:
        summary = database.get_latest_summary(db_path=DB_FILE)
        if not summary:
            return
        current_hash = str(summary.get("data_hash") or "")
        if not current_hash or current_hash == self._last_hash:
            return
        self._last_hash = current_hash
        import notifier

        notifier.run_check(data_dir=DATA_DIR, arg="tray-poll")

    def _poll_loop(self) -> None:
        while not self._stop_poll.wait(POLL_SECONDS):
            if not self.refreshing:
                mtime = self._current_mtime()
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    self.load_data()
                    self.icon.menu = self._build_menu()
                    if platform_utils.is_windows():
                        self._maybe_notify()

    def run(self) -> None:
        threading.Thread(target=self._poll_loop, daemon=True).start()
        try:
            self.icon.run()
        finally:
            self._stop_poll.set()


if __name__ == "__main__":
    if not (platform_utils.is_windows() or platform_utils.is_linux()):
        raise SystemExit("tray_app.py is intended for Windows and Linux desktop sessions.")
    TrayApp().run()
