"""WebSocket protocol tests for the local FastAPI backend."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.support import TemporaryDatabaseTestCase, load_bin_module


class ConnectionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_removes_stale_connections(self):
        local_server = load_bin_module("local_server")
        manager = local_server.ConnectionManager()
        healthy = mock.AsyncMock()
        stale = mock.AsyncMock()
        stale.send_json.side_effect = RuntimeError("closed")
        await manager.connect(healthy)
        await manager.connect(stale)
        await manager.broadcast("scan.progress", {"current": 1})
        healthy.send_json.assert_awaited_once()
        self.assertIn(healthy, manager.connections)
        self.assertNotIn(stale, manager.connections)
        await manager.disconnect(healthy)
        self.assertFalse(manager.connections)


class LocalServerWebSocketTests(TemporaryDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.local_server = load_bin_module("local_server")
        self.local_server.DATA_DIR = self.data_dir
        self.local_server.DB_FILE = self.db_path
        self.local_server.STATE.port = 8123
        self.local_server.database.initialize_database(self.db_path)
        self.client = TestClient(
            self.local_server.APP, base_url="http://127.0.0.1:8123"
        )
        self.headers = {
            "host": "127.0.0.1:8123",
            "origin": "http://127.0.0.1:8123",
        }

    def test_websocket_requires_session_cookie(self):
        with self.assertRaises(WebSocketDisconnect) as raised:
            with self.client.websocket_connect("/ws", headers=self.headers):
                pass
        self.assertEqual(raised.exception.code, 1008)

    def test_snapshot_and_settings_command(self):
        self.client.cookies.set(
            self.local_server.CSRF_COOKIE, self.local_server.CSRF_TOKEN
        )
        saved = {
            "email": "me@example.com",
            "scan_times": ["10:00"],
            "max_scan_times": 5,
        }
        with mock.patch.object(
            self.local_server.scheduler,
            "apply_settings_with_rollback",
            return_value=saved,
        ):
            with self.client.websocket_connect("/ws", headers=self.headers) as websocket:
                initial = websocket.receive_json()
                self.assertEqual(initial["type"], "app.snapshot")
                websocket.send_json({
                    "version": 1,
                    "type": "settings.save",
                    "request_id": "request-1",
                    "payload": {"email": "me@example.com", "scan_times": ["10:00"]},
                })
                messages = [websocket.receive_json(), websocket.receive_json()]
                response = next(
                    message for message in messages
                    if message.get("request_id") == "request-1"
                )
                self.assertEqual(response["type"], "settings.updated")
                self.assertEqual(response["payload"]["email"], "me@example.com")


if __name__ == "__main__":
    unittest.main()
