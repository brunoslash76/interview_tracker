#!/usr/bin/env python3
"""Hash-gated scan notifications (macOS alerts, Windows toast, optional ntfy)."""

from __future__ import annotations

import json
import subprocess
import sys
import os
import shutil
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import database
import platform_utils

ROOT = platform_utils.project_root()


def _log(log_file: Path, message: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def dashboard_open_url(data_dir: Path) -> str:
    port_file = data_dir / ".http_port"
    dashboard = data_dir / "dashboard.html"
    if port_file.is_file():
        port = port_file.read_text(encoding="utf-8").strip()
        if port.isdigit():
            return f"http://127.0.0.1:{port}/dashboard"
    return dashboard.resolve().as_uri()


def notify_body(summary: dict[str, object]) -> str:
    total = summary.get("total", 0)
    upcoming = summary.get("upcoming", 0)
    offers = summary.get("offers", 0)
    new_names = summary.get("new_company_names") or []
    if new_names:
        return f"Total {total} · Upcoming {upcoming} · Offers {offers}. New: {', '.join(new_names)}."
    return f"Total {total} · Upcoming {upcoming} · Offers {offers}. Existing records updated."


def send_ntfy(topic: str, body: str, open_url: str) -> int:
    curl = shutil.which("curl")
    if curl:
        result = subprocess.run(
            [
                curl,
                "-s",
                "-o",
                os.devnull,
                "-w",
                "%{http_code}",
                "-d",
                body,
                "-H",
                "Title: Interview Tracker updated",
                "-H",
                "Tags: briefcase",
                "-H",
                f"Click: {open_url}",
                f"https://ntfy.sh/{topic}",
            ],
            capture_output=True,
            text=True,
        )
        code_text = (result.stdout or "0").strip()
        return int(code_text) if code_text.isdigit() else 0
    request = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=body.encode("utf-8"),
        headers={
            "Title": "Interview Tracker updated",
            "Tags": "briefcase",
            "Click": open_url,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def show_platform_notification(title: str, body: str, open_url: str, log_file: Path) -> None:
    if platform_utils.is_darwin():
        tn = shutil.which("terminal-notifier")
        if tn:
            if subprocess.run(
                [tn, "-title", title, "-message", body, "-open", open_url, "-sound", "default"],
                capture_output=True,
                text=True,
            ).returncode == 0:
                _log(log_file, "sent via terminal-notifier")
                return
        escaped = body.replace('"', '\\"')
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{escaped}" with title "{title}"',
            ],
            capture_output=True,
            text=True,
        )
        _log(log_file, "sent via osascript (or failed)")
        return
    if platform_utils.is_linux():
        notify_send = shutil.which("notify-send")
        if notify_send:
            subprocess.run(
                [
                    notify_send,
                    "--app-name=Interview Tracker",
                    title,
                    body,
                ],
                capture_output=True,
                text=True,
            )
            _log(log_file, "sent via notify-send")
            return
        _log(log_file, "notify-send not found — local notification skipped")
        return
    if platform_utils.is_windows():
        try:
            from win10toast import ToastNotifier  # type: ignore[import-untyped]

            ToastNotifier().show_toast(title, body, duration=8, threaded=True)
            _log(log_file, "sent via win10toast")
        except Exception as exc:
            _log(log_file, f"Windows toast failed: {exc}")


def run_check(data_dir: Path | None = None, arg: str = "") -> int:
    data_dir = data_dir or platform_utils.default_data_dir()
    db_file = data_dir / database.DEFAULT_DB_NAME
    log_file = data_dir / "logs" / "notifier.log"
    last_hash_file = data_dir / ".last_notified_hash"
    config = platform_utils.load_config_env(data_dir)

    _log(log_file, f"notifier fired (arg: {arg or 'none'})")
    summary = database.get_latest_summary(db_path=db_file)
    if not summary:
        _log(log_file, "no successful scan summary yet — nothing to notify")
        return 0

    current_hash = str(summary.get("data_hash") or "")
    if not current_hash:
        _log(log_file, "ERROR: could not read data_hash")
        return 1

    last_hash = last_hash_file.read_text(encoding="utf-8").strip() if last_hash_file.is_file() else ""
    if current_hash == last_hash:
        _log(log_file, f"data unchanged since last notification (hash {current_hash[:12]}...) — staying silent")
        return 0

    body = notify_body(summary)
    open_url = dashboard_open_url(data_dir)
    _log(log_file, f"changes detected — notifying. {body}")
    show_platform_notification("Interview Tracker updated", body, open_url, log_file)

    topic = config.get("NTFY_TOPIC") or os.environ.get("NTFY_TOPIC") or ""
    if not topic:
        topic_file = data_dir / ".ntfy_topic"
        if topic_file.is_file():
            topic = topic_file.read_text(encoding="utf-8").strip()
    if topic:
        code = send_ntfy(topic, body, open_url)
        _log(log_file, f"ntfy push sent, HTTP {code}")
    else:
        _log(log_file, "no ntfy topic set — local notification only")

    last_hash_file.write_text(current_hash, encoding="utf-8")
    _log(log_file, "done")
    return 0


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    return run_check(arg=arg)


if __name__ == "__main__":
    raise SystemExit(main())
