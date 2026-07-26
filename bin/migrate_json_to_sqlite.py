#!/usr/bin/env python3
"""One-time, verified migration from the legacy JSON store to private SQLite."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import database

ROOT = Path(__file__).resolve().parent.parent
LEGACY_STORE = ROOT / "data" / "interviews.json"
PRIVATE_FILES = ("config.env", ".ntfy_topic", ".last_notified_hash")


def _find_imported(
    source: Mapping[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any] | None:
    thread_id = source.get("thread_id")
    if thread_id:
        match = next((row for row in records if row.get("thread_id") == thread_id), None)
        if match:
            return match
    company_key = database.normalize_company(source.get("company"))
    return next(
        (
            row
            for row in records
            if database.normalize_company(row.get("company")) == company_key
        ),
        None,
    )


def _verify(source_records: list[dict[str, Any]], db_records: list[dict[str, Any]]) -> None:
    for source in source_records:
        imported = _find_imported(source, db_records)
        if imported is None:
            raise RuntimeError(
                f"migration verification failed: missing {source.get('company', '<unknown>')}"
            )
        for field in database.WRITABLE_FIELDS:
            expected = source.get(field)
            if expected is not None and imported.get(field) != expected:
                raise RuntimeError(
                    "migration verification failed for "
                    f"{source.get('company', '<unknown>')}.{field}"
                )


def _migrate_private_files(db_path: Path, remove_source: bool) -> list[str]:
    backup_dir = db_path.parent / "backups"
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    migrated = []
    for filename in PRIVATE_FILES:
        legacy_file = ROOT / filename
        if not legacy_file.exists():
            continue
        private_file = db_path.parent / filename
        if private_file.exists() and private_file.read_bytes() != legacy_file.read_bytes():
            backup_dir.mkdir(parents=True, exist_ok=True)
            private_file = backup_dir / f"{filename}.{timestamp}"
        private_file.write_bytes(legacy_file.read_bytes())
        if filename == "config.env":
            os.chmod(private_file, 0o600)
        if private_file.read_bytes() != legacy_file.read_bytes():
            raise RuntimeError(f"private file verification failed: {filename}")
        if remove_source:
            legacy_file.unlink()
        migrated.append(str(private_file))
    return migrated


def migrate(
    source: Path = LEGACY_STORE,
    db_path: Path | None = None,
    remove_source: bool = True,
) -> dict[str, Any]:
    source = source.expanduser().resolve()
    resolved_db = database.get_database_path(db_path)
    if not source.exists():
        database.initialize_database(resolved_db)
        return {
            "status": "not_found",
            "source": str(source),
            "database": str(resolved_db),
            "private_files": _migrate_private_files(resolved_db, remove_source),
        }

    raw = source.read_bytes()
    records = json.loads(raw)
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ValueError("legacy store must be a JSON array of objects")

    database.initialize_database(resolved_db)
    database.import_records(records, resolved_db)
    imported = database.get_records(resolved_db)
    _verify(records, imported)

    backup_dir = resolved_db.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"interviews.pre-sqlite.{timestamp}.json"
    counter = 1
    while backup.exists():
        backup = backup_dir / f"interviews.pre-sqlite.{timestamp}.{counter}.json"
        counter += 1
    backup.write_bytes(raw)
    if backup.read_bytes() != raw:
        raise RuntimeError("migration backup verification failed")

    database.merge_scan([], resolved_db, update_scan_date=False)
    migrated_private_files = _migrate_private_files(resolved_db, remove_source)

    if remove_source:
        source.unlink()

    return {
        "status": "migrated",
        "source": str(source),
        "database": str(resolved_db),
        "backup": str(backup),
        "source_count": len(records),
        "database_count": len(imported),
        "source_removed": remove_source,
        "private_files": migrated_private_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=LEGACY_STORE)
    parser.add_argument("--db", type=Path)
    parser.add_argument(
        "--keep-source",
        action="store_true",
        help="verify and back up the import but leave the legacy JSON in place",
    )
    args = parser.parse_args()
    result = migrate(args.source, args.db, remove_source=not args.keep_source)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
