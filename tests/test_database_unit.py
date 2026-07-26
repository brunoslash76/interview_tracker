"""Unit tests for bin/database.py."""

from __future__ import annotations

import os
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest import mock

from tests.support import TemporaryDatabaseTestCase, database


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

    def test_schema_version_too_new_raises(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("PRAGMA user_version = 99")
        with self.assertRaises(RuntimeError) as ctx:
            database.initialize_database(self.db_path)
        self.assertIn("newer than supported", str(ctx.exception))

    def test_connection_uses_delete_journal_mode(self):
        database.initialize_database(self.db_path)
        with sqlite3.connect(self.db_path) as connection:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "delete")


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

    def test_merge_preserves_existing_fields_when_incoming_values_are_null(self):
        database.merge_records(
            [
                {
                    "thread_id": "keep-notes",
                    "company": "Notes Co",
                    "notes": "important detail",
                    "position": "Engineer",
                }
            ],
            self.db_path,
            timestamp="2026-01-01T00:00:00+00:00",
        )
        records, _, updated = database.merge_records(
            [
                {
                    "thread_id": "keep-notes",
                    "company": "Notes Co",
                    "notes": None,
                    "position": "Staff Engineer",
                }
            ],
            self.db_path,
            timestamp="2026-02-01T00:00:00+00:00",
        )
        self.assertEqual(updated, 1)
        self.assertEqual(records[0]["notes"], "important detail")
        self.assertEqual(records[0]["position"], "Staff Engineer")

    def test_merge_records_rejects_non_mapping_entries(self):
        database.initialize_database(self.db_path)
        with self.assertRaises(TypeError):
            database.merge_records(["not-a-mapping"], self.db_path)


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

    def test_merge_scan_skips_scan_date_update_when_disabled(self):
        database.initialize_database(self.db_path)
        database.set_last_successful_scan_date("2025-06-01", self.db_path)
        database.merge_scan([], self.db_path, update_scan_date=False)
        self.assertEqual(
            database.get_last_successful_scan_date(self.db_path), "2025-06-01"
        )
        database.merge_scan([], self.db_path, scan_date="2026-01-15")
        self.assertEqual(
            database.get_last_successful_scan_date(self.db_path), "2026-01-15"
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


class ParseDatetimeTests(unittest.TestCase):
    def test_parse_datetime_accepts_z_suffix(self):
        parsed = database.parse_datetime("2026-03-01T12:00:00Z")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.utcoffset(), timezone.utc.utcoffset(None))

    def test_parse_datetime_returns_none_for_invalid(self):
        self.assertIsNone(database.parse_datetime("not-a-date"))
        self.assertIsNone(database.parse_datetime(""))
        self.assertIsNone(database.parse_datetime(None))


class GmailFilterTests(unittest.TestCase):
    def test_build_gmail_involvement_filter_escapes_quotes(self):
        fragment = database.build_gmail_involvement_filter('recruiter@"evil".com')
        self.assertIn('\\"', fragment)
        self.assertIn('to:"recruiter@\\"evil\\".com"', fragment)


class EmailFilterTests(unittest.TestCase):
    def test_normalize_email_filter_rejects_invalid(self):
        with self.assertRaises(ValueError):
            database.normalize_email_filter("not-an-email")


class DatabasePathTests(TemporaryDatabaseTestCase):
    def test_get_database_path_honors_env_vars(self):
        explicit = self.root / "custom.sqlite3"
        self.assertEqual(database.get_database_path(explicit), explicit)

        db_env = self.root / "from-db-env.sqlite3"
        data_env = self.root / "data-dir"
        with mock.patch.dict(
            os.environ,
            {
                "INTERVIEW_TRACKER_DB": str(db_env),
                "INTERVIEW_TRACKER_DATA_DIR": str(data_env),
            },
            clear=False,
        ):
            self.assertEqual(database.get_database_path(), db_env)
            self.assertEqual(
                database.get_database_path(None),
                db_env,
            )

        with mock.patch.dict(
            os.environ,
            {"INTERVIEW_TRACKER_DB": "", "INTERVIEW_TRACKER_DATA_DIR": str(data_env)},
            clear=False,
        ):
            os.environ.pop("INTERVIEW_TRACKER_DB", None)
            expected = data_env / database.DEFAULT_DB_NAME
            self.assertEqual(database.get_database_path(), expected)


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


if __name__ == "__main__":
    unittest.main()
