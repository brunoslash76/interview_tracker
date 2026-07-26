#!/usr/bin/env python3
"""Loopback HTTP server for the dashboard and scan settings UI."""

from __future__ import annotations

import html
import json
import os
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import database
import scheduler

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(
    os.environ.get(
        "INTERVIEW_TRACKER_DATA_DIR",
        Path.home() / "Library" / "Application Support" / "InterviewTracker",
    )
).expanduser()
DB_FILE = DATA_DIR / database.DEFAULT_DB_NAME
DASHBOARD_TEMPLATE = ROOT / "dashboard_template.html"
SETTINGS_TEMPLATE = ROOT / "settings_template.html"
CSRF_COOKIE = "it_csrf"
MAX_BODY_BYTES = 16_384


def port_file() -> Path:
    return DATA_DIR / ".http_port"


class LocalServerState:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 0
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()


STATE = LocalServerState()


def _merge_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "merge_interviews", ROOT / "bin" / "merge_interviews.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load merge_interviews")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_dashboard_html() -> str:
    merge = _merge_module()
    records = database.get_records(DB_FILE)
    return merge.render_dashboard(records)


def render_settings_html(csrf_token: str) -> str:
    template = SETTINGS_TEMPLATE.read_text(encoding="utf-8")
    return (
        template.replace("__CSRF_TOKEN__", html.escape(csrf_token, quote=True))
        .replace("__MAX_SCAN_TIMES__", str(database.MAX_SCAN_TIMES))
    )


def dashboard_url() -> Optional[str]:
    if STATE.port <= 0:
        path = port_file()
        if path.exists():
            try:
                port = int(path.read_text().strip())
                return f"http://127.0.0.1:{port}/dashboard"
            except ValueError:
                return None
        return None
    return f"http://{STATE.host}:{STATE.port}/dashboard"


def settings_url() -> Optional[str]:
    base = dashboard_url()
    if base is None:
        return None
    return base.replace("/dashboard", "/settings")


class InterviewTrackerHandler(BaseHTTPRequestHandler):
    server_version = "InterviewTrackerLocal/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    @property
    def csrf_token(self) -> str:
        return getattr(self.server, "csrf_token", "")

    def _expected_host(self) -> str:
        return f"{STATE.host}:{self.server.server_address[1]}"

    def _validate_host(self) -> bool:
        host = self.headers.get("Host", "")
        return host in {self._expected_host(), f"localhost:{self.server.server_address[1]}"}

    def _validate_origin(self) -> bool:
        origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
        if not origin:
            return self.command == "GET"
        prefix = f"http://{STATE.host}:{self.server.server_address[1]}"
        localhost_prefix = f"http://localhost:{self.server.server_address[1]}"
        return origin.startswith(prefix) or origin.startswith(localhost_prefix)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _csrf_valid(self) -> bool:
        cookie = ""
        for part in self.headers.get("Cookie", "").split(";"):
            part = part.strip()
            if part.startswith(f"{CSRF_COOKIE}="):
                cookie = part.split("=", 1)[1]
        header = self.headers.get("X-CSRF-Token", "")
        return bool(cookie) and secrets.compare_digest(cookie, header) and secrets.compare_digest(
            cookie, self.csrf_token
        )

    def _send_html(self, status: HTTPStatus, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header(
            "Set-Cookie",
            f"{CSRF_COOKIE}={self.csrf_token}; Path=/; HttpOnly; SameSite=Strict",
        )
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if not self._validate_host():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "invalid host"})
            return
        path = urlparse(self.path).path
        if path in {"/", ""}:
            self.send_response(HTTPStatus.TEMPORARY_REDIRECT)
            self.send_header("Location", "/dashboard")
            self.end_headers()
            return
        if path == "/dashboard":
            self._send_html(HTTPStatus.OK, render_dashboard_html())
            return
        if path == "/settings":
            self._send_html(HTTPStatus.OK, render_settings_html(self.csrf_token))
            return
        if path == "/api/settings":
            self._send_json(HTTPStatus.OK, database.get_user_settings(DB_FILE))
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_PUT(self) -> None:
        self._handle_settings_update()

    def do_POST(self) -> None:
        if urlparse(self.path).path == "/api/settings":
            self._handle_settings_update()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _handle_settings_update(self) -> None:
        if not self._validate_host() or not self._validate_origin():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "invalid origin"})
            return
        if not self._csrf_valid():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "invalid csrf token"})
            return
        try:
            payload = self._read_json_body()
            email = payload.get("email", "")
            scan_times = payload.get("scan_times", [])
            if not isinstance(scan_times, list):
                raise ValueError("scan_times must be an array")
            saved = scheduler.apply_settings_with_rollback(
                email,
                scan_times,
                ROOT,
                Path.home(),
                DATA_DIR,
                DB_FILE,
            )
            self._send_json(HTTPStatus.OK, saved)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


def start_local_server() -> int:
    with STATE.lock:
        if STATE.httpd is not None:
            return STATE.port
        token = secrets.token_urlsafe(32)
        httpd = ThreadingHTTPServer((STATE.host, 0), InterviewTrackerHandler)
        httpd.csrf_token = token  # type: ignore[attr-defined]
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        STATE.httpd = httpd
        STATE.thread = thread
        STATE.port = port
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        port_file().write_text(str(port), encoding="utf-8")
        database.set_metadata(database.HTTP_LISTEN_PORT_KEY, str(port), DB_FILE)
        return port


def stop_local_server() -> None:
    with STATE.lock:
        if STATE.httpd is not None:
            STATE.httpd.shutdown()
            STATE.httpd.server_close()
            STATE.httpd = None
            STATE.thread = None
            STATE.port = 0


if __name__ == "__main__":
    print(start_local_server())
