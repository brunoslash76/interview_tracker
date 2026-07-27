#!/usr/bin/env python3
"""Loopback FastAPI server for the live dashboard and scan settings UI."""

from __future__ import annotations

import html
import json
import asyncio
import contextlib
import secrets
import socket
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import Cookie, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import database
import platform_utils
import scheduler
import scan_runner

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = platform_utils.default_data_dir()
DB_FILE = DATA_DIR / database.DEFAULT_DB_NAME
DASHBOARD_TEMPLATE = ROOT / "dashboard_template.html"
SETTINGS_TEMPLATE = ROOT / "settings_template.html"
FRONTEND_DIST = ROOT / "frontend" / "dist"
CSRF_COOKIE = "it_csrf"
MAX_BODY_BYTES = 16_384


def port_file() -> Path:
    return DATA_DIR / ".http_port"


class LocalServerState:
    def __init__(self) -> None:
        self.host = "127.0.0.1"
        self.port = 0
        self.server: Optional[uvicorn.Server] = None
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()


STATE = LocalServerState()
_SCAN_RUNNER: Optional[scan_runner.ScanRunner] = None
CSRF_TOKEN = secrets.token_urlsafe(32)


def get_scan_runner() -> scan_runner.ScanRunner:
    global _SCAN_RUNNER
    if _SCAN_RUNNER is None or _SCAN_RUNNER.data_dir != DATA_DIR or _SCAN_RUNNER.db_path != DB_FILE:
        _SCAN_RUNNER = scan_runner.ScanRunner(ROOT, DATA_DIR, DB_FILE)
    return _SCAN_RUNNER


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


def render_dashboard_html(csrf_token: str = "") -> str:
    merge = _merge_module()
    records = database.get_records(DB_FILE)
    return merge.render_dashboard(records).replace(
        "__CSRF_TOKEN__", html.escape(csrf_token, quote=True)
    )


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


def _allowed_host(host: str) -> bool:
    return host in {f"{STATE.host}:{STATE.port}", f"localhost:{STATE.port}"}


def _allowed_origin(origin: str) -> bool:
    if not origin:
        return False
    return origin.rstrip("/") in {
        f"http://{STATE.host}:{STATE.port}",
        f"http://localhost:{STATE.port}",
    }


def _csrf_valid(cookie: str, header: str) -> bool:
    return bool(cookie and header) and secrets.compare_digest(cookie, header) and secrets.compare_digest(
        cookie, CSRF_TOKEN
    )


def app_snapshot() -> dict[str, Any]:
    return {
        "dashboard": scan_runner.dashboard_payload(DB_FILE),
        "settings": database.get_user_settings(DB_FILE),
        "scan": get_scan_runner().snapshot(),
    }


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, event_type: str, payload: Any) -> None:
        message = {"version": 1, "type": event_type, "payload": payload}
        stale: list[WebSocket] = []
        for websocket in list(self.connections):
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(websocket)


MANAGER = ConnectionManager()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.watcher = asyncio.create_task(_event_watcher())
    try:
        yield
    finally:
        app.state.watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.watcher


APP = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@APP.middleware("http")
async def security_middleware(request: Request, call_next):
    if not _allowed_host(request.headers.get("host", "")):
        return JSONResponse({"error": "invalid host"}, status_code=403)
    response = await call_next(request)
    if request.url.path in {"/", "/dashboard", "/settings"}:
        response.set_cookie(CSRF_COOKIE, CSRF_TOKEN, httponly=True, samesite="strict", path="/")
    return response


def _require_mutation(request: Request, cookie: str, header: str) -> None:
    if not _allowed_origin(request.headers.get("origin") or request.headers.get("referer", "")):
        raise HTTPException(403, "invalid origin")
    if not _csrf_valid(cookie, header):
        raise HTTPException(403, "invalid csrf token")


async def _json_payload(request: Request) -> dict[str, Any]:
    length = int(request.headers.get("content-length", "0"))
    if length > MAX_BODY_BYTES:
        raise HTTPException(400, "request body too large")
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "JSON body must be an object")
    return payload


def _react_index() -> FileResponse | HTMLResponse:
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse("<h1>Frontend is not built</h1><p>Run npm run build in frontend/.</p>", 503)


@APP.get("/")
async def root():
    return RedirectResponse("/dashboard", status_code=307)


@APP.get("/dashboard")
@APP.get("/settings")
async def react_page():
    return _react_index()


@APP.get("/api/settings")
async def get_settings():
    return database.get_user_settings(DB_FILE)


@APP.get("/api/scan/status")
async def get_scan_status():
    return get_scan_runner().snapshot()


@APP.get("/api/dashboard-data")
async def get_dashboard_data():
    return scan_runner.dashboard_payload(DB_FILE)


