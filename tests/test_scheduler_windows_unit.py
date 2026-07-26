"""Unit tests for bin/scheduler_windows.py (XML generation)."""

from __future__ import annotations

import unittest
from unittest import mock

from tests.support import PROJECT_ROOT, TemporaryDatabaseTestCase, load_bin_module


class SchedulerWindowsUnitTests(TemporaryDatabaseTestCase):
    def test_build_scan_task_xml_contains_intervals(self):
        scheduler_windows = load_bin_module("scheduler_windows")
        xml = scheduler_windows.build_scan_task_xml(
            PROJECT_ROOT,
            self.home_dir,
            self.data_dir,
            [(9, 0), (20, 15)],
        )
        self.assertIn("09:00:00", xml)
        self.assertIn("20:15:00", xml)
        self.assertIn("scan_gmail.py", xml)

    def test_build_tray_task_xml_uses_tray_script(self):
        scheduler_windows = load_bin_module("scheduler_windows")
        xml = scheduler_windows.build_tray_task_xml(PROJECT_ROOT, self.data_dir)
        self.assertIn("tray_app.py", xml)
        self.assertIn("LogonTrigger", xml)

    def test_read_scheduler_backup_roundtrip(self):
        scheduler_windows = load_bin_module("scheduler_windows")
        xml = scheduler_windows.build_scan_task_xml(
            PROJECT_ROOT, self.home_dir, self.data_dir, [(8, 30)]
        )
        path = scheduler_windows._task_xml_path(self.data_dir, "gmail_scan")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml, encoding="utf-8")
        backup = scheduler_windows.read_scheduler_backup(self.data_dir)
        self.assertEqual(backup.decode("utf-8"), xml)

    def test_sync_scheduler_without_load_skips_schtasks(self):
        scheduler_windows = load_bin_module("scheduler_windows")
        with mock.patch.object(scheduler_windows, "_register_task") as register, mock.patch.object(
            scheduler_windows, "_delete_task"
        ) as delete:
            scheduler_windows.sync_scheduler(
                PROJECT_ROOT,
                self.home_dir,
                self.data_dir,
                [(7, 0)],
                load_agent=False,
            )
        register.assert_not_called()
        delete.assert_not_called()

    def test_sync_scheduler_with_load_registers_task(self):
        scheduler_windows = load_bin_module("scheduler_windows")
        with mock.patch.object(scheduler_windows, "_delete_task"), mock.patch.object(
            scheduler_windows, "_register_task"
        ) as register:
            scheduler_windows.sync_scheduler(
                PROJECT_ROOT,
                self.home_dir,
                self.data_dir,
                [(9, 30)],
                load_agent=True,
            )
        register.assert_called_once()


if __name__ == "__main__":
    unittest.main()
