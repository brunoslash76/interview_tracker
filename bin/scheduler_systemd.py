"""Linux systemd user-unit backend."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import database
import platform_utils

SCAN_SERVICE = "interview-tracker-scan.service"
SCAN_TIMER = "interview-tracker-scan.timer"
NOTIFIER_PATH = "interview-tracker-notifier.path"
NOTIFIER_SERVICE = "interview-tracker-notifier.service"
TRAY_SERVICE = "interview-tracker-tray.service"

UNIT_NAMES = (
    SCAN_SERVICE,
    SCAN_TIMER,
    NOTIFIER_PATH,
    NOTIFIER_SERVICE,
    TRAY_SERVICE,
)


def _systemd_dir(data_dir: Path) -> Path:
    return data_dir / "systemd"


def _unit_path(data_dir: Path, name: str) -> Path:
    return _systemd_dir(data_dir) / name


def _service_environment(root: Path, home: Path, data_dir: Path) -> str:
    config = data_dir / "config.env"
    lines = [
        f"Environment=HOME={home}",
        f"Environment=INTERVIEW_TRACKER_DATA_DIR={data_dir}",
        f"Environment=PATH={platform_utils.default_path_env()}",
        f"EnvironmentFile=-{config}",
    ]
    return "\n".join(lines)


def build_scan_service_unit(root: Path, home: Path, data_dir: Path) -> str:
    python = platform_utils.resolve_python_for_subprocess(root)
    script = root / "bin" / "scan_gmail.py"
    out_log = data_dir / "logs" / "scheduler.out.log"
    err_log = data_dir / "logs" / "scheduler.err.log"
    return f"""[Unit]
Description=Interview Tracker Gmail scan

[Service]
Type=oneshot
WorkingDirectory={root}
ExecStart={python} {script}
{_service_environment(root, home, data_dir)}
StandardOutput=append:{out_log}
StandardError=append:{err_log}
"""


def build_scan_timer_unit(intervals: list[tuple[int, int]]) -> str:
    lines = [
        "[Unit]",
        "Description=Interview Tracker Gmail scan schedule",
        "",
        "[Timer]",
    ]
    for hour, minute in intervals:
        lines.append(f"OnCalendar=*-*-* {hour:02d}:{minute:02d}:00")
    lines.extend(
        [
            "Persistent=true",
            f"Unit={SCAN_SERVICE}",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )
    return "\n".join(lines)


def build_notifier_path_unit(data_dir: Path) -> str:
    db_file = data_dir / database.DEFAULT_DB_NAME
    return f"""[Unit]
Description=Interview Tracker database change watcher

[Path]
PathChanged={db_file}

[Install]
WantedBy=default.target
"""


def build_notifier_service_unit(root: Path, home: Path, data_dir: Path) -> str:
    python = platform_utils.resolve_python_for_subprocess(root)
    script = root / "bin" / "notifier.py"
    out_log = data_dir / "logs" / "notifier.log"
    return f"""[Unit]
Description=Interview Tracker notifier

[Service]
Type=oneshot
WorkingDirectory={root}
ExecStart={python} {script} check
{_service_environment(root, home, data_dir)}
StandardOutput=append:{out_log}
StandardError=append:{out_log}
"""


def build_tray_service_unit(root: Path, home: Path, data_dir: Path) -> str:
    python = platform_utils.resolve_python_for_subprocess(root)
    script = root / "bin" / "tray_app.py"
    out_log = data_dir / "logs" / "menubar_debug.log"
    return f"""[Unit]
Description=Interview Tracker system tray
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
WorkingDirectory={root}
ExecStart={python} {script}
{_service_environment(root, home, data_dir)}
Restart=on-failure
RestartSec=60
StandardOutput=append:{out_log}
StandardError=append:{out_log}

[Install]
WantedBy=default.target
"""


def _write_units(data_dir: Path, units: dict[str, str]) -> None:
    unit_dir = _systemd_dir(data_dir)
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, content in units.items():
        _unit_path(data_dir, name).write_text(content, encoding="utf-8")


def _install_units(home: Path, data_dir: Path, names: tuple[str, ...]) -> None:
    dest_dir = platform_utils.systemd_user_unit_dir(home)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        source = _unit_path(data_dir, name)
        shutil.copy2(source, dest_dir / name)


def _systemctl_user(args: list[str]) -> None:
    subprocess.run(["systemctl", "--user", *args], check=True, capture_output=True, text=True)


def sync_scheduler(
    root: Path,
    home: Path,
    data_dir: Path,
    intervals: list[tuple[int, int]],
    load_agent: bool = True,
) -> dict[str, Any]:
    units = {
        SCAN_SERVICE: build_scan_service_unit(root, home, data_dir),
        SCAN_TIMER: build_scan_timer_unit(intervals),
    }
    _write_units(data_dir, units)
    if load_agent:
        _install_units(home, data_dir, (SCAN_SERVICE, SCAN_TIMER))
        _systemctl_user(["daemon-reload"])
        if intervals:
            _systemctl_user(["enable", "--now", SCAN_TIMER])
        else:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", SCAN_TIMER],
                capture_output=True,
                text=True,
            )
    timer_path = _unit_path(data_dir, SCAN_TIMER)
    return {"intervals": intervals, "installed_plist": str(timer_path)}


def sync_notifier_units(
    root: Path,
    home: Path,
    data_dir: Path,
    load_agent: bool = True,
) -> dict[str, Any]:
    units = {
        NOTIFIER_PATH: build_notifier_path_unit(data_dir),
        NOTIFIER_SERVICE: build_notifier_service_unit(root, home, data_dir),
    }
    _write_units(data_dir, units)
    if load_agent:
        _install_units(home, data_dir, (NOTIFIER_PATH, NOTIFIER_SERVICE))
        _systemctl_user(["daemon-reload"])
        _systemctl_user(["enable", "--now", NOTIFIER_PATH])
    return {"notifier_path": str(_unit_path(data_dir, NOTIFIER_PATH))}


def sync_tray_service(
    root: Path,
    home: Path,
    data_dir: Path,
    load_agent: bool = True,
) -> dict[str, Any]:
    units = {TRAY_SERVICE: build_tray_service_unit(root, home, data_dir)}
    _write_units(data_dir, units)
    if load_agent:
        _install_units(home, data_dir, (TRAY_SERVICE,))
        _systemctl_user(["daemon-reload"])
        _systemctl_user(["enable", "--now", TRAY_SERVICE])
    return {"tray_service": str(_unit_path(data_dir, TRAY_SERVICE))}


def read_scheduler_backup(data_dir: Path) -> bytes | None:
    timer_path = _unit_path(data_dir, SCAN_TIMER)
    if timer_path.is_file():
        return timer_path.read_bytes()
    return None


def restore_scheduler_backup(data_dir: Path, backup: bytes | None) -> None:
    if not backup:
        return
    timer_path = _unit_path(data_dir, SCAN_TIMER)
    timer_path.parent.mkdir(parents=True, exist_ok=True)
    timer_path.write_bytes(backup)
    home = Path.home()
    _install_units(home, data_dir, (SCAN_SERVICE, SCAN_TIMER))
    _systemctl_user(["daemon-reload"])
    content = backup.decode("utf-8")
    if "OnCalendar=" in content:
        _systemctl_user(["enable", "--now", SCAN_TIMER])
    else:
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", SCAN_TIMER],
            capture_output=True,
            text=True,
        )
