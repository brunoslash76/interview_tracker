"""Pure menu-bar helpers (no PyObjC imports)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping


def parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def is_rejected(record: Mapping[str, Any]) -> bool:
    status = (record.get("status") or "").lower()
    return any(word in status for word in ("reject", "withdraw", "declin"))


def upcoming_records(
    records: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    limit: int = 5,
) -> list[tuple[datetime, dict[str, Any]]]:
    current = now or datetime.now().astimezone()
    upcoming: list[tuple[datetime, dict[str, Any]]] = []
    for record in records:
        if is_rejected(record):
            continue
        dt = parse_dt(record.get("interview_datetime"))
        if dt and dt >= current:
            upcoming.append((dt, dict(record)))
    upcoming.sort(key=lambda pair: pair[0])
    return upcoming[:limit]


def action_count(
    records: Iterable[Mapping[str, Any]], *, now: datetime | None = None
) -> int:
    cues = (
        "take-home",
        "book ",
        "calendly",
        "not yet booked",
        "sign nda",
        "docusign",
        "complete",
        "respond",
        "reference",
    )
    current = now or datetime.now().astimezone()
    total = 0
    for record in records:
        if is_rejected(record):
            continue
        dt = parse_dt(record.get("interview_datetime"))
        if dt and dt >= current:
            total += 1
            continue
        blob = ((record.get("next_steps") or "") + " " + (record.get("status") or "")).lower()
        if any(cue in blob for cue in cues):
            total += 1
    return total
