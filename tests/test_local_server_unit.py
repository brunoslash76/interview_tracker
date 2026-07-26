"""Unit tests for bin/local_server.py HTTP behavior."""

from __future__ import annotations

import http.client
import json
import unittest
from pathlib import Path
from unittest import mock

from tests.support import load_bin_module


class LocalServerHttpTests(unittest.TestCase):
    def setUp(self):
        self.local_server_module = load_bin_module("local_server")

    def test_dashboard_render_embeds_escaped_csrf_token(self):
        merge = mock.Mock()
        merge.render_dashboard.return_value = (
            '<input id="csrfToken" value="__CSRF_TOKEN__">'
        )
        with mock.patch.object(
            self.local_server_module, "_merge_module", return_value=merge
        ), mock.patch.object(
            self.local_server_module.database, "get_records", return_value=[]
        ):
            rendered = self.local_server_module.render_dashboard_html('token&"value')

        self.assertNotIn("__CSRF_TOKEN__", rendered)
        self.assertIn("token&amp;&quot;value", rendered)
        merge.render_dashboard.assert_called_once_with([])

    def _start(self, temp_dir: Path) -> tuple[int, http.client.HTTPConnection]:
        data_dir = temp_dir
        db_path = data_dir / "interview_tracker.sqlite3"
        patches = (
            mock.patch.object(self.local_server_module, "DATA_DIR", data_dir),
            mock.patch.object(
                self.local_server_module.database,
                "get_database_path",
                return_value=db_path,
            ),
            mock.patch.object(self.local_server_module, "DB_FILE", db_path),
            mock.patch.object(
                self.local_server_module.scheduler,
                "apply_settings_with_rollback",
                return_value={
                    "status": "ok",
                    "email": "",
                    "scan_times": ["10:00"],
                    "max_scan_times": 5,
                },
            ),
            mock.patch.object(
                self.local_server_module,
                "render_dashboard_html",
                return_value="<html>dashboard</html>",
            ),
            mock.patch.object(
                self.local_server_module,
                "render_settings_html",
                return_value="<html>settings</html>",
            ),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.local_server_module.database.initialize_database(db_path)
        port = self.local_server_module.start_local_server()
        self.addCleanup(self.local_server_module.stop_local_server)
        return port, http.client.HTTPConnection("127.0.0.1", port, timeout=5)

    def _csrf_from_settings_page(self, conn: http.client.HTTPConnection, port: int) -> str:
        conn.request("GET", "/settings", headers={"Host": f"127.0.0.1:{port}"})
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        response.read()
        for header, value in response.getheaders():
            if header.lower() == "set-cookie":
                return value.split("=", 1)[1].split(";", 1)[0]
        self.fail("expected CSRF cookie from /settings")

    def test_get_api_settings_without_csrf_is_ok(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            port, conn = self._start(Path(temp_dir))
            conn.request("GET", "/api/settings", headers={"Host": f"127.0.0.1:{port}"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
            self.assertIn("scan_times", payload)
            conn.close()

    def test_csrf_matrix_blocks_invalid_mutations(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            port, conn = self._start(Path(temp_dir))
            body = json.dumps({"email": "", "scan_times": ["10:00"]})
            headers_base = {
                "Content-Type": "application/json",
                "Host": f"127.0.0.1:{port}",
                "Origin": f"http://127.0.0.1:{port}",
            }
            csrf = self._csrf_from_settings_page(conn, port)

            conn.request("PUT", "/api/settings", body=body, headers=headers_base)
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()

            conn.request(
                "PUT",
                "/api/settings",
                body=body,
                headers={**headers_base, "Cookie": f"it_csrf={csrf}"},
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()

            conn.request(
                "PUT",
                "/api/settings",
                body=body,
                headers={
                    **headers_base,
                    "Cookie": f"it_csrf={csrf}",
                    "X-CSRF-Token": "wrong-token",
                },
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()

            conn.request(
                "PUT",
                "/api/settings",
                body=body,
                headers={
                    **headers_base,
                    "Cookie": f"it_csrf={csrf}",
                    "X-CSRF-Token": csrf,
                },
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            conn.close()

    def test_post_api_settings_with_valid_csrf(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            port, conn = self._start(Path(temp_dir))
            csrf = self._csrf_from_settings_page(conn, port)
            body = json.dumps({"email": "a@b.co", "scan_times": ["09:30"]})
            conn.request(
                "POST",
                "/api/settings",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Host": f"127.0.0.1:{port}",
                    "Origin": f"http://127.0.0.1:{port}",
                    "Cookie": f"it_csrf={csrf}",
                    "X-CSRF-Token": csrf,
                },
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            conn.close()

    def test_bad_host_returns_403(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            port, conn = self._start(Path(temp_dir))
            conn.request("GET", "/api/settings", headers={"Host": "evil.example:9999"})
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            conn.close()

    def test_bad_origin_returns_403_on_put(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            port, conn = self._start(Path(temp_dir))
            csrf = self._csrf_from_settings_page(conn, port)
            body = json.dumps({"email": "", "scan_times": ["10:00"]})
            conn.request(
                "PUT",
                "/api/settings",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Host": f"127.0.0.1:{port}",
                    "Origin": "http://evil.example",
                    "Cookie": f"it_csrf={csrf}",
                    "X-CSRF-Token": csrf,
                },
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            conn.close()

    def test_get_api_scan_status(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            port, conn = self._start(Path(temp_dir))
            conn.request("GET", "/api/scan/status", headers={"Host": f"127.0.0.1:{port}"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["state"], "idle")
            conn.close()

    def test_post_api_scan_requires_csrf(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            port, conn = self._start(Path(temp_dir))
            conn.request(
                "POST",
                "/api/scan",
                body="{}",
                headers={
                    "Content-Type": "application/json",
                    "Host": f"127.0.0.1:{port}",
                    "Origin": f"http://127.0.0.1:{port}",
                },
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            conn.close()

    def test_post_api_scan_starts_with_csrf(self):
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as temp_dir:
            port, conn = self._start(Path(temp_dir))
            csrf = self._csrf_from_settings_page(conn, port)
            fake_runner = mock.Mock()
            fake_runner.start.return_value = (True, {"state": "running", "phase": "starting"})
            with mock.patch.object(self.local_server_module, "get_scan_runner", return_value=fake_runner):
                conn.request(
                    "POST",
                    "/api/scan",
                    body="{}",
                    headers={
                        "Content-Type": "application/json",
                        "Host": f"127.0.0.1:{port}",
                        "Origin": f"http://127.0.0.1:{port}",
                        "Cookie": f"it_csrf={csrf}",
                        "X-CSRF-Token": csrf,
                    },
                )
                response = conn.getresponse()
                self.assertEqual(response.status, 202)
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(payload["status"]["state"], "running")
            conn.close()

    def test_get_api_dashboard_data(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            port, conn = self._start(Path(temp_dir))
            conn.request("GET", "/api/dashboard-data", headers={"Host": f"127.0.0.1:{port}"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
            self.assertIn("records", payload)
            self.assertIn("generated_at", payload)
            conn.close()

        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            port, conn = self._start(Path(temp_dir))
            csrf = self._csrf_from_settings_page(conn, port)
            huge = "x" * (self.local_server_module.MAX_BODY_BYTES + 1)
            body = json.dumps({"email": "", "scan_times": ["10:00"], "pad": huge})
            conn.request(
                "PUT",
                "/api/settings",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Host": f"127.0.0.1:{port}",
                    "Origin": f"http://127.0.0.1:{port}",
                    "Cookie": f"it_csrf={csrf}",
                    "X-CSRF-Token": csrf,
                },
            )
            response = conn.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
            conn.close()


if __name__ == "__main__":
    unittest.main()
