#!/usr/bin/env python3
"""Cross-platform fake Claude CLI for Playwright E2E (discovery + stream-json)."""

from __future__ import annotations

import json
import os
import sys
import time

INTERVIEWS = [
    {
        "thread_id": "e2e-t1",
        "company": "E2E Fixture Co",
        "position": "Engineer",
        "stage": "Phone Screen",
        "status": "Active",
        "last_email_date": "2026-07-15T12:00:00Z",
    }
]


def _output_format() -> str:
    if "--output-format" in sys.argv:
        index = sys.argv.index("--output-format")
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return "json"


def _discovery() -> None:
    payload = {"thread_ids": ["e2e-t1", "e2e-t2"]}
    print(json.dumps({"result": json.dumps(payload)}))


def _stream() -> None:
    if os.environ.get("FAKE_CLAUDE_MODE") == "fail":
        sys.stderr.write("simulated extraction failure\n")
        sys.exit(1)
    delay = float(os.environ.get("FAKE_CLAUDE_DELAY", "0.05"))
    threads = ["e2e-t1", "e2e-t2"]
    for index, thread_id in enumerate(threads, start=1):
        tool_id = f"use-{index}"
        print(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": tool_id,
                                "name": "mcp__claude_ai_Gmail__get_thread",
                                "input": {"thread_id": thread_id},
                            }
                        ]
                    },
                }
            ),
            flush=True,
        )
        time.sleep(delay)
        print(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "content": [{"type": "tool_result", "tool_use_id": tool_id}]
                    },
                }
            ),
            flush=True,
        )
        time.sleep(delay)
    print(
        json.dumps(
            {
                "type": "result",
                "structured_output": {
                    "interviews": INTERVIEWS,
                    "latest_email_date_seen": "2026-07-15T12:00:00Z",
                },
            }
        ),
        flush=True,
    )


def main() -> int:
    if os.environ.get("CLAUDE_ARGS_LOG"):
        with open(os.environ["CLAUDE_ARGS_LOG"], "a", encoding="utf-8") as handle:
            handle.write(" ".join(sys.argv) + "\n")
    fmt = _output_format()
    if fmt == "stream-json":
        _stream()
    else:
        _discovery()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
