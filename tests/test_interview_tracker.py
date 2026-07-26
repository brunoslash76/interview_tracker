"""Standard-library integration tests for the Interview Tracker data layer."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = PROJECT_ROOT / "bin"
sys.path.insert(0, str(BIN_DIR))

import database  # noqa: E402


def load_bin_module(name: str):
    """Load a bin script under a test-only module name."""
    path = BIN_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"tests_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TemporaryDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "private" / "interviews.sqlite3"


class SchemaTests(TemporaryDatabaseTestCase):
    def test_initialization_sets_version_and_creates_expected_tables(self):
        result = database.initialize_database(self.db_path)

        self.assertEqual(result, self.db_path)
        self.assertTrue(self.db_path.is_file())
        with sqlite3.connect(self.db_path) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

        self.assertEqual(version, database.SCHEMA_VERSION)
        self.assertEqual(
            tables,
            {
                "applications",
                "scan_runs",
                "metadata",
                "scan_schedule",
                "scan_preferences",
            },
        )

    def test_initialization_is_idempotent(self):
        database.initialize_database(self.db_path)
        database.initialize_database(self.db_path)

        with sqlite3.connect(self.db_path) as connection:
            applications_count = connection.execute(
                "SELECT COUNT(*) FROM applications"
            ).fetchone()[0]
        self.assertEqual(applications_count, 0)


class MergeTests(TemporaryDatabaseTestCase):
    def test_insert_then_thread_update_is_idempotent_and_preserves_first_seen(self):
        first_seen = "2025-01-02T03:04:05+00:00"
        records, new_names, updated = database.merge_records(
            [
                {
                    "thread_id": "thread-123",
                    "company": "Acme",
                    "position": "Engineer",
                    "first_seen": first_seen,
                }
            ],
            self.db_path,
            timestamp="2026-01-01T00:00:00+00:00",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(new_names, ["Acme"])
        self.assertEqual(updated, 0)

        records, new_names, updated = database.merge_records(
            [
                {
                    "thread_id": "thread-123",
                    "company": "Acme",
                    "position": "Senior Engineer",
                    "first_seen": "2099-01-01T00:00:00+00:00",
                }
            ],
            self.db_path,
            timestamp="2026-02-01T00:00:00+00:00",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(new_names, [])
        self.assertEqual(updated, 1)
        self.assertEqual(records[0]["position"], "Senior Engineer")
        self.assertEqual(records[0]["first_seen"], first_seen)
        self.assertEqual(records[0]["last_updated"], "2026-02-01T00:00:00+00:00")

    def test_normalized_company_fallback_adopts_real_thread_id(self):
        first_seen = "2025-03-04T05:06:07+00:00"
        database.merge_records(
            [
                {
                    "thread_id": "seed-acme",
                    "company": "Acme, Inc.",
                    "first_seen": first_seen,
                }
            ],
            self.db_path,
            timestamp="2025-03-04T05:06:07+00:00",
        )

        records, new_names, updated = database.merge_records(
            [
                {
                    "thread_id": "gmail-real-thread",
                    "company": "ACME INC",
                    "status": "Phone screen",
                }
            ],
            self.db_path,
            timestamp="2025-04-01T00:00:00+00:00",
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(new_names, [])
        self.assertEqual(updated, 1)
        self.assertEqual(records[0]["thread_id"], "gmail-real-thread")
        self.assertEqual(records[0]["first_seen"], first_seen)


class SummaryTests(TemporaryDatabaseTestCase):
    def test_summary_hash_stats_are_deterministic_and_latest_summary_is_returned(self):
        records = [
            {
                "thread_id": "offer-thread",
                "company": "Offer Co",
                "stage": "Offer",
                "status": "Offer Received",
                "interview_datetime": "2026-01-11T12:00:00+00:00",
            },
            {
                "thread_id": "past-thread",
                "company": "Past Co",
                "stage": "Technical Round",
                "status": "Active",
                "interview_datetime": "2026-01-09T12:00:00+00:00",
            },
        ]
        timestamp = "2026-01-10T12:00:00+00:00"
        first = database.merge_scan(
            records,
            self.db_path,
            timestamp=timestamp,
            scan_date="2026-01-10",
        )

        self.assertEqual(
            {key: first[key] for key in ("total", "upcoming", "offers", "completed")},
            {"total": 2, "upcoming": 1, "offers": 1, "completed": 1},
        )
        stored_records = database.get_records(self.db_path)
        self.assertEqual(first["data_hash"], database.records_hash(stored_records))
        self.assertEqual(
            database.records_hash(stored_records),
            database.records_hash(reversed(stored_records)),
        )

        second = database.merge_scan(
            list(reversed(records)),
            self.db_path,
            timestamp=timestamp,
            scan_date="2026-01-10",
        )
        self.assertEqual(second["data_hash"], first["data_hash"])
        self.assertEqual(database.get_latest_summary(self.db_path), second)

    def test_compute_stats_is_stable_at_an_explicit_instant(self):
        records = [
            {
                "stage": "Offer",
                "status": "Rejected after offer",
                "interview_datetime": "2026-07-26T00:00:00Z",
            },
            {
                "stage": "Final Interview",
                "status": "Active",
                "interview_datetime": "2026-07-24T00:00:00Z",
            },
        ]
        stats = database.compute_stats(
            records, at=datetime(2026, 7, 25, tzinfo=timezone.utc)
        )
        self.assertEqual(
            stats, {"total": 2, "upcoming": 0, "offers": 1, "completed": 1}
        )


class LegacyImportTests(TemporaryDatabaseTestCase):
    def test_import_preserves_timestamps_and_is_duplicate_free(self):
        legacy = [
            {
                "thread_id": "legacy-thread",
                "company": "Legacy Co",
                "position": "Developer",
                "first_seen": "2023-01-02T03:04:05+00:00",
                "last_updated": "2024-02-03T04:05:06+00:00",
            }
        ]

        database.import_records(legacy, self.db_path)
        database.import_records(legacy, self.db_path)
        records = database.get_records(self.db_path)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["first_seen"], legacy[0]["first_seen"])
        self.assertEqual(records[0]["last_updated"], legacy[0]["last_updated"])


class MigrationScriptTests(TemporaryDatabaseTestCase):
    def test_verified_migration_backs_up_and_removes_temporary_source(self):
        migrate_module = load_bin_module("migrate_json_to_sqlite")
        isolated_project_root = self.root / "isolated-project"
        isolated_project_root.mkdir()
        source = isolated_project_root / "legacy.json"
        source_records = [
            {
                "thread_id": "migration-thread",
                "company": "Migration Co",
                "first_seen": "2022-05-06T07:08:09+00:00",
                "last_updated": "2023-06-07T08:09:10+00:00",
            }
        ]
        source_bytes = json.dumps(source_records, ensure_ascii=False).encode("utf-8")
        source.write_bytes(source_bytes)

        with mock.patch.object(migrate_module, "ROOT", isolated_project_root):
            result = migrate_module.migrate(
                source=source, db_path=self.db_path, remove_source=True
            )

        self.assertEqual(result["status"], "migrated")
        self.assertTrue(result["source_removed"])
        self.assertFalse(source.exists())
        backup = Path(result["backup"])
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_bytes(), source_bytes)
        migrated = database.get_records(self.db_path)
        self.assertEqual(len(migrated), 1)
        self.assertEqual(migrated[0]["first_seen"], source_records[0]["first_seen"])
        self.assertEqual(migrated[0]["last_updated"], source_records[0]["last_updated"])
        summary = database.get_latest_summary(self.db_path)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["total"], 1)
        self.assertIsNone(database.get_last_successful_scan_date(self.db_path))


class DashboardRenderingTests(unittest.TestCase):
    def test_render_embeds_json_replaces_tokens_and_escapes_script_closers(self):
        merge_module = load_bin_module("merge_interviews")
        with tempfile.TemporaryDirectory() as temp_dir:
            template = Path(temp_dir) / "template.html"
            template.write_text(
                '<p>__GENERATED_AT__</p><script id="data">__DATA_JSON__</script>',
                encoding="utf-8",
            )
            records = [
                {
                    "company": "Closing </script><script>alert(1)</script>",
                    "notes": "embedded JSON",
                }
            ]

            with mock.patch.object(merge_module, "TEMPLATE_FILE", template):
                rendered = merge_module.render_dashboard(records)

        self.assertNotIn("__DATA_JSON__", rendered)
        self.assertNotIn("__GENERATED_AT__", rendered)
        self.assertIn('"notes": "embedded JSON"', rendered)
        self.assertIn("<\\/script>", rendered)
        self.assertNotIn("</script><script>alert(1)</script>", rendered)
        self.assertRegex(rendered, r"<p>.+</p>")


class SettingsTests(TemporaryDatabaseTestCase):
    def test_default_schedule_and_empty_email(self):
        database.initialize_database(self.db_path)
        settings = database.get_user_settings(self.db_path)
        self.assertEqual(settings["scan_times"], ["09:00", "20:00"])
        self.assertEqual(settings["email"], "")
        self.assertEqual(settings["max_scan_times"], 5)

    def test_schedule_validation_and_deduplication(self):
        database.initialize_database(self.db_path)
        saved = database.set_scan_schedule(
            ["09:00", "09:00", "12:30", "23:59"], self.db_path
        )
        self.assertEqual(saved, ["09:00", "12:30", "23:59"])
        with self.assertRaises(ValueError):
            database.set_scan_schedule(
                ["00:00", "01:00", "02:00", "03:00", "04:00", "05:00"], self.db_path
            )

    def test_email_filter_and_scan_config(self):
        database.initialize_database(self.db_path)
        database.set_scan_email_filter("Recruiter@Example.com", self.db_path)
        config = database.get_scan_config(self.db_path)
        self.assertEqual(config["email_filter"], "recruiter@example.com")
        self.assertIn("recruiter@example.com", config["gmail_involvement_filter"])


class SchedulerTests(TemporaryDatabaseTestCase):
    def test_build_plist_from_database(self):
        database.initialize_database(self.db_path)
        scheduler_module = load_bin_module("scheduler")
        plist = scheduler_module.build_plist_dict(
            PROJECT_ROOT,
            Path.home(),
            self.root / "private",
            database.get_enabled_scan_intervals(self.db_path),
        )
        self.assertEqual(
            plist["StartCalendarInterval"],
            [{"Hour": 9, "Minute": 0}, {"Hour": 20, "Minute": 0}],
        )
        database.set_scan_schedule(["07:15"], self.db_path)
        plist = scheduler_module.build_plist_dict(
            PROJECT_ROOT,
            Path.home(),
            self.root / "private",
            database.get_enabled_scan_intervals(self.db_path),
        )
        self.assertEqual(plist["StartCalendarInterval"], [{"Hour": 7, "Minute": 15}])
        database.set_scan_schedule([], self.db_path)
        plist = scheduler_module.build_plist_dict(
            PROJECT_ROOT,
            Path.home(),
            self.root / "private",
            database.get_enabled_scan_intervals(self.db_path),
        )
        self.assertNotIn("StartCalendarInterval", plist)


class LocalServerTests(unittest.TestCase):
    def test_settings_get_and_put_require_csrf(self):
        local_server_module = load_bin_module("local_server")
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            db_path = data_dir / "interview_tracker.sqlite3"
            with mock.patch.object(local_server_module, "DATA_DIR", data_dir), mock.patch.object(
                local_server_module.database, "get_database_path", return_value=db_path
            ), mock.patch.object(local_server_module, "DB_FILE", db_path), mock.patch.object(
                local_server_module.scheduler,
                "apply_settings_with_rollback",
                return_value={"status": "ok", "email": "", "scan_times": ["10:00"], "max_scan_times": 5},
            ):
                local_server_module.database.initialize_database(db_path)
                port = local_server_module.start_local_server()
                try:
                    import http.client
                    import json

                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request("GET", "/settings")
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()
                    csrf_cookie = ""
                    for header, value in response.getheaders():
                        if header.lower() == "set-cookie":
                            csrf_cookie = value.split("=", 1)[1].split(";", 1)[0]
                    conn.request("GET", "/api/settings")
                    settings_response = conn.getresponse()
                    self.assertEqual(settings_response.status, 200)
                    settings_response.read()
                    conn.request(
                        "PUT",
                        "/api/settings",
                        body=json.dumps({"email": "", "scan_times": ["10:00"]}),
                        headers={"Content-Type": "application/json"},
                    )
                    blocked = conn.getresponse()
                    self.assertEqual(blocked.status, 403)
                    conn.request(
                        "PUT",
                        "/api/settings",
                        body=json.dumps({"email": "", "scan_times": ["10:00"]}),
                        headers={
                            "Content-Type": "application/json",
                            "Cookie": f"it_csrf={csrf_cookie}",
                            "X-CSRF-Token": csrf_cookie,
                            "Origin": f"http://127.0.0.1:{port}",
                        },
                    )
                    ok = conn.getresponse()
                    self.assertEqual(ok.status, 200)
                    conn.close()
                finally:
                    local_server_module.stop_local_server()


if __name__ == "__main__":
    unittest.main()
