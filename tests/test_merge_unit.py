"""Unit tests for bin/merge_interviews.py."""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests.support import TemporaryDatabaseTestCase, database, load_bin_module


class RenderDashboardTests(unittest.TestCase):
    def test_render_embeds_json_replaces_tokens_and_escapes_script_closers(self):
        merge_module = load_bin_module("merge_interviews")
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            template = Path(temp_dir) / "template.html"
            template.write_text(
                '<p>__GENERATED_AT__</p><script id="data">__DATA_JSON__</script>',
                encoding="utf-8",
            )
            records = [
                {
                    "company": "Closing </script><script>alert(1)</script>",
                    "notes": "embedded JSON",
                }
            ]

            with mock.patch.object(merge_module, "TEMPLATE_FILE", template):
                rendered = merge_module.render_dashboard(records)

        self.assertNotIn("__DATA_JSON__", rendered)
        self.assertNotIn("__GENERATED_AT__", rendered)
        self.assertIn('"notes": "embedded JSON"', rendered)
        self.assertIn("<\\/script>", rendered)
        self.assertNotIn("</script><script>alert(1)</script>", rendered)
        self.assertRegex(rendered, r"<p>.+</p>")


class AtomicWriteTests(TemporaryDatabaseTestCase):
    def test_atomic_write_replaces_target(self):
        merge_module = load_bin_module("merge_interviews")
        target = self.root / "dashboard.html"
        merge_module.atomic_write(target, "first")
        self.assertEqual(target.read_text(encoding="utf-8"), "first")
        merge_module.atomic_write(target, "second")
        self.assertEqual(target.read_text(encoding="utf-8"), "second")
        tmp_leftovers = list(self.root.glob("*.tmp"))
        self.assertEqual(tmp_leftovers, [])


class MergeMainTests(TemporaryDatabaseTestCase):
    def test_main_rerender_only_without_scan_argument(self):
        merge_module = load_bin_module("merge_interviews")
        database.initialize_database(self.db_path)
        database.merge_records(
            [{"thread_id": "t1", "company": "Render Co"}],
            self.db_path,
        )
        template = self.root / "template.html"
        template.write_text(
            '<html>__GENERATED_AT__ __DATA_JSON__</html>', encoding="utf-8"
        )
        dashboard = self.data_dir / "dashboard.html"

        with mock.patch.object(merge_module, "DATA_DIR", self.data_dir), mock.patch.object(
            merge_module, "DB_FILE", self.db_path
        ), mock.patch.object(merge_module, "TEMPLATE_FILE", template), mock.patch.object(
            merge_module, "DASHBOARD_FILE", dashboard
        ):
            buffer = io.StringIO()
            with mock.patch.object(sys, "argv", ["merge_interviews.py"]), mock.patch.object(
                sys, "stdout", buffer
            ):
                merge_module.main()

        self.assertTrue(dashboard.is_file())
        self.assertIn("Render Co", dashboard.read_text(encoding="utf-8"))
        self.assertIn("rendered:", buffer.getvalue())

    def test_main_merges_structured_extraction_and_watermark(self):
        merge_module = load_bin_module("merge_interviews")
        database.initialize_database(self.db_path)
        extraction = self.root / "extraction.json"
        extraction.write_text(
            json.dumps(
                {
                    "interviews": [
                        {
                            "thread_id": "watermark-thread",
                            "company": "Watermark Co",
                            "stage": "Initial Contact",
                            "status": "Active",
                        }
                    ],
                    "latest_email_date_seen": "2026-07-25T21:49:00Z",
                }
            ),
            encoding="utf-8",
        )
        template = self.root / "template.html"
        template.write_text("__GENERATED_AT__ __DATA_JSON__", encoding="utf-8")

        with mock.patch.object(merge_module, "DATA_DIR", self.data_dir), mock.patch.object(
            merge_module, "DB_FILE", self.db_path
        ), mock.patch.object(merge_module, "TEMPLATE_FILE", template), mock.patch.object(
            merge_module, "DASHBOARD_FILE", self.data_dir / "dashboard.html"
        ), mock.patch.object(
            sys, "argv", ["merge_interviews.py", str(extraction)]
        ):
            merge_module.main()

        self.assertEqual(len(database.get_records(self.db_path)), 1)
        self.assertEqual(
            database.get_latest_email_watermark(self.db_path),
            "2026-07-25T21:49:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
