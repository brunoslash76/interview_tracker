#!/usr/bin/env python3
"""Interview Tracker — Gmail scan + persist + dashboard regen (all platforms)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import database
import platform_utils

ROOT = platform_utils.project_root()
SCAN_TIMEOUT_SECONDS = 600

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "interviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "thread_id": {"type": "string", "description": "Gmail thread ID"},
                    "company": {"type": "string"},
                    "position": {"type": "string"},
                    "stage": {
                        "type": "string",
                        "enum": [
                            "Initial Contact",
                            "Phone Screen",
                            "Technical Round",
                            "Final Interview",
                            "Offer",
                        ],
                    },
                    "status": {"type": "string"},
                    "interview_datetime": {"type": ["string", "null"]},
                    "contact_person": {"type": ["string", "null"]},
                    "next_steps": {"type": ["string", "null"]},
                    "meeting_link": {"type": ["string", "null"]},
                    "last_email_date": {"type": ["string", "null"]},
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["thread_id", "company", "stage", "status"],
            },
        },
        "latest_email_date_seen": {"type": ["string", "null"]},
    },
    "required": ["interviews", "latest_email_date_seen"],
}


def _data_dir() -> Path:
    return platform_utils.default_data_dir()


def _log_line(log_file: Path, message: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def emit_progress(progress_file: Path, phase: str, detail: str = "") -> None:
    payload: dict[str, object] = {
        "phase": phase,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if detail:
        payload["detail"] = detail
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file.write_text(json.dumps(payload), encoding="utf-8")
    print(f"IT_PROGRESS:{phase}", file=sys.stderr)


def build_prompt(
    search_query: str,
    window_mode: str,
    email_watermark: str,
    email_filter: str,
    gmail_involvement: str,
) -> str:
    prompt = f"""You are scanning my Gmail for job-interview-related email threads: interview invitations, scheduling/confirmation emails, recruiter or HR replies about an application, technical/onsite interview logistics, and offer communications. Ignore generic job-board alerts, newsletters, and marketing.

Search using mcp__claude_ai_Gmail__search_threads with queries covering interview-related terms (e.g. interview, phone screen, technical interview, onsite, recruiter, hiring, offer, schedule a call, next steps). EVERY search query MUST include this exact boundary unchanged: {search_query}. Never issue a search without it and never replace it with an older or broader boundary. Run several searches with different terms since one query will not catch everything. Only call mcp__claude_ai_Gmail__get_thread for thread IDs returned by those bounded searches. For each candidate thread, read the full content before extracting data — do not guess from snippets alone."""
    if window_mode == "recent-watermark":
        prompt += f"""

RECENT-SCAN GUARDRAIL: the previous successful scan was less than 30 minutes ago. The newest message it read was {email_watermark}. Process only messages newer than that watermark. Older messages included in a matching thread are context only; do not re-extract or reconsider them unless a newer message changes that application's current state."""
    if gmail_involvement:
        prompt += f"""

Every Gmail search query MUST also include this involvement filter for {email_filter}: {gmail_involvement}. Do not return threads that do not involve this address."""
    prompt += """

For every distinct company/application you find, extract one record with:
- thread_id: the Gmail thread ID (if a company has multiple threads for the SAME application, pick the thread with the latest activity)
- company: company name
- position: job title/position
- stage: classify into exactly one of Initial Contact, Phone Screen, Technical Round, Final Interview, Offer — based on the FURTHEST stage reached in the thread, not the first email
- status: current application status in plain text (e.g. Active, Awaiting Response, Rejected, Withdrawn, Offer Received)
- interview_datetime: ISO 8601 date/time if a specific interview was scheduled and still relevant, else null
- contact_person: name (and email if available) of the recruiter/interviewer if mentioned, else null
- next_steps: brief plain-text description of what I concretely need to DO next, else null
- meeting_link: video call / scheduling link if present, else null
- last_email_date: ISO 8601 date of the most recent email in the thread
- notes: any other useful short context, else null

Also return latest_email_date_seen as the ISO 8601 timestamp of the newest individual Gmail message you actually inspected across every fetched thread. Return null only when no thread was fetched. This watermark must reflect message data, not the current clock time.

Output ONLY the structured JSON matching the provided schema — no prose, no markdown fences."""
    return prompt


def parse_claude_output(raw_stdout: str) -> dict[str, object]:
    outer = json.loads(raw_stdout)
    result = outer.get("result")
    if isinstance(result, str):
        result = json.loads(result)
    if not isinstance(result, dict):
        raise TypeError("claude result must be an object")
    interviews = result.get("interviews", [])
    if not isinstance(interviews, list):
        raise TypeError("interviews must be an array")
    watermark = result.get("latest_email_date_seen")
    if watermark is not None and not isinstance(watermark, str):
        raise TypeError("latest_email_date_seen must be a string or null")
    return {"interviews": interviews, "latest_email_date_seen": watermark}


