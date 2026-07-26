"""Integration tests for shell scripts and install-time plist rendering."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

from support import (
    BIN_DIR,
    FIXTURES_DIR,
    IsolatedRuntimeTestCase,
    PROJECT_ROOT,
    database,
    write_fake_claude,
)

INSTALL_PLIST_PY = """
import sys
from pathlib import Path
from xml.sax.saxutils import escape

source, destination, root, home, data_dir = sys.argv[1:]
text = Path(source).read_text(encoding="utf-8")
values = {
    "__ROOT__": root,
    "__HOME__": home,
    "__DATA_DIR__": data_dir,
}
for placeholder, value in values.items():
    text = text.replace(
        placeholder,
        escape(value, {'"': "&quot;", "'": "&apos;"}),
    )
unresolved = [placeholder for placeholder in values if placeholder in text]
if unresolved:
    raise SystemExit(f"unresolved plist placeholders: {', '.join(unresolved)}")
Path(destination).write_text(text, encoding="utf-8")
"""


@unittest.skipUnless(sys.platform == "darwin", "macOS shell integration")
class ShellIntegrationTests(IsolatedRuntimeTestCase):
    """Integration tests: scan_gmail.sh, macos_notifier.sh, install plist substitution."""

    scan_script = BIN_DIR / "scan_gmail.sh"
    notifier_script = BIN_DIR / "macos_notifier.sh"

    def setUp(self):
        super().setUp()
        database.initialize_database(self.db_path)

    def test_scan_gmail_merges_dashboard_and_releases_lock(self):
        interviews = json.loads(
            (FIXTURES_DIR / "sample_interviews.json").read_text(encoding="utf-8")
        )
        fake_claude = write_fake_claude(self.root / "fake_claude", interviews)

        result = self.run_shell(
            self.scan_script,
            extra_env={"CLAUDE_BIN": str(fake_claude)},
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)

        records = database.get_records(self.db_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["thread_id"], "fake-thread-1")
        self.assertEqual(records[0]["company"], "Fixture Co")

        dashboard = self.data_dir / "dashboard.html"
        self.assertTrue(dashboard.is_file())
        self.assertIn("Fixture Co", dashboard.read_text(encoding="utf-8"))

        progress = self.data_dir / ".scan_progress.json"
        self.assertTrue(progress.is_file())
        phase = json.loads(progress.read_text(encoding="utf-8")).get("phase")
        self.assertEqual(phase, "complete")

        lock_dir = self.data_dir / "scan.lock"
        self.assertFalse(lock_dir.exists())

    def test_scan_lock_second_run_exits_zero_quickly(self):
        lock_dir = self.data_dir / "scan.lock"
        lock_dir.mkdir()
        self.addCleanup(lambda: lock_dir.rmdir() if lock_dir.is_dir() else None)

        start = time.monotonic()
        result = self.run_shell(self.scan_script)
        elapsed = time.monotonic() - start

        self.assertEqual(result.returncode, 2)
        self.assertLess(elapsed, 5.0)
        self.assertTrue(lock_dir.is_dir())

    def _notifier_fake_bin(self) -> Path:
        fake_bin = self.root / "fakebin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        for dest_name, fixture_name in (
            ("terminal-notifier", "fake_terminal_notifier"),
            ("curl", "fake_curl"),
        ):
            dest = fake_bin / dest_name
            shutil.copy(FIXTURES_DIR / fixture_name, dest)
            dest.chmod(0o755)
        return fake_bin

    def test_macos_notifier_fires_once_then_stays_silent(self):
        interviews = json.loads(
            (FIXTURES_DIR / "sample_interviews.json").read_text(encoding="utf-8")
        )
        database.merge_scan(interviews, self.db_path, timestamp="2026-01-20T12:00:00+00:00")

        notify_log = self.data_dir / "notify.log"
        curl_log = self.data_dir / "curl.log"
        fake_bin = self._notifier_fake_bin()
        env = self.env.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
        env["NOTIFY_LOG"] = str(notify_log)
        env["CURL_LOG"] = str(curl_log)
        env["NTFY_TOPIC"] = "integration-test-topic"

        first = subprocess.run(
            ["/bin/bash", str(self.notifier_script), "check"],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(first.returncode, 0, msg=first.stderr + first.stdout)
        self.assertTrue(notify_log.is_file())
        self.assertGreater(notify_log.stat().st_size, 0)
        self.assertTrue(curl_log.is_file())
        hash_file = self.data_dir / ".last_notified_hash"
        self.assertTrue(hash_file.is_file())
        first_hash = hash_file.read_text(encoding="utf-8").strip()
        self.assertTrue(first_hash)

        notify_size_after_first = notify_log.stat().st_size
        curl_size_after_first = curl_log.stat().st_size

        second = subprocess.run(
            ["/bin/bash", str(self.notifier_script), "check"],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(second.returncode, 0)
        self.assertEqual(notify_log.stat().st_size, notify_size_after_first)
        self.assertEqual(curl_log.stat().st_size, curl_size_after_first)
        self.assertEqual(hash_file.read_text(encoding="utf-8").strip(), first_hash)

    def test_install_plist_substitution_escapes_special_characters(self):
        template = self.root / "template.plist"
        template.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Root</key><string>__ROOT__</string>
    <key>Home</key><string>__HOME__</string>
    <key>Data</key><string>__DATA_DIR__</string>
</dict>
</plist>
""",
            encoding="utf-8",
        )
        root = str(self.root / "proj'ect\"&")
        home = str(self.home_dir / "user's \"home\"")
        data_dir = str(self.data_dir / "App & Co")
        installed = self.root / "installed.plist"

        subprocess.run(
            [
                "/usr/bin/python3",
                "-c",
                INSTALL_PLIST_PY,
                str(template),
                str(installed),
                root,
                home,
                data_dir,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        lint = subprocess.run(
            ["/usr/bin/plutil", "-lint", str(installed)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(lint.returncode, 0, msg=lint.stderr + lint.stdout)

        rendered = installed.read_text(encoding="utf-8")
        self.assertNotIn("__ROOT__", rendered)
        self.assertNotIn("__HOME__", rendered)
        self.assertNotIn("__DATA_DIR__", rendered)
        self.assertIn("&amp;", rendered)
        self.assertIn("&apos;", rendered)
        self.assertIn("&quot;", rendered)

        with installed.open("rb") as handle:
            plist = plistlib.load(handle)
        self.assertEqual(plist["Root"], root)
        self.assertEqual(plist["Home"], home)
        self.assertEqual(plist["Data"], data_dir)


if __name__ == "__main__":
    unittest.main()
