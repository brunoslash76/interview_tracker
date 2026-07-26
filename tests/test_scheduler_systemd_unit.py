"""Unit tests for bin/scheduler_systemd.py."""

from __future__ import annotations

import unittest
from unittest import mock

from tests.support import PROJECT_ROOT, TemporaryDatabaseTestCase, load_bin_module


class SchedulerSystemdUnitTests(TemporaryDatabaseTestCase):
    def test_build_scan_timer_unit_contains_intervals(self):
        scheduler_systemd = load_bin_module("scheduler_systemd")
        timer = scheduler_systemd.build_scan_timer_unit([(9, 0), (20, 15)])
        self.assertIn("OnCalendar=*-*-* 09:00:00", timer)
        self.assertIn("OnCalendar=*-*-* 20:15:00", timer)
        self.assertIn("Persistent=true", timer)

    def test_build_scan_service_unit_includes_data_dir_env(self):
        scheduler_systemd = load_bin_module("scheduler_systemd")
        service = scheduler_systemd.build_scan_service_unit(
            PROJECT_ROOT, self.home_dir, self.data_dir
        )
        self.assertIn(f"INTERVIEW_TRACKER_DATA_DIR={self.data_dir}", service)
        self.assertIn("scan_gmail.py", service)

    def test_build_notifier_path_unit_watches_database(self):
        scheduler_systemd = load_bin_module("scheduler_systemd")
        import database

        path_unit = scheduler_systemd.build_notifier_path_unit(self.data_dir)
        self.assertIn(str(self.data_dir / database.DEFAULT_DB_NAME), path_unit)

    def test_build_tray_service_unit_restarts_on_failure(self):
        scheduler_systemd = load_bin_module("scheduler_systemd")
        tray = scheduler_systemd.build_tray_service_unit(
            PROJECT_ROOT, self.home_dir, self.data_dir
        )
        self.assertIn("Restart=on-failure", tray)
        self.assertIn("tray_app.py", tray)

    def test_read_scheduler_backup_roundtrip(self):
        scheduler_systemd = load_bin_module("scheduler_systemd")
        timer = scheduler_systemd.build_scan_timer_unit([(8, 30)])
        path = scheduler_systemd._unit_path(self.data_dir, scheduler_systemd.SCAN_TIMER)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(timer, encoding="utf-8")
        backup = scheduler_systemd.read_scheduler_backup(self.data_dir)
        self.assertEqual(backup.decode("utf-8"), timer)

    def test_sync_scheduler_without_load_skips_systemctl(self):
        scheduler_systemd = load_bin_module("scheduler_systemd")
        with mock.patch.object(scheduler_systemd, "_systemctl_user") as ctl:
            scheduler_systemd.sync_scheduler(
                PROJECT_ROOT,
                self.home_dir,
                self.data_dir,
                [(7, 0)],
                load_agent=False,
            )
        ctl.assert_not_called()

    def test_sync_scheduler_with_load_enables_timer(self):
        scheduler_systemd = load_bin_module("scheduler_systemd")
        with mock.patch.object(scheduler_systemd, "_install_units"), mock.patch.object(
            scheduler_systemd, "_systemctl_user"
        ) as ctl:
            scheduler_systemd.sync_scheduler(
                PROJECT_ROOT,
                self.home_dir,
                self.data_dir,
                [(10, 0)],
                load_agent=True,
            )
        ctl.assert_any_call(["daemon-reload"])
        ctl.assert_any_call(["enable", "--now", scheduler_systemd.SCAN_TIMER])

    def test_sync_notifier_units_loads_path_and_service(self):
        scheduler_systemd = load_bin_module("scheduler_systemd")
        with mock.patch.object(scheduler_systemd, "_install_units"), mock.patch.object(
            scheduler_systemd, "_systemctl_user"
        ) as ctl:
            scheduler_systemd.sync_notifier_units(
                PROJECT_ROOT, self.home_dir, self.data_dir, load_agent=True
            )
        ctl.assert_any_call(["enable", "--now", scheduler_systemd.NOTIFIER_PATH])

    def test_sync_tray_service_enables_unit(self):
        scheduler_systemd = load_bin_module("scheduler_systemd")
        with mock.patch.object(scheduler_systemd, "_install_units"), mock.patch.object(
            scheduler_systemd, "_systemctl_user"
        ) as ctl:
            scheduler_systemd.sync_tray_service(
                PROJECT_ROOT, self.home_dir, self.data_dir, load_agent=True
            )
        ctl.assert_any_call(["enable", "--now", scheduler_systemd.TRAY_SERVICE])

    def test_restore_scheduler_backup_reloads_timer(self):
        scheduler_systemd = load_bin_module("scheduler_systemd")
        timer = scheduler_systemd.build_scan_timer_unit([(6, 45)])
        with mock.patch.object(scheduler_systemd, "_install_units"), mock.patch.object(
            scheduler_systemd, "_systemctl_user"
        ) as ctl, mock.patch.object(scheduler_systemd.subprocess, "run"):
            scheduler_systemd.restore_scheduler_backup(self.data_dir, timer.encode("utf-8"))
        ctl.assert_any_call(["enable", "--now", scheduler_systemd.SCAN_TIMER])


if __name__ == "__main__":
    unittest.main()
