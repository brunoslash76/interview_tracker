"""Unit tests for bin/scheduler.py."""

from __future__ import annotations

import plistlib
import unittest
from pathlib import Path
from unittest import mock

from tests.support import PROJECT_ROOT, TemporaryDatabaseTestCase, database, load_bin_module


class BuildPlistTests(TemporaryDatabaseTestCase):
    def test_build_plist_from_database(self):
        database.initialize_database(self.db_path)
        scheduler_module = load_bin_module("scheduler")
        plist = scheduler_module.build_plist_dict(
            PROJECT_ROOT,
            self.home_dir,
            self.data_dir,
            database.get_enabled_scan_intervals(self.db_path),
        )
        self.assertEqual(
            plist["StartCalendarInterval"],
            [{"Hour": 9, "Minute": 0}, {"Hour": 20, "Minute": 0}],
        )
        database.set_scan_schedule(["07:15"], self.db_path)
        plist = scheduler_module.build_plist_dict(
            PROJECT_ROOT,
            self.home_dir,
            self.data_dir,
            database.get_enabled_scan_intervals(self.db_path),
        )
        self.assertEqual(plist["StartCalendarInterval"], [{"Hour": 7, "Minute": 15}])
        database.set_scan_schedule([], self.db_path)
        plist = scheduler_module.build_plist_dict(
            PROJECT_ROOT,
            self.home_dir,
            self.data_dir,
            database.get_enabled_scan_intervals(self.db_path),
        )
        self.assertNotIn("StartCalendarInterval", plist)


class WritePlistTests(TemporaryDatabaseTestCase):
    def test_write_plist_writes_and_lints_at_temp_path(self):
        scheduler_module = load_bin_module("scheduler")
        plist_path = self.root / "LaunchAgents" / "com.interview-tracker.scheduler.plist"
        sample = scheduler_module.build_plist_dict(
            PROJECT_ROOT, self.home_dir, self.data_dir, [(9, 0)]
        )
        with mock.patch.object(scheduler_module, "_installed_plist_path", return_value=plist_path):
            scheduler_module.write_plist(plist_path, sample)
        self.assertTrue(plist_path.is_file())
        loaded = plistlib.loads(plist_path.read_bytes())
        self.assertEqual(loaded["Label"], sample["Label"])


class ApplySettingsTests(TemporaryDatabaseTestCase):
    def test_apply_settings_with_rollback_success(self):
        database.initialize_database(self.db_path)
        scheduler_module = load_bin_module("scheduler")
        with mock.patch.object(scheduler_module, "sync_scheduler") as sync_mock:
            sync_mock.return_value = {"intervals": [(10, 0)], "installed_plist": "/tmp/x.plist"}
            result = scheduler_module.apply_settings_with_rollback(
                "user@example.com",
                ["10:00"],
                PROJECT_ROOT,
                self.home_dir,
                self.data_dir,
                self.db_path,
            )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["email"], "user@example.com")
        self.assertEqual(result["scan_times"], ["10:00"])
        settings = database.get_user_settings(self.db_path)
        self.assertEqual(settings["email"], "user@example.com")
        sync_mock.assert_called_once()

    def test_apply_settings_with_rollback_restores_on_sync_failure(self):
        database.initialize_database(self.db_path)
        database.set_scan_email_filter("before@example.com", self.db_path)
        database.set_scan_schedule(["08:00"], self.db_path)
        scheduler_module = load_bin_module("scheduler")
        plist_path = self.root / "agent.plist"
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        backup_bytes = b"<?xml version='1.0'?><plist version='1.0'><dict></dict></plist>"
        plist_path.write_bytes(backup_bytes)

        def failing_sync(*_args, **_kwargs):
            raise RuntimeError("launchctl failed")

        with mock.patch.object(
            scheduler_module, "_installed_plist_path", return_value=plist_path
        ), mock.patch.object(scheduler_module, "sync_scheduler", side_effect=failing_sync), mock.patch.object(
            scheduler_module, "bootout_scheduler"
        ), mock.patch.object(
            scheduler_module, "bootstrap_scheduler"
        ) as bootstrap_mock:
            with self.assertRaises(RuntimeError):
                scheduler_module.apply_settings_with_rollback(
                    "after@example.com",
                    ["11:00"],
                    PROJECT_ROOT,
                    self.home_dir,
                    self.data_dir,
                    self.db_path,
                )
        settings = database.get_user_settings(self.db_path)
        self.assertEqual(settings["email"], "before@example.com")
        self.assertEqual(settings["scan_times"], ["08:00"])
        self.assertEqual(plist_path.read_bytes(), backup_bytes)
        bootstrap_mock.assert_called_once()


class SyncSchedulerTests(TemporaryDatabaseTestCase):
    def test_sync_scheduler_without_load_writes_plist_only(self):
        database.initialize_database(self.db_path)
        scheduler_module = load_bin_module("scheduler")
        plist_path = self.root / "LaunchAgents" / "scheduler.plist"
        with mock.patch.object(
            scheduler_module, "_installed_plist_path", return_value=plist_path
        ), mock.patch.object(scheduler_module, "bootout_scheduler") as bootout, mock.patch.object(
            scheduler_module, "bootstrap_scheduler"
        ) as bootstrap:
            result = scheduler_module.sync_scheduler(
                PROJECT_ROOT,
                self.home_dir,
                self.data_dir,
                self.db_path,
                load_agent=False,
            )
        self.assertTrue(plist_path.is_file())
        self.assertIn("intervals", result)
        bootout.assert_not_called()
        bootstrap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