async def _save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    scan_times = payload.get("scan_times", [])
    if not isinstance(scan_times, list):
        raise ValueError("scan_times must be an array")
    saved = await asyncio.to_thread(
        scheduler.apply_settings_with_rollback,
        payload.get("email", ""),
        scan_times,
        ROOT,
        Path.home(),
        DATA_DIR,
        DB_FILE,
    )
    await MANAGER.broadcast("settings.updated", saved)
    return saved


@APP.api_route("/api/settings", methods=["PUT", "POST"])
async def update_settings(
    request: Request,
    it_csrf: str = Cookie(default="", alias=CSRF_COOKIE),
    x_csrf_token: str = Header(default=""),
):
    _require_mutation(request, it_csrf, x_csrf_token)
    payload = await _json_payload(request)
    try:
        return await _save_settings(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@APP.post("/api/scan", status_code=202)
async def start_scan(
    request: Request,
    it_csrf: str = Cookie(default="", alias=CSRF_COOKIE),
    x_csrf_token: str = Header(default=""),
):
    _require_mutation(request, it_csrf, x_csrf_token)
    started, payload = get_scan_runner().start(source="dashboard")
    if not started:
        raise HTTPException(409, payload.get("error", "scan busy"))
    await MANAGER.broadcast("scan.started", payload)
    return {"status": payload}


@APP.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not _allowed_host(websocket.headers.get("host", "")) or not _allowed_origin(
        websocket.headers.get("origin", "")
    ):
        await websocket.close(code=1008)
        return
    if not secrets.compare_digest(websocket.cookies.get(CSRF_COOKIE, ""), CSRF_TOKEN):
        await websocket.close(code=1008)
        return
    await MANAGER.connect(websocket)
    try:
        await websocket.send_json({"version": 1, "type": "app.snapshot", "payload": app_snapshot()})
        while True:
            message = await websocket.receive_json()
            request_id = message.get("request_id")
            event_type = message.get("type")
            try:
                if message.get("version") != 1:
                    raise ValueError("unsupported protocol version")
                if event_type == "snapshot.request":
                    response_type, payload = "app.snapshot", app_snapshot()
                elif event_type == "scan.start":
                    started, payload = get_scan_runner().start(source="dashboard")
                    if not started:
                        raise ValueError(payload.get("error", "scan busy"))
                    response_type = "scan.started"
                    await MANAGER.broadcast(response_type, payload)
                elif event_type == "settings.save":
                    payload = await _save_settings(message.get("payload") or {})
                    response_type = "settings.updated"
                else:
                    raise ValueError("unknown command")
                await websocket.send_json(
                    {"version": 1, "type": response_type, "request_id": request_id, "payload": payload}
                )
            except Exception as exc:
                await websocket.send_json(
                    {"version": 1, "type": "error", "request_id": request_id, "payload": {"error": str(exc)}}
                )
    except WebSocketDisconnect:
        pass
    finally:
        await MANAGER.disconnect(websocket)


if FRONTEND_DIST.is_dir():
    APP.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


async def _event_watcher() -> None:
    last_scan: Optional[str] = None
    last_db_mtime = -1
    last_heartbeat = 0.0
    while True:
        status = get_scan_runner().snapshot()
        fingerprint = json.dumps(status, sort_keys=True, default=str)
        if fingerprint != last_scan:
            event = "scan.progress"
            if status["state"] == "succeeded":
                event = "scan.completed"
            elif status["state"] == "failed":
                event = "scan.failed"
            elif status["state"] == "running" and last_scan is None:
                event = "scan.started"
            await MANAGER.broadcast(event, status)
            last_scan = fingerprint
        try:
            db_mtime = DB_FILE.stat().st_mtime_ns
        except OSError:
            db_mtime = -1
        if last_db_mtime >= 0 and db_mtime != last_db_mtime:
            await MANAGER.broadcast("dashboard.updated", scan_runner.dashboard_payload(DB_FILE))
        last_db_mtime = db_mtime
        now = asyncio.get_running_loop().time()
        if now - last_heartbeat >= 15:
            await MANAGER.broadcast("heartbeat", {"timestamp": datetime.now(timezone.utc).isoformat()})
            last_heartbeat = now
        await asyncio.sleep(0.5)


def start_local_server() -> int:
    global CSRF_TOKEN
    with STATE.lock:
        if STATE.server is not None:
            return STATE.port
        CSRF_TOKEN = secrets.token_urlsafe(32)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((STATE.host, 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        STATE.port = port
        config = uvicorn.Config(APP, host=STATE.host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        STATE.server = server
        STATE.thread = thread
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        port_file().write_text(str(port), encoding="utf-8")
        database.set_metadata(database.HTTP_LISTEN_PORT_KEY, str(port), DB_FILE)
        return port


def stop_local_server() -> None:
    with STATE.lock:
        if STATE.server is not None:
            STATE.server.should_exit = True
            if STATE.thread:
                STATE.thread.join(timeout=5)
            STATE.server = None
            STATE.thread = None
            STATE.port = 0


if __name__ == "__main__":
    print(start_local_server())
