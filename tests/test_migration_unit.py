"""Unit tests for bin/migrate_json_to_sqlite.py."""

from __future__ import annotations

import json
import sys
import unittest
from unittest import mock

from tests.support import TemporaryDatabaseTestCase, database, load_bin_module


class MigrateTests(TemporaryDatabaseTestCase):
    def test_migrate_not_found_initializes_empty_database(self):
        migrate_module = load_bin_module("migrate_json_to_sqlite")
        isolated_root = self.root / "isolated-project"
        isolated_root.mkdir()
        missing = isolated_root / "missing.json"
        with unittest.mock.patch.object(migrate_module, "ROOT", isolated_root):
            result = migrate_module.migrate(
                source=missing, db_path=self.db_path, remove_source=True
            )
        self.assertEqual(result["status"], "not_found")
        self.assertTrue(self.db_path.is_file())
        self.assertEqual(database.get_records(self.db_path), [])

    def test_migrate_rejects_invalid_json_shape(self):
        migrate_module = load_bin_module("migrate_json_to_sqlite")
        isolated_root = self.root / "isolated-project"
        isolated_root.mkdir()
        source = isolated_root / "bad.json"
        source.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        with unittest.mock.patch.object(migrate_module, "ROOT", isolated_root):
            with self.assertRaises(ValueError):
                migrate_module.migrate(
                    source=source, db_path=self.db_path, remove_source=True
                )

    def test_migrate_keep_source_leaves_legacy_file(self):
        migrate_module = load_bin_module("migrate_json_to_sqlite")
        isolated_root = self.root / "isolated-project"
        isolated_root.mkdir()
        source = isolated_root / "legacy.json"
        source_records = [
            {
                "thread_id": "keep-source-thread",
                "company": "Keep Source Co",
                "first_seen": "2022-05-06T07:08:09+00:00",
                "last_updated": "2023-06-07T08:09:10+00:00",
            }
        ]
        source.write_text(json.dumps(source_records), encoding="utf-8")
        with unittest.mock.patch.object(migrate_module, "ROOT", isolated_root):
            result = migrate_module.migrate(
                source=source, db_path=self.db_path, remove_source=False
            )
        self.assertEqual(result["status"], "migrated")
        self.assertFalse(result["source_removed"])
        self.assertTrue(source.is_file())
        migrated = database.get_records(self.db_path)
        self.assertEqual(len(migrated), 1)
        self.assertEqual(migrated[0]["company"], "Keep Source Co")

    def test_main_keep_source_flag(self):
        migrate_module = load_bin_module("migrate_json_to_sqlite")
        isolated_root = self.root / "isolated-project"
        isolated_root.mkdir()
        source = isolated_root / "legacy.json"
        source.write_text("[]", encoding="utf-8")
        with unittest.mock.patch.object(migrate_module, "ROOT", isolated_root), mock.patch.object(
            sys,
            "argv",
            [
                "migrate_json_to_sqlite.py",
                "--source",
                str(source),
                "--db",
                str(self.db_path),
                "--keep-source",
            ],
        ):
            rc = migrate_module.main()
        self.assertEqual(rc, 0)
        self.assertTrue(source.is_file())
        self.assertTrue(self.db_path.is_file())


if __name__ == "__main__":
    unittest.main()
