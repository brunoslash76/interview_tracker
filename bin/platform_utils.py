"""Cross-platform paths, formatting, and small OS helpers for Interview Tracker."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional


def is_windows() -> bool:
    return sys.platform == "win32"


def is_darwin() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def default_data_dir() -> Path:
    override = os.environ.get("INTERVIEW_TRACKER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if is_windows():
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "InterviewTracker"
    if is_linux():
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
        return base / "InterviewTracker"
    return Path.home() / "Library" / "Application Support" / "InterviewTracker"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def venv_python(root: Optional[Path] = None) -> Path:
    root = root or project_root()
    if is_windows():
        candidate = root / "venv" / "Scripts" / "python.exe"
    else:
        candidate = root / "venv" / "bin" / "python3"
    if candidate.is_file():
        return candidate
    return Path(sys.executable)


def resolve_python_for_subprocess(root: Optional[Path] = None) -> str:
    return str(venv_python(root))


def load_config_env(data_dir: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines from config.env (shell-compatible subset)."""
    conf_path = Path(
        os.environ.get("INTERVIEW_TRACKER_CONFIG", data_dir / "config.env")
    ).expanduser()
    out: dict[str, str] = {}
    if not conf_path.is_file():
        return out
    for line in conf_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        out[key] = value
    return out


def format_dashboard_timestamp(when: Optional[datetime] = None) -> str:
    when = when or datetime.now().astimezone()
    if is_windows() or is_linux():
        day = str(when.day)
        hour12 = when.strftime("%I").lstrip("0") or "12"
        minute = when.strftime("%M")
        ampm = when.strftime("%p")
        return when.strftime(f"%b {day}, %Y at {hour12}:{minute} {ampm}")
    return when.strftime("%b %-d, %Y at %-I:%M %p")


def format_menubar_datetime(dt: datetime) -> str:
    if is_windows() or is_linux():
        day = str(dt.day)
        hour12 = dt.strftime("%I").lstrip("0") or "12"
        return dt.strftime(f"%a %b {day}, {hour12}:%M %p")
    return dt.strftime("%a %b %-d, %-I:%M %p")


def open_url_or_file(url: str, fallback: Path) -> None:
    if url:
        webbrowser.open(url)
        return
    if is_darwin():
        subprocess.run(["/usr/bin/open", str(fallback)], capture_output=True, text=True)
    elif is_windows():
        os.startfile(str(fallback))  # type: ignore[attr-defined]
    elif is_linux():
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.run([opener, str(fallback)], capture_output=True, text=True)
        else:
            webbrowser.open(fallback.as_uri())
    else:
        webbrowser.open(fallback.as_uri())


def claude_candidates(home: Optional[Path] = None) -> list[Path]:
    home = home or Path.home()
    names = ("claude", "claude.exe", "claude.cmd")
    candidates: list[Path] = []
    if is_windows():
        candidates.extend(
            [
                home / ".local" / "bin" / "claude.exe",
                home / ".local" / "bin" / "claude.cmd",
                home / "AppData" / "Local" / "Programs" / "claude" / "claude.exe",
            ]
        )
    else:
        candidates.extend(
            [
                home / ".local" / "bin" / "claude",
                Path("/opt/homebrew/bin/claude"),
                Path("/usr/local/bin/claude"),
            ]
        )
    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return candidates


def resolve_claude_bin(
    configured: Optional[str] = None,
    home: Optional[Path] = None,
) -> Optional[str]:
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path)
        if shutil.which(configured):
            return configured
    for candidate in claude_candidates(home):
        if candidate.is_file():
            return str(candidate)
    return None


def default_path_env() -> str:
    if is_windows():
        local = os.environ.get("LOCALAPPDATA", "")
        user = os.environ.get("USERPROFILE", str(Path.home()))
        parts = [
            str(Path(user) / ".local" / "bin"),
            os.environ.get("PATH", ""),
        ]
        return os.pathsep.join(p for p in parts if p)
    if is_linux():
        home = Path.home()
        parts = [
            str(home / ".local" / "bin"),
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
        ]
        return os.pathsep.join(parts)
    return "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def systemd_user_unit_dir(home: Optional[Path] = None) -> Path:
    return (home or Path.home()) / ".config" / "systemd" / "user"
