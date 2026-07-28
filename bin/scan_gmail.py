#!/usr/bin/env python3
"""Interview Tracker — Gmail scan + persist + dashboard regen (all platforms)."""

from __future__ import annotations

import json
import os
import argparse
import queue
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import database
import platform_utils
import scan_runner

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

DISCOVERY_SCHEMA = {
    "type": "object",
    "properties": {
        "thread_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["thread_ids"],
}


def _data_dir() -> Path:
    return platform_utils.default_data_dir()


def _log_line(log_file: Path, message: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def emit_progress(
    progress_file: Path,
    phase: str,
    detail: str = "",
    *,
    run_id: str | None = None,
    source: str = "manual",
    sequence: int = 0,
    current: int = 0,
    total: int | None = None,
    thread_id: str | None = None,
    started_at: str | None = None,
    error: str | None = None,
) -> None:
    scan_runner.write_progress_file(
        progress_file,
        phase,
        detail,
        run_id=run_id,
        source=source,
        sequence=sequence,
        current=current,
        total=total,
        thread_id=thread_id,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc).isoformat() if phase in {"complete", "failed"} else None,
        error=error,
    )
    print(f"IT_PROGRESS:{phase}", file=sys.stderr)


class ProgressEmitter:
    def __init__(self, path: Path, run_id: str, source: str) -> None:
        self.path = path
        self.run_id = run_id
        self.source = source
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.sequence = 0

    def emit(
        self,
        phase: str,
        detail: str = "",
        *,
        current: int = 0,
        total: int | None = None,
        thread_id: str | None = None,
        error: str | None = None,
    ) -> None:
        self.sequence += 1
        emit_progress(
            self.path,
            phase,
            detail,
            run_id=self.run_id,
            source=self.source,
            sequence=self.sequence,
            current=current,
            total=total,
            thread_id=thread_id,
            started_at=self.started_at,
            error=error,
        )


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


def build_discovery_prompt(
    search_query: str,
    window_mode: str,
    email_watermark: str,
    email_filter: str,
    gmail_involvement: str,
) -> str:
    prompt = f"""Discover Gmail threads related to active job interviews, recruiter replies,
interview scheduling, technical rounds, onsite logistics, or offers. Ignore newsletters,
job-board alerts, and marketing. Run several mcp__claude_ai_Gmail__search_threads searches
with varied relevant terms. EVERY search query MUST include this boundary unchanged: {search_query}.
Return each matching Gmail thread ID once in thread_ids. Do not read thread contents."""
    if window_mode == "recent-watermark":
        prompt += (
            "\nRECENT-SCAN GUARDRAIL: the prior scan was recent. Only include threads with a message newer than "
            f"{email_watermark}; older messages are context only."
        )
    if gmail_involvement:
        prompt += (
            f"\nEVERY query MUST include this involvement filter for {email_filter}: "
            f"{gmail_involvement}."
        )
    prompt += "\nOutput only the structured JSON matching the schema."
    return prompt


def _result_object(outer: dict[str, object]) -> object:
    result = outer.get("structured_output", outer.get("result"))
    if isinstance(result, str):
        result = json.loads(result)
    return result


def parse_claude_output(raw_stdout: str) -> dict[str, object]:
    outer = json.loads(raw_stdout)
    result = _result_object(outer)
    if not isinstance(result, dict):
        raise TypeError("claude result must be an object")
    interviews = result.get("interviews", [])
    if not isinstance(interviews, list):
        raise TypeError("interviews must be an array")
    watermark = result.get("latest_email_date_seen")
    if watermark is not None and not isinstance(watermark, str):
        raise TypeError("latest_email_date_seen must be a string or null")
    return {"interviews": interviews, "latest_email_date_seen": watermark}


def parse_discovery_output(raw_stdout: str) -> list[str]:
    outer = json.loads(raw_stdout)
    result = _result_object(outer)
    if not isinstance(result, dict):
        raise TypeError("claude discovery result must be an object")
    values = result.get("thread_ids")
    # Compatibility with old/fake extraction envelopes used by local tests.
    if values is None and isinstance(result.get("interviews"), list):
        values = [
            row.get("thread_id")
            for row in result["interviews"]
            if isinstance(row, dict) and row.get("thread_id")
        ]
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise TypeError("thread_ids must be an array of strings")
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def build_extraction_prompt(thread_ids: list[str]) -> str:
    encoded = json.dumps(thread_ids)
    return f"""Read exactly these Gmail thread IDs using
mcp__claude_ai_Gmail__get_thread: {encoded}

Read every listed thread fully. Extract one current record per distinct company/application.
If multiple listed threads are for the same application, retain the thread_id with latest
activity. Use exactly the schema fields and stage enum supplied by the caller. Set
latest_email_date_seen to the newest individual message timestamp actually read, or null
when the list is empty. Do not search Gmail and do not read any unlisted thread.
Output only the structured result."""


def _walk_objects(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_objects(child)


def process_stream_event(
    event: dict[str, object],
    pending_tools: dict[str, str],
    completed_threads: set[str],
) -> tuple[str | None, object | None]:
    final_result: object | None = None
    current_thread: str | None = None
    if event.get("type") == "result":
        final_result = event.get("structured_output", event.get("result"))
    for item in _walk_objects(event):
        if item.get("type") == "tool_use" and str(item.get("name", "")).endswith("get_thread"):
            inputs = item.get("input")
            thread_id = inputs.get("thread_id") if isinstance(inputs, dict) else None
            tool_id = item.get("id")
            if isinstance(thread_id, str):
                current_thread = thread_id
                if isinstance(tool_id, str):
                    pending_tools[tool_id] = thread_id
        if item.get("type") == "tool_result":
            tool_id = item.get("tool_use_id")
            if isinstance(tool_id, str) and tool_id in pending_tools:
                completed_threads.add(pending_tools.pop(tool_id))
    return current_thread, final_result


def run_streaming_extraction(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_file: Path,
    emitter: ProgressEmitter,
    total: int,
) -> tuple[int, str, str]:
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    messages: queue.Queue[tuple[str, str | None]] = queue.Queue()

    def reader(name: str, stream) -> None:
        try:
            for line in iter(stream.readline, ""):
                messages.put((name, line))
        finally:
            messages.put((name, None))

    assert process.stdout is not None and process.stderr is not None
    threading.Thread(target=reader, args=("stdout", process.stdout), daemon=True).start()
    threading.Thread(target=reader, args=("stderr", process.stderr), daemon=True).start()
    pending_tools: dict[str, str] = {}
    completed_threads: set[str] = set()
    final_result: object | None = None
    stderr: list[str] = []
    closed: set[str] = set()
    started = time.monotonic()
    while len(closed) < 2:
        if time.monotonic() - started > SCAN_TIMEOUT_SECONDS:
            process.kill()
            raise subprocess.TimeoutExpired(cmd, SCAN_TIMEOUT_SECONDS)
        try:
            name, line = messages.get(timeout=0.25)
        except queue.Empty:
            continue
        if line is None:
            closed.add(name)
            continue
        if name == "stderr":
            stderr.append(line)
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        thread_id, result = process_stream_event(event, pending_tools, completed_threads)
        if result is not None:
            final_result = result
        elif "result" in event or "structured_output" in event:
            # Compatibility with test fakes and older CLI builds that emit one
            # JSON envelope even when stream-json was requested.
            final_result = _result_object(event)
        emitter.emit(
            "extracting",
            current=len(completed_threads),
            total=total,
            thread_id=thread_id,
        )
    return_code = process.wait(timeout=5)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.writelines(stderr)
    if isinstance(final_result, str):
        result_text = final_result
    elif final_result is not None:
        result_text = json.dumps(final_result)
    else:
        result_text = ""
    return return_code, result_text, "".join(stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        choices=("dashboard", "tray", "scheduled", "manual"),
        default=os.environ.get("INTERVIEW_TRACKER_SCAN_SOURCE", "manual"),
    )
    parser.add_argument("--run-id", default="")
    args = parser.parse_args(argv if argv is not None else [])
    data_dir = _data_dir()
    db_file = data_dir / database.DEFAULT_DB_NAME
    log_file = data_dir / "logs" / "scan.log"
    progress_file = data_dir / ".scan_progress.json"
    lock_dir = data_dir / "scan.lock"
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    emitter = ProgressEmitter(progress_file, run_id, args.source)

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
        emitter.emit("busy", "scan lock held")
        return 2

    raw_file: Path | None = None
    try:
        raw_file = Path(tempfile.mkstemp(prefix="raw_extraction.", dir=data_dir)[1])
        emitter.emit("starting")
        _log_line(log_file, f"=== scan started (claude: {claude_bin or 'missing'}) ===")

        if not claude_bin:
            _log_line(log_file, "ERROR: claude CLI not found. Set CLAUDE_BIN in config.env.")
            emitter.emit("failed", "claude CLI not found", error="claude CLI not found")
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
        emitter.emit("config")

        discovery_prompt = build_discovery_prompt(
            search_query,
            window_mode,
            email_watermark,
            email_filter,
            gmail_involvement,
        )
        emitter.emit("discovery")
        common_args = [
            "--system-prompt",
            (
                "You are a headless data-extraction worker with no memory, no persona, "
                "and no context beyond this task. Use only the tools explicitly provided. "
                "Follow the instructions exactly and produce only the requested output."
            ),
            "--disallowedTools",
            (
                "Bash Read Write Edit NotebookEdit WebFetch WebSearch Agent Task "
                "TaskCreate TaskUpdate TaskGet TaskList TaskOutput TaskStop Artifact "
                "ExitPlanMode"
            ),
            "--no-session-persistence",
        ]
        discovery_cmd = [
            claude_bin,
            "-p",
            discovery_prompt,
            *common_args,
            "--allowedTools",
            "mcp__claude_ai_Gmail__search_threads",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(DISCOVERY_SCHEMA),
        ]

        env = os.environ.copy()
        env.setdefault("HOME", str(Path.home()))
        env["INTERVIEW_TRACKER_DATA_DIR"] = str(data_dir)
        path_prefix = platform_utils.default_path_env()
        env["PATH"] = path_prefix + os.pathsep + env.get("PATH", "")

        with log_file.open("a", encoding="utf-8") as log_handle:
            try:
                discovery = subprocess.run(
                    discovery_cmd,
                    cwd=str(ROOT),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=SCAN_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                _log_line(log_file, "ERROR: Claude discovery timed out")
                emitter.emit("failed", "timeout", error="discovery timed out")
                return 1
            if discovery.stderr:
                log_handle.write(discovery.stderr)
            if discovery.returncode != 0:
                _log_line(log_file, "ERROR: Claude discovery failed")
                emitter.emit("failed", "discovery failed", error="Claude discovery failed")
                return 1

        try:
            thread_ids = parse_discovery_output(discovery.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            _log_line(log_file, f"ERROR: Claude discovery JSON parsing failed: {exc}")
            emitter.emit("failed", "discovery output invalid", error=str(exc))
            return 1
        total = len(thread_ids)
        _log_line(log_file, f"discovered {total} unique candidate threads")
        emitter.emit("extracting", current=0, total=total)

        if total:
            extraction_cmd = [
                claude_bin,
                "-p",
                build_extraction_prompt(thread_ids),
                *common_args,
                "--allowedTools",
                "mcp__claude_ai_Gmail__get_thread",
                "--output-format",
                "stream-json",
                "--verbose",
                "--json-schema",
                json.dumps(JSON_SCHEMA),
            ]
            try:
                return_code, final_output, stream_error = run_streaming_extraction(
                    extraction_cmd,
                    cwd=ROOT,
                    env=env,
                    log_file=log_file,
                    emitter=emitter,
                    total=total,
                )
            except subprocess.TimeoutExpired:
                _log_line(log_file, "ERROR: Claude extraction timed out")
                emitter.emit("failed", "timeout", total=total, error="extraction timed out")
                return 1
            if return_code != 0:
                detail = stream_error.strip() or "Claude extraction failed"
                _log_line(log_file, f"ERROR: {detail}")
                emitter.emit("failed", "extraction failed", total=total, error=detail)
                return 1
            try:
                parsed = parse_claude_output(json.dumps({"result": final_output}))
            except (json.JSONDecodeError, TypeError) as exc:
                _log_line(log_file, f"ERROR: Claude extraction JSON parsing failed: {exc}")
                emitter.emit("failed", "extraction output invalid", total=total, error=str(exc))
                return 1
            unexpected = {
                row.get("thread_id")
                for row in parsed["interviews"]  # type: ignore[union-attr]
                if isinstance(row, dict) and row.get("thread_id") not in thread_ids
            }
            if unexpected:
                detail = f"extraction returned undiscovered thread IDs: {sorted(unexpected)}"
                _log_line(log_file, f"ERROR: {detail}")
                emitter.emit("failed", "thread validation failed", total=total, error=detail)
                return 1
        else:
            parsed = {"interviews": [], "latest_email_date_seen": None}

        raw_file.write_text(json.dumps(parsed), encoding="utf-8")
        count = len(parsed["interviews"])  # type: ignore[arg-type]
        _log_line(log_file, f"extracted {count} candidate records")
        emitter.emit("merging", str(count), current=total, total=total)

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
            emitter.emit("failed", "merge failed", current=total, total=total, error=detail)
            return 1

        emitter.emit("complete", str(count), current=total, total=total)
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
    raise SystemExit(main(sys.argv[1:]))
