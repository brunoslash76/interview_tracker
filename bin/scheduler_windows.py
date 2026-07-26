"""Windows Task Scheduler backend."""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.dom import minidom

import platform_utils

SCAN_TASK_NAME = r"InterviewTracker\GmailScan"
TRAY_TASK_NAME = r"InterviewTracker\Tray"
TASKS_FOLDER = "InterviewTracker"


def _pretty_xml(element: ET.Element) -> str:
    rough = ET.tostring(element, encoding="unicode")
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ")


def build_scan_task_xml(
    root: Path,
    home: Path,
    data_dir: Path,
    intervals: list[tuple[int, int]],
) -> str:
    python = platform_utils.resolve_python_for_subprocess(root)
    script = root / "bin" / "scan_gmail.py"
    task = ET.Element("Task", version="1.2", xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task")
    reg = ET.SubElement(task, "RegistrationInfo")
    ET.SubElement(reg, "Description").text = "Interview Tracker Gmail scan"
    triggers = ET.SubElement(task, "Triggers")
    for hour, minute in intervals:
        trigger = ET.SubElement(triggers, "CalendarTrigger")
        ET.SubElement(trigger, "StartBoundary").text = "2000-01-01T{:02d}:{:02d}:00".format(
            hour, minute
        )
        schedule = ET.SubElement(trigger, "ScheduleByDay")
        ET.SubElement(schedule, "DaysInterval").text = "1"
    actions = ET.SubElement(task, "Actions")
    action = ET.SubElement(actions, "Exec")
    ET.SubElement(action, "Command").text = python
    ET.SubElement(action, "Arguments").text = f'"{script}"'
    ET.SubElement(action, "WorkingDirectory").text = str(root)
    settings = ET.SubElement(task, "Settings")
    ET.SubElement(settings, "MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(settings, "DisallowStartIfOnBatteries").text = "false"
    ET.SubElement(settings, "StopIfGoingOnBatteries").text = "false"
    ET.SubElement(settings, "Enabled").text = "true" if intervals else "false"
    ET.SubElement(settings, "ExecutionTimeLimit").text = "PT2H"
    ET.SubElement(settings, "RestartOnFailure").text = "false"
    principals = ET.SubElement(task, "Principals")
    principal = ET.SubElement(principals, "Principal", id="Author")
    ET.SubElement(principal, "LogonType").text = "InteractiveToken"
    ET.SubElement(principal, "RunLevel").text = "LeastPrivilege"
    return _pretty_xml(task)


def build_tray_task_xml(root: Path, data_dir: Path) -> str:
    pythonw = platform_utils.venv_python(root).with_name("pythonw.exe")
    if not pythonw.is_file():
        pythonw = platform_utils.venv_python(root)
    script = root / "bin" / "tray_app.py"
    task = ET.Element("Task", version="1.2", xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task")
    reg = ET.SubElement(task, "RegistrationInfo")
    ET.SubElement(reg, "Description").text = "Interview Tracker system tray"
    triggers = ET.SubElement(task, "Triggers")
    logon = ET.SubElement(triggers, "LogonTrigger")
    ET.SubElement(logon, "Enabled").text = "true"
    actions = ET.SubElement(task, "Actions")
    action = ET.SubElement(actions, "Exec")
    ET.SubElement(action, "Command").text = str(pythonw)
    ET.SubElement(action, "Arguments").text = f'"{script}"'
    ET.SubElement(action, "WorkingDirectory").text = str(root)
    settings = ET.SubElement(task, "Settings")
    ET.SubElement(settings, "MultipleInstancesPolicy").text = "IgnoreNew"
    ET.SubElement(settings, "DisallowStartIfOnBatteries").text = "false"
    ET.SubElement(settings, "StopIfGoingOnBatteries").text = "false"
    ET.SubElement(settings, "Enabled").text = "true"
    ET.SubElement(settings, "RestartOnFailure").text = "true"
    ET.SubElement(settings, "RestartInterval").text = "PT1M"
    principals = ET.SubElement(task, "Principals")
    principal = ET.SubElement(principals, "Principal", id="Author")
    ET.SubElement(principal, "LogonType").text = "InteractiveToken"
    ET.SubElement(principal, "RunLevel").text = "LeastPrivilege"
    return _pretty_xml(task)


def _task_xml_path(data_dir: Path, name: str) -> Path:
    return data_dir / "tasks" / f"{name}.xml"


def _register_task(task_name: str, xml_path: Path) -> None:
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN",
            task_name,
            "/XML",
            str(xml_path),
            "/F",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _delete_task(task_name: str) -> None:
    subprocess.run(
        ["schtasks", "/Delete", "/TN", task_name, "/F"],
        capture_output=True,
        text=True,
    )


def sync_scheduler(
    root: Path,
    home: Path,
    data_dir: Path,
    intervals: list[tuple[int, int]],
    load_agent: bool = True,
) -> dict[str, Any]:
    xml_text = build_scan_task_xml(root, home, data_dir, intervals)
    xml_path = _task_xml_path(data_dir, "gmail_scan")
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(xml_text, encoding="utf-8")
    if load_agent:
        _delete_task(SCAN_TASK_NAME)
        if intervals:
            _register_task(SCAN_TASK_NAME, xml_path)
    return {"intervals": intervals, "installed_plist": str(xml_path)}


def sync_tray_task(
    root: Path,
    data_dir: Path,
    load_agent: bool = True,
) -> dict[str, Any]:
    xml_text = build_tray_task_xml(root, data_dir)
    xml_path = _task_xml_path(data_dir, "tray")
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_text(xml_text, encoding="utf-8")
    if load_agent:
        _delete_task(TRAY_TASK_NAME)
        _register_task(TRAY_TASK_NAME, xml_path)
        subprocess.run(
            ["schtasks", "/Run", "/TN", TRAY_TASK_NAME],
            capture_output=True,
            text=True,
        )
    return {"tray_task": TRAY_TASK_NAME, "xml": str(xml_path)}


def restore_scheduler_backup(data_dir: Path, backup: bytes | None) -> None:
    if not backup:
        return
    xml_path = _task_xml_path(data_dir, "gmail_scan")
    xml_path.write_bytes(backup)
    _delete_task(SCAN_TASK_NAME)
    _register_task(SCAN_TASK_NAME, xml_path)


def read_scheduler_backup(data_dir: Path) -> bytes | None:
    xml_path = _task_xml_path(data_dir, "gmail_scan")
    if xml_path.is_file():
        return xml_path.read_bytes()
    return None