def main() -> int:
    data_dir = _data_dir()
    db_file = data_dir / database.DEFAULT_DB_NAME
    log_file = data_dir / "logs" / "scan.log"
    progress_file = data_dir / ".scan_progress.json"
    lock_dir = data_dir / "scan.lock"

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)

    config = platform_utils.load_config_env(data_dir)
    claude_bin = platform_utils.resolve_claude_bin(
        config.get("CLAUDE_BIN") or os.environ.get("CLAUDE_BIN")
    )

    try:
        lock_dir.mkdir()
    except FileExistsError:
        _log_line(log_file, "scan already running — exiting")
        emit_progress(progress_file, "busy", "scan lock held")
        return 2

    raw_file: Path | None = None
    try:
        raw_file = Path(tempfile.mkstemp(prefix="raw_extraction.", dir=data_dir)[1])
        emit_progress(progress_file, "starting")
        _log_line(log_file, f"=== scan started (claude: {claude_bin or 'missing'}) ===")

        if not claude_bin:
            _log_line(log_file, "ERROR: claude CLI not found. Set CLAUDE_BIN in config.env.")
            emit_progress(progress_file, "failed", "claude CLI not found")
            return 1

        database.initialize_database(db_file)
        scan_window = database.get_scan_window(db_path=db_file)
        search_query = scan_window["query"]
        window_mode = scan_window["mode"]
        email_watermark = scan_window.get("latest_email_watermark") or ""
        _log_line(log_file, f"searching Gmail with {search_query} (mode: {window_mode})")

        scan_config = database.get_scan_config(db_path=db_file)
        email_filter = scan_config.get("email_filter", "")
        gmail_involvement = scan_config.get("gmail_involvement_filter", "")
        if email_filter:
            _log_line(log_file, f"using email involvement filter for {email_filter}")
        emit_progress(progress_file, "config")

        prompt = build_prompt(
            search_query,
            window_mode,
            email_watermark,
            email_filter,
            gmail_involvement,
        )
        emit_progress(progress_file, "extracting")

        cmd = [
            claude_bin,
            "-p",
            prompt,
            "--system-prompt",
            (
                "You are a headless data-extraction worker with no memory, no persona, "
                "and no context beyond this task. Use only the tools explicitly provided. "
                "Follow the instructions exactly and produce only the requested output."
            ),
            "--allowedTools",
            "mcp__claude_ai_Gmail__search_threads mcp__claude_ai_Gmail__get_thread",
            "--disallowedTools",
            (
                "Bash Read Write Edit NotebookEdit WebFetch WebSearch Agent Task "
                "TaskCreate TaskUpdate TaskGet TaskList TaskOutput TaskStop Artifact "
                "ExitPlanMode"
            ),
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(JSON_SCHEMA),
            "--no-session-persistence",
        ]

        env = os.environ.copy()
        env.setdefault("HOME", str(Path.home()))
        env["INTERVIEW_TRACKER_DATA_DIR"] = str(data_dir)
        path_prefix = platform_utils.default_path_env()
        env["PATH"] = path_prefix + os.pathsep + env.get("PATH", "")

        with log_file.open("a", encoding="utf-8") as log_handle:
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(ROOT),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=SCAN_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                _log_line(log_file, "ERROR: claude invocation timed out")
                emit_progress(progress_file, "failed", "timeout")
                return 1
            if completed.stderr:
                log_handle.write(completed.stderr)
            if completed.returncode != 0:
                _log_line(log_file, "ERROR: claude invocation failed")
                emit_progress(progress_file, "failed", "claude extraction failed")
                return 1

        try:
            parsed = parse_claude_output(completed.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            _log_line(log_file, f"ERROR: claude JSON parsing failed: {exc}")
            emit_progress(progress_file, "failed", "claude extraction failed")
            return 1

        raw_file.write_text(json.dumps(parsed), encoding="utf-8")
        count = len(parsed["interviews"])  # type: ignore[arg-type]
        _log_line(log_file, f"extracted {count} candidate records")
        emit_progress(progress_file, "merging", str(count))

        merge_cmd = [
            platform_utils.resolve_python_for_subprocess(ROOT),
            str(ROOT / "bin" / "merge_interviews.py"),
            str(raw_file),
        ]
        merge = subprocess.run(
            merge_cmd,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        if merge.stdout:
            _log_line(log_file, merge.stdout.strip())
        if merge.returncode != 0:
            detail = merge.stderr.strip() or "merge failed"
            _log_line(log_file, f"ERROR: failed to merge extracted records: {detail}")
            emit_progress(progress_file, "failed", "merge failed")
            return 1

        emit_progress(progress_file, "complete", str(count))
        _log_line(log_file, "=== scan completed ===")
        return 0
    finally:
        if raw_file and raw_file.is_file():
            raw_file.unlink(missing_ok=True)
        try:
            lock_dir.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
