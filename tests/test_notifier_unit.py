"""Unit tests for bin/notifier.py."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from tests.support import TemporaryDatabaseTestCase, database, load_bin_module


class NotifierTests(TemporaryDatabaseTestCase):
    def test_run_check_skips_when_hash_unchanged(self):
        database.initialize_database(self.db_path)
        database.merge_scan([], db_path=self.db_path)
        notifier = load_bin_module("notifier")
        hash_file = self.data_dir / ".last_notified_hash"
        summary = database.get_latest_summary(self.db_path)
        hash_file.write_text(str(summary["data_hash"]), encoding="utf-8")
        with mock.patch.object(notifier, "show_platform_notification") as notify:
            code = notifier.run_check(data_dir=self.data_dir)
        self.assertEqual(code, 0)
        notify.assert_not_called()

    def test_notify_body_lists_new_companies(self):
        notifier = load_bin_module("notifier")
        body = notifier.notify_body(
            {
                "total": 3,
                "upcoming": 1,
                "offers": 0,
                "new_company_names": ["Acme"],
            }
        )
        self.assertIn("Acme", body)
        self.assertIn("New:", body)

    def test_send_ntfy_uses_curl_when_available(self):
        notifier = load_bin_module("notifier")
        with mock.patch.object(notifier.shutil, "which", return_value="/usr/bin/curl"), mock.patch.object(
            notifier.subprocess, "run", return_value=mock.Mock(stdout="204")
        ):
            code = notifier.send_ntfy("topic", "hello", "http://127.0.0.1/")
        self.assertEqual(code, 204)

    def test_run_check_notifies_when_hash_changes(self):
        database.initialize_database(self.db_path)
        database.merge_scan([], db_path=self.db_path)
        notifier = load_bin_module("notifier")
        with mock.patch.object(notifier, "show_platform_notification") as notify, mock.patch.object(
            notifier, "send_ntfy", return_value=200
        ):
            code = notifier.run_check(data_dir=self.data_dir, arg="test")
        self.assertEqual(code, 0)
        notify.assert_called_once()

    def test_dashboard_open_url_uses_loopback_port(self):
        notifier = load_bin_module("notifier")
        (self.data_dir / ".http_port").write_text("8765", encoding="utf-8")
        url = notifier.dashboard_open_url(self.data_dir)
        self.assertEqual(url, "http://127.0.0.1:8765/dashboard")

    def test_show_platform_notification_uses_notify_send_on_linux(self):
        notifier = load_bin_module("notifier")
        log_file = self.data_dir / "logs" / "notifier.log"
        with mock.patch.object(notifier.platform_utils, "is_darwin", return_value=False), mock.patch.object(
            notifier.platform_utils, "is_linux", return_value=True
        ), mock.patch.object(notifier.platform_utils, "is_windows", return_value=False), mock.patch.object(
            notifier.shutil, "which", return_value="/usr/bin/notify-send"
        ), mock.patch.object(notifier.subprocess, "run") as run:
            notifier.show_platform_notification("Title", "Body", "http://127.0.0.1/", log_file)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][0], "/usr/bin/notify-send")


if __name__ == "__main__":
    unittest.main()
