#!/usr/bin/env python3
"""Private SQLite persistence for Interview Tracker.

This module intentionally uses only the Python standard library.  The database
uses SQLite's rollback journal (not WAL) so a successful write always changes
the main database file watched by launchd.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Union


SCHEMA_VERSION = 2
DEFAULT_DATA_DIR = Path.home() / "Library" / "Application Support" / "InterviewTracker"
DEFAULT_DB_NAME = "interview_tracker.sqlite3"
LAST_SUCCESSFUL_SCAN_DATE_KEY = "last_successful_scan_date"
HTTP_LISTEN_PORT_KEY = "http_listen_port"
MAX_SCAN_TIMES = 5
DEFAULT_SCAN_TIMES = ((9, 0), (20, 0))
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

APPLICATION_FIELDS = (
    "thread_id",
    "company",
    "company_key",
    "position",
    "stage",
    "status",
    "interview_datetime",
    "contact_person",
    "next_steps",
    "meeting_link",
    "last_email_date",
    "notes",
    "first_seen",
    "last_updated",
)
WRITABLE_FIELDS = tuple(field for field in APPLICATION_FIELDS if field != "company_key")

PathLike = Union[str, os.PathLike[str]]


def get_database_path(db_path: Optional[PathLike] = None) -> Path:
    """Resolve an explicit path, then INTERVIEW_TRACKER_DB, then the data dir."""
    if db_path is not None:
        return Path(db_path).expanduser()
    configured_db = os.environ.get("INTERVIEW_TRACKER_DB")
    if configured_db:
        return Path(configured_db).expanduser()
    data_dir = os.environ.get("INTERVIEW_TRACKER_DATA_DIR")
    return (Path(data_dir).expanduser() if data_dir else DEFAULT_DATA_DIR) / DEFAULT_DB_NAME


def normalize_company(company: Any) -> str:
    """Return the legacy company deduplication key."""
    return re.sub(r"[^a-z0-9]", "", str(company or "").lower())


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_datetime(value: Any) -> Optional[datetime]:
    """Best-effort parsing that always returns an aware datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        raw = str(value).strip()
        if not raw:
            return None
        iso_value = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(raw)
            except (TypeError, ValueError, OverflowError):
                parsed = None
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
                    try:
                        parsed = datetime.strptime(raw, fmt)
                        break
                    except ValueError:
                        continue
                if parsed is None:
                    return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def _connect(db_path: Optional[PathLike] = None) -> sqlite3.Connection:
    path = get_database_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    # DELETE is deliberate: WAL may leave the main file unchanged after writes.
    connection.execute("PRAGMA journal_mode = DELETE")
    return connection


