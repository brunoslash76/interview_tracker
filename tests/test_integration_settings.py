"""Integration tests for settings API and scheduler plist sync."""

from __future__ import annotations

import http.client
import json
import plistlib
import unittest
from pathlib import Path
from unittest import mock

from support import IsolatedRuntimeTestCase, database, load_bin_module


class SettingsIntegrationTests(IsolatedRuntimeTestCase):
    """Integration tests: local server PUT persists schedule and renders launchd plist."""

    def setUp(self):
        super().setUp()
        database.initialize_database(self.db_path)
        self.launch_agents = self.home_dir / "Library" / "LaunchAgents"
        self.launch_agents.mkdir(parents=True, exist_ok=True)
        self.installed_plist = self.launch_agents / "com.interview-tracker.scheduler.plist"

    def test_put_settings_applies_scheduler_without_load_agent(self):
        local_server_module = load_bin_module("local_server")
        sched = local_server_module.scheduler
        real_sync = sched.sync_scheduler

        def sync_without_load(*args, **kwargs):
            kwargs["load_agent"] = False
            return real_sync(*args, **kwargs)

        with mock.patch.object(local_server_module, "DATA_DIR", self.data_dir), mock.patch.object(
            local_server_module, "DB_FILE", self.db_path
        ), mock.patch.object(
            sched, "_installed_plist_path", return_value=self.installed_plist
        ), mock.patch.object(
            sched, "sync_scheduler", side_effect=sync_without_load
        ), mock.patch.object(
            Path, "home", return_value=self.home_dir
        ):
            port = local_server_module.start_local_server()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/settings")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                csrf_cookie = ""
                for header, value in response.getheaders():
                    if header.lower() == "set-cookie":
                        csrf_cookie = value.split("=", 1)[1].split(";", 1)[0]

                payload = {"email": "me@example.com", "scan_times": ["10:00", "18:30"]}
                conn.request(
                    "PUT",
                    "/api/settings",
                    body=json.dumps(payload),
                    headers={
                        "Content-Type": "application/json",
                        "Cookie": f"it_csrf={csrf_cookie}",
                        "X-CSRF-Token": csrf_cookie,
                        "Origin": f"http://127.0.0.1:{port}",
                    },
                )
                ok = conn.getresponse()
                body = ok.read().decode("utf-8")
                self.assertEqual(ok.status, 200, msg=body)
                saved = json.loads(body)
                self.assertEqual(saved["status"], "ok")
                self.assertEqual(saved["email"], "me@example.com")
                self.assertEqual(saved["scan_times"], ["10:00", "18:30"])
                conn.close()

                settings = database.get_user_settings(self.db_path)
                self.assertEqual(settings["email"], "me@example.com")
                self.assertEqual(settings["scan_times"], ["10:00", "18:30"])

                self.assertTrue(self.installed_plist.is_file())
                with self.installed_plist.open("rb") as handle:
                    plist = plistlib.load(handle)
                self.assertEqual(
                    plist["StartCalendarInterval"],
                    [{"Hour": 10, "Minute": 0}, {"Hour": 18, "Minute": 30}],
                )
                env = plist["EnvironmentVariables"]
                self.assertEqual(env["HOME"], str(self.home_dir))
                self.assertEqual(env["INTERVIEW_TRACKER_DATA_DIR"], str(self.data_dir))
            finally:
                local_server_module.stop_local_server()


if __name__ == "__main__":
    unittest.main()
