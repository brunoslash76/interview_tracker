"""Regression tests for the hermetic Playwright server."""

from __future__ import annotations

from types import SimpleNamespace

from tests import e2e_server
from tests.support import TemporaryDatabaseTestCase


class E2EServerSchedulerTests(TemporaryDatabaseTestCase):
    def test_scheduler_patch_targets_local_server_module(self):
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("OS scheduler backend must not run in E2E tests")

        scheduler = SimpleNamespace(apply_settings_with_rollback=fail_if_called)
        local_server = SimpleNamespace(scheduler=scheduler, DB_FILE=self.db_path)

        e2e_server._patch_scheduler(local_server)
        result = local_server.scheduler.apply_settings_with_rollback(
            "e2e@example.com",
            ["09:00"],
            self.root,
            self.home_dir,
            self.data_dir,
            self.db_path,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["email"], "e2e@example.com")
        self.assertEqual(result["scan_times"], ["09:00"])