def _migrate(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {version} is newer than supported version {SCHEMA_VERSION}"
        )
    if version == 0:
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE applications (
                thread_id TEXT UNIQUE,
                company TEXT,
                company_key TEXT NOT NULL,
                position TEXT,
                stage TEXT,
                status TEXT,
                interview_datetime TEXT,
                contact_person TEXT,
                next_steps TEXT,
                meeting_link TEXT,
                last_email_date TEXT,
                notes TEXT,
                first_seen TEXT,
                last_updated TEXT
            );
            CREATE INDEX applications_company_key_idx ON applications(company_key);

            CREATE TABLE scan_runs (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                data_hash TEXT NOT NULL,
                total INTEGER NOT NULL,
                upcoming INTEGER NOT NULL,
                offers INTEGER NOT NULL,
                completed INTEGER NOT NULL,
                new_company_names TEXT NOT NULL,
                new_count INTEGER NOT NULL,
                updated_count INTEGER NOT NULL,
                successful INTEGER NOT NULL DEFAULT 1 CHECK (successful IN (0, 1))
            );
            CREATE INDEX scan_runs_timestamp_idx ON scan_runs(timestamp DESC);

            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            PRAGMA user_version = 1;
            COMMIT;
            """
        )
        version = 1
    if version == 1:
        connection.executescript(
            f"""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS scan_schedule (
                id INTEGER PRIMARY KEY,
                hour INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
                minute INTEGER NOT NULL CHECK (minute BETWEEN 0 AND 59),
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                sort_order INTEGER NOT NULL DEFAULT 0,
                UNIQUE (hour, minute)
            );
            CREATE TABLE IF NOT EXISTS scan_preferences (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                email_filter TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            INSERT OR IGNORE INTO scan_preferences (id, email_filter, updated_at)
            VALUES (1, '', '{now_iso()}');
            INSERT OR IGNORE INTO scan_schedule (hour, minute, enabled, sort_order)
            VALUES (9, 0, 1, 0), (20, 0, 1, 1);
            PRAGMA user_version = 2;
            COMMIT;
            """
        )


def initialize_database(db_path: Optional[PathLike] = None) -> Path:
    """Create the database and apply all supported schema migrations."""
    connection = _connect(db_path)
    try:
        _migrate(connection)
    finally:
        connection.close()
    return get_database_path(db_path)


init_db = initialize_database


def _ready_connection(db_path: Optional[PathLike] = None) -> sqlite3.Connection:
    connection = _connect(db_path)
    try:
        _migrate(connection)
    except Exception:
        connection.close()
        raise
    return connection


def _application_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {field: row[field] for field in APPLICATION_FIELDS if field != "company_key"}


def _sort_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(record: Mapping[str, Any]) -> tuple[float, str, str]:
        parsed = parse_datetime(record.get("last_updated"))
        stamp = parsed.timestamp() if parsed else float("-inf")
        return (
            stamp,
            str(record.get("company") or "").casefold(),
            str(record.get("thread_id") or ""),
        )

    return sorted(records, key=key, reverse=True)


def _read_records(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT " + ", ".join(APPLICATION_FIELDS) + " FROM applications"
    ).fetchall()
    return _sort_records(_application_from_row(row) for row in rows)


def get_records(db_path: Optional[PathLike] = None) -> list[dict[str, Any]]:
    connection = _ready_connection(db_path)
    try:
        return _read_records(connection)
    finally:
        connection.close()


read_records = get_records


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def records_hash(records: Iterable[Mapping[str, Any]]) -> str:
    """Return a deterministic SHA-256 of records in canonical sorted order."""
    clean = [{field: record.get(field) for field in WRITABLE_FIELDS} for record in records]
    canonical_records = _sort_records(clean)
    return hashlib.sha256(_canonical_json(canonical_records).encode("utf-8")).hexdigest()


compute_data_hash = records_hash


def is_rejected(record: Mapping[str, Any]) -> bool:
    status = str(record.get("status") or "").lower()
    return any(word in status for word in ("reject", "withdraw", "declin"))


def compute_stats(
    records: Iterable[Mapping[str, Any]], at: Optional[datetime] = None
) -> dict[str, int]:
    """Compute the same total/upcoming/offers/completed counters as the JSON store."""
    current = at or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.now().astimezone().tzinfo)
    current = current.astimezone(timezone.utc)
    materialized = list(records)
    upcoming = completed = offers = 0
    for record in materialized:
        status = str(record.get("status") or "")
        if record.get("stage") == "Offer" or "offer" in status.lower():
            offers += 1
        interview = parse_datetime(record.get("interview_datetime"))
        if interview:
            interview = interview.astimezone(timezone.utc)
            if interview >= current and not is_rejected(record):
                upcoming += 1
            elif interview < current:
                completed += 1
    return {
        "total": len(materialized),
        "upcoming": upcoming,
        "offers": offers,
        "completed": completed,
    }


def _insert_application(
    connection: sqlite3.Connection, record: Mapping[str, Any], timestamp: str
) -> int:
    values = {field: record.get(field) for field in WRITABLE_FIELDS}
    values["first_seen"] = values["first_seen"] or timestamp
    values["last_updated"] = values["last_updated"] or timestamp
    values["company_key"] = normalize_company(values["company"])
    columns = APPLICATION_FIELDS
    placeholders = ", ".join("?" for _ in columns)
    cursor = connection.execute(
        f"INSERT INTO applications ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(values.get(column) for column in columns),
    )
    return int(cursor.lastrowid)


def _merge_in_transaction(
    connection: sqlite3.Connection,
    incoming: Iterable[Mapping[str, Any]],
    timestamp: str,
    preserve_timestamps: bool,
) -> tuple[list[dict[str, Any]], list[str], int]:
    rows = connection.execute(
        "SELECT rowid AS _rowid, " + ", ".join(APPLICATION_FIELDS) + " FROM applications"
    ).fetchall()
    by_thread = {row["thread_id"]: row for row in rows if row["thread_id"]}
    by_company: dict[str, sqlite3.Row] = {}
    for row in rows:
        if row["company_key"]:
            by_company.setdefault(row["company_key"], row)
    known_before = set(by_company)
    new_company_names: list[str] = []
    updated_count = 0

    for raw_record in incoming:
        if not isinstance(raw_record, Mapping):
            raise TypeError("every application record must be a mapping")
        record = {field: raw_record.get(field) for field in WRITABLE_FIELDS}
        thread_id = record.get("thread_id")
        company_key = normalize_company(record.get("company"))
        target = by_thread.get(thread_id) if thread_id else None
        if target is None and company_key:
            target = by_company.get(company_key)

        if target is None:
            rowid = _insert_application(connection, record, timestamp)
            target = connection.execute(
                "SELECT rowid AS _rowid, "
                + ", ".join(APPLICATION_FIELDS)
                + " FROM applications WHERE rowid = ?",
                (rowid,),
            ).fetchone()
            if thread_id:
                by_thread[str(thread_id)] = target
            if company_key:
                by_company[company_key] = target
                if company_key not in known_before and record.get("company"):
                    new_company_names.append(str(record["company"]))
            continue

        existing = dict(target)
        merged = {field: existing.get(field) for field in WRITABLE_FIELDS}
        for field, value in record.items():
            if value is not None:
                merged[field] = value
        merged["first_seen"] = existing.get("first_seen") or record.get("first_seen") or timestamp
        if preserve_timestamps:
            merged["last_updated"] = (
                record.get("last_updated") or existing.get("last_updated") or timestamp
            )
        else:
            merged["last_updated"] = timestamp
        merged_key = normalize_company(merged.get("company"))
        assignments = ", ".join(f"{field} = ?" for field in APPLICATION_FIELDS)
        connection.execute(
            f"UPDATE applications SET {assignments} WHERE rowid = ?",
            tuple(
                merged_key if field == "company_key" else merged.get(field)
                for field in APPLICATION_FIELDS
            )
            + (existing["_rowid"],),
        )
        refreshed = connection.execute(
            "SELECT rowid AS _rowid, "
            + ", ".join(APPLICATION_FIELDS)
            + " FROM applications WHERE rowid = ?",
            (existing["_rowid"],),
        ).fetchone()
        if existing.get("thread_id"):
            by_thread[existing["thread_id"]] = refreshed
        if merged.get("thread_id"):
            by_thread[merged["thread_id"]] = refreshed
        if existing.get("company_key"):
            by_company[existing["company_key"]] = refreshed
        if merged_key:
            by_company[merged_key] = refreshed
        updated_count += 1

    records = _read_records(connection)
    return records, sorted(set(new_company_names)), updated_count


def merge_records(
    incoming: Iterable[Mapping[str, Any]],
    db_path: Optional[PathLike] = None,
    timestamp: Optional[str] = None,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Merge records and return (sorted records, new company names, updated count)."""
    connection = _ready_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        result = _merge_in_transaction(connection, incoming, timestamp or now_iso(), False)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def import_records(
    records: Iterable[Mapping[str, Any]],
    db_path: Optional[PathLike] = None,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Idempotently import legacy records without bumping supplied timestamps."""
    connection = _ready_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        result = _merge_in_transaction(connection, records, now_iso(), True)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _summary_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "timestamp": row["timestamp"],
        "data_hash": row["data_hash"],
        "total": row["total"],
        "upcoming": row["upcoming"],
        "offers": row["offers"],
        "completed": row["completed"],
        "new_company_names": json.loads(row["new_company_names"]),
        "new_count": row["new_count"],
        "updated_count": row["updated_count"],
    }


def merge_scan(
    incoming: Iterable[Mapping[str, Any]],
    db_path: Optional[PathLike] = None,
    timestamp: Optional[str] = None,
    scan_date: Optional[str] = None,
    update_scan_date: bool = True,
) -> dict[str, Any]:
    """Atomically merge one successful scan and append its summary row."""
    run_timestamp = timestamp or now_iso()
    parsed_timestamp = parse_datetime(run_timestamp)
    successful_date = scan_date or (
        parsed_timestamp.astimezone().date().isoformat()
        if parsed_timestamp
        else datetime.now().astimezone().date().isoformat()
    )
    connection = _ready_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        records, new_names, updated_count = _merge_in_transaction(
            connection, incoming, run_timestamp, False
        )
        stats = compute_stats(records, at=parsed_timestamp)
        summary = {
            "timestamp": run_timestamp,
            "data_hash": records_hash(records),
            **stats,
            "new_company_names": new_names,
            "new_count": len(new_names),
            "updated_count": updated_count,
        }
        connection.execute(
            """
            INSERT INTO scan_runs (
                timestamp, data_hash, total, upcoming, offers, completed,
                new_company_names, new_count, updated_count, successful
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                summary["timestamp"],
                summary["data_hash"],
                summary["total"],
                summary["upcoming"],
                summary["offers"],
                summary["completed"],
                json.dumps(new_names, ensure_ascii=False),
                summary["new_count"],
                summary["updated_count"],
            ),
        )
        if update_scan_date:
            connection.execute(
                """
                INSERT INTO metadata (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (LAST_SUCCESSFUL_SCAN_DATE_KEY, successful_date),
            )
        connection.commit()
        return summary
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_latest_summary(db_path: Optional[PathLike] = None) -> Optional[dict[str, Any]]:
    connection = _ready_connection(db_path)
    try:
        row = connection.execute(
            "SELECT * FROM scan_runs WHERE successful = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _summary_from_row(row) if row else None
    finally:
        connection.close()


read_summary = get_latest_summary


def get_metadata(key: str, db_path: Optional[PathLike] = None) -> Optional[str]:
    connection = _ready_connection(db_path)
    try:
        row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None
    finally:
        connection.close()


def set_metadata(key: str, value: str, db_path: Optional[PathLike] = None) -> None:
    if not key:
        raise ValueError("metadata key must not be empty")
    connection = _ready_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO metadata (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_last_successful_scan_date(db_path: Optional[PathLike] = None) -> Optional[str]:
    return get_metadata(LAST_SUCCESSFUL_SCAN_DATE_KEY, db_path)


def set_last_successful_scan_date(
    value: Union[str, date, datetime], db_path: Optional[PathLike] = None
) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"invalid scan date: {value!r}")
    normalized = parsed.date().isoformat()
    set_metadata(LAST_SUCCESSFUL_SCAN_DATE_KEY, normalized, db_path)
    return normalized


def parse_time_value(value: Any) -> tuple[int, int]:
    """Parse an HTML time input value such as 09:00 or 09:00:00."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("time value is required")
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", raw)
    if not match:
        raise ValueError(f"invalid time value: {value!r}")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"time out of range: {value!r}")
    return hour, minute


def format_time_value(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def normalize_email_filter(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not EMAIL_RE.fullmatch(raw):
        raise ValueError(f"invalid email address: {value!r}")
    return raw.casefold()


def get_scan_schedule(db_path: Optional[PathLike] = None) -> list[dict[str, Any]]:
    connection = _ready_connection(db_path)
    try:
        rows = connection.execute(
            """
            SELECT hour, minute, enabled, sort_order
            FROM scan_schedule
            ORDER BY sort_order ASC, hour ASC, minute ASC
            """
        ).fetchall()
        return [
            {
                "hour": row["hour"],
                "minute": row["minute"],
                "enabled": bool(row["enabled"]),
                "time": format_time_value(row["hour"], row["minute"]),
            }
            for row in rows
        ]
    finally:
        connection.close()


def get_enabled_scan_intervals(db_path: Optional[PathLike] = None) -> list[tuple[int, int]]:
    return [
        (entry["hour"], entry["minute"])
        for entry in get_scan_schedule(db_path)
        if entry["enabled"]
    ]


def set_scan_schedule(
    times: Iterable[Any], db_path: Optional[PathLike] = None
) -> list[str]:
    """Replace the daily scan schedule with up to five unique HH:MM values."""
    normalized: list[tuple[int, int]] = []
    for value in times:
        hour, minute = parse_time_value(value)
        slot = (hour, minute)
        if slot not in normalized:
            normalized.append(slot)
    if len(normalized) > MAX_SCAN_TIMES:
        raise ValueError(f"at most {MAX_SCAN_TIMES} scan times are allowed")

    connection = _ready_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM scan_schedule")
        for index, (hour, minute) in enumerate(normalized):
            connection.execute(
                """
                INSERT INTO scan_schedule (hour, minute, enabled, sort_order)
                VALUES (?, ?, 1, ?)
                """,
                (hour, minute, index),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return [format_time_value(hour, minute) for hour, minute in normalized]


def get_scan_email_filter(db_path: Optional[PathLike] = None) -> str:
    connection = _ready_connection(db_path)
    try:
        row = connection.execute(
            "SELECT email_filter FROM scan_preferences WHERE id = 1"
        ).fetchone()
        return str(row["email_filter"]) if row else ""
    finally:
        connection.close()


def set_scan_email_filter(value: Any, db_path: Optional[PathLike] = None) -> str:
    normalized = normalize_email_filter(value)
    connection = _ready_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO scan_preferences (id, email_filter, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                email_filter = excluded.email_filter,
                updated_at = excluded.updated_at
            """,
            (normalized, now_iso()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return normalized


def get_user_settings(db_path: Optional[PathLike] = None) -> dict[str, Any]:
    schedule = get_scan_schedule(db_path)
    return {
        "email": get_scan_email_filter(db_path),
        "scan_times": [entry["time"] for entry in schedule if entry["enabled"]],
        "max_scan_times": MAX_SCAN_TIMES,
    }


def update_user_settings(
    email: Any,
    scan_times: Iterable[Any],
    db_path: Optional[PathLike] = None,
) -> dict[str, Any]:
    saved_email = set_scan_email_filter(email, db_path)
    saved_times = set_scan_schedule(scan_times, db_path)
    return {
        "email": saved_email,
        "scan_times": saved_times,
        "max_scan_times": MAX_SCAN_TIMES,
    }


def build_gmail_involvement_filter(email: str) -> str:
    """Best-effort Gmail query fragment for messages involving an address."""
    if not email:
        return ""
    escaped = email.replace('"', '\\"')
    return f'(to:"{escaped}" OR from:"{escaped}")'


def get_scan_config(db_path: Optional[PathLike] = None) -> dict[str, Any]:
    email = get_scan_email_filter(db_path)
    return {
        "email_filter": email,
        "gmail_involvement_filter": build_gmail_involvement_filter(email),
        "scan_times": get_enabled_scan_intervals(db_path),
    }


def _json_print(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Interview Tracker SQLite store")
    parser.add_argument("--db", help="override the database path")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="initialize the database")
    subparsers.add_parser("records-json", help="print all application records")
    subparsers.add_parser("summary-json", help="print the latest scan summary")
    subparsers.add_parser("last-scan-date", help="print the last successful scan date")
    set_date_parser = subparsers.add_parser(
        "set-last-scan-date", help="set the last successful scan date"
    )
    set_date_parser.add_argument("date")
    subparsers.add_parser("settings-json", help="print user settings")
    subparsers.add_parser("scan-config-json", help="print Gmail scan configuration")
    args = parser.parse_args(argv)

    if args.command == "init":
        print(initialize_database(args.db))
    elif args.command == "records-json":
        _json_print(get_records(args.db))
    elif args.command == "summary-json":
        _json_print(get_latest_summary(args.db))
    elif args.command == "last-scan-date":
        value = get_last_successful_scan_date(args.db)
        if value is not None:
            print(value)
    elif args.command == "set-last-scan-date":
        print(set_last_successful_scan_date(args.date, args.db))
    elif args.command == "settings-json":
        _json_print(get_user_settings(args.db))
    elif args.command == "scan-config-json":
        _json_print(get_scan_config(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
